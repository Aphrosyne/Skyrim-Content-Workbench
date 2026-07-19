"""migrations 模块测试。

覆盖 v0→v1 / v1→v2 / v2→v3 / v3→v4 / v4→v5 / v5→v6 迁移。
v3→v4 为方向 C 重建：新建 content_unit 等表，移除 mod_item / file_asset /
folder_node / operation_log，重建 thumbnail_cache（FK 改为 content_unit）。
v4→v5 新增 staging_area 表（阶段 3 Task 1 暂存区标记）。
v5→v6 移除 content_unit.rating 列 + 加 tag_category.name / tag(name, category_id)
UNIQUE 约束（阶段 4 Task 1）。
"""

from __future__ import annotations

import sqlite3

from infrastructure.db import CURRENT_SCHEMA_VERSION, init_db
from infrastructure.migrations import (
    MIGRATIONS,
    migrate_v0_to_v1,
    migrate_v1_to_v2,
    migrate_v2_to_v3,
    migrate_v3_to_v4,
    migrate_v4_to_v5,
    migrate_v5_to_v6,
)


def test_migrations_sorted_by_target() -> None:
    """MIGRATIONS 列表应按 target 升序可排序（init_db 内部排序）。"""
    targets = [t for t, _ in MIGRATIONS]
    assert targets == sorted(targets)
    assert len(MIGRATIONS) >= 6
    assert MIGRATIONS[0][0] == 1
    assert MIGRATIONS[1][0] == 2
    assert MIGRATIONS[2][0] == 3
    assert MIGRATIONS[3][0] == 4
    assert MIGRATIONS[4][0] == 5
    assert MIGRATIONS[5][0] == 6


def test_current_schema_version_is_six() -> None:
    """当前 schema 版本应为 6。"""
    assert CURRENT_SCHEMA_VERSION == 6


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


def test_migrate_v2_to_v3_creates_thumbnail_cache_table() -> None:
    """v2→v3 迁移应创建 thumbnail_cache 表（旧版，asset_id + FK→file_asset）。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        migrate_v0_to_v1(conn)
        migrate_v1_to_v2(conn)
        migrate_v2_to_v3(conn)

        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='thumbnail_cache'"
        ).fetchone()
        assert row is not None

        # v3 版本列名为 asset_id
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(thumbnail_cache)")}
        assert "asset_id" in cols
    finally:
        conn.close()


def test_migrate_v2_to_v3_idempotent() -> None:
    """v2→v3 迁移函数本身幂等。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        migrate_v0_to_v1(conn)
        migrate_v1_to_v2(conn)
        migrate_v2_to_v3(conn)
        migrate_v2_to_v3(conn)

        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='thumbnail_cache'"
        ).fetchone()
        assert row is not None
    finally:
        conn.close()


# --- v3 → v4 迁移测试（方向 C 重建） ---


def _apply_v0_to_v3(conn: sqlite3.Connection) -> None:
    """辅助：将内存数据库迁移到 v3 状态。"""
    migrate_v0_to_v1(conn)
    migrate_v1_to_v2(conn)
    migrate_v2_to_v3(conn)


def test_migrate_v3_to_v4_creates_new_tables() -> None:
    """v3→v4 迁移应创建 6 张新表与对应索引。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        _apply_v0_to_v3(conn)
        migrate_v3_to_v4(conn)

        for table in (
            "content_unit",
            "tag_category",
            "tag",
            "content_unit_tag",
            "operation_history",
            "folder_cache",
        ):
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            assert row is not None, f"表 {table} 应存在"

        # 索引存在
        for idx in (
            "idx_content_unit_status",
            "idx_content_unit_path",
            "idx_tag_category_id",
            "idx_content_unit_tag_cu",
            "idx_content_unit_tag_tag",
            "idx_operation_history_created",
            "idx_folder_cache_parent",
            "idx_folder_cache_path",
        ):
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (idx,),
            ).fetchone()
            assert row is not None, f"索引 {idx} 应存在"
    finally:
        conn.close()


def test_migrate_v3_to_v4_drops_old_tables() -> None:
    """v3→v4 迁移应移除旧表 mod_item / file_asset / folder_node / operation_log。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        _apply_v0_to_v3(conn)
        # v3 状态下旧表存在
        for table in ("mod_item", "file_asset", "folder_node", "operation_log"):
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            assert row is not None

        migrate_v3_to_v4(conn)

        for table in ("mod_item", "file_asset", "folder_node", "operation_log"):
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            assert row is None, f"表 {table} 应被移除"
    finally:
        conn.close()


def test_migrate_v3_to_v4_idempotent() -> None:
    """v3→v4 迁移函数本身幂等（CREATE IF NOT EXISTS + DROP IF EXISTS）。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        _apply_v0_to_v3(conn)
        migrate_v3_to_v4(conn)
        # 再次调用不应报错
        migrate_v3_to_v4(conn)

        # 新表仍存在
        for table in ("content_unit", "tag_category", "tag", "operation_history", "folder_cache"):
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            assert row is not None

        # 旧表仍不存在
        for table in ("mod_item", "file_asset", "folder_node", "operation_log"):
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            assert row is None
    finally:
        conn.close()


def test_migrate_v3_to_v4_preserves_managed_root_data() -> None:
    """v3→v4 迁移应保留 managed_root 数据。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        _apply_v0_to_v3(conn)
        # 插入 managed_root 数据
        conn.execute(
            "INSERT INTO managed_root (id, real_path, path_key, display_name, "
            "created_at, updated_at) VALUES "
            "('mr1', 'D:/Mods', 'd:/mods', 'Mods', '2026-07-07T00:00:00Z', "
            "'2026-07-07T00:00:00Z')"
        )
        conn.commit()

        migrate_v3_to_v4(conn)

        row = conn.execute("SELECT * FROM managed_root WHERE id = 'mr1'").fetchone()
        assert row is not None
        assert row["real_path"] == "D:/Mods"
        assert row["path_key"] == "d:/mods"
        assert row["display_name"] == "Mods"
    finally:
        conn.close()


def test_migrate_v3_to_v4_thumbnail_cache_uses_content_unit_id() -> None:
    """v3→v4 迁移应重建 thumbnail_cache：列名为 content_unit_id，FK 指向 content_unit。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        _apply_v0_to_v3(conn)
        migrate_v3_to_v4(conn)

        cols = {r["name"] for r in conn.execute("PRAGMA table_info(thumbnail_cache)")}
        assert "content_unit_id" in cols
        assert "asset_id" not in cols

        # FK 指向 content_unit
        fk_rows = conn.execute("PRAGMA foreign_key_list(thumbnail_cache)").fetchall()
        assert len(fk_rows) == 1
        assert fk_rows[0]["table"] == "content_unit"

        # 旧 thumbnail_cache 数据应被清空（drop + recreate）
        count = conn.execute("SELECT COUNT(*) FROM thumbnail_cache").fetchone()[0]
        assert count == 0
    finally:
        conn.close()


def test_migrate_v3_to_v4_check_constraints() -> None:
    """v4 CHECK 约束应生效：operation_type 非法值被拒绝；thumbnail_cache.status 非法值被拒绝。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        _apply_v0_to_v3(conn)
        migrate_v3_to_v4(conn)

        # 先插入 content_unit，供 thumbnail_cache FK 引用
        conn.execute(
            "INSERT INTO content_unit (id, path, created_at, updated_at) "
            "VALUES ('cu1', '/p', 't', 't')"
        )

        # 非法 operation_type
        try:
            conn.execute(
                "INSERT INTO operation_history (id, operation_type, source_path, created_at) "
                "VALUES ('h1', 'invalid_op', '/s', 't')"
            )
            raise AssertionError("应拒绝非法 operation_type")
        except sqlite3.IntegrityError:
            pass

        # 合法 operation_type
        for op in ("move", "delete", "rename", "new_folder"):
            conn.execute(
                "INSERT INTO operation_history (id, operation_type, source_path, created_at) "
                f"VALUES ('h_{op}', '{op}', '/s', 't')"
            )

        # 非法 thumbnail_cache.status
        try:
            conn.execute(
                "INSERT INTO thumbnail_cache (content_unit_id, source_size_bytes, "
                "source_modified_at, cache_filename, status, generated_at) "
                "VALUES ('cu1', 1, 't', 'f.png', 'invalid_status', 't')"
            )
            raise AssertionError("应拒绝非法 thumbnail_cache.status")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_migrate_v3_to_v4_unicode_support() -> None:
    """v4 新表应支持 Unicode 与中文路径。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        _apply_v0_to_v3(conn)
        migrate_v3_to_v4(conn)

        # 中文路径 content_unit
        conn.execute(
            "INSERT INTO content_unit (id, path, title, content_type, status, "
            "created_at, updated_at) VALUES "
            "('cu1', 'D:/Mods/护甲/寒霜之心', '寒霜之心', 'mod', 'unorganized', "
            "'2026-07-07T00:00:00Z', '2026-07-07T00:00:00Z')"
        )

        # 中文标签
        conn.execute(
            "INSERT INTO tag_category (id, name, color_hue) VALUES ('tc1', '服装护甲', 210)"
        )
        conn.execute("INSERT INTO tag (id, name, category_id) VALUES ('t1', '重甲', 'tc1')")
        conn.execute("INSERT INTO content_unit_tag (content_unit_id, tag_id) VALUES ('cu1', 't1')")

        row = conn.execute("SELECT path, title FROM content_unit WHERE id = 'cu1'").fetchone()
        assert row["path"] == "D:/Mods/护甲/寒霜之心"
        assert row["title"] == "寒霜之心"

        row = conn.execute("SELECT name FROM tag_category WHERE id = 'tc1'").fetchone()
        assert row["name"] == "服装护甲"

        row = conn.execute(
            "SELECT t.name FROM content_unit_tag cut "
            "JOIN tag t ON cut.tag_id = t.id "
            "WHERE cut.content_unit_id = 'cu1'"
        ).fetchone()
        assert row["name"] == "重甲"
    finally:
        conn.close()


def test_migrate_v3_to_v4_folder_cache_self_reference_ok() -> None:
    """folder_cache.parent_id 自引用在 schema 层允许（业务层校验，schema 不阻止）。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        _apply_v0_to_v3(conn)
        migrate_v3_to_v4(conn)

        conn.execute("INSERT INTO folder_cache (id, path, created_at) VALUES ('fc1', '/root', 't')")
        conn.execute(
            "INSERT INTO folder_cache (id, path, parent_id, created_at) "
            "VALUES ('fc2', '/root/sub', 'fc1', 't')"
        )

        row = conn.execute("SELECT parent_id FROM folder_cache WHERE id = 'fc2'").fetchone()
        assert row["parent_id"] == "fc1"
    finally:
        conn.close()


def test_init_db_migrates_from_v0_to_current(tmp_path) -> None:
    """init_db 从空数据库迁移到当前版本。"""
    db_path = tmp_path / "test.db"
    version = init_db(db_path)
    assert version == CURRENT_SCHEMA_VERSION
    assert version == 6

    # v6 后 managed_root 表仍存在
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='managed_root'"
        ).fetchone()
        assert row is not None

        # v6 后 content_unit 表存在
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='content_unit'"
        ).fetchone()
        assert row is not None

        # v6 后 staging_area 表存在
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='staging_area'"
        ).fetchone()
        assert row is not None

        # v6 后旧表 mod_item 不存在
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='mod_item'"
        ).fetchone()
        assert row is None
    finally:
        conn.close()


def test_migrate_v4_to_v5_idempotent() -> None:
    """v4→v5 迁移函数本身幂等（CREATE TABLE IF NOT EXISTS）。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        migrate_v4_to_v5(conn)
        # 再次调用不应报错
        migrate_v4_to_v5(conn)

        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='staging_area'"
        ).fetchone()
        assert row is not None
    finally:
        conn.close()


def test_init_db_idempotent_at_current(tmp_path) -> None:
    """init_db 在已迁移到当前版本的数据库上重复调用应保持版本，不报错。"""
    db_path = tmp_path / "test.db"
    version1 = init_db(db_path)
    version2 = init_db(db_path)
    assert version1 == version2 == CURRENT_SCHEMA_VERSION


def test_init_db_migrates_v3_db_to_v6(tmp_path) -> None:
    """已存在 v3 数据库的 init_db 应迁移到 v6。

    模拟真实场景：用户已有 v3 数据库（含 managed_root 数据），
    升级后 managed_root 数据应保留，旧业务表被移除，staging_area 表被创建，
    rating 列被移除，UNIQUE 约束已建立。
    """
    db_path = tmp_path / "test.db"
    # 手动构造 v3 状态
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE schema_version (
                version INTEGER NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        migrate_v0_to_v1(conn)
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        migrate_v1_to_v2(conn)
        conn.execute("INSERT INTO schema_version (version) VALUES (2)")
        migrate_v2_to_v3(conn)
        conn.execute("INSERT INTO schema_version (version) VALUES (3)")

        # 插入 managed_root 数据
        conn.execute(
            "INSERT INTO managed_root (id, real_path, path_key, display_name, "
            "created_at, updated_at) VALUES "
            "('mr1', 'D:/Mods/中文目录', 'd:/mods/中文目录', '中文目录', "
            "'2026-07-07T00:00:00Z', '2026-07-07T00:00:00Z')"
        )
        conn.commit()
    finally:
        conn.close()

    # init_db 应识别 v3 并依次应用 v3→v4→v5→v6
    version = init_db(db_path)
    assert version == 6

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # managed_root 数据保留
        row = conn.execute("SELECT * FROM managed_root WHERE id = 'mr1'").fetchone()
        assert row is not None
        assert row["display_name"] == "中文目录"

        # 旧表已移除
        for table in ("mod_item", "file_asset", "folder_node", "operation_log"):
            r = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            assert r is None, f"表 {table} 应被移除"

        # 新表存在
        for table in ("content_unit", "tag_category", "tag", "operation_history", "folder_cache"):
            r = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            assert r is not None, f"表 {table} 应存在"

        # thumbnail_cache 列名已改为 content_unit_id
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(thumbnail_cache)")}
        assert "content_unit_id" in cols
        assert "asset_id" not in cols

        # schema_version 应记录到 6
        rows = conn.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
        versions = [int(r[0]) for r in rows]
        assert 6 in versions
    finally:
        conn.close()


# --- v5 → v6 迁移测试（阶段 4 Task 1） ---


def _apply_v0_to_v5(conn: sqlite3.Connection) -> None:
    """辅助：将内存数据库迁移到 v5 状态。"""
    migrate_v0_to_v1(conn)
    migrate_v1_to_v2(conn)
    migrate_v2_to_v3(conn)
    migrate_v3_to_v4(conn)
    migrate_v4_to_v5(conn)


def test_migrate_v5_to_v6_drops_rating_column() -> None:
    """v5→v6 迁移应移除 content_unit.rating 列。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        _apply_v0_to_v5(conn)
        # v5 状态下 rating 列存在
        cols_v5 = {r["name"] for r in conn.execute("PRAGMA table_info(content_unit)")}
        assert "rating" in cols_v5

        migrate_v5_to_v6(conn)

        # v6 状态下 rating 列已移除
        cols_v6 = {r["name"] for r in conn.execute("PRAGMA table_info(content_unit)")}
        assert "rating" not in cols_v6
    finally:
        conn.close()


def test_migrate_v5_to_v6_creates_unique_indexes() -> None:
    """v5→v6 迁移应创建 tag_category.name 和 tag(name, category_id) 的 UNIQUE 索引。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        _apply_v0_to_v5(conn)
        migrate_v5_to_v6(conn)

        # tag_category.name 唯一索引存在
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_tag_category_name_unique'"
        ).fetchone()
        assert row is not None

        # tag(name, category_id) 唯一索引存在
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_tag_name_category_unique'"
        ).fetchone()
        assert row is not None

        # 验证 idx_tag_category_name_unique 确实 UNIQUE
        info = conn.execute("PRAGMA index_info('idx_tag_category_name_unique')").fetchall()
        assert len(info) == 1
        idx_list = conn.execute("PRAGMA index_list('tag_category')").fetchall()
        cat_unique_idx = [i for i in idx_list if i["name"] == "idx_tag_category_name_unique"]
        assert len(cat_unique_idx) == 1
        assert cat_unique_idx[0]["unique"] == 1
    finally:
        conn.close()


def test_migrate_v5_to_v6_enforces_tag_category_name_unique() -> None:
    """v6 后 tag_category.name 重复插入应失败。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        _apply_v0_to_v5(conn)
        migrate_v5_to_v6(conn)

        conn.execute(
            "INSERT INTO tag_category (id, name, color_hue) VALUES ('c1', '服装护甲', 210)"
        )
        try:
            conn.execute(
                "INSERT INTO tag_category (id, name, color_hue) VALUES ('c2', '服装护甲', 30)"
            )
            raise AssertionError("应拒绝重复 tag_category.name")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_migrate_v5_to_v6_enforces_tag_name_unique_in_category() -> None:
    """v6 后同分类下 tag.name 重复插入应失败。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        _apply_v0_to_v5(conn)
        migrate_v5_to_v6(conn)

        conn.execute(
            "INSERT INTO tag_category (id, name, color_hue) VALUES ('c1', '服装护甲', 210)"
        )
        conn.execute("INSERT INTO tag (id, name, category_id) VALUES ('t1', '重甲', 'c1')")
        try:
            conn.execute("INSERT INTO tag (id, name, category_id) VALUES ('t2', '重甲', 'c1')")
            raise AssertionError("应拒绝同分类下重复 tag.name")
        except sqlite3.IntegrityError:
            pass

        # 不同分类下同名标签应允许
        conn.execute("INSERT INTO tag_category (id, name, color_hue) VALUES ('c2', '武器', 30)")
        conn.execute("INSERT INTO tag (id, name, category_id) VALUES ('t3', '重甲', 'c2')")
    finally:
        conn.close()


def test_migrate_v5_to_v6_preserves_existing_data() -> None:
    """v5→v6 迁移应保留已有 tag_category / tag 数据，rating 列移除时保留其他字段。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        _apply_v0_to_v5(conn)
        # 插入 v5 状态的数据（含 rating）
        conn.execute(
            "INSERT INTO content_unit (id, path, title, rating, created_at, updated_at) "
            "VALUES ('cu1', '/mods/a', '测试', 4, 't', 't')"
        )
        conn.execute(
            "INSERT INTO tag_category (id, name, color_hue) VALUES ('c1', '服装护甲', 210)"
        )
        conn.execute("INSERT INTO tag (id, name, category_id) VALUES ('t1', '重甲', 'c1')")
        conn.commit()

        migrate_v5_to_v6(conn)

        # content_unit 其他字段保留
        row = conn.execute("SELECT id, path, title FROM content_unit WHERE id = 'cu1'").fetchone()
        assert row is not None
        assert row["path"] == "/mods/a"
        assert row["title"] == "测试"

        # tag_category 保留
        row = conn.execute("SELECT name, color_hue FROM tag_category WHERE id = 'c1'").fetchone()
        assert row is not None
        assert row["name"] == "服装护甲"
        assert row["color_hue"] == 210

        # tag 保留
        row = conn.execute("SELECT name, category_id FROM tag WHERE id = 't1'").fetchone()
        assert row is not None
        assert row["name"] == "重甲"
        assert row["category_id"] == "c1"
    finally:
        conn.close()


def test_migrate_v5_to_v6_idempotent() -> None:
    """v5→v6 迁移函数本身幂等（IF NOT EXISTS + DROP COLUMN IF EXISTS）。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        _apply_v0_to_v5(conn)
        migrate_v5_to_v6(conn)
        # 再次调用不应报错
        migrate_v5_to_v6(conn)

        # rating 列仍不存在
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(content_unit)")}
        assert "rating" not in cols

        # 索引仍存在
        for idx in ("idx_tag_category_name_unique", "idx_tag_name_category_unique"):
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (idx,),
            ).fetchone()
            assert row is not None
    finally:
        conn.close()


def test_migrate_v5_to_v6_idempotent_when_rating_already_absent() -> None:
    """v5→v6 迁移在 rating 列已不存在时不应报错（防御性幂等）。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        _apply_v0_to_v5(conn)
        # 先迁移一次（rating 被移除）
        migrate_v5_to_v6(conn)
        # 第二次迁移：rating 列不存在，应跳过 DROP COLUMN
        migrate_v5_to_v6(conn)

        # 验证状态稳定
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(content_unit)")}
        assert "rating" not in cols
    finally:
        conn.close()
