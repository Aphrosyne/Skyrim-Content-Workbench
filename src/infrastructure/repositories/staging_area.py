"""StagingAreaRepository。

负责 StagingArea dataclass 与 staging_area 表之间的转换。
不访问文件系统；real_path 仅作为字符串存储。
schema v5 引入（见 docs/roadmap.md 阶段 3 Task 1）。
"""

from __future__ import annotations

import logging
import sqlite3

from domain.models import StagingArea
from infrastructure.repositories.errors import (
    ConstraintViolationError,
    NotFoundError,
    RepositoryError,
)

logger = logging.getLogger(__name__)


class StagingAreaRepository:
    """StagingArea 的 CRUD。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, staging: StagingArea) -> StagingArea:
        """插入 StagingArea。path_key 唯一约束冲突抛 ConstraintViolationError。

        写操作不自提交，由 application 层控制事务边界（与其他 Repository 一致）。
        """
        try:
            self._conn.execute(
                """
                INSERT INTO staging_area (
                    id, real_path, path_key, display_name, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    staging.id,
                    staging.real_path,
                    staging.path_key,
                    staging.display_name,
                    staging.created_at,
                    staging.updated_at,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise ConstraintViolationError(f"无法创建 StagingArea：{e}") from e
        except sqlite3.Error as e:
            raise RepositoryError(f"无法创建 StagingArea：{e}") from e
        return self.get_by_id(staging.id)  # type: ignore[return-value]

    def get_by_id(self, staging_id: str) -> StagingArea | None:
        """按 ID 查询；不存在返回 None。"""
        try:
            row = self._conn.execute(
                "SELECT * FROM staging_area WHERE id = ?",
                (staging_id,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法查询 StagingArea：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def get_by_path_key(self, path_key: str) -> StagingArea | None:
        """按 path_key 查询；不存在返回 None。用于去重检查。"""
        try:
            row = self._conn.execute(
                "SELECT * FROM staging_area WHERE path_key = ?",
                (path_key,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法按 path_key 查询 StagingArea：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def list_all(self) -> list[StagingArea]:
        """返回全部 StagingArea，按 real_path 排序。"""
        try:
            rows = self._conn.execute("SELECT * FROM staging_area ORDER BY real_path").fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法列出 StagingArea：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def delete(self, staging_id: str) -> None:
        """按 ID 删除 StagingArea 记录。

        仅删除 staging_area 表中的配置记录，不删除、不修改任何用户文件。

        实体不存在时抛 NotFoundError。写操作不自提交，由 application 层控制事务边界。
        """
        try:
            cur = self._conn.execute(
                "DELETE FROM staging_area WHERE id = ?",
                (staging_id,),
            )
        except sqlite3.Error as e:
            raise RepositoryError(f"无法删除 StagingArea：{e}") from e
        if cur.rowcount == 0:
            raise NotFoundError(f"StagingArea 不存在：{staging_id}")

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> StagingArea:
        return StagingArea(
            id=row["id"],
            real_path=row["real_path"],
            path_key=row["path_key"],
            display_name=row["display_name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
