"""数据库迁移。

迁移函数本身幂等（使用 CREATE TABLE IF NOT EXISTS）。
迁移成功后由 init_db 在独立事务中写入 schema_version。

约束：
- 每个迁移函数只负责 DDL，不写 schema_version。
- 迁移函数不删除列、不修改既有列定义（避免破坏现有数据）。
- schema 变更必须通过迁移（见 AGENTS.md 代码质量）。
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

logger = logging.getLogger(__name__)


def migrate_v0_to_v1(conn: sqlite3.Connection) -> None:
    """v0 → v1：创建四张业务表与索引。

    表定义依据 docs/spec.md §6 与 docs/architecture.md §4。
    - ModItem: §6.1（不引入 status 列，见 open-questions.md Q1）
    - FileAsset: §6.2（不引入 batch_id 列，见 open-questions.md Q2）
    - FolderNode: §6.3
    - OperationLog: §6.4（undo_payload 为 TEXT，结构由 Task 5 定义，见 Q14）

    path_key 列实现 A2 决策：原样存储 real_path，path_key 用于比较与唯一约束。
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS mod_item (
            id TEXT PRIMARY KEY,
            display_name TEXT,
            description TEXT,
            source_url TEXT,
            category_folder_id TEXT,
            tags TEXT NOT NULL DEFAULT '[]',
            cover_asset_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (category_folder_id) REFERENCES folder_node(id),
            FOREIGN KEY (cover_asset_id) REFERENCES file_asset(id)
        );

        CREATE TABLE IF NOT EXISTS file_asset (
            id TEXT PRIMARY KEY,
            mod_item_id TEXT,
            real_path TEXT NOT NULL,
            path_key TEXT NOT NULL UNIQUE,
            filename TEXT NOT NULL,
            extension TEXT NOT NULL,
            asset_kind TEXT NOT NULL CHECK(asset_kind IN ('file','folder')),
            role TEXT NOT NULL CHECK(role IN (
                'main_mod','translation','preview','readme','optional_file','unknown'
            )),
            size_bytes INTEGER NOT NULL,
            modified_at TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            FOREIGN KEY (mod_item_id) REFERENCES mod_item(id)
        );

        CREATE TABLE IF NOT EXISTS folder_node (
            id TEXT PRIMARY KEY,
            real_path TEXT NOT NULL,
            path_key TEXT NOT NULL UNIQUE,
            parent_id TEXT,
            display_name TEXT,
            is_managed_root INTEGER NOT NULL CHECK(is_managed_root IN (0,1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (parent_id) REFERENCES folder_node(id)
        );

        CREATE TABLE IF NOT EXISTS operation_log (
            id TEXT PRIMARY KEY,
            operation_type TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN (
                'planned','confirmed','completed','failed','undone'
            )),
            affected_asset_ids TEXT NOT NULL DEFAULT '[]',
            source_paths TEXT NOT NULL DEFAULT '[]',
            target_paths TEXT NOT NULL DEFAULT '[]',
            conflict_policy TEXT NOT NULL CHECK(conflict_policy IN ('ask')),
            created_at TEXT NOT NULL,
            completed_at TEXT,
            undo_payload TEXT,
            error_message TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_file_asset_mod_item_id ON file_asset(mod_item_id);
        CREATE INDEX IF NOT EXISTS idx_mod_item_category_folder_id
            ON mod_item(category_folder_id);
        CREATE INDEX IF NOT EXISTS idx_folder_node_parent_id ON folder_node(parent_id);
        CREATE INDEX IF NOT EXISTS idx_operation_log_status ON operation_log(status);
        """
    )
    logger.info("迁移 v0 → v1 完成")


def migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """v1 → v2：新增 managed_root 表。

    managed_root 保存用户配置的受管理根目录，独立于 folder_node 扫描结果。
    与 folder_node.is_managed_root 的关系（见 docs/architecture.md §4）：
    - managed_root：用户配置（持久化、跨扫描保留）。
    - folder_node.is_managed_root：扫描结果标记（标识哪些 FolderNode 是扫描时的根）。
    移除 managed_root 配置不自动清理 folder_node 记录（清理策略待确认）。

    依据 docs/spec.md §6.5、docs/phase-2-plan.md 任务 1 D1。
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS managed_root (
            id TEXT PRIMARY KEY,
            real_path TEXT NOT NULL,
            path_key TEXT NOT NULL UNIQUE,
            display_name TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_managed_root_path_key ON managed_root(path_key);
        """
    )
    logger.info("迁移 v1 → v2 完成")


# 迁移注册表：(target_version, migrate_fn)
# init_db 按 target 升序应用 current < target 的迁移。
MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, migrate_v0_to_v1),
    (2, migrate_v1_to_v2),
]
