# Technical Debt 记录

> 本文档记录 Code Review 中发现但未在第一批修复的问题。
> 第一批已修复：C1-C4、H2、H5、H6、M8、M12（详见 CHANGELOG v0.15.0）。
> 第二批已修复：TD-H4、TD-H5、TD-H6（详见 CHANGELOG v0.15.1）。
> 第三批已修复：TD-H7（收敛为 normalized 接口）、TD-H8（folder_cache 同步事务一致性）。
> 第四批已修复：TD-M25（application 层 except Exception 收窄）、TD-L20（删除旧 list_by_path_prefix）。
> 第五批已修复（Stage 4.5）：TD-H2（ScanService 事务边界）、TD-M22（folder_cache 同步 helper）、TD-L18（mtime 同步策略统一）。
> Stage 5 Code Review 已修复：TD-H9、TD-L6/L10/L11/L12/L15/L17/L22、TD-M1/M3/M4/M18/M19/M20
> （详见 CHANGELOG v0.41.0）；D1 ModGroupService→ContentUnitCreationService 代码层重命名、
> D2/D3 status→is_marked、D4 撤销不记录、H5 path_key + M12 冗余索引清理统一在 schema v11 迁移完成。
> 以下问题按严重级别排列，将在阶段 3 及后续迭代中逐步处理。

---

## High（影响正确性、稳定性、可用性）

### TD-H1: OperationHistory 缺少 target_path 与 operation_type 一致性校验 ✅ 已修复（Stage 5 Task 0）

- **位置**: [models.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/domain/models.py) `OperationHistory.__post_init__`
- **问题**: `move`/`rename`/`new_folder` 操作允许 `target_path=None`，`delete` 操作允许 `target_path` 非 None，无一致性校验。一旦 `FileOperationService` 实现，撤销链路会数据不一致。
- **修复（Stage 5 Task 0）**: 在 `__post_init__` 增加操作类型与 target_path 的一致性校验。move/rename/new_folder 要求 target_path 非空；delete 要求 target_path 为 None。
- **测试**: `tests/test_domain_models.py::TestOperationHistory::test_move_without_target_raises` 等 4 个新增测试。

### TD-H2: ScanService 持久化缺少事务边界与异常隔离 ✅ 已修复（Stage 4.5）

- **位置**: [scan_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/scan_service.py) `_persist_scan_result`
- **问题**: 写入 `folder_cache` 与 `content_unit` 两张表既未显式开启事务也未 commit。H5 修复后 Repository 不自提交，但 ScanService 未持有 connection 引用，无法控制事务边界。中途异常会导致部分提交或全部回滚，行为不可预测。
- **修复（Stage 4.5）**: ScanService 注入 `UnitOfWork`，`_persist_scan_result` 在 UoW 事务内执行多步写操作，任一失败整体回滚。与 H6（Service 多步写事务边界）同源一并修复。

### TD-H3: 文件列表加载在主线程同步执行 I/O + N+1 数据库查询

- **位置**: [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py) `_refresh_content_list` → [content_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/content_service.py) `list_directory_entries`
- **问题**: 每个目录条目执行 3 次系统调用（is_symlink/is_dir/stat）+ 1 次独立 DB 查询（get_by_path）。大目录（数百文件）UI 可冻结数百毫秒至数秒。违反 project_memory 中"UI must not freeze"约束。
- **建议**: 批量查询替代 N+1；将 list_directory_entries 移入后台线程或加 mtime 缓存。

### TD-H4: 扫描线程引用管理存在竞态条件 ✅ 已修复（v0.15.1）

- **位置**: [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py) `_on_thread_finished`
- **修复**: 在 `_on_thread_finished` 中用 `sender()` 校验，仅当退出的线程是当前 `self._thread` 时才清除引用。

### TD-H5: closeEvent 线程等待逻辑受 TD-H4 竞态影响 ✅ 已修复（v0.15.1）

- **位置**: [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py) `closeEvent`
- **修复**: 随 TD-H4 一并修复。`self._thread` 现在始终指向当前运行的线程，closeEvent 能正确等待。

### TD-H6: ContentUnitRepository.list_by_path_prefix SQL LIKE 通配符未转义 ✅ 已修复（v0.15.1）

- **位置**: [content_unit.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/repositories/content_unit.py) `list_by_path_prefix`
- **修复**: 转义 `prefix + sep` 中的 `%`、`_`、`\`，使用 `ESCAPE '\\'` 子句。

### TD-H7: list_by_path_prefix 在分隔符分歧场景下漏匹配子路径 ✅ 已修复（v0.16.0）

- **位置**: [content_unit.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/repositories/content_unit.py)
- **原描述更正**：原 TD-H7 描述"LIKE 翻倍导致 Windows 反斜杠路径下 broken"
  在机制上不准确。经实测验证：原 `list_by_path_prefix` 用 `LIKE ... ESCAPE '\'`，
  `\\` 在模式中匹配单个字面反斜杠，因此**同分隔符路径下（Windows 均反斜杠）
  实际能正常工作**。真正的失败场景是**分隔符分歧**——当数据库存储的路径与
  查询路径分隔符不一致时（如 FileScanner 存正斜杠、service 传反斜杠），
  LIKE 无法匹配，子路径记录被漏掉。
- **影响**：`ContentService.mark_as_content_unit` 的子项取消逻辑（spec §5.4）
  在分隔符分歧下静默失效；`list_staging_entries` 批量预查漏掉子项；
  `list_by_directory` / `list_direct_children` 同样受影响。
- **修复（v0.16.0）**：新增 `ContentUnitRepository.list_by_path_prefix_normalized`，
  用 `make_path_key` 归一化后做字符串前缀比较，跨平台一致。`ContentService`
  所有调用点（`list_by_directory` / `list_direct_children` / `mark_as_content_unit`
  / `list_staging_entries`）及 `QuickInsertService._cleanup_stale_content_units`
  统一切换到新接口，消除 service 层散落的 `list_all + make_path_key` 绕行方案。
  原 `list_by_path_prefix` 标记 deprecated 保留，待所有外部调用点迁移后删除。
- **回归测试**：`tests/test_content_service.py::TestListByPathPrefixNormalized`
  覆盖分隔符分歧、同分隔符、兄弟目录排除、`mark_as_content_unit` 子项取消
  分隔符分歧场景；含一条对照测试固化"原方法在分隔符分歧下返回空"的事实。

### TD-H8: folder_cache 同步采用"吞异常 + 上层 commit"模式导致部分提交态 ✅ 已修复（v0.16.0）

- **位置**: [quick_insert_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/quick_insert_service.py) `_sync_folder_cache` / [mod_group_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/mod_group_service.py) `create_mod_group` 步骤 1b
- **问题**：原实现用 `except Exception: logger.exception(...)` 吞掉 folder_cache
  同步中的所有异常，但同步内部包含多步写操作（删除旧 → 插入新 → 更新父 mtime）。
  一旦中间步骤失败、异常被外层吞掉，MainWindow 随后调用 `_commit` 会把
  "删除旧记录成功 + 插入新记录失败" 的部分提交态持久化进数据库，
  导致目录树出现静默缺节点，且无错误提示给用户。
- **修复（v0.16.0）**：
  - `QuickInsertService._sync_folder_cache` 不再吞异常，任一步失败立即抛出
    `FileOperationError`，由上层（MainWindow `_on_quick_insert_clicked`）
    捕获后调用 `_rollback` 回滚整个事务。
  - `ModGroupService.create_mod_group` 步骤 1b 同样改为抛出异常，
    并在抛出前调用 `_try_cleanup_empty_folder` 清理已创建的空文件夹。
  - MainWindow 已有的 `except FileOperationError: self._rollback()` 分支
    无需修改即可正确处理新行为。
- **回归测试**：`tests/test_quick_insert_service.py` 新增
  `test_quick_insert_sync_folder_cache_failure_rolls_back_transaction`
  和 `test_mod_group_create_folder_cache_failure_rolls_back`，用
  `_FlakyFolderCacheRepository` 模拟插入失败，验证事务回滚 + 数据库一致性。

---

## Medium（影响可维护性、性能、测试质量）

### TD-M1: ScanSummary.success 恒返回 True ✅ 已修复（Stage 5 Code Review）

- **位置**: [scan_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/scan_service.py) `ScanSummary.success`
- **问题**: 属性实现为 `return True`，docstring 暗示会基于 errors 判定，具有误导性。
- **修复**: 删除 `success` 属性。docstring 明确说明调用方应使用 `has_errors` 判断错误。

### TD-M2: ScanService 访问 FileScanner 私有方法 _mtime_equal

- **位置**: [scan_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/scan_service.py) 第 176 行
- **问题**: Application 层直接调用 Infrastructure 层的下划线前缀方法，封装泄漏。
- **建议**: 将 `_mtime_equal` 改为 public `mtime_equal`，或抽到共享工具模块。

### TD-M3: application.errors.ScanError 死代码 ✅ 已修复（Stage 5 Code Review）

- **位置**: [errors.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/errors.py) 第 25-26 行
- **问题**: `ScanError` 异常类从未被 raise/except/import，与 `file_scanner.ScanError` dataclass 同名易混淆。
- **修复**: 删除 `application.errors.ScanError` 类。

### TD-M4: FolderTreeService.list_root_nodes 类型信息丢失 ✅ 已修复（Stage 5 Code Review）

- **位置**: [folder_tree_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/folder_tree_service.py) 第 92 行
- **问题**: `fc_root_map: dict[str, object]` 应为 `dict[str, FolderCache]`，访问 `.id` 需 `# type: ignore`。
- **修复**: 导入 `FolderCache`，类型标注改为 `dict[str, FolderCache]`，删除 `# type: ignore` 注释。

### TD-M5: FolderTreeService 重复扫描 folder_cache 根节点列表

- **位置**: [folder_tree_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/folder_tree_service.py) `list_root_nodes` / `_list_children_of_managed_root` / `_get_managed_root_node`
- **问题**: 三处都调用 `list_by_parent(None)` 全表扫描后线性匹配 path_key，O(N*M)。无 helper 抽取。
- **建议**: 抽 helper 或在 Repository 增加 `get_by_path_key` 方法。

### TD-M6: FolderTreeService.count_children 通过 len(list_children) 实现

- **位置**: [folder_tree_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/folder_tree_service.py) 第 158-160 行
- **问题**: 仅为获取数量而构造全部子 TreeNode，浪费内存与 IO。
- **建议**: 在 FolderCacheRepository 增加 `count_by_parent(parent_id)` 使用 `SELECT COUNT(*)`。

### TD-M7: ManagedRootService 与 ScanService 重复定义 provider 函数

- **位置**: [managed_root_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/managed_root_service.py) / [scan_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/scan_service.py)
- **问题**: 两个 service 各自定义实现完全一致的 `_default_now_utc()` 与 `_default_uuid_provider()`。
- **建议**: 抽到共享模块（如 `application/_providers.py`）。

### TD-M8: except Exception 捕获过宽

- **位置**: [content_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/content_service.py) 第 119 行 / [scan_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/scan_service.py) 第 219 行
- **问题**: `except Exception` 会吞掉 `AttributeError`/`TypeError` 等编程错误，让 bug 在生产环境被静默忽略。
- **建议**: 收窄为 `except (RepositoryError, sqlite3.Error)`。

### TD-M9: ContentService._build_entry 多次 stat 系统调用

- **位置**: [content_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/content_service.py) 第 105-110 行
- **问题**: `is_symlink()` + `is_dir()` + `stat()` 三次独立 syscall，大目录累计开销明显。
- **建议**: 改用 `os.scandir()` 迭代，DirEntry 在 Windows 上首次调用后缓存 stat。

### TD-M10: FolderTreeService._find_managed_root_node_id 缺少参数类型标注

- **位置**: [folder_tree_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/folder_tree_service.py) 第 317 行
- **问题**: `fc_root` 参数无类型标注，违反 AGENTS.md 类型标注要求。
- **建议**: 改为 `fc_root: FolderCache`。

### TD-M11: _commit 数据库提交失败无 UI 反馈 ✅ 已修复（Stage 5 Task 0）

- **位置**: [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py) `_commit`
- **问题**: 提交失败仅 `logger.exception`，用户不知操作未持久化。违反 AGENTS.md"所有异常必须转换为用户可理解的错误信息"。
- **修复（Stage 5 Task 0）**: 提交失败时调用 `QMessageBox.critical`，标题与消息来自 `ui_constants.DB_COMMIT_FAILED_TITLE` / `DB_COMMIT_FAILED_MESSAGE`。同时保留 `logger.exception` 记录技术细节。
- **测试**: `tests/test_main_window_commit_error.py` 新增 3 个测试覆盖失败/成功/无 callback 场景。

### TD-M12: _refresh_content_list 失败时静默显示"空目录"

- **位置**: [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py) 第 431-441 行
- **问题**: 异常时 `entries = []`，显示"该目录为空"，用户无法区分错误与真空目录。
- **建议**: 异常时设置不同的提示文本。

### TD-M13: scan_progress 信号声明但不更新进度

- **位置**: [scan_worker.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/scan_worker.py) 第 51 行
- **问题**: `scan_progress` 信号仅在 run() 开头发送一次，大型目录扫描持续数十秒用户只看到静态"正在扫描…"。MainWindow 也未连接该信号。
- **建议**: ScanService 增加进度回调，ScanWorker 转发，MainWindow 连接更新状态栏。

### TD-M14: 根目录添加/移除 UI 流程无测试覆盖

- **位置**: `tests/` 目录
- **问题**: `_on_add_root` 和 `_on_remove_root` 的 UI 流程（含错误分支、按钮状态、列表刷新）无任何测试。
- **建议**: 新增 `test_main_window_roots.py`，mock QFileDialog/QMessageBox 测试 UI 行为。

### TD-M15: 扫描线程生命周期/closeEvent/_on_scan_failed 无集成测试

- **位置**: `tests/`
- **问题**: 现有测试直接调用 `_refresh_content_list_after_scan` 模拟扫描完成，未经过完整链路。TD-H4/H5 竞态条件无测试覆盖。
- **建议**: 增加 MainWindow 级别扫描集成测试。

### TD-M16: 文件列表无缓存

- **位置**: [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py) `_refresh_content_list`
- **问题**: 每次目录树选中都重新读取文件系统，用户在目录间切换时反复执行相同 I/O。
- **建议**: 引入带目录 mtime 失效的缓存。

### TD-M17: with get_connection(...) as conn: 不关闭连接

- **位置**: [db.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/db.py) `init_db` / [test_db.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/tests/test_db.py)（8 处）
- **问题**: `sqlite3.Connection` 的上下文管理器仅提交/回滚事务，不关闭连接。WAL 模式下文件句柄泄漏，Windows 上无法删除 db 文件。
- **建议**: 改用 `try/finally: conn.close()`，或用 `contextlib.closing` 包装。

### TD-M18: 误导性测试声称 delete/remove_root 自提交 ✅ 已修复（Stage 5 Code Review）

- **位置**: [test_managed_root_repository.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/tests/test_managed_root_repository.py) `test_delete_commits_without_explicit_commit` / [test_managed_root_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/tests/test_managed_root_service.py) `test_remove_root_persists_without_explicit_commit`
- **问题**: 测试名称和 docstring 声称"自提交"，但实际因 rollback 通过（create 也被回滚）。与 H5 修复后的设计契约冲突，给出虚假保障。
- **修复**: 删除这两个误导性测试。当前 Repository 不自提交是设计契约，测试"自提交"本身已无意义。

### TD-M19: FolderCacheRepository.upsert_mtime 的 path 参数未使用 ✅ 已修复（Stage 5 Code Review）

- **位置**: [folder_cache.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/repositories/folder_cache.py) `upsert_mtime`
- **问题**: `path` 参数声明后从未参与 SQL 或逻辑，调用方误以为 WHERE 用 path 过滤。
- **修复**: 移除 `path` 参数，签名改为 `upsert_mtime(mtime, folder_id)`。同步更新 3 处调用方：`folder_cache_sync_helper.py` / `scan_service.py` / `test_folder_cache_repository.py`。

### TD-M20: test_content_service.py 局部 fixture 遮蔽 conftest ✅ 已修复（Stage 5 Code Review）

- **位置**: [test_content_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/tests/test_content_service.py) 第 26-34 行
- **问题**: 局部 `db_connection` fixture 用 `tmp_path / "test.db"` 而非 conftest 的 `temp_app_data` 隔离路径，与项目约定相悖，且与 conftest 完全等价重复。
- **修复**: 删除局部 fixture，统一使用 conftest 的 `db_connection`。

---

## Low（代码风格、命名、文档）

### TD-L1: TreeNode.valid_categories 应为 ClassVar

- **位置**: [folder_tree_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/folder_tree_service.py) `__post_init__`
- **问题**: 每次 TreeNode 实例化都重建集合，应与 OperationHistory.VALID_OPERATION_TYPES 保持 ClassVar 模式。

### TD-L2: FolderTreeService TreeNode 构造代码重复

- **位置**: [folder_tree_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/folder_tree_service.py) `list_root_nodes` / `_get_managed_root_node`
- **问题**: managed_root/unscanned_root 两种 category 的 TreeNode 构造字段计算完全重复。
- **建议**: 抽 helper `_build_managed_root_node`。

### TD-L3: _extract_dirname 函数内 import

- **位置**: [folder_tree_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/folder_tree_service.py) 第 336 行
- **问题**: `from pathlib import PurePath` 在函数体内 import，违反 PEP 8。

### TD-L4: UI 文本硬编码未放入 ui_constants.py

- **位置**: [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py) 多处
- **问题**: "扫描状态"、"是"/"否"、"（无标题）"、评分格式、错误摘要格式等硬编码。违反 AGENTS.md"UI 文本集中在 ui_constants.py"。
- **建议**: 提取为 ui_constants.py 常量。

### TD-L5: folder_tree_model.py 硬编码"（未扫描）"

- **位置**: [folder_tree_model.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/folder_tree_model.py) 第 131 行
- **问题**: `f"{name}（未扫描）"` 硬编码，而 `ui_constants.TREE_UNSCANNED_HINT` 已定义但未引用。

### TD-L6: logging_setup.py docstring 路径名过时 ✅ 已修复（Stage 5 Code Review）

- **位置**: [logging_setup.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/logging_setup.py) 第 3 行
- **问题**: 写 `SkyrimModWorkbench`，实际为 `SkyrimContentWorkbench`。
- **修复**: 更新 docstring，说明日志写入应用数据目录下的 `logs/app.log`，并列出数据目录解析优先级。

### TD-L7: _ELIDE_PATH_PREFIXES 硬编码字符串前缀

- **位置**: [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py) 第 509 行
- **问题**: 前缀硬编码，未从 ui_constants 标签常量派生，标签修改后 Elide 检测会静默失效。

### TD-L8: main.py 数据库连接未用 try/finally 保护

- **位置**: [main.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main.py) 第 57-77 行
- **问题**: `conn = get_connection(db_path)` 后直接 `app.exec()`，异常时连接泄漏。

### TD-L9: main.py 作为组合根直接导入 infrastructure

- **位置**: [main.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main.py) 第 21-24 行
- **问题**: main.py 位于 UI 层目录但直接导入 infrastructure.repositories 创建实例，与 AGENTS.md 规则 3 有张力。
- **建议**: 移至独立 bootstrap 模块，或在文档中明确组合根角色。

### TD-L10: _on_scan_started 与 _begin_scanning 状态设置重复 ✅ 已修复（Stage 5 Code Review）

- **位置**: [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py) 第 692、709-710 行
- **问题**: 两处都设置 `STATUS_SCANNING`，属冗余。
- **修复**: 删除 `_on_scan_started` 中的状态设置，统一由 `_begin_scanning` 设置。

### TD-L11: file_classify.py 死代码 ✅ 已修复（Stage 5 Code Review）

- **位置**: [file_classify.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/file_classify.py)
- **问题**: `AssetHint` 枚举、`classify_by_extension` 函数、`IMAGE_EXTENSIONS` 常量无外部引用，docstring 引用已不存在的 FileAsset 表。
- **修复**: 删除 `AssetHint` / `classify_by_extension` / `IMAGE_EXTENSIONS` 及对应测试。保留 `ARCHIVE_EXTENSIONS` 和 `get_extension`（仍被 file_scanner.py 使用）。

### TD-L12: conftest.py sample_mod_tree fixture 死代码 ✅ 已修复（Stage 5 Code Review）

- **位置**: [conftest.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/tests/conftest.py) 第 66-103 行
- **问题**: 无任何测试引用，各测试文件都自定义本地 mod_tree fixture。
- **修复**: 删除 `sample_mod_tree` fixture。

### TD-L13: conftest.py db_connection 冗余设置 row_factory

- **位置**: [conftest.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/tests/conftest.py) 第 59 行
- **问题**: `get_connection` 已设置 row_factory（M12 修复），conftest 再次设置是多余操作。

### TD-L14: test_migrations.py 用 f-string 拼接 SQL

- **位置**: [test_migrations.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/tests/test_migrations.py) 第 411-415 行
- **问题**: 虽无注入风险，但破坏参数化查询风格一致性。

### TD-L15: init_db schema_version 初始化与首次迁移同事务 ✅ 已修复（Stage 5 Code Review）

- **位置**: [db.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/db.py) 第 72-89 行
- **问题**: 建表 + v0 基线 INSERT 实际和 v0→v1 迁移落在同一事务，与 docstring 声称的"每步迁移在独立事务中执行"不一致。
- **修复**: 在 v0 基线 INSERT 后添加显式 `conn.commit()`，使 v0 基线与首次迁移分属独立事务，与 docstring 契约一致。

### TD-L16: test_migrations.py 三个测试用 tmp_path 而非 temp_app_data

- **位置**: [test_migrations.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/tests/test_migrations.py) 第 491、521、529 行
- **问题**: 与 test_db.py 的 fixture 体系不一致，缺少类型标注。

### TD-L17: test_managed_root_service.py 用 __import__ hack ✅ 已修复（Stage 5 Code Review）

- **位置**: [test_managed_root_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/tests/test_managed_root_service.py) 第 352、366 行
- **问题**: `__import__("sqlite3").Row` 而非顶部 `import sqlite3`，可读性差。M12 修复后该设置本身也冗余。
- **修复**: 配合 M18 删除误导性测试后，`__import__` hack 一并随之删除。

---

## 第三批新增（Stage 3 Code Review 2026-07-17 确认暂缓）

> 以下问题来自 Stage 3 正式 Code Review，经评估不阻塞 Stage 4 启动，
> 但建议在对应阶段择机处理。编号接续既有 TD 序列。

### TD-M21: MainWindow God Object 趋势 ✅ 已处理（UX 重构 Task 7，v0.48.0）

- **位置**: [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py)
- **背景**: Stage 3 Code Review 发现 MainWindow 已增长到约 3490 行 / 150 方法
  （2026-08-01 复核，原登记 1570 行 / 76 方法已过时），
  承担 UI 搭建、信号槽、扫描线程生命周期、装配面板绑定、快速插入流程、
  元数据展示、Elide 渲染、模式切换、DB 事务边界（`_commit`/`_rollback`）等
  多重职责。Stage 4 还要加搜索栏、标签筛选、评分控件、备注编辑器；
  Stage 5 还要加删除确认、重命名对话框、撤销栈 UI。按当前增长趋势，
  MainWindow 会迅速突破 2500 行。
- **影响范围**: 仅影响 UI 层可维护性，不影响正确性。但 Stage 4/5 的 UI 改动
  都要在巨型文件里找上下文，开发成本显著上升。
- **推荐修复方案**: 至少拆出 `ScanController`（封装 ScanWorker 生命周期 +
  信号转发）、`AssemblyController`（装配面板绑定 / 回调 / 快速插入流程）、
  `MetadataView`（元数据 + Elide 渲染）、`ModeController`（模式切换 + hint）。
  `_commit` / `_rollback` 移到 `UnitOfWork` 或 `TransactionScope`，UI 持有
  其引用而非裸 connection。
- **建议修复阶段**: **UX 重构 Task 7**（Q8:C 决策"边开发边小规模拆分"未执行，
  已由用户决策归入 UI 重构版本统一处理）。
- **处理（UX 重构 Task 7，v0.48.0）**: TransactionScope / ScanController /
  AssemblyController / MetadataView 已拆出；MainWindow 保留薄委托与文件操作编排，
  行数继续下降，可进一步瘦身。

### TD-M22: folder_cache 同步辅助逻辑在多个 Service 中重复 ✅ 已修复（Stage 4.5）

- **位置**: [mod_group_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/mod_group_service.py) `_resolve_parent_id_by_path` / [quick_insert_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/quick_insert_service.py) `_resolve_parent_id_by_path` / `_delete_folder_cache_by_path` / `_create_folder_cache_for_new_path` / `_update_parent_mtime` / [assembly_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/assembly_service.py) `_sync_folder_mtime`
- **背景**: `_resolve_parent_id_by_path` / `_new_folder_cache_id` / `_now_iso`
  在 `ModGroupService` 和 `QuickInsertService` 中逐字重复；`_is_in_directory`
  在 `ModGroupService` 和 `AssemblyService` 中重复；`_default_now_utc` /
  `_default_uuid_provider` / `_mtime_to_iso` 在 4 个 service 中各自重复。
- **影响范围**: Stage 5 加 undo 时需要反向同步 folder_cache（删新 + 插旧 +
  更新两个父 mtime），如果不抽公共方法，undo 路径会再次复制一份，届时
  4 份重复。任何一处修 bug 都要同步改 4 处。
- **修复（Stage 4.5）**: 新建 [FolderCacheSyncHelper](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/folder_cache_sync_helper.py)，
  提供 `on_folder_created` / `on_folder_moved` / `on_folder_deleted` /
  `update_folder_mtime` 语义化方法。多步同步失败抛 `FileOperationError`，
  单字段 mtime 更新保留 best-effort（TD-L18 策略统一）。
  `ModGroupService` / `QuickInsertService` / `AssemblyService` 移除各自的
  重复同步逻辑，`FileOperationService.move` / `new_folder` 注入 helper 后
  自动同步 folder_cache + ContentUnit.path（H4），消除调用方手动同步的
  隐式契约。

### TD-M23: folder_cache 同步中多次 list_all() 全表扫描

- **位置**: [quick_insert_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/quick_insert_service.py) `_delete_folder_cache_by_path` / `_create_folder_cache_for_new_path` / `_resolve_parent_id_by_path` / `_update_parent_mtime`
- **背景**: 单次 `quick_insert` 调用会触发至少 5 次 `folder_cache_repo.list_all()`
  全表扫描。当前 folder_cache 规模小，无感；当用户管理几千个文件夹时，
  每次快速插入都要全表扫描 5 次。
- **影响范围**: 性能问题，不影响正确性。
- **推荐修复方案**: `FolderCacheRepository` 加 `get_by_path_key(path_key)` /
  `find_by_path_prefix(prefix)` 方法，用 SQL 直接查。归一化比较仍可用
  `make_path_key`，但只对结果集做，不对全表做。
- **建议修复阶段**: **Stage 4 后**（性能优化，非阻塞）。

### TD-M24: AssemblyService.rename_as_cover 的 9999 上限抛 ConflictError 语义错位

- **位置**: [assembly_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/assembly_service.py) `rename_as_cover`
- **背景**: 当后缀编号超过 9999 时抛 `ConflictError`，但这是"命名空间耗尽"
  而非"目标已存在冲突"。`ConflictError` 在 UI 层会被当作"目标已存在，
  请用户改名"处理，但这里实际上是无法生成唯一名。
- **影响范围**: 实际场景下 9999 几乎不会触发，但语义错位会让 Stage 5 的
  错误提示体系混乱。
- **推荐修复方案**: 用新的异常类型（如 `CoverRenameLimitError`）或
  `FileOperationError`。
- **建议修复阶段**: **Stage 4 后**（非阻塞，但建议在 Stage 5 错误提示
  体系统一时一并处理）。

### TD-M25: 多处 except Exception 吞掉编程错误 ✅ 已修复（Stage 4 Task 0）

- **位置**: [content_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/content_service.py) / [scan_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/scan_service.py) / [quick_insert_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/quick_insert_service.py) / [mod_group_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/mod_group_service.py) / [assembly_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/assembly_service.py)
- **背景**: 多处 `except Exception: # noqa: BLE001` 会吞掉 `TypeError` /
  `AttributeError` / `KeyError` 等编程错误，让 bug 以"日志里一条 traceback
  + 用户看到功能异常"的形式存在，而不是"快速失败暴露问题"。
- **影响范围**: Stage 4 加标签 / 评分时，如果 dataclass 字段拼错导致
  `TypeError`，会被这类 except 吞掉，表现为"标签偶尔加不上"，极难定位。
- **修复（Stage 4 Task 0）**: 区分"预期外部错误"和"编程错误"。application
  层 service 中的 14 处 `except Exception` 收窄为具体异常类型：
  - 数据库相关：`(RepositoryError, sqlite3.Error)`
  - 文件系统相关：附加 `OSError`
  - 应用层错误（service 间调用）：附加 `ApplicationError` / `FileOperationError`
  - UI 边界 / Qt worker / QAbstractItemModel 边界保留宽捕获（防止进程崩溃，
    这是合理的防御性编程）。
  编程错误（`TypeError` / `AttributeError` 等）现在会在开发期直接冒泡暴露。

### TD-M26: MainWindow 信号槽 / 状态同步 / 扫描线程生命周期无集成测试

- **位置**: `tests/`
- **背景**: Stage 3 Code Review 指出 `_update_quick_insert_button_state`、
  `_bind_assembly_panel` 切换 Mod 组时旧 panel 状态清理、扫描完成后
  `_refresh_content_list_after_scan` 是否保留当前选中等都无自动化测试，
  纯靠手动验收。Stage 4 加更多状态（标签筛选、评分编辑）后，手动验收
  成本会爆炸。
- **影响范围**: 不影响当前正确性，但影响回归保障。
- **推荐修复方案**: 至少加 `MainWindow` 的轻量级集成测试（用 `QTest`
  模拟点击 / 选中），覆盖快速插入按钮状态机和装配面板绑定流程。
- **建议修复阶段**: **UX 重构 Task 7**（与 TD-M21 拆分同步进行，
  拆分后更易为各 Controller 写测试）。

### TD-M27: SQLite 并发写未测试（ScanWorker 独立连接 vs 主线程连接）

- **位置**: `tests/`
- **背景**: `ScanWorker` 用独立 connection，与主线程 connection 并发写
  folder_cache。没有测试覆盖"扫描进行中用户点击快速插入"的场景。
  SQLite 默认 isolation 下可能出现 `database is locked`。
- **影响范围**: 极端场景下的稳定性风险。
- **推荐修复方案**: 加集成测试覆盖"扫描进行中触发快速插入"的并发场景，
  验证是否出现 `database is locked` 或数据损坏。
- **建议修复阶段**: **Stage 4 后**（非阻塞，但建议在 Stage 5 undo
  实现前验证并发安全）。

### TD-L18: AssemblyService._sync_folder_mtime 与 H2 修复后的同步策略不一致 ✅ 已修复（Stage 4.5）

- **位置**: [assembly_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/assembly_service.py) `_sync_folder_mtime`
- **背景**: H2 修复后 `QuickInsertService._sync_folder_cache` 和
  `ModGroupService.create_mod_group` 的 folder_cache 同步失败都改为抛异常，
  但 `AssemblyService._sync_folder_mtime` 仍保留 `except Exception: 吞异常`
  模式。因为 `_sync_folder_mtime` 只更新单字段（mtime），不涉及多步写，
  部分提交风险低，最坏情况是下次扫描重新处理该文件夹——不会数据不一致。
  但策略不一致本身是认知负担。
- **影响范围**: 无数据一致性风险，仅策略一致性。
- **修复（Stage 4.5）**: 与 TD-M22 一并处理。`FolderCacheSyncHelper` 明确
  区分两类契约：`update_folder_mtime` 为 best-effort（单字段更新，失败仅记日志），
  `on_folder_moved` / `on_folder_created` / `on_folder_deleted` 为多步原子操作，
  失败抛 `FileOperationError`。`AssemblyService` 移除 `_sync_folder_mtime`，
  由 `FileOperationService.move` 内部 helper 自动同步 mtime。

### TD-L19: OperationHistory.can_undo 恒为 True，但 undo 未实现 ✅ 已修复（Stage 5 Task 0）

- **位置**: [file_operation_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/file_operation_service.py) `new_folder` / `move`
- **背景**: 写历史时 `can_undo=True`，但 Stage 3 没有 undo 实现。
  这是已知的 Stage 5 范围，但 `can_undo` 字段语义在 Stage 3 期间是
  "承诺可撤销"而非"实际可撤销"。UI 若基于此字段显示"可撤销"标识会误导用户。
- **修复（Stage 5 Task 0）**: 在 `OperationHistory.__post_init__` 增加
  `delete` 操作的 `can_undo` 校验：delete 不可撤销，`can_undo` 必须为 False。
  move/rename/new_folder 的 `can_undo` 校验留待 Stage 5 Task 6 实现 undo 时
  配合"安全状态检查"一并落地（届时根据运行时文件状态决定是否可撤销）。
- **测试**: `tests/test_domain_models.py::TestOperationHistory::test_delete_can_undo_true_raises` 等。
- **建议修复阶段**: **Stage 5**（undo 实现时）。

### TD-L20: list_by_path_prefix（旧 broken 方法）保留待删除 ✅ 已修复（Stage 4 Task 0）

- **位置**: [content_unit.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/repositories/content_unit.py) `list_by_path_prefix`
- **背景**: TD-H7 修复新增 `list_by_path_prefix_normalized`，但旧的
  `list_by_path_prefix`（LIKE + ESCAPE，分隔符分歧下 broken）保留为
  deprecated，因为有测试直接调用它（`test_content_unit_repository.py::TestListByPathPrefix`
  及 `test_content_service.py::TestListByPathPrefixNormalized::test_separator_divergence_old_method_returns_empty`
  对照测试）。
- **影响范围**: 旧方法若被新代码误用会重现分隔符分歧 bug。
- **修复（Stage 4 Task 0）**: 确认 v0.20.1 后生产代码已全部迁移到
  `list_by_path_prefix_normalized`，无外部调用。删除：
  - `ContentUnitRepository.list_by_path_prefix` 方法（content_unit.py）
  - `TestListByPathPrefix` 测试类（test_content_unit_repository.py，4 项测试）
  - `test_separator_divergence_old_method_returns_empty` 对照测试
    （test_content_service.py，1 项）
  - test_content_unit_repository.py 中 `from pathlib import Path` 不再需要
    （仅旧 TestListByPathPrefix 使用 Path 构造跨平台路径），已删除。
  - 各 service 的 docstring 中"原 list_by_path_prefix broken"表述更新为
    "原方法已删除，统一使用 normalized 接口"。

---

## 第五批新增（Stage 4 Code Review 2026-07-28 确认登记）

> 以下问题来自 Stage 4 正式 Code Review，经 Stage 4.5 评估后登记为技术债延后处理。
> Stage 4.5 已修复的问题（H1-H4、H6-H7、M4、M19 等）详见 CHANGELOG。
> 编号接续既有 TD 序列。

### TD-H9: content_unit.path UNIQUE 约束绕过 make_path_key ✅ 已修复（Stage 5 Code Review schema v11）

- **位置**: [db.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/db.py) `content_unit` 表 schema
- **背景**: `content_unit.path` 列有 UNIQUE 约束，但数据库存储的路径字符串
  大小写/分隔符不一致时（Windows 大小写不敏感），UNIQUE 约束无法防止
  "同一路径不同表示"的重复记录。`make_path_key`（normcase + normpath）
  在应用层统一了比较，但 DB 层 UNIQUE 约束未使用 path_key。
- **修复（schema v11）**: content_unit 表新增 `path_key TEXT NOT NULL UNIQUE` 列，
  与 managed_root / staging_area 模式一致。迁移时回填 `path_key = make_path_key(path)`，
  ContentUnitRepository.create / update 自动计算 path_key。DB 层强制路径归一化唯一，
  消除应用层兜底的不完全保障。

### TD-H10: FileOperationService 分层归属 ✅ 已修复（UX 重构 Task 7 Commit 2）

- **位置**: [file_operation_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/file_operation_service.py)
- **背景**: `FileOperationService` 位于 infrastructure 层，但 Stage 4.5 H4
  修复后注入了 `FolderCacheSyncHelper` + `ContentUnitRepository`，进一步加深
  了分层违反。当前 `FolderCacheSyncHelper` 放在 infrastructure 层避免反向依赖，
  但长期来看 `FileOperationService` 应移到 application 层。
- **影响范围**: 架构层次不清，但不影响正确性。Stage 5 文件操作重构时
  （rename/delete/undo）会进一步增加耦合。
- **修复（UX 重构 Task 7 Commit 2）**: `FileOperationService` 从 `infrastructure/`
  迁移到 `application/`（消除 infrastructure → application 反向依赖；
  `FolderCacheSyncHelper` 保持 infrastructure，仅依赖 FolderCacheRepository）。

### TD-M28: 多处 N+1 查询

- **位置**: [content_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/content_service.py) `list_directory_entries` / [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py) `_refresh_content_list` 等
- **背景**: Stage 4 Code Review 发现 7 处 N+1 查询：每个目录条目独立查询
  ContentUnit / Tag 关联，大目录（数百文件）累计数十次 DB 查询。与 TD-H3
  和 TD-M9 同源。
- **影响范围**: 性能问题，大目录 UI 响应慢。不影响正确性。
- **推荐修复方案**: 批量查询（`list_by_directory` 一次查全部子项 ContentUnit），
  或用 `list_by_unit_ids` 批量查标签关联。
- **建议修复阶段**: **Stage 5 中期**（与 TD-H3 性能优化一并处理）。

### TD-M29: 测试组织风格不统一

- **位置**: `tests/` 目录
- **背景**: 各测试文件组织风格不一致：部分用 `class TestXxx` 分组，
  部分用顶层函数；测试辅助方法混在主类中；fixture 命名和复用方式不统一。
- **影响范围**: 不影响正确性，但增加测试维护成本。
- **推荐修复方案**: 统一测试组织风格，抽公共测试辅助到 `tests/helpers/`。
- **建议修复阶段**: **Stage 5 中期**（非阻塞）。

### TD-L21: UI 样式表硬编码颜色

- **位置**: [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py) / [metadata_panel.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/metadata_panel.py) 等
- **背景**: 多处 QSS 样式表中硬编码颜色值（如 `#2d2d2d`），未使用
  主题变量或常量。暗色模式或主题切换时需逐处修改。
- **影响范围**: 不影响正确性，仅影响主题可维护性。
- **推荐修复方案**: 提取颜色常量到 `ui_constants.py` 或 QSS 主题文件。
- **建议修复阶段**: **暗色模式/主题切换时**（非阻塞）。

### TD-M30: spec §10.3 "最近常用置顶"未实现

- **位置**: spec §10.3
- **背景**: spec 定义了"最近常用标签置顶"功能，但 Stage 4 Task 3
  未实现。Stage 4 Code Review 确认此为产品范围决策（D7: C），登记为
  技术债延后处理。
- **影响范围**: 功能缺失，不影响正确性。用户使用标签筛选时无"最近常用"
  排序辅助。
- **推荐修复方案**: Stage 5 或后续迭代中实现，或从 spec 中移除。
- **建议修复阶段**: **需用户决策后确定**（D7: C 登记为 TD）。

### TD-L22: ContentUnit.status 字段重构为 is_marked: bool ✅ 已修复（Stage 5 Code Review schema v11）

- **位置**: [models.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/domain/models.py) `ContentUnit.status`
- **问题**: Stage 5 Task 7 收尾清理后，status 仅剩两态（`organized` / `unmarked`），语义等价于布尔 `is_marked`。使用字符串字段略显冗余，且 schema DEFAULT 仍为旧值 `unorganized`（SQLite 不便修改 DEFAULT，由应用层 ContentUnit 默认值接管）。
- **修复（schema v11，D2=B / D3=C 决策）**: 将 status 字段重构为 `is_marked: bool`，破坏性 schema 迁移：
  - content_unit 表移除 `status` 列，新增 `is_marked INTEGER NOT NULL DEFAULT 1 CHECK(is_marked IN (0, 1))`
  - 数据迁移：`status='organized'` → `is_marked=1`，`status='unmarked'` → `is_marked=0`
  - Domain 层 `ContentUnit` / `SearchResult` 字段 `status: str` → `is_marked: bool`，`__post_init__` 增加 bool 类型校验
  - Repository / Service / UI 全链路改用 `is_marked`
  - 简化两态语义为布尔值，消除 "organized" 字面歧义

---

## Stage 5 Code Review 新增（2026-07-31）

> 以下问题来自 Stage 5 完成后的全面 Code Review，经用户决策后登记为技术债延后处理。
> 已修复项（H1/H2/H3 文档说明、H5 path_key、M1-M14、TD-H9、TD-L6/L10/L11/L12/L15/L17/L22 等）
> 详见 CHANGELOG v0.41.0。编号接续既有 TD 序列。

### TD-H11: operation_history.source_path 在 undo 记录中存 ID 而非路径（H3）✅ 已修复（Stage 5 Code Review schema v11）

- **位置**: [undo_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/undo_service.py) `undo()`
- **背景**: undo 记录的 `source_path` 存的是原 history.id 而非路径（H3），字段名与实际用途不符。
- **修复（schema v11，D4=A 决策）**: 撤销操作不再写入 `operation_history` 新记录。撤销只标记原记录的 `undone_at` 时间戳，UI 通过 `undone_at` 判断灰色状态。迁移时清理历史 `operation_type='undo'` 记录。H3 问题（source_path 存 ID）随之消失，无需新增 `original_op_id` 列。

### TD-H12: 文件操作与 DB 事务不一致窗口未补偿（H4）

- **位置**: [file_operation_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/file_operation_service.py) `move` / `rename` / `copy`
- **背景**: 文件已成功 + DB 同步失败时，文件无法回滚，仅抛 `FileOperationError` 让 UoW 回滚 DB。导致文件系统与 DB 状态不一致——文件已在新位置，DB 仍记录旧路径。这是文件系统固有约束（shutil 不支持事务）。
- **影响范围**: 极端场景下（DB 锁、磁盘满）用户文件已移动但应用显示旧位置。
- **推荐修复方案**: 引入"补偿日志"机制（记录文件已成功移动但 DB 未更新），下次启动时尝试补偿；或在错误提示中明确告知用户"文件已移动但元数据更新失败，请手动刷新或重新扫描"。
- **建议修复阶段**: **Stage 6 或后续迭代**（数据一致性版本）。

### TD-M31: MainWindow 业务逻辑泄漏 ✅ 已处理（UX 重构 Task 7，v0.48.0）

- **位置**: [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py)
- **背景**: MainWindow 约 3490 行、150 个方法、60+ 实例变量、6 个并行状态机
  （2026-08-01 复核，原登记 3823 行 / 95 方法已过时）。承担 21 处 `_commit()` + 文件操作编排 + 冲突解决编排（2 个重复方法）。Stage 4/5 期间 Q8:C 决策"边开发边小规模拆分"实际未执行，反而新增了快捷键 handler（14 个）、导航历史栈等逻辑。
- **影响范围**: 任何 UI 改动成本极高，且 UI 层承担了本应在 Application 层的事务边界职责。
- **推荐修复方案**: UI 重构版本前置任务。至少拆出 `ScanController` / `AssemblyController` / `MetadataView` / `ModeController` / `TransactionScope`（事务边界从 UI 移到 Application 层）。
- **建议修复阶段**: **UI 重构版本（前置）**（用户决策：UI 重构单独开分支处理）。

### TD-M32: UndoService 安全校验无 size/mtime 比对

- **位置**: [undo_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/undo_service.py) `_safety_check`
- **背景**: 当前 undo 安全校验仅诊断记录，未存储操作前快照，无法检测文件已被外部修改。撤销可能覆盖用户在 undo 期间的外部修改。
- **影响范围**: 撤销安全性不足，极端场景可能丢失用户外部修改。
- **推荐修复方案**: schema 扩展存储操作前快照（size + mtime），undo 前比对当前文件状态与快照。
- **建议修复阶段**: **Stage 6 或后续**（数据一致性版本，与 TD-H12 一并处理）。

### TD-M33: mark_undone 失败可能导致重复撤销

- **位置**: [undo_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/undo_service.py) `undo()` 第 5 步
- **背景**: 反向文件操作已执行但 `mark_undone` 失败时，原记录未标记 `undone_at`，用户可能再次触发撤销，导致重复反向操作。当前仅记日志，由调用方决定是否提示用户。
- **影响范围**: 极端场景下（DB 锁）可能重复撤销。
- **推荐修复方案**: 引入版本号或乐观锁，或在 `mark_undone` 失败时回滚反向操作（成本高）。
- **建议修复阶段**: **Stage 6 或后续**（与 TD-M32 一并处理）。

### TD-M34: 覆盖模式子节点 folder_cache 不立即重建

- **位置**: [file_operation_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/file_operation_service.py) 覆盖模式分支
- **背景**: 覆盖模式下子节点 folder_cache 不立即重建，需等下次扫描才修复。当前扫描速度可接受，用户感知低。
- **影响范围**: 覆盖后目录树可能短暂缺节点，下次扫描后恢复。
- **推荐修复方案**: 下次扫描优化时一并处理。
- **建议修复阶段**: **下次扫描优化时**（非阻塞）。

### TD-M35: rename 跨盘抛 FileOperationError，move 抛 CrossDriveError，异常类型不一致 ✅ 已修复（UX 重构 Task 7 Commit 2）

- **位置**: [file_operation_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/file_operation_service.py) `rename` / `move`
- **背景**: 同一语义的跨盘操作，rename 抛 `FileOperationError`，move 抛 `CrossDriveError`，UI 层需分别捕获。
- **影响范围**: 不影响正确性，但异常处理代码冗余。
- **修复（UX 重构 Task 7 Commit 2）**: `rename` 跨盘统一抛 `CrossDriveError`
  （FileOperationError 子类），与 `move` 一致。

### TD-L23: content_unit.content_type 默认 'mod' 与实体名不一致

- **位置**: [models.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/domain/models.py) `ContentUnit.content_type`
- **背景**: `content_type` 默认值 `'mod'`，但实体名为 `ContentUnit`（内容单元），不是 "Mod"。当前仅支持单一类型，字段预留多类型扩展。
- **影响范围**: 不影响正确性，仅命名不一致。
- **推荐修复方案**: 未来支持多类型时重构。
- **建议修复阶段**: **未来支持多类型时**（非阻塞）。

### TD-L24: FileEntry 类名与注释不一致

- **位置**: [content_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/content_service.py) `FileEntry`
- **背景**: 类名 `FileEntry`，注释"目录条目"。实际既可能是文件也可能是目录。
- **影响范围**: 不影响正确性，仅认知负担。
- **推荐修复方案**: UI 重构时一并考虑。
- **建议修复阶段**: **UI 重构时**（非阻塞）。

### TD-L25: FileOperationService._sync_on_delete 访问 helper 私有 `_repo` ✅ 已修复（UX 重构 Task 7 Commit 2）

- **位置**: [file_operation_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/file_operation_service.py) `_sync_on_delete`
- **背景**: 通过 `self._helper._repo` 访问 FolderCacheSyncHelper 的私有 `_repo`，标注 `# noqa: SLF001`。
- **影响范围**: 封装泄漏，但不影响正确性。
- **修复（UX 重构 Task 7 Commit 2）**: `FolderCacheSyncHelper` 新增语义化
  `delete_folder_subtree(path)`（按路径前缀 + 深度降序删除），`_sync_on_delete`
  改走公共方法，不再访问私有 `_repo`。

### TD-L26: time 字段后缀不统一（`_mtime` vs `_at`，REAL vs TEXT）

- **位置**: 多处 schema 与 domain 模型
- **背景**: `folder_cache.mtime` 用 REAL，`content_unit.created_at` 用 TEXT；`_mtime` 与 `_at` 后缀语义模糊。
- **影响范围**: 不影响正确性，仅文档约定。
- **推荐修复方案**: 文档统一约定。
- **建议修复阶段**: **文档统一约定即可**（非阻塞）。

### TD-L27: ClipboardEntry.timestamp 字段未使用（潜在死代码）

- **位置**: [clipboard_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/clipboard_service.py) `ClipboardEntry`
- **背景**: `timestamp` 字段定义后从未被读取。
- **影响范围**: 潜在死代码。
- **推荐修复方案**: 确认是否预留，否则删除。
- **建议修复阶段**: **确认用途后决定**（非阻塞）。

### TD-L28: UI 中"目录"和"文件夹"混用

- **位置**: [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py) / [ui_constants.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/ui_constants.py) 多处
- **背景**: UI 文本中"目录"和"文件夹"混用，未统一。
- **影响范围**: 不影响正确性，仅术语一致性。
- **推荐修复方案**: UI 重构时统一为"文件夹"或"目录"。
- **建议修复阶段**: **UI 重构时**（非阻塞）。

### TD-L29: M13 Domain 校验已扩展到 ContentUnit.content_type（Stage 5 Code Review）

- **位置**: [models.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/domain/models.py) `ContentUnit.VALID_CONTENT_TYPES`
- **背景**: Stage 5 Code Review M13 为 `ContentUnit.content_type` 添加了 Domain 层取值范围校验（`VALID_CONTENT_TYPES = frozenset({"mod"})`），与 `OperationHistory.operation_type` 的严格校验对齐。
- **现状**：已修复，无需进一步处理。当前 `content_type` 仅 `'mod'`，未来扩展类型时需同步更新此集合。
- **建议修复阶段**: **未来扩展类型时**（已修复，仅记录约定）。

## UX 重构新增（2026-08-01）

> 以下问题来自 UX 重构 Phase 1/2 实施与文档一致性复核，编号接续既有 TD 序列。

### TD-M36: FileListView 未统一（FileListModel / AssemblyListModel 双模型）✅ 已修复（UX 重构 Task 7 Commit 2）

- **位置**: [file_list_model.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/file_list_model.py) `FileListModel`（中栏）/ [assembly_panel.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/assembly_panel.py) `AssemblyListModel`（装配面板）
- **背景**: UX 重构 Phase 1 Task 1 已登记但未编号。中栏 FileListModel 与装配面板
  AssemblyListModel 两套模型各自维护，文件操作/右键菜单/拖拽逻辑需在两处同步修改。
- **影响范围**: 可维护性，不影响正确性。
- **修复（UX 重构 Task 7 Commit 2）**: 移除 `AssemblyListModel`，装配面板复用
  `FileListModel(single_column=True)`（单列纯文件名 + 标准图标，视觉行为一致），
  消除双模型维护。

### TD-L30: Assembly* 代码标识符 legacy 命名（显示名已改为「文件夹预览」）✅ 已决策（v0.50.2）

- **位置**: [assembly_panel.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/assembly_panel.py) / [ui_constants.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/ui_constants.py)
- **背景**: UX 重构 Phase 1 Task 2 扩展装配面板语义为"文件夹透视器"（可透视任意
  文件夹，不限于内容单元），面板名称仍为"装配面板"，是否改名待用户确认
  （Task 2 遗留项，登记为技术债）。
- **影响范围**: UI 文案与文档术语。
- **决策（2026-08-02，UI合理性1）**: 显示名改为「文件夹预览」
  （`ASSEMBLY_PANEL_TITLE`，v0.50.2 生效）；代码标识符
  （`AssemblyPanel` / `assembly_panel.py` / `assembly_controller.py` /
  `assembly_service.py` / `ASSEMBLY_*` 常量，共 17 个文件）保留 legacy 命名，
  避免纯机械改名引入回归。
- **建议修复阶段**: **UX 重构 Task 8**：代码标识符统一改名（与 TD-L28
  术语统一一并处理），改名后同步更新 3 个测试文件与相关文档。

### TD-L31: ui_constants 缩略图死常量与 WebP 实现不符 ✅ 已修复（UX 重构 Task 6）

- **位置**: [ui_constants.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/ui_constants.py) `THUMBNAIL_SIZE` / `THUMBNAIL_FORMAT` / `THUMBNAIL_FILENAME_TEMPLATE`
- **背景**: Stage 5 Task 1a 缩略图缓存已实现为 WebP 多档
  （`{content_unit_id}_{size}.webp`，默认 256），但 ui_constants 仍保留 PNG 单档常量
  （`THUMBNAIL_FORMAT="PNG"`、`THUMBNAIL_FILENAME_TEMPLATE="{unit_id}.png"`、
  `THUMBNAIL_SIZE=64`），全项目无引用。
- **影响范围**: 死代码，误导阅读者。
- **修复（UX 重构 Task 6）**: 删除三个常量（THUMBNAIL_SIZE / THUMBNAIL_FORMAT /
  THUMBNAIL_FILENAME_TEMPLATE），全项目无引用。

### TD-L32: AssemblyService.remove_file 死代码 ✅ 已修复（UX 重构 Task 6）

- **位置**: [assembly_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/assembly_service.py) `remove_file`
- **背景**: UX 重构 Phase 1 Task 1 Commit 3（L2 提前）移除装配面板「移除文件」功能时，
  UI/回调/常量已清理，但 `AssemblyService.remove_file` 方法及对应测试
  （test_assembly_service.py）保留未删除，UI 层已无调用方。
- **影响范围**: 死代码，维护成本。
- **修复（UX 重构 Task 6）**: 删除 `remove_file` 方法及 test_assembly_service.py
  对应测试。

### TD-L33: 代码注释遗留"浏览/整理模式"描述 ✅ 已修复（UX 重构 Task 6）

- **位置**: [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py) /
  [search_dialog.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/search_dialog.py) /
  [tag_filter.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/tag_filter.py) /
  [metadata_panel.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/metadata_panel.py) 等 docstring 与注释
- **背景**: UX 重构 Phase 1 移除双模式后，部分代码注释仍描述"浏览模式/整理模式"
  行为（如 search_dialog "Q5=C：整理模式下不跳转"），与当前单面板行为不符。
- **影响范围**: 认知负担，不影响正确性。
- **修复（UX 重构 Task 6）**: 清理 main_window / search_dialog / tag_filter /
  metadata_panel / folder_tree_model / assembly_service / domain.models 中
  遗留的"浏览/整理模式"注释。

### TD-M37: 缩略图 Coordinator 生成链路未接入 UI

- **位置**: [thumbnail_coordinator.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/thumbnail_coordinator.py) `request_thumbnail` / [card_list_model.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/card_list_model.py) / [metadata_panel.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/metadata_panel.py)
- **背景**: Stage 5 Task 1a 实现了 WebP 多档磁盘缓存基础设施，但当前 UI 未接入：
  `request_thumbnail` 无生产调用方；卡片视图与元数据面板直接 QPixmap 加载原图并
  内存缓存；FileListModel 使用 Qt 标准图标。磁盘缩略图缓存仅由测试链路与启动 GC 触及。
- **影响范围**: 磁盘缓存未发挥作用（原图每次会话重新加载）；不影响正确性。
- **推荐修复方案**: 接入 Coordinator 链路（卡片视图按 icon_size 请求 256/512 档），
  或按需简化缓存体系；需产品确认。
- **建议修复阶段**: **UX 重构 Task 8**（UI 美化时）或单独决策。

### TD-M38: MainWindow 薄委托与文件操作编排待进一步拆分

- **位置**: [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py)
- **背景**: UX 重构 Task 7 已拆出 TransactionScope / ScanController / AssemblyController /
  MetadataView（核心逻辑与状态迁出），但 MainWindow 仍约 3800 行 / 149 方法：
  1. 保留的薄委托方法（_bind_assembly_* / _follow_middle_selection_after_unpin /
     _refresh_assembly_if_affected 等）可删除、改为直接调用控制器；
  2. 文件操作编排（创建 Mod 组 / 重命名 / 删除 / 复制剪切粘贴 / 移动到 / 冲突解决）、
     右键菜单构建、快捷键 handler、目录导航/视图状态等大块逻辑仍留在 MainWindow。
- **影响范围**: 可维护性；任何 UI 改动仍需在大文件中找上下文。
- **推荐修复方案**: 下个阶段单独小任务：先删除薄委托（对测试/回调无影响），
  再按域拆出 FileOpsController（文件操作编排）与 NavigationView（目录导航/视图状态），
  MainWindow 收敛为布局 + 组合根。
- **建议修复阶段**: **Task 8（UI 美化）之后或与其并行**（用户确认，2026-08-02）。

---

## 处理优先级建议

1. ~~**阶段 3 开发前优先处理**（影响安全/正确性）~~：
   - ~~TD-H6（SQL LIKE 未转义，数据正确性）~~ ✅ 已修复
   - ~~TD-H4 + TD-H5（线程竞态，可致崩溃）~~ ✅ 已修复

2. ~~**阶段 4 开发前优先处理**（影响正确性）~~ ✅ 已修复（v0.16.0）：
   - ~~TD-H7（list_by_path_prefix 分隔符分歧漏匹配，已收敛为 normalized 接口）~~ ✅
   - ~~TD-H8（folder_cache 同步吞异常导致部分提交态，已改为抛 FileOperationError 触发上层回滚）~~ ✅
   - **结论**：截至 v0.16.0，无阻塞 Stage 4 启动的 High 级别技术债。

3. ~~**阶段 4 开发中视情况处理**~~（Stage 4.5 已修复 TD-H2）：
   - TD-H3（UI 冻结，影响基本可用性）
   - ~~TD-H2（扫描事务边界）~~ ✅ 已修复（Stage 4.5）
   - TD-M17（连接泄漏，影响测试稳定性）

4. ~~**阶段 4 中期建议处理**~~（部分已修复）：
   - TD-M21（MainWindow God Object 拆分，加搜索/标签 UI 前先拆分）
   - ~~TD-M25（except Exception 吞掉编程错误，加标签/评分功能前收窄）~~ ✅ 已修复（Stage 4 Task 0）
   - TD-M26（MainWindow 集成测试，与拆分同步进行）
   - ~~TD-L20（删除旧 list_by_path_prefix，确认无外部调用后）~~ ✅ 已修复（Stage 4 Task 0）

5. ~~**Stage 5 前/Stage 5 中处理**~~（Stage 4.5 已修复 TD-M22 + TD-L18）：
   - ~~TD-M22（folder_cache 同步辅助逻辑抽公共 helper，避免 undo 路径复制粘贴 4 份）~~ ✅ 已修复（Stage 4.5）
   - ~~TD-L18（AssemblyService._sync_folder_mtime 策略统一，与 TD-M22 一并处理）~~ ✅ 已修复（Stage 4.5）
   - TD-H10（FileOperationService 分层归属，Stage 5 文件操作重构时处理）
   - TD-M24（rename_as_cover 9999 上限错误类型语义错位，Stage 5 错误提示体系统一时处理）
   - ~~TD-L19（OperationHistory.can_undo 恒为 True，Stage 5 实现 undo 时校验）~~ ✅ 已修复（Stage 5 Task 0）
   - TD-M27（SQLite 并发写测试，Stage 5 undo 前验证并发安全）

5a. **Stage 5 Task 0 已修复**（为 undo 与文件操作做基础）：
   - ~~TD-H1（OperationHistory 一致性校验，影响 undo 安全性）~~ ✅ 已修复（Stage 5 Task 0）
   - ~~TD-L19（OperationHistory.can_undo 恒为 True，Stage 5 实现 undo 时校验）~~ ✅ 已修复（Stage 5 Task 0）
   - ~~TD-M11（_commit 数据库提交失败无 UI 反馈，Stage 5 频繁写操作需用户反馈）~~ ✅ 已修复（Stage 5 Task 0）

5b. ~~**Stage 5 Code Review 已修复**~~（v0.41.0，详见 CHANGELOG）：
   - ~~TD-H9（content_unit.path UNIQUE 绕过 make_path_key，v11 schema 新增 path_key 列）~~ ✅
   - ~~TD-H11（operation_history.source_path 在 undo 记录中存 ID，D4 决策撤销不再写新记录）~~ ✅
   - ~~TD-L6（logging_setup.py docstring 路径名过时）~~ ✅
   - ~~TD-L10（_on_scan_started 与 _begin_scanning 状态设置重复）~~ ✅
   - ~~TD-L11（file_classify.py 死代码）~~ ✅
   - ~~TD-L12（conftest.py sample_mod_tree fixture 死代码）~~ ✅
   - ~~TD-L15（init_db schema_version 初始化与首次迁移同事务）~~ ✅
   - ~~TD-L17（test_managed_root_service.py 用 __import__ hack）~~ ✅
   - ~~TD-L22（ContentUnit.status 重构为 is_marked: bool，D2/D3 决策 schema v11）~~ ✅
   - ~~TD-M1（ScanSummary.success 恒返回 True）~~ ✅
   - ~~TD-M3（application.errors.ScanError 死代码）~~ ✅
   - ~~TD-M4（FolderTreeService.list_root_nodes 类型信息丢失）~~ ✅
   - ~~TD-M18（误导性测试声称 delete/remove_root 自提交）~~ ✅
   - ~~TD-M19（FolderCacheRepository.upsert_mtime 的 path 参数未使用）~~ ✅
   - ~~TD-M20（test_content_service.py 局部 fixture 遮蔽 conftest）~~ ✅
   - D1 决策落地：ModGroupService → ContentUnitCreationService 代码层重命名（UI 文本保留 "Mod 组"）
   - M12 冗余索引清理（5 个对 UNIQUE/复合主键的冗余索引删除）
   - M13 Domain 校验扩展（ContentUnit.content_type / is_marked 类型校验）
   - M10 事务边界修正（init_db v0 基线与首次迁移分属独立事务）
   - 文档同步：architecture.md 更新到 schema v11；search_service.py Q2=A→Q2=B 注释修正

6. **UI 重构版本处理**（用户决策：单独开分支）：
   - **Task 6 先行**（数据库与死代码清理）：
     - TD-L31（ui_constants 缩略图死常量）
     - TD-L32（AssemblyService.remove_file 死代码）
     - TD-L33（代码注释遗留"浏览/整理模式"描述，顺带）
   - ~~TD-M21 + TD-M31（MainWindow God Object 拆分 + 业务逻辑泄漏）~~ ✅ 进行中（Task 7 控制器拆分完成，MainWindow 保留薄委托）
   - ~~TD-H10 + TD-L25（FileOperationService 分层迁移 + helper 私有访问）~~ ✅ 已修复（Task 7 Commit 2）
   - TD-M26（MainWindow 集成测试，与拆分同步）— 部分落地（test_scan_controller.py）
   - ~~TD-M36（FileListView 统一，与拆分同步）~~ ✅ 已修复（Task 7 Commit 2）
   - ~~TD-M35（rename/move 跨盘异常类型统一）~~ ✅ 已修复（Task 7 Commit 2）
   - TD-L24（FileEntry 类名与注释不一致）
   - TD-L28（UI 中"目录"和"文件夹"混用）
   - TD-L30（装配面板命名"文件夹透视器"待用户确认）
   - UI 重构清单 8 项（详见 open-questions.md）

7. **Stage 6 前处理**（数据一致性版本）：
   - TD-H12（文件操作与 DB 事务不一致窗口未补偿）
   - TD-M32（UndoService 安全校验无 size/mtime 比对）
   - TD-M33（mark_undone 失败可能导致重复撤销）

8. **后续迭代批量处理**（非阻塞，性能优化为主）：
   - TD-M23（folder_cache 同步多次 list_all() 全表扫描）
   - TD-M28（7 处 N+1 查询，Stage 5 中期与 TD-H3 一并处理）
   - TD-M29（测试组织风格不统一，Stage 5 中期）
   - TD-M30（spec §10.3 "最近常用置顶"，需用户决策）
   - TD-L21（UI 样式表硬编码颜色，暗色模式时处理）
   - TD-M34（覆盖模式子节点 folder_cache 不立即重建）
   - TD-L23（content_unit.content_type 默认 'mod' 与实体名不一致）
   - TD-L26（time 字段后缀不统一）
   - TD-L27（ClipboardEntry.timestamp 字段未使用）
   - TD-L29（已修复，仅记录 content_type 扩展约定）
   - 其余 Medium/Low 级别的代码质量/测试覆盖问题
