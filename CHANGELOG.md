# Changelog

本项目遵循 [SemVer 2.0.0](https://semver.org/lang/zh-CN/) 语义化版本控制。

在 1.0.0 之前，0.MINOR.PATCH 中的 MINOR 用于标记里程碑推进（roadmap 阶段/Task），PATCH 用于同里程碑内的修复与小幅调整。任何可能影响用户数据或破坏已有功能的变化都会使 MINOR 递增。

## [Unreleased]

尚未发布的改动。开发期间此节用于汇总已完成但未标注版本标签的提交。

## [0.2.0] - 2026-07-07

对应 [docs/roadmap.md](docs/roadmap.md) Task 2（数据库 Schema 与领域模型）完成。schema_version 由 0 升至 1。

### Added

- 领域模型 [src/domain/models.py](src/domain/models.py)：ModItem、FileAsset、FolderNode、OperationLog dataclass；AssetKind、FileRole、OperationStatus、ConflictPolicy、OperationType enum；`__post_init__` 轻量校验。
- 路径工具 [src/infrastructure/path_utils.py](src/infrastructure/path_utils.py)：`make_path_key(path)` 实现 A2 决策（normcase + normpath），用于路径比较与唯一约束。不访问文件系统。
- 迁移机制 [src/infrastructure/migrations.py](src/infrastructure/migrations.py)：`MIGRATIONS` 注册表与 `migrate_v0_to_v1`。迁移函数幂等（CREATE TABLE IF NOT EXISTS），不写 schema_version。
- 数据库初始化升级 [src/infrastructure/db.py](src/infrastructure/db.py)：`CURRENT_SCHEMA_VERSION` 升至 1；`init_db` 改为「确保 schema_version 表 → 写入 v0 基线（若空） → 按 target 升序应用 pending 迁移 → 每步迁移独立事务后写入新版本号」。
- Repository 层 [src/infrastructure/repositories/](src/infrastructure/repositories/)：
  - `errors.py`：RepositoryError、NotFoundError、ConstraintViolationError。
  - `mod_item.py`：ModItemRepository（create / get_by_id / list_all / update；tags 序列化为 JSON 数组）。
  - `file_asset.py`：FileAssetRepository（create / get_by_id / list_by_mod_item / list_unassociated / update）。
  - `folder_node.py`：FolderNodeRepository（create / get_by_id / list_by_parent / list_managed_roots / update；is_managed_root 存为 0/1）。
  - `operation_log.py`：OperationLogRepository（create / get_by_id / list_by_status / update；list 字段序列化为 JSON 数组）。
- Schema v1（4 张业务表 + 4 个索引 + CHECK 约束）：
  - `mod_item`：依据 spec §6.1，不引入 status 列（open-questions.md Q1）。
  - `file_asset`：依据 spec §6.2，不引入 batch_id 列（Q2）；path_key UNIQUE；asset_kind/role CHECK。
  - `folder_node`：依据 spec §6.3；path_key UNIQUE；is_managed_root CHECK(0,1)；parent_id 自引用 FK。
  - `operation_log`：依据 spec §6.4；status CHECK；conflict_policy CHECK 仅 'ask'（B3）；operation_type 不加 CHECK（Q16）；undo_payload 为 TEXT，结构由 Task 5 定义（Q14）。
- 测试 fixture [tests/conftest.py](tests/conftest.py)：新增 `db_path` 与 `db_connection` fixture（基于 temp_app_data，使用 Row 工厂）。
- 单元测试 67 项新增（总计 73 项），覆盖：
  - path_utils：normpath、normcase、中文路径、幂等、驱动器大小写（A2）。
  - 领域模型：必填字段、enum 类型、负 size、非 set tags、非 list asset_ids。
  - migrations：MIGRATIONS 排序、migrate_v0_to_v1 幂等、CHECK 约束生效。
  - db：fresh DB → v1、v0 → v1 升级、v1 DB 跳过迁移、外键启用、Row 工厂。
  - ModItemRepository：CRUD、中文标签往返、空 tags 序列化为 '[]'、update not found。
  - FileAssetRepository：CRUD、path_key 唯一约束、多成员关联、未关联素材、中文路径、folder kind、空扩展名。
  - FolderNodeRepository：CRUD、父子关系、list_managed_roots、中文 real_path、update not found。
  - OperationLogRepository：CRUD、状态枚举、B3 conflict_policy 拒绝 'overwrite'、undo_payload JSON、中文错误消息、UNDO 操作类型、空 list 字段。

### Changed

- [tests/test_db.py](tests/test_db.py)：扩展为覆盖 v0→v1 升级、幂等、业务表存在、外键启用、Row 工厂。
- [tests/conftest.py](tests/conftest.py)：新增 db_path 与 db_connection fixture。

### 待确认项

- 新增 [open-questions.md Q16](docs/open-questions.md#L129-L138)：OperationType 完整值集。Task 2 代码层定义 {move, undo}，DB 不加 CHECK，预计 Task 5 决策。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 30 files already formatted
- `python -m pytest` → 73 passed in 34.77s

### Not in Scope

未实现：UI、扫描器、文件移动、AI JSON、搜索、缩略图、application 层服务、文件操作预演与撤销。所有 Repository 仅读写应用自身 SQLite DB，不访问用户文件系统。

## [0.1.0] - 2026-07-07

首个可运行骨架版本。对应 [docs/roadmap.md](docs/roadmap.md) 阶段 0（项目初始化）完成。

### Added

- Python 3.12+ 项目骨架，采用 PySide6、SQLite、pytest、ruff。
- 分层目录结构：`src/app`、`src/domain`、`src/infrastructure`、`src/application`、`tests`、`docs`。
- 应用入口 [src/app/main.py](src/app/main.py)，启动顺序：应用数据目录 → 日志 → 数据库 → Qt 事件循环。
- 应用数据目录初始化 [src/app/app_paths.py](src/app/app_paths.py)，位于 `%LOCALAPPDATA%\SkyrimModWorkbench\`，含 `thumbnails\`、`exports\`、`logs\` 子目录。
- 基础日志 [src/app/logging_setup.py](src/app/logging_setup.py)，RotatingFileHandler，UTF-8，写入 `logs\app.log`。
- 空主窗口 [src/app/main_window.py](src/app/main_window.py)，占位 1024×720。
- SQLite 初始化 [src/infrastructure/db.py](src/infrastructure/db.py)，启用外键与 WAL；创建 `schema_version` 表，初始版本 0；幂等可重复调用。
- 测试 fixture [tests/conftest.py](tests/conftest.py)，`temp_app_data` 将 LOCALAPPDATA 指向临时目录，确保不写入真实用户目录。
- 单元测试 6 项，覆盖应用数据目录创建、数据库初始化与幂等、MainWindow 构造。
- 项目配置 [pyproject.toml](pyproject.toml)：依赖、ruff（line-length=100, target py312）、pytest（pythonpath=src）。
- 待确认问题清单 [docs/open-questions.md](docs/open-questions.md)，记录 15 项未决策事项及其兼容性约束。

### 工程决定

- PySide6 版本约束定为 `>=6.8,<7`。文档未固定版本；在 Python 3.14 环境下 pip 选取 6.11.1。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 14 files already formatted
- `python -m pytest` → 6 passed
- 手动运行 `python -m app.main`，主窗口正常启动，控制台无错误。

### Not in Scope

本版本严格限定于 roadmap 阶段 0。未实现：领域模型、文件扫描、文件移动、Repository CRUD、UI 内容（三栏布局/目录树/卡片）、搜索、AI JSON、缩略图、打包。
