# Technical Debt 记录

> 本文档记录 Code Review 中发现但未在第一批修复的问题。
> 第一批已修复：C1-C4、H2、H5、H6、M8、M12（详见 CHANGELOG v0.15.0）。
> 第二批已修复：TD-H4、TD-H5、TD-H6（详见 CHANGELOG v0.15.1）。
> 以下问题按严重级别排列，将在阶段 3 及后续迭代中逐步处理。

---

## High（影响正确性、稳定性、可用性）

### TD-H1: OperationHistory 缺少 target_path 与 operation_type 一致性校验

- **位置**: [models.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/domain/models.py) `OperationHistory.__post_init__`
- **问题**: `move`/`rename`/`new_folder` 操作允许 `target_path=None`，`delete` 操作允许 `target_path` 非 None，无一致性校验。一旦 `FileOperationService` 实现，撤销链路会数据不一致。
- **建议**: 在 `__post_init__` 增加操作类型与 target_path 的一致性校验。

### TD-H2: ScanService 持久化缺少事务边界与异常隔离

- **位置**: [scan_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/scan_service.py) `_persist_scan_result`
- **问题**: 写入 `folder_cache` 与 `content_unit` 两张表既未显式开启事务也未 commit。H5 修复后 Repository 不自提交，但 ScanService 未持有 connection 引用，无法控制事务边界。中途异常会导致部分提交或全部回滚，行为不可预测。
- **建议**: 给 ScanService 注入 connection（或 Unit of Work），用 `with conn:` 包裹持久化逻辑，收窄异常捕获。

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

### TD-H7: list_by_path_prefix 的 LIKE 转义在 Windows 反斜杠路径下 broken

- **位置**: [content_unit.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/repositories/content_unit.py) `list_by_path_prefix`
- **问题**: TD-H6 修复了 LIKE 通配符转义，但 Windows 下 `os.sep = "\\"`，构造 `full_prefix = prefix + sep` 后做 `replace("\\", "\\\\")` 会让每个反斜杠翻倍，LIKE 模式期望路径中两个连续反斜杠，但实际 path 只有一个反斜杠，**子路径无法匹配**。原测试用 POSIX 路径（`/mods/armor`）掩盖了此 bug。
- **影响**: 阶段 3 Task 5 第二轮验收时暴露——`QuickInsertService._cleanup_stale_content_units` 原实现依赖 `list_by_path_prefix` 清理目标路径子项旧记录，Windows 下子路径匹配失败，导致 `update` 时 UNIQUE 冲突。
- **临时规避（阶段 3 Task 5 已实施）**: `QuickInsertService._cleanup_stale_content_units` 改用 `list_all + make_path_key` 归一化比较，不依赖 SQL LIKE（符合 AGENTS 规则 9）。
- **建议**: 修复 `list_by_path_prefix` 的 LIKE 转义逻辑（或改为 `list_all + make_path_key` 归一化比较），并补充 Windows 路径测试覆盖。当前 `list_by_path_prefix` 仍被 `ContentService` 使用，潜在影响其他功能。

---

## Medium（影响可维护性、性能、测试质量）

### TD-M1: ScanSummary.success 恒返回 True

- **位置**: [scan_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/scan_service.py) `ScanSummary.success`
- **问题**: 属性实现为 `return True`，docstring 暗示会基于 errors 判定，具有误导性。
- **建议**: 实现为 `return not self.has_errors`，或删除该属性。

### TD-M2: ScanService 访问 FileScanner 私有方法 _mtime_equal

- **位置**: [scan_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/scan_service.py) 第 176 行
- **问题**: Application 层直接调用 Infrastructure 层的下划线前缀方法，封装泄漏。
- **建议**: 将 `_mtime_equal` 改为 public `mtime_equal`，或抽到共享工具模块。

### TD-M3: application.errors.ScanError 死代码

- **位置**: [errors.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/errors.py) 第 25-26 行
- **问题**: `ScanError` 异常类从未被 raise/except/import，与 `file_scanner.ScanError` dataclass 同名易混淆。
- **建议**: 删除，或加 TODO 注释说明保留意图。

### TD-M4: FolderTreeService.list_root_nodes 类型信息丢失

- **位置**: [folder_tree_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/folder_tree_service.py) 第 92 行
- **问题**: `fc_root_map: dict[str, object]` 应为 `dict[str, FolderCache]`，访问 `.id` 需 `# type: ignore`。
- **建议**: 改为正确类型标注，移除 type: ignore。

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

### TD-M11: _commit 数据库提交失败无 UI 反馈

- **位置**: [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py) `_commit`
- **问题**: 提交失败仅 `logger.exception`，用户不知操作未持久化。违反 AGENTS.md"所有异常必须转换为用户可理解的错误信息"。
- **建议**: 提交失败时通过 QMessageBox 或状态栏提示用户。

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

### TD-M18: 误导性测试声称 delete/remove_root 自提交

- **位置**: [test_managed_root_repository.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/tests/test_managed_root_repository.py) `test_delete_commits_without_explicit_commit` / [test_managed_root_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/tests/test_managed_root_service.py) `test_remove_root_persists_without_explicit_commit`
- **问题**: 测试名称和 docstring 声称"自提交"，但实际因 rollback 通过（create 也被回滚）。与 H5 修复后的设计契约冲突，给出虚假保障。
- **建议**: 重写为正确验证事务边界，或删除。

### TD-M19: FolderCacheRepository.upsert_mtime 的 path 参数未使用

- **位置**: [folder_cache.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/repositories/folder_cache.py) `upsert_mtime`
- **问题**: `path` 参数声明后从未参与 SQL 或逻辑，调用方误以为 WHERE 用 path 过滤。
- **建议**: 删除 `path` 参数，或加 `AND path = ?` 防御性校验。

### TD-M20: test_content_service.py 局部 fixture 遮蔽 conftest

- **位置**: [test_content_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/tests/test_content_service.py) 第 26-34 行
- **问题**: 局部 `db_connection` fixture 用 `tmp_path / "test.db"` 而非 conftest 的 `temp_app_data` 隔离路径，与项目约定相悖，且与 conftest 完全等价重复。
- **建议**: 删除局部 fixture，使用 conftest 的 `db_connection`。

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

### TD-L6: logging_setup.py docstring 路径名过时

- **位置**: [logging_setup.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/logging_setup.py) 第 3 行
- **问题**: 写 `SkyrimModWorkbench`，实际为 `SkyrimContentWorkbench`。

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

### TD-L10: _on_scan_started 与 _begin_scanning 状态设置重复

- **位置**: [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py) 第 692、709-710 行
- **问题**: 两处都设置 `STATUS_SCANNING`，属冗余。

### TD-L11: file_classify.py 死代码

- **位置**: [file_classify.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/file_classify.py)
- **问题**: `AssetHint` 枚举、`classify_by_extension` 函数、`IMAGE_EXTENSIONS` 常量无外部引用，docstring 引用已不存在的 FileAsset 表。

### TD-L12: conftest.py sample_mod_tree fixture 死代码

- **位置**: [conftest.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/tests/conftest.py) 第 66-103 行
- **问题**: 无任何测试引用，各测试文件都自定义本地 mod_tree fixture。

### TD-L13: conftest.py db_connection 冗余设置 row_factory

- **位置**: [conftest.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/tests/conftest.py) 第 59 行
- **问题**: `get_connection` 已设置 row_factory（M12 修复），conftest 再次设置是多余操作。

### TD-L14: test_migrations.py 用 f-string 拼接 SQL

- **位置**: [test_migrations.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/tests/test_migrations.py) 第 411-415 行
- **问题**: 虽无注入风险，但破坏参数化查询风格一致性。

### TD-L15: init_db schema_version 初始化与首次迁移同事务

- **位置**: [db.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/db.py) 第 72-89 行
- **问题**: 建表 + v0 基线 INSERT 实际和 v0→v1 迁移落在同一事务，与 docstring 声称的"每步迁移在独立事务中执行"不一致。

### TD-L16: test_migrations.py 三个测试用 tmp_path 而非 temp_app_data

- **位置**: [test_migrations.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/tests/test_migrations.py) 第 491、521、529 行
- **问题**: 与 test_db.py 的 fixture 体系不一致，缺少类型标注。

### TD-L17: test_managed_root_service.py 用 __import__ hack

- **位置**: [test_managed_root_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/tests/test_managed_root_service.py) 第 352、366 行
- **问题**: `__import__("sqlite3").Row` 而非顶部 `import sqlite3`，可读性差。M12 修复后该设置本身也冗余。

---

## 处理优先级建议

1. ~~**阶段 3 开发前优先处理**（影响安全/正确性）~~：
   - ~~TD-H6（SQL LIKE 未转义，数据正确性）~~ ✅ 已修复
   - ~~TD-H4 + TD-H5（线程竞态，可致崩溃）~~ ✅ 已修复

2. **阶段 4 开发前优先处理**（影响正确性）：
   - TD-H7（list_by_path_prefix Windows 下 LIKE 转义 broken，QuickInsertService 已规避但 ContentService 仍使用，潜在影响标签筛选/元数据加载）

3. **阶段 4 开发中视情况处理**（影响性能/可用性）：
   - TD-H3（UI 冻结，影响基本可用性）
   - TD-H2（扫描事务边界）
   - TD-M17（连接泄漏，影响测试稳定性）

4. **后续迭代批量处理**：
   - Medium 级别的代码质量/测试覆盖问题
   - Low 级别的风格/命名/文档问题
