"""migrations 模块测试。

补充 test_db.py 中未覆盖的迁移函数行为。
覆盖 v0→v1 与 v1→v2 迁移。
"""

from __future__ import annotations

import sqlite3

from infrastructure.db import CURRENT_SCHEMA_VERSION, init_db
from infrastructure.migrations import (
    MIGRATIONS,
    migrate_v0_to_v1,
    migrate_v1_to_v2,
)


def test_migrations_sorted_by_target() -> None:
    """MIGRATIONS 列表应按 target 升序可排序（init_db 内部排序）。"""
    targets = [t for t, _ in MIGRATIONS]
    assert targets == sorted(targets)
    assert len(MIGRATIONS) >= 2
    assert MIGRATIONS[0][0] == 1
    assert MIGRATIONS[1][0] == 2


def test_current_schema_version_is_two() -> None:
    """当前 schema 版本应为 2。"""
    assert CURRENT_SCHEMA_VERSION == 2


def test_migrate_v0_to_v1_idempotent() -> None:
    """迁移函数本身幂等（CREATE TABLE IF NOT EXISTS）。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        migrate_v0_to_v1(conn)
        # 再次调用不应报错
        migrate_v0_to_v1(conn)

        # 业务表存在
        for table in ("mod_item", "file_asset", "folder_node", "operation_log"):
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            assert row is not None

        # 索引存在
        for idx in (
            "idx_file_asset_mod_item_id",
            "idx_mod_item_category_folder_id",
            "idx_folder_node_parent_id",
            "idx_operation_log_status",
        ):
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (idx,),
            ).fetchone()
            assert row is not None
    finally:
        conn.close()


def test_migrate_v0_to_v1_creates_check_constraints() -> None:
    """CHECK 约束应生效。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        migrate_v0_to_v1(conn)

        # 非法 asset_kind 应被拒绝
        try:
            conn.execute(
                "INSERT INTO file_asset (id, real_path, path_key, filename, extension, "
                "asset_kind, role, size_bytes, modified_at, imported_at) "
                "VALUES ('x', 'p', 'k', 'f', '', 'invalid', 'main_mod', 0, 't', 't')"
            )
            raise AssertionError("应拒绝非法 asset_kind")
        except sqlite3.IntegrityError:
            pass

        # 非法 role 应被拒绝
        try:
            conn.execute(
                "INSERT INTO file_asset (id, real_path, path_key, filename, extension, "
                "asset_kind, role, size_bytes, modified_at, imported_at) "
                "VALUES ('x', 'p', 'k', 'f', '', 'file', 'invalid_role', 0, 't', 't')"
            )
            raise AssertionError("应拒绝非法 role")
        except sqlite3.IntegrityError:
            pass

        # 非法 conflict_policy（B3：仅 ask）应被拒绝
        try:
            conn.execute(
                "INSERT INTO operation_log (id, operation_type, status, conflict_policy, "
                "created_at) VALUES ('x', 'move', 'planned', 'overwrite', 't')"
            )
            raise AssertionError("应拒绝非法 conflict_policy")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_migrate_v1_to_v2_creates_managed_root_table() -> None:
    """v1→v2 迁移应创建 managed_root 表与索引。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        migrate_v0_to_v1(conn)
        migrate_v1_to_v2(conn)

        # managed_root 表存在
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='managed_root'"
        ).fetchone()
        assert row is not None

        # 索引存在
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_managed_root_path_key'"
        ).fetchone()
        assert row is not None

        # 验证列结构
        cols = {r["name"]: r["type"] for r in conn.execute("PRAGMA table_info(managed_root)")}
        assert "id" in cols
        assert "real_path" in cols
        assert "path_key" in cols
        assert "display_name" in cols
        assert "created_at" in cols
        assert "updated_at" in cols
        assert cols["real_path"] == "TEXT"
        assert cols["path_key"] == "TEXT"
    finally:
        conn.close()


def test_migrate_v1_to_v2_idempotent() -> None:
    """v1→v2 迁移函数本身幂等。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        migrate_v0_to_v1(conn)
        migrate_v1_to_v2(conn)
        # 再次调用不应报错
        migrate_v1_to_v2(conn)

        # 表仍存在
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='managed_root'"
        ).fetchone()
        assert row is not None
    finally:
        conn.close()


def test_migrate_v1_to_v2_path_key_unique_constraint() -> None:
    """managed_root.path_key 唯一约束生效。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        migrate_v0_to_v1(conn)
        migrate_v1_to_v2(conn)

        conn.execute(
            "INSERT INTO managed_root (id, real_path, path_key, display_name, "
            "created_at, updated_at) VALUES ('a', '/p', 'k', 'n', 't', 't')"
        )
        try:
            conn.execute(
                "INSERT INTO managed_root (id, real_path, path_key, display_name, "
                "created_at, updated_at) VALUES ('b', '/p2', 'k', 'n2', 't', 't')"
            )
            raise AssertionError("应拒绝重复 path_key")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_init_db_migrates_from_v0_to_v2(tmp_path) -> None:
    """init_db 从空数据库迁移到 v2。"""
    db_path = tmp_path / "test.db"
    version = init_db(db_path)
    assert version == CURRENT_SCHEMA_VERSION
    assert version == 2

    # 验证 managed_root 表可用
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='managed_root'"
        ).fetchone()
        assert row is not None
    finally:
        conn.close()


def test_init_db_idempotent_at_v2(tmp_path) -> None:
    """init_db 在已迁移到 v2 的数据库上重复调用应保持 v2，不报错。"""
    db_path = tmp_path / "test.db"
    version1 = init_db(db_path)
    version2 = init_db(db_path)
    assert version1 == version2 == 2
