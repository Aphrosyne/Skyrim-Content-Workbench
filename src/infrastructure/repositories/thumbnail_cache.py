"""ThumbnailCacheRepository。

负责 thumbnail_cache 表的 CRUD。
不访问文件系统；仅读写数据库。
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from infrastructure.repositories.errors import RepositoryError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ThumbnailCacheRecord:
    """thumbnail_cache 表的领域表示。"""

    asset_id: str
    source_size_bytes: int
    source_modified_at: str
    cache_filename: str
    status: str  # 'ok' | 'missing' | 'corrupt' | 'unsupported' | 'error'
    error_message: str | None
    generated_at: str


class ThumbnailCacheRepository:
    """thumbnail_cache 表的 CRUD。

    使用 upsert 语义：同一 asset_id 只有一条记录，重复生成时覆盖。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_by_asset_id(self, asset_id: str) -> ThumbnailCacheRecord | None:
        """按 asset_id 查询；不存在返回 None。"""
        try:
            row = self._conn.execute(
                "SELECT * FROM thumbnail_cache WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法查询 thumbnail_cache：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def upsert(self, record: ThumbnailCacheRecord) -> ThumbnailCacheRecord:
        """插入或更新缓存记录（asset_id 为唯一键）。"""
        try:
            self._conn.execute(
                """
                INSERT INTO thumbnail_cache (
                    asset_id, source_size_bytes, source_modified_at,
                    cache_filename, status, error_message, generated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    source_size_bytes = excluded.source_size_bytes,
                    source_modified_at = excluded.source_modified_at,
                    cache_filename = excluded.cache_filename,
                    status = excluded.status,
                    error_message = excluded.error_message,
                    generated_at = excluded.generated_at
                """,
                (
                    record.asset_id,
                    record.source_size_bytes,
                    record.source_modified_at,
                    record.cache_filename,
                    record.status,
                    record.error_message,
                    record.generated_at,
                ),
            )
        except sqlite3.Error as e:
            raise RepositoryError(f"无法写入 thumbnail_cache：{e}") from e
        return record

    def delete(self, asset_id: str) -> None:
        """删除缓存记录。不存在时不报错（幂等）。"""
        try:
            self._conn.execute(
                "DELETE FROM thumbnail_cache WHERE asset_id = ?",
                (asset_id,),
            )
        except sqlite3.Error as e:
            raise RepositoryError(f"无法删除 thumbnail_cache：{e}") from e

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> ThumbnailCacheRecord:
        return ThumbnailCacheRecord(
            asset_id=row["asset_id"],
            source_size_bytes=int(row["source_size_bytes"]),
            source_modified_at=row["source_modified_at"],
            cache_filename=row["cache_filename"],
            status=row["status"],
            error_message=row["error_message"],
            generated_at=row["generated_at"],
        )
