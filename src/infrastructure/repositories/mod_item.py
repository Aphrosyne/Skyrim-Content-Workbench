"""ModItemRepository。

负责 ModItem dataclass 与 mod_item 表之间的转换。
不访问文件系统；仅读写 SQLite。
"""

from __future__ import annotations

import json
import logging
import sqlite3

from domain.models import ModItem
from infrastructure.repositories.errors import (
    ConstraintViolationError,
    NotFoundError,
    RepositoryError,
)

logger = logging.getLogger(__name__)


class ModItemRepository:
    """ModItem 的 CRUD。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, item: ModItem) -> ModItem:
        """插入 ModItem。tags 序列化为 JSON 数组。"""
        try:
            self._conn.execute(
                """
                INSERT INTO mod_item (
                    id, display_name, description, source_url,
                    category_folder_id, tags, cover_asset_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.display_name,
                    item.description,
                    item.source_url,
                    item.category_folder_id,
                    json.dumps(sorted(item.tags), ensure_ascii=False),
                    item.cover_asset_id,
                    item.created_at,
                    item.updated_at,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise ConstraintViolationError(f"无法创建 ModItem：{e}") from e
        except sqlite3.Error as e:
            raise RepositoryError(f"无法创建 ModItem：{e}") from e
        return self.get_by_id(item.id)  # type: ignore[return-value]

    def get_by_id(self, item_id: str) -> ModItem | None:
        """按 ID 查询；不存在返回 None。"""
        try:
            row = self._conn.execute(
                "SELECT * FROM mod_item WHERE id = ?",
                (item_id,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法查询 ModItem：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def list_all(self) -> list[ModItem]:
        """返回全部 ModItem。"""
        try:
            rows = self._conn.execute("SELECT * FROM mod_item ORDER BY created_at").fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法列出 ModItem：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def update(self, item: ModItem) -> ModItem:
        """全字段更新。实体不存在时抛 NotFoundError。"""
        try:
            cur = self._conn.execute(
                """
                UPDATE mod_item SET
                    display_name = ?,
                    description = ?,
                    source_url = ?,
                    category_folder_id = ?,
                    tags = ?,
                    cover_asset_id = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    item.display_name,
                    item.description,
                    item.source_url,
                    item.category_folder_id,
                    json.dumps(sorted(item.tags), ensure_ascii=False),
                    item.cover_asset_id,
                    item.updated_at,
                    item.id,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise ConstraintViolationError(f"无法更新 ModItem：{e}") from e
        except sqlite3.Error as e:
            raise RepositoryError(f"无法更新 ModItem：{e}") from e
        if cur.rowcount == 0:
            raise NotFoundError(f"ModItem 不存在：{item.id}")
        return self.get_by_id(item.id)  # type: ignore[return-value]

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> ModItem:
        return ModItem(
            id=row["id"],
            display_name=row["display_name"],
            description=row["description"],
            source_url=row["source_url"],
            category_folder_id=row["category_folder_id"],
            tags=set(json.loads(row["tags"])),
            cover_asset_id=row["cover_asset_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
