"""ContentUnitRepository。

负责 ContentUnit dataclass 与 content_unit 表之间的转换。
不访问文件系统；path 仅作为字符串存储。
"""

from __future__ import annotations

import logging
import os
import sqlite3

from domain.models import ContentUnit
from infrastructure.path_utils import make_path_key
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
                    id, path, title, content_type, source_url,
                    cover_path, status, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    unit.id,
                    unit.path,
                    unit.title,
                    unit.content_type,
                    unit.source_url,
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

    def list_by_path_prefix_normalized(self, prefix: str) -> list[ContentUnit]:
        """返回 path 等于 prefix 或位于 prefix 子树下的 ContentUnit（含 prefix 自身）。

        TD-H7 修复：原 ``list_by_path_prefix`` 在分隔符分歧场景下漏匹配子路径
        （数据库存储的路径与查询路径分隔符不一致时，LIKE 无法匹配）。本方法用
        ``make_path_key`` 归一化后做字符串前缀比较，符合 AGENTS 规则 9
        （路径比较统一使用 ``make_path_key()``），跨平台一致。

        旧 ``list_by_path_prefix`` 已在 TD-L20 清理中删除（生产代码 v0.20.1
        全部迁移到本方法，无外部调用）。

        匹配规则：
            unit.path 归一化后 == prefix 归一化后
            或 unit.path 归一化后以 ``{prefix}{sep}`` 开头（目录层级前缀，避免
            "D:/Mods" 误匹配 "D:/Mods2"）。

        Args:
            prefix: 目录路径（不含尾部分隔符）。

        Returns:
            匹配的 ContentUnit 列表，按 path 排序。
        """
        target_key = make_path_key(prefix)
        sep = os.sep
        target_prefix = target_key.rstrip(sep) + sep
        try:
            rows = self._conn.execute("SELECT * FROM content_unit ORDER BY path").fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法列出 ContentUnit：{e}") from e
        result: list[ContentUnit] = []
        for row in rows:
            unit = self._row_to_model(row)
            unit_key = make_path_key(unit.path)
            if unit_key == target_key or unit_key.startswith(target_prefix):
                result.append(unit)
        return result

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
        """按 ID 删除。不存在抛 NotFoundError。

        级联清理 content_unit_tag 表中所有引用该 unit_id 的关联记录，
        避免 FK 违约（content_unit_tag.content_unit_id REFERENCES content_unit(id)，
        但 schema 未声明 ON DELETE CASCADE）。

        写操作不自提交，由 application 层控制事务边界。
        """
        try:
            # 先清理 content_unit_tag 关联（避免 FK 违约）
            self._conn.execute(
                "DELETE FROM content_unit_tag WHERE content_unit_id = ?",
                (unit_id,),
            )
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
            cover_path=row["cover_path"],
            status=row["status"],
            notes=row["notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
