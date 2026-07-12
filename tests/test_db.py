"""db 初始化与迁移测试。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from infrastructure.db import CURRENT_SCHEMA_VERSION, get_connection, init_db


def test_init_db_fresh_upgrades_to_current(temp_app_data: Path) -> None:
    """全新数据库应升级到 CURRENT_SCHEMA_VERSION。"""
    db_path = temp_app_data / "app.db"
    version = init_db(db_path)
    assert version == CURRENT_SCHEMA_VERSION
    assert db_path.exists()

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        assert int(row[0]) == CURRENT_SCHEMA_VERSION


def test_init_db_creates_business_tables(temp_app_data: Path) -> None:
    """v4 应包含方向 C 重建后的业务表，且旧表应不存在。"""
    db_path = temp_app_data / "app.db"
    init_db(db_path)

    with get_connection(db_path) as conn:
        # v4 新表应存在
        for table in (
            "content_unit",
            "tag_category",
            "tag",
            "content_unit_tag",
            "operation_history",
            "folder_cache",
            "thumbnail_cache",
            "managed_root",
        ):
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            assert row is not None, f"表 {table} 应存在"

        # v3 旧表应已移除
        for table in ("mod_item", "file_asset", "folder_node", "operation_log"):
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            assert row is None, f"旧表 {table} 应被移除"


def test_init_db_idempotent(temp_app_data: Path) -> None:
    """重复调用不报错，版本不变。"""
    db_path = temp_app_data / "app.db"
    init_db(db_path)
    version = init_db(db_path)
    assert version == CURRENT_SCHEMA_VERSION

    with get_connection(db_path) as conn:
        # schema_version 应只有一条最终版本记录（按版本降序取首条）
        # 注意：每次 init_db 不会重复插入已有版本
        rows = conn.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
        versions = [int(r[0]) for r in rows]
        assert versions[-1] == CURRENT_SCHEMA_VERSION
        # 不应出现重复的最终版本号
        assert versions.count(CURRENT_SCHEMA_VERSION) == 1


def test_init_db_upgrades_from_v0_baseline(temp_app_data: Path) -> None:
    """模拟 v0 DB（仅 schema_version 表，无业务表），
    运行 init_db 后应迁移到当前版本（v4）。"""
    db_path = temp_app_data / "app.db"
    # 手动构造 v0 状态
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE schema_version (
                version INTEGER NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute("INSERT INTO schema_version (version) VALUES (0)")

    # 运行 init_db 应执行 v0→current 全部迁移
    version = init_db(db_path)
    assert version == CURRENT_SCHEMA_VERSION

    with get_connection(db_path) as conn:
        # v4 业务表应已创建
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='content_unit'"
        ).fetchone()
        assert row is not None
        # schema_version 应记录从 v0 到 current 的版本轨迹
        rows = conn.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
        versions = [int(r[0]) for r in rows]
        assert 0 in versions
        assert CURRENT_SCHEMA_VERSION in versions


def test_init_db_at_current_version_skips_migration(temp_app_data: Path) -> None:
    """已是当前版本的 DB 再次 init_db 不应重复迁移。"""
    db_path = temp_app_data / "app.db"
    init_db(db_path)

    # 记录迁移次数（通过 schema_version 行数）
    with get_connection(db_path) as conn:
        before = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]

    init_db(db_path)

    with get_connection(db_path) as conn:
        after = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
        assert after == before


def test_foreign_keys_enabled(temp_app_data: Path) -> None:
    """连接应启用外键约束。"""
    db_path = temp_app_data / "app.db"
    init_db(db_path)
    with get_connection(db_path) as conn:
        value = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert value == 1


def test_row_factory_works(db_connection: sqlite3.Connection) -> None:
    """db_connection fixture 应使用 Row 工厂。"""
    row = db_connection.execute("SELECT 1 AS v").fetchone()
    assert row["v"] == 1
