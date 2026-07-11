# 项目进度

本文件追踪 roadmap 各阶段与原子任务的执行进度。每完成一项即更新此处，并在 [CHANGELOG.md](../CHANGELOG.md) 中记录。

图例：

- ✅ 已完成
- ⏳ 进行中
- ⬜ 未开始
- ⛔ 已决定不做（标注原因与决策来源）

---

## 阶段 0：项目初始化  ✅

| 任务 | 状态 | 备注 |
|---|---|---|
| Python 项目初始化 | ✅ | pyproject.toml，requires-python>=3.12 |
| PySide6 空窗口 | ✅ | [src/app/main_window.py](../src/app/main_window.py) |
| SQLite 初始化 | ✅ | [src/infrastructure/db.py](../src/infrastructure/db.py)，schema_version=0 |
| 基础目录结构 | ✅ | src/{app,domain,infrastructure,application}、tests、docs |
| ruff 和 pytest | ✅ | ruff check / format / pytest 全通过 |
| 基础日志 | ✅ | [src/app/logging_setup.py](../src/app/logging_setup.py) |
| 应用数据目录创建 | ✅ | [src/app/app_paths.py](../src/app/app_paths.py) |

**验收**：

- [x] Windows 上可启动空窗口
- [x] 自动创建本地数据库
- [x] 可运行测试和静态检查

**版本标签**：[0.1.0]

---

## 阶段 1：安全数据与文件操作基础  ✅

| 任务 | 状态 | 备注 |
|---|---|---|
| 受管理根目录配置 | ⬜ | 阶段 1 仅完成 scanner 接口（接受调用方传入根目录）；配置持久化迁移至阶段 2 任务 1 |
| 文件和目录扫描 | ✅ | Task 3 完成；只读扫描器 + persist_scan_result |
| FolderNode、FileAsset、ModItem、OperationLog 数据模型 | ✅ | Task 2 完成；schema v1，4 表 + Repository CRUD |
| 手动创建 Mod 条目 | ✅ | Task 4 完成；ModAssemblyService.create_mod_item |
| 手动关联多个 FileAsset | ✅ | Task 4 完成；add_member / set_member_role / set_cover / remove_member |
| 移动预演 | ✅ | Task 5 完成；FileOperationService.plan_move + MovePlan/MovePlanEntry |
| 确认后移动 | ✅ | Task 5 完成；execute_move 同盘 rename / 跨盘 copy2+unlink |
| 操作日志 | ✅ | Task 5 完成；plan_move 写 planned、execute_move 写 completed/failed + undo_payload |
| 撤销预演与撤销执行 | ✅ | Task 5 完成；plan_undo（B1/B2 校验）+ execute_undo |
| 中文路径测试 | ✅ | Task 2/3/5 全覆盖；Task 5 新增 execute_move 中文路径往返测试 |

**验收（来自 roadmap）**：

- [x] 能在测试目录中创建一个包含本体、汉化和预览图的 Mod 条目
- [x] 能预演并执行整体移动
- [x] 能在安全条件下撤销
- [x] 能阻止重名、缺失、目标为子目录等危险操作

---

## 阶段 2：基础桌面工作台  ⏳

进行中。详见 [roadmap.md](roadmap.md) 阶段 2 与 [phase-2-plan.md](phase-2-plan.md)。

| 任务 | 状态 | 备注 |
|---|---|---|
| 受管理根目录持久化与 schema v2 | ✅ | Task 1 完成；ManagedRoot + ManagedRootRepository + ManagedRootService + v1→v2 迁移 |
| 扫描工作流应用层与后台任务适配 | ✅ | Task 1 完成；ScanWorkflowService + ScanWorker（Qt 后台线程） |
| 只读目录树视图 | ✅ | Task 2 完成；FolderTreeService + FolderTreeModel + 三栏布局 + 详情区 |
| 未关联素材池与 ModItem 列表 | ✅ | Task 3 完成；UnassociatedPoolModel + ModItemListModel + 素材池多选 + ModItem 列表 |
| ModItem 手动组装与编辑 UI | ✅ | Task 3 完成；成员关联/移除、角色编辑、元数据编辑；封面设置待后续 |
| 安全移动与撤销确认工作流 UI | ⬜ | 阶段 2 任务 5；预演→确认→执行→撤销 |

**Task 1 完成内容（v0.6.0）**：

- Schema v2 迁移：新增 `managed_root` 表（`id` / `real_path` / `path_key` UNIQUE / `display_name` / `created_at` / `updated_at`）+ 索引；`CURRENT_SCHEMA_VERSION` 升至 2；v1→v2 迁移幂等。
- 领域模型：`ManagedRoot` dataclass（[src/domain/models.py](../src/domain/models.py) §6.5）。
- Repository：`ManagedRootRepository`（create / get_by_id / get_by_path_key / list_all）。
- Application 层：
  - `ManagedRootService.add_root()`：只读校验路径存在+是目录，path_key 去重，display_name=目录名；不扫描、不移动、不复制、不修改。
  - `ScanWorkflowService.scan_root()` / `scan_root_by_path()`：调用 `FileScanner.scan()` + `persist_scan_result()`，返回 `ScanSummary`（含目录/文件/持久化/错误统计）。
  - 错误类型：`ManagedRootNotFoundError` / `DuplicateManagedRootError` / `InvalidRootPathError`。
- UI 层：
  - `ScanWorker`（QObject + QThread）：后台线程执行扫描，独立 SQLite 连接，信号回传 `scan_finished(ScanSummary)` / `scan_failed(str)`。
  - `MainWindow` 重写：左侧根目录列表 + 添加目录 + 扫描选中目录；右侧扫描状态 + 三占位区（目录树/素材池/详情）。
  - `ui_constants.py`：UI 文本集中定义。
  - `main.py`：构造 `ManagedRootService` 注入 `MainWindow`。
- 测试新增 38 项（总计 203 项）：
  - `test_managed_root_repository.py`（7 项）：CRUD、中文路径、path_key 唯一约束、重启后读取。
  - `test_managed_root_service.py`（10 项）：添加合法目录、拒绝不存在/非目录路径、重复根目录、不修改目标目录、list/get。
  - `test_scan_workflow_service.py`（7 项）：scan_root 成功结果回传、持久化、scan_root_by_path、缺失目录错误回传、未知 root_id、ScanSummary.is_success 逻辑。
  - `test_scan_worker.py`（4 项）：成功 scan_finished 信号回传、缺失目录错误摘要回传、未知 root_id scan_failed 信号、独立连接。
  - `test_migrations.py`（10 项）：v1→v2 创建 managed_root 表、幂等、path_key 唯一约束、init_db 从 v0 迁移到 v2、幂等。
  - `test_main_window.py`（5 项，原 1 项重写）：构造、已保存根目录显示、扫描按钮无选择禁用、选中启用、状态文本。

**Task 1 验收修复（v0.6.1，未提交）**：

用户复测发现两处与预期不符的问题，已按最小修复方案处理：

1. **根目录配置未持久化**：`ManagedRootRepository.create` 未调用 `conn.commit()`，连接关闭后数据丢失。修复：`create` 在 INSERT 成功后自提交。
2. **扫描完成进程 CTD**：`MainWindow._end_scanning` 在 `thread.quit()` 生效前清空 `_thread` 引用，QThread 在 `Running` 状态被析构导致 `QThread: Destroyed while thread is still running`。修复：
   - `_end_scanning` 不再清空引用；新增 `_on_thread_finished`（`thread.finished` 信号触发）负责清空。
   - 调整信号连接顺序：先连 `thread.quit`，再连 UI 处理槽。
   - 新增 `MainWindow.closeEvent`：扫描中关窗时 `thread.quit()` + `wait(5000)` 等待线程退出。

测试新增 4 项（总计 207 passed, 2 skipped）：
- `test_create_commits_transaction_without_explicit_commit`：repo 自提交回归。
- `test_add_root_persists_without_explicit_commit`：service 自提交回归。
- `test_main_window_scan_completes_without_crash`：扫描完成线程安全退出回归。
- `test_main_window_close_event_safe_when_idle`：closeEvent 空闲路径。

**Task 1 遗漏补完：移除受管理根目录配置（v0.6.2）**：

阶段 2 Task 1 验收标准要求"可移除根目录配置；移除配置不删除、不移动、不修改该目录及其中任何用户文件"，但原实现主动跳过了该项。本次作为 Task 1 遗漏补完实现：

- Repository 层 [src/infrastructure/repositories/managed_root.py](../src/infrastructure/repositories/managed_root.py)：新增 `delete(root_id)`，DELETE FROM managed_root WHERE id=?；实体不存在抛 `NotFoundError`；写操作自提交（与 `create` 一致）。
- Service 层 [src/application/managed_root_service.py](../src/application/managed_root_service.py)：新增 `remove_root(root_id)`；先校验存在性（抛 `ManagedRootNotFoundError`），再调用 `repo.delete`。移除模块注释中"本任务不实现删除根目录配置"说明。
- UI 层 [src/app/main_window.py](../src/app/main_window.py)：
  - 左栏新增「移除选中目录」按钮（`_remove_button`）。
  - `_on_remove_root`：弹出确认对话框（QMessageBox.question），用户确认后调用 `service.remove_root` 并刷新列表。
  - 按钮状态联动：`_on_selection_changed` / `_begin_scanning` / `_end_scanning` 同步禁用/恢复移除按钮；扫描期间禁用。
  - 新增 `is_remove_button_enabled()` 测试接口。
- UI 文案 [src/app/ui_constants.py](../src/app/ui_constants.py)：新增 `REMOVE_ROOT_BUTTON` / `REMOVE_ROOT_CONFIRM_TITLE` / `REMOVE_ROOT_CONFIRM_TEXT` / `ERR_REMOVE_ROOT_FAILED`。
- 边界：仅删除 `managed_root` 记录，不删除、不移动、不修改任何用户文件；不清理 `folder_node` / `file_asset` 扫描记录（清理策略待确认）。
- 测试新增 11 项（总计 291 passed, 2 skipped）：
  - `test_managed_root_repository.py`（+5 项）：delete 删除记录、delete 自提交、delete 不存在抛 NotFoundError、delete 不影响其他根目录、delete 保留 folder_node/file_asset。
  - `test_managed_root_service.py`（+5 项）：remove_root 删除配置、remove_root 不存在抛错、remove_root 保留真实目录与文件（mtime/size 不变）、remove_root 不清理扫描记录、remove_root 自提交。
  - `test_main_window.py`（+6 项）：移除按钮无选择禁用、选中启用、初始禁用、确认后从列表消失且真实目录保留、取消确认保留列表、移除后真实目录文件不变、扫描期间禁用。

**Task 2 完成内容（v0.7.0）**：

- Repository 扩展 [src/infrastructure/repositories/folder_node.py](../src/infrastructure/repositories/folder_node.py)：
  - `list_all()`：返回全部 FolderNode，按 `real_path` 排序。
  - `get_by_path_key(path_key)`：按 `path_key` 查询，用于 `ManagedRoot` 与 `FolderNode` 关联。
  - `count_children(parent_id)`：返回直接子目录数量（不含文件、不含孙节点）。
- Application 层只读查询服务 [src/application/folder_tree_service.py](../src/application/folder_tree_service.py)：
  - `TreeNode` dataclass：node_id / display_name / real_path / category（`managed_root` / `unscanned_root` / `folder`）/ is_managed_root / managed_root_id / folder_node_id / parent_id。
  - `FolderTreeService`：`list_root_nodes()` 合并 `ManagedRoot` 配置与 `FolderNode` 扫描根；`list_children(node_id)` 按 node_id 前缀（`mr:` / `fn:`）分发查询；`get_node(node_id)` / `count_children(node_id)` / `has_scan_data(managed_root_id)`。
  - `ManagedRoot` 与 `FolderNode` 通过 `path_key` 关联（`get_by_path_key`），不散落 UI 字符串匹配。
  - `display_name` 回退：`FolderNode.display_name` 为 None 时用 `PurePath(real_path).name`。
- Qt model [src/app/folder_tree_model.py](../src/app/folder_tree_model.py)：
  - `FolderTreeModel(QAbstractItemModel)`：惰性加载（`canFetchMore` / `fetchMore`）；`refresh()` 重置顶层；`node_at` / `node_id_at` / `root_node_count` 测试接口。
  - 节点内部 ID：`"mr:<managed_root_id>"` / `"fn:<folder_node_id>"`，通过 `internalPointer` 往返。
  - 错误隔离：捕获查询异常，记录日志并降级为空子树。
- UI 文本常量 [src/app/ui_constants.py](../src/app/ui_constants.py)：新增目录树与详情区常量。
- 主窗口重写 [src/app/main_window.py](../src/app/main_window.py)：
  - 构造签名新增 `folder_tree_service` 参数。
  - 三栏 QSplitter 布局：左栏根目录列表+按钮；中栏目录树+素材池占位；右栏扫描状态+选中目录详情。
  - `_refresh_tree()`：扫描完成/根目录变更后刷新 `FolderTreeModel`。
  - `_on_tree_selection_changed` → `_update_detail`：选中节点显示名称/路径/是否根/类型/子目录数；未扫描根目录追加提示。
  - 测试接口：`detail_text()` / `tree_root_count()`。
- 应用入口 [src/app/main.py](../src/app/main.py)：构造 `FolderTreeService` 注入 `MainWindow`。
- 测试新增 34 项（总计 241 passed, 2 skipped）：
  - `test_folder_node_repository.py`（+4 项）：list_all 排序与空表、get_by_path_key 中文、count_children 直接子目录数。
  - `test_folder_tree_service.py`（16 项）：空、未扫描根、已扫描根、中文目录、空目录、多层层级、多根目录、重复扫描不重复、重叠根去重、get_node、list_children 无效 ID、count_children 无效 ID、TreeNode category 校验、重新连接后树可加载。
  - `test_folder_tree_model.py`（11 项）：空 model、顶层节点、惰性加载、父子关系、深层访问、node_at、node_id_at、refresh 重置、无效 index、中文显示名。
  - `test_main_window.py`（+4 项）：包含树视图、未扫描根目录提示、选中后详情更新、扫描后树刷新。

**Task 2 验收修复（Unreleased）**：

- **根因**：`FolderTreeModel._fetch` 在 `beginInsertRows` 之后才设置 `_loaded` 与
  `_children_cache`。`beginInsertRows` 同步触发 view 查询 `rowCount`，`rowCount`
  检查 `_loaded` 未设置又调用 `_fetch`，形成无限递归直至 `RecursionError`。
  当 `%LOCALAPPDATA%\SkyrimModWorkbench\app.db` 中已有 Task 1 验收时残留的
  扫描数据时，启动即崩溃（窗口出现但控制台刷屏 `Error calling Python override
  of QAbstractItemModel::rowCount()`）。
- **修复**（[src/app/folder_tree_model.py](../src/app/folder_tree_model.py) `_fetch` 方法）：
  - 开头加 `if parent_node_id in self._loaded: return` 重入保护；
  - `_children_cache` 与 `_loaded` 赋值移到 `beginInsertRows` 之前；
  - 空子节点跳过 `beginInsertRows`/`endInsertRows`。
- **测试新增 3 项**（总计 244 passed, 2 skipped）：
  - `test_fetch_does_not_recurse_when_connected_to_view`：model 连接真实 `QTreeView`
    后 `fetchMore` 不触发 `RecursionError`。
  - `test_fetch_empty_children_does_not_emit_rows_inserted`：空子节点不发
    `rowsInserted` 信号。
  - `test_fetch_sets_loaded_before_begin_insert_rows`：通过 `rowsAboutToBeInserted`
    信号中查询 `rowCount` 验证 `_loaded` 顺序，确保重入不递归。
- **技术债**：`rowCount` 中的副作用（未加载时调用 `_fetch`）记录为
  open question Q21，本次不调整加载策略。

**Task 2 验收修复第二轮（Unreleased）**：

- **根因**：`ScanWorker.run` 在 `service.scan_root` 返回后直接 `conn.close()`，
  未调用 `conn.commit()`。`persist_scan_result` 与 `FolderNodeRepository.create` /
  `FileAssetRepository.create` 均不自提交事务（与 `ManagedRootRepository.create`
  不同），导致扫描结果在连接关闭时被 SQLite 回滚。数据库中无 `folder_node` 记录，
  `FolderTreeService` 无法关联 `ManagedRoot` 与 `FolderNode`，根目录始终显示为
  "未扫描"，无法展开子目录。此问题自 v0.6.0 起即记录为已知遗留问题。
- **修复**（[src/app/scan_worker.py](../src/app/scan_worker.py) `run` 方法）：
  在 `scan_root` 返回后、`scan_finished.emit` 前调用 `conn.commit()`。
  不修改 `ScanWorkflowService`、Repository 接口或事务策略。
- **测试新增 1 项 + 调整 1 项**（总计 245 passed, 2 skipped）：
  - `test_scan_worker_persists_results_to_db`：扫描完成后用独立连接验证
    `folder_node` 与 `file_asset` 表非空，确保事务已提交。
  - `test_main_window_tree_refresh_after_scan`（调整）：扫描完成后新增验证
    根节点不再显示"未扫描"且可展开有子节点。修复前该测试仅验证
    `tree_root_count() == 1`，漏掉了数据未持久化的场景。
- **遗留技术债**：`persist_scan_result` 不自提交仍为已知遗留问题，
  本次仅在 `ScanWorker` 层补提交，不统一 Repository 写操作提交策略。

**Task 3 完成内容（v0.8.0）**：

- Application 层 [src/application/mod_assembly_service.py](../src/application/mod_assembly_service.py)：
  - 新增 `list_unassociated_assets()`：委托 `FileAssetRepository.list_unassociated()`，返回 `mod_item_id` 为 `NULL` 的 `FileAsset` 列表，供 UI 素材池展示。
  - 复用阶段 1 既有 `create_mod_item` / `add_member` / `set_member_role` / `remove_member` / `update_mod_item` / `get_members` / `list_mod_items`，不复制关联规则到 UI。
- UI model [src/app/pool_model.py](../src/app/pool_model.py)：
  - `UnassociatedPoolModel(QAbstractListModel)`：包装未关联 `FileAsset` 列表，显示 `📁 filename` / `📄 filename`，tooltip 显示完整路径；`refresh()` 重置；`asset_at` / `asset_id_at` / `asset_count` 测试接口。
  - `ModItemListModel(QAbstractListModel)`：包装 `ModItem` 列表，显示 `display_name` 或"(未命名)"；`refresh()` 重置；`mod_item_at` / `mod_item_id_at` / `item_count` 测试接口。
  - `ROLE_DISPLAY_NAMES` / `ROLE_ORDER`：角色中文显示名与下拉顺序，集中定义；角色数量限制仍由 `ModAssemblyService.ROLE_LIMITS` 强制。
  - 错误隔离：捕获查询异常，记录日志并降级为空列表。
- UI 文本常量 [src/app/ui_constants.py](../src/app/ui_constants.py)：新增素材池、ModItem 列表、详情编辑、成员表格、角色中文名、操作按钮与错误提示常量。
- 主窗口重写 [src/app/main_window.py](../src/app/main_window.py)：
  - 构造签名新增 `mod_assembly_service` 参数。
  - 中栏：素材池 `QListView`（ExtendedSelection）+ ModItem 列表 `QListView`（SingleSelection）+ 新建 Mod 条目按钮 + 关联到选中条目按钮。
  - 右栏：ModItem 详情编辑表单（显示名称/说明/来源链接/标签 + 保存元数据按钮）+ 成员表格 `QTableWidget`（文件名/类型/角色下拉/路径/移除按钮）。
  - `_on_new_mod()`：QInputDialog 输入名称创建 ModItem，刷新列表并选中新条目。
  - `_on_associate()`：多选素材以 `UNKNOWN` 角色关联到当前 ModItem，展示错误。
  - `_on_role_changed(asset_id)`：通过 `self.sender()` 获取 QComboBox，调用 `set_member_role`。
  - `_on_remove_member(asset_id)`：调用 `remove_member`，刷新成员表和素材池。
  - `_on_save_metadata()`：保存名称/说明/URL/标签（中文逗号分隔标签）。
  - 扫描完成/失败后调用 `_refresh_pool()`。
  - 测试接口：`pool_count()` / `mod_list_count()` / `mod_detail_name()` / `members_table_row_count()`。
- 应用入口 [src/app/main.py](../src/app/main.py)：构造 `ModAssemblyService` 注入 `MainWindow`。
- 测试新增 22 项（总计 266 passed, 2 skipped）：
  - `test_mod_assembly_service.py`（+3 项）：`list_unassociated_assets` 基础、中文名素材、文件夹型素材。
  - `test_pool_model.py`（13 项）：素材池空/显示未关联/关联后消失/解除后重现/中文文件名/文件夹类型/文件 tooltip；ModItem 列表空/显示条目/未命名显示/创建后刷新/中文标签 tooltip。
  - `test_main_window.py`（+6 项）：素材池初始空、扫描后显示未关联素材、创建 ModItem 并关联、移除成员回到素材池、元数据保存持久化、无选择时关联保护。

**Task 3 缺口修复内容（v0.8.1）**：

- 布局调整 [src/app/main_window.py](../src/app/main_window.py)：
  - 目录树从中栏移至左栏（与受管理根目录列表、扫描状态、目录详情同栏）。
  - 中栏改为：素材池（上）+ ModItem 列表 + 新建/关联按钮（下）。
  - 右栏改为：ModItem 详情编辑（元数据）+ 成员表格。
- 素材池显示字段补全 [src/app/pool_model.py](../src/app/pool_model.py)：
  - `_format_display` 从仅显示 `📁 filename` 改为 `📁 filename  (类型)  完整路径`，满足"文件名、类型、完整路径"三项可见字段要求。
- 新建 Mod 条目自动关联 [src/app/main_window.py](../src/app/main_window.py)：
  - `_on_new_mod()` 创建 ModItem 后自动将素材池中选中的素材以 `UNKNOWN` 角色关联到新条目。
  - 关联失败时收集错误并通过 `QMessageBox` 展示。
  - 成功后刷新素材池、ModItem 列表，选中新条目并加载成员。
- 按钮状态联动 [src/app/main_window.py](../src/app/main_window.py)：
  - 新增 `_update_new_mod_button()`：素材池无选择时「新建 Mod 条目」禁用。
  - 新增 `_on_pool_selection_changed()`：素材池选择变化时同步更新「新建」和「关联」按钮状态。
  - `_new_mod_button` 初始 `setEnabled(False)`。
- 测试新增 5 项（总计 271 passed, 2 skipped）：
  - `test_pool_model.py`（+2 项）：素材池显示包含类型和完整路径（文件型 + 文件夹型）。
  - `test_main_window.py`（+3 项）：新建按钮无选择时禁用、新建自动关联选中素材、素材池显示完整路径。
- 文档更新：spec.md §8 UI 结构、architecture.md §2.4 写入链路与边界约定。

**验收（来自 roadmap）**：

- [ ] 用户可添加、查看、移除受管理根目录配置（添加/查看已实现；移除未在 Task 1 范围）
- [x] 用户可手动触发扫描，看到扫描结果与错误摘要（未关联素材池已实现）
- [x] 用户可在目录树中浏览已扫描目录并选中目标分类目录（Task 2 只读浏览；移动入口待 Task 5）
- [x] 用户可在素材池选择文件创建 ModItem，设置成员角色与元数据（封面设置待后续）
- [ ] 用户可在目录树选择目标分类，发起移动预演并明确确认执行
- [ ] 用户可看到执行结果，对安全操作发起撤销预演并确认撤销
- [x] 中文路径、中文显示名和 UTF-8 数据在扫描、目录树浏览与 Mod 组装流程中保持可用
- [x] 所有用户文件位置变化仍只由 `FileOperationService` 执行（本任务不调用任何文件写 API）

## 阶段 3：搜索与 AI JSON 交换  ⬜

未开始。

## 阶段 4：交互优化  ⬜

未开始。

## 阶段 5：预览增强  ⬜

未开始。

## 阶段 6：开源发布准备  ⬜

未开始。

---

## 已确认的关键决策（来自 A/B 类待确认项）

| 编号 | 决策 | 决策内容 | 影响阶段 |
|---|---|---|---|
| A1 | 第一阶段范围 | 仅做 roadmap 阶段 0+1 | 全局 |
| A2 | 路径比较键策略 | 原样存储 real_path，另存 path_key（normcase+normpath）用于比较与唯一约束 | Task 2/3/5 |
| A3 | 受管理根目录与扫描深度 | Mod 根目录与待整理目录均标记 is_managed_root=true；递归扫描；所有子目录生成 FolderNode；重叠目录去重 | Task 3 |
| B1 | 撤销不安全时的行为 | 完全阻止，留下当前文件状态，写日志+用户提示；不做部分回滚 | Task 5 |
| B2 | 跨盘移动的撤销路径 | 校验目标文件 size+mtime 与 OperationLog 记录一致才反向移动，否则拒绝 | Task 5 |
| B3 | conflict_policy 取值集合 | 阶段 1 仅 {ask}，任何重名即阻止 | Task 5 |
| B4 | 外部关联图存储策略 | 仅存原路径，不复制到应用缓存 | 阶段 2+ |

阶段 2 决策（来自 [docs/phase-2-plan.md](phase-2-plan.md) §3）：

| 编号 | 决策 | 决策内容 | 影响阶段 |
|---|---|---|---|
| D1 | 受管理根目录数据模型 | 新增独立 `managed_root` 表，不依赖 `folder_node.is_managed_root` | 阶段 2 任务 1 |
| D2 | 阶段 2 移动入口 | 仅按钮式「移动到选中目录」，不实现拖拽 | 阶段 2 任务 5 |
| D3 | 未关联素材处置 | 阶段 2 仅展示，不提供忽略/移出/删除 | 阶段 2 任务 3 |
| D4 | 扫描执行模型 | Qt 后台线程包裹同步扫描器，不承诺取消 | 阶段 2 任务 2 |
| D5 | ModItem.status | 阶段 2 不引入 status 字段 | 阶段 2 |
| D6 | 成员角色限制 | 保持 MAIN_MOD≤1、README≤1，其余不限 | 阶段 2 |
| D7 | 部分失败 UI 处理 | 不自动回滚，UI 展示成功/失败成员，允许安全撤销 | 阶段 2 任务 5 |

C 类待确认项见 [docs/open-questions.md](open-questions.md)。
