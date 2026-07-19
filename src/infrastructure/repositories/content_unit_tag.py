"""ContentUnitTagRepository。

负责 content_unit_tag 关联表的 CRUD。
本表无独立 dataclass（关联表仅含两列外键），直接使用元组 / 命名结构。

约束：
- (content_unit_id, tag_id) 为联合主键，重复 attach 由调用方判断（本仓库 INSERT OR IGNORE 幂等）。
- 不删除 content_unit 或 tag 实体，仅操作关联表。
"""

from __future__ import annotations

import logging
import sqlite3

from infrastructure.repositories.errors import RepositoryError

logger = logging.getLogger(__name__)


class ContentUnitTagRepository:
    """content_unit_tag 关联表的 CRUD。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def attach(self, content_unit_id: str, tag_id: str) -> bool:
        """关联内容单元与标签。

        使用 INSERT OR IGNORE 实现幂等：重复 attach 同一对不会抛 ConstraintViolationError，
        返回 True 表示新增关联，False 表示已存在（未变更）。

        写操作不自提交，由 application 层控制事务边界。
        """
        try:
            cur = self._conn.execute(
                """
                INSERT OR IGNORE INTO content_unit_tag (content_unit_id, tag_id)
                VALUES (?, ?)
                """,
                (content_unit_id, tag_id),
            )
        except sqlite3.Error as e:
            raise RepositoryError(f"无法关联 ContentUnit-Tag：{e}") from e
        return cur.rowcount > 0

    def detach(self, content_unit_id: str, tag_id: str) -> bool:
        """移除关联。返回 True 表示实际删除一行，False 表示原本就无关联。"""
        try:
            cur = self._conn.execute(
                """
                DELETE FROM content_unit_tag
                WHERE content_unit_id = ? AND tag_id = ?
                """,
                (content_unit_id, tag_id),
            )
        except sqlite3.Error as e:
            raise RepositoryError(f"无法移除 ContentUnit-Tag 关联：{e}") from e
        return cur.rowcount > 0

    def detach_all_by_content_unit(self, content_unit_id: str) -> int:
        """移除指定内容单元的所有标签关联。返回删除的行数。"""
        try:
            cur = self._conn.execute(
                "DELETE FROM content_unit_tag WHERE content_unit_id = ?",
                (content_unit_id,),
            )
        except sqlite3.Error as e:
            raise RepositoryError(f"无法按 content_unit_id 移除关联：{e}") from e
        return cur.rowcount

    def detach_all_by_tag(self, tag_id: str) -> int:
        """移除指定标签的所有内容单元关联。返回删除的行数。"""
        try:
            cur = self._conn.execute(
                "DELETE FROM content_unit_tag WHERE tag_id = ?",
                (tag_id,),
            )
        except sqlite3.Error as e:
            raise RepositoryError(f"无法按 tag_id 移除关联：{e}") from e
        return cur.rowcount

    def detach_all_by_category(self, category_id: str) -> int:
        """移除指定分类下所有标签的 content_unit 关联。

        通过子查询找出该分类下所有 tag_id，再删除 content_unit_tag 中引用这些 tag_id 的记录。
        """
        try:
            cur = self._conn.execute(
                """
                DELETE FROM content_unit_tag
                WHERE tag_id IN (
                    SELECT id FROM tag WHERE category_id = ?
                )
                """,
                (category_id,),
            )
        except sqlite3.Error as e:
            raise RepositoryError(f"无法按 category_id 级联移除关联：{e}") from e
        return cur.rowcount

    def list_tag_ids_by_content_unit(self, content_unit_id: str) -> list[str]:
        """返回指定内容单元关联的所有 tag_id（按 tag_id 排序）。"""
        try:
            rows = self._conn.execute(
                "SELECT tag_id FROM content_unit_tag WHERE content_unit_id = ? ORDER BY tag_id",
                (content_unit_id,),
            ).fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法按 content_unit_id 查询 tag_id 列表：{e}") from e
        return [r["tag_id"] for r in rows]

    def list_content_unit_ids_by_tag(self, tag_id: str) -> list[str]:
        """返回指定标签关联的所有 content_unit_id（按 content_unit_id 排序）。"""
        try:
            rows = self._conn.execute(
                "SELECT content_unit_id FROM content_unit_tag WHERE tag_id = ? "
                "ORDER BY content_unit_id",
                (tag_id,),
            ).fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法按 tag_id 查询 content_unit_id 列表：{e}") from e
        return [r["content_unit_id"] for r in rows]

    def count_by_tag(self, tag_id: str) -> int:
        """返回指定标签关联的内容单元数量。"""
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM content_unit_tag WHERE tag_id = ?",
                (tag_id,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法统计 tag 关联数量：{e}") from e
        return int(row["cnt"]) if row is not None else 0

    def count_by_category(self, category_id: str) -> int:
        """返回指定分类下所有标签关联的内容单元数量总和。"""
        try:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS cnt FROM content_unit_tag
                WHERE tag_id IN (
                    SELECT id FROM tag WHERE category_id = ?
                )
                """,
                (category_id,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法按 category_id 统计关联数量：{e}") from e
        return int(row["cnt"]) if row is not None else 0

    def is_attached(self, content_unit_id: str, tag_id: str) -> bool:
        """检查指定关联是否存在。"""
        try:
            row = self._conn.execute(
                "SELECT 1 FROM content_unit_tag WHERE content_unit_id = ? AND tag_id = ? LIMIT 1",
                (content_unit_id, tag_id),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法检查关联存在性：{e}") from e
        return row is not None
