"""快速插入服务（阶段 3 Task 5）。

整理模式下，将当前装配面板绑定的 Mod 组文件夹整体移动到目录树中选中的目标分类目录。

工作流（Stage 4.5 H4 简化后）：
1. 查询 Mod 组 ContentUnit。
2. 目标路径 = target_dir / mod_folder.name。
3. **先清理**目标路径下的旧 ContentUnit 记录（避免 move 内部更新
   ContentUnit.path 时 UNIQUE 冲突）。清理在 move 之前，此时文件系统
   状态干净，若清理失败可安全 rollback。
4. 调用 FileOperationService.move 执行移动（含跨盘/子目录/冲突检测）。
   Stage 4.5 H4：move 内部自动同步 folder_cache（删除旧 + 插入新 + 更新父
   mtime）和 ContentUnit.path 前缀重写（注入 helper + content_unit_repo 时）。
5. 返回最新查询到的 ContentUnit（path 已由 move 内部更新）。

顺序设计原理（避免死循环）：
- 旧顺序 move → cleanup → update：若 update 失败，rollback 会回滚 cleanup 的 delete，
  旧记录"复活"，下次重试 update 仍会 UNIQUE 冲突 → 死循环。
- 新顺序 cleanup → move：cleanup 在 move 之前，move 内部的 ContentUnit.path 更新
  时数据库已无冲突记录，不会 UNIQUE 冲突。若 move 失败，rollback 回滚 cleanup，
  旧记录复活但文件未移动，下次重试可正常清理。

安全规则（spec §6.1）：
- 跨盘移动：FileOperationService.move 抛 CrossDriveError。
- 子目录阻止：FileOperationService.move 抛 SelfSubdirectoryError。
- 重名冲突：FileOperationService.move 抛 ConflictError（不覆盖，AGENTS 规则 2）。
- operation_history 由 FileOperationService.move 写入。

约束（AGENTS 规则）：
- 文件操作通过 FileOperationService，本服务不直接调用 shutil / Path.rename。
- 不自提交，由调用方控制事务边界。
- 路径比较统一使用 make_path_key()（AGENTS 规则 9）。

目录树刷新统一机制：
- folder_cache 同步（删除旧节点 + 插入新节点 + 更新父目录 mtime）由
  FileOperationService.move 内部的 FolderCacheSyncHelper 自动完成（H4）。
- UI 层（MainWindow）在操作完成后只需调用一次 _refresh_tree() 即可立即刷新目录树。

Stage 4.5 H4（TD-M22）：folder_cache 同步 + ContentUnit.path 更新由
FileOperationService 内部的 FolderCacheSyncHelper + ContentUnitRepository
自动完成，本服务移除了 _sync_folder_cache / _delete_folder_cache_by_path /
_create_folder_cache_for_new_path / _update_parent_mtime /
_resolve_parent_id_by_path / _new_folder_cache_id / _now_iso 等重复逻辑
（已集中到 FolderCacheSyncHelper）。
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from application.errors import ContentUnitNotFoundError
from domain.models import ContentUnit
from infrastructure.file_operation_service import FileOperationService
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.errors import RepositoryError
from infrastructure.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)


class QuickInsertService:
    """快速插入服务：Mod 组文件夹整体移动到目标分类目录。

    Stage 4.5 H4（TD-M22）：folder_cache 同步 + ContentUnit.path 更新由
    FileOperationService.move 内部自动完成，本服务不再手动同步。

    使用方式：
        service = QuickInsertService(file_op_service, content_repo, uow=uow)
        unit = service.quick_insert(unit_id, Path("D:/Mods/Armor"))
    """

    def __init__(
        self,
        file_op_service: FileOperationService,
        content_unit_repo: ContentUnitRepository,
        uow: UnitOfWork | None = None,
    ) -> None:
        """初始化 QuickInsertService。

        Args:
            file_op_service: 文件操作服务（Stage 4.5 H4：应注入 FolderCacheSyncHelper
                + ContentUnitRepository，move 时自动同步 folder_cache +
                ContentUnit.path）。
            content_unit_repo: 内容单元仓储（用于 cleanup 旧记录查询 +
                move 后读取最新 ContentUnit）。
            uow: 事务边界管理器（可选）。Stage 4.5 H6 修复：
                注入后 quick_insert 的多步写操作（cleanup + move 内部 DB 写）
                在事务内执行，保证原子性。None 时保持原行为
                （调用方控制事务边界）。文件操作（move）不受事务保护（无法回滚），
                但在事务内执行——异常时 DB 回滚 + 文件已移动需用户手动修正。
        """
        self._file_op = file_op_service
        self._content_repo = content_unit_repo
        self._uow = uow

    def quick_insert(self, unit_id: str, target_dir: Path) -> ContentUnit:
        """将 Mod 组文件夹整体移动到目标分类目录。

        操作顺序（2026-07-17 修复，避免 UNIQUE 冲突死循环；
        Stage 4.5 H4 简化：folder_cache + ContentUnit.path 由 move 自动同步）：
        1. cleanup：清理目标路径下的旧 ContentUnit 记录
        2. move：移动文件（含 operation_history + 自动 folder_cache 同步 +
           ContentUnit.path 前缀重写）
        3. 重新查询 ContentUnit 返回最新状态

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
        # 查询 ContentUnit（只读，不需要事务）
        unit = self._content_repo.get_by_id(unit_id)
        if unit is None:
            raise ContentUnitNotFoundError(f"内容单元不存在：{unit_id}")

        src_folder = Path(unit.path)
        # 目标路径 = target_dir / src_folder.name（保留原 Mod 组名）
        dst_folder = target_dir / src_folder.name

        # DB + 文件操作在事务内执行（Stage 4.5 H6：保证多步写原子性）
        # 文件操作（move）不受事务保护（无法回滚），但异常时 re-raise → UoW 回滚
        # DB 写操作（cleanup + move 内部的 folder_cache/ContentUnit.path 同步）。
        if self._uow is not None:
            with self._uow.transaction():
                return self._quick_insert_core(unit, src_folder, dst_folder, target_dir)
        return self._quick_insert_core(unit, src_folder, dst_folder, target_dir)

    def _quick_insert_core(
        self,
        unit: ContentUnit,
        src_folder: Path,
        dst_folder: Path,
        target_dir: Path,
    ) -> ContentUnit:
        """quick_insert 的核心逻辑（cleanup + move）。

        Stage 4.5 H4：folder_cache 同步 + ContentUnit.path 更新由
        FileOperationService.move 内部自动完成，本方法不再手动同步。
        """
        # 步骤 1：先清理目标路径下的旧 ContentUnit 记录（在 move 之前）。
        # 此时文件系统状态干净（dst_folder 尚不存在），若清理失败可安全 rollback。
        # 清理在 move 之前，确保 move 内部更新 ContentUnit.path 时数据库无 UNIQUE 冲突。
        self._cleanup_stale_content_units(dst_folder, unit.id)

        # 步骤 2：调用 FileOperationService.move 执行移动（含所有安全检测）
        # move 会写入 operation_history（operation_type='move'）
        # H4：注入 helper + content_unit_repo 后，move 内部自动：
        #   - 同步 folder_cache（删除旧 + 插入新 + 更新父 mtime）
        #   - 重写 ContentUnit.path 前缀（src → dst，含子路径前缀重写）
        self._file_op.move(src_folder, dst_folder)

        # 步骤 3：重新查询 ContentUnit 返回最新状态
        # （move 内部已更新 ContentUnit.path，这里只读返回）
        updated_unit = self._content_repo.get_by_id(unit.id)
        if updated_unit is None:
            # 极端情况：move 内部更新成功但此处查不到（如事务隔离级别问题）
            # 返回基于 src unit 构造的对象，path 指向新路径
            logger.warning(
                "quick_insert 后 ContentUnit 查询失败（id=%s），返回构造对象",
                unit.id,
            )
            return ContentUnit(
                id=unit.id,
                path=str(dst_folder),
                title=unit.title,
                content_type=unit.content_type,
                source_url=unit.source_url,
                cover_path=unit.cover_path,
                is_marked=unit.is_marked,
                notes=unit.notes,
                created_at=unit.created_at,
                updated_at=unit.updated_at,
            )
        return updated_unit

    def _cleanup_stale_content_units(self, dst_folder: Path, current_unit_id: str) -> None:
        """清理目标路径下的旧 ContentUnit 记录（避免 move 内部更新时 UNIQUE 冲突）。

        TD-H7 修复收敛：使用 ContentUnitRepository.list_by_path_prefix_normalized
        （归一化接口，原 list_by_path_prefix 已在 TD-L20 清理中删除）。

        清理范围：dst_folder 自身 + 其所有子路径。
        排除当前 unit（current_unit_id），因为 move 内部会更新它的 path。

        清理失败不阻塞主流程（记日志），交由上层事务回滚处理。
        """
        try:
            stale_units = self._content_repo.list_by_path_prefix_normalized(str(dst_folder))
        except (RepositoryError, sqlite3.Error):  # 整体清理失败不阻塞，交由上层处理
            logger.exception("清理目标路径旧 ContentUnit 记录失败：path=%s", dst_folder)
            return

        for stale in stale_units:
            if stale.id == current_unit_id:
                continue  # 不删除当前要更新的 unit
            try:
                self._content_repo.delete(stale.id)
            except (RepositoryError, sqlite3.Error):  # 单条清理失败不中断
                logger.warning(
                    "清理旧 ContentUnit 记录失败：id=%s path=%s",
                    stale.id,
                    stale.path,
                )
