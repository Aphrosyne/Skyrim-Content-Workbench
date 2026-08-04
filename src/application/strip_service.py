"""剥离服务（操作便捷性1，2026-08-04）。

把普通文件夹顶层内容提取到其上级目录（同级位置），并在文件夹清空后将其移入
回收站。UI 菜单名「提取内容」（用户确认 2026-08-04）。

约束：
- 仅限未标记为内容单元的普通文件夹（服务层前置校验 + 菜单可见性双重保证）。
- 空文件夹拒绝提取。
- 子项逐个通过 ``FileOperationService.move``（record_history=False）执行，
  自动同步 folder_cache / ContentUnit.path；冲突走 ConflictResolutionService
  决策（覆盖/跳过/重命名）。
- 文件夹清空后经 ``delete_to_recycle_bin`` 删除（可恢复，写 delete 历史）。
- 汇总写一条 ``operation_type='strip'`` 历史（can_undo=False——多子项移动 +
  空文件夹删除的组合操作无法安全单条撤销，与 copy/delete 一致）。

不自提交：DB 写操作与调用方共享连接，由 UI 层事务边界统一 commit/rollback
（与 perform_move_to 等既有流程一致）。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from application.conflict_resolution_service import (
    ConflictItem,
    ConflictResolutionService,
    ResolvedAction,
)
from application.content_service import ContentService
from application.errors import FileOperationError
from application.file_operation_service import FileOperationService
from domain.models import OperationHistory
from infrastructure.repositories.operation_history import OperationHistoryRepository

logger = logging.getLogger(__name__)


def _default_now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_uuid_provider() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class StripPlan:
    """剥离前置校验结果（prepare 返回，供 UI 确认与冲突决策）。"""

    folder: Path
    child_count: int
    conflicts: list[ConflictItem]


@dataclass
class StripResult:
    """剥离执行结果。"""

    folder: Path
    moved_count: int
    failure_count: int
    folder_removed: bool
    errors: list[str]


class StripService:
    """剥离（提取内容）服务。

    使用方式：
        service = StripService(file_op_service, content_service, history_repo)
        plan = service.prepare(Path("D:/Mods/Stash/Flat"))
        result = service.strip(Path("D:/Mods/Stash/Flat"), decisions)
    """

    def __init__(
        self,
        file_op_service: FileOperationService,
        content_service: ContentService,
        history_repo: OperationHistoryRepository,
        conflict_service: ConflictResolutionService | None = None,
        now_provider: Callable[[], str] | None = None,
        uuid_provider: Callable[[], str] | None = None,
    ) -> None:
        """初始化 StripService。

        Args:
            file_op_service: 文件操作服务（move / delete_to_recycle_bin）。
            content_service: 内容单元服务（剥离目标必须未标记）。
            history_repo: 操作历史仓储（写 strip 汇总记录）。
            conflict_service: 冲突扫描/解决服务（默认新建实例）。
            now_provider: 时间戳生成器（测试可注入）。
            uuid_provider: UUID 生成器（测试可注入）。
        """
        self._file_op = file_op_service
        self._content = content_service
        self._history_repo = history_repo
        self._conflict_service = conflict_service or ConflictResolutionService()
        self._now = now_provider or _default_now_utc
        self._new_uuid = uuid_provider or _default_uuid_provider

    def prepare(self, folder: Path) -> StripPlan:
        """前置校验 + 冲突扫描（不执行任何文件操作）。

        校验：路径存在且为目录、未标记为内容单元、非空。
        冲突定义：folder.parent 下已存在同名条目（复用冲突解决服务）。

        Raises:
            FileOperationError: 校验失败或路径不可访问。
        """
        try:
            if not folder.is_dir():
                raise FileOperationError(f"只能对文件夹执行提取内容：{folder}")
        except OSError as e:
            raise FileOperationError(f"无法访问路径：{folder}：{e}") from e

        if self._content.get_by_path(str(folder)) is not None:
            raise FileOperationError(f"已标记为内容单元的文件夹不能执行提取内容：{folder.name}")

        children = self._list_children(folder)
        if not children:
            raise FileOperationError(f"文件夹为空，无内容可提取：{folder.name}")

        conflicts = self._conflict_service.scan_conflicts(children, folder.parent, operation="cut")
        return StripPlan(folder=folder, child_count=len(children), conflicts=conflicts)

    def strip(self, folder: Path, decisions: list[str] | None = None) -> StripResult:
        """执行剥离：提取顶层条目到上级目录，清空后删除文件夹。

        Args:
            folder: 待剥离的普通文件夹（未标记内容单元、非空）。
            decisions: 与 prepare().conflicts 顺序一一对应的冲突决策
                （"overwrite" / "skip" / "rename"）。None 表示无冲突全部默认移动。

        Returns:
            StripResult：移动/失败计数、文件夹是否已删除、错误消息列表。

        Raises:
            FileOperationError: 前置校验失败（目录/标记/空），或决策数量不匹配。
        """
        plan = self.prepare(folder)
        if decisions is None:
            actions = [ResolvedAction(src=c.src, dst=c.default_dst) for c in plan.conflicts]
        else:
            if len(decisions) != len(plan.conflicts):
                raise FileOperationError(
                    f"决策数量与冲突数量不匹配：{len(decisions)} vs {len(plan.conflicts)}"
                )
            actions = self._conflict_service.resolve(plan.conflicts, decisions)

        moved_count = 0
        failure_count = 0
        errors: list[str] = []
        for action in actions:
            if action.skipped:
                continue
            try:
                self._file_op.move(
                    action.src,
                    action.dst,
                    overwrite=action.overwrite,
                    record_history=False,
                )
                moved_count += 1
            except (FileOperationError, OSError) as e:
                failure_count += 1
                errors.append(str(e))
                logger.warning("提取内容移动失败，跳过：%s：%s", action.src, e)

        # 全部移出且文件夹为空 → 移入回收站（可恢复，写 delete 历史）
        folder_removed = False
        if moved_count > 0 and self._is_empty(folder):
            try:
                _histories, sync_errors = self._file_op.delete_to_recycle_bin([folder])
                folder_removed = True
                errors.extend(sync_errors)
            except FileOperationError as e:
                errors.append(str(e))
                logger.warning("提取内容后删除空文件夹失败：%s：%s", folder, e)

        # 至少移动成功 1 项才写 strip 汇总历史（组合操作不可撤销）
        if moved_count > 0:
            self._write_strip_history(folder, errors)

        return StripResult(
            folder=folder,
            moved_count=moved_count,
            failure_count=failure_count,
            folder_removed=folder_removed,
            errors=errors,
        )

    def _list_children(self, folder: Path) -> list[Path]:
        """列出顶层条目（名称不区分大小写升序，保证执行顺序确定）。"""
        try:
            children = [p for p in folder.iterdir()]
        except OSError as e:
            raise FileOperationError(f"无法读取文件夹内容：{folder}：{e}") from e
        children.sort(key=lambda p: (p.name.lower(), p.name))
        return children

    def _is_empty(self, folder: Path) -> bool:
        """判断文件夹是否为空（不可访问时视为非空，避免误删）。"""
        try:
            return not any(folder.iterdir())
        except OSError as e:
            logger.warning("无法判断文件夹是否为空 %s: %s", folder, e)
            return False

    def _write_strip_history(self, folder: Path, errors: list[str]) -> None:
        """写一条 strip 汇总历史（can_undo=False）。失败仅记日志不阻塞。"""
        history = OperationHistory(
            id=self._new_uuid(),
            operation_type="strip",
            source_path=str(folder),
            target_path=str(folder.parent),
            created_at=self._now(),
            can_undo=False,
        )
        try:
            self._history_repo.create(history)
        except Exception as e:  # noqa: BLE001 - 历史写入失败不应掩盖文件操作结果
            logger.exception("写入 operation_history 失败（strip：%s）", folder)
            errors.append(f"写入操作历史失败：{e}")
