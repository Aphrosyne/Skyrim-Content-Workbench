"""migrations 模块测试。

补充 test_db.py 中未覆盖的迁移函数行为。
"""

from __future__ import annotations

import sqlite3

from infrastructure.migrations import MIGRATIONS, migrate_v0_to_v1


def test_migrations_sorted_by_target() -> None:
    """MIGRATIONS 列表应按 target 升序可排序（init_db 内部排序）。"""
    targets = [t for t, _ in MIGRATIONS]
    assert targets == sorted(targets)
    assert len(MIGRATIONS) >= 1
    assert MIGRATIONS[0][0] == 1


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
