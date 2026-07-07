"""SQLite 数据库初始化。

第一版（Task 1）仅创建 schema_version 表并记录当前 schema 版本为 0。
具体业务表（ModItem、FileAsset、FolderNode、OperationLog）在 Task 2 中
通过迁移添加，并递增 schema_version。

约束：
- 所有路径使用 pathlib.Path。
- 启用外键约束与 WAL 模式。
- schema 变更必须通过迁移或可重复初始化逻辑（见 AGENTS.md 代码质量）。
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 0


def get_connection(db_path: Path) -> sqlite3.Connection:
    """打开 SQLite 连接，启用外键与 WAL。"""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db(db_path: Path) -> int:
    """初始化数据库。

    若 schema_version 表不存在则创建并写入当前版本。
    若已存在则返回当前最新版本。
    返回当前 schema 版本号。

    此函数可重复调用（幂等）。
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        row = conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (CURRENT_SCHEMA_VERSION,),
            )
            logger.info("数据库初始化完成，schema_version=%d", CURRENT_SCHEMA_VERSION)
            return CURRENT_SCHEMA_VERSION
        current = int(row[0])
        logger.info("数据库已存在，当前 schema_version=%d", current)
        return current
