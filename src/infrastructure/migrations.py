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


def migrate_v5_to_v6(conn: sqlite3.Connection) -> None:
    """v5 → v6：移除 ContentUnit.rating 列 + 加 tag / tag_category UNIQUE 约束。

    Stage 4 Task 1：spec §4.1 移除 rating 字段（用户决策：私人数据库用不上 rating）；
    同时为 tag_category.name 与 tag (name, category_id) 添加 UNIQUE 约束，
    schema 层强制保证"同一分类下不能重名，跨分类可以重名"。

    实现说明：
    - SQLite 3.35+ 支持 ALTER TABLE DROP COLUMN。Python 3.12+ 内置 SQLite ≥ 3.40，
      本项目要求 Python 3.12+，可安全使用。
    - rating 列无 CHECK / FK / INDEX 引用，可直接 DROP。
    - UNIQUE 约束通过 CREATE UNIQUE INDEX IF NOT EXISTS 实现（schema 层强约束）。
      application 层仍提供 DuplicateTagCategoryNameError / DuplicateTagNameError，
      给 UI 友好的错误消息，但 schema 是最后一道防线。

    幂等性：DROP COLUMN 不存在时抛 OperationalError；本迁移函数采用
    "先检查列是否存在再 DROP"模式，确保重复执行不报错。
    """
    # 1. 检查 content_unit.rating 列是否存在，存在则 DROP
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(content_unit)")}
    if "rating" in cols:
        conn.execute("ALTER TABLE content_unit DROP COLUMN rating")
        logger.info("v6 迁移：content_unit.rating 列已移除")

    # 2. 加 UNIQUE 约束（CREATE UNIQUE INDEX IF NOT EXISTS 幂等）
    conn.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tag_category_name_unique
            ON tag_category(name);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tag_name_category_unique
            ON tag(name, category_id);
        """
    )
    logger.info("迁移 v5 → v6 完成")


def migrate_v6_to_v7(conn: sqlite3.Connection) -> None:
    """v6 → v7：thumbnail_cache 支持多尺寸缓存（Task 1a）。

    Stage 5 Task 1a：卡片视图需要 256/512 双档缓存，原单档 64×64 PNG 缓存
    改为多尺寸复合主键，缓存格式从 PNG 改为 WebP。

    变更：
    - 新增 size 列（INTEGER NOT NULL，默认 64）
    - 主键改为 (content_unit_id, size) 复合主键
    - 旧 64 档记录保留（GC 清理无对应 content_unit 的记录）

    实现说明：
    - SQLite 不支持 ALTER PRIMARY KEY，需重建表
    - 旧 cache_filename 仍为 {id}.png，新生成为 {id}_{size}.webp
    - 旧 64 档缓存文件由 GC 在启动时清理（不在此迁移删除，避免数据丢失）

    幂等性：通过检查 thumbnail_cache 是否已有 size 列判断是否已迁移。
    """
    # 幂等检查：若 size 列已存在则跳过
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(thumbnail_cache)")}
    if "size" in cols:
        logger.info("v7 迁移已应用，跳过")
        return

    # 1. 创建新表（复合主键）
    conn.executescript(
        """
        CREATE TABLE thumbnail_cache_new (
            content_unit_id TEXT NOT NULL,
            size INTEGER NOT NULL DEFAULT 64,
            source_size_bytes INTEGER NOT NULL,
            source_modified_at TEXT NOT NULL,
            cache_filename TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('ok','missing','corrupt','unsupported','error')),
            error_message TEXT,
            generated_at TEXT NOT NULL,
            PRIMARY KEY (content_unit_id, size)
        );
        """
    )

    # 2. 迁移旧数据（标记为 64 档）
    conn.execute(
        """
        INSERT INTO thumbnail_cache_new
            (content_unit_id, size, source_size_bytes, source_modified_at,
             cache_filename, status, error_message, generated_at)
        SELECT content_unit_id, 64, source_size_bytes, source_modified_at,
               cache_filename, status, error_message, generated_at
        FROM thumbnail_cache
        """
    )

    # 3. 替换旧表
    conn.executescript(
        """
        DROP TABLE thumbnail_cache;
        ALTER TABLE thumbnail_cache_new RENAME TO thumbnail_cache;
        CREATE INDEX idx_thumbnail_cache_unit ON thumbnail_cache(content_unit_id);
        """
    )
    logger.info("迁移 v6 → v7 完成")


def migrate_v7_to_v8(conn: sqlite3.Connection) -> None:
    """v7 → v8：operation_history 支持撤销标记（Task 6）。

    Stage 5 Task 6：为操作历史撤销框架做铺垫。

    变更：
    - 新增 undone_at TEXT 列（NULL 表示未撤销，非 NULL 为撤销时间戳）
    - operation_type CHECK 约束扩展为包含 'undo'
      （undo 记录的 source_path 指向被撤销的原 history.id，
       can_undo=0，undone_at 必须为 NULL，避免无限循环撤销）

    实现说明：
    - SQLite 不支持直接修改 CHECK 约束，需重建表
    - 旧数据全部保留，undone_at 默认 NULL（未撤销）
    - operation_type='undo' 的记录在迁移后才会被 UndoService 写入

    幂等性：通过检查 operation_history 是否已有 undone_at 列判断是否已迁移。
    """
    # 幂等检查：若 undone_at 列已存在则跳过
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(operation_history)")}
    if "undone_at" in cols:
        logger.info("v8 迁移已应用，跳过")
        return

    # 1. 创建新表（扩展 CHECK 约束 + 新增 undone_at 列）
    conn.executescript(
        """
        CREATE TABLE operation_history_new (
            id TEXT PRIMARY KEY,
            operation_type TEXT NOT NULL CHECK(operation_type IN (
                'move','delete','rename','new_folder','undo'
            )),
            source_path TEXT NOT NULL,
            target_path TEXT,
            created_at TEXT NOT NULL,
            can_undo INTEGER NOT NULL DEFAULT 1,
            undone_at TEXT
        );
        """
    )

    # 2. 迁移旧数据（undone_at 默认 NULL，表示未撤销）
    conn.execute(
        """
        INSERT INTO operation_history_new
            (id, operation_type, source_path, target_path, created_at, can_undo, undone_at)
        SELECT id, operation_type, source_path, target_path, created_at, can_undo, NULL
        FROM operation_history
        """
    )

    # 3. 替换旧表 + 重建索引
    conn.executescript(
        """
        DROP TABLE operation_history;
        ALTER TABLE operation_history_new RENAME TO operation_history;
        CREATE INDEX IF NOT EXISTS idx_operation_history_created
            ON operation_history(created_at);
        """
    )
    logger.info("迁移 v7 → v8 完成")


def migrate_v8_to_v9(conn: sqlite3.Connection) -> None:
    """v8 → v9：operation_history 支持复制操作（Stage 5 Task 3b）。

    变更：
    - operation_type CHECK 约束扩展为包含 'copy'
      （copy 记录由 FileOperationService.copy 写入，
       source_path=原路径，target_path=新路径，can_undo=0）

    实现说明：
    - SQLite 不支持直接修改 CHECK 约束，需重建表
    - 旧数据全部保留，无新列

    幂等性：通过检查 operation_history 的 CHECK 约束是否已包含 'copy' 判断是否已迁移。
    旧表 CHECK 约束文本不含 'copy'，迁移后包含 'copy'。
    """
    # 幂等检查：读取当前 operation_history 表的 sql，若已含 'copy' 则跳过
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='operation_history'"
    ).fetchone()
    if row is None:
        # 表不存在（全新数据库走 init_db 建表路径），无需迁移
        return
    current_sql = row["sql"] if isinstance(row, sqlite3.Row) else row[0]
    if current_sql and "'copy'" in current_sql:
        logger.info("v9 迁移已应用，跳过")
        return

    # 1. 创建新表（CHECK 约束扩展 'copy'）
    conn.executescript(
        """
        CREATE TABLE operation_history_new (
            id TEXT PRIMARY KEY,
            operation_type TEXT NOT NULL CHECK(operation_type IN (
                'move','delete','rename','new_folder','undo','copy'
            )),
            source_path TEXT NOT NULL,
            target_path TEXT,
            created_at TEXT NOT NULL,
            can_undo INTEGER NOT NULL DEFAULT 1,
            undone_at TEXT
        );
        """
    )

    # 2. 迁移旧数据
    conn.execute(
        """
        INSERT INTO operation_history_new
            (id, operation_type, source_path, target_path, created_at, can_undo, undone_at)
        SELECT id, operation_type, source_path, target_path, created_at, can_undo, undone_at
        FROM operation_history
        """
    )

    # 3. 替换旧表 + 重建索引
    conn.executescript(
        """
        DROP TABLE operation_history;
        ALTER TABLE operation_history_new RENAME TO operation_history;
        CREATE INDEX IF NOT EXISTS idx_operation_history_created
            ON operation_history(created_at);
        """
    )
    logger.info("迁移 v8 → v9 完成")


def migrate_v9_to_v10(conn: sqlite3.Connection) -> None:
    """v9 → v10：ContentUnit.status 简化为两态（Stage 5 Task 7 收尾）。

    变更：
    - 将所有 status='unorganized' 记录更新为 'organized'。
      （'unorganized' 语义为"已标记"，重命名为更直观的 'organized'）
    - 旧 'organized' 取值（"已整理"语义）实际从未被生产代码写入，无需处理。
    - 'missing' 取值完全未实现，也无需处理。
    - 表 DEFAULT 不变（SQLite 不便修改 DEFAULT，由应用层 ContentUnit 默认值接管）。

    迁移后 status 仅两态：
    - 'organized'：当前标记为内容单元
    - 'unmarked'：用户已取消标记（保留记录以阻止扫描器重新创建）

    幂等性：UPDATE 语句本身幂等，无 'unorganized' 记录时不影响任何行。
    """
    result = conn.execute(
        "UPDATE content_unit SET status = 'organized' WHERE status = 'unorganized'"
    )
    if result.rowcount > 0:
        logger.info(
            "迁移 v9 → v10 完成：更新 %d 条记录 status='unorganized' → 'organized'", result.rowcount
        )
    else:
        logger.info("迁移 v9 → v10 完成：无 'unorganized' 记录需要更新")


# 迁移注册表：(target_version, migrate_fn)
# init_db 按 target 升序应用 current < target 的迁移。
MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, migrate_v0_to_v1),
    (2, migrate_v1_to_v2),
    (3, migrate_v2_to_v3),
    (4, migrate_v3_to_v4),
    (5, migrate_v4_to_v5),
    (6, migrate_v5_to_v6),
    (7, migrate_v6_to_v7),
    (8, migrate_v7_to_v8),
    (9, migrate_v8_to_v9),
    (10, migrate_v9_to_v10),
]
