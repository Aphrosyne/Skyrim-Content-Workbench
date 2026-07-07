"""db 初始化测试。"""

from __future__ import annotations

from pathlib import Path

from infrastructure.db import CURRENT_SCHEMA_VERSION, get_connection, init_db


def test_init_db_creates_schema_version_table(temp_app_data: Path) -> None:
    db_path = temp_app_data / "app.db"
    version = init_db(db_path)
    assert version == CURRENT_SCHEMA_VERSION
    assert db_path.exists()

    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT version FROM schema_version").fetchall()
        assert len(rows) == 1
        assert int(rows[0][0]) == CURRENT_SCHEMA_VERSION


def test_init_db_idempotent(temp_app_data: Path) -> None:
    db_path = temp_app_data / "app.db"
    init_db(db_path)
    version = init_db(db_path)
    assert version == CURRENT_SCHEMA_VERSION

    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT version FROM schema_version").fetchall()
        # 幂等：不应重复插入
        assert len(rows) == 1
