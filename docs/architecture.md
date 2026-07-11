# 架构设计

## 1. 技术选型

第一版采用：

* Python 3.12+
* PySide6
* SQLite + FTS5
* Pillow（阶段 2 不引入；缩略图服务实现前添加）
* pytest
* ruff
* PyInstaller 或 Nuitka，用于后续 Windows 打包

选择理由：

* PySide6 适合 Windows 桌面文件管理交互，包括目录树、卡片视图、右键菜单、多选和拖放。
* SQLite 是本地单文件数据库，无需服务端。
* Python 对 UTF-8、中文路径和快速迭代友好。
* 第一版不需要前后端分离、Web 服务、云端 API 或桌面 WebView。

## 2. 分层原则

UI 层不得包含业务规则或文件系统写操作。

```text
PySide6 UI
    ↓ 调用
Application Services
    ↓ 调用
Domain Logic
    ↓ 调用
Infrastructure
    ├─ SQLite Repository
    ├─ File Scanner
    ├─ File Operation Service
    ├─ Thumbnail Service
    └─ JSON Import/Export Service
```

UI 分层规则（阶段 2 起）：

* widget / view 不直接访问 Repository 或文件系统；通过 controller、view model 或 application service 调用。
* Qt worker 仅包裹同步扫描器（`FileScanner.scan()`），不得包含文件系统写入逻辑；扫描结果仅写应用数据库。
* 目录树的数据源是 SQLite `FolderNode`，不是可写的即时文件系统树。

### 2.1 Qt 后台扫描线程边界（阶段 2 Task 1 实现）

扫描使用 `QObject + QThread` 模式，严格划分线程边界：

* `ScanWorker`（[src/app/scan_worker.py](../src/app/scan_worker.py)）继承 `QObject`，通过 `moveToThread` 在独立 `QThread` 中执行 `run()`。
* 主线程持有 SQLite 连接用于 UI 查询（`ManagedRootService` 列出根目录等）；`ScanWorker` 在 `run()` 内调用 `get_connection(db_path)` 创建独立连接，**不与主线程连接共享**，避免 SQLite 跨线程问题。
* `ScanWorker` 仅调用 `ScanWorkflowService.scan_root()`（同步），不访问 UI、不直接调用 `FileScanner`。
* 结果回传通过 Qt 信号跨线程投递：
  * `scan_started()`：扫描开始。
  * `scan_progress(str)`：进度文本（当前任务仅发送"正在扫描…"）。
  * `scan_finished(ScanSummary)`：扫描完成（含错误摘要时也触发，错误计入 `ScanSummary.errors`）。
  * `scan_failed(str)`：扫描过程抛出未预期异常（如 `root_id` 不存在、DB 异常）。
* `scan_finished` 与 `scan_failed` 均连接至 `thread.quit`，扫描完成后线程自动退出；`thread.finished` 连接至 `worker.deleteLater` / `thread.deleteLater` 与 `_on_thread_finished` 清理资源。
* **线程生命周期约定**（Task 1 修复）：`MainWindow._end_scanning` 恢复按钮状态，但**不得清空 `_worker` / `_thread` Python 引用**；引用清空只能由 `_on_thread_finished`（`thread.finished` 信号触发）执行，确保 QThread 在 `Finished` 状态下被析构。否则 QThread 在 `Running` 状态析构会导致进程 CTD（`QThread: Destroyed while thread is still running`）。
* **窗口关闭约定**（Task 1 修复）：`MainWindow.closeEvent` 在关闭前检查 `thread.isRunning()`，若为真则调用 `thread.quit()` + `thread.wait(5000)` 等待线程退出，避免扫描中关窗触发同类 CTD。
* 扫描期间 `MainWindow` 禁用「扫描选中目录」与「添加目录」按钮，避免重复扫描与并发写库；扫描结束后恢复。
* 本任务不提供取消机制（Q18 未决部分）。`FileScanner.scan()` 同步执行至完成后通过信号回传，无法中断。

### 2.2 事务管理约定（Task 1 修复）

* `ManagedRootRepository.create` 为写操作自提交：INSERT 成功后调用 `conn.commit()`，确保调用方无需显式 commit 即可跨连接/重启可见。
* 其他 Repository（FolderNode / FileAsset / OperationLog）的写操作提交策略暂未统一，`persist_scan_result` 仍依赖调用方或上下文提交；此为已知遗留问题，待后续任务处理。

### 2.3 目录树 model/view 边界（阶段 2 Task 2 实现）

目录树使用 Qt model/view 架构，严格分层：

```text
QTreeView (view)
    ↓ 读取
FolderTreeModel (QAbstractItemModel)
    ↓ 读取
FolderTreeService (application)
    ↓ 读取
FolderNodeRepository / ManagedRootRepository (infrastructure)
    ↓ 读取
SQLite FolderNode / ManagedRoot 表
```

边界约定：

* `FolderTreeModel`（[src/app/folder_tree_model.py](../src/app/folder_tree_model.py)）继承 `QAbstractItemModel`，仅包装 `FolderTreeService` 返回的 `TreeNode`，不访问文件系统、不写数据库、不调用 `FileOperationService`。
* `FolderTreeService`（[src/application/folder_tree_service.py](../src/application/folder_tree_service.py)）为只读查询服务，协调 `ManagedRootRepository` 与 `FolderNodeRepository`，返回 `TreeNode` 列表；不在 UI 层递归拼 SQL。
* 数据源严格为 SQLite `FolderNode`；不在 UI 线程临时递归真实文件系统。`ManagedRoot` 与 `FolderNode` 通过 `path_key` 关联（`FolderNodeRepository.get_by_path_key()`），不通过隐式字符串匹配散落 UI。
* 惰性加载：`FolderTreeModel.canFetchMore()` / `fetchMore()` 在 view 请求时（展开、`rowCount` 调用）查询 `FolderTreeService.list_children(node_id)`，避免一次性加载整棵树。
* 节点内部 ID 编码：`"mr:<managed_root_id>"` 表示 `ManagedRoot` 顶层节点，`"fn:<folder_node_id>"` 表示 `FolderNode` 节点；通过 `QModelIndex.internalPointer()` 在 index 与 node 间往返。
* `TreeNode.category` 三类：`managed_root`（已配置且已扫描）、`unscanned_root`（已配置未扫描，虚拟节点）、`folder`（扫描得到的子目录）。
* 错误隔离：`FolderTreeService` 与 `FolderTreeModel` 捕获查询异常，记录日志并降级为空列表/空子树，不让整个树崩溃。
* `display_name` 回退：`FileScanner.persist_scan_result` 持久化时 `display_name` 为 `None`，`FolderTreeService` 用 `PurePath(real_path).name` 回退显示真实目录名。
* 线程边界：`FolderTreeModel` 与 `FolderTreeService` 在 UI 主线程构造与访问，使用主线程 SQLite 连接（与 `ManagedRootService` 共享），不创建后台线程。

### 2.4 素材池与 Mod 组装 UI model/view 边界（阶段 2 Task 3 实现）

素材池与 ModItem 组装使用 Qt model/view 架构，严格分层：

```text
QListView / QTableWidget (view)
    ↓ 读取 / 事件
UnassociatedPoolModel / ModItemListModel (QAbstractListModel)
    ↓ 读取
ModAssemblyService (application)
    ↓ 读取 / 写入
FileAssetRepository / ModItemRepository (infrastructure)
    ↓ 读取 / 写入
SQLite file_asset / mod_item 表
```

写入链路（UI 不直接组合 Repository 写操作）：

* `MainWindow._on_new_mod()` → `ModAssemblyService.create_mod_item()` → `ModItemRepository.create()` + `ModAssemblyService.add_member(new_id, asset_id, UNKNOWN)` → `FileAssetRepository.update()`：创建 ModItem 后自动将素材池中选中的素材以 `UNKNOWN` 角色关联到新条目。
* `MainWindow._on_associate()` → `ModAssemblyService.add_member(mod_id, asset_id, UNKNOWN)` → `FileAssetRepository.update()`：将选中素材以 `UNKNOWN` 角色关联到当前 ModItem。UI 不直接调用 `FileAssetRepository.update()`。
* `MainWindow._on_role_changed(asset_id)` → `ModAssemblyService.set_member_role(mod_id, asset_id, role)` → `FileAssetRepository.update()`：角色下拉变更后通过 service 写入。UI 不复制 `ROLE_LIMITS` 规则，直接展示服务层返回的 `MemberLimitError` / `DuplicateMemberError`。
* `MainWindow._on_remove_member(asset_id)` → `ModAssemblyService.remove_member(mod_id, asset_id)` → `FileAssetRepository.update()`：解除关联（`mod_item_id=None`, `role=UNKNOWN`），不删除、不移动真实文件。
* `MainWindow._on_save_metadata()` → `ModAssemblyService.update_mod_item(mod_id, ...)` → `ModItemRepository.update()`：保存显示名称/说明/来源链接/标签。

边界约定：

* `UnassociatedPoolModel`（[src/app/pool_model.py](../src/app/pool_model.py)）继承 `QAbstractListModel`，包装 `ModAssemblyService.list_unassociated_assets()` 返回的 `FileAsset` 列表，不访问文件系统、不写数据库。每行显示文件名、类型（文件/文件夹）和完整路径。
* `ModItemListModel`（同文件）继承 `QAbstractListModel`，包装 `ModAssemblyService.list_mod_items()` 返回的 `ModItem` 列表。
* `ROLE_DISPLAY_NAMES` / `ROLE_ORDER` 集中定义在 [src/app/pool_model.py](../src/app/pool_model.py)，UI 层角色下拉顺序与中文显示名从此处导出，不散落 widget 代码；角色数量限制仍由 `ModAssemblyService.ROLE_LIMITS` 强制，UI 不复制规则。
* 成员表格使用 `QTableWidget`，每行内嵌 `QComboBox`（角色编辑）和 `QPushButton`（移除按钮）；角色变更通过 `self.sender()` 获取发送者后调用 service。
* 按钮状态联动：「新建 Mod 条目」按钮在素材池无选择时禁用（`_update_new_mod_button`）；「关联到选中条目」按钮在无素材选择或无 ModItem 选中时禁用（`_update_associate_button`）。素材池选择变化通过 `_on_pool_selection_changed` 触发两个按钮的状态更新。
* 素材池刷新时机：扫描完成（`_on_scan_finished` / `_on_scan_failed`）、新建条目并关联（`_on_new_mod`）、关联素材（`_on_associate`）、移除成员（`_on_remove_member`）后调用 `_refresh_pool()`。
* 三栏布局：左栏=根目录列表+扫描状态+目录树+目录详情；中栏=素材池+ModItem 列表+新建/关联按钮；右栏=ModItem 详情编辑+成员表格。
* 错误展示：service 层抛出的 `ApplicationError` 子类由 UI 捕获并通过 `QMessageBox` 或状态栏展示给用户；中文文案集中在 [src/app/ui_constants.py](../src/app/ui_constants.py)，不写进 domain/application 层异常逻辑。
* 线程边界：`UnassociatedPoolModel` / `ModItemListModel` 与 `MainWindow` 在 UI 主线程构造与访问，使用主线程 SQLite 连接，不创建后台线程。
* 数据源严格为 SQLite `file_asset` / `mod_item` 表；不在 UI 线程重新扫描文件系统。

## 3. 模块职责

### ui/

负责：

* 主窗口
* 三栏布局（左栏：根目录列表 + 扫描状态 + 目录树 + 目录详情；中栏：素材池 + ModItem 列表 + 新建/关联按钮；右栏：ModItem 详情编辑 + 成员表格）
* 目录树
* 素材池（未关联 FileAsset 列表，显示文件名/类型/完整路径，支持多选）
* ModItem 列表与详情编辑（元数据 + 成员角色）
* 预演确认对话框
* 操作日志与撤销入口

不得负责：

* 拼接真实目标路径
* 直接移动文件
* 直接写 SQL
* 直接解析 AI JSON

### domain/

负责：

* ModItem、FileAsset、FolderNode、OperationLog 等领域模型
* 成员角色规则
* 移动预演规则
* 冲突规则
* 撤销可行性规则
* AI 建议应用规则

### infrastructure/

负责：

* SQLite 数据库连接、迁移和 Repository（含阶段 2 新增的 `ManagedRootRepository`）
* 文件扫描
* 路径标准化
* 文件移动、复制、存在性检查和权限检查
* 缩略图生成与缓存
* JSON 导入导出

`FolderNodeRepository`（Task 2 新增只读查询方法）：`list_all()` 返回全部节点按 `real_path` 排序；`get_by_path_key(path_key)` 按 `path_key` 查询，用于 `ManagedRoot` 与 `FolderNode` 关联；`count_children(parent_id)` 返回直接子目录数量（不含文件、不含孙节点）。

### application/

负责：

* 协调 UI 与领域逻辑
* 执行扫描
* 创建 Mod 条目
* 关联成员
* 生成移动预演
* 执行确认后的移动
* 导出和导入 AI 建议
* 更新搜索索引

阶段 2 新增职责：

* `ManagedRootService`：受管理根目录配置的添加、列出、查询；路径检查仅用只读文件系统 API（`Path.exists` / `Path.is_dir`）；不扫描、不移动、不删除用户文件。本任务不实现移除配置。
* `ScanWorkflowService`：读取已配置根目录，调用 `FileScanner.scan()` 与 `persist_scan_result()`，返回结构化 `ScanSummary`（扫描目录数、扫描文件数、持久化目录数、持久化文件数、错误列表）；不修改 `FileScanner` 同步接口；不访问 UI。
* `FolderTreeService`（Task 2 新增）：只读目录树查询服务，协调 `ManagedRootRepository` 与 `FolderNodeRepository`，返回 `TreeNode` 列表供 UI model 包装。方法：`list_root_nodes()` / `list_children(node_id)` / `get_node(node_id)` / `count_children(node_id)` / `has_scan_data(managed_root_id)`。不访问文件系统、不写数据库、不调用 `FileOperationService`。`ManagedRoot` 与 `FolderNode` 通过 `path_key` 关联，不在 UI 层散落字符串匹配。
* `ModAssemblyService`（Task 3 新增 UI 查询入口）：在阶段 1 既有 `create_mod_item` / `add_member` / `set_member_role` / `remove_member` / `update_mod_item` / `get_members` / `list_mod_items` 等写操作与查询接口基础上，新增 `list_unassociated_assets()` 委托 `FileAssetRepository.list_unassociated()`，返回 `mod_item_id` 为 `NULL` 的 `FileAsset` 列表供 UI 素材池展示。不复制关联规则到 UI；`ROLE_LIMITS` 仍为唯一规则源。

## 4. 数据存储

应用数据应位于：

```text
%LOCALAPPDATA%\SkyrimModWorkbench\
  app.db
  thumbnails\
  exports\
  logs\
```

用户 Mod 文件不应被复制到应用数据目录。唯一例外是缩略图缓存。

数据库损坏不应影响用户原始 Mod 文件；重新扫描后应能重建基础索引。

Schema 版本与迁移：

* schema v1（阶段 1）：`mod_item` / `file_asset` / `folder_node` / `operation_log` 四表。
* schema v2（阶段 2 任务 1）：新增 `managed_root` 表（`id` / `real_path` / `path_key` UNIQUE / `display_name` / `created_at` / `updated_at`）。`managed_root` 保存用户配置，独立于扫描结果；`folder_node.is_managed_root` 保留作为扫描结果标记。移除 `managed_root` 配置不自动清理 `folder_node` 记录（清理策略待确认）。v1→v2 迁移不丢失已有业务数据。

## 5. 路径与 Unicode

* 所有路径使用 pathlib.Path。
* 不得以字节串方式处理 Windows 路径。
* SQLite TEXT 字段保存 Unicode。
* JSON 文件使用 UTF-8。
* UI 必须完整显示中文、英文、日文和混合路径。
* 路径比较必须经过标准化；不得仅依赖字符串大小写比较。
* 待确认：Windows 下路径大小写规范化策略。

## 6. 文件操作服务

文件操作服务是唯一允许修改用户文件位置的模块。

接口示例：

```text
plan_move(mod_item_id, target_folder_id) -> MovePlan
execute_move(plan_id) -> OperationResult
plan_undo(operation_id) -> UndoPlan
execute_undo(undo_plan_id) -> OperationResult
```

MovePlan 必须包含：

* 操作 ID
* 成员文件列表
* 每个成员的源路径和目标路径
* 重名冲突
* 缺失文件
* 跨盘标记
* 可写性检查
* 阻止原因
* 可执行状态

执行前，MovePlan 必须持久化为 `planned` 状态。用户确认后才变为 `confirmed` 并执行。

预演后外部变化风险（阶段 2 UI 处理说明）：`execute_move` 从 OperationLog 读取 source/target 直接执行，执行前再次检查源存在与目标重名。预演到执行之间文件可能被外部改动，执行结果必须重新反映实际成功/失败，旧预演不作为执行保证。UI 必须展示执行结果的实际状态，不得直接复用预演结果。

## 7. 搜索架构

使用 SQLite FTS5 建立本地搜索索引。

索引字段：

* display_name
* description
* filename
* real_path
* source_url
* tags
* category_display_path

第一版搜索不要求复杂语法；普通关键词搜索即可。

## 8. 缩略图架构

阶段 2 未实现。缩略图生成与预览图墙归阶段 5（预览增强）。

* 原图保持不变。
* 缩略图以 `asset_id` 或内容标识命名。
* 缩略图缓存可随时删除并重建。
* 卡片优先加载缩略图，不直接加载大图。
* 待确认：缩略图缓存失效策略。

## 9. AI JSON 架构

* 所有 JSON 文件都必须有 `schema_version`。
* 导入前必须校验字段、类型、ID 是否存在。
* AI 返回的路径字段不得被信任。
* AI 只能引用已导出的 `asset_id`、`mod_item_id`、`folder_id`。
* AI 不得提供 shell 命令、任意文件路径或删除指令。
* 分类移动必须由本地 `folder_id` 映射到真实路径。

## 10. 操作历史查询

阶段 2 任务 5 需要展示最近操作列表与撤销入口。

* UI 不得直接拼接 `operation_log` SQL。
* 操作历史最小查询接口由 `OperationLogRepository` 或新增 query service 提供（如 `list_recent(limit)` / `list_undoable()`）。
* 查询接口仅读取数据库，不访问文件系统。
* 撤销可行性判断由 `FileOperationService.plan_undo()` 负责，UI 不得自行实现安全校验。

## 11. 测试策略

必须优先测试：

* 扫描中文路径。
* 创建 Mod 条目和关联成员。
* 同盘移动预演。
* 重名冲突预演。
* 目标目录为源目录子目录时的阻止。
* 部分成员缺失时的阻止。
* 操作日志写入。
* 撤销预演。
* AI JSON 非法字段拒绝。
* 数据库重启后数据恢复。

阶段 2 新增优先测试项：

* v1→v2 schema 迁移。
* ManagedRoot CRUD 与中文路径往返。
* 扫描工作流多根目录、错误继续、后台线程摘要。
* 移动预演→确认→执行→刷新→撤销预演→确认撤销完整流程。
* 取消确认后不执行移动。
* 部分失败结果展示。
* B1/B2 撤销阻止结果展示。
* 目录树查询：多根目录、中文目录、空目录、重叠根目录去重、重新连接数据库后树可加载（Task 2）。
* 目录树 model：节点层级、父子关系、惰性加载、无数据/错误数据不崩溃、刷新后状态正确（Task 2）。
* 目录树 UI：主窗口包含树视图、选中节点后详情区更新、未扫描根目录显示提示、扫描后树刷新（Task 2）。
* 素材池 model：未关联素材显示、关联后消失、解除关联后重新出现、中文文件名、文件/文件夹类型（Task 3）。
* ModItem 列表 model：空列表、显示条目、创建后刷新、中文标签 tooltip（Task 3）。
* Mod 组装 UI：无选择时创建/关联保护、错误展示、元数据编辑后重载保留、关联与移除后素材池刷新（Task 3）。
* ModAssemblyService 回归：创建 ModItem、添加多个成员、文件与文件夹成员、中文名称与中文标签、设置角色、移除成员、角色限制与重复成员错误（Task 3）。