"""TagCategoryRepository。

负责 TagCategory dataclass 与 tag_category 表之间的转换。
不访问文件系统；name 仅作为字符串存储。

schema v6（Stage 4 Task 1）起 tag_category.name 有 UNIQUE 约束
（通过 idx_tag_category_name_unique 索引实现）。
"""

from __future__ import annotations

import logging
import sqlite3

from domain.models import TagCategory
from infrastructure.repositories.errors import (
    ConstraintViolationError,
    NotFoundError,
    RepositoryError,
)

logger = logging.getLogger(__name__)


class TagCategoryRepository:
    """TagCategory 的 CRUD。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, category: TagCategory) -> TagCategory:
        """插入 TagCategory。name 唯一冲突抛 ConstraintViolationError。

        写操作不自提交，由 application 层控制事务边界（与其他 Repository 一致）。
        """
        try:
            self._conn.execute(
                """
                INSERT INTO tag_category (id, name, color_hue)
                VALUES (?, ?, ?)
                """,
                (category.id, category.name, category.color_hue),
            )
        except sqlite3.IntegrityError as e:
            raise ConstraintViolationError(f"无法创建 TagCategory：{e}") from e
        except sqlite3.Error as e:
            raise RepositoryError(f"无法创建 TagCategory：{e}") from e
        return self.get_by_id(category.id)  # type: ignore[return-value]

    def get_by_id(self, category_id: str) -> TagCategory | None:
        """按 ID 查询；不存在返回 None。"""
        try:
            row = self._conn.execute(
                "SELECT * FROM tag_category WHERE id = ?",
                (category_id,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法查询 TagCategory：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def get_by_name(self, name: str) -> TagCategory | None:
        """按 name 查询；不存在返回 None。用于去重检查。"""
        try:
            row = self._conn.execute(
                "SELECT * FROM tag_category WHERE name = ?",
                (name,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法按 name 查询 TagCategory：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def list_all(self) -> list[TagCategory]:
        """返回全部 TagCategory，按 name 排序。"""
        try:
            rows = self._conn.execute("SELECT * FROM tag_category ORDER BY name").fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法列出 TagCategory：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def update(self, category: TagCategory) -> TagCategory:
        """全字段更新。实体不存在时抛 NotFoundError；重名抛 ConstraintViolationError。"""
        try:
            cur = self._conn.execute(
                """
                UPDATE tag_category SET
                    name = ?,
                    color_hue = ?
                WHERE id = ?
                """,
                (category.name, category.color_hue, category.id),
            )
        except sqlite3.IntegrityError as e:
            raise ConstraintViolationError(f"无法更新 TagCategory：{e}") from e
        except sqlite3.Error as e:
            raise RepositoryError(f"无法更新 TagCategory：{e}") from e
        if cur.rowcount == 0:
            raise NotFoundError(f"TagCategory 不存在：{category.id}")
        return self.get_by_id(category.id)  # type: ignore[return-value]

    def delete(self, category_id: str) -> None:
        """按 ID 删除 TagCategory。

        级联清理由 application 层负责（删除该分类下所有标签 + content_unit_tag 关联），
        避免 FK 违约（tag.category_id REFERENCES tag_category(id)）。

        实体不存在时抛 NotFoundError。写操作不自提交，由 application 层控制事务边界。
        """
        try:
            cur = self._conn.execute(
                "DELETE FROM tag_category WHERE id = ?",
                (category_id,),
            )
        except sqlite3.Error as e:
            raise RepositoryError(f"无法删除 TagCategory：{e}") from e
        if cur.rowcount == 0:
            raise NotFoundError(f"TagCategory 不存在：{category_id}")

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> TagCategory:
        return TagCategory(
            id=row["id"],
            name=row["name"],
            color_hue=row["color_hue"],
        )
