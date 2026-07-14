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


def migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    r"""v2 → v3：新增 thumbnail_cache 表。

    thumbnail_cache 保存缩略图缓存元数据，用于缓存有效性判断。
    缓存失效策略（Q5 已关闭）：以 asset_id + source_size_bytes + source_modified_at
    为有效性依据；不一致时重建。

    缓存命名（Q13 已关闭）：缓存文件名格式 {asset_id}.png。
    缓存文件位于应用数据目录 thumbnails\，不写入用户 Mod 目录。

    status 枚举：
    - ok：缩略图已成功生成，cache_filename 指向有效缓存文件。
    - missing：源文件不存在。
    - corrupt：源文件存在但无法解码（损坏图片）。
    - unsupported：源文件格式不被 Pillow 支持。
    - error：其他 IO 或处理错误。

    依据 docs/spec.md §10、docs/architecture.md §8、docs/open-questions.md Q5/Q13。
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS thumbnail_cache (
            asset_id TEXT PRIMARY KEY,
            source_size_bytes INTEGER NOT NULL,
            source_modified_at TEXT NOT NULL,
            cache_filename TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN (
                'ok','missing','corrupt','unsupported','error'
            )),
            error_message TEXT,
            generated_at TEXT NOT NULL,
            FOREIGN KEY (asset_id) REFERENCES file_asset(id)
        );
        """
    )
    logger.info("迁移 v2 → v3 完成")


def migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    """v3 → v4：方向 C 重建——建立 ContentUnit 体系，移除旧表，重建 thumbnail_cache。

    依据 docs/spec.md §4 / §11、docs/architecture.md §6、docs/roadmap.md 阶段 2 Task 1。

    变更内容：
    1. 新建 6 张表：content_unit / tag_category / tag / content_unit_tag /
       operation_history / folder_cache（均 IF NOT EXISTS，幂等）。
    2. 重建 thumbnail_cache：列名 asset_id → content_unit_id，FK 由 file_asset(id)
       改为 content_unit(id)。drop + create（旧记录因 file_asset 已被 drop 成为孤儿，
       保留无意义）。缓存 PNG 文件按需重新生成（旧文件名按 asset_id 命名，自然失效）。
    3. 移除旧表：operation_log / file_asset / folder_node / mod_item。
       drop 顺序遵循 FK 依赖：thumbnail_cache（旧版）→ operation_log → file_asset
       → mod_item → folder_node。

    不迁移旧数据（roadmap 明确）。保留表 managed_root 数据不受影响。
    """
    conn.executescript(
        """
        -- 1. 创建新表（幂等）
        CREATE TABLE IF NOT EXISTS content_unit (
            id TEXT PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            title TEXT,
            content_type TEXT NOT NULL DEFAULT 'mod',
            source_url TEXT,
            rating INTEGER,
            cover_path TEXT,
            status TEXT NOT NULL DEFAULT 'unorganized',
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tag_category (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            color_hue INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS tag (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category_id TEXT NOT NULL REFERENCES tag_category(id)
        );

        CREATE TABLE IF NOT EXISTS content_unit_tag (
            content_unit_id TEXT NOT NULL REFERENCES content_unit(id),
            tag_id TEXT NOT NULL REFERENCES tag(id),
            PRIMARY KEY (content_unit_id, tag_id)
        );

        CREATE TABLE IF NOT EXISTS operation_history (
            id TEXT PRIMARY KEY,
            operation_type TEXT NOT NULL CHECK(operation_type IN (
                'move','delete','rename','new_folder'
            )),
            source_path TEXT NOT NULL,
            target_path TEXT,
            created_at TEXT NOT NULL,
            can_undo INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS folder_cache (
            id TEXT PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            parent_id TEXT REFERENCES folder_cache(id),
            last_scanned_mtime REAL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_content_unit_status ON content_unit(status);
        CREATE INDEX IF NOT EXISTS idx_content_unit_path ON content_unit(path);
        CREATE INDEX IF NOT EXISTS idx_tag_category_id ON tag(category_id);
        CREATE INDEX IF NOT EXISTS idx_content_unit_tag_cu ON content_unit_tag(content_unit_id);
        CREATE INDEX IF NOT EXISTS idx_content_unit_tag_tag ON content_unit_tag(tag_id);
        CREATE INDEX IF NOT EXISTS idx_operation_history_created ON operation_history(created_at);
        CREATE INDEX IF NOT EXISTS idx_folder_cache_parent ON folder_cache(parent_id);
        CREATE INDEX IF NOT EXISTS idx_folder_cache_path ON folder_cache(path);

        -- 2. 重建 thumbnail_cache（FK 由 file_asset 改为 content_unit）
        DROP TABLE IF EXISTS thumbnail_cache;
        CREATE TABLE thumbnail_cache (
            content_unit_id TEXT PRIMARY KEY REFERENCES content_unit(id),
            source_size_bytes INTEGER NOT NULL,
            source_modified_at TEXT NOT NULL,
            cache_filename TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN (
                'ok','missing','corrupt','unsupported','error'
            )),
            error_message TEXT,
            generated_at TEXT NOT NULL
        );

        -- 3. 移除旧表（顺序遵循 FK 依赖）
        DROP TABLE IF EXISTS operation_log;
        DROP TABLE IF EXISTS file_asset;
        DROP TABLE IF EXISTS mod_item;
        DROP TABLE IF EXISTS folder_node;
        """
    )
    logger.info("迁移 v3 → v4 完成")


def migrate_v4_to_v5(conn: sqlite3.Connection) -> None:
    """v4 → v5：新增 staging_area 表。

    staging_area 保存用户标记的"暂存区"目录配置，独立于 folder_cache 扫描结果。
    即使暂存区目录未被扫描到或 folder_cache 被清理，标记仍保留。

    设计决策：
    - 独立配置表（与 managed_root 同模式），而非在 folder_cache 加字段。
    - path_key 唯一约束防止重复标记同一路径（复用 make_path_key 归一化）。
    - 不与 managed_root 建立外键：暂存区路径不必在受管理根目录下，
      移除受管理根目录不应级联删除暂存区标记。

    依据 docs/spec.md §5.2、docs/roadmap.md 阶段 3 Task 1。
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS staging_area (
            id TEXT PRIMARY KEY,
            real_path TEXT NOT NULL,
            path_key TEXT NOT NULL UNIQUE,
            display_name TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_staging_area_path_key ON staging_area(path_key);
        """
    )
    logger.info("迁移 v4 → v5 完成")


# 迁移注册表：(target_version, migrate_fn)
# init_db 按 target 升序应用 current < target 的迁移。
MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, migrate_v0_to_v1),
    (2, migrate_v1_to_v2),
    (3, migrate_v2_to_v3),
    (4, migrate_v3_to_v4),
    (5, migrate_v4_to_v5),
]
