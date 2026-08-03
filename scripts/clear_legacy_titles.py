"""一次性数据清理脚本：清除 content_unit 遗留别名（title ≠ 文件名）。

UI合理性13（2026-08-03）：content_unit.title 列保留但停止使用。历史数据中
存在少量「别名」title（与真实文件名不一致），本脚本将其清为 NULL，使 title 列
不再承载用户语义。

安全约束：
- 只修改 content_unit.title（置 NULL），不触碰任何文件系统内容，不删除记录。
- 默认 dry-run：仅列出受影响行，需显式 --apply 才写入。
- 幂等：重复执行结果一致（清理后不再有 title ≠ 文件名 的行）。

用法::

    python scripts/clear_legacy_titles.py            # 仅预览
    python scripts/clear_legacy_titles.py --apply    # 实际清除
    python scripts/clear_legacy_titles.py --db PATH  # 指定数据库（测试用）

数据库路径默认由 app.app_paths 解析（SCW_DATA_DIR > 项目 data/ > LOCALAPPDATA 回退）。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# 让脚本可以直接用项目源码（app.app_paths）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from app.app_paths import get_app_db_path  # noqa: E402


def _basename(path: str) -> str:
    """返回路径的文件名部分（兼容 \\ 与 / 分隔符，无分隔符时返回原路径）。"""
    for sep in ("\\", "/"):
        pos = path.rfind(sep)
        if pos >= 0:
            return path[pos + 1 :]
    return path


def collect_legacy_titles(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """返回 title 与文件名不一致的行（title ≠ basename(path)）。"""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, path, title FROM content_unit "
        "WHERE title IS NOT NULL AND title != ''"
    ).fetchall()
    return [row for row in rows if row["title"] != _basename(row["path"])]


def clear_legacy_titles(conn: sqlite3.Connection) -> list[dict]:
    """把 title ≠ 文件名的行清为 NULL（幂等），返回受影响行信息。"""
    affected = collect_legacy_titles(conn)
    for row in affected:
        conn.execute("UPDATE content_unit SET title = NULL WHERE id = ?", (row["id"],))
    conn.commit()
    return [dict(row) for row in affected]


def main(argv: list[str] | None = None) -> int:
    """命令行入口。默认 dry-run，--apply 实际清除。"""
    parser = argparse.ArgumentParser(
        description="清除 content_unit 遗留别名（title ≠ 文件名，UI合理性13）"
    )
    parser.add_argument("--db", help="数据库文件路径（默认由 app.app_paths 解析）")
    parser.add_argument("--apply", action="store_true", help="实际写入；默认仅预览")
    args = parser.parse_args(argv)

    db_path = Path(args.db) if args.db else get_app_db_path()
    if not db_path.exists():
        print(f"数据库不存在：{db_path}")
        return 1

    conn = sqlite3.connect(str(db_path))
    try:
        affected = collect_legacy_titles(conn)
        if not affected:
            print("无遗留别名（title ≠ 文件名 的行数为 0）。")
            return 0

        print(f"发现 {len(affected)} 条遗留别名：")
        for row in affected:
            print(f"  - {row['id']} | title={row['title']!r} | path={row['path']}")

        if not args.apply:
            print("dry-run：未修改数据库。使用 --apply 实际清除。")
            return 0

        cleared = clear_legacy_titles(conn)
        print(f"已清除 {len(cleared)} 条遗留别名（title → NULL）。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
