"""TagRepository。

负责 Tag dataclass 与 tag 表之间的转换。
不访问文件系统；name 仅作为字符串存储。

schema v6（Stage 4 Task 1）起 tag (name, category_id) 有 UNIQUE 约束
（通过 idx_tag_name_category_unique 索引实现）——同一分类下不能重名，
不同分类下可以重名。
"""

from __future__ import annotations

import logging
import sqlite3

from domain.models import Tag
from infrastructure.repositories.errors import (
    ConstraintViolationError,
    NotFoundError,
    RepositoryError,
)

logger = logging.getLogger(__name__)


class TagRepository:
    """Tag 的 CRUD。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, tag: Tag) -> Tag:
        """插入 Tag。(name, category_id) 唯一冲突抛 ConstraintViolationError。"""
        try:
            self._conn.execute(
                """
                INSERT INTO tag (id, name, category_id)
                VALUES (?, ?, ?)
                """,
                (tag.id, tag.name, tag.category_id),
            )
        except sqlite3.IntegrityError as e:
            raise ConstraintViolationError(f"无法创建 Tag：{e}") from e
        except sqlite3.Error as e:
            raise RepositoryError(f"无法创建 Tag：{e}") from e
        return self.get_by_id(tag.id)  # type: ignore[return-value]

    def get_by_id(self, tag_id: str) -> Tag | None:
        """按 ID 查询；不存在返回 None。"""
        try:
            row = self._conn.execute(
                "SELECT * FROM tag WHERE id = ?",
                (tag_id,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法查询 Tag：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def get_by_name_in_category(self, name: str, category_id: str) -> Tag | None:
        """按 (name, category_id) 查询；不存在返回 None。用于去重检查。"""
        try:
            row = self._conn.execute(
                "SELECT * FROM tag WHERE name = ? AND category_id = ?",
                (name, category_id),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法按 name 查询 Tag：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def list_all(self) -> list[Tag]:
        """返回全部 Tag，按 name 排序。"""
        try:
            rows = self._conn.execute("SELECT * FROM tag ORDER BY name").fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法列出 Tag：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def list_by_category(self, category_id: str) -> list[Tag]:
        """返回指定分类下的全部 Tag，按 name 排序。"""
        try:
            rows = self._conn.execute(
                "SELECT * FROM tag WHERE category_id = ? ORDER BY name",
                (category_id,),
            ).fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法按 category_id 列出 Tag：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def list_by_ids(self, tag_ids: list[str]) -> list[Tag]:
        """按 ID 列表批量查询。忽略不存在的 ID。"""
        if not tag_ids:
            return []
        placeholders = ",".join("?" for _ in tag_ids)
        try:
            rows = self._conn.execute(
                f"SELECT * FROM tag WHERE id IN ({placeholders}) ORDER BY name",
                tag_ids,
            ).fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法按 ID 列表查询 Tag：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def update(self, tag: Tag) -> Tag:
        """全字段更新。实体不存在抛 NotFoundError；重名抛 ConstraintViolationError。"""
        try:
            cur = self._conn.execute(
                """
                UPDATE tag SET
                    name = ?,
                    category_id = ?
                WHERE id = ?
                """,
                (tag.name, tag.category_id, tag.id),
            )
        except sqlite3.IntegrityError as e:
            raise ConstraintViolationError(f"无法更新 Tag：{e}") from e
        except sqlite3.Error as e:
            raise RepositoryError(f"无法更新 Tag：{e}") from e
        if cur.rowcount == 0:
            raise NotFoundError(f"Tag 不存在：{tag.id}")
        return self.get_by_id(tag.id)  # type: ignore[return-value]

    def delete(self, tag_id: str) -> None:
        """按 ID 删除 Tag。

        级联清理 content_unit_tag 中引用该 tag_id 的关联由 application 层负责，
        避免 FK 违约（content_unit_tag.tag_id REFERENCES tag(id)）。

        实体不存在时抛 NotFoundError。写操作不自提交，由 application 层控制事务边界。
        """
        try:
            cur = self._conn.execute(
                "DELETE FROM tag WHERE id = ?",
                (tag_id,),
            )
        except sqlite3.Error as e:
            raise RepositoryError(f"无法删除 Tag：{e}") from e
        if cur.rowcount == 0:
            raise NotFoundError(f"Tag 不存在：{tag_id}")

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> Tag:
        return Tag(
            id=row["id"],
            name=row["name"],
            category_id=row["category_id"],
        )
