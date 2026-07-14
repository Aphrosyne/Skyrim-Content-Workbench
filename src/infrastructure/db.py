"""SQLite 数据库初始化与迁移。

约束：
- 所有路径使用 pathlib.Path。
- 启用外键约束与 WAL 模式。
- schema 变更必须通过迁移或可重复初始化逻辑（见 AGENTS.md 代码质量）。
- 迁移按 target 升序应用；每步迁移在独立事务中执行，
  成功后写入对应版本号到 schema_version。
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from infrastructure.migrations import MIGRATIONS

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 4


def get_connection(db_path: Path) -> sqlite3.Connection:
    """打开 SQLite 连接，启用外键与 WAL，设置 Row 工厂。

    Row 工厂使查询结果可通过列名访问（row["column"]），
    与所有 Repository 的 _row_to_model 实现一致。
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    """确保 schema_version 表存在。幂等。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def _get_current_version(conn: sqlite3.Connection) -> int:
    """返回当前 schema 版本；无记录时返回 -1 表示需要写入 v0 基线。"""
    row = conn.execute(
        "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
    ).fetchone()
    return -1 if row is None else int(row[0])


def init_db(db_path: Path) -> int:
    """初始化数据库并应用 pending 迁移。返回最终 schema 版本。

    流程：
    1. 确保父目录存在
    2. 确保 schema_version 表存在
    3. 若无任何版本记录，插入 v0 基线（Task 1 的初始状态）
    4. 读取当前版本
    5. 按 target 升序应用 current < target 的迁移
    6. 每步迁移在独立事务中执行；成功后插入新版本号
    7. 返回最终版本

    此函数可重复调用（幂等）。
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(db_path) as conn:
        _ensure_schema_version_table(conn)

        current = _get_current_version(conn)
        if current == -1:
            conn.execute("INSERT INTO schema_version (version) VALUES (0)")
            logger.info("数据库初始化完成，schema_version=0（基线）")
            current = 0

        # 按 target 升序应用迁移
        for target, migrate_fn in sorted(MIGRATIONS, key=lambda m: m[0]):
            if target <= current:
                continue
            with conn:
                migrate_fn(conn)
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (target,))
            logger.info("数据库迁移至 schema_version=%d", target)
            current = target

        return current
