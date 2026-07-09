# Changelog

本项目遵循 [SemVer 2.0.0](https://semver.org/lang/zh-CN/) 语义化版本控制。

在 1.0.0 之前，0.MINOR.PATCH 中的 MINOR 用于标记里程碑推进（roadmap 阶段/Task），PATCH 用于同里程碑内的修复与小幅调整。任何可能影响用户数据或破坏已有功能的变化都会使 MINOR 递增。

## [Unreleased]

尚未发布的改动。开发期间此节用于汇总已完成但未标注版本标签的提交。

### Fixed（阶段 2 Task 1 验收修复）

- **根目录配置未持久化**：`ManagedRootRepository.create` 未调用 `conn.commit()`，应用关闭后数据丢失，重启后已添加的根目录不可见。修复：`create` 在 INSERT 成功后自提交事务（[src/infrastructure/repositories/managed_root.py](src/infrastructure/repositories/managed_root.py)）。
- **扫描完成进程 CTD**：`MainWindow._end_scanning` 在 `thread.quit()` 生效前清空 `self._thread` 引用，QThread 在 `Running` 状态被析构导致 `QThread: Destroyed while thread is still running`，扫描完成后约 3 秒内进程崩溃。修复（[src/app/main_window.py](src/app/main_window.py)）：
  - `_end_scanning` 不再清空 `_worker` / `_thread` 引用；新增 `_on_thread_finished`（由 `thread.finished` 信号触发）负责清空，确保 QThread 在 `Finished` 状态下被析构。
  - 调整信号连接顺序：先连 `thread.quit`，再连 UI 处理槽，确保 quit 先入队。
  - 新增 `MainWindow.closeEvent`：扫描中关窗时调用 `thread.quit()` + `wait(5000)` 等待线程退出，避免同类 CTD。

### Added（测试）

- `test_create_commits_transaction_without_explicit_commit`：验证 repo 自提交，无需调用方显式 commit（[tests/test_managed_root_repository.py](tests/test_managed_root_repository.py)）。
- `test_add_root_persists_without_explicit_commit`：验证 service 自提交，模拟生产路径（[tests/test_managed_root_service.py](tests/test_managed_root_service.py)）。
- `test_main_window_scan_completes_without_crash`：扫描完成线程安全退出回归测试（[tests/test_main_window.py](tests/test_main_window.py)）。
- `test_main_window_close_event_safe_when_idle`：closeEvent 空闲路径测试（[tests/test_main_window.py](tests/test_main_window.py)）。

### Known Issues（未修复，超出本次范围）

- `persist_scan_result`（扫描结果持久化）同样未自提交事务，重启后扫描结果丢失。本任务范围内未修复，待后续任务统一处理 Repository 写操作提交策略。

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
