"""快速插入服务（阶段 3 Task 5）。

整理模式下，将当前装配面板绑定的 Mod 组文件夹整体移动到目录树中选中的目标分类目录。

工作流（2026-07-17 修复事务边界与 UNIQUE 冲突根因后）：
1. 查询 Mod 组 ContentUnit。
2. 目标路径 = target_dir / mod_folder.name。
3. **先清理**目标路径下的旧 ContentUnit 记录（避免 update 时 UNIQUE 冲突）。
   清理在 move 之前，此时文件系统状态干净，若清理失败可安全 rollback。
   使用 ContentUnitRepository.list_by_path_prefix_normalized（TD-H7 修复：
   原 list_by_path_prefix 在 Windows 反斜杠路径下 broken）。
4. 调用 FileOperationService.move 执行移动（含跨盘/子目录/冲突检测）。
5. 更新 ContentUnit.path 指向新路径。
6. 同步 folder_cache（与 ModGroupService 模式一致）：
   a. 删除旧路径的 folder_cache 记录。
   b. 在目标目录下插入新路径的 folder_cache 记录（path=新路径, parent_id=目标目录的 id）。
   c. 更新目标目录的 last_scanned_mtime（让下次扫描知道该目录变了）。
   d. 任一步失败立即抛出异常，由上层 rollback 保证事务一致性（H2 修复）。

顺序设计原理（避免死循环）：
- 旧顺序 move → cleanup → update：若 update 失败，rollback 会回滚 cleanup 的 delete，
  旧记录"复活"，下次重试 update 仍会 UNIQUE 冲突 → 死循环。
- 新顺序 cleanup → move → update：cleanup 在 move 之前，update 时数据库已无冲突记录，
  不会 UNIQUE 冲突。若 move 失败，rollback 回滚 cleanup，旧记录复活但文件未移动，
  下次重试可正常清理。若 update 失败（非 UNIQUE 原因），文件已移动但数据库回滚，
  状态不一致但不会死循环（下次重试 move 会因源不存在而失败，提示用户手动修复）。

安全规则（spec §6.1）：
- 跨盘移动：FileOperationService.move 抛 CrossDriveError。
- 子目录阻止：FileOperationService.move 抛 SelfSubdirectoryError。
- 重名冲突：FileOperationService.move 抛 ConflictError（不覆盖，AGENTS 规则 2）。
- operation_history 由 FileOperationService.move 写入。

约束（AGENTS 规则）：
- 文件操作通过 FileOperationService，本服务不直接调用 shutil / Path.rename。
- 不自提交，由调用方控制事务边界。
- 路径比较统一使用 make_path_key()（AGENTS 规则 9）。

目录树刷新统一机制（2026-07-17 用户验收后修复）：
- 所有涉及真实文件夹移动/创建/删除的服务（ModGroupService / QuickInsertService）
  负责同步 folder_cache（删除旧节点 + 插入新节点 + 更新父目录 mtime）。
- UI 层（MainWindow）在操作完成后只需调用一次 _refresh_tree() 即可立即刷新目录树，
  无需依赖扫描。
- AssemblyService.add_file / remove_file 移动的是文件（非文件夹），folder_cache
  只记录目录，因此只需更新 Mod 组文件夹的 mtime（已正确实现）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from application.errors import ContentUnitNotFoundError, FileOperationError
from domain.models import ContentUnit, FolderCache
from infrastructure.file_operation_service import FileOperationService
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.folder_cache import FolderCacheRepository

logger = logging.getLogger(__name__)


class QuickInsertService:
    """快速插入服务：Mod 组文件夹整体移动到目标分类目录。

    使用方式：
        service = QuickInsertService(file_op_service, content_repo, folder_cache_repo)
        service.quick_insert(unit_id, Path("D:/Mods/Armor"))
    """

    def __init__(
        self,
        file_op_service: FileOperationService,
        content_unit_repo: ContentUnitRepository,
        folder_cache_repo: FolderCacheRepository | None = None,
    ) -> None:
        self._file_op = file_op_service
        self._content_repo = content_unit_repo
        self._folder_cache_repo = folder_cache_repo

    def quick_insert(self, unit_id: str, target_dir: Path) -> ContentUnit:
        """将 Mod 组文件夹整体移动到目标分类目录。

        操作顺序（2026-07-17 修复，避免 UNIQUE 冲突死循环）：
        1. cleanup：清理目标路径下的旧 ContentUnit 记录
        2. move：移动文件（含 operation_history）
        3. update：更新 ContentUnit.path
        4. sync：同步 folder_cache

        Args:
            unit_id: Mod 组 ContentUnit ID（必须指向文件夹）。
            target_dir: 目标分类目录路径（必须存在）。

        Returns:
            更新后的 ContentUnit（path 指向新路径）。

        Raises:
            ContentUnitNotFoundError: unit_id 不存在。
            ConflictError: 目标已存在同名文件夹。
            CrossDriveError: 跨盘移动。
            SelfSubdirectoryError: 移动到自身子目录。
            FileOperationError: 其他文件操作失败。
        """
        # 查询 ContentUnit
        unit = self._content_repo.get_by_id(unit_id)
        if unit is None:
            raise ContentUnitNotFoundError(f"内容单元不存在：{unit_id}")

        src_folder = Path(unit.path)
        # 目标路径 = target_dir / src_folder.name（保留原 Mod 组名）
        dst_folder = target_dir / src_folder.name

        # 步骤 1：先清理目标路径下的旧 ContentUnit 记录（在 move 之前）。
        # 此时文件系统状态干净（dst_folder 尚不存在），若清理失败可安全 rollback。
        # 清理在 move 之前，确保 update 时数据库无 UNIQUE 冲突。
        self._cleanup_stale_content_units(dst_folder, unit.id)

        # 步骤 2：调用 FileOperationService.move 执行移动（含所有安全检测）
        # move 会写入 operation_history（operation_type='move'）
        self._file_op.move(src_folder, dst_folder)

        # 步骤 3：更新 ContentUnit.path 指向新路径
        updated_unit = ContentUnit(
            id=unit.id,
            path=str(dst_folder),
            title=unit.title,
            content_type=unit.content_type,
            source_url=unit.source_url,
            rating=unit.rating,
            cover_path=unit.cover_path,
            status=unit.status,
            notes=unit.notes,
            created_at=unit.created_at,
            updated_at=unit.updated_at,
        )
        try:
            self._content_repo.update(updated_unit)
        except Exception as e:  # noqa: BLE001
            # 文件已移动但 ContentUnit 更新失败：记日志，抛异常让上层 rollback 释放写锁。
            # 注意：rollback 会回滚步骤 1 的 cleanup，旧记录复活，但因文件已移动，
            # 下次重试时 move 会因源不存在而失败（不会死循环）。
            logger.exception(
                "更新 ContentUnit.path 失败（文件已移动到 %s），请手动修正内容单元路径",
                dst_folder,
            )
            raise FileOperationError(  # noqa: TRY200 - 重新抛出为 FileOperationError
                f"更新 ContentUnit 路径失败：{e}"
            ) from e

        # 步骤 4：同步 folder_cache：删除旧节点 + 插入新节点 + 更新目标父目录 mtime
        # （与 ModGroupService.create_mod_group 步骤 1b 模式一致，确保目录树立即刷新）
        # H2 修复：同步失败不再吞异常，立即抛出让上层 rollback 保证事务一致性。
        try:
            self._sync_folder_cache(src_folder, dst_folder, target_dir)
        except Exception as sync_err:  # noqa: BLE001
            # 文件已移动 + ContentUnit.path 已更新，但 folder_cache 同步失败：
            # 抛出 FileOperationError 让上层 rollback。rollback 会回滚 ContentUnit.path
            # 更新与 cleanup（旧记录复活）。文件已移动无法回滚，下次重试 move 会因
            # 源不存在而失败，提示用户手动修正（不会死循环）。
            logger.exception(
                "同步 folder_cache 失败（文件已移动到 %s，ContentUnit 已更新），"
                "请手动刷新目录树或重新扫描",
                dst_folder,
            )
            raise FileOperationError(f"同步 folder_cache 失败：{sync_err}") from sync_err

        return updated_unit

    def _cleanup_stale_content_units(self, dst_folder: Path, current_unit_id: str) -> None:
        """清理目标路径下的旧 ContentUnit 记录（避免 update 时 UNIQUE 约束冲突）。

        TD-H7 修复收敛：原实现用 list_all + make_path_key 在 service 层内做归一化
        比较以绕开 broken 的 list_by_path_prefix。现已将该归一化查询下沉到
        ContentUnitRepository.list_by_path_prefix_normalized，service 层直接调用，
        避免该规避方案散落在多个 service 中。

        清理范围：dst_folder 自身 + 其所有子路径。
        排除当前 unit（current_unit_id），因为后续要更新它的 path。

        清理失败不阻塞主流程（记日志），交由上层事务回滚处理。
        """
        try:
            stale_units = self._content_repo.list_by_path_prefix_normalized(str(dst_folder))
        except Exception:  # noqa: BLE001 - 整体清理失败不阻塞，交由上层处理
            logger.exception("清理目标路径旧 ContentUnit 记录失败：path=%s", dst_folder)
            return

        for stale in stale_units:
            if stale.id == current_unit_id:
                continue  # 不删除当前要更新的 unit
            try:
                self._content_repo.delete(stale.id)
            except Exception:  # noqa: BLE001 - 单条清理失败不中断
                logger.warning(
                    "清理旧 ContentUnit 记录失败：id=%s path=%s",
                    stale.id,
                    stale.path,
                )

    def _sync_folder_cache(
        self, old_folder_path: Path, new_folder_path: Path, target_dir: Path
    ) -> None:
        """同步 folder_cache：删除旧节点 + 插入新节点 + 更新目标父目录 mtime。

        H2 修复（2026-07-17 Code Review）：原实现采用 ``except Exception: 吞异常``
        的 best-effort 模式，但同步内部包含多步写操作（删除旧 → 插入新 → 更新父
        mtime）。一旦中间步骤失败、异常被外层吞掉，MainWindow 随后调用 ``_commit``
        会把这种"部分成功"的状态提交进数据库，导致目录树出现静默缺节点。

        新契约：任一步失败立即抛出 ``FileOperationError``，由上层（MainWindow）
        捕获后调用 ``_rollback`` 回滚整个事务。文件已移动但数据库回滚后，
        ContentUnit.path 仍指向旧路径——下次重试时 move 会因源不存在而失败，
        提示用户手动修正（不会死循环，与 cleanup→move→update 顺序设计一致）。

        Args:
            old_folder_path: 源 Mod 组文件夹路径（已移走）。
            new_folder_path: 目标路径（已存在）。
            target_dir: 目标分类目录（new_folder_path 的父目录）。

        Raises:
            FileOperationError: folder_cache 同步任一步失败。
        """
        if self._folder_cache_repo is None:
            return
        # 不再吞异常：任一步失败立即抛出，让上层 rollback 保证事务一致性。
        # 1. 删除旧路径的 folder_cache 记录
        self._delete_folder_cache_by_path(old_folder_path)

        # 2. 在目标目录下插入新路径的 folder_cache 记录
        self._create_folder_cache_for_new_path(new_folder_path, target_dir)

        # 3. 更新目标目录的 last_scanned_mtime（让下次扫描知道该目录变了）
        self._update_parent_mtime(target_dir)

    def _delete_folder_cache_by_path(self, folder_path: Path) -> None:
        """删除指定路径的 folder_cache 记录（按 path_key 归一化匹配）。"""
        target_key = make_path_key(str(folder_path))
        for fc in self._folder_cache_repo.list_all():
            if make_path_key(fc.path) == target_key:
                self._folder_cache_repo.delete(fc.id)
                return

    def _create_folder_cache_for_new_path(self, new_folder_path: Path, target_dir: Path) -> None:
        """为新路径插入 folder_cache 记录（parent_id 取目标目录的 folder_cache.id）。"""
        # 检查是否已存在（避免唯一约束冲突）
        new_path_key = make_path_key(str(new_folder_path))
        for fc in self._folder_cache_repo.list_all():
            if make_path_key(fc.path) == new_path_key:
                # 已存在（异常情况），不重复插入
                return

        parent_id = self._resolve_parent_id_by_path(str(target_dir))
        # 用当前 mtime 作为 last_scanned_mtime（近似值，下次全量扫描会修正）
        try:
            mtime = new_folder_path.stat().st_mtime
        except OSError:
            mtime = 0.0

        folder = FolderCache(
            id=self._new_folder_cache_id(),
            path=str(new_folder_path),
            parent_id=parent_id,
            last_scanned_mtime=mtime,
            created_at=self._now_iso(),
        )
        self._folder_cache_repo.create(folder)

    def _update_parent_mtime(self, target_dir: Path) -> None:
        """更新目标目录的 last_scanned_mtime。"""
        target_key = make_path_key(str(target_dir))
        try:
            mtime = target_dir.stat().st_mtime
        except OSError:
            return
        for fc in self._folder_cache_repo.list_all():
            if make_path_key(fc.path) == target_key:
                self._folder_cache_repo.upsert_mtime(fc.path, mtime, fc.id)
                return

    def _resolve_parent_id_by_path(self, parent_path: str) -> str | None:
        """按路径查找 folder_cache.id（用于新建子文件夹时的 parent_id 关联）。

        使用 make_path_key 归一化后比较，避免大小写/分隔符差异导致匹配失败。
        与 ModGroupService._resolve_parent_id_by_path 保持一致的归一化策略。
        """
        target_key = make_path_key(parent_path)
        for fc in self._folder_cache_repo.list_all():
            if make_path_key(fc.path) == target_key:
                return fc.id
        return None

    def _new_folder_cache_id(self) -> str:
        """生成 folder_cache 的 UUID。"""
        import uuid

        return str(uuid.uuid4())

    def _now_iso(self) -> str:
        """返回当前 UTC 时间的 ISO 8601 字符串。"""
        from datetime import UTC, datetime

        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
