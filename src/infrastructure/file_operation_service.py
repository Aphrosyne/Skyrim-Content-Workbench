"""统一文件操作服务。

依据 docs/roadmap.md Task 5。
依据 docs/architecture.md §6：本服务是唯一允许修改用户文件位置的模块。
依据 docs/spec.md §7：文件操作安全要求。
依据已确认决策 B1（撤销不安全时阻止）、B2（跨盘撤销校验 size+mtime）、
B3（conflict_policy 仅 ask，重名即阻止）。

约束：
- 所有文件修改仅通过本服务；UI 层不直接调用 shutil / Path.rename。
- 执行前必须生成预演并持久化为 OperationLog(status=planned)。
- 用户确认后才执行（execute_move）。
- 重名即阻止（B3）。
- 禁止把文件夹移动到其自身或子目录。
- 同盘优先 Path.rename（原子）；跨盘 shutil.copy2 + Path.unlink。
- 单成员失败不中断其他成员；部分失败时 OperationLog=failed。
- 撤销前必须验证当前文件状态（B1）；跨盘撤销校验 size+mtime（B2）。
- 不删除用户文件（spec §7.13）。
- 不修改文件内容（spec §7.14）。

undo_payload 结构（Q14，由本任务定义）：
{
  "version": 1,
  "members": [
    {
      "asset_id": "...",
      "src_path": "原源路径",
      "dst_path": "原目标路径",
      "size_bytes": 100,
      "mtime_iso": "2026-07-07T00:00:00Z"
    }
  ]
}
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from domain.models import (
    ConflictPolicy,
    FileAsset,
    OperationLog,
    OperationStatus,
    OperationType,
)
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.file_asset import FileAssetRepository
from infrastructure.repositories.folder_node import FolderNodeRepository
from infrastructure.repositories.mod_item import ModItemRepository
from infrastructure.repositories.operation_log import OperationLogRepository

logger = logging.getLogger(__name__)


def _default_now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_uuid_provider() -> str:
    return str(uuid.uuid4())


def _mtime_to_iso(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# undo_payload JSON 的版本号。结构变化时递增。
UNDO_PAYLOAD_VERSION = 1


@dataclass
class MovePlanEntry:
    """单个成员的移动预演条目。spec §7.4 / architecture §6。"""

    asset_id: str
    source_path: str
    target_path: str
    is_cross_drive: bool
    source_exists: bool
    target_exists: bool
    target_dir_exists: bool
    target_writable: bool
    is_self_or_subdir: bool  # 目标是否为源自身或子目录（非法，spec §7.7）
    block_reason: str | None
    can_execute: bool


@dataclass
class MovePlan:
    """ModItem 移动预演。"""

    plan_id: str  # = OperationLog.id
    mod_item_id: str
    target_folder_id: str
    target_folder_path: str
    entries: list[MovePlanEntry] = field(default_factory=list)
    can_execute: bool = False
    conflict_policy: ConflictPolicy = ConflictPolicy.ASK
    created_at: str = ""


@dataclass
class UndoPlanEntry:
    """单个成员的撤销预演条目。B1/B2 校验结果。"""

    asset_id: str
    source_path: str  # 原目标路径（撤销时的源）
    target_path: str  # 原源路径（撤销时的目标）
    is_cross_drive: bool
    source_exists: bool  # 原目标文件是否存在
    target_exists: bool  # 原源路径是否已存在
    size_matches: bool  # B2：size 是否与记录一致
    mtime_matches: bool  # B2：mtime 是否与记录一致
    block_reason: str | None
    can_execute: bool


@dataclass
class UndoPlan:
    """撤销预演。B1：不安全时 can_execute=False。"""

    operation_id: str  # 原移动 OperationLog.id
    entries: list[UndoPlanEntry] = field(default_factory=list)
    can_execute: bool = False
    block_reason: str | None = None
    created_at: str = ""


@dataclass
class OperationResult:
    """execute_move / execute_undo 的返回。"""

    operation_id: str
    success: bool
    partial: bool
    moved_assets: list[str] = field(default_factory=list)
    failed_assets: list[str] = field(default_factory=list)
    error_messages: list[str] = field(default_factory=list)


class FileOperationService:
    """统一文件操作服务。唯一允许修改用户文件位置的模块。

    使用方式：
        service = FileOperationService(mod_repo, file_repo, folder_repo, op_repo)
        plan = service.plan_move(mod_item_id, target_folder_id)
        # 用户确认后：
        result = service.execute_move(plan.plan_id)
        # 撤销：
        undo_plan = service.plan_undo(result.operation_id)
        if undo_plan.can_execute:
            service.execute_undo(undo_plan.operation_id)
    """

    def __init__(
        self,
        mod_item_repo: ModItemRepository,
        file_asset_repo: FileAssetRepository,
        folder_node_repo: FolderNodeRepository,
        operation_log_repo: OperationLogRepository,
        now_provider: Callable[[], str] | None = None,
        uuid_provider: Callable[[], str] | None = None,
    ) -> None:
        self._mod_repo = mod_item_repo
        self._file_repo = file_asset_repo
        self._folder_repo = folder_node_repo
        self._op_repo = operation_log_repo
        self._now = now_provider or _default_now_utc
        self._new_uuid = uuid_provider or _default_uuid_provider

    # --- 移动预演 ---

    def plan_move(self, mod_item_id: str, target_folder_id: str) -> MovePlan:
        """生成移动预演并持久化为 OperationLog(status=planned)。

        依据 spec §7.3-§7.9 检查每个成员。
        B3：重名即阻止。
        spec §7.7：禁止移到自身或子目录。
        """
        # 验证 ModItem 存在
        mod_item = self._mod_repo.get_by_id(mod_item_id)
        if mod_item is None:
            raise ValueError(f"ModItem 不存在：{mod_item_id}")

        # 验证目标 FolderNode 存在
        target_folder = self._folder_repo.get_by_id(target_folder_id)
        if target_folder is None:
            raise ValueError(f"目标 FolderNode 不存在：{target_folder_id}")

        target_path = Path(target_folder.real_path)
        members = self._file_repo.list_by_mod_item(mod_item_id)

        entries: list[MovePlanEntry] = []
        for asset in members:
            entry = self._plan_entry_for(asset, target_path)
            entries.append(entry)

        can_execute = all(e.can_execute for e in entries) if entries else False
        now = self._now()
        plan_id = self._new_uuid()

        # 持久化为 OperationLog(planned)
        source_paths = [e.source_path for e in entries]
        target_paths = [e.target_path for e in entries]
        affected = [e.asset_id for e in entries]

        op_log = OperationLog(
            id=plan_id,
            operation_type=OperationType.MOVE,
            status=OperationStatus.PLANNED,
            conflict_policy=ConflictPolicy.ASK,
            created_at=now,
            affected_asset_ids=affected,
            source_paths=source_paths,
            target_paths=target_paths,
            completed_at=None,
            undo_payload=None,
            error_message=None,
        )
        self._op_repo.create(op_log)

        return MovePlan(
            plan_id=plan_id,
            mod_item_id=mod_item_id,
            target_folder_id=target_folder_id,
            target_folder_path=str(target_path),
            entries=entries,
            can_execute=can_execute,
            conflict_policy=ConflictPolicy.ASK,
            created_at=now,
        )

    def _plan_entry_for(self, asset: FileAsset, target_dir: Path) -> MovePlanEntry:
        """为单个成员生成预演条目。"""
        source = Path(asset.real_path)
        target = target_dir / asset.filename

        # 跨盘检查
        is_cross_drive = self._is_cross_drive(source, target_dir)

        # 源存在性
        source_exists = source.exists()

        # 目标目录存在性
        target_dir_exists = target_dir.is_dir()

        # 目标重名（B3：重名即阻止）
        target_exists = target.exists()

        # 目标目录可写性
        target_writable = os.access(target_dir, os.W_OK) if target_dir_exists else False

        # 子目录非法性（spec §7.7）
        is_self_or_subdir = self._is_self_or_subdir(source, target_dir)

        # 综合阻止原因
        block_reason = self._determine_block_reason(
            source_exists=source_exists,
            target_exists=target_exists,
            target_dir_exists=target_dir_exists,
            target_writable=target_writable,
            is_self_or_subdir=is_self_or_subdir,
        )

        return MovePlanEntry(
            asset_id=asset.id,
            source_path=str(source),
            target_path=str(target),
            is_cross_drive=is_cross_drive,
            source_exists=source_exists,
            target_exists=target_exists,
            target_dir_exists=target_dir_exists,
            target_writable=target_writable,
            is_self_or_subdir=is_self_or_subdir,
            block_reason=block_reason,
            can_execute=block_reason is None,
        )

    def _determine_block_reason(
        self,
        source_exists: bool,
        target_exists: bool,
        target_dir_exists: bool,
        target_writable: bool,
        is_self_or_subdir: bool,
    ) -> str | None:
        """综合判断阻止原因。返回 None 表示可执行。"""
        if is_self_or_subdir:
            return "目标目录是源文件自身或其子目录，禁止移动（spec §7.7）"
        if not source_exists:
            return "源文件不存在"
        if not target_dir_exists:
            return "目标目录不存在"
        if target_exists:
            return "目标路径已存在重名文件（B3：重名即阻止，不覆盖）"
        if not target_writable:
            return "目标目录不可写"
        return None

    def _is_cross_drive(self, path_a: Path, path_b: Path) -> bool:
        """判断两路径是否跨盘。无法 stat 时返回 False（保守）。"""
        try:
            return (
                path_a.stat(follow_symlinks=False).st_dev
                != path_b.stat(follow_symlinks=False).st_dev
            )
        except OSError:
            # 源不存在时无法 stat；用盘符比较作为回退（Windows）
            drive_a = os.path.splitdrive(str(path_a))[0]
            drive_b = os.path.splitdrive(str(path_b))[0]
            if drive_a and drive_b:
                return drive_a.lower() != drive_b.lower()
            return False

    def _is_self_or_subdir(self, source: Path, target_dir: Path) -> bool:
        """判断 target_dir 是否为 source 自身或 source 的子目录。

        依据 A2：用 path_key（normcase+normpath）比较，避免大小写差异。
        spec §7.7：禁止把文件夹移动到其自身或子目录。
        """
        try:
            source_key = make_path_key(source)
            target_key = make_path_key(target_dir)
            # target 是 source 自身，或 target 是 source 的子目录
            return target_key == source_key or target_key.startswith(source_key + os.sep)
        except (OSError, ValueError):
            return False

    # --- 执行移动 ---

    def execute_move(self, plan_id: str) -> OperationResult:
        """执行移动预演。

        依据 spec §7.8/§7.9：同盘 Path.rename；跨盘 copy2+unlink。
        依据 spec §7.12：单成员失败不中断其他成员。
        """
        op_log = self._op_repo.get_by_id(plan_id)
        if op_log is None:
            raise ValueError(f"OperationLog 不存在：{plan_id}")

        if op_log.status != OperationStatus.PLANNED:
            raise ValueError(f"OperationLog 状态非 planned，无法执行：{op_log.status.value}")

        # 重新生成预演以获取最新状态（避免预演后文件状态变化）
        # 注意：plan_id 即 OperationLog.id；这里不重新预演，
        # 而是从 OperationLog 读取 source/target 路径并直接执行。
        # 预演阶段已检查；执行阶段若发现文件状态变化，记为该成员失败。

        # 更新状态为 confirmed
        op_log.status = OperationStatus.CONFIRMED
        self._op_repo.update(op_log)

        moved_assets: list[str] = []
        failed_assets: list[str] = []
        error_messages: list[str] = []
        undo_members: list[dict[str, object]] = []

        for i, asset_id in enumerate(op_log.affected_asset_ids):
            source_str = op_log.source_paths[i]
            target_str = op_log.target_paths[i]
            source = Path(source_str)
            target = Path(target_str)

            asset = self._file_repo.get_by_id(asset_id)
            if asset is None:
                failed_assets.append(asset_id)
                error_messages.append(f"FileAsset 不存在：{asset_id}")
                continue

            try:
                # 执行前再次检查（文件状态可能已变化）
                if not source.exists():
                    raise OSError(f"源文件不存在：{source}")
                if target.exists():
                    raise OSError(f"目标已存在重名文件：{target}")

                # 记录 size/mtime 用于 undo（B2）
                stat = source.stat(follow_symlinks=False)

                # 执行移动
                self._move_file(source, target)

                # 更新 FileAsset
                asset.real_path = str(target)
                asset.path_key = make_path_key(target)
                asset.modified_at = _mtime_to_iso(stat.st_mtime)
                self._file_repo.update(asset)

                moved_assets.append(asset_id)
                undo_members.append(
                    {
                        "asset_id": asset_id,
                        "src_path": source_str,
                        "dst_path": target_str,
                        "size_bytes": stat.st_size,
                        "mtime_iso": _mtime_to_iso(stat.st_mtime),
                    }
                )
            except OSError as e:
                failed_assets.append(asset_id)
                error_messages.append(str(e))
                logger.warning("移动成员失败 %s: %s", asset_id, e)

        # 更新 OperationLog
        success = len(failed_assets) == 0
        partial = len(moved_assets) > 0 and len(failed_assets) > 0
        op_log.status = OperationStatus.COMPLETED if success else OperationStatus.FAILED
        op_log.completed_at = self._now()
        if undo_members:
            op_log.undo_payload = json.dumps(
                {
                    "version": UNDO_PAYLOAD_VERSION,
                    "members": undo_members,
                },
                ensure_ascii=False,
            )
        if failed_assets:
            op_log.error_message = "; ".join(error_messages)
        self._op_repo.update(op_log)

        return OperationResult(
            operation_id=plan_id,
            success=success,
            partial=partial,
            moved_assets=moved_assets,
            failed_assets=failed_assets,
            error_messages=error_messages,
        )

    def _move_file(self, source: Path, target: Path) -> None:
        """执行单文件移动。同盘 rename；跨盘 copy2+unlink。

        spec §7.8：同盘优先原子移动。
        spec §7.9：跨盘复制后删除。
        """
        is_cross = self._is_cross_drive(source, target.parent)
        if not is_cross:
            # 同盘：原子 rename
            source.rename(target)
        else:
            # 跨盘：copy2 + unlink
            shutil.copy2(source, target)
            source.unlink()

    # --- 撤销预演 ---

    def plan_undo(self, operation_id: str) -> UndoPlan:
        """生成撤销预演。

        B1：检查每个成员当前状态；不安全时 can_execute=False。
        B2：跨盘撤销校验 size+mtime。
        """
        op_log = self._op_repo.get_by_id(operation_id)
        if op_log is None:
            raise ValueError(f"OperationLog 不存在：{operation_id}")

        if op_log.status not in (OperationStatus.COMPLETED, OperationStatus.FAILED):
            return UndoPlan(
                operation_id=operation_id,
                entries=[],
                can_execute=False,
                block_reason=f"原操作状态非 completed/failed，无法撤销：{op_log.status.value}",
                created_at=self._now(),
            )

        if not op_log.undo_payload:
            return UndoPlan(
                operation_id=operation_id,
                entries=[],
                can_execute=False,
                block_reason="原操作无 undo_payload，无法撤销",
                created_at=self._now(),
            )

        try:
            payload = json.loads(op_log.undo_payload)
        except json.JSONDecodeError as e:
            return UndoPlan(
                operation_id=operation_id,
                entries=[],
                can_execute=False,
                block_reason=f"undo_payload 解析失败：{e}",
                created_at=self._now(),
            )

        members = payload.get("members", [])
        entries: list[UndoPlanEntry] = []

        for member in members:
            entry = self._plan_undo_entry(member)
            entries.append(entry)

        # B1：任何成员不安全 → 整体阻止
        can_execute = all(e.can_execute for e in entries) if entries else False
        block_reason = None if can_execute else "部分成员撤销不安全（B1）：见各 entry.block_reason"

        return UndoPlan(
            operation_id=operation_id,
            entries=entries,
            can_execute=can_execute,
            block_reason=block_reason,
            created_at=self._now(),
        )

    def _plan_undo_entry(self, member: dict[str, object]) -> UndoPlanEntry:
        """为单个成员生成撤销预演条目。B1/B2 校验。"""
        asset_id = str(member["asset_id"])
        src_path = str(member["src_path"])  # 原源路径（撤销目标）
        dst_path = str(member["dst_path"])  # 原目标路径（撤销源）
        recorded_size = int(member["size_bytes"])
        recorded_mtime = str(member["mtime_iso"])

        source = Path(dst_path)  # 撤销时的源
        target = Path(src_path)  # 撤销时的目标

        source_exists = source.exists()
        target_exists = target.exists()
        is_cross_drive = self._is_cross_drive(source, target.parent)

        # B2：校验 size+mtime
        size_matches = False
        mtime_matches = False
        if source_exists:
            stat = source.stat(follow_symlinks=False)
            size_matches = stat.st_size == recorded_size
            actual_mtime = _mtime_to_iso(stat.st_mtime)
            mtime_matches = actual_mtime == recorded_mtime

        # 综合阻止原因
        block_reason: str | None = None
        if not source_exists:
            block_reason = "原目标文件不存在，无法撤销"
        elif target_exists:
            block_reason = "原源路径已存在文件，撤销将覆盖（B1 阻止）"
        elif not size_matches:
            block_reason = f"文件大小与记录不一致（B2）：记录 {recorded_size}，实际不同"
        elif not mtime_matches:
            block_reason = f"修改时间与记录不一致（B2）：记录 {recorded_mtime}，实际不同"

        return UndoPlanEntry(
            asset_id=asset_id,
            source_path=str(source),
            target_path=str(target),
            is_cross_drive=is_cross_drive,
            source_exists=source_exists,
            target_exists=target_exists,
            size_matches=size_matches,
            mtime_matches=mtime_matches,
            block_reason=block_reason,
            can_execute=block_reason is None,
        )

    # --- 执行撤销 ---

    def execute_undo(self, undo_plan_id: str) -> OperationResult:
        """执行撤销。

        仅当 UndoPlan.can_execute 为 True 时执行。
        撤销方向：原目标 → 原源。
        """
        # UndoPlan 不持久化为独立 OperationLog；通过原 operation_id 获取
        op_log = self._op_repo.get_by_id(undo_plan_id)
        if op_log is None:
            raise ValueError(f"OperationLog 不存在：{undo_plan_id}")

        # 重新生成 undo plan 以验证安全性（B1）
        undo_plan = self.plan_undo(undo_plan_id)
        if not undo_plan.can_execute:
            return OperationResult(
                operation_id=undo_plan_id,
                success=False,
                partial=False,
                moved_assets=[],
                failed_assets=[e.asset_id for e in undo_plan.entries],
                error_messages=[f"撤销不安全（B1）：{undo_plan.block_reason}"],
            )

        moved_assets: list[str] = []
        failed_assets: list[str] = []
        error_messages: list[str] = []

        for entry in undo_plan.entries:
            source = Path(entry.source_path)
            target = Path(entry.target_path)

            asset = self._file_repo.get_by_id(entry.asset_id)
            if asset is None:
                failed_assets.append(entry.asset_id)
                error_messages.append(f"FileAsset 不存在：{entry.asset_id}")
                continue

            try:
                self._move_file(source, target)
                asset.real_path = str(target)
                asset.path_key = make_path_key(target)
                stat = target.stat(follow_symlinks=False)
                asset.modified_at = _mtime_to_iso(stat.st_mtime)
                self._file_repo.update(asset)
                moved_assets.append(entry.asset_id)
            except OSError as e:
                failed_assets.append(entry.asset_id)
                error_messages.append(str(e))
                logger.warning("撤销成员失败 %s: %s", entry.asset_id, e)

        success = len(failed_assets) == 0
        if success:
            op_log.status = OperationStatus.UNDONE
            op_log.completed_at = self._now()
            self._op_repo.update(op_log)

        return OperationResult(
            operation_id=undo_plan_id,
            success=success,
            partial=len(moved_assets) > 0 and len(failed_assets) > 0,
            moved_assets=moved_assets,
            failed_assets=failed_assets,
            error_messages=error_messages,
        )
