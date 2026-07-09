"""FolderNodeRepository。

负责 FolderNode dataclass 与 folder_node 表之间的转换。
不访问文件系统；real_path 仅作为字符串存储。
"""

from __future__ import annotations

import logging
import sqlite3

from domain.models import FolderNode
from infrastructure.repositories.errors import (
    ConstraintViolationError,
    NotFoundError,
    RepositoryError,
)

logger = logging.getLogger(__name__)


class FolderNodeRepository:
    """FolderNode 的 CRUD。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, node: FolderNode) -> FolderNode:
        """插入 FolderNode。is_managed_root 存为 0/1。"""
        try:
            self._conn.execute(
                """
                INSERT INTO folder_node (
                    id, real_path, path_key, parent_id, display_name,
                    is_managed_root, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.id,
                    node.real_path,
                    node.path_key,
                    node.parent_id,
                    node.display_name,
                    1 if node.is_managed_root else 0,
                    node.created_at,
                    node.updated_at,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise ConstraintViolationError(f"无法创建 FolderNode：{e}") from e
        except sqlite3.Error as e:
            raise RepositoryError(f"无法创建 FolderNode：{e}") from e
        return self.get_by_id(node.id)  # type: ignore[return-value]

    def get_by_id(self, node_id: str) -> FolderNode | None:
        """按 ID 查询；不存在返回 None。"""
        try:
            row = self._conn.execute(
                "SELECT * FROM folder_node WHERE id = ?",
                (node_id,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法查询 FolderNode：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def list_by_parent(self, parent_id: str | None) -> list[FolderNode]:
        """返回指定父节点下的子目录。

        parent_id=None 时返回受管理根目录列表。
        """
        if parent_id is None:
            try:
                rows = self._conn.execute(
                    "SELECT * FROM folder_node WHERE parent_id IS NULL ORDER BY real_path"
                ).fetchall()
            except sqlite3.Error as e:
                raise RepositoryError(f"无法列出根目录：{e}") from e
        else:
            try:
                rows = self._conn.execute(
                    "SELECT * FROM folder_node WHERE parent_id = ? ORDER BY real_path",
                    (parent_id,),
                ).fetchall()
            except sqlite3.Error as e:
                raise RepositoryError(f"无法列出子目录：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def list_managed_roots(self) -> list[FolderNode]:
        """返回所有受管理根目录。"""
        try:
            rows = self._conn.execute(
                "SELECT * FROM folder_node WHERE is_managed_root = 1 ORDER BY real_path"
            ).fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法列出受管理根目录：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def list_all(self) -> list[FolderNode]:
        """返回全部 FolderNode，按 real_path 排序。

        供目录树构建等只读批量查询场景使用；不区分根/子节点。
        """
        try:
            rows = self._conn.execute("SELECT * FROM folder_node ORDER BY real_path").fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法列出全部 FolderNode：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def get_by_path_key(self, path_key: str) -> FolderNode | None:
        """按 path_key 查询；不存在返回 None。

        用于将 ManagedRoot 配置关联到扫描得到的 FolderNode 根节点。
        """
        try:
            row = self._conn.execute(
                "SELECT * FROM folder_node WHERE path_key = ?",
                (path_key,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法按 path_key 查询 FolderNode：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def count_children(self, parent_id: str) -> int:
        """返回指定父节点下的子目录数量（仅 FolderNode，不含文件）。"""
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM folder_node WHERE parent_id = ?",
                (parent_id,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法统计子目录数量：{e}") from e
        return int(row[0])

    def update(self, node: FolderNode) -> FolderNode:
        """全字段更新。实体不存在时抛 NotFoundError。"""
        try:
            cur = self._conn.execute(
                """
                UPDATE folder_node SET
                    real_path = ?,
                    path_key = ?,
                    parent_id = ?,
                    display_name = ?,
                    is_managed_root = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    node.real_path,
                    node.path_key,
                    node.parent_id,
                    node.display_name,
                    1 if node.is_managed_root else 0,
                    node.updated_at,
                    node.id,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise ConstraintViolationError(f"无法更新 FolderNode：{e}") from e
        except sqlite3.Error as e:
            raise RepositoryError(f"无法更新 FolderNode：{e}") from e
        if cur.rowcount == 0:
            raise NotFoundError(f"FolderNode 不存在：{node.id}")
        return self.get_by_id(node.id)  # type: ignore[return-value]

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> FolderNode:
        return FolderNode(
            id=row["id"],
            real_path=row["real_path"],
            path_key=row["path_key"],
            parent_id=row["parent_id"],
            display_name=row["display_name"],
            is_managed_root=bool(row["is_managed_root"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
