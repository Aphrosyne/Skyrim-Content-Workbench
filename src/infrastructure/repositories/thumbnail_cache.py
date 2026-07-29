"""ThumbnailCacheRepository。

负责 ThumbnailCache dataclass 与 thumbnail_cache 表之间的转换。
本表无独立 service 层封装，由 ThumbnailService 直接调用。

schema v7 起表结构（Task 1a）：
    content_unit_id TEXT NOT NULL,
    size INTEGER NOT NULL,                  -- 缓存档位（64 旧档/256/512）
    source_size_bytes INTEGER NOT NULL,
    source_modified_at TEXT NOT NULL,
    cache_filename TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('ok','missing','corrupt','unsupported','error')),
    error_message TEXT,
    generated_at TEXT NOT NULL,
    PRIMARY KEY (content_unit_id, size)     -- 复合主键

约束：
- 复合主键为 (content_unit_id, size)，一个内容单元可有多个档位缓存。
- 不删除 content_unit 实体，仅操作缓存表。
- 写操作不自提交，由 application 层控制事务边界。
"""

from __future__ import annotations

import logging
import sqlite3

from domain.models import ThumbnailCache
from infrastructure.repositories.errors import RepositoryError

logger = logging.getLogger(__name__)


class ThumbnailCacheRepository:
    """thumbnail_cache 表的 CRUD。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_by_id_and_size(self, content_unit_id: str, size: int) -> ThumbnailCache | None:
        """按 (content_unit_id, size) 查询缓存记录；不存在返回 None。"""
        try:
            row = self._conn.execute(
                "SELECT * FROM thumbnail_cache WHERE content_unit_id = ? AND size = ?",
                (content_unit_id, size),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法查询 ThumbnailCache：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def upsert(self, cache: ThumbnailCache) -> None:
        """插入或更新缓存记录（INSERT OR REPLACE）。

        - 复合主键 (content_unit_id, size) 已存在则整体覆盖。
        - 写操作不自提交，由 application 层控制事务边界。
        """
        try:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO thumbnail_cache
                    (content_unit_id, size, source_size_bytes, source_modified_at,
                     cache_filename, status, error_message, generated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cache.content_unit_id,
                    cache.size,
                    cache.source_size_bytes,
                    cache.source_modified_at,
                    cache.cache_filename,
                    cache.status,
                    cache.error_message,
                    cache.generated_at,
                ),
            )
        except sqlite3.Error as e:
            raise RepositoryError(f"无法写入 ThumbnailCache：{e}") from e

    def delete(self, content_unit_id: str) -> bool:
        """删除该 content_unit 的所有档位缓存记录。

        返回 True 表示实际删除至少一行，False 表示原本就无记录。
        """
        try:
            cur = self._conn.execute(
                "DELETE FROM thumbnail_cache WHERE content_unit_id = ?",
                (content_unit_id,),
            )
        except sqlite3.Error as e:
            raise RepositoryError(f"无法删除 ThumbnailCache：{e}") from e
        return cur.rowcount > 0

    def list_all(self) -> list[ThumbnailCache]:
        """返回所有缓存记录（仅供 GC 使用，按 content_unit_id 排序）。"""
        try:
            rows = self._conn.execute(
                "SELECT * FROM thumbnail_cache ORDER BY content_unit_id"
            ).fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法列出 ThumbnailCache：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def list_by_unit(self, content_unit_id: str) -> list[ThumbnailCache]:
        """返回指定 content_unit 的所有档位缓存记录。"""
        try:
            rows = self._conn.execute(
                "SELECT * FROM thumbnail_cache WHERE content_unit_id = ? ORDER BY size",
                (content_unit_id,),
            ).fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法查询 ThumbnailCache：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def list_by_unit_ids(self, content_unit_ids: list[str]) -> dict[str, ThumbnailCache]:
        """批量查询多个 content_unit_id 的 256 档缓存记录。

        - 空 input 返回空 dict（不执行 SQL）。
        - 命中记录以 {content_unit_id: ThumbnailCache} 形式返回。
        - 未知 unit_id 不在结果中出现（不抛错）。
        - 默认查询 256 档（列表视图使用）；其他档位请用 list_by_unit。
        """
        if not content_unit_ids:
            return {}
        # 使用 IN(?,?,...) 形式。unit_id 数量级有限，不分批。
        placeholders = ",".join("?" * len(content_unit_ids))
        try:
            rows = self._conn.execute(
                f"SELECT * FROM thumbnail_cache WHERE content_unit_id IN ({placeholders}) "
                "AND size = 256",
                content_unit_ids,
            ).fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法批量查询 ThumbnailCache：{e}") from e
        return {r["content_unit_id"]: self._row_to_model(r) for r in rows}

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> ThumbnailCache:
        return ThumbnailCache(
            content_unit_id=row["content_unit_id"],
            size=row["size"],
            source_size_bytes=row["source_size_bytes"],
            source_modified_at=row["source_modified_at"],
            cache_filename=row["cache_filename"],
            status=row["status"],
            generated_at=row["generated_at"],
            error_message=row["error_message"],
        )
