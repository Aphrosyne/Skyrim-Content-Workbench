"""folder_cache 同步辅助（Stage 4.5 TD-M22 + H4 + TD-L18）。

集中各 Service（ContentUnitCreationService / AssemblyService）中
重复的 folder_cache 同步逻辑，避免 Stage 5 undo 实现时反向同步逻辑复制粘贴。

放置在 infrastructure 层：FileOperationService（infrastructure）需注入本 helper
以在 move/new_folder 后自动同步 folder_cache（H4），避免引入
infrastructure -> application 的反向依赖。

策略契约（TD-L18 统一）：
- 多步写操作（on_folder_moved：删除旧 + 插入新 + 更新父 mtime）：
  任一步失败立即抛出 FileOperationError，由上层 rollback 保证事务一致性
  （TD-H8 既有策略）。
- 单字段 mtime 更新（update_folder_mtime）：best-effort，失败仅记日志
  （最坏情况是下次扫描重新处理该文件夹，不会数据不一致）。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from application.errors import FileOperationError
from domain.models import FolderCache
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.errors import RepositoryError
from infrastructure.repositories.folder_cache import FolderCacheRepository

logger = logging.getLogger(__name__)


def default_now_utc() -> str:
    """返回当前 UTC 时间的 ISO 8601 字符串。"""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_uuid_provider() -> str:
    """生成 UUID 字符串。"""
    return str(uuid.uuid4())


def is_in_directory(file_path: Path, dir_path: Path) -> bool:
    """判断 file_path 是否在 dir_path 之下（含 dir_path 自身）。

    使用 make_path_key 归一化后字符串前缀比较，避免大小写/分隔符差异。
    不访问文件系统，仅基于路径字符串比较。
    """
    sep = os.sep
    file_key = make_path_key(file_path)
    dir_key = make_path_key(dir_path)
    if file_key == dir_key:
        return True
    return file_key.startswith(dir_key.rstrip(sep) + sep)


class FolderCacheSyncHelper:
    """folder_cache 同步辅助。

    提供语义化的 folder_cache 同步方法，供 FileOperationService 和各
    Application Service 调用，消除 4 处重复的同步逻辑（TD-M22）。

    使用方式：
        helper = FolderCacheSyncHelper(folder_cache_repo)
        helper.on_folder_created(new_path, parent_path)
        helper.on_folder_moved(old_path, new_path, target_dir)
        helper.update_folder_mtime(folder_path)
    """

    def __init__(
        self,
        folder_cache_repo: FolderCacheRepository,
        now_provider: Callable[[], str] | None = None,
        uuid_provider: Callable[[], str] | None = None,
    ) -> None:
        self._repo = folder_cache_repo
        self._now = now_provider or default_now_utc
        self._new_uuid = uuid_provider or default_uuid_provider

    def on_folder_created(self, new_path: Path, parent_path: Path) -> None:
        """文件夹创建后同步：插入新 folder_cache 记录。

        多步写操作（TD-L18 策略：失败抛异常）。

        Args:
            new_path: 新创建的文件夹路径。
            parent_path: 父目录路径（用于关联 parent_id）。

        Raises:
            FileOperationError: folder_cache 写入失败。
        """
        try:
            parent_id = self._resolve_parent_id_by_path(str(parent_path))
            mtime = _safe_mtime(new_path)
            folder = FolderCache(
                id=self._new_uuid(),
                path=str(new_path),
                parent_id=parent_id,
                last_scanned_mtime=mtime,
                created_at=self._now(),
            )
            self._repo.create(folder)
        except (RepositoryError, sqlite3.Error, OSError) as e:
            raise FileOperationError(f"写入 folder_cache 失败：{e}") from e

    def on_folder_moved(self, old_path: Path, new_path: Path, target_dir: Path) -> None:
        """文件夹移动后同步：迁移整棵缓存子树 + 更新父目录 mtime。

        Bug紧急修复2（2026-08-02）：原实现只"删除旧单行 + 插入新单行"，移动带
        子目录缓存（folder_cache.parent_id 引用）的文件夹时删除父行触发
        FOREIGN KEY 约束失败，导致"磁盘已移动但数据库未同步"，随后扫描清理
        会误删旧路径 content_unit 行（丢失内容单元标记）。现改为整棵子树迁移：
        新路径行按父先子后插入（路径前缀重写、父关系重建），旧行按先子后父删除。

        多步写操作（TD-L18 策略：任一步失败立即抛异常，由上层 rollback 保证
        事务一致性，TD-H8 既有策略）。

        Args:
            old_path: 源文件夹路径（已移走）。
            new_path: 目标路径（已存在）。
            target_dir: 目标分类目录（new_path 的父目录）。

        Raises:
            FileOperationError: folder_cache 同步任一步失败。
        """
        try:
            # 1. 迁移整棵子树（新行插入 + 旧行先子后父删除）
            self._move_folder_subtree(old_path, new_path, target_dir)

            # 2. 更新目标目录的 last_scanned_mtime
            self._update_parent_mtime(target_dir)
        except (RepositoryError, sqlite3.Error, OSError) as e:
            raise FileOperationError(f"同步 folder_cache 失败：{e}") from e

    def on_folder_deleted(self, old_path: Path) -> None:
        """文件夹删除后同步：删除旧 folder_cache 记录。

        单步写，失败抛异常。

        Raises:
            FileOperationError: folder_cache 删除失败。
        """
        try:
            self._delete_by_path(old_path)
        except (RepositoryError, sqlite3.Error) as e:
            raise FileOperationError(f"删除 folder_cache 失败：{e}") from e

    def delete_folder_subtree(self, path: Path) -> bool:
        """删除指定路径及其所有子节点的 folder_cache 记录（先子后父）。

        TD-L25：将"按路径前缀批量删除"封装为语义化方法，供
        FileOperationService._sync_on_delete 等使用，消除外部访问私有 ``_repo``。
        目标路径无记录时为空操作（返回 False）。

        Args:
            path: 目标文件夹路径（文件删除场景传入的路径无 folder_cache 记录，
                将返回 False 且仅更新父目录 mtime 由调用方处理）。

        Returns:
            True 表示删除了至少一条记录。

        Raises:
            FileOperationError: folder_cache 删除失败。
        """
        try:
            target_key = make_path_key(str(path))
            sep = os.sep
            target_prefix = target_key.rstrip(sep) + sep
            to_delete = [
                fc
                for fc in self._repo.list_all()
                if make_path_key(fc.path) == target_key
                or make_path_key(fc.path).startswith(target_prefix)
            ]
            # 按路径深度降序删除（先子后父，避免 FK 约束冲突）
            to_delete.sort(key=lambda fc: len(fc.path), reverse=True)
            for fc in to_delete:
                self._repo.delete(fc.id)
            return bool(to_delete)
        except (RepositoryError, sqlite3.Error) as e:
            raise FileOperationError(f"删除 folder_cache 子树失败：{e}") from e

    def update_folder_mtime(self, folder_path: Path) -> None:
        """更新文件夹 mtime（单字段，best-effort）。

        TD-L18 统一策略：单字段 mtime 更新保留 best-effort 模式——
        失败仅记日志（最坏情况是下次扫描重新处理该文件夹，不会数据不一致）。

        与 on_folder_moved 的多步同步不同：多步同步中间步骤失败会导致部分提交态，
        必须抛异常；单字段更新最坏情况只是 mtime 不准，可安全吞异常。
        """
        try:
            target_key = make_path_key(str(folder_path))
            mtime = _safe_mtime(folder_path)
            if mtime is None:
                return
            for fc in self._repo.list_all():
                if make_path_key(fc.path) == target_key:
                    self._repo.upsert_mtime(mtime, fc.id)
                    return
        except (RepositoryError, sqlite3.Error, OSError):
            logger.exception("更新 folder_cache mtime 失败：path=%s", folder_path)

    # --- 内部方法 ---

    def _resolve_parent_id_by_path(self, parent_path: str) -> str | None:
        """按路径查找 folder_cache.id（归一化匹配）。"""
        target_key = make_path_key(parent_path)
        for fc in self._repo.list_all():
            if make_path_key(fc.path) == target_key:
                return fc.id
        return None

    def _delete_by_path(self, folder_path: Path) -> None:
        """删除指定路径的 folder_cache 记录（按 path_key 归一化匹配）。"""
        target_key = make_path_key(str(folder_path))
        for fc in self._repo.list_all():
            if make_path_key(fc.path) == target_key:
                self._repo.delete(fc.id)
                return

    def _move_folder_subtree(self, old_path: Path, new_path: Path, target_dir: Path) -> None:
        """迁移 old_path 下整棵 folder_cache 子树到 new_path（Bug紧急修复2）。

        - 收集 old_path（含自身）及所有子节点的缓存行
        - 按路径深度升序（父先子后）插入新路径行：路径前缀 old→new 重写，
          根节点 parent_id 改为 target_dir 的缓存 id，子节点 parent_id 映射到
          新建父行的新 id
        - 按路径深度降序（先子后父）删除旧行，避免 FOREIGN KEY 约束冲突

        旧路径无记录时仍插入新路径根节点（保持原行为，目录树即时可见）。
        """
        old_key = make_path_key(str(old_path))
        sep = os.sep
        old_prefix = old_key.rstrip(sep) + sep
        rows = [
            fc
            for fc in self._repo.list_all()
            if make_path_key(fc.path) == old_key or make_path_key(fc.path).startswith(old_prefix)
        ]
        if not rows:
            # 旧路径无缓存记录：仅插入新路径根节点
            new_fc = FolderCache(
                id=self._new_uuid(),
                path=str(new_path),
                parent_id=self._resolve_parent_id_by_path(str(target_dir)),
                last_scanned_mtime=_safe_mtime(new_path),
                created_at=self._now(),
            )
            self._repo.create(new_fc)
            return

        # 父先子后插入新行（父节点 id 先映射，子节点才能引用）
        rows.sort(key=lambda fc: len(fc.path))
        old_to_new: dict[str, str] = {}
        for fc in rows:
            if make_path_key(fc.path) == old_key:
                new_fc_path = new_path
                parent_id = self._resolve_parent_id_by_path(str(target_dir))
            else:
                try:
                    rel = Path(os.path.relpath(fc.path, old_path))
                except (ValueError, OSError):
                    # 大小写/分隔符差异：用归一化后缀回退
                    rel = Path(make_path_key(fc.path)[len(old_key) :].lstrip(sep))
                new_fc_path = new_path / rel
                parent_id = old_to_new.get(fc.parent_id)  # type: ignore[arg-type]
            new_fc = FolderCache(
                id=self._new_uuid(),
                path=str(new_fc_path),
                parent_id=parent_id,
                last_scanned_mtime=_safe_mtime(new_fc_path),
                created_at=self._now(),
            )
            created = self._repo.create(new_fc)
            old_to_new[fc.id] = created.id

        # 先子后父删除旧行（避免 FK 约束冲突）
        for fc in sorted(rows, key=lambda fc: len(fc.path), reverse=True):
            self._repo.delete(fc.id)

    def _update_parent_mtime(self, target_dir: Path) -> None:
        """更新目标目录的 last_scanned_mtime。"""
        target_key = make_path_key(str(target_dir))
        mtime = _safe_mtime(target_dir)
        if mtime is None:
            return
        for fc in self._repo.list_all():
            if make_path_key(fc.path) == target_key:
                self._repo.upsert_mtime(mtime, fc.id)
                return


def _safe_mtime(path: Path) -> float:
    """安全获取 mtime，失败返回 0.0。"""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
