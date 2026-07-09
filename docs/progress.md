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
| 主窗口骨架与目录树、素材池、ModItem 列表 | ⏳ | Task 1 完成主窗口骨架与根目录/扫描区域；目录树/素材池/详情为占位区，Task 3 实现 |
| ModItem 手动组装与编辑 UI | ⬜ | 阶段 2 任务 4；成员角色、封面、元数据 |
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

**验收（来自 roadmap）**：

- [ ] 用户可添加、查看、移除受管理根目录配置（添加/查看已实现；移除未在 Task 1 范围）
- [x] 用户可手动触发扫描，看到扫描结果与错误摘要（未关联素材池待 Task 3）
- [ ] 用户可在素材池选择文件创建 ModItem，设置成员角色与封面
- [ ] 用户可在目录树选择目标分类，发起移动预演并明确确认执行
- [ ] 用户可看到执行结果，对安全操作发起撤销预演并确认撤销
- [x] 中文路径、中文显示名和 UTF-8 数据在扫描流程中保持可用
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
