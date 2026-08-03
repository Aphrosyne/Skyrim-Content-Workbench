"""scripts/clear_legacy_titles.py 的单元测试。

覆盖：
- 仅识别 title ≠ 文件名（basename）的遗留别名行
- 兼容 \\ 与 / 分隔符
- clear 只把别名行 title 置 NULL，不影响 title=文件名 / title 为 NULL 的行
- 幂等：重复执行不再有遗留别名
- CLI dry-run 不修改数据库；--apply 实际清除
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

# 将 scripts/ 加入 sys.path 以导入 clear_legacy_titles 模块
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from clear_legacy_titles import clear_legacy_titles, collect_legacy_titles, main  # noqa: E402

from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.path_utils import make_path_key  # noqa: E402


def _insert_unit(
    conn: sqlite3.Connection,
    unit_id: str,
    path: str,
    title: str | None,
) -> None:
    """插入一条 content_unit 记录。"""
    conn.execute(
        "INSERT INTO content_unit (id, path, path_key, title, content_type, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, 'mod', 't', 't')",
        (unit_id, path, make_path_key(path), title),
    )
    conn.commit()


@pytest.fixture
def legacy_db(tmp_path: Path):
    """构造含遗留别名 / 默认 title / 无 title 的测试库。"""
    db_path = tmp_path / "app.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row

    # 遗留别名（title ≠ 文件名，Windows 反斜杠）
    _insert_unit(conn, "u-alias-1", r"D:\mods\[Ivyy]Sinful Sister", "[Ivyy]Sinful Sister UBE")
    # 遗留别名（前斜杠路径）
    _insert_unit(
        conn,
        "u-alias-2",
        "D:/mods/Shiro_Follower（在雪漫龙临堡附近）",
        "Shiro_Follower_2",
    )
    # 默认 title = 文件名（不应清理）
    _insert_unit(conn, "u-default", r"D:\mods\Frost.7z", "Frost.7z")
    # title 为 NULL（不应清理）
    _insert_unit(conn, "u-none", r"D:\mods\Plain.7z", None)

    yield conn, db_path
    conn.close()


class TestCollect:
    def test_collect_only_legacy_aliases(self, legacy_db) -> None:
        """只收集 title ≠ 文件名的行。"""
        conn, _ = legacy_db
        affected = collect_legacy_titles(conn)
        ids = {row["id"] for row in affected}
        assert ids == {"u-alias-1", "u-alias-2"}


class TestClear:
    def test_clear_sets_alias_to_null_only(self, legacy_db) -> None:
        """别名行 title → NULL，其余行不受影响。"""
        conn, _ = legacy_db
        cleared = clear_legacy_titles(conn)
        assert len(cleared) == 2

        rows = {
            r["id"]: r["title"]
            for r in conn.execute("SELECT id, title FROM content_unit").fetchall()
        }
        assert rows["u-alias-1"] is None
        assert rows["u-alias-2"] is None
        assert rows["u-default"] == "Frost.7z"  # title=文件名 不受影响
        assert rows["u-none"] is None

    def test_clear_is_idempotent(self, legacy_db) -> None:
        """重复执行不再有遗留别名。"""
        conn, _ = legacy_db
        clear_legacy_titles(conn)
        assert collect_legacy_titles(conn) == []
        # 第二次执行返回空列表
        assert clear_legacy_titles(conn) == []


class TestMain:
    def test_dry_run_does_not_modify(self, legacy_db, capsys) -> None:
        """默认 dry-run：列出但未修改数据库。"""
        conn, db_path = legacy_db
        exit_code = main(["--db", str(db_path)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "dry-run" in captured.out
        # 数据库未被修改
        affected = collect_legacy_titles(conn)
        assert len(affected) == 2

    def test_apply_clears(self, legacy_db, capsys) -> None:
        """--apply：实际清除。"""
        conn, db_path = legacy_db
        exit_code = main(["--db", str(db_path), "--apply"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "已清除 2 条" in captured.out
        assert collect_legacy_titles(conn) == []

    def test_missing_db_returns_error(self, tmp_path: Path, capsys) -> None:
        """数据库不存在 → 退出码 1。"""
        exit_code = main(["--db", str(tmp_path / "nope.db")])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "数据库不存在" in captured.out
