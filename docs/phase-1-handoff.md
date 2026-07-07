# 阶段 1 交接报告

本报告仅记录 Skyrim Mod Workbench 阶段 0 + 阶段 1 完成后的已验证现状，不规划阶段 2。
所有陈述基于当前代码、测试、Git 历史与文档。报告生成日期：2026-07-07。

---

## 1. 当前可运行功能及用户可见行为

### 1.1 可启动的桌面应用

入口 [src/app/main.py](../src/app/main.py)，命令 `python -m app.main`。

启动顺序（`main()` 函数）：

1. `ensure_app_directories()` 创建应用数据目录。
2. `setup_logging()` 初始化日志。
3. `init_db(get_app_db_path())` 初始化 SQLite。
4. 启动 Qt 事件循环，显示主窗口。

用户可见行为：

- 弹出标题为 "Skyrim Mod Workbench" 的窗口，尺寸 1024×720，中央为空白 `QWidget` 占位。
- 无三栏布局、无目录树、无卡片、无按钮、无菜单。
- `%LOCALAPPDATA%\SkyrimModWorkbench\` 自动创建，含 `app.db`、`thumbnails\`、`exports\`、`logs\app.log`。
- 任何启动步骤失败会向 stderr 输出中文错误信息并返回退出码 1。

### 1.2 阶段 1 已实现的能力（无 UI，仅 API）

| 能力 | 入口 | 说明 |
|---|---|---|
| 数据库初始化 | `init_db(db_path)` | schema_version=1，幂等，迁移驱动 |
| 路径标准化 | `make_path_key(path)` | normcase + normpath（A2） |
| 只读扫描 | `FileScanner.scan(root)` / `scan_many(roots)` | 递归扫描，产出 `ScanResult` |
| 扫描持久化 | `persist_scan_result(...)` | 写 FolderNode / FileAsset，path_key 去重 |
| Mod 条目组装 | `ModAssemblyService` | 创建 / 关联成员 / 设置角色与封面 / 查询 / 编辑 / 解除 |
| 文件移动预演 | `FileOperationService.plan_move` | 生成 `MovePlan` + 持久化 `OperationLog(planned)` |
| 文件移动执行 | `FileOperationService.execute_move` | 同盘 rename / 跨盘 copy2+unlink |
| 撤销预演 | `FileOperationService.plan_undo` | B1/B2 安全校验 |
| 撤销执行 | `FileOperationService.execute_undo` | 反向移动 + status=undone |

以上能力均无 UI 调用方，仅由测试覆盖。阶段 1 验收场景（本体 + 汉化 + 预览图组成同一 ModItem，预演并执行整体移动，安全撤销，阻止危险操作）全部在 `tests/test_file_operation_service.py` 与 `tests/test_mod_assembly_service.py` 中以自动化测试验证。

---

## 2. 目录结构与主要模块职责

### 2.1 顶层目录

```text
Skyrim-Content-Workbench/
├── AGENTS.md                  # 工作规则（12 条不可违反规则）
├── CHANGELOG.md               # SemVer 变更日志，[0.1.0]–[0.5.0]
├── LICENSE                    # MIT
├── README.md                  # 占位（仅 1 行）
├── pyproject.toml             # 构建与工具配置
├── docs/
│   ├── architecture.md
│   ├── open-questions.md
│   ├── phase-1-handoff.md     # 本文件
│   ├── progress.md
│   ├── roadmap.md
│   └── spec.md
├── src/
│   ├── app/                   # 应用入口与系统层
│   ├── application/           # 应用服务
│   ├── domain/                # 领域模型
│   └── infrastructure/        # 基础设施
└── tests/                     # pytest 测试套件
```

### 2.2 模块职责

#### `src/app/`（系统层）

| 文件 | 职责 |
|---|---|
| [main.py](../src/app/main.py) | 应用入口；启动顺序编排；异常转用户可读错误 |
| [app_paths.py](../src/app/app_paths.py) | 应用数据目录路径；`ensure_app_directories()` 创建目录 |
| [logging_setup.py](../src/app/logging_setup.py) | RotatingFileHandler，UTF-8，`logs/app.log` |
| [main_window.py](../src/app/main_window.py) | 主窗口；阶段 1 仅占位空白窗口 |

#### `src/domain/`（领域层）

| 文件 | 职责 |
|---|---|
| [models.py](../src/domain/models.py) | 4 个 dataclass + 5 个 enum + `__post_init__` 校验；纯数据载体，不访问 DB 与文件系统 |

#### `src/application/`（应用服务层）

| 文件 | 职责 |
|---|---|
| [errors.py](../src/application/errors.py) | `ApplicationError` / `ModItemNotFoundError` / `FileAssetNotFoundError` / `MemberLimitError` / `DuplicateMemberError` |
| [mod_assembly_service.py](../src/application/mod_assembly_service.py) | ModItem 组装；不访问文件系统；不自动推断成员关系 |

#### `src/infrastructure/`（基础设施层）

| 文件 | 职责 |
|---|---|
| [db.py](../src/infrastructure/db.py) | SQLite 连接（外键 + WAL）；迁移驱动 init_db |
| [migrations.py](../src/infrastructure/migrations.py) | `MIGRATIONS` 注册表 + `migrate_v0_to_v1` |
| [path_utils.py](../src/infrastructure/path_utils.py) | `make_path_key`；不访问文件系统 |
| [file_classify.py](../src/infrastructure/file_classify.py) | `AssetHint` 枚举 + 扩展名集合 + `classify_by_extension`；仅供扫描器内部使用 |
| [file_scanner.py](../src/infrastructure/file_scanner.py) | 只读扫描器 + `persist_scan_result` |
| [file_operation_service.py](../src/infrastructure/file_operation_service.py) | 唯一允许修改用户文件位置的模块 |
| [repositories/errors.py](../src/infrastructure/repositories/errors.py) | `RepositoryError` / `NotFoundError` / `ConstraintViolationError` |
| [repositories/mod_item.py](../src/infrastructure/repositories/mod_item.py) | ModItem CRUD |
| [repositories/file_asset.py](../src/infrastructure/repositories/file_asset.py) | FileAsset CRUD |
| [repositories/folder_node.py](../src/infrastructure/repositories/folder_node.py) | FolderNode CRUD |
| [repositories/operation_log.py](../src/infrastructure/repositories/operation_log.py) | OperationLog CRUD |

---

## 3. 数据模型、持久化位置与关键接口

### 3.1 持久化位置

- **应用数据库**：`%LOCALAPPDATA%\SkyrimModWorkbench\app.db`（SQLite，WAL 模式）。
- **日志**：`%LOCALAPPDATA%\SkyrimModWorkbench\logs\app.log`（滚动，2MB×3，UTF-8）。
- **预留目录**：`thumbnails\`（未写入）、`exports\`（未写入）。
- **用户 Mod 文件**：不被复制到应用数据目录（spec §7.15，arch §4）。

### 3.2 数据库 Schema（v1）

由 [migrations.py](../src/infrastructure/migrations.py) 的 `migrate_v0_to_v1` 创建，4 张业务表 + 4 个索引 + CHECK 约束。

| 表 | 主键 | 关键约束 | 依据 |
|---|---|---|---|
| `mod_item` | `id TEXT` | `category_folder_id` FK → `folder_node(id)`；`cover_asset_id` FK → `file_asset(id)`；`tags TEXT` 默认 `'[]'` | spec §6.1 |
| `file_asset` | `id TEXT` | `mod_item_id` FK → `mod_item(id)`；`path_key TEXT UNIQUE`；`asset_kind CHECK IN ('file','folder')`；`role CHECK IN (6 种)` | spec §6.2 |
| `folder_node` | `id TEXT` | `path_key TEXT UNIQUE`；`parent_id` FK 自引用；`is_managed_root CHECK IN (0,1)` | spec §6.3 |
| `operation_log` | `id TEXT` | `status CHECK IN ('planned','confirmed','completed','failed','undone')`；`conflict_policy CHECK IN ('ask')`；`operation_type` 无 CHECK | spec §6.4 |

索引：`idx_file_asset_mod_item_id`、`idx_mod_item_category_folder_id`、`idx_folder_node_parent_id`、`idx_operation_log_status`。

未引入的列（待确认）：
- `mod_item.status`（Q1）
- `file_asset.batch_id`（Q2）

### 3.3 领域模型（dataclass）

[src/domain/models.py](../src/domain/models.py)：

- `ModItem`：id, created_at, updated_at, display_name, description, source_url, category_folder_id, tags(set[str]), cover_asset_id
- `FileAsset`：id, real_path, path_key, filename, asset_kind, role, size_bytes, modified_at, imported_at, extension, mod_item_id
- `FolderNode`：id, real_path, path_key, created_at, updated_at, parent_id, display_name, is_managed_root
- `OperationLog`：id, operation_type, status, conflict_policy, created_at, affected_asset_ids(list), source_paths(list), target_paths(list), completed_at, undo_payload, error_message

枚举：
- `AssetKind`：FILE / FOLDER
- `FileRole`：MAIN_MOD / TRANSLATION / PREVIEW / README / OPTIONAL_FILE / UNKNOWN
- `OperationStatus`：PLANNED / CONFIRMED / COMPLETED / FAILED / UNDONE
- `ConflictPolicy`：ASK（阶段 1 仅此值）
- `OperationType`：MOVE / UNDO

所有 dataclass 在 `__post_init__` 做轻量校验（非空、enum 类型、set/list 类型、非负 size）。

### 3.4 关键接口

#### Repository 层（CRUD）

| Repository | 方法 |
|---|---|
| `ModItemRepository` | create / get_by_id / list_all / update |
| `FileAssetRepository` | create / get_by_id / list_by_mod_item / list_unassociated / update |
| `FolderNodeRepository` | create / get_by_id / list_by_parent / list_managed_roots / update |
| `OperationLogRepository` | create / get_by_id / list_by_status / update |

Repository 不访问文件系统；list 字段（tags / affected_asset_ids / source_paths / target_paths）序列化为 JSON 数组。

#### 应用服务

`ModAssemblyService`：
- `create_mod_item(display_name, description, source_url, category_folder_id, tags) -> ModItem`
- `add_member(mod_item_id, file_asset_id, role) -> FileAsset`
- `set_member_role(mod_item_id, file_asset_id, role) -> FileAsset`
- `set_cover(mod_item_id, file_asset_id) -> ModItem`（要求 role=PREVIEW）
- `get_mod_item / get_members / get_mod_item_with_members / list_mod_items`
- `update_mod_item(mod_item_id, **fields)`（可更新 display_name/description/source_url/category_folder_id/tags）
- `remove_member(mod_item_id, file_asset_id) -> FileAsset`（mod_item_id=None, role=UNKNOWN；若为 cover 同步清除）
- `ROLE_LIMITS`：MAIN_MOD≤1, README≤1，其他不限制（Q19）

#### 文件操作服务

`FileOperationService`：
- `plan_move(mod_item_id, target_folder_id) -> MovePlan`
- `execute_move(plan_id) -> OperationResult`
- `plan_undo(operation_id) -> UndoPlan`
- `execute_undo(undo_plan_id) -> OperationResult`

数据类：`MovePlan` / `MovePlanEntry` / `UndoPlan` / `UndoPlanEntry` / `OperationResult`。

`undo_payload` JSON 结构（Q14，由 Task 5 定义）：

```json
{
  "version": 1,
  "members": [
    {"asset_id": "...", "src_path": "...", "dst_path": "...", "size_bytes": 100, "mtime_iso": "2026-07-07T00:00:00Z"}
  ]
}
```

---

## 4. 用户文件访问、扫描、索引行为与安全边界

### 4.1 扫描行为

入口：`FileScanner.scan(root: Path) -> ScanResult` / `scan_many(roots: list[Path])`。

- 递归扫描，所有子目录生成 `ScannedFileEntry`（含根目录本身）。
- 仅使用只读文件系统 API：`Path.iterdir` / `is_dir(follow_symlinks=False)` / `is_symlink()` / `stat(follow_symlinks=False)` / `suffix`。
- 符号链接与 junction：不跟随，按文件处理（`asset_hint=OTHER`）。
- 异常处理：`PermissionError` / `OSError` / `stat` 失败记入 `ScanError`，不中断整次扫描。
- 根目录不存在或非目录：返回仅含错误的 `ScanResult`。
- 扩展名识别：`IMAGE_EXTENSIONS`（jpg/png/webp/gif/bmp/tif/tiff/ico/tga/dds）、`ARCHIVE_EXTENSIONS`（7z/zip/rar/001/r00-r05/tar/gz/bz2/xz/tgz/tbz2/txz）。分类结果（`AssetHint`）不持久化。
- 支持中文路径；mtime 转 ISO 8601 UTC 字符串。

### 4.2 持久化行为

`persist_scan_result(scan_result, folder_repo, file_repo)`：

- FolderNode 按 `real_path` 字符串长度排序，确保父先于子插入。
- path_key 冲突时跳过（A3 重叠目录去重）。
- 根目录 `is_managed_root=True`，其余 False。
- `parent_id` 通过 `make_path_key(parent_path)` 查找已插入节点。
- FileAsset `role` 默认 `UNKNOWN`（角色由用户在 Task 4 手动指定）。
- 预加载所有现有 FolderNode 到内存映射（`_preload_existing_folders` 递归加载）。

### 4.3 文件操作行为

`FileOperationService` 是唯一允许修改用户文件位置的模块（arch §6）。

- `plan_move`：检查每个成员的源存在性、目标目录存在性、目标重名（B3 重名即阻止）、目标目录可写性、目标是否为源自身或子目录（spec §7.7）、是否跨盘。持久化 `OperationLog(status=PLANNED)`。
- `execute_move`：planned → confirmed → 同盘 `Path.rename`（原子）/ 跨盘 `shutil.copy2 + Path.unlink` → completed/failed。单成员失败不中断其他成员（spec §7.12）。写 `undo_payload`（仅记录成功成员）。
- `plan_undo`：B1 不安全即整体阻止；B2 校验目标文件 size + mtime 与 `undo_payload` 记录一致。
- `execute_undo`：先重新 `plan_undo` 验证，不安全则直接返回失败；安全则反向移动 + status=undone。

### 4.4 明确保证的安全边界

依据 AGENTS.md 12 条规则与 spec §7：

1. **不上传**：全 local-first，无网络代码。
2. **不自动操作**：所有移动经 `plan_move` + 用户确认 + `execute_move`；无自动删除/覆盖/重命名。
3. **UI 不直接操作文件**：仅 `FileOperationService` 可移动文件；UI 层（阶段 2+）不直接调用 `shutil` / `Path.rename`。
4. **预演先行**：`plan_move` 持久化 `OperationLog(planned)` 后才可执行。
5. **安全撤销**：B1 不安全阻止 + B2 size+mtime 校验。
6. **不删除用户文件**（spec §7.13）：跨盘 `unlink` 是移动语义的一部分，非删除；测试 `test_execute_move_does_not_delete_user_files` 显式验证。
7. **不修改文件内容**（spec §7.14）：仅 rename / copy2（保留 metadata）。
8. **不修改用户原始图片/压缩包/文档/Mod 内容**（AGENTS 规则 8）。
9. **缩略图缓存不写入用户 Mod 目录**（AGENTS 规则 9）：`thumbnails\` 位于应用数据目录。
10. **中文路径与 UTF-8 JSON**（AGENTS 规则 10）：全链路支持。
11. **不自动分组**（AGENTS 规则 7）：ModAssemblyService 不自动推断成员关系。
12. **扫描只读**：FileScanner 不移动/重命名/删除/修改/打开（读取内容）任何用户文件；测试 `test_scan_*_preserves_files` 验证扫描前后 mtime/size/内容一致。

---

## 5. 测试、运行方式、构建方式与已验证命令

### 5.1 构建与依赖

[pyproject.toml](../pyproject.toml)：

- 构建：`setuptools>=68`，`packages.find` 在 `src/`。
- `requires-python = ">=3.12"`（实际运行环境 Python 3.14.0）。
- 运行依赖：`PySide6>=6.8,<7`（实际 6.11.1）。
- 开发依赖：`pytest>=8.0`（实际 9.1.1）、`ruff>=0.6`（实际 0.15.20）。
- 入口脚本：`skyrim-mod-workbench = "app.main:main"`。
- ruff：line-length=100，target py312，lint select = E/F/W/I/UP/B/SIM；`tests/*` 忽略 S101/E402。
- pytest：`testpaths=["tests"]`，`pythonpath=["src"]`，`addopts="-ra"`。

### 5.2 已验证命令

```powershell
# 安装
pip install -e .

# 静态检查
ruff check src tests
ruff format --check src tests

# 测试
python -m pytest                              # 完整套件
python -m pytest -v                           # 详细
python -m pytest tests/test_file_operation_service.py -v   # 单文件

# 自动修复
ruff check --fix src tests
ruff format src tests

# 启动应用
python -m app.main
```

### 5.3 最近一次验证结果

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 39 files already formatted
- `python -m pytest tests/test_file_operation_service.py -v` → 23 passed
- `python -m pytest`（完整套件）→ 165 passed, 2 skipped

### 5.4 测试覆盖

测试文件（15 个）位于 `tests/`：

| 测试文件 | 覆盖范围 |
|---|---|
| test_app_paths.py | 应用数据目录创建 |
| test_db.py | schema_version、v0→v1 迁移、外键、Row 工厂 |
| test_domain_models.py | dataclass 校验、enum 类型 |
| test_file_asset_repository.py | CRUD、path_key 唯一、中文路径、未关联素材 |
| test_file_classify.py | 扩展名识别、大小写、多扩展名、点号边界 |
| test_file_operation_service.py | plan_move / execute_move / plan_undo / execute_undo + 中文路径 + 安全限制（23 项） |
| test_file_scanner.py | 扫描、中文路径、符号链接（Windows skip）、权限（Windows skip）、持久化、只读保证 |
| test_folder_node_repository.py | CRUD、父子关系、list_managed_roots |
| test_main_window.py | MainWindow 构造 |
| test_migrations.py | MIGRATIONS 排序、幂等、CHECK 约束 |
| test_mod_assembly_service.py | 创建/关联/角色/封面/查询/编辑/解除（32 项） |
| test_mod_item_repository.py | CRUD、中文标签往返 |
| test_operation_log_repository.py | CRUD、状态枚举、conflict_policy 拒绝 overwrite、undo_payload JSON |
| test_path_utils.py | normpath、normcase、中文路径、幂等 |

**测试统计**：165 passed, 2 skipped。

**Skipped 测试**（Windows 平台限制）：
- `test_scan_permission_denied_directory`：`chmod 000` 在 Windows 不可靠。
- `test_scan_symlink_not_followed`：创建符号链接需管理员权限或开发者模式。

逻辑已实现，可在 POSIX 平台或具备权限的 Windows 环境验证。

### 5.5 测试安全保证

- 所有涉及真实文件的测试使用 pytest `tmp_path` 临时目录。
- [tests/conftest.py](../tests/conftest.py) 的 `temp_app_data` fixture 把 `LOCALAPPDATA` 指向临时目录，不写入真实用户目录。
- `sample_mod_tree` fixture 构造混合中英文目录树（护甲/Weapons/空目录等）。
- Task 3 测试显式验证扫描前后文件 mtime/size/内容一致。
- Task 5 测试显式验证 `test_execute_move_does_not_delete_user_files`（spec §7.13）。

---

## 6. 已知限制、技术债、临时实现、失败路径

### 6.1 已知限制

- **无 UI**：阶段 1 所有能力仅 API 与测试，无用户图形界面。
- **无根目录配置持久化**：`FileScanner` 接受调用方传入根目录，但未持久化到 DB（progress.md 标记 🔶，配置 UI 在阶段 2）。
- **无搜索**：SQLite FTS5 未实现（阶段 3）。
- **无缩略图**：`thumbnails\` 目录已创建但无写入逻辑（阶段 2+）。
- **无 AI JSON**：导入导出未实现（阶段 3）。
- **无压缩包内容解析**（spec §4）。
- **无文件监听 / 增量扫描**（Q17/Q18）。
- **无 Windows 打包**（阶段 6）。

### 6.2 技术债与临时实现

1. **`pyproject.toml` 版本号未更新**：`version = "0.1.0"`，但 CHANGELOG 已到 `[0.5.0]`。setuptools 元数据落后于实际版本。
2. **`README.md` 仅 1 行占位**：未提供安装说明、数据位置说明、隐私说明（阶段 6 范围）。
3. **`architecture.md` 列出 Pillow**（§1），但 `pyproject.toml` 未声明该依赖，阶段 1 未实现缩略图。Pillow 依赖需在阶段 2 缩略图服务实现前添加。
4. **`file_scanner.py` 的 `_preload_existing_folders` 递归加载所有 FolderNode**：大规模目录树时可能性能问题。注释中已标注"FolderNodeRepository 未提供 list_all，这里递归从根开始加载"。
5. **`file_scanner.py` 的 `_make_entry` 注释混乱**：docstring 说"调用方需记录错误"，但实际返回 None 且调用方未记录 stat 失败的错误（仅 `is_symlink` / `is_dir` 失败才记录）。stat 失败的条目会静默丢失。
6. **`file_operation_service.py` 的 `execute_move` 不重新预演**：从 OperationLog 读取 source/target 直接执行；执行前再次检查源存在 + 目标重名，状态变化记为该成员失败。这是有意设计，但意味着预演后到执行前文件被外部改动时，预演结果与执行结果可能不一致。
7. **跨盘移动测试覆盖有限**：单盘测试环境无法构造真实跨盘场景；`_is_cross_drive` 的 `os.path.splitdrive` 回退逻辑未被真实跨盘测试覆盖。
8. **部分失败不自动回滚（Q20）**：`execute_move` 单成员失败时已成功成员不回滚，OperationLog=failed，用户需手动撤销。决策里程碑=阶段 2。
9. **`OperationStatus` 未扩展 `UNDO_BLOCKED`**：plan 描述提到状态机含 undo_blocked，但 models.py 未定义。当前用 status=FAILED + error_message 表示 B1 阻止情况。
10. **`file_asset.py` 的 `list_by_mod_item` 排序**：按 `imported_at` 排序，但 SQL 中未显式 ORDER BY（需确认实现）。

### 6.3 失败路径

| 场景 | 行为 |
|---|---|
| 应用数据目录创建失败 | `main()` 捕获 OSError，stderr 输出中文错误，返回 1 |
| 日志初始化失败 | 同上 |
| 数据库初始化失败 | 捕获 sqlite3.Error，logger.exception 记录，stderr 输出，返回 1 |
| 扫描根目录不存在 | 返回仅含 `ScanError` 的 `ScanResult` |
| 扫描权限不足 | 记入 `ScanError`，继续扫描其他目录 |
| Repository 实体不存在 | 抛 `NotFoundError` |
| Repository 唯一约束冲突 | 抛 `ConstraintViolationError` |
| Repository 其他 SQLite 错误 | 抛 `RepositoryError` |
| ModAssemblyService ModItem 不存在 | 抛 `ModItemNotFoundError` |
| ModAssemblyService FileAsset 不存在 | 抛 `FileAssetNotFoundError` |
| ModAssemblyService 重复关联 | 抛 `DuplicateMemberError` |
| ModAssemblyService 角色超限 | 抛 `MemberLimitError` |
| ModAssemblyService 封面非 PREVIEW | 抛 `ValueError` |
| FileOperationService ModItem/FolderNode 不存在 | 抛 `ValueError` |
| FileOperationService execute_move 状态非 planned | 抛 `ValueError` |
| FileOperationService execute_move 单成员失败 | 该成员记入 failed，其他成员继续；OperationLog=failed |
| FileOperationService plan_undo 不安全 | 返回 `UndoPlan(can_execute=False)` |
| FileOperationService execute_undo 不安全 | 返回 `OperationResult(success=False)` |

---

## 7. 与 spec.md、architecture.md、roadmap.md 的差异

### 7.1 与 spec.md 的差异

| spec 条目 | 现状 | 差异类型 |
|---|---|---|
| §6.1 ModItem.status 待确认 | 未实现 | 待确认项 Q1，未引入列 |
| §6.2 FileAsset.batch_id 待确认 | 未实现 | 待确认项 Q2，未引入列 |
| §6.4 OperationLog.operation_type | 代码仅 {move, undo}，DB 无 CHECK | 待确认项 Q16（Task 5 关闭） |
| §6.4 undo_payload 结构 | Task 5 定义 | Q14 已关闭 |
| §7 文件操作安全要求 | 全部实现 | 一致 |
| §8 UI 三栏布局 | 未实现 | 阶段 2 范围 |
| §9 搜索 | 未实现 | 阶段 3 范围 |
| §10 预览图 | 未实现 | 阶段 2+ 范围 |
| §11 AI JSON | 未实现 | 阶段 3 范围 |

### 7.2 与 architecture.md 的差异

| arch 条目 | 现状 | 差异类型 |
|---|---|---|
| §1 技术选型列出 Pillow | `pyproject.toml` 未声明 | 待阶段 2 缩略图服务前添加 |
| §1 列出 PyInstaller/Nuitka | 未实现 | 阶段 6 范围 |
| §2 分层原则 | 完全遵循 | 一致 |
| §3 模块职责 | 完全遵循 | 一致 |
| §4 数据存储位置 | 完全遵循 | 一致 |
| §5 路径与 Unicode | 完全遵循（A2 已落实） | 一致 |
| §6 文件操作服务接口 | `plan_move`/`execute_move`/`plan_undo`/`execute_undo` 全部实现 | 一致 |
| §7 搜索架构（FTS5） | 未实现 | 阶段 3 范围 |
| §8 缩略图架构 | 未实现 | 阶段 2+ 范围 |
| §9 AI JSON 架构 | 未实现 | 阶段 3 范围 |
| §10 测试策略 | 全部优先项已覆盖 | 一致 |

### 7.3 与 roadmap.md 的差异

| roadmap 条目 | 现状 | 差异类型 |
|---|---|---|
| 阶段 0 | ✅ 完成（[0.1.0]） | 一致 |
| 阶段 1 全部 10 项 | 9 项 ✅ + 1 项 🔶 | 见下 |
| 阶段 1 验收 4 项 | 全部 ✅ | 一致 |
| 阶段 2-6 | 未开始 | 一致 |

阶段 1 唯一 🔶 项：「受管理根目录配置」——Task 3 完成 scanner 接口（接受调用方传入根目录），但根目录配置的持久化与 UI 在阶段 2。这是 roadmap 阶段 1 范围 "受管理根目录配置" 的部分完成，已在 progress.md 标注。

---

## 8. Git 状态与阶段 1 commits

### 8.1 当前 Git 状态

- 分支：`master`
- 工作树：clean（`nothing to commit, working tree clean`）
- 与远程关系：`Your branch is ahead of 'origin/master' by 5 commits`（未 push）
- 远程 `origin/master` 仅含初始 `Initial commit`（24d0fd3，仅 LICENSE + README.md）

### 8.2 阶段 0 + 1 相关 commits（按时间顺序）

| commit | 版本 | 主题 | 文件变更 |
|---|---|---|---|
| `24d0fd3` | — | Initial commit | LICENSE + README.md（2 文件） |
| `8376dcb` | [0.1.0] | feat: 完成阶段 0 项目初始化 | 23 文件，+1324 行（含全部 docs、AGENTS.md、阶段 0 代码、阶段 1 设计文档） |
| `fcf26ea` | [0.2.0] | feat: 完成 Task 2 数据库 Schema 与领域模型 | 23 文件，+2133/-45 行 |
| `26705c8` | [0.3.0] | feat: 完成 Task 3 只读扫描器 | 9 文件，+1257/-4 行 |
| `47adec9` | [0.4.0] | feat: 完成 Task 4 Mod 条目组装服务 | 7 文件，+944/-3 行 |
| `b47c213` | [0.5.0] | feat: 完成 Task 5 安全移动预演与执行服务 | 6 文件，+1590/-12 行 |

### 8.3 建议作为阶段 2 起点的 commit

**`b47c213`（HEAD, master）** — `feat: 完成 Task 5 安全移动预演与执行服务 (v0.5.0)`

理由：

- 阶段 1 全部验收通过的最新 commit。
- 工作树 clean，无未提交改动。
- 包含完整的阶段 1 实现与文档。
- 阶段 1 验收 4 项全部在测试中通过。

### 8.4 注意事项

- 阶段 0 的 commit `8376dcb` 实际包含了 `docs/spec.md` / `architecture.md` / `roadmap.md` / `open-questions.md` / `progress.md` / `CHANGELOG.md` / `AGENTS.md`，即阶段 1 的设计文档在阶段 0 的 commit 中已建立。后续 Task 2-5 的 commit 仅更新这些文档。
- 所有 commit 信息采用 `feat: 完成 Task X 描述 (vX.X.X)` 格式，遵循 Conventional Commits 风格。
- 未使用 git tag 标记版本号；版本号仅记录在 CHANGELOG.md 与 commit 信息中。

---

## 9. docs/open-questions.md 中仍未决且会影响后续设计的问题

[docs/open-questions.md](open-questions.md) 共 20 项。Q14（undo_payload 结构）与 Q16（OperationType 值集）已在 Task 5 关闭。其余 18 项仍未决。

### 9.1 会影响阶段 2（基础桌面工作台）设计的问题

| 编号 | 问题 | 影响阶段 2 的方面 |
|---|---|---|
| Q1 | ModItem.status 字段是否实现 | UI 列表筛选、状态展示；若引入需 ALTER TABLE 迁移 |
| Q3 | 卡片拖入目录树 vs「移动到…」按钮 | UI 移动入口设计；application 层 API 已解耦 |
| Q5 | 缩略图缓存失效策略 | 缩略图服务实现前必须决定 |
| Q9 | 是否需要英文国际化 | UI 文本架构（i18n 框架选择） |
| Q11 | 未归类素材如何移出素材池 | 素材池 UI 设计 |
| Q13 | 缩略图命名「内容标识」定义 | 缩略图服务实现前必须决定 |
| Q17 | 增量扫描与变更检测策略 | UI 是否需要实时性、扫描触发机制 |
| Q18 | 扫描并发与取消模型 | UI 非阻塞扫描、进度显示、取消按钮 |
| Q19 | 成员角色数量限制 | UI 角色选择控件的约束 |
| Q20 | 部分失败时的回滚策略 | UI 失败提示与用户操作流 |

### 9.2 会影响阶段 3（搜索与 AI JSON）设计的问题

| 编号 | 问题 | 影响阶段 3 的方面 |
|---|---|---|
| Q2 | FileAsset.batch_id 是否实现 | AI JSON 导入可能涉及批量 |
| Q4 | 预览图缩略图联系表是否导出给 AI | 导出格式设计 |
| Q10 | 候选成员关系生成机制 | AI 建议流程设计 |
| Q12 | 搜索索引更新时机 | FTS5 索引刷新策略 |
| Q15 | AI JSON Schema 文件 | 阶段 3 启动前需先产出 schema 文件并评审 |

### 9.3 会影响阶段 4/5/6 的问题

| 编号 | 问题 | 影响阶段 |
|---|---|---|
| Q6 | 从 Windows 资源管理器拖入应用 | 阶段 4 |
| Q7 | 导入预览图方式 | 阶段 5 启动前 |
| Q8 | 开源许可证（MIT 或 GPL-3.0） | 阶段 6 |

### 9.4 已关闭的问题

- **Q14**（undo_payload 内部结构）：Task 5 已定义结构 `{version:1, members:[...]}`，写入代码注释与 schema 注释。
- **Q16**（OperationType 完整值集）：Task 5 未引入新值，保持 `{move, undo}`；DB 无 CHECK 约束以支持未来扩展。

---

## 10. 参考

- [AGENTS.md](../AGENTS.md) — 工作规则
- [docs/spec.md](spec.md) — 产品规格说明
- [docs/architecture.md](architecture.md) — 架构设计
- [docs/roadmap.md](roadmap.md) — 开发路线图
- [docs/progress.md](progress.md) — 项目进度
- [docs/open-questions.md](open-questions.md) — 待确认问题清单
- [CHANGELOG.md](../CHANGELOG.md) — 变更日志（[0.1.0]–[0.5.0]）
