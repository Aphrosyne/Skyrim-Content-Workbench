"""ManagedRootRepository。

负责 ManagedRoot dataclass 与 managed_root 表之间的转换。
不访问文件系统；real_path 仅作为字符串存储。
schema v2 引入（见 docs/phase-2-plan.md 任务 1 D1）。
"""

from __future__ import annotations

import logging
import sqlite3

from domain.models import ManagedRoot
from infrastructure.repositories.errors import (
    ConstraintViolationError,
    NotFoundError,
    RepositoryError,
)

logger = logging.getLogger(__name__)


class ManagedRootRepository:
    """ManagedRoot 的 CRUD。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, root: ManagedRoot) -> ManagedRoot:
        """插入 ManagedRoot。path_key 唯一约束冲突抛 ConstraintViolationError。

        写操作不自提交，由 application 层控制事务边界（与其他 Repository 一致）。
        """
        try:
            self._conn.execute(
                """
                INSERT INTO managed_root (
                    id, real_path, path_key, display_name, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    root.id,
                    root.real_path,
                    root.path_key,
                    root.display_name,
                    root.created_at,
                    root.updated_at,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise ConstraintViolationError(f"无法创建 ManagedRoot：{e}") from e
        except sqlite3.Error as e:
            raise RepositoryError(f"无法创建 ManagedRoot：{e}") from e
        return self.get_by_id(root.id)  # type: ignore[return-value]

    def get_by_id(self, root_id: str) -> ManagedRoot | None:
        """按 ID 查询；不存在返回 None。"""
        try:
            row = self._conn.execute(
                "SELECT * FROM managed_root WHERE id = ?",
                (root_id,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法查询 ManagedRoot：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def get_by_path_key(self, path_key: str) -> ManagedRoot | None:
        """按 path_key 查询；不存在返回 None。用于去重检查。"""
        try:
            row = self._conn.execute(
                "SELECT * FROM managed_root WHERE path_key = ?",
                (path_key,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法按 path_key 查询 ManagedRoot：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def list_all(self) -> list[ManagedRoot]:
        """返回全部 ManagedRoot，按 real_path 排序。"""
        try:
            rows = self._conn.execute("SELECT * FROM managed_root ORDER BY real_path").fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法列出 ManagedRoot：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def delete(self, root_id: str) -> None:
        """按 ID 删除 ManagedRoot 记录。

        仅删除 managed_root 表中的配置记录，不删除、不修改任何用户文件，
        不清理 folder_cache / content_unit 等扫描记录（清理策略待确认）。

        实体不存在时抛 NotFoundError。写操作不自提交，由 application 层控制事务边界。
        """
        try:
            cur = self._conn.execute(
                "DELETE FROM managed_root WHERE id = ?",
                (root_id,),
            )
        except sqlite3.Error as e:
            raise RepositoryError(f"无法删除 ManagedRoot：{e}") from e
        if cur.rowcount == 0:
            raise NotFoundError(f"ManagedRoot 不存在：{root_id}")

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> ManagedRoot:
        return ManagedRoot(
            id=row["id"],
            real_path=row["real_path"],
            path_key=row["path_key"],
            display_name=row["display_name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
