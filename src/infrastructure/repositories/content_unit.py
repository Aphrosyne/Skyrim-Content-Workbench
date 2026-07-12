"""ContentUnitRepository。

负责 ContentUnit dataclass 与 content_unit 表之间的转换。
不访问文件系统；path 仅作为字符串存储。
"""

from __future__ import annotations

import logging
import sqlite3

from domain.models import ContentUnit
from infrastructure.repositories.errors import (
    ConstraintViolationError,
    NotFoundError,
    RepositoryError,
)

logger = logging.getLogger(__name__)


class ContentUnitRepository:
    """ContentUnit 的 CRUD。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, unit: ContentUnit) -> ContentUnit:
        """插入 ContentUnit。path 唯一冲突抛 ConstraintViolationError。"""
        try:
            self._conn.execute(
                """
                INSERT INTO content_unit (
                    id, path, title, content_type, source_url, rating,
                    cover_path, status, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    unit.id,
                    unit.path,
                    unit.title,
                    unit.content_type,
                    unit.source_url,
                    unit.rating,
                    unit.cover_path,
                    unit.status,
                    unit.notes,
                    unit.created_at,
                    unit.updated_at,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise ConstraintViolationError(f"无法创建 ContentUnit：{e}") from e
        except sqlite3.Error as e:
            raise RepositoryError(f"无法创建 ContentUnit：{e}") from e
        return self.get_by_id(unit.id)  # type: ignore[return-value]

    def get_by_id(self, unit_id: str) -> ContentUnit | None:
        """按 ID 查询；不存在返回 None。"""
        try:
            row = self._conn.execute(
                "SELECT * FROM content_unit WHERE id = ?",
                (unit_id,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法查询 ContentUnit：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def get_by_path(self, path: str) -> ContentUnit | None:
        """按 path 查询；不存在返回 None。"""
        try:
            row = self._conn.execute(
                "SELECT * FROM content_unit WHERE path = ?",
                (path,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法按 path 查询 ContentUnit：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def list_by_path_prefix(self, prefix: str) -> list[ContentUnit]:
        """返回 path 以 prefix 开头（含 prefix 自身）的 ContentUnit。

        用于"目录下的内容单元"查询。prefix 应为目录路径（不含尾部分隔符）。
        匹配规则：path == prefix OR path LIKE 'prefix/%'。
        """
        try:
            rows = self._conn.execute(
                "SELECT * FROM content_unit WHERE path = ? OR path LIKE ? ORDER BY path",
                (prefix, f"{prefix}/%"),
            ).fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法列出 ContentUnit：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def list_all(self) -> list[ContentUnit]:
        """返回全部 ContentUnit，按 path 排序。"""
        try:
            rows = self._conn.execute("SELECT * FROM content_unit ORDER BY path").fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法列出 ContentUnit：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def update(self, unit: ContentUnit) -> ContentUnit:
        """全字段更新。实体不存在时抛 NotFoundError。"""
        try:
            cur = self._conn.execute(
                """
                UPDATE content_unit SET
                    path = ?,
                    title = ?,
                    content_type = ?,
                    source_url = ?,
                    rating = ?,
                    cover_path = ?,
                    status = ?,
                    notes = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    unit.path,
                    unit.title,
                    unit.content_type,
                    unit.source_url,
                    unit.rating,
                    unit.cover_path,
                    unit.status,
                    unit.notes,
                    unit.updated_at,
                    unit.id,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise ConstraintViolationError(f"无法更新 ContentUnit：{e}") from e
        except sqlite3.Error as e:
            raise RepositoryError(f"无法更新 ContentUnit：{e}") from e
        if cur.rowcount == 0:
            raise NotFoundError(f"ContentUnit 不存在：{unit.id}")
        return self.get_by_id(unit.id)  # type: ignore[return-value]

    def delete(self, unit_id: str) -> None:
        """按 ID 删除。不存在抛 NotFoundError。"""
        try:
            cur = self._conn.execute(
                "DELETE FROM content_unit WHERE id = ?",
                (unit_id,),
            )
        except sqlite3.Error as e:
            raise RepositoryError(f"无法删除 ContentUnit：{e}") from e
        if cur.rowcount == 0:
            raise NotFoundError(f"ContentUnit 不存在：{unit_id}")

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> ContentUnit:
        return ContentUnit(
            id=row["id"],
            path=row["path"],
            title=row["title"],
            content_type=row["content_type"],
            source_url=row["source_url"],
            rating=row["rating"],
            cover_path=row["cover_path"],
            status=row["status"],
            notes=row["notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
