# Skyrim Content Workbench — 架构设计

> 本文档为方向 C 确认后的重写版。旧版已归档至 `archive/`。
>
> 实现依据：`docs/spec.md`（产品规格）、`docs/design-workbook.md`（设计工作手册）

---

## 1. 技术选型

| 层 | 技术 | 说明 |
|----|------|------|
| UI | PySide6 (Qt 6) | 适合 Windows 桌面文件管理交互，目录树、拖拽、右键菜单、卡片视图 |
| 语言 | Python 3.12+ | UTF-8 / 中文路径友好，快速迭代 |
| 数据库 | SQLite + FTS5 | 本地单文件数据库，无需服务端，第一版不上云 |
| 缩略图 | Pillow | 只读加载源图，生成缩略图缓存 |
| 测试 | pytest | 单元测试 + 临时目录文件操作测试 |
| 代码质量 | ruff | 格式化和静态检查 |
| 打包 | PyInstaller 或 Nuitka | 阶段 6 实施 |

---

## 2. 分层架构

```text
┌──────────────────────────────────────────────────────────┐
│  PySide6 UI (主窗口 / TreeView / ListView / 元数据面板)    │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Application Services                              │  │
│  │  StagingService / ContentService / TagService      │  │
│  │  FileOperationService / ScanService / SearchService │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Domain Logic                                      │  │
│  │  ContentUnit / TagCategory / Tag / OperationHistory│  │
│  │  ManagedRoot / FolderCache / ThumbnailCache        │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Infrastructure                                   │  │
│  │  SQLite Repository / FileScanner / FileOperations  │  │
│  │  ThumbnailGenerator / path_utils                  │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### 分层规则

- **UI 层**不直接访问 Repository 或文件系统写操作，通过 Application Service 调用。
- **Application 层**协调 UI 与领域逻辑，不包含领域规则。
- **Domain 层**为纯数据载体，不包含数据库或文件系统知识。
- **Infrastructure 层**为唯一允许直接操作数据库和文件系统的模块。

---

## 3. UI 层 (`src/app/`)

### 3.1 主窗口布局

```text
MainWindow
  ├─ TopBar: 标题 + 置顶按钮 + 搜索框 + [浏览|整理] 模式切换
  │
  ├─ DirectoryTree (左侧，QTreeView + FolderTreeModel)
  │   └─ 数据源：FolderCache（SQLite 缓存）
  │   └─ 惰性加载：canFetchMore / fetchMore
  │   └─ 支持：展开/折叠、拖拽（DropAction）、右键菜单
  │
  ├─ ContentArea (中间，QSplitter)
  │   ├─ BrowseMode:
  │   │   ├─ ContentUnitList (QListView / QTableView)
  │   │   │   ├─ 有封面 → 大图卡片 (QListWidgetItem + Icon)
  │   │   │   ├─ 无封面 → 详细列表 (QTableView)
  │   │   │   └─ 排序：名称/日期/类型/大小/状态 + 正序/倒序
  │   │   ├─ TagFilterBar (QWidget + 自定义标签按钮)
  │   │   │   └─ 先选分类 → 展开标签 → 多选高亮
  │   │   └─ SearchBar (QLineEdit)
  │   │
  │   └─ OrganizeMode:
  │       ├─ StagingFileList (QListView)
  │       │   └─ 暂存区零散文件列表（文件名/大小/日期）
  │       └─ AssemblyPanel (QWidget)
  │           └─ 正在组装的内容单元文件夹内容
  │
  └─ MetadataPanel (右侧，QWidget)
      ├─ 标题（中文别名）
      ├─ 标签选择器（自动补全）
      ├─ 来源 URL
      ├─ 评分（星标）
      ├─ 备注（多行文本）
      ├─ 封面预览 + 设置按钮
      └─ [保存] 按钮
```

### 3.2 组件职责

| 组件 | 文件 | 职责 |
|------|------|------|
| `MainWindow` | `main_window.py` | 主窗口、布局、模式切换、服务注入 |
| `FolderTreeModel` | `folder_tree_model.py` | QAbstractItemModel，惰性加载目录树 |
| `ContentUnitListModel` | `content_model.py`（新建） | 内容单元列表的 Qt Model |
| `TagFilterBar` | `tag_filter.py`（新建） | 标签分类展开 + 标签多选筛选 |
| `AssemblyPanel` | `assembly_panel.py`（新建） | Mod 组装配面板 |
| `MetadataPanel` | `metadata_panel.py`（新建） | 元数据编辑表单 |
| `ScanWorker` | `scan_worker.py`（改造） | Qt 后台线程执行扫描 |
| `ThumbnailWorker` | `thumbnail_worker.py`（改造） | Qt 后台线程生成缩略图 |
| `ui_constants.py` | `ui_constants.py` | UI 文本常量集中定义 |

### 3.3 UI 线程边界

- `FolderTreeModel`、`ContentUnitListModel`、`MetadataPanel` 在 UI 主线程构造与访问。
- 扫描使用 `ScanWorker`（QObject + QThread），独立 SQLite 连接。
- 缩略图生成使用 `ThumbnailWorker`（QObject + QThread），独立 SQLite 连接。
- UI 不直接调用文件系统写操作（`shutil`、`Path.rename` 等）。

---

## 4. Application 层 (`src/application/`)

### 4.1 Service 划分

| Service | 职责 | 主要方法 |
|---------|------|---------|
| `StagingService` | 暂存区标记与管理 | `set_staging(path)` / `list_staging_files()` / `create_mod_group(file)` |
| `ContentService` | 内容单元元数据 | `list_by_directory(path)` / `update_metadata(...)` / `batch_tag(...)` |
| `TagService` | 标签系统 | `get_categories()` / `search_tags(query)` / `filter_by_tags(tags)` |
| `FileOperationService` | 文件操作（简化） | `move(src, dst)` / `rename(path, name)` / `delete(path)` / `undo(op_id)` |
| `ScanService` | 增量/全量扫描 | `scan(managed_root)` / `scan_all()` |
| `SearchService` | 全局搜索 | `search(query)` |

### 4.2 Service 依赖关系

```text
MainWindow
  ↓
StagingService ──→ FileOperationService (创建 Mod 组需要移动文件)
      │
ContentService ───→ TagService (打标签需要查询标签)
      │
ScanService ──────→ ContentService (扫描后写入候选内容单元)
      │
FileOperationService ──→ OperationHistory (记录操作)
      │
SearchService ─────────→ ContentService + TagService (跨字段搜索)
```

### 4.3 数据流示例

**浏览模式加载流程：**
```
用户点击目录树节点
  → FolderTreeModel.fetchMore() 加载子节点
  → MainWindow._on_tree_selection_changed()
  → ContentService.list_by_directory(path)
  → ContentUnitRepository.list_by_path_prefix(path)
  → 返回 ContentUnit[] → 更新 ContentUnitListModel
  → 同时查询已有缩略图缓存 → 显示封面图标
```

**创建 Mod 组流程：**
```
用户选中文件 → 右键 "创建 Mod 组"
  → MainWindow._on_create_mod_group()
  → StagingService.create_mod_group(file_path)
  → 提取文件名 → 生成目标文件夹名
  → FileOperationService.rename(file_path, target_path)  // 移动文件到新建文件夹
  → ContentService 创建新 ContentUnit（路径指向新建文件夹）
  → 刷新暂存区文件列表 + 显示装配面板
```

---

## 5. Domain 层 (`src/domain/`)

### 5.1 实体定义

详见 `docs/spec.md §4.1-4.8`。Domain 层为纯 dataclass，不包含数据库或文件系统知识。

### 5.2 已移除的旧实体

- `ModItem` → 由 `ContentUnit` 替代
- `FileAsset` → 不再以文件为粒度记录
- `FileRole` → 不再需要
- `OperationLog`（旧版） → 由 `OperationHistory` 替代
- `ConflictPolicy`、`OperationStatus`、`OperationType`（旧版枚举）

---

## 6. Infrastructure 层 (`src/infrastructure/`)

### 6.1 模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| 数据库初始化 | `db.py` | SQLite 连接、WAL 模式、外键、版本管理 |
| Schema 迁移 | `migrations.py` | v3→v4 迁移（建新表、移除旧表） |
| Repository 层 | `repositories/` | 每个实体对应一个 Repository |
| 文件扫描器 | `file_scanner.py` | 递归扫描、增量 mtime 判断、内容识别 |
| 文件操作服务 | `file_operation_service.py` | 文件移动/重命名/删除/撤销（简化版） |
| 缩略图生成 | `thumbnail_generator.py` | Pillow 只读生成缩略图 |
| 路径工具 | `path_utils.py` | path_key 标准化（normcase+normpath） |

### 6.2 Repository 清单

```text
repositories/
  ├── content_unit.py       # 新建
  ├── tag_category.py        # 新建
  ├── tag.py                 # 新建
  ├── content_unit_tag.py    # 新建
  ├── operation_history.py   # 新建
  ├── folder_cache.py        # 新建（简化版 folder_node）
  ├── managed_root.py        # 保留
  ├── thumbnail_cache.py     # 保留
  └── errors.py              # 保留（RepositoryError 等）
```

### 6.3 移除的 Repository

- `mod_item.py` ❌
- `file_asset.py` ❌
- `folder_node.py` ❌（由 `folder_cache.py` 替代）
- `operation_log.py` ❌（由 `operation_history.py` 替代）

### 6.4 SQLite 数据库结构

**数据库位置：** `%LOCALAPPDATA%\SkyrimContentWorkbench\app.db`

**Schema v4 表清单：**

```text
content_unit
  - id TEXT PRIMARY KEY
  - path TEXT NOT NULL UNIQUE
  - title TEXT
  - content_type TEXT NOT NULL DEFAULT 'mod'
  - source_url TEXT
  - rating INTEGER
  - cover_path TEXT
  - status TEXT NOT NULL DEFAULT 'unorganized'
  - notes TEXT
  - created_at TEXT NOT NULL
  - updated_at TEXT NOT NULL

tag_category
  - id TEXT PRIMARY KEY
  - name TEXT NOT NULL
  - color_hue INTEGER NOT NULL DEFAULT 0

tag
  - id TEXT PRIMARY KEY
  - name TEXT NOT NULL
  - category_id TEXT NOT NULL REFERENCES tag_category(id)

content_unit_tag
  - content_unit_id TEXT NOT NULL REFERENCES content_unit(id)
  - tag_id TEXT NOT NULL REFERENCES tag(id)
  - PRIMARY KEY (content_unit_id, tag_id)

operation_history
  - id TEXT PRIMARY KEY
  - operation_type TEXT NOT NULL CHECK(operation_type IN ('move','delete','rename','new_folder'))
  - source_path TEXT NOT NULL
  - target_path TEXT
  - created_at TEXT NOT NULL
  - can_undo INTEGER NOT NULL DEFAULT 1

managed_root（保留）
  - id, real_path, path_key UNIQUE, display_name, created_at, updated_at

folder_cache
  - id TEXT PRIMARY KEY
  - path TEXT NOT NULL UNIQUE
  - parent_id TEXT REFERENCES folder_cache(id)
  - last_scanned_mtime REAL
  - created_at TEXT NOT NULL

thumbnail_cache（保留）
  - asset_id TEXT PRIMARY KEY REFERENCES content_unit(id)  ← 关联改为 content_unit_id
  - source_size_bytes INTEGER
  - source_modified_at TEXT
  - cache_filename TEXT
  - status TEXT CHECK(status IN ('ok','missing','corrupt','unsupported','error'))
  - error_message TEXT
  - generated_at TEXT
```

### 6.5 路径工具

`path_utils.make_path_key(path)` 保留现有实现：`normcase(normpath(path))`。

路径比较和唯一约束统一使用 path_key，不依赖字符串大小写。

---

## 7. 文件操作服务

### 7.1 接口

```text
FileOperationService
  - move(src: Path, dst: Path) → OperationResult     # 移动（含冲突检查）
  - rename(path: Path, new_name: str) → Path          # 重命名 + 更新 ContentUnit
  - delete(path: Path) → None                         # 移到回收站
  - undo(op_id: str) → OperationResult                # 撤销操作
```

### 7.2 安全规则（实现于服务层）

- `move()` 执行前校验冲突，冲突时抛 `ConflictError`，由 UI 弹窗选择。
- 跨盘移动检测（`st_dev` 比较），检测到时抛 `CrossDriveError`。
- 自目录移动检测（`path_key` 比较），检测到时抛 `SelfSubdirectoryError`。
- `undo()` 执行前校验源文件存在性和状态一致性。

### 7.3 操作记录

每次操作（move / delete / rename / new_folder）后自动写入 `operation_history` 表。
写入由 FileOperationService 内部完成，调用方不需要手动写。

---

## 8. 扫描架构

### 8.1 增量扫描策略

```text
ScanService.scan(managed_root)
  ├─ 遍历 managed_root 下的第一级目录
  ├─ 读取每个目录的 mtime（os.stat.st_mtime）
  ├─ 对比 folder_cache.last_scanned_mtime
  │   ├─ 相等 → 跳过，沿用缓存
  │   └─ 不等 → 递归扫描该目录
  │
  ├─ 递归扫描时：
  │   ├─ 遇到含压缩包文件的文件夹 → 标记为内容单元候选
  │   ├─ 记录所有子目录到 folder_cache
  │   └─ 跳过已被标记为内容单元的文件夹内部
  │
  └─ 写入：
      ├─ folder_cache（目录树缓存）
      └─ content_unit（候选内容单元，status=unorganized）
```

### 8.2 线程模型

- `ScanWorker`（QObject + QThread）包裹同步 `ScanService.scan()`。
- ScanWorker 在自身线程内创建独立 SQLite 连接。
- 通过 Qt 信号回传结果：`scan_finished(summary)` / `scan_failed(error)`。

### 8.3 触发时机

- 应用启动时自动触发增量扫描。
- 用户可通过 UI 按钮手动触发全量扫描。
- 不做实时文件系统监听（避免 CPU 负载）。

---

## 9. 缩略图架构

保留现有 `ThumbnailGenerator` + `ThumbnailCoordinator` + `ThumbnailWorker` 架构，主要改动：

| 改动 | 说明 |
|------|------|
| 关联键 | `asset_id` → `content_unit_id` |
| 源路径 | 从 `FileAsset.real_path` → `ContentUnit.path` + `cover_path` |
| 查询 | 从 `FileAssetRepository` → `ContentUnitRepository` |

缩略图缓存目录：`%LOCALAPPDATA%\SkyrimContentWorkbench\thumbnails\`
缓存文件命名：`{content_unit_id}.png`

---

## 10. 应用数据目录

```text
%LOCALAPPDATA%\SkyrimContentWorkbench\
  ├── app.db              # SQLite 数据库（schema v4）
  ├── thumbnails\         # 缩略图缓存
  ├── exports\            # AI JSON 导出
  └── logs\               # 应用日志
```

用户 Mod 文件不应被复制到应用数据目录。唯一例外是缩略图缓存（可随时删除并重建）。

---

## 11. 测试策略

### 11.1 优先测试

- 内容单元 CRUD 与中文路径
- 增量扫描逻辑与 mtime 判断
- 内容单元识别规则（含压缩包 → 候选）
- 文件夹操作（移动/重命名/删除）与安全规则
- 操作历史读写与撤销
- 标签 CRUD、自动补全、筛选
- UI 模式切换与数据联动
- 数据库 v4 迁移（v3→v4 幂等、旧表移除验证）

### 11.2 保留的旧测试

以下旧测试可保留或小幅修改继续使用：

- `test_path_utils.py` ✅
- `test_file_classify.py` ✅
- `test_thumbnail_*.py` ✅（需调整关联字段）
- `test_managed_root_*.py` ✅
- `test_scan_worker.py` ✅
- `test_thumbnail_ui.py` ⚠️（需调整关联）
- `test_db.py` ✅
- `test_migrations.py` ⚠️（需扩展 v4）

### 11.3 需重写或移除的旧测试

- `test_mod_assembly_service.py` ❌
- `test_pool_model.py` ❌
- `test_file_operation_service.py` ⚠️（需适配简化版接口）
- `test_main_window.py` ❌（需重写）
- `test_folder_tree_*.py` ⚠️（需适配新数据源）

---

## 12. 旧版架构迁移说明

当前代码（版本 ≤ v0.9.0）实现了旧版架构（ModItem / FileAsset / FileRole / OperationLog 四步状态机），与新架构不兼容。

迁移策略：
1. 阶段 2 Task 1：建立新数据库 schema v4，移除旧表（不迁移旧数据）。
2. 旧版代码文件逐步改造或重写，不保留旧版 Service 和 UI。
3. 旧版文档已归档至 `archive/`。
