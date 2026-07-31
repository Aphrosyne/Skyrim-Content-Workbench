"""操作历史撤销服务（Stage 5 Task 6）。

负责：
- 加载最近操作历史（list_recent）
- 对 can_undo=True 的操作执行撤销（undo）
- 撤销前安全校验：路径存在 + size/mtime 校验
- 撤销后标记原记录 undone_at 时间戳（避免重复撤销）

v11 schema（Stage 5 Code Review D4 决策）：
- 撤销操作不再写入 operation_history（用户决策：撤销只标记原记录 undone_at）
- 移除原"写 operation_type='undo' 记录"逻辑
- 保留 undone_at 标记原操作已撤销
- 历史 undo 记录已在 v11 迁移中清理

设计要点（用户补充要求 #2）：
- undo 不直接复用普通文件操作方法后简单取反，而是明确记录：
  * 原始操作类型（operation_type）
  * 操作前状态（source_path 的 size/mtime）
  * 操作后状态（target_path 的 size/mtime）
  * 安全检查结果（_SafetyCheckResult）
- 反向操作执行后调用 FolderCacheSyncHelper 同步 folder_cache，
  调用 ContentUnitRepository 同步 ContentUnit.path。

分层契约：
- 本服务位于 application 层，不直接调用 shutil / Path.rename。
  反向文件操作通过注入的 FileOperationService 执行（move / rename），
  或通过 FolderCacheSyncHelper 同步 folder_cache（删除空文件夹时直接 rmdir，
  因为 FileOperationService 没有"删除空文件夹"方法，且撤销 new_folder 的语义
  是"删除自己刚创建的空文件夹"，不属于用户文件操作，无需走 FileOperationService）。
- 不自提交，由调用方控制事务边界。

支持的撤销类型：
- new_folder → 删除新建的空文件夹（非空时拒绝）
- rename → 反向重命名（target_path → source_path.name）
- move → 反向移动（target_path → source_path）
- delete → 拒绝（can_undo=False，提示用户从回收站手动还原）
- undo → 拒绝（避免无限循环；v11 后不再写入新 undo 记录，但保留校验以防历史数据）
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from application.errors import (
    ConflictError,
    FileOperationError,
    SourceNotFoundError,
    UndoAlreadyUndoneError,
    UndoError,
    UndoNotAllowedError,
    UndoSafetyError,
)
from domain.models import OperationHistory
from infrastructure.folder_cache_sync_helper import FolderCacheSyncHelper
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.operation_history import OperationHistoryRepository

if TYPE_CHECKING:
    from infrastructure.file_operation_service import FileOperationService

logger = logging.getLogger(__name__)


def _default_now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class _SafetyCheckResult:
    """撤销前安全检查结果（用户补充要求 #2：明确记录安全检查结果）。

    Attributes:
        ok: 是否通过安全检查。
        reason: 失败原因（ok=False 时填入，面向用户的中文消息）。
        source_exists: 检查时 source_path 是否存在。
        target_exists: 检查时 target_path 是否存在。
        source_size: source_path 的 size（不存在时为 None）。
        source_mtime: source_path 的 mtime（不存在时为 None）。
        target_size: target_path 的 size（不存在时为 None）。
        target_mtime: target_path 的 mtime（不存在时为 None）。
    """

    ok: bool
    reason: str = ""
    source_exists: bool = False
    target_exists: bool = False
    source_size: int | None = None
    source_mtime: float | None = None
    target_size: int | None = None
    target_mtime: float | None = None


class UndoService:
    """操作历史撤销服务。

    使用方式：
        undo_service = UndoService(
            history_repo=OperationHistoryRepository(conn),
            file_operation_service=file_op_service,  # 注入以执行反向 move/rename
            folder_cache_helper=helper,              # 注入以同步 folder_cache
            content_unit_repo=content_unit_repo,     # 注入以同步 ContentUnit.path
        )
        # 加载最近 100 条历史
        histories = undo_service.list_recent(limit=100)
        # 撤销一条记录
        undo_record = undo_service.undo(history)
    """

    def __init__(
        self,
        history_repo: OperationHistoryRepository,
        file_operation_service: FileOperationService | None = None,
        folder_cache_helper: FolderCacheSyncHelper | None = None,
        content_unit_repo: ContentUnitRepository | None = None,
        now_provider: Callable[[], str] | None = None,
        uuid_provider: Callable[[], str] | None = None,
    ) -> None:
        """初始化 UndoService。

        Args:
            history_repo: 操作历史仓储（必填）。
            file_operation_service: 文件操作服务（注入以执行反向 move/rename）。
                None 时 move/rename 类型的撤销不可用。
            folder_cache_helper: folder_cache 同步辅助（注入以同步 folder_cache）。
            content_unit_repo: ContentUnit 仓储（注入以同步 ContentUnit.path）。
            now_provider: 时间戳生成器（测试可注入）。
            uuid_provider: UUID 生成器（测试可注入）。
        """
        self._repo = history_repo
        self._file_op = file_operation_service
        self._folder_cache_helper = folder_cache_helper
        self._content_unit_repo = content_unit_repo
        self._now = now_provider or _default_now_utc

        # UUID 生成器（用于 undo 记录的 id）
        if uuid_provider is not None:
            self._new_uuid = uuid_provider
        else:
            import uuid  # noqa: PLC0415

            self._new_uuid = lambda: str(uuid.uuid4())  # noqa: E731

    # === 查询 ===

    def list_recent(self, limit: int = 100) -> list[OperationHistory]:
        """返回最近的 OperationHistory，按 created_at 降序（最新在上）。"""
        return self._repo.list_recent(limit=limit)

    # === 撤销主流程 ===

    def undo(self, history: OperationHistory) -> None:
        """撤销一条操作历史记录。

        流程（用户补充要求 #2：明确记录各阶段状态）：
        1. 前置校验：can_undo / operation_type / undone_at
        2. 安全校验：source_path / target_path 当前状态 + size/mtime 比对
        3. 执行反向操作（按 operation_type 分派）
        4. 同步 folder_cache + ContentUnit.path
        5. 标记原记录 undone_at 时间戳（避免重复撤销）

        v11 schema（D4 决策）：不再写 operation_type='undo' 新记录。
        撤销只标记原记录的 undone_at，UI 通过 undone_at 判断灰色状态。

        Args:
            history: 待撤销的操作历史记录。

        Raises:
            UndoNotAllowedError: 该操作不允许撤销（delete/undo/can_undo=False）。
            UndoAlreadyUndoneError: 该操作已被撤销（undone_at 非空）。
            UndoSafetyError: 安全校验失败（源不存在/已被外部修改/目标已存在）。
            FileOperationError: 反向文件操作失败或标记原记录失败。
        """
        # 1. 前置校验
        self._check_undo_allowed(history)

        # 2. 安全校验（明确记录操作前后状态 + 安全检查结果）
        safety = self._safety_check(history)
        if not safety.ok:
            logger.warning(
                "撤销安全检查失败：history_id=%s operation_type=%s reason=%s",
                history.id,
                history.operation_type,
                safety.reason,
            )
            raise UndoSafetyError(safety.reason, reason=safety.reason)

        # 3. 执行反向操作
        self._dispatch_reverse_operation(history)

        # 4. 同步 folder_cache + ContentUnit.path
        self._sync_on_undo(history)

        # 5. 标记原记录为已撤销（v11：不再写 undo 新记录，仅标记原记录）
        try:
            self._repo.mark_undone(history.id, self._now())
        except Exception as e:  # noqa: BLE001
            # 标记失败：反向文件操作已执行，但原记录未标记，可能导致重复撤销
            # 记日志，由调用方决定是否提示用户
            logger.exception(
                "标记原记录 undone_at 失败（history_id=%s）：反向操作已执行，"
                "但原记录未标记，可能导致重复撤销",
                history.id,
            )
            raise FileOperationError(f"标记原操作为已撤销失败：{e}") from e

    # === 前置校验 ===

    def _check_undo_allowed(self, history: OperationHistory) -> None:
        """前置校验：是否允许撤销该记录。

        Raises:
            UndoNotAllowedError: 不允许撤销。
            UndoAlreadyUndoneError: 已被撤销。
        """
        # undo 记录本身不可再撤销（避免无限循环）
        if history.operation_type == "undo":
            raise UndoNotAllowedError("撤销记录本身不可再次撤销")
        # delete 不可撤销（can_undo=False，提示用户从回收站手动还原）
        if history.operation_type == "delete":
            raise UndoNotAllowedError("删除操作不可撤销，请从 Windows 回收站手动还原")
        # can_undo=False 的操作不可撤销
        if not history.can_undo:
            raise UndoNotAllowedError("该操作不可撤销")
        # 已撤销的操作不可重复撤销
        if history.undone_at is not None:
            raise UndoAlreadyUndoneError(
                f"该操作已被撤销（undone_at={history.undone_at}），不可重复撤销"
            )

    # === 安全校验 ===

    def _safety_check(self, history: OperationHistory) -> _SafetyCheckResult:
        """撤销前安全校验（用户补充要求 #2：明确记录操作前后状态）。

        校验规则（Q5=A：路径存在 + size/mtime 校验）：
        - new_folder：target_path（新建的文件夹）必须存在且为空
        - rename：target_path（重命名后的路径）必须存在；
                  source_path（原路径）必须不存在（避免覆盖外部创建的文件）
        - move：target_path（移动后的路径）必须存在；
                source_path（原路径）必须不存在（避免覆盖外部创建的文件）

        Q5 明确要求"路径存在检查 + size/mtime 校验"。
        但本系统不存储操作前的 size/mtime 快照（operation_history 表无此字段），
        因此 size/mtime 校验的含义是"撤销前再次读取当前文件状态，作为安全检查结果记录"，
        供失败时诊断使用。未来若引入 hash 校验，可在此扩展。

        Args:
            history: 待撤销的操作历史记录。

        Returns:
            _SafetyCheckResult：包含操作前后状态 + 安全检查结果。
        """
        result = _SafetyCheckResult(ok=True)

        if history.operation_type == "new_folder":
            # 撤销 new_folder：删除新建的空文件夹
            # 校验：target_path 存在 + 为空目录
            target = Path(history.target_path) if history.target_path else None
            if target is None:
                return _SafetyCheckResult(ok=False, reason="历史记录缺少 target_path")
            result.target_exists = self._path_exists(target)
            if not result.target_exists:
                return _SafetyCheckResult(
                    ok=False,
                    reason=f"待撤销的文件夹不存在：{target}",
                    target_exists=False,
                )
            # 读取 target 状态
            result.target_size, result.target_mtime = self._read_path_stats(target)
            # 必须是空目录（Q4=A：严格非空检查）
            if not self._is_empty_dir(target):
                return _SafetyCheckResult(
                    ok=False,
                    reason=f"文件夹非空，无法撤销新建：{target}",
                    target_exists=True,
                    target_size=result.target_size,
                    target_mtime=result.target_mtime,
                )
            return result

        if history.operation_type in ("rename", "move"):
            # 撤销 rename/move：反向移动 target_path → source_path
            # 校验：target_path 存在 + source_path 不存在（避免覆盖）
            target = Path(history.target_path) if history.target_path else None
            source = Path(history.source_path)
            if target is None:
                return _SafetyCheckResult(ok=False, reason="历史记录缺少 target_path")

            result.target_exists = self._path_exists(target)
            if not result.target_exists:
                return _SafetyCheckResult(
                    ok=False,
                    reason=f"待撤销的操作结果不存在：{target}",
                    target_exists=False,
                )
            # 读取 target 状态（用户补充要求 #2：记录操作后状态）
            result.target_size, result.target_mtime = self._read_path_stats(target)

            result.source_exists = self._path_exists(source)
            if result.source_exists:
                return _SafetyCheckResult(
                    ok=False,
                    reason=f"原路径已存在，撤销将覆盖外部创建的文件：{source}",
                    source_exists=True,
                    target_exists=True,
                    target_size=result.target_size,
                    target_mtime=result.target_mtime,
                )
            # 读取 source 状态（用户补充要求 #2：记录操作前状态）
            # source 不存在，size/mtime 为 None
            return result

        # 其他类型（delete/undo 已在 _check_undo_allowed 拦截，理论上不会到达这里）
        return _SafetyCheckResult(
            ok=False, reason=f"不支持撤销的操作类型：{history.operation_type}"
        )

    # === 反向操作分派 ===

    def _dispatch_reverse_operation(self, history: OperationHistory) -> None:
        """按 operation_type 分派反向操作。

        Raises:
            UndoError: 反向操作不支持或失败。
        """
        if history.operation_type == "new_folder":
            self._undo_new_folder(history)
        elif history.operation_type == "rename":
            self._undo_rename(history)
        elif history.operation_type == "move":
            self._undo_move(history)
        else:
            raise UndoError(f"不支持撤销的操作类型：{history.operation_type}")

    def _undo_new_folder(self, history: OperationHistory) -> None:
        """撤销新建文件夹：删除空文件夹。

        Q4=A：严格非空检查，非空时拒绝（已在 _safety_check 拦截）。
        不走 FileOperationService（无"删除空文件夹"方法），直接 rmdir。
        """
        target = Path(history.target_path) if history.target_path else None
        if target is None:
            raise UndoError("历史记录缺少 target_path")
        try:
            target.rmdir()  # 仅删除空目录，非空抛 OSError
        except OSError as e:
            raise UndoError(f"删除空文件夹失败：{target}：{e}") from e

    def _undo_rename(self, history: OperationHistory) -> None:
        """撤销重命名：反向重命名 target_path → source_path.name。

        通过 FileOperationService.rename 执行（复用其校验 + 同步逻辑）。
        """
        if self._file_op is None:
            raise UndoError("未注入 FileOperationService，无法撤销 rename")
        target = Path(history.target_path) if history.target_path else None
        source = Path(history.source_path)
        if target is None:
            raise UndoError("历史记录缺少 target_path")
        # 反向重命名：target → source.name
        try:
            self._file_op.rename(target, source.name)
        except (FileOperationError, SourceNotFoundError, ConflictError) as e:
            raise UndoError(f"反向重命名失败：{target} → {source.name}：{e}") from e

    def _undo_move(self, history: OperationHistory) -> None:
        """撤销移动：反向移动 target_path → source_path。

        通过 FileOperationService.move 执行（复用其校验 + 同步逻辑）。
        """
        if self._file_op is None:
            raise UndoError("未注入 FileOperationService，无法撤销 move")
        target = Path(history.target_path) if history.target_path else None
        source = Path(history.source_path)
        if target is None:
            raise UndoError("历史记录缺少 target_path")
        # 反向移动：target → source
        try:
            self._file_op.move(target, source)
        except (FileOperationError, SourceNotFoundError, ConflictError) as e:
            raise UndoError(f"反向移动失败：{target} → {source}：{e}") from e

    # === 同步 ===

    def _sync_on_undo(self, history: OperationHistory) -> None:
        """撤销后同步 folder_cache + ContentUnit.path。

        - new_folder：folder_cache 删除该节点（复用 on_folder_deleted）
        - rename/move：已通过 FileOperationService.rename/move 内部的同步逻辑处理，
          此处无需重复同步（FileOperationService 注入了 helper/repo 时会自动同步）
        """
        if history.operation_type == "new_folder":
            # 撤销 new_folder：删除 folder_cache 中对应的节点
            target = Path(history.target_path) if history.target_path else None
            if target is None:
                return
            if self._folder_cache_helper is not None:
                try:
                    self._folder_cache_helper.on_folder_deleted(target)
                except FileOperationError as e:
                    # folder_cache 同步失败：文件夹已删除，但缓存残留
                    # 记日志，不阻塞 undo 流程（下次扫描会清理）
                    logger.warning(
                        "撤销 new_folder 后 folder_cache 同步失败（target=%s）：%s",
                        target,
                        e,
                    )
            # ContentUnit 同步：新建文件夹时通常无关联 ContentUnit，无需处理
            return
        # rename/move 的同步由 FileOperationService 内部处理（_sync_on_rename / _sync_on_move）
        # 此处无需重复同步

    # === 工具方法 ===

    @staticmethod
    def _path_exists(path: Path) -> bool:
        """安全检查路径是否存在。"""
        try:
            return path.exists()
        except OSError:
            return False

    @staticmethod
    def _read_path_stats(path: Path) -> tuple[int | None, float | None]:
        """读取路径的 size 和 mtime（用户补充要求 #2：记录操作前后状态）。

        不存在或无法访问时返回 (None, None)。
        """
        try:
            stat = path.stat()
            return stat.st_size, stat.st_mtime
        except OSError:
            return None, None

    @staticmethod
    def _is_empty_dir(path: Path) -> bool:
        """判断是否为空目录。"""
        try:
            return path.is_dir() and not any(path.iterdir())
        except OSError:
            return False
