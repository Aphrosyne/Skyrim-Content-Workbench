"""FolderCacheRepository。

负责 FolderCache dataclass 与 folder_cache 表之间的转换。
不访问文件系统；path 仅作为字符串存储。
"""

from __future__ import annotations

import logging
import sqlite3

from domain.models import FolderCache
from infrastructure.repositories.errors import (
    ConstraintViolationError,
    NotFoundError,
    RepositoryError,
)

logger = logging.getLogger(__name__)


class FolderCacheRepository:
    """FolderCache 的 CRUD。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, folder: FolderCache) -> FolderCache:
        """插入 FolderCache。path 唯一冲突抛 ConstraintViolationError。"""
        try:
            self._conn.execute(
                """
                INSERT INTO folder_cache (
                    id, path, parent_id, last_scanned_mtime, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    folder.id,
                    folder.path,
                    folder.parent_id,
                    folder.last_scanned_mtime,
                    folder.created_at,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise ConstraintViolationError(f"无法创建 FolderCache：{e}") from e
        except sqlite3.Error as e:
            raise RepositoryError(f"无法创建 FolderCache：{e}") from e
        return self.get_by_path(folder.path)  # type: ignore[return-value]

    def get_by_id(self, folder_id: str) -> FolderCache | None:
        """按 ID 查询；不存在返回 None。"""
        try:
            row = self._conn.execute(
                "SELECT * FROM folder_cache WHERE id = ?",
                (folder_id,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法查询 FolderCache：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def get_by_path(self, path: str) -> FolderCache | None:
        """按 path 查询；不存在返回 None。"""
        try:
            row = self._conn.execute(
                "SELECT * FROM folder_cache WHERE path = ?",
                (path,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法按 path 查询 FolderCache：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def list_by_parent(self, parent_id: str | None) -> list[FolderCache]:
        """返回指定 parent_id 下的所有 FolderCache。

        parent_id=None 返回根节点（parent_id IS NULL）。
        按 path 排序。
        """
        try:
            if parent_id is None:
                rows = self._conn.execute(
                    "SELECT * FROM folder_cache WHERE parent_id IS NULL ORDER BY path"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM folder_cache WHERE parent_id = ? ORDER BY path",
                    (parent_id,),
                ).fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法列出 FolderCache：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def list_all(self) -> list[FolderCache]:
        """返回全部 FolderCache，按 path 排序。"""
        try:
            rows = self._conn.execute("SELECT * FROM folder_cache ORDER BY path").fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法列出 FolderCache：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def upsert_mtime(self, path: str, mtime: float, folder_id: str) -> None:
        """更新 last_scanned_mtime。不存在抛 NotFoundError。

        mtime 为 epoch 秒（float）。
        """
        try:
            cur = self._conn.execute(
                "UPDATE folder_cache SET last_scanned_mtime = ? WHERE id = ?",
                (mtime, folder_id),
            )
        except sqlite3.Error as e:
            raise RepositoryError(f"无法更新 FolderCache mtime：{e}") from e
        if cur.rowcount == 0:
            raise NotFoundError(f"FolderCache 不存在：{folder_id}")

    def delete(self, folder_id: str) -> None:
        """按 ID 删除。不存在抛 NotFoundError。"""
        try:
            cur = self._conn.execute(
                "DELETE FROM folder_cache WHERE id = ?",
                (folder_id,),
            )
        except sqlite3.Error as e:
            raise RepositoryError(f"无法删除 FolderCache：{e}") from e
        if cur.rowcount == 0:
            raise NotFoundError(f"FolderCache 不存在：{folder_id}")

    def delete_by_path(self, path: str) -> None:
        """按 path 删除。不存在抛 NotFoundError。"""
        try:
            cur = self._conn.execute(
                "DELETE FROM folder_cache WHERE path = ?",
                (path,),
            )
        except sqlite3.Error as e:
            raise RepositoryError(f"无法按 path 删除 FolderCache：{e}") from e
        if cur.rowcount == 0:
            raise NotFoundError(f"FolderCache 不存在：path={path}")

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> FolderCache:
        return FolderCache(
            id=row["id"],
            path=row["path"],
            parent_id=row["parent_id"],
            last_scanned_mtime=row["last_scanned_mtime"],
            created_at=row["created_at"],
        )
