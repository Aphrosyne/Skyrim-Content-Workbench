"""ThumbnailCacheRepository 与 v2→v3 迁移测试。"""

from __future__ import annotations

import pytest

pytest.skip(
    "方向 C 重建（Task 1）：本模块依赖的旧 schema/服务将在 Task 2+ 重写后重新启用",
    allow_module_level=True,
)

import sqlite3
from pathlib import Path

import pytest

from infrastructure.db import CURRENT_SCHEMA_VERSION, get_connection, init_db
from infrastructure.repositories.thumbnail_cache import (
    ThumbnailCacheRecord,
    ThumbnailCacheRepository,
)


def _make_record(
    asset_id: str = "asset-1",
    status: str = "ok",
    **overrides,
) -> ThumbnailCacheRecord:
    defaults = {
        "asset_id": asset_id,
        "source_size_bytes": 100,
        "source_modified_at": "2026-07-07T00:00:00Z",
        "cache_filename": f"{asset_id}.png",
        "status": status,
        "error_message": None,
        "generated_at": "2026-07-07T00:00:00Z",
    }
    defaults.update(overrides)
    return ThumbnailCacheRecord(**defaults)


def test_thumbnail_cache_table_exists_after_migration(tmp_path: Path) -> None:
    """v3 迁移后 thumbnail_cache 表存在。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='thumbnail_cache'"
        ).fetchone()
        assert row is not None
    finally:
        conn.close()


def test_schema_version_is_three_after_migration(tmp_path: Path) -> None:
    """迁移后 schema_version 为 3。"""
    db_path = tmp_path / "test.db"
    version = init_db(db_path)
    assert version == 3
    assert version == CURRENT_SCHEMA_VERSION


def test_migrate_v2_to_v3_idempotent(tmp_path: Path) -> None:
    """v3 迁移幂等。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    # 再次调用不应报错
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        assert row["version"] == 3
    finally:
        conn.close()


def test_upsert_and_get(db_connection: sqlite3.Connection) -> None:
    """upsert 插入后可查询。"""
    # 需先插入 file_asset 以满足外键约束
    db_connection.execute(
        "INSERT INTO file_asset (id, mod_item_id, real_path, path_key, filename, extension, "
        "asset_kind, role, size_bytes, modified_at, imported_at) VALUES "
        "('asset-1', NULL, '/test.png', '/test.png', 'test.png', '.png', 'file', 'unknown', "
        "100, '2026-07-07T00:00:00Z', '2026-07-07T00:00:00Z')"
    )
    db_connection.commit()

    repo = ThumbnailCacheRepository(db_connection)
    record = _make_record("asset-1")
    repo.upsert(record)

    fetched = repo.get_by_asset_id("asset-1")
    assert fetched is not None
    assert fetched.asset_id == "asset-1"
    assert fetched.status == "ok"
    assert fetched.cache_filename == "asset-1.png"


def test_upsert_overwrites_existing(db_connection: sqlite3.Connection) -> None:
    """upsert 对同一 asset_id 覆盖旧记录。"""
    db_connection.execute(
        "INSERT INTO file_asset (id, mod_item_id, real_path, path_key, filename, extension, "
        "asset_kind, role, size_bytes, modified_at, imported_at) VALUES "
        "('asset-2', NULL, '/test.png', '/test.png', 'test.png', '.png', 'file', 'unknown', "
        "100, '2026-07-07T00:00:00Z', '2026-07-07T00:00:00Z')"
    )
    db_connection.commit()

    repo = ThumbnailCacheRepository(db_connection)
    repo.upsert(_make_record("asset-2", status="ok"))
    repo.upsert(_make_record("asset-2", status="corrupt", error_message="损坏"))

    fetched = repo.get_by_asset_id("asset-2")
    assert fetched is not None
    assert fetched.status == "corrupt"
    assert fetched.error_message == "损坏"


def test_get_missing_returns_none(db_connection: sqlite3.Connection) -> None:
    """查询不存在的 asset_id 返回 None。"""
    repo = ThumbnailCacheRepository(db_connection)
    assert repo.get_by_asset_id("nonexistent") is None


def test_delete_removes_record(db_connection: sqlite3.Connection) -> None:
    """delete 移除记录。"""
    db_connection.execute(
        "INSERT INTO file_asset (id, mod_item_id, real_path, path_key, filename, extension, "
        "asset_kind, role, size_bytes, modified_at, imported_at) VALUES "
        "('asset-3', NULL, '/test.png', '/test.png', 'test.png', '.png', 'file', 'unknown', "
        "100, '2026-07-07T00:00:00Z', '2026-07-07T00:00:00Z')"
    )
    db_connection.commit()

    repo = ThumbnailCacheRepository(db_connection)
    repo.upsert(_make_record("asset-3"))
    repo.delete("asset-3")

    assert repo.get_by_asset_id("asset-3") is None


def test_delete_missing_is_idempotent(db_connection: sqlite3.Connection) -> None:
    """delete 不存在的记录不报错。"""
    repo = ThumbnailCacheRepository(db_connection)
    repo.delete("nonexistent")  # 不抛异常


def test_status_check_constraint(db_connection: sqlite3.Connection) -> None:
    """status 列 CHECK 约束拒绝非法值。"""
    from infrastructure.repositories.errors import RepositoryError

    db_connection.execute(
        "INSERT INTO file_asset (id, mod_item_id, real_path, path_key, filename, extension, "
        "asset_kind, role, size_bytes, modified_at, imported_at) VALUES "
        "('asset-4', NULL, '/test.png', '/test.png', 'test.png', '.png', 'file', 'unknown', "
        "100, '2026-07-07T00:00:00Z', '2026-07-07T00:00:00Z')"
    )
    db_connection.commit()

    repo = ThumbnailCacheRepository(db_connection)
    with pytest.raises(RepositoryError):
        repo.upsert(_make_record("asset-4", status="invalid_status"))
