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

## 3. 模块职责

### ui/

负责：

* 主窗口
* 三栏布局
* 目录树
* 素材池和 Mod 卡片
* 详情编辑
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
* 可选 `WorkbenchQueryService`：集中 UI 查询逻辑（目录树构建、未关联素材查询、ModItem 列表查询），避免 widget 直接访问 Repository。本任务未实现。

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