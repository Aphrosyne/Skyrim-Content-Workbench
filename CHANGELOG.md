# Changelog

本项目遵循 [SemVer 2.0.0](https://semver.org/lang/zh-CN/) 语义化版本控制。

在 1.0.0 之前，0.MINOR.PATCH 中的 MINOR 用于标记里程碑推进（roadmap 阶段/Task），PATCH 用于同里程碑内的修复与小幅调整。任何可能影响用户数据或破坏已有功能的变化都会使 MINOR 递增。

## [Unreleased]

尚未发布的改动。开发期间此节用于汇总已完成但未标注版本标签的提交。

## [0.12.0] - 2026-07-12

对应 [docs/roadmap.md](docs/roadmap.md) 阶段 2 Task 3（目录树浏览）完成。schema_version 维持 4。

### Added

- 只读目录树查询服务 [src/application/folder_tree_service.py](src/application/folder_tree_service.py)（新文件）：
  - `TreeNode` dataclass：node_id / display_name / real_path / category / is_managed_root / managed_root_id / folder_cache_id / parent_id。
  - category 取值：`managed_root`（已扫描根目录）/ `unscanned_root`（未扫描根目录）/ `folder`（普通子目录）。
  - 节点 ID 约定：`"mr:<managed_root_id>"` / `"fc:<folder_cache_id>"`。
  - `FolderTreeService.list_root_nodes()`：合并 ManagedRoot 与 FolderCache 根节点，已扫描→managed_root，未扫描→unscanned_root。
  - `FolderTreeService.list_children(node_id)`：按 node_id 前缀分发（mr:→managed_root 子节点，fc:→folder_cache 子节点）。
  - `FolderTreeService.get_node(node_id)` / `count_children(node_id)` / `has_scan_data(managed_root_id)`。
  - 关联逻辑（决策问题 1 选项 B）：对 FolderCache.path 调用 make_path_key 归一化后与 ManagedRoot.path_key 比较，不改 schema。
  - 不访问文件系统；不写数据库。
- Qt 目录树 model [src/app/folder_tree_model.py](src/app/folder_tree_model.py)（新文件）：
  - `FolderTreeModel(QAbstractItemModel)`：采用 Qt 推荐的内部节点对象 + 对象引用 internalPointer 的标准实现。
  - `_Node` 内部类持有 TreeNode、父节点引用、子节点列表、loaded 标记、row_in_parent 行号。
  - 惰性加载（canFetchMore / fetchMore），`fetchMore` 直接使用 View 传入的 parent。
  - `parent()` O(1) 直接访问（通过 _Node.parent 引用 + row_in_parent 缓存）。
  - 数据源严格为 FolderTreeService（即 SQLite folder_cache 表），不重新扫描文件系统。
  - 未扫描根目录 display 追加「（未扫描）」提示。
  - 选中节点可通过 node_at / node_id_at 接口获取。
  - refresh() 重置所有缓存并重新加载根节点。
- UI 文案常量 [src/app/ui_constants.py](src/app/ui_constants.py)：
  - 新增目录树区域常量：TREE_GROUP_TITLE / TREE_EMPTY_HINT / TREE_UNSCANNED_HINT。
  - 新增详情区常量：DETAIL_GROUP_TITLE / DETAIL_NAME_LABEL / DETAIL_PATH_LABEL / DETAIL_IS_ROOT_LABEL / DETAIL_TYPE_LABEL / DETAIL_CHILD_COUNT_LABEL / DETAIL_TYPE_MANAGED_ROOT / DETAIL_TYPE_UNSCANNED_ROOT / DETAIL_TYPE_FOLDER / DETAIL_NOT_SELECTED。
  - 移除旧占位常量 PLACEHOLDER_CONTENT_TITLE / PLACEHOLDER_CONTENT_HINT。

### Changed

- [src/app/main_window.py](src/app/main_window.py)：
  - 构造签名新增 `folder_tree_service: FolderTreeService` 参数。
  - 右栏占位替换为目录树（QTreeView + FolderTreeModel）+ 选中目录详情（QLabel）。
  - 详情区显示 5 字段：目录名称 / 完整路径 / 是否受管理根目录 / 类型 / 直接子目录数（决策问题 4 选项 A）。
  - `_refresh_tree()`：扫描完成/根目录变更后刷新目录树模型。
  - `_on_tree_selection_changed`：选中节点更新详情区。
  - 添加/移除根目录后调用 `_refresh_tree()`。
  - `_on_scan_finished` 扫描完成后调用 `_refresh_tree()`。
- [src/app/main.py](src/app/main.py)：
  - 构造 `FolderTreeService(ManagedRootRepository(conn), FolderCacheRepository(conn))` 注入 MainWindow。

### Fixed

- **FolderTreeModel 架构重构**：初版实现采用字符串 node_id 作为 internalPointer，`parent()` 通过 service 反查 + 线性扫描实现，存在性能与稳定性缺陷。手动验收时连续暴露三个问题：
  1. `hasChildren` 未重写 → QTreeView 不显示展开箭头，根节点无法展开。
  2. `internalPointer()` 在 PySide6 某些调用路径返回非字符串非 None 对象 → `_loaded` 集合 `in` 操作触发 `TypeError: unhashable type`。
  3. `_fetch` 通过 `_find_index_by_node_id` 重新创建 parent index 调用 `beginInsertRows` → Qt C++ 层 persistent index 机制访问无效内存导致 segfault，展开二级节点时闪退且无 Python 异常输出。
  局部补丁修复无效后，按 Qt 官方推荐架构重构为 `_Node` 内部类 + 对象引用 internalPointer 的标准实现：
  - `parent()` 由 O(深度)+反查 变为 O(1) 直接访问。
  - `fetchMore` 直接使用 View 传入的 parent，满足 persistent index 机制对 index 对象身份的要求。
  - 缓存状态集中在 _Node 对象内（children + loaded），消除多处缓存不一致风险。
  - 删除 `_find_index_by_node_id` / `_children_cache` / `_loaded` 等旧实现。

### Tests

- 单元测试 44 项新增（总计 214 passed, 3 skipped），覆盖：
  - `test_folder_tree_service.py`（22 项）：
    - TestListRootNodes（5）：空数据 / 未扫描根 / 已扫描根 / 中文目录名 / 多根目录 / 重复扫描不重复。
    - TestListChildren（6）：空根节点 / 多层层级 / mr: 前缀分发 / fc: 前缀分发 / 无效 node_id / 未扫描根返回空。
    - TestGetNode（4）：managed_root / folder / 无效 ID / 未扫描根。
    - TestCountChildren（3）：直接子目录数 / 孙节点不计入 / 无效 node_id 返回 0。
    - 持久化验证：重新连接数据库后树可加载。
    - TreeNode category 校验：拒绝非法值 / 接受所有合法值。
  - `test_folder_tree_model.py`（22 项，重构后）：
    - 基础测试（10）：空 model / 未扫描顶层节点 / fetchMore 惰性加载 / 父子关系 / 深层访问 / node_at / node_id_at / refresh 重置 / 无效 index / 中文显示名。
    - hasChildren 测试（5）：未扫描根 / 已扫描根未 fetch / 叶子节点 fetch 后 / 已加载父节点 / 空 model。
    - 旧版缺陷回归测试（7）：
      - `test_fetch_does_not_recurse_when_connected_to_view`：连接真实 QTreeView 后 fetchMore 不触发 RecursionError。
      - `test_fetch_empty_children_does_not_emit_rows_inserted`：空子节点不发 rowsInserted 信号。
      - `test_row_count_handles_invalid_index_without_crash`：rowCount 对无效 QModelIndex 不崩溃。
      - `test_index_handles_invalid_parent_without_crash`：index 对无效 parent 不崩溃。
      - `test_has_children_handles_invalid_index_without_crash`：hasChildren 对无效 QModelIndex 不崩溃。
      - `test_deep_expansion_does_not_crash`：**核心回归测试**——Root/L1/L2/L3 逐级展开 + parent 链验证，连接真实 QTreeView，验证 Qt C++ 层 persistent index 机制在多层 fetchMore 下不崩溃。
      - `test_view_loads_root_children_without_crash`：连接真实 QTreeView 后显式 fetchMore 加载根子节点不崩溃。

### 安全限制

- 目录树数据源严格为 SQLite folder_cache 表，不重新扫描文件系统。
- FolderTreeService 只读：不访问文件系统，不写数据库。
- FolderTreeModel 惰性加载：仅在展开节点时查询子节点，避免一次性加载全树。
- 错误隔离：查询异常捕获并降级为空子树，不崩溃。
- UI 不直接访问 Repository 或文件系统（AGENTS 规则 3）。
- 路径归一化使用 make_path_key（normcase + normpath），支持中文路径。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 51 files already formatted
- `python -m pytest` → 214 passed, 3 skipped
- `python -m app.main` → 主窗口正常启动，可添加目录、扫描、浏览目录树（含深层逐级展开）、选中节点查看详情（人工验收通过）

### Not in Scope

- 内容单元列表与浏览模式（Task 4）。
- 双模式切换（Task 5）。
- 缩略图适配新 schema（Task 4+）。
- 文件操作服务适配新 schema（阶段 3）。

## [0.11.0] - 2026-07-12

对应 [docs/roadmap.md](docs/roadmap.md) 阶段 2 Task 2（方向 C 重建：新扫描器 + Domain/Repository/Service/UI 适配）完成。schema_version 维持 4（Task 1 已建立）。

### Added

- Domain 层重写 [src/domain/models.py](src/domain/models.py)：
  - 移除全部旧实体（ModItem / FileAsset / FolderNode / OperationLog / AssetKind / FileRole / OperationStatus / ConflictPolicy / OperationType）。
  - 新增 `ContentUnit`（id / path / title / content_type / source_url / rating / cover_image / status / notes / created_at / updated_at；status ∈ {unorganized, organized}；rating ∈ [0,5] 或 None）。
  - 新增 `TagCategory`（id / name / color_hue ∈ [0,360]）。
  - 新增 `Tag`（id / name / category_id）。
  - 新增 `OperationHistory`（id / operation_type ∈ {move,delete,rename,new_folder} / source_path / target_path / created_at / can_undo）；`VALID_OPERATION_TYPES` 为 ClassVar 避免被 dataclass 视为实例字段。
  - 新增 `FolderCache`（id / path / parent_id / last_scanned_mtime / managed_root_id）；parent_id 可自引用（根节点）。
  - 保留 `ManagedRoot`（未改动）。
- ContentUnitRepository [src/infrastructure/repositories/content_unit.py](src/infrastructure/repositories/content_unit.py)（新文件）：
  - CRUD：create / get_by_id / get_by_path / list_by_path_prefix / list_all / update / delete。
  - path 唯一约束冲突抛 `ConstraintViolationError`。
  - `_row_to_model` 使用 `row["column"]` 索引（需 row_factory = sqlite3.Row）。
- FolderCacheRepository [src/infrastructure/repositories/folder_cache.py](src/infrastructure/repositories/folder_cache.py)（新文件）：
  - CRUD：create / get_by_id / get_by_path / list_by_parent / list_all / upsert_mtime / delete / delete_by_path。
  - path 唯一约束冲突抛 `ConstraintViolationError`。
  - upsert_mtime：已存在则更新 mtime，不存在抛 `NotFoundError`。
- 文件系统扫描器重写 [src/infrastructure/file_scanner.py](src/infrastructure/file_scanner.py)：
  - `ScanError` / `ScannedFolderEntry` / `ScanResult` 数据类。
  - `FileScanner.scan_full(root)`：全量递归扫描。
  - `FileScanner.scan_incremental(root, folder_mtime_map)`：增量扫描，mtime 未变目录跳过记录但仍递归子目录（子目录 mtime 可能独立变化）。
  - 内容单元识别规则（spec §5.4）：文件夹内含压缩包 → 候选 ContentUnit，识别后停止递归子目录。
  - 只读：仅使用 `Path.iterdir` / `is_dir` / `is_file` / `is_symlink` / `stat`，不修改用户文件。
  - 符号链接不跟随（避免循环）。
  - mtime 相等判定使用差值绝对值 < 0.001 秒（避免浮点精度问题）。
  - 单目录扫描失败不中断整体流程，记入 `ScanResult.errors`。
- 扫描编排服务 [src/application/scan_service.py](src/application/scan_service.py)（新文件）：
  - `ScanSummary` dataclass：root_id / root_path / scanned_dirs / content_units_found / skipped_unchanged / errors。
  - `ScanService.scan_root(root_id, incremental=True)`：读取 ManagedRoot，构建 folder_mtime_map（增量），调用 FileScanner，持久化结果。
  - `ScanService.scan_root_by_path(real_path)`：直接按路径全量扫描。
  - 持久化：folder_cache upsert（更新 mtime 或新建）；content_unit create（path 已存在则跳过，避免重复）。
  - root_id 不存在抛 `ManagedRootNotFoundError`；根路径不存在抛 `ScanError`。
- Application 层错误更新 [src/application/errors.py](src/application/errors.py)：
  - 移除 `ModItemNotFoundError` / `FileAssetNotFoundError` / `MemberLimitError` / `DuplicateMemberError`。
  - 新增 `ScanError`。
- ScanWorker 重写 [src/app/scan_worker.py](src/app/scan_worker.py)：
  - 构造签名：`ScanWorker(db_path, root_id, incremental=True)`。
  - 在自身线程创建独立 SQLite 连接（row_factory = sqlite3.Row）。
  - 信号：scan_started / scan_finished(ScanSummary) / scan_failed(str)。
  - 捕获所有异常转为 scan_failed 信号。
- 主窗口最小修复 [src/app/main_window.py](src/app/main_window.py)：
  - 构造签名：`MainWindow(managed_root_service, db_path, commit_callback=None)`。
  - 左栏：受管理根目录列表 + 添加/移除按钮 + 增量扫描按钮 + 全量重扫按钮 + 扫描状态。
  - 右栏：内容区占位（Task 3+ 实现目录树、内容单元列表、详情面板）。
  - 移除全部旧 UI 组件（素材池、ModItem 列表、详情面板、目录树、缩略图、成员表格）。
  - 扫描期间禁用所有扫描入口与根目录操作按钮。
  - closeEvent 等待后台线程退出。
- 应用入口简化 [src/app/main.py](src/app/main.py)：
  - 仅构造 ManagedRootService 注入 MainWindow。
  - 移除 ModAssemblyService / FolderTreeService / ThumbnailCoordinator 等旧依赖。
- UI 文案更新 [src/app/ui_constants.py](src/app/ui_constants.py)：
  - APP_TITLE 改为 "Skyrim Content Workbench"。
  - 新增 SCAN_BUTTON_FULL / SCAN_BUTTON_SCANNING。
  - format_summary 改名 format_scan_summary，参数调整为 scanned_dirs / content_units_found / skipped_unchanged / errors。
  - 移除旧 Task 3/4 相关常量（素材池、ModItem 列表、详情编辑、成员表格、角色名）。

### Changed

- [src/domain/models.py](src/domain/models.py)：完全重写（见 Added）。
- [src/infrastructure/file_scanner.py](src/infrastructure/file_scanner.py)：完全重写（见 Added）。
- [src/app/scan_worker.py](src/app/scan_worker.py)：完全重写（见 Added）。
- [src/app/main_window.py](src/app/main_window.py)：完全重写为最小可启动版本（见 Added）。
- [src/app/main.py](src/app/main.py)：简化为仅注入 ManagedRootService。
- [src/app/ui_constants.py](src/app/ui_constants.py)：重写文案常量（见 Added）。
- [src/application/errors.py](src/application/errors.py)：移除旧错误，新增 ScanError。

### Removed

- 删除旧 Domain 实体（ModItem / FileAsset / FolderNode / OperationLog 及相关 enum）。
- 删除旧 Repository 模块：
  - `src/infrastructure/repositories/mod_item.py`
  - `src/infrastructure/repositories/file_asset.py`
  - `src/infrastructure/repositories/folder_node.py`
  - `src/infrastructure/repositories/operation_log.py`
- 删除旧 Application Service：
  - `src/application/scan_workflow_service.py`
  - `src/application/mod_assembly_service.py`
  - `src/application/folder_tree_service.py`
- 删除旧 UI model：
  - `src/app/pool_model.py`
  - `src/app/folder_tree_model.py`
- 删除旧测试文件：
  - `tests/test_scan_workflow_service.py`

### Preserved（保留但未在 main.py 引用，Task 3+ 重新接入）

- `src/application/thumbnail_coordinator.py`：保留文件，移除 main.py 引用（决策 1）。
- `src/app/thumbnail_worker.py`：保留文件，移除 main.py 引用。
- `src/infrastructure/thumbnail_generator.py`：保留文件，测试仍 skip。
- `src/infrastructure/file_operation_service.py`：保留文件，移除 main.py 引用（决策 2）。
- `src/infrastructure/repositories/thumbnail_cache.py`：保留文件，测试仍 skip。

### Skipped（测试仍 module-level skip，Task 3+ 重新启用）

- `tests/test_folder_tree_model.py`：Task 3 重写目录树后启用。
- `tests/test_folder_tree_service.py`：Task 3 重写目录树后启用。
- `tests/test_thumbnail_coordinator.py`：Task 4+ 适配新 schema 后启用。
- `tests/test_thumbnail_generator.py`：Task 4+ 适配新 schema 后启用。
- `tests/test_thumbnail_cache.py`：Task 4+ 适配新 schema 后启用。

### Tests

- 单元测试 92 项新增/重写（总计 170 passed, 5 skipped），覆盖：
  - `test_domain_models.py`（完全重写，33 项）：ContentUnit（10）/ TagCategory（6）/ Tag（4）/ OperationHistory（5）/ FolderCache（4）/ ManagedRoot（4）。
  - `test_content_unit_repository.py`（新文件，16 项）：create+get_by_id / get_by_path / 中文路径 / path 唯一约束 / id 重复 / list_by_path_prefix / list_all / update / delete。
  - `test_folder_cache_repository.py`（新文件，16 项）：create+get_by_id / get_by_path / 中文路径 / path 唯一约束 / list_by_parent / list_all / upsert_mtime / parent 自引用 / delete。
  - `test_file_scanner.py`（完全重写，11 项）：全量扫描（7：扫描所有子目录、识别内容单元候选、不递归内容单元、中文路径、根不存在、根非目录、空根）+ 增量扫描（3：未变跳过、变更重扫、无缓存全扫）+ 符号链接（1，Windows 权限不足 skip）。
  - `test_scan_service.py`（新文件，11 项）：全量扫描（4：持久化 folder_cache、持久化 content_unit、默认 status、标题为目录名）+ 增量扫描（2：跳过未变、重扫变更）+ 错误（2：root 不存在、路径不存在）+ scan_by_path（1）+ 重复扫描（2：无重复 content_unit、无重复 folder_cache）。
  - `test_scan_worker.py`（完全重写，4 项）：scan_finished 回传 summary / 持久化到 DB / 不存在 root 触发 scan_failed / 增量扫描跳过未变目录。

### 安全限制

- 扫描器严格只读：不移动、不删除、不重命名、不修改、不读取文件内容（仅 iterdir / is_dir / is_file / stat）。
- 符号链接不跟随（避免循环）。
- 单目录扫描失败不中断整体流程。
- ScanWorker 在后台线程创建独立 SQLite 连接，不冻结 UI。
- 扫描期间禁用所有扫描入口与根目录操作按钮。
- UI 不直接访问 Repository 或文件系统（AGENTS 规则 3）。
- 路径、日志、数据库文本编码为 UTF-8。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 49 files already formatted
- `python -m pytest` → 170 passed, 5 skipped

### Not in Scope

- 目录树浏览 UI（Task 3）。
- 内容单元列表与浏览模式（Task 4）。
- 双模式切换（Task 5）。
- 缩略图适配新 schema（Task 4+）。
- 文件操作服务适配新 schema（阶段 3）。
- `thumbnail_coordinator` / `file_operation_service` / `thumbnail_worker` 保留源文件但未接入 main.py，Task 3+ 重新启用。

## [0.10.0] - 2026-07-12

对应 [docs/roadmap.md](docs/roadmap.md) 阶段 2 Task 1（方向 C 重建：新数据库 Schema + 迁移）完成。schema_version 由 3 升至 4。

### Added

- Schema v4 迁移 [src/infrastructure/migrations.py](src/infrastructure/migrations.py)：
  - 新增 `migrate_v3_to_v4(conn)`：方向 C 重建——建立 ContentUnit 体系，移除旧表，重建 thumbnail_cache。
  - 新建 6 张表：`content_unit` / `tag_category` / `tag` / `content_unit_tag` / `operation_history` / `folder_cache`（均 IF NOT EXISTS，幂等）。
  - 新建 8 个索引（content_unit status/path、tag category_id、content_unit_tag 双向、operation_history created_at、folder_cache parent/path）。
  - 重建 `thumbnail_cache`：列名 `asset_id` → `content_unit_id`，FK 由 `file_asset(id)` 改为 `content_unit(id)`（drop + create）。
  - 移除旧表：`operation_log` / `file_asset` / `mod_item` / `folder_node`（drop 顺序遵循 FK 依赖）。
  - 保留 `managed_root` 表与数据不受影响。
  - `CURRENT_SCHEMA_VERSION` 升至 4（[src/infrastructure/db.py](src/infrastructure/db.py)）。
- 应用数据目录改名 [src/app/app_paths.py](src/app/app_paths.py)：
  - `APP_DATA_DIR_NAME` 由 `SkyrimModWorkbench` 改为 `SkyrimContentWorkbench`。
  - docstring 同步更新。
- 单元测试 10 项新增（v4 迁移覆盖）+ 既有测试调整：
  - `test_migrate_v3_to_v4_creates_new_tables`：6 张新表 + 8 个索引。
  - `test_migrate_v3_to_v4_drops_old_tables`：mod_item/file_asset/folder_node/operation_log 移除。
  - `test_migrate_v3_to_v4_idempotent`：连续两次调用幂等。
  - `test_migrate_v3_to_v4_preserves_managed_root_data`：managed_root 数据保留。
  - `test_migrate_v3_to_v4_thumbnail_cache_uses_content_unit_id`：列名 + FK 验证。
  - `test_migrate_v3_to_v4_check_constraints`：operation_type/status CHECK 约束。
  - `test_migrate_v3_to_v4_unicode_support`：中文路径与标签。
  - `test_migrate_v3_to_v4_folder_cache_self_reference_ok`：parent_id 自引用。
  - `test_init_db_migrates_v3_db_to_v4`：完整 v3→v4 升级场景（含 managed_root 中文路径数据保留）。
  - `test_current_schema_version_is_four`：版本断言。
  - 调整：`test_migrations_sorted_by_target` 增加 v4 断言；`test_init_db_migrates_from_v0_to_current` 增加 v4 表存在性断言。

### Changed

- [src/infrastructure/db.py](src/infrastructure/db.py)：`CURRENT_SCHEMA_VERSION` 由 3 升至 4。
- [src/infrastructure/migrations.py](src/infrastructure/migrations.py)：`MIGRATIONS` 注册表新增 v3→v4 迁移。
- [src/app/app_paths.py](src/app/app_paths.py)：`APP_DATA_DIR_NAME` 改为 `SkyrimContentWorkbench`。
- [tests/test_db.py](tests/test_db.py)：`test_init_db_creates_business_tables` 改为断言 v4 新表存在且旧表已移除；`test_init_db_upgrades_from_v0_baseline` 改为断言 `content_unit` 表；`test_init_db_with_v1_db_skips_migration` 重命名为 `test_init_db_at_current_version_skips_migration`。
- [tests/test_app_paths.py](tests/test_app_paths.py)：新增 `APP_DATA_DIR_NAME == "SkyrimContentWorkbench"` 断言。
- [tests/conftest.py](tests/conftest.py)：`temp_app_data` fixture 注释更新为 `SkyrimContentWorkbench`。
- [tests/test_managed_root_repository.py](tests/test_managed_root_repository.py)：`test_delete_preserves_folder_node_and_file_asset` 重写为 `test_delete_preserves_content_unit_and_folder_cache`（引用 v4 新表）。
- [tests/test_managed_root_service.py](tests/test_managed_root_service.py)：`test_add_root_does_not_modify_target_directory` 与 `test_remove_root_does_not_clean_scan_records` 改为引用 `content_unit` / `folder_cache` 表。
- [docs/roadmap.md](docs/roadmap.md)：标记阶段 2 Task 1 完成；更新验收清单。

### Removed

- 删除 9 个纯废弃模块测试文件（依赖已移除的旧表/旧服务，Task 2+ 不再保留）：
  - `tests/test_mod_item_repository.py`
  - `tests/test_file_asset_repository.py`
  - `tests/test_folder_node_repository.py`
  - `tests/test_operation_log_repository.py`
  - `tests/test_mod_assembly_service.py`
  - `tests/test_pool_model.py`
  - `tests/test_main_window.py`
  - `tests/test_file_operation_service.py`
  - `tests/test_thumbnail_ui.py`

### Skipped

- 标记 9 个重写模块测试文件为 module-level skip（Task 2+ 重写后重新启用）：
  - `tests/test_domain_models.py`：domain.models 将在 Task 2 重写为 ContentUnit 等新实体。
  - `tests/test_file_scanner.py` / `test_scan_worker.py` / `test_scan_workflow_service.py`：扫描器将在 Task 2 重写。
  - `tests/test_folder_tree_model.py` / `test_folder_tree_service.py`：目录树将在 Task 3 重写。
  - `tests/test_thumbnail_coordinator.py` / `test_thumbnail_generator.py` / `test_thumbnail_cache.py`：缩略图模块将在 Task 4+ 适配新 schema。

### 安全限制

- 迁移函数仅执行 DDL（CREATE/DROP），不读取或修改用户文件。
- `managed_root` 用户配置数据在迁移中保留；其余旧业务表数据不迁移（roadmap 明确，用户已知）。
- 应用数据目录改名后，旧目录 `%LOCALAPPDATA%\SkyrimModWorkbench\` 下的 app.db 与缩略图缓存不再使用（用户手动删除）。
- 不联网；不读写压缩包内容；不修改用户原始图片。

### Not in Scope

- Domain 模型重写（ContentUnit / Tag / TagCategory 等 dataclass）——Task 2。
- 新 Repository / Service / UI 实现——Task 2+。
- 旧 Repository / Service / UI 源文件删除——Task 2（本次仅处理测试文件）。
- 新扫描器实现——Task 2。
- `python -m app.main` 在 Task 1 完成后仍会失败（因 main.py 仍依赖废弃 Service），属预期，Task 2+ 修复。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 53 files already formatted
- `python -m pytest` → 77 passed, 9 skipped in 2.23s

## [0.9.0] - 2026-07-11

对应 [docs/roadmap.md](docs/roadmap.md) 阶段 2 Task 4（本地缩略图缓存与 ModItem 预览图展示）完成。schema_version 由 2 升至 3。

### Added

- Schema v3 迁移 [src/infrastructure/migrations.py](src/infrastructure/migrations.py)：
  - 新增 `migrate_v2_to_v3(conn)`：创建 `thumbnail_cache` 表（`asset_id` PK / `source_size_bytes` / `source_modified_at` / `cache_filename` / `status` CHECK / `error_message` / `generated_at` / FK→file_asset）；幂等。
  - `CURRENT_SCHEMA_VERSION` 升至 3（[src/infrastructure/db.py](src/infrastructure/db.py)）。
- Repository [src/infrastructure/repositories/thumbnail_cache.py](src/infrastructure/repositories/thumbnail_cache.py)（新文件）：
  - `ThumbnailCacheRecord` dataclass + `ThumbnailCacheRepository`（get_by_asset_id / upsert / delete）。
- 缩略图生成器 [src/infrastructure/thumbnail_generator.py](src/infrastructure/thumbnail_generator.py)（新文件）：
  - `ThumbnailStatus(StrEnum)`：`ok` / `missing` / `corrupt` / `unsupported` / `error`。
  - `ThumbnailGenerator`：延迟导入 Pillow 只读加载源图，生成缩略图写入 `cache_dir`；所有错误转为 ThumbnailResult 返回，不抛异常。
  - 支持格式：JPG/JPEG/PNG/WEBP/GIF/BMP/TIF/TIFF/ICO。
  - `cache_dir` property。
- Application 协调层 [src/application/thumbnail_coordinator.py](src/application/thumbnail_coordinator.py)（新文件）：
  - `ThumbnailInfo` DTO + `ThumbnailCoordinator`：`get_thumbnail_info` / `generate_thumbnail` / `get_cover_thumbnail_info`。
  - 缓存有效性检查（source_size + source_modified_at 匹配）。
  - `cache_dir` property。
- UI 后台 worker [src/app/thumbnail_worker.py](src/app/thumbnail_worker.py)（新文件）：
  - `ThumbnailWorker(QObject)`：在 `run()` 内创建独立 SQLite 连接 + ThumbnailCoordinator，逐个生成缩略图；信号 `thumbnail_ready(str, object)` + `finished()`。
- UI 升级 [src/app/main_window.py](src/app/main_window.py)：
  - 构造签名新增 `thumbnail_coordinator` 参数。
  - 成员表格从 5 列扩展为 6 列（新增封面列）；preview 成员可"设为封面"，非 preview 被拒绝。
  - 详情区新增封面预览 QGroupBox + QLabel。
  - `_request_thumbnail` / `_on_thumbnail_ready` / `_refresh_cover_icons` / `_on_set_cover` / `_load_cover_preview`。
  - `closeEvent` 等待缩略图线程退出。
- UI model [src/app/pool_model.py](src/app/pool_model.py)：
  - `ModItemListModel` 升级：`refresh()` 查询成员数；`data()` 支持 `Qt.DecorationRole`；`set_cover_icon` 方法。
- UI 文案 [src/app/ui_constants.py](src/app/ui_constants.py)：新增封面与缩略图相关常量。
- 应用入口 [src/app/main.py](src/app/main.py)：构造 `ThumbnailCoordinator` 注入 `MainWindow`。
- 依赖 [pyproject.toml](pyproject.toml)：新增 `Pillow>=10.0` 正式运行依赖。
- 单元测试 43 项新增（总计 335 passed, 2 skipped），覆盖：
  - `test_thumbnail_generator.py`（12 项，新文件）：PNG/WEBP/JPG 生成、缓存目录隔离、源文件不变性、中文路径、缺失文件、损坏图片、不支持格式、缩略图尺寸、缓存路径一致性。
  - `test_thumbnail_cache.py`（9 项，新文件）：表存在、schema 版本=3、v3 迁移幂等、upsert+get、upsert 覆盖、get 缺失、delete、delete 幂等、CHECK 约束。
  - `test_thumbnail_coordinator.py`（14 项，新文件）：无缓存记录、asset 不存在、有效缓存、size/mtime 过期、生成成功/缺失/损坏/不支持、源文件不变、中文路径、get_cover_thumbnail_info、缓存命中。
  - `test_thumbnail_ui.py`（9 项，新文件）：ThumbnailWorker 异步生成、设为封面更新成员表、非 preview 被拒绝、列表显示成员数、列表支持封面图标、封面预览 QLabel 存在、成员表格 6 列、设为封面后预览显示、不阻塞主线程。
  - `test_migrations.py`（+1 项，调整 2 项）：MIGRATIONS 含 v3、CURRENT_SCHEMA_VERSION==3、init_db 从 v0 迁移到当前版本、幂等。

### Changed

- [src/infrastructure/db.py](src/infrastructure/db.py)：`CURRENT_SCHEMA_VERSION` 由 2 升至 3。
- [src/infrastructure/migrations.py](src/infrastructure/migrations.py)：`MIGRATIONS` 注册表新增 v2→v3 迁移。
- [src/app/main_window.py](src/app/main_window.py)：构造签名新增 `thumbnail_coordinator`；成员表格 6 列；新增封面预览区与缩略图后台生成逻辑。
- [src/app/pool_model.py](src/app/pool_model.py)：`ModItemListModel` 升级（成员数显示、DecorationRole、set_cover_icon）。
- [src/app/main.py](src/app/main.py)：构造 `ThumbnailCoordinator` 注入 `MainWindow`。
- [src/app/ui_constants.py](src/app/ui_constants.py)：新增封面与缩略图相关常量。
- [pyproject.toml](pyproject.toml)：新增 `Pillow>=10.0` 运行依赖。
- [tests/test_migrations.py](tests/test_migrations.py)：测试名与断言更新为 v3。
- [docs/spec.md](docs/spec.md)：更新 §10 预览图（阶段 2 Task 4 已实现范围）。
- [docs/architecture.md](docs/architecture.md)：更新 §8 缩略图架构（分层、缓存策略、安全约束）。
- [docs/roadmap.md](docs/roadmap.md)：标记 Task 4 完成；更新验收清单。
- [docs/progress.md](docs/progress.md)：新增 Task 4 完成内容；更新验收清单。
- [docs/open-questions.md](docs/open-questions.md)：Q5（缓存失效策略）已关闭、Q13（缩略图命名）已关闭。

### 安全限制

- 只读访问用户原图；不修改、不转换、不压缩、不覆盖。
- 缩略图仅写入 `%LOCALAPPDATA%\SkyrimModWorkbench\thumbnails\`，不写入用户 Mod 目录。
- 不联网；不调用 `FileOperationService`；不读取或解压用户压缩包内容。
- 失败时显示安全占位状态，不尝试"修复"用户文件。
- 缩略图生成在后台线程执行，worker 在自身线程内创建独立 SQLite 连接，不卡死 UI。

### 待确认项

- 关闭 [open-questions.md Q5](docs/open-questions.md)：缩略图缓存失效策略（asset_id + source_size + source_modified_at）。
- 关闭 [open-questions.md Q13](docs/open-questions.md)：缩略图命名（`{asset_id}.png` + thumbnail_cache 表）。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 62 files already formatted
- `python -m pytest` → 335 passed, 2 skipped in 9.97s
- `python -m app.main` → 主窗口正常启动，可设封面、查看缩略图（人工验证步骤见下方）

### 人工验证步骤

1. 扫描含中文路径图片的测试根目录。
2. 将图片关联为 preview 成员。
3. 在成员表格点击"设为封面"。
4. 卡片列表与详情区显示封面缩略图。
5. 重启应用，确认缓存可复用。
6. 修改测试图片后重新打开/刷新，确认缓存失效后重建。
7. 确认原图未变化。

### Not in Scope

未实现：预览图墙、Nexus URL 导入预览图、OCR、图像识别、搜索、AI JSON、拖拽移动、文件监听、增量扫描、压缩包内容解析、自动分组、AI 建议。
本任务不修改 `FileOperationService` 的行为；不修改 `FileScanner` 同步签名。

## [0.6.2] - 2026-07-11

对应阶段 2 Task 1 遗漏补完：移除受管理根目录配置。Task 1 验收标准要求"可移除根目录配置；移除配置不删除、不移动、不修改该目录及其中任何用户文件"，但原实现主动跳过了该项。本次作为 Task 1 遗漏的最小补完。

### Added

- `ManagedRootRepository.delete(root_id)`：按 ID 删除 `managed_root` 记录，实体不存在抛 `NotFoundError`，写操作自提交（与 `create` 一致）。
- `ManagedRootService.remove_root(root_id)`：先校验存在性（抛 `ManagedRootNotFoundError`），再调用 `repo.delete`。
- `MainWindow._on_remove_root()`：左栏「移除选中目录」按钮，弹出确认对话框，用户确认后调用 `service.remove_root` 并刷新列表。
- 按钮状态联动：`_on_selection_changed` / `_begin_scanning` / `_end_scanning` 同步禁用/恢复移除按钮；扫描期间禁用。
- `MainWindow.is_remove_button_enabled()`：测试接口。
- UI 文案：`REMOVE_ROOT_BUTTON` / `REMOVE_ROOT_CONFIRM_TITLE` / `REMOVE_ROOT_CONFIRM_TEXT` / `ERR_REMOVE_ROOT_FAILED`。

### Changed

- [src/application/managed_root_service.py](src/application/managed_root_service.py)：移除模块注释中"本任务不实现删除根目录配置"说明，改为说明移除配置不清理扫描记录。
- [src/infrastructure/repositories/managed_root.py](src/infrastructure/repositories/managed_root.py)：新增 `NotFoundError` 导入。

### Tests

- `test_managed_root_repository.py`（+5 项）：delete 删除记录、delete 自提交、delete 不存在抛 NotFoundError、delete 不影响其他根目录、delete 保留 folder_node/file_asset。
- `test_managed_root_service.py`（+5 项）：remove_root 删除配置、remove_root 不存在抛错、remove_root 保留真实目录与文件（mtime/size 不变）、remove_root 不清理扫描记录、remove_root 自提交。
- `test_main_window.py`（+6 项）：移除按钮无选择禁用、选中启用、初始禁用、确认后从列表消失且真实目录保留、取消确认保留列表、移除后真实目录文件不变、扫描期间禁用。
- 总计 291 passed, 2 skipped（原 266 项，新增 25 项）。

### Constraints

- 仅删除 `managed_root` 记录，不删除、不移动、不修改任何用户文件。
- 不清理 `folder_node` / `file_asset` 扫描记录（清理策略待确认，见 docs/phase-2-plan.md 任务 1 范围外内容）。
- 不修改数据库 schema，不引入新的设计或决策。

## [0.8.1] - 2026-07-11

对应阶段 2 Task 3 缺口修复（素材池布局调整、显示字段补全、新建自动关联、按钮状态联动）。

### Fixed

- **布局调整**：目录树从中栏移至左栏（与受管理根目录列表、扫描状态、目录详情同栏）。中栏改为素材池 + ModItem 列表 + 新建/关联按钮。右栏改为 ModItem 详情编辑 + 成员表格。修复前目录树占据中栏主要空间，素材池可视区域过小。
- **素材池显示字段补全**：`UnassociatedPoolModel._format_display` 从仅显示 `📁 filename` 改为 `📁 filename  (类型)  完整路径`，满足"文件名、类型、完整路径"三项可见字段要求。
- **新建 Mod 条目自动关联**：`_on_new_mod()` 创建 ModItem 后自动将素材池中选中的素材以 `UNKNOWN` 角色关联到新条目。修复前创建 ModItem 后不关联任何素材，用户需额外手动关联。
- **新建按钮状态联动**：新增 `_update_new_mod_button()` 和 `_on_pool_selection_changed()`。「新建 Mod 条目」按钮在素材池无选择时禁用；素材池选择变化时同步更新「新建」和「关联」按钮状态。修复前「新建」按钮始终启用。

### Added

- `test_pool_model_display_includes_type_and_path`：文件型素材显示包含类型和完整路径。
- `test_pool_model_display_folder_includes_type_and_path`：文件夹型素材显示包含类型和完整路径。
- `test_main_window_new_mod_button_disabled_without_pool_selection`：素材池无选择时「新建」按钮禁用，选中后启用。
- `test_main_window_new_mod_auto_associates_selected_assets`：新建 ModItem 自动关联选中素材。
- `test_main_window_pool_display_shows_full_path`：素材池显示文本包含完整路径。

### Changed

- [src/app/main_window.py](src/app/main_window.py)：`_setup_ui` 重构三栏布局；新增 `_update_new_mod_button` / `_on_pool_selection_changed`；`_on_new_mod` 增加自动关联逻辑；`_refresh_pool` 增加新建按钮状态更新。
- [src/app/pool_model.py](src/app/pool_model.py)：`_format_display` 增加类型和完整路径。
- [docs/spec.md](docs/spec.md)：更新 §8 UI 结构描述。
- [docs/architecture.md](docs/architecture.md)：更新 §2.4 写入链路与边界约定。
- [docs/progress.md](docs/progress.md)：新增 Task 3 缺口修复内容。

## [0.8.0] - 2026-07-11

对应 [docs/roadmap.md](docs/roadmap.md) 阶段 2 Task 3（未归类素材池与人工 Mod 条目组装）完成。

### Added

- Application 层查询入口 [src/application/mod_assembly_service.py](src/application/mod_assembly_service.py)：
  - `list_unassociated_assets()`：委托 `FileAssetRepository.list_unassociated()`，返回 `mod_item_id` 为 `NULL` 的 `FileAsset` 列表，供 UI 素材池展示。不复制关联规则到 UI；`ROLE_LIMITS` 仍为唯一规则源。
- UI model [src/app/pool_model.py](src/app/pool_model.py)（新文件）：
  - `UnassociatedPoolModel(QAbstractListModel)`：包装未关联 `FileAsset` 列表，显示 `📁 filename` / `📄 filename`，tooltip 显示完整路径；`refresh()` 重置；多选支持。
  - `ModItemListModel(QAbstractListModel)`：包装 `ModItem` 列表，显示 `display_name` 或"(未命名)"；`refresh()` 重置。
  - `ROLE_DISPLAY_NAMES` / `ROLE_ORDER`：角色中文显示名与下拉顺序，集中定义；角色数量限制仍由 `ModAssemblyService.ROLE_LIMITS` 强制，UI 不复制规则。
  - 错误隔离：捕获查询异常，记录日志并降级为空列表。
  - 测试接口：`asset_at` / `asset_id_at` / `asset_count` / `mod_item_at` / `mod_item_id_at` / `item_count`。
- UI 文本常量 [src/app/ui_constants.py](src/app/ui_constants.py)：新增素材池、ModItem 列表、详情编辑、成员表格、角色中文名、操作按钮与错误提示常量。
- 主窗口重写 [src/app/main_window.py](src/app/main_window.py)：
  - 构造签名新增 `mod_assembly_service` 参数。
  - 中栏：素材池 `QListView`（ExtendedSelection）+ ModItem 列表 `QListView`（SingleSelection）+ 新建 Mod 条目按钮 + 关联到选中条目按钮。
  - 右栏：ModItem 详情编辑表单（显示名称 QLineEdit / 说明 QTextEdit / 来源链接 QLineEdit / 标签 QLineEdit + 保存元数据按钮）+ 成员表格 `QTableWidget`（文件名/类型/角色下拉 QComboBox/路径/移除按钮 QPushButton）。
  - `_on_new_mod()`：QInputDialog 输入名称创建 ModItem，刷新列表并选中新条目。
  - `_on_associate()`：多选素材以 `UNKNOWN` 角色关联到当前 ModItem，展示错误。
  - `_on_role_changed(asset_id)`：通过 `self.sender()` 获取 QComboBox，调用 `set_member_role`；展示 `MemberLimitError` / `DuplicateMemberError`。
  - `_on_remove_member(asset_id)`：调用 `remove_member`，刷新成员表和素材池。
  - `_on_save_metadata()`：保存名称/说明/URL/标签（中文逗号分隔标签）。
  - 扫描完成/失败后调用 `_refresh_pool()`，新扫描的未关联素材进入素材池。
  - 测试接口：`pool_count()` / `mod_list_count()` / `mod_detail_name()` / `members_table_row_count()`。
- 应用入口 [src/app/main.py](src/app/main.py)：构造 `ModAssemblyService` 注入 `MainWindow`。
- 单元测试 22 项新增（总计 266 passed, 2 skipped），覆盖：
  - `test_mod_assembly_service.py`（+3 项）：`list_unassociated_assets` 基础（3 未关联 + 2 已关联）、中文名素材、文件夹型素材。
  - `test_pool_model.py`（13 项，新文件）：素材池空/显示未关联/关联后消失/解除后重现/中文文件名/文件夹类型/文件 tooltip；ModItem 列表空/显示条目/未命名显示/创建后刷新/中文标签 tooltip。
  - `test_main_window.py`（+6 项）：素材池初始空、扫描后显示未关联素材、创建 ModItem 并关联、移除成员回到素材池、元数据保存持久化、无选择时关联保护。

### Changed

- [src/app/main_window.py](src/app/main_window.py)：构造签名新增 `mod_assembly_service` 参数；中栏新增素材池与 ModItem 列表；右栏新增 ModItem 详情编辑与成员表格。
- [src/app/main.py](src/app/main.py)：构造 `ModAssemblyService` 注入 `MainWindow`。
- [src/app/ui_constants.py](src/app/ui_constants.py)：新增素材池、ModItem 列表、详情编辑、成员表格、角色中文名与错误提示常量。
- [tests/test_main_window.py](tests/test_main_window.py)：适配新构造签名（注入 `ModAssemblyService`），扩展 6 项 Task 3 测试。
- [docs/spec.md](docs/spec.md)：新增 §5.5 未归类素材池与人工 Mod 条目组装（15 条行为规范）；更新 §8 UI 结构反映 Task 3 实现。
- [docs/architecture.md](docs/architecture.md)：新增 §2.4 素材池与 Mod 组装 UI model/view 边界（写入链路、边界约定）；更新 §3 application 层职责；扩展 §11 测试策略。
- [docs/roadmap.md](docs/roadmap.md)：标记 Task 3 完成；更新验收清单。
- [docs/open-questions.md](docs/open-questions.md)：更新 Q11 实现现状（不关闭未决部分）；Q19 保持不变。
- [docs/progress.md](docs/progress.md)：新增 Task 3 完成内容；更新验收清单。

### Fixed（阶段 2 Task 2 验收修复，自 v0.7.0 起）

- **目录树启动崩溃（无限递归）**：`FolderTreeModel._fetch` 在
  [src/app/folder_tree_model.py](src/app/folder_tree_model.py) 中调用
  `beginInsertRows` **之后**才设置 `_loaded` 标记与 `_children_cache`。
  `beginInsertRows` 同步触发 view 查询 `rowCount`，而 `rowCount` 检查
  `_loaded` 未设置又调用 `_fetch`，形成无限递归直至 `RecursionError`。
  当 `%LOCALAPPDATA%\SkyrimModWorkbench\app.db` 中已有 Task 1 验收时
  残留的扫描数据时，启动即崩溃。修复（`_fetch` 方法）：
  - 开头加 `if parent_node_id in self._loaded: return` 重入保护；
  - `_children_cache` 与 `_loaded` 赋值移到 `beginInsertRows` **之前**；
  - 空子节点跳过 `beginInsertRows`/`endInsertRows`（避免
    `beginInsertRows(idx, 0, 0)` 误报"插入 1 行"）。
- **扫描结果未持久化导致目录树始终"未扫描"**：
  `ScanWorker.run` 在 [src/app/scan_worker.py](src/app/scan_worker.py) 中
  调用 `service.scan_root` 后直接 `conn.close()`，未调用 `conn.commit()`。
  而 `persist_scan_result` 与 `FolderNodeRepository.create` /
  `FileAssetRepository.create` 均不自提交事务（与 `ManagedRootRepository.create`
  不同），导致扫描结果在连接关闭时被 SQLite 回滚。修复：
  在 `scan_root` 返回后、`scan_finished.emit` 前调用 `conn.commit()`。
  不修改 `ScanWorkflowService`、Repository 接口或事务策略。
- **技术债记录**：`rowCount` 中的副作用（未加载时调用 `_fetch`）记录为
  open question Q21，本次不调整加载策略，仅缓解递归。
  `persist_scan_result` 不自提交仍为已知遗留问题（v0.6.0 起记录），
  本次仅在 `ScanWorker` 层补提交，不统一 Repository 写操作提交策略。
- `test_fetch_does_not_recurse_when_connected_to_view`：model 连接真实
  `QTreeView` 后 `fetchMore` 不触发 `RecursionError`（[tests/test_folder_tree_model.py](tests/test_folder_tree_model.py)）。
- `test_fetch_empty_children_does_not_emit_rows_inserted`：空子节点
  不发 `rowsInserted` 信号（[tests/test_folder_tree_model.py](tests/test_folder_tree_model.py)）。
- `test_fetch_sets_loaded_before_begin_insert_rows`：通过
  `rowsAboutToBeInserted` 信号中查询 `rowCount` 验证 `_loaded` 顺序，
  确保重入不递归（[tests/test_folder_tree_model.py](tests/test_folder_tree_model.py)）。
- `test_scan_worker_persists_results_to_db`：扫描完成后用独立连接验证
  `folder_node` 与 `file_asset` 表非空，确保事务已提交（[tests/test_scan_worker.py](tests/test_scan_worker.py)）。
- `test_main_window_tree_refresh_after_scan`：扫描完成后新增验证根节点
  不再显示"未扫描"且可展开有子节点（[tests/test_main_window.py](tests/test_main_window.py)）。
  修复前该测试仅验证 `tree_root_count() == 1`，漏掉了数据未持久化的场景。

### 安全限制

- 本任务严格只读用户文件：不调用 `FileOperationService` 的任何方法。
- 关联/移除成员只写应用数据库 `file_asset` 表（`mod_item_id` / `role` 字段），不移动、不复制、不删除、不重命名任何用户文件。
- 不生成缩略图、不读取图片内容、不把用户文件复制进应用数据目录。
- 素材池数据源严格为 SQLite `file_asset` 表；不在 UI 线程重新扫描文件系统。
- UI 不直接访问 SQLite connection 或 Repository；所有写操作通过 `ModAssemblyService`。
- 路径、日志、数据库文本编码为 UTF-8。

### 待确认项

- 本任务未触及新的 open question。
- Q11（未归类素材如何移出素材池）：更新实现现状（`UnassociatedPoolModel` 列出未关联素材，不实现忽略/删除/移出机制），长期处置策略保留未决。
- Q19（成员角色数量限制）：保持不变（`MAIN_MOD≤1`、`README≤1`，其他不限），UI 直接展示服务层返回的错误。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 54 files already formatted
- `python -m pytest` → 266 passed, 2 skipped in 8.64s
- `python -m app.main` → 主窗口正常启动，三栏布局，可添加目录、扫描、浏览目录树、选中节点查看详情、素材池多选、创建 ModItem、关联素材、编辑角色、移除成员、编辑元数据（人工验证步骤见下方）

### 人工验证步骤

1. 运行 `python -m app.main`，主窗口显示三栏布局：左栏「受管理根目录」+ 按钮、中栏「目录树」+ 素材池 + ModItem 列表 + 按钮、右栏「扫描状态」+ 目录详情 + ModItem 详情编辑 + 成员表格。
2. 添加并扫描一个包含本体压缩包、汉化压缩包、图片和说明文件的测试目录。
3. 扫描完成后，中栏素材池应显示所有未关联素材（文件 📄 / 文件夹 📁），tooltip 显示完整路径。
4. 在素材池多选素材，点击「新建 Mod 条目」，输入名称后创建；新条目自动选中并出现在 ModItem 列表中。
5. 选中素材后点击「关联到选中条目」，素材从素材池消失，出现在右栏成员表格。
6. 在成员表格中通过角色下拉框为每个成员指定角色（本体/汉化/预览图/说明/可选文件/未知）；角色超限时展示错误。
7. 在右栏 ModItem 详情编辑表单中填写显示名称、说明、来源链接、标签（中文逗号分隔），点击「保存元数据」。
8. 关闭应用后重新运行，确认关联、角色、标签、描述仍存在。
9. 在成员表格中点击某成员的「移除」按钮，该素材回到素材池；真实文件未被移动或删除。
10. 中文文件名、中文显示名、中文标签全程正确显示。

### Not in Scope

未实现：封面设置 UI、缩略图生成与图片预览、搜索、AI JSON 导入导出、拖拽移动、真实文件移动、批量下载批次、ModItem.status、忽略/删除/移出素材池机制、压缩包内容解析、自动分组、AI 建议。
本任务不修改 `FileOperationService` 的行为；不修改 `FileScanner` 同步签名；不修改数据库 schema（沿用 v2）。

## [0.7.0] - 2026-07-09

对应 [docs/roadmap.md](docs/roadmap.md) 阶段 2 Task 2（只读目录树视图）完成。

### Added

- Repository 查询扩展 [src/infrastructure/repositories/folder_node.py](src/infrastructure/repositories/folder_node.py)：
  - `list_all()`：返回全部 FolderNode，按 `real_path` 排序。
  - `get_by_path_key(path_key)`：按 `path_key` 查询，用于 `ManagedRoot` 与 `FolderNode` 关联。
  - `count_children(parent_id)`：返回直接子目录数量（不含文件、不含孙节点）。
- Application 层只读目录树查询服务 [src/application/folder_tree_service.py](src/application/folder_tree_service.py)：
  - `TreeNode` dataclass：node_id / display_name / real_path / category（`managed_root` / `unscanned_root` / `folder`）/ is_managed_root / managed_root_id / folder_node_id / parent_id。
  - `FolderTreeService`：`list_root_nodes()` 合并 `ManagedRoot` 配置与 `FolderNode` 扫描根；`list_children(node_id)` 按 node_id 前缀（`mr:` / `fn:`）分发查询；`get_node(node_id)` / `count_children(node_id)` / `has_scan_data(managed_root_id)`。
  - `ManagedRoot` 与 `FolderNode` 通过 `path_key` 关联（`get_by_path_key`），不在 UI 层散落字符串匹配。
  - `display_name` 回退：`FolderNode.display_name` 为 None 时用 `PurePath(real_path).name`。
  - 不访问文件系统、不写数据库、不调用 `FileOperationService`。
- Qt 目录树 model [src/app/folder_tree_model.py](src/app/folder_tree_model.py)：
  - `FolderTreeModel(QAbstractItemModel)`：惰性加载（`canFetchMore` / `fetchMore`），`refresh()` 重置顶层。
  - 节点内部 ID：`"mr:<managed_root_id>"` / `"fn:<folder_node_id>"`，通过 `internalPointer` 往返。
  - 错误隔离：捕获查询异常，记录日志并降级为空子树，不让整个树崩溃。
  - 测试接口：`node_at(index)` / `node_id_at(index)` / `root_node_count()`。
- UI 文本常量 [src/app/ui_constants.py](src/app/ui_constants.py)：新增目录树与详情区常量（TREE_GROUP_TITLE / TREE_EMPTY_HINT / TREE_UNSCANNED_HINT / DETAIL_*）。
- 主窗口重写 [src/app/main_window.py](src/app/main_window.py)：
  - 构造签名新增 `folder_tree_service` 参数。
  - 三栏 QSplitter 布局：左栏根目录列表+按钮；中栏目录树（QTreeView，headerHidden / NoEditTriggers / NoDragDrop）+素材池占位；右栏扫描状态+选中目录详情。
  - `_refresh_tree()`：扫描完成/根目录变更后刷新 `FolderTreeModel`，更新空状态提示。
  - `_on_tree_selection_changed` → `_update_detail`：选中节点显示目录名称/完整真实路径/是否受管理根目录/类型/直接子目录数量；未扫描根目录追加"（未扫描）"提示。
  - 测试接口：`detail_text()` / `tree_root_count()`。
- 应用入口 [src/app/main.py](src/app/main.py)：构造 `FolderTreeService` 注入 `MainWindow`。
- 单元测试 34 项新增（总计 241 passed, 2 skipped），覆盖：
  - folder_node_repository（+4 项）：list_all 排序与空表、get_by_path_key 中文路径、count_children 直接子目录数与孙节点不计入。
  - folder_tree_service（16 项）：空数据、未扫描根显示为 unscanned_root、已扫描根显示为 managed_root、中文目录名、空目录、多层层级 parent_id 链、多根目录、重复扫描不重复、重叠根去重（子根显示为 unscanned_root）、get_node managed_root/folder/无效 ID、list_children 无效 ID、count_children 无效 ID、TreeNode category 校验、重新连接数据库后树可加载。
  - folder_tree_model（11 项）：空 model、顶层节点、惰性加载 fetchMore、父子关系 parent()、深层 index 链访问、node_at 返回 TreeNode、node_id_at、refresh 重置、无效 index 返回 None、中文显示名。
  - main_window（+4 项）：包含树视图、未扫描根目录显示提示、选中节点后详情区更新、扫描完成后树刷新。

### Fixed（阶段 2 Task 1 验收修复，自 v0.6.0 起）

- **根目录配置未持久化**：`ManagedRootRepository.create` 未调用 `conn.commit()`，应用关闭后数据丢失，重启后已添加的根目录不可见。修复：`create` 在 INSERT 成功后自提交事务（[src/infrastructure/repositories/managed_root.py](src/infrastructure/repositories/managed_root.py)）。
- **扫描完成进程 CTD**：`MainWindow._end_scanning` 在 `thread.quit()` 生效前清空 `self._thread` 引用，QThread 在 `Running` 状态被析构导致 `QThread: Destroyed while thread is still running`，扫描完成后约 3 秒内进程崩溃。修复（[src/app/main_window.py](src/app/main_window.py)）：
  - `_end_scanning` 不再清空 `_worker` / `_thread` 引用；新增 `_on_thread_finished`（由 `thread.finished` 信号触发）负责清空，确保 QThread 在 `Finished` 状态下被析构。
  - 调整信号连接顺序：先连 `thread.quit`，再连 UI 处理槽，确保 quit 先入队。
  - 新增 `MainWindow.closeEvent`：扫描中关窗时调用 `thread.quit()` + `wait(5000)` 等待线程退出，避免同类 CTD。
- `test_create_commits_transaction_without_explicit_commit`：验证 repo 自提交（[tests/test_managed_root_repository.py](tests/test_managed_root_repository.py)）。
- `test_add_root_persists_without_explicit_commit`：验证 service 自提交（[tests/test_managed_root_service.py](tests/test_managed_root_service.py)）。
- `test_main_window_scan_completes_without_crash`：扫描完成线程安全退出回归测试（[tests/test_main_window.py](tests/test_main_window.py)）。
- `test_main_window_close_event_safe_when_idle`：closeEvent 空闲路径测试（[tests/test_main_window.py](tests/test_main_window.py)）。

### Changed

- [src/app/main_window.py](src/app/main_window.py)：从单栏根目录/扫描区域重写为三栏布局（左栏根目录列表+按钮、中栏目录树+素材池占位、右栏扫描状态+详情区）；构造签名新增 `folder_tree_service`。
- [src/app/main.py](src/app/main.py)：构造 `FolderTreeService` 注入 `MainWindow`。
- [src/app/ui_constants.py](src/app/ui_constants.py)：新增目录树与详情区常量。
- [src/infrastructure/repositories/folder_node.py](src/infrastructure/repositories/folder_node.py)：新增 `list_all` / `get_by_path_key` / `count_children` 只读查询方法。
- [tests/test_folder_node_repository.py](tests/test_folder_node_repository.py)：扩展 4 项新查询方法测试。
- [tests/test_main_window.py](tests/test_main_window.py)：适配新构造签名，扩展 4 项目录树测试。

### 安全限制

- 本任务严格只读：不调用 `FileOperationService.execute_move` / `execute_undo` 或任何文件写 API。
- 目录树数据源严格为 SQLite `FolderNode`；不在 UI 线程临时递归真实文件系统。
- `FolderTreeService` / `FolderTreeModel` / Repository 查询均不调用 `Path.rename` / `unlink` / `shutil` / `FileOperationService.execute_*`。
- 不重新扫描真实目录来填充树；不修改用户文件或目录；不将目录树缓存写回用户目录。
- 路径、日志、数据库文本编码为 UTF-8。

### 待确认项

- 本任务未触及新的 open question；Q3（移动入口）保持未决（本任务不实现移动入口）。
- 重叠根目录展示策略已在本任务中确定为：子根因 `path_key` 已被父根扫描覆盖时显示为"未扫描"虚拟节点（spec §5.4 第 9 条、architecture §2.3）。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 52 files already formatted
- `python -m pytest` → 241 passed, 2 skipped in 7.28s
- `python -m app.main` → 主窗口正常启动，三栏布局，可添加目录、扫描、浏览目录树、选中节点查看详情（人工验证步骤见下方）

### 人工验证步骤

1. 运行 `python -m app.main`，主窗口显示三栏布局：左栏「受管理根目录」+ 按钮、中栏「目录树」+ 素材池占位、右栏「扫描状态」+ 详情区。
2. 点击「添加目录」，选择一个含中英文目录与空目录的测试根目录，目录应出现在左侧列表。
3. 选中根目录，点击「扫描选中目录」，扫描完成后中栏目录树应显示根目录及其子目录。
4. 展开树节点，确认空目录正常显示，中文目录名正确。
5. 选中深层目录，右栏详情区应显示目录名称、完整路径、是否为根、类型、子目录数量。
6. 关闭应用后重新运行，目录树应从已持久化的扫描数据加载，无需重新扫描。
7. 添加一个新根目录但不扫描，树中应显示该根目录为"未扫描"。

### Not in Scope

未实现：拖拽移动、右键文件操作、文件系统写入、文件监听、自动刷新、搜索、缩略图、ModItem 卡片、AI JSON、未关联素材池数据展示、ModItem 列表、移动预演/确认/撤销 UI、删除根目录配置、目录树缓存写回用户目录。
本任务不修改 `FileOperationService` 的行为；不修改 `FileScanner` 同步签名；不改变 `path_key` 语义。

## [0.6.0] - 2026-07-07

对应 [docs/roadmap.md](docs/roadmap.md) 阶段 2 Task 1（工作台骨架与根目录扫描）完成。schema_version 由 1 升至 2。

### Added

- Schema v2 迁移 [src/infrastructure/migrations.py](src/infrastructure/migrations.py)：
  - 新增 `migrate_v1_to_v2(conn)`：创建 `managed_root` 表（`id` / `real_path` / `path_key` UNIQUE / `display_name` / `created_at` / `updated_at`）+ 索引 `idx_managed_root_path_key`。
  - `MIGRATIONS` 注册表新增 `(2, migrate_v1_to_v2)`；迁移函数幂等（CREATE TABLE IF NOT EXISTS）。
  - `CURRENT_SCHEMA_VERSION` 升至 2（[src/infrastructure/db.py](src/infrastructure/db.py)）。
  - v1→v2 迁移不修改既有业务表，不丢失已有数据。
- 领域模型 [src/domain/models.py](src/domain/models.py)：新增 `ManagedRoot` dataclass（spec §6.5），`__post_init__` 校验必填字段。
- Repository [src/infrastructure/repositories/managed_root.py](src/infrastructure/repositories/managed_root.py)：
  `ManagedRootRepository`（create / get_by_id / get_by_path_key / list_all）。
  不访问文件系统；real_path 仅作为字符串存储；path_key 唯一约束冲突抛 `ConstraintViolationError`。
- Application 层错误 [src/application/errors.py](src/application/errors.py)：
  新增 `ManagedRootNotFoundError` / `DuplicateManagedRootError` / `InvalidRootPathError`。
- 受管理根目录服务 [src/application/managed_root_service.py](src/application/managed_root_service.py)：
  - `ManagedRootService.add_root(real_path)`：只读校验路径存在+是目录（`Path.exists` / `Path.is_dir`），path_key 去重，display_name=目录名。
  - `list_roots()` / `get_root(root_id)`。
  - 不扫描、不移动、不复制、不修改该目录或其中任何用户文件。
  - 可注入 `now_provider` / `uuid_provider`。
- 扫描工作流服务 [src/application/scan_workflow_service.py](src/application/scan_workflow_service.py)：
  - `ScanSummary` dataclass：root_id / root_path / scanned_folders / scanned_files / persisted_folders / persisted_files / skipped_folders / skipped_files / error_count / errors；`is_success` property。
  - `ScanWorkflowService.scan_root(root_id)` / `scan_root_by_path(real_path)`：读取 ManagedRoot，调用 `FileScanner.scan()` + `persist_scan_result()`，返回 `ScanSummary`。
  - 不修改 `FileScanner` 同步签名；不访问 UI；仅写应用数据库。
  - 根目录不存在/非目录时返回含错误的 `ScanSummary`（error_count > 0），不抛异常。
- Qt 后台扫描 worker [src/app/scan_worker.py](src/app/scan_worker.py)：
  - `ScanWorker(QObject)`：信号 `scan_started` / `scan_progress(str)` / `scan_finished(ScanSummary)` / `scan_failed(str)`。
  - `run()` 在 worker 所在线程内创建独立 SQLite 连接（`get_connection(db_path)`），不与主线程连接共享。
  - 捕获所有异常转为 `scan_failed` 信号，不向调用线程抛出。
  - 本任务不提供取消机制（Q18 未决部分）。
- UI 文本常量 [src/app/ui_constants.py](src/app/ui_constants.py)：
  集中定义窗口标题、按钮文本、状态文本、错误消息、占位区提示、`format_summary()` 函数。
- 主窗口重写 [src/app/main_window.py](src/app/main_window.py)：
  - `MainWindow(managed_root_service, db_path, parent=None)` 构造注入，便于测试。
  - 布局：QSplitter 水平分割——左侧「受管理根目录」区域（QListWidget + 添加目录按钮 + 扫描选中目录按钮），右侧扫描状态区域 + 三占位 GroupBox（目录树/素材池/详情，本任务不实现数据展示）。
  - 添加目录：`QFileDialog.getExistingDirectory` 选择目录，调用 `ManagedRootService.add_root()`；重复路径 / 路径不存在 / 路径非目录均展示用户可读错误。
  - 扫描：选中根目录后点击按钮，创建 `QThread` + `ScanWorker` 后台执行；扫描期间禁用「扫描选中目录」与「添加目录」按钮，显示「扫描中…」状态。
  - 扫描完成：展示摘要（扫描目录数/文件数/持久化目录数/文件数/错误数）；若有错误展示前 5 条错误摘要（路径与原因）。
  - 扫描失败：展示用户可读错误信息。
  - 测试接口：`status_text()` / `root_count()` / `is_scan_button_enabled()`。
- 应用入口 [src/app/main.py](src/app/main.py)：构造主线程 SQLite 连接，构造 `ManagedRootService` 注入 `MainWindow`；退出时关闭连接。
- 单元测试 38 项新增（总计 203 项），覆盖：
  - managed_root_repository（7 项）：创建与读取、中文路径、path_key 查询、path_key 唯一约束、list_all 排序、重启后读取、不存在 id 返回 None。
  - managed_root_service（10 项）：添加合法目录、中文路径、拒绝不存在路径、拒绝非目录路径、拒绝重复、不修改目标目录、list_roots 空/非空、get_root 存在/不存在。
  - scan_workflow_service（7 项）：成功结果回传、持久化验证、scan_root_by_path、缺失目录错误回传、未知 root_id 抛错、scan_root_by_path 未知路径抛错、ScanSummary.is_success 逻辑。
  - scan_worker（4 项）：成功 scan_finished 信号回传、缺失目录错误摘要回传、未知 root_id scan_failed 信号、worker 创建独立连接（主线程连接关闭后仍可扫描）。
  - migrations（10 项，原 3 项扩展）：CURRENT_SCHEMA_VERSION=2、v1→v2 创建 managed_root 表与索引、列结构、幂等、path_key 唯一约束、init_db 从 v0 迁移到 v2、init_db 在 v2 上幂等。
  - main_window（5 项，原 1 项重写）：构造与初始状态、已保存根目录显示、无选择时扫描按钮禁用、选中后启用、状态文本可读。

### Changed

- [src/infrastructure/db.py](src/infrastructure/db.py)：`CURRENT_SCHEMA_VERSION` 由 1 升至 2。
- [src/infrastructure/migrations.py](src/infrastructure/migrations.py)：`MIGRATIONS` 注册表新增 v1→v2 迁移。
- [src/domain/models.py](src/domain/models.py)：末尾新增 `ManagedRoot` dataclass。
- [src/app/main_window.py](src/app/main_window.py)：从空窗口重写为带根目录配置与扫描区域的工作台骨架；构造签名变更（需注入 `ManagedRootService` + `db_path`）。
- [src/app/main.py](src/app/main.py)：构造 `ManagedRootService` 并注入 `MainWindow`。
- [tests/test_main_window.py](tests/test_main_window.py)：适配新构造签名，扩展为 5 项测试。
- [tests/test_migrations.py](tests/test_migrations.py)：扩展为覆盖 v1→v2 迁移。

### 安全限制

- 本任务不调用 `FileOperationService.execute_move` / `execute_undo` 或任何文件写 API。
- 扫描仅使用只读文件系统 API（`Path.iterdir` / `is_dir(follow_symlinks=False)` / `stat(follow_symlinks=False)` / `suffix`）。
- 添加根目录配置仅写应用数据库 `managed_root` 表；不移动、不复制、不修改该目录。
- 不将用户 Mod 文件复制进应用数据目录。
- 日志写入 `%LOCALAPPDATA%\SkyrimModWorkbench\logs\app.log`，不写入用户目录。
- 路径、日志、数据库文本编码为 UTF-8。

### 待确认项

- 关闭 [open-questions.md Q18](docs/open-questions.md) 扫描并发与取消模型（阶段 2 部分决策：Qt 后台线程包裹同步扫描器，不提供取消；取消机制保留未决）。
- ManagedRoot 与 FolderNode.is_managed_root 的关系已在架构文档明确（D1 决策）：ManagedRoot 是用户配置，FolderNode.is_managed_root 是扫描结果标记；移除 ManagedRoot 不自动清理 FolderNode（清理策略待确认）。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 48 files already formatted
- `python -m pytest` → 203 passed, 2 skipped in 114.80s
- `python -m app.main` → 主窗口正常启动，可添加目录、扫描、查看结果（人工验证步骤见下方）

### 人工验证步骤

1. 运行 `python -m app.main`，主窗口应显示非空白布局：左侧「受管理根目录」区域，右侧「扫描状态」+ 三占位区。
2. 点击「添加目录」，选择一个本地目录，目录应出现在左侧列表。
3. 关闭应用后重新运行，已保存的根目录应仍在列表中。
4. 选中根目录，点击「扫描选中目录」，状态应显示「正在扫描…」，扫描期间按钮禁用。
5. 扫描完成后，状态区域应显示扫描目录数/文件数/持久化数/错误数。
6. 选择一个不存在的目录路径配置（需通过手动修改 DB 或先配置后删除目录），扫描应显示错误摘要。
7. 验证扫描前后用户文件未被修改（mtime/size 不变）。

### Not in Scope

未实现：删除根目录配置、目录树数据展示、素材池、ModItem 列表与详情、移动预演/确认/撤销 UI、搜索、AI JSON、缩略图、文件监听、增量扫描、取消扫描、压缩包内容解析。
本任务不修改 `FileScanner` 同步签名；不调用 `FileOperationService` 的任何方法。

## [0.5.0] - 2026-07-07

对应 [docs/roadmap.md](docs/roadmap.md) Task 5（安全移动预演与执行服务）完成。阶段 1（安全数据与文件操作基础）全部验收通过。

### Added

- 统一文件操作服务 [src/infrastructure/file_operation_service.py](src/infrastructure/file_operation_service.py)：
  唯一允许修改用户文件位置的模块（arch §6）。
  - `FileOperationService` 协调 ModItem / FileAsset / FolderNode / OperationLog 四个 Repository。
  - `plan_move(mod_item_id, target_folder_id) -> MovePlan`：生成移动预演并持久化
    `OperationLog(status=PLANNED)`。预演检查每个成员的源存在性、目标目录存在性、
    目标重名（B3：重名即阻止）、目标目录可写性、目标是否为源自身或子目录（spec §7.7）、
    是否跨盘。`can_execute` 仅在全部成员可执行时为 True。
  - `execute_move(plan_id) -> OperationResult`：校验 status=planned → 更新为 confirmed
    → 同盘 `Path.rename`（spec §7.8 原子）/ 跨盘 `shutil.copy2 + Path.unlink`
    （spec §7.9）→ 单成员失败不中断其他成员（spec §7.12）→ status=completed/failed
    + 写 undo_payload（Q14）。
  - `plan_undo(operation_id) -> UndoPlan`：B1 不安全即整体阻止；B2 跨盘撤销校验
    目标文件 size + mtime 与 undo_payload 记录一致。
  - `execute_undo(undo_plan_id) -> OperationResult`：先调用 plan_undo 重新验证
    （B1），不安全则直接返回失败；安全则反向移动 + status=undone。
  - 数据类：`MovePlan` / `MovePlanEntry` / `UndoPlan` / `UndoPlanEntry` / `OperationResult`。
  - `undo_payload` JSON 结构（Q14 由本任务定义）：
    `{version:1, members:[{asset_id, src_path, dst_path, size_bytes, mtime_iso}]}`。
  - 可注入 `now_provider` / `uuid_provider`，便于测试。
  - 执行后更新 FileAsset.real_path / path_key / modified_at 以反映新位置。
- 单元测试 23 项新增（总计 165 项），覆盖：
  - plan_move：正常、源缺失阻止、目标重名阻止、目标目录不存在阻止、
    子目录非法阻止、空 ModItem、ModItem 不存在、OperationLog 持久化为 planned。
  - execute_move：同盘单成员、同盘多成员、部分成员失败不中断、
    拒绝非 planned 状态、中文路径往返、undo_payload 记录 size+mtime、
    不删除用户文件（spec §7.13）。
  - plan_undo：正常、原目标文件缺失阻止、原源路径已占用阻止、
    size 不一致阻止（B2）、mtime 不一致阻止（B2）、非 completed/failed 拒绝。
  - execute_undo：正常往返、拒绝不安全撤销（B1）。
  - 完整场景：move + undo 往返验证文件回到原位。

### 安全限制

- UI 层不直接调用 shutil / Path.rename（AGENTS 规则 3）。
- 所有移动必须先 plan_move 生成预演并持久化为 planned（AGENTS 规则 4）。
- 所有移动支持撤销预演与安全撤销执行（AGENTS 规则 5）。
- 重名即阻止，不覆盖（B3）。
- 禁止移到源自身或子目录（spec §7.7）。
- 不删除用户文件（spec §7.13）；不修改文件内容（spec §7.14）。
- 撤销前强制重新验证文件状态（B1）；跨盘撤销校验 size+mtime（B2）。

### 无法原子回滚的情况

- 跨盘移动采用 copy2+unlink，原文件已删除；撤销为反向 copy2+unlink，
  依赖 undo_payload 中记录的 size+mtime 校验目标文件未被外部改动（B2）。
- 部分成员失败时已成功成员不自动回滚（Q20，决策里程碑=阶段 2）；
  OperationLog.status=failed，用户可手动执行 plan_undo + execute_undo。

### 待确认项

- 新增 [open-questions.md Q20](docs/open-questions.md#L171-L184)：部分失败时的回滚策略。
- 关闭 Q14（undo_payload 结构由本任务定义）。
- 关闭 Q16（OperationType 仅 {move, undo}，Task 5 未引入新值）。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 39 files already formatted
- `python -m pytest tests/test_file_operation_service.py -v` → 23 passed
- `python -m pytest` → 165 passed, 2 skipped

### Not in Scope

未实现：UI、application 层文件操作编排（Task 4 已实现的 ModAssemblyService
不含文件操作）、根目录配置持久化、缩略图、搜索索引、AI JSON、压缩包内容解析。
本服务不修改 OperationStatus 枚举（未引入 UNDO_BLOCKED/partial 等新值）；
不修改数据库 schema（沿用 Task 2 的 v1）。

## [0.4.0] - 2026-07-07

对应 [docs/roadmap.md](docs/roadmap.md) Task 4（Mod 条目组装服务）完成。

### Added

- Application 层错误 [src/application/errors.py](src/application/errors.py)：
  `ApplicationError`、`ModItemNotFoundError`、`FileAssetNotFoundError`、
  `MemberLimitError`、`DuplicateMemberError`。
- Mod 条目组装服务 [src/application/mod_assembly_service.py](src/application/mod_assembly_service.py)：
  - `ModAssemblyService` 协调 ModItemRepository 与 FileAssetRepository。
  - `create_mod_item`：创建空 ModItem（无成员）。
  - `add_member`：将 FileAsset 关联到 ModItem，设置角色；检查重复关联与角色数量限制。
  - `set_member_role`：更新已关联成员的角色。
  - `set_cover`：设置封面，要求成员为 PREVIEW 角色。
  - `get_mod_item` / `get_members` / `get_mod_item_with_members` / `list_mod_items`：查询接口。
  - `update_mod_item`：更新可编辑字段（display_name/description/source_url/category_folder_id/tags）。
  - `remove_member`：解除关联（mod_item_id=None, role=UNKNOWN）；若被移除的是 cover 同步清除。
  - `ROLE_LIMITS`：MAIN_MOD≤1、README≤1；其他角色不限制（Q19）。
  - 不自动推断成员关系（AGENTS 规则 7）；不访问文件系统；
    不实现 ModItem.status（Q1）、FileAsset.batch_id（Q2）、候选生成（Q10）。
- 单元测试 32 项新增（总计 144 项），覆盖：
  - 创建空 ModItem、带中文字段的 ModItem。
  - 关联单成员、多成员（本体+汉化+预览图，roadmap 验收场景）。
  - 重复关联 → DuplicateMemberError；MAIN_MOD/README 超限 → MemberLimitError；
    TRANSLATION/PREVIEW 不限制。
  - set_member_role：更新角色、改为 MAIN_MOD 时超限、同角色 noop。
  - set_cover：正常设置、非 PREVIEW 拒绝、未关联拒绝。
  - 查询：get_mod_item_not_found、get_members_not_found、
    get_mod_item_with_members、list_mod_items、空成员列表。
  - update_mod_item：全字段、部分字段、中文往返、not_found、tags 非 set 拒绝。
  - remove_member：解除关联、清除 cover、未关联拒绝、解除后重新关联。
  - 完整场景：本体+汉化+预览图+封面+中文显示名。

### 待确认项

- 新增 [open-questions.md Q19](docs/open-questions.md#L159-L169)：成员角色数量限制。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 37 files already formatted
- `python -m pytest` → 142 passed, 2 skipped in 2.80s

### Not in Scope

未实现：UI、文件移动、预演、撤销（Task 5）、OperationLog 写入（Task 5）、
搜索索引、缩略图、AI JSON、候选生成、删除 ModItem 或 FileAsset。
Service 不访问文件系统，仅通过 Repository 读写 SQLite。

## [0.3.0] - 2026-07-07

对应 [docs/roadmap.md](docs/roadmap.md) Task 3（只读扫描器）完成。

### Added

- 扩展名分类 [src/infrastructure/file_classify.py](src/infrastructure/file_classify.py)：
  `AssetHint` 枚举（IMAGE/ARCHIVE/OTHER）；`IMAGE_EXTENSIONS` 与 `ARCHIVE_EXTENSIONS` 集合；
  `get_extension(filename)` 与 `classify_by_extension(filename)`。
  分类结果仅扫描器内部使用，不持久化到 FileAsset 表。
- 只读扫描器 [src/infrastructure/file_scanner.py](src/infrastructure/file_scanner.py)：
  - `FileScanner.scan(root)` / `scan_many(roots)` 递归扫描，返回 `ScanResult`。
  - `ScanResult` 含 `folders`、`files`（`ScannedFileEntry` 列表）与 `errors`（`ScanError` 列表）。
  - `persist_scan_result(scan_result, folder_repo, file_repo)` 将扫描结果通过 Repository 写入 DB，
    处理 path_key 去重（A3 重叠根目录）、父子关系、is_managed_root 标记。
  - 仅使用只读文件系统 API（`Path.iterdir` / `is_dir(follow_symlinks=False)` / `stat(follow_symlinks=False)` / `suffix`），
    不移动、不重命名、不删除、不修改、不打开（读取内容）任何用户文件。
  - 符号链接与 junction 不跟随，按文件处理。
  - 异常（PermissionError / OSError / stat 失败）记入 `ScanError`，不中断整次扫描。
  - 支持中文路径；mtime 转 ISO 8601 UTC。
  - `now_provider` / `uuid_provider` 可注入，便于测试。
- 测试 fixture [tests/conftest.py](tests/conftest.py)：新增 `sample_mod_tree`（混合中英文目录与文件）。
- 单元测试 37 项新增（总计 112 项），覆盖：
  - file_classify：扩展名识别、大小写、多扩展名、中文文件名、点号边界。
  - file_scanner：空目录、样本树、中英文目录/文件名、图片/压缩包分类、文件大小、文件夹 size=0、
    modified_at ISO 格式、扩展名小写、根不存在、根为文件、权限不足（POSIX skip）、
    符号链接不跟随（Windows skip）、scan_many 独立根。
  - persist_scan_result：写入 FolderNode/FileAsset、根 is_managed_root、父子关系、
    字段完整、中文路径往返、重叠根去重、幂等、多受管理根。
  - 只读保证：扫描前后文件 mtime/size/内容一致；扫描不创建/删除文件。

### Skipped

- 2 项测试在 Windows 平台被 skip：`test_scan_permission_denied_directory`（chmod 000 在 Windows 不可靠）、
  `test_scan_symlink_not_followed`（创建符号链接需管理员权限或开发者模式）。
  逻辑已实现，可在 POSIX 平台或具备权限的 Windows 环境验证。

### 待确认项

- 新增 [open-questions.md Q17](docs/open-questions.md#L140-L148)：增量扫描与变更检测策略。
- 新增 [open-questions.md Q18](docs/open-questions.md#L150-L157)：扫描并发与取消模型。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 34 files already formatted
- `python -m pytest` → 110 passed, 2 skipped in 1.74s

### Not in Scope

未实现：UI、application 层编排（Task 4）、Mod 条目组装（Task 4）、文件移动（Task 5）、
搜索索引、缩略图、AI JSON、压缩包内容解析、文件哈希去重、文件监听、
根目录配置持久化、扫描进度回调与取消、增量扫描。
扫描器不读取文件内容，仅按扩展名识别图片/压缩包。

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
