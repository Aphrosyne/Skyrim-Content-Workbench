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
│  │  ContentService / ContentUnitCreationService /     │  │
│  │  AssemblyService / TagService / ScanService /      │  │
│  │  SearchService / FolderTreeService /               │  │
│  │  ManagedRootService / UndoService /                │  │
│  │  ClipboardService / ConflictResolutionService /    │  │
│  │  ThumbnailService                                  │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Domain Logic                                      │  │
│  │  ContentUnit / TagCategory / Tag / OperationHistory│  │
│  │  ManagedRoot / FolderCache / ThumbnailCache        │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Infrastructure                                   │  │
│  │  SQLite Repository / FileScanner / FileOperation   │  │
│  │  Service / ThumbnailGenerator / path_utils /       │  │
│  │  FolderCacheSyncHelper / windows_recycle_bin       │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

> **注**：`FileOperationService` 位于 Infrastructure 层但注入了 Application 层依赖
> （FolderCacheSyncHelper + ContentUnitRepository），分层归属违反已登记为 TD-H10，
> 计划在 UX 重构 Task 7 迁移到 Application 层。

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
  ├─ TopBar: 搜索框 + 标签管理按钮 + 操作历史按钮
  │
  ├─ 左栏（QWidget）
  │   ├─ 受管理根目录列表 + 添加/移除 + 增量/全量扫描按钮
  │   ├─ DirectoryTree (QTreeView + FolderTreeModel)
  │   │   └─ 数据源：FolderCache（SQLite 缓存）
  │   │   └─ 惰性加载：canFetchMore / fetchMore
  │   │   └─ 支持：展开/折叠、右键菜单（新建文件夹/重命名/删除/移动到…/复制剪切粘贴/折叠全部）
  │   └─ 选中目录详情区（路径简化显示）
  │
  ├─ 中栏（QSplitter + QStackedWidget）
  │   ├─ 标题栏：刷新按钮（F5）+ 前进/后退 + 视图切换（列表/卡片）+ 排序下拉 + 缩放（卡片）
  │   ├─ TagFilterBar (QWidget + 自定义标签按钮)
  │   │   └─ 先选分类 → 展开标签 → 多选高亮 → 实时筛选（同分类 OR，跨分类 AND）
  │   ├─ FileListModel（详细列表，QTableView + rubber band 框选）
  │   └─ CardListModel（大图卡片，QListView IconMode，缩放 96~256 预选档）
  │
  ├─ 右栏（QSplitter，元数据上 + 装配下，3:2）
  │   ├─ MetadataPanel (QWidget，注入 TagService 时显示)
  │   │   ├─ 标题（QLineEdit，中文别名）
  │   │   ├─ 标签 chip 列表 + 独立输入框（QListWidget LeftToRight + Wrapping + QCompleter 自动补全）
  │   │   ├─ 标签预选区域（输入框下方，单击快速添加到 chip，排除已在 chip 列表的）
  │   │   ├─ 来源 URL（QLineEdit）
  │   │   ├─ 备注（QTextEdit，多行）
  │   │   ├─ 封面预览 + 设置封面按钮 + 清除封面按钮
  │   │   └─ [保存] 按钮（显式保存，不自提交）
  │   └─ AssemblyPanel（文件夹透视器）
  │       ├─ 📌 钉住按钮（钉住后中栏操作不改变绑定）
  │       ├─ 透视任意文件夹内部文件（AssemblyListModel）
  │       ├─ 拖拽接受文件（仅钉住时）
  │       └─ 右键：文件操作继承中栏 + 图片重命名 + 空白处移动到……
  │
  └─ StatusBar（QStatusBar：扫描状态 + 操作提示）
```

> UX 重构 Phase 1 起为单面板统一工作区（无浏览/整理模式切换，无暂存区/快速插入）。
> 未注入 TagService 时 MetadataPanel 降级为只读 `_metadata_label`（兼容旧测试）。

### 3.2 组件职责

| 组件 | 文件 | 职责 |
|------|------|------|
| `MainWindow` | `main_window.py` | 主窗口、布局、服务注入、信号槽编排（God Object，TD-M21/M31，待 Task 7 拆分） |
| `FolderTreeModel` | `folder_tree_model.py` | QAbstractItemModel，惰性加载目录树 |
| `FileListModel` | `file_list_model.py` | 中栏详细列表 QAbstractListModel（文件系统条目 + 内容单元标记 + 排序） |
| `CardListModel` | `card_list_model.py` | 中栏大图卡片视图 QAbstractListModel（封面 + 名称） |
| `TagFilterBar` | `tag_filter.py`（新建） | 标签分类展开 + 标签多选筛选 |
| `AssemblyPanel` | `assembly_panel.py` | 右栏下方装配面板（文件夹透视器 + 📌 钉住 + 拖拽 drop target + 右键继承中栏操作） |
| `MetadataPanel` | `metadata_panel.py`（新建） | 元数据编辑表单（标题/标签/来源/备注/封面），显式保存按钮，标签 chip + 自动补全 |
| `BatchTagDialog` | `batch_tag_dialog.py`（新建） | 批量打标签对话框（添加/移除模式 + chip + 自动补全） |
| `CoverPickerDialog` | `cover_picker_dialog.py`（新建） | 封面选择对话框（IconMode 缩略图列表，默认选中第一张或当前封面） |
| `TagManagerDialog` | `tag_manager_dialog.py` | 标签分类/标签 CRUD + JSON 导入导出 |
| `MoveToDialog` | `move_to_dialog.py` | "移动到……"目标目录选择对话框（内嵌 FolderTreeModel） |
| `ConflictResolutionDialog` | `conflict_resolution_dialog.py` | 冲突解决对话框（覆盖/跳过/重命名） |
| `OperationHistoryDialog` | `operation_history_dialog.py` | 操作历史对话框（含撤销，Tooltip 显示详情） |
| `SearchDialog` | `search_dialog.py` | 全局搜索对话框（LIKE 查询，双击跳转） |
| `ScanWorker` | `scan_worker.py`（改造） | Qt 后台线程执行扫描 |
| `ThumbnailWorker` | `thumbnail_worker.py`（改造） | Qt 后台线程生成缩略图 |
| `ThumbnailCoordinator` | `thumbnail_coordinator.py` | 缩略图任务队列（单 worker + FIFO + 去重） |
| `path_display` | `path_display.py` | 路径简化显示（相对根目录名，外部路径 `[外部]` 前缀） |
| `message_box_helper` | `message_box_helper.py` | QMessageBox 系统提示音抑制 |
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
| `ManagedRootService` | 受管理根目录 CRUD | `add_root(path)` / `remove_root(id)` / `list_roots()` |
| `FolderTreeService` | 目录树数据源（folder_cache + managed_root） | `list_root_nodes()` / `list_children(path)` / `count_children(path)` |
| `ContentService` | 内容单元元数据 + 目录条目 + 标记/取消标记 | `mark_as_content_unit(path)` / `unmark_content_unit(id)` / `list_directory_entries(path)` / `update_metadata(unit_id, title, source_url, notes, cover_path)` / `list_cover_candidates(unit_path)` / `quick_set_cover(unit_id)` |
| `ContentUnitCreationService` | 创建 Mod 组（D1：原 ModGroupService 代码层重命名） | `create_content_unit_from_file(source_file, staging_path, name)` / `create_content_unit_from_files(entries, staging_path)` |
| `AssemblyService` | 装配面板（文件夹透视 + 封面重命名） | `list_folder_files(folder_path)` / `bind_mod_group(unit_id)` / `rename_as_cover_by_path(folder_path, image_path)` / `add_file(...)` |
| `ScanService` | 增量/全量扫描 | `scan_root(root_id, incremental)` / `scan_root_by_path(path, incremental)` |
| `TagService` | 标签系统 | `create_category()` / `create_tag()` / `list_categories_with_tags()` / `import_from_json()` / `export_to_json()` / `search_tags(query)` / `list_tags_of_content_unit(unit_id)` / `attach_tag_to_unit(...)` / `batch_attach_tags(...)` / `batch_detach_tags(...)` / `filter_unit_ids_by_category_and(tag_ids)` / `load_default_tags_if_empty(...)` |
| `SearchService` | 全局搜索（LIKE，标题+标签+备注） | `search(query)` |
| `UndoService` | 操作历史撤销（安全校验 + 反向操作 + 标记 undone_at） | `undo(history)` / `list_recent(limit)` |
| `ClipboardService` | 应用内剪贴板（Q3=A 不与系统剪贴板混用） | `set_copy(paths)` / `set_cut(paths)` / `get()` / `is_cut(path)` / `cut_paths()` |
| `ConflictResolutionService` | 冲突解决策略（覆盖/跳过/重命名 + 跨盘检测） | `scan_conflicts(...)` / `resolve(...)` |
| `ThumbnailService` | 缩略图缓存管理（生成/查询/失效/GC） | `get_cache(unit_id, source_path, size)` / `generate(...)` / `invalidate(unit_id)` / `cleanup_orphans()` |
| `FileOperationService` | 文件操作（**位于 Infrastructure，分层违反登记 TD-H10**） | `new_folder(path)` / `move(src, dst, overwrite=False, record_history=True)` / `copy(...)` / `rename(...)` / `delete(path)` / `undo(op_id)` |

### 4.2 Service 依赖关系

```text
MainWindow
  ↓
ManagedRootService ──→ ManagedRootRepository
      │
FolderTreeService ──→ FolderCacheRepository + ManagedRootRepository
      │
ContentService ──→ ContentUnitRepository + ThumbnailService（可选）+ UnitOfWork
      │
ContentUnitCreationService ──→ FileOperationService + ContentService + UnitOfWork
      │
AssemblyService ──→ FileOperationService + ContentUnitRepository
      │
FileOperationService ──→ OperationHistoryRepository + FolderCacheSyncHelper + ContentUnitRepository
      │
UndoService ──→ OperationHistoryRepository + FileOperationService + FolderCacheSyncHelper + ContentUnitRepository
      │
ScanService ──→ ManagedRootRepository + FolderCacheRepository + ContentUnitRepository + FileScanner
      │
TagService ──→ TagCategoryRepository + TagRepository + ContentUnitTagRepository
      │
SearchService ──→ SearchRepository
      │
ThumbnailService ──→ ThumbnailCacheRepository + ContentUnitRepository
```

> 已移除：`StagingService` / `StagingAreaRepository` / `QuickInsertService`（UX 重构
> Phase 1 Task 1/4）。`ScanService` 额外注入 `UnitOfWork`（TD-H2 修复后），
> `ContentService` 注入 `UnitOfWork`（Stage 4.5 H6 修复后）。

### 4.3 数据流示例

**目录浏览加载流程：**
```
用户点击目录树节点
  → FolderTreeModel.fetchMore() 加载子节点
  → MainWindow._on_tree_selection_changed()
  → ContentService.list_directory_entries(path)
  → 文件系统 iterdir + ContentUnitRepository.get_by_path() 关联
  → 返回 FileEntry[] → 更新 FileListModel
  → 同时查询已有缩略图缓存 → 显示封面图标
```

**创建 Mod 组流程（UX 重构 Phase 1 Task 1 调整）：**
```
用户中栏选中文件（单/多选）→ 右键 "创建 Mod 组"
  → MainWindow._on_create_mod_group(entries)
  → ContentUnitCreationService.create_content_unit_from_files(entries, 当前目录)
  → 提取文件名 → 生成目标文件夹名
  → FileOperationService.new_folder(target_folder)（自动同步 folder_cache）
  → FileOperationService.move(...) 逐个移入（自动同步 folder_cache + ContentUnit.path）
  → ContentService.mark_as_content_unit(target_folder)
  → 刷新中栏 + 目录树
```

**添加到钉住文件夹 / 拖拽流程（UX 重构 Phase 1 Task 3/4）：**
```
装配面板已钉住 → 中栏右键文件/文件夹 → 「添加到钉住文件夹」（或直接拖拽到装配面板）
  → MainWindow._perform_move_to(entries, 钉住文件夹路径, refresh_assembly=True)
  → 冲突解决（ConflictResolutionService + ConflictResolutionDialog：覆盖/跳过/重命名）
  → FileOperationService.move(src, dst, overwrite=...)
    （自动同步 folder_cache + ContentUnit.path + 写入 operation_history）
  → 刷新装配面板 + 中栏
```

**文件夹整体移动流程（UX 重构 Phase 1 Task 2/3）：**
```
装配面板绑定文件夹 → 右键空白处 → 「移动到……」
  → MainWindow._on_move_to(...) → MoveToDialog 选择目标目录
  → 移动安全规则：确认弹窗 / 冲突解决 / 跨盘拒绝 / 子目录阻止
  → FileOperationService.move(src_folder, dst_folder)
    （自动同步 folder_cache + ContentUnit.path + 写入 operation_history）
  → 移动成功后自动取消钉住/解绑装配面板
  → 刷新目录树 + 中栏
```

**元数据保存流程（阶段 4 Task 2；2026-07-25 调整：单击加载）：**
```
中栏单击内容单元 → MetadataPanel.load_unit(unit) 加载字段
  （双击兼容保留；单击非内容单元 → clear_panel 清空元数据面板）
  → 用户编辑标题 / 来源 URL / 备注 / 添加或移除标签 chip（输入回车 / 单击预选标签） / （可选）设置封面
  → 点击「保存」按钮
  → MetadataPanel._on_save_clicked()
    1. ContentService.update_metadata(unit_id, title, source_url, notes, cover_path)
       - 字段校验：title ≤ 200、source_url ≤ 2000
       - cover_path 校验：拒绝绝对路径和 ..，统一转 POSIX 分隔符
       - cover_path 语义：None=不改、""=清空、非空=设置
    2. TagService.set_content_unit_tags(unit_id, current_tag_ids)
       - diff 计算 original_tag_ids vs current_ids → to_add / to_remove
       - 事务内 attach / detach（INSERT OR IGNORE 幂等）
  → 发射 on_saved(updated_unit) 信号
  → MainWindow._on_metadata_saved()
    → _commit()（事务边界，Service 不自提交）
    → _refresh_content_list_for_current_mode()
    → _update_metadata(updated_unit)（重新加载 panel）
    → 状态栏提示「元数据已保存」
```

**封面选择流程（阶段 4 Task 2）：**
```
MetadataPanel 已加载内容单元 → 点击「设置封面」按钮
  → MetadataPanel 发射 on_pick_cover_requested(unit_id) 信号
  → MainWindow._on_pick_cover_requested(unit_id)
    → ContentService.get_by_id(unit_id) 取 ContentUnit
    → ContentService.list_cover_candidates(unit.path)
      - 扫描内容单元目录下所有图片文件（jpg/jpeg/png/webp/gif/bmp/tif/tiff/ico）
    → 若无候选 → QMessageBox.information 提示，结束
    → 弹出 CoverPickerDialog(candidates, unit_path, current_cover)
      - 默认选中第一张，或当前封面（若提供且在候选中）
      - 用户在 IconMode 列表中切换选择
    → 用户点击「确定」 → dialog.selected_relative_path()
      - 返回 POSIX 风格相对路径（相对内容单元路径）
    → MetadataPanel.set_cover_path(rel_path)（仅更新界面预览，不立即写库）
    → 用户点击「保存」按钮 → 走元数据保存流程
```

**批量打标签流程（阶段 4 Task 2；2026-07-25 调整：预选标签 + 回车不关闭窗口）：**
```
文件列表多选（≥2 项且至少一个内容单元）→ 右键 → 「批量打标签」
  → MainWindow._on_batch_tag(entries)
    → 收集所有 entries 中 content_unit is not None 的 id 列表
    → 若无内容单元 → QMessageBox.information 提示，结束
    → 弹出 BatchTagDialog(tag_service, content_unit_ids)
      - 默认 add 模式 + 空 chip 列表
      - 用户输入标签名 + 回车 → 前缀匹配自动补全（QCompleter + TagRepository.search_by_name_prefix）
        回车仅添加到 chip 列表，不关闭窗口（setAutoDefault(False) 禁用默认按钮）
      - 单击预选标签 → 快速添加到 chip（与回车等效）
      - 重复标签警告 / 未知标签警告 / 空白名称 no-op
      - 单击 chip 移除
      - 切换 add / remove 模式（RadioButton）
    → 用户点击「应用」（此时才执行批量操作 + accept 关闭窗口）
      - add 模式：TagService.batch_attach_tags(unit_ids, tag_ids)
      - remove 模式：TagService.batch_detach_tags(unit_ids, tag_ids)
      - 每个 (unit, tag) 对独立 attach/detach，已关联/未关联的跳过（幂等）
      - 收集 result_messages（如「已为 3 个内容单元添加标签『重甲』」）
    → dialog.exec() 返回 Accepted
    → MainWindow._commit()
    → _refresh_content_list_for_current_mode()
    → 状态栏显示 result_messages（；分隔）
```

**标签筛选流程（阶段 4 Task 3）：**
```
浏览模式 + TagFilterBar 可见（注入 TagService 且有分类）
  → TagFilterBar.refresh_categories()
    → TagService.list_categories_with_tags() 一次性加载所有分类与标签
    → 构建内部状态 [(TagCategory, [Tag]), selected_tag_ids: set, expanded_category_id]
    → 默认全部折叠（Q5: A），分类按钮互斥展开（Q2: A）

用户点击分类按钮 → 展开该分类标签列表（互斥：自动折叠旧分类）
用户点击标签按钮 → toggle 选中态，边框高亮（Q7: A）
  → TagFilterBar.on_filter_changed.emit(set[tag_id])
  → MainWindow._on_tag_filter_changed(selected_tag_ids)
    → 若 selected_tag_ids 非空：
      - MetadataPanel 保持上一次可见状态（Q6: A 修正：筛选不清空不隐藏面板，
        用户可继续查看选中条目的元数据）
      - TagService.filter_unit_ids_by_category_and(tag_ids)
        - 按 category_id 分组 → 每个分类 OR 取并集 → 跨分类 AND 取交集
      - _refresh_content_list_for_current_mode() 应用筛选
        - _apply_tag_filter(entries)：
          - 筛选激活时仅保留 entry.content_unit.id in allowed_unit_ids 的条目
          - 非内容单元条目全部隐藏（Q1: B：列表变成纯结果集）
        - 无结果显示「无符合筛选条件的内容单元」
    → 若 selected_tag_ids 为空：
      - _refresh_content_list_for_current_mode() 显示全量

用户点击「清除全部」→ 清空所有已选 → 发射空集合信号 → 恢复全量列表

切换目录树节点 → 筛选状态保留，自动应用于新目录（Q3: A）
标签管理对话框关闭 → refresh_categories()：剔除已删除的已选标签并重新筛选
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
| Schema 迁移 | `migrations.py` | v0→v13 迁移注册表（建新表、移除旧表、加 UNIQUE 约束、thumbnail_cache 复合主键、operation_history 撤销/复制支持、status→is_marked→纯 DELETE 模式、staging_area 移除） |
| Repository 层 | `repositories/` | 每个实体对应一个 Repository |
| 文件扫描器 | `file_scanner.py` | 递归扫描、增量 mtime 判断、内容识别 |
| 文件操作服务 | `file_operation_service.py` | 文件移动/重命名/删除/撤销（简化版） |
| 缩略图生成 | `thumbnail_generator.py` | Pillow 只读生成缩略图 |
| 路径工具 | `path_utils.py` | path_key 标准化（normcase+normpath） |

### 6.2 Repository 清单

```text
repositories/
  ├── content_unit.py       # ContentUnit 仓储
  ├── tag_category.py        # TagCategory 仓储
  ├── tag.py                 # Tag 仓储
  ├── content_unit_tag.py    # ContentUnitTag 关联仓储
  ├── operation_history.py   # OperationHistory 仓储（含 list_recent / count / delete_oldest_exceeding）
  ├── folder_cache.py        # FolderCache 仓储（简化版 folder_node）
  ├── managed_root.py        # ManagedRoot 仓储（保留）
  ├── thumbnail_cache.py     # ThumbnailCache 仓储（v7 起复合主键 content_unit_id + size）
  ├── search.py              # SearchRepository（阶段 5 Task 7，跨表 LIKE 全局搜索）
  └── errors.py              # RepositoryError 等
```

> `staging_area.py` 已于 UX 重构 Phase 1 Task 1（v0.42.0）随暂存区功能移除。

### 6.3 移除的 Repository

- `mod_item.py` ❌
- `file_asset.py` ❌
- `folder_node.py` ❌（由 `folder_cache.py` 替代）
- `operation_log.py` ❌（由 `operation_history.py` 替代）

### 6.4 SQLite 数据库结构

**数据库位置：** 数据目录下 `app.db`（数据目录解析优先级见 §10）

**Schema v13 表清单：**

```text
schema_version
  - version INTEGER NOT NULL
  - applied_at TEXT NOT NULL DEFAULT (datetime('now'))
  # 由 init_db 维护，每步迁移成功后插入一行

content_unit
  - id TEXT PRIMARY KEY
  - path TEXT NOT NULL UNIQUE
  - path_key TEXT NOT NULL UNIQUE  # v11 新增：DB 层强制路径归一化唯一
  - title TEXT
  - content_type TEXT NOT NULL DEFAULT 'mod'
  - source_url TEXT
  - cover_path TEXT
  - notes TEXT
  - created_at TEXT NOT NULL
  - updated_at TEXT NOT NULL
  # v6 移除：rating INTEGER（私人数据库用不上）
  # v10 变更：所有 'unorganized' → 'organized'（语义重命名，旧 organized/"已整理"语义已废弃）
  # v11 变更：status 列移除，重构为 is_marked（D2/D3 决策）
  # v13 变更（UX 重构 Task 6）：is_marked 列移除，回归纯 DELETE 模式
  #  （记录存在即已标记；取消标记 = DELETE 记录）

tag_category
  - id TEXT PRIMARY KEY
  - name TEXT NOT NULL
  - color_hue INTEGER NOT NULL DEFAULT 0
  # v6 新增：UNIQUE INDEX idx_tag_category_name_unique (name)

tag
  - id TEXT PRIMARY KEY
  - name TEXT NOT NULL
  - category_id TEXT NOT NULL REFERENCES tag_category(id)
  # v6 新增：UNIQUE INDEX idx_tag_name_category_unique (name, category_id)

content_unit_tag
  - content_unit_id TEXT NOT NULL REFERENCES content_unit(id)
  - tag_id TEXT NOT NULL REFERENCES tag(id)
  - PRIMARY KEY (content_unit_id, tag_id)

operation_history
  - id TEXT PRIMARY KEY
  - operation_type TEXT NOT NULL CHECK(operation_type IN ('move','delete','rename','new_folder','undo','copy'))
  - source_path TEXT NOT NULL
  - target_path TEXT
  - created_at TEXT NOT NULL
  - can_undo INTEGER NOT NULL DEFAULT 1
  - undone_at TEXT NULL  # v8 新增，撤销时间戳；NULL 表示未撤销
  # v8：CHECK 约束扩展 'undo'（Stage 5 Task 6）
  # v9：CHECK 约束扩展 'copy'（Stage 5 Task 3b）
  # 自动清理上限：max_history_records=1000，写入前预清理，保留可撤销记录

managed_root（保留）
  - id, real_path, path_key UNIQUE, display_name, created_at, updated_at

folder_cache
  - id TEXT PRIMARY KEY
  - path TEXT NOT NULL UNIQUE
  - parent_id TEXT REFERENCES folder_cache(id)
  - last_scanned_mtime REAL
  - created_at TEXT NOT NULL

thumbnail_cache
  - content_unit_id TEXT NOT NULL  # v4 起关联键由旧 asset_id 改为 content_unit_id
  - size INTEGER NOT NULL DEFAULT 64  # v7 新增：支持多尺寸缓存
  - source_size_bytes INTEGER NOT NULL
  - source_modified_at TEXT NOT NULL
  - cache_filename TEXT NOT NULL
  - status TEXT NOT NULL CHECK(status IN ('ok','missing','corrupt','unsupported','error'))
  - error_message TEXT
  - generated_at TEXT NOT NULL
  - PRIMARY KEY (content_unit_id, size)  # v7 改为复合主键
  # v7 变更：从单档 PNG 改为多尺寸 WebP，旧 64 档记录迁移保留，旧文件由 GC 清理
  # 缓存文件命名：{content_unit_id}_{size}.webp
```

**迁移历史摘要：**

| 版本 | 阶段 | 关键变更 |
|------|------|---------|
| v0→v1 | 阶段 2 前置 | 创建 mod_item / file_asset / folder_node / operation_log 旧表（方向 C 已废弃） |
| v1→v2 | 阶段 2 Task 1 | 新增 managed_root 表 |
| v2→v3 | 阶段 2 Task 1 | 新增 thumbnail_cache 旧表（关联 asset_id） |
| v3→v4 | 阶段 2 Task 1 | 方向 C 重建：建 content_unit / tag_category / tag / content_unit_tag / operation_history / folder_cache；重建 thumbnail_cache（关联键改为 content_unit_id）；移除旧表 |
| v4→v5 | 阶段 3 Task 1 | 新增 staging_area 表（暂存区持久化） |
| v5→v6 | 阶段 4 Task 1 | 移除 content_unit.rating；tag_category.name 加 UNIQUE；tag (name, category_id) 加 UNIQUE |
| v6→v7 | 阶段 5 Task 1a | thumbnail_cache 改复合主键 (content_unit_id, size)，缓存格式 PNG → WebP |
| v7→v8 | 阶段 5 Task 6 | operation_history 新增 undone_at 列；CHECK 扩展 'undo' |
| v8→v9 | 阶段 5 Task 3b | operation_history CHECK 扩展 'copy' |
| v9→v10 | 阶段 5 Task 7 收尾 | content_unit.status 'unorganized' → 'organized'（语义简化为两态） |
| v10→v11 | Stage 5 Code Review | content_unit.status → is_marked + 新增 path_key（UNIQUE）；清理历史 undo 记录；清理冗余索引（M12） |
| v11→v12 | UX 重构 Phase 1 Task 1 | 移除 staging_area 表（暂存区功能移除） |
| v12→v13 | UX 重构 Phase 2 Task 6 | 清理 is_marked=0 记录及关联 → content_unit 表重建移除 is_marked 列，回归纯 DELETE 模式 |

所有迁移函数幂等（CREATE TABLE IF NOT EXISTS / 列存在性检查 / SQL 文本检查）。
迁移注册表见 `migrations.py` 末尾 `MIGRATIONS` 列表，`init_db` 按 target 升序应用。

### 6.5 路径工具

`path_utils.make_path_key(path)` 保留现有实现：`normcase(normpath(path))`。

路径比较和唯一约束统一使用 path_key，不依赖字符串大小写。

---

## 7. 文件操作服务

### 7.1 接口

```text
FileOperationService
  - new_folder(folder_path: Path) → OperationHistory   # 新建文件夹（自动同步 folder_cache）
  - move(src: Path, dst: Path, *, overwrite=False, record_history=True) → OperationHistory  # 移动（冲突/跨盘/自目录检查 + 同步 folder_cache/ContentUnit.path）
  - rename(old_path: Path, new_name: str, *, record_history=True) → OperationHistory  # 重命名 + 同步 ContentUnit
  - copy(src: Path, dst: Path, *, overwrite=False) → OperationHistory  # 复制（Stage 5 Task 3b，can_undo=0）
  - delete_to_recycle_bin(paths: list[Path]) → tuple[list[OperationHistory], list[str]]  # 移至回收站（ctypes SHFileOperation）

UndoService
  - undo(history: OperationHistory) → None             # 撤销（Stage 5 Task 6：安全校验 + 反向 move/rename + 标记 undone_at，不写新记录）
```

### 7.2 安全规则（实现于服务层）

- `move()` / `copy()` 执行前校验冲突，冲突时抛 `ConflictError`，由 UI 弹窗选择
  （`ConflictResolutionDialog` 提供 覆盖/跳过/重命名 三选项，`overwrite=True` 时直接覆盖）。
- 跨盘移动检测（`st_dev` 比较），`move` 检测到时抛 `CrossDriveError`；
  `copy` 允许跨盘（语义上复制本就跨盘）。
- 自目录移动检测（`path_key` 比较），检测到时抛 `SelfSubdirectoryError`。
- `UndoService.undo()` 执行前校验源文件存在性和状态一致性（路径存在 + size/mtime 校验，
  Stage 5 Task 6 严格安全检查；非空 new_folder 撤销时弹窗阻止）。
- 撤销操作不写入新的 `operation_history` 记录（原记录通过 `undone_at` 标记为已撤销）。

### 7.3 操作记录

每次操作（move / delete / rename / new_folder / copy）后自动写入 `operation_history` 表。
写入由 FileOperationService 内部完成，调用方不需要手动写。

- `move` / `delete` / `rename` / `new_folder`：`can_undo=1`，可被撤销。
- `copy`：`can_undo=0`，不可撤销（语义上复制不应反向撤销）。
- `undo`：不写新记录，仅更新原记录的 `undone_at` 字段。
- 自动清理上限：`max_history_records=1000`，写入前预清理；
  仅删除 `can_undo=0` 或 `undone_at IS NOT NULL` 的记录（保留可撤销记录）。

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
      └─ content_unit（候选内容单元）
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

> 阶段 4 Task 4（封面预览）已实现，阶段 5 Task 1a 升级为多尺寸 WebP 缓存。
> 完整流程：UI 请求 → Coordinator 调度 → Worker 在 QThread 中调用
> ThumbnailService.generate → Pillow 只读加载源图并写入缓存 WebP。
> 缓存命中时 UI 同步获得 QPixmap。
>
> **当前实际状态（2026-08-01 复核）**：磁盘缓存基础设施（生成/查询/GC）已实现，
> 但 UI 未接入 Coordinator 请求链路——卡片视图与元数据面板直接以 QPixmap 加载原图
> 并做内存缓存，`request_thumbnail` 无生产调用方（仅测试覆盖）。该差距登记为
> TD-M37，待后续 Task 决定接入缓存链路或简化。

### 分层与职责

- `infrastructure/thumbnail_generator.py`：纯生成逻辑。Pillow 只读加载源图、
  保持宽高比缩放到调用方指定尺寸（默认 256×256，列表/卡片视图基础档位；
  Task 1a 起支持 256/512 双档）、应用圆角遮罩、写入 WebP。
  异常分类：`ThumbnailSourceNotFoundError` / `ThumbnailSourceCorruptError` /
  `ThumbnailSourceUnsupportedError`。
- `infrastructure/repositories/thumbnail_cache.py`：`thumbnail_cache` 表 CRUD
  （v7 起复合主键 (content_unit_id, size)；方法：`get_by_id_and_size` /
  `upsert` / `delete` / `list_all` / `list_by_unit` / `list_by_unit_ids`）。
- `application/thumbnail_service.py`：业务编排。
  - `get_cache(unit_id, source_path, size)`：缓存命中同步返回 Path，未命中返回 None
  - `generate(unit_id, source_path, size)`：生成 + 写入缓存记录，按异常分类记录 status
    （ok / missing / corrupt / unsupported / error）
  - `invalidate(unit_id)`：删除该内容单元所有尺寸的缓存记录与文件（封面更换/清除时调用）
  - `cleanup_orphans()`：启动时清理无对应 content_unit 的缓存记录与孤立缓存文件
    （Q8:B）
- `app/thumbnail_worker.py`：QObject + QThread worker。在 `run()` 内创建独立 SQLite
  连接，调用 `ThumbnailService.generate`，发射 `thumbnail_ready(unit_id, status)`
  或 `thumbnail_failed(unit_id, error)`。
- `app/thumbnail_coordinator.py`：调度器。管理 FIFO 队列 + 去重 set。
  - `request_thumbnail(unit_id, source_path, size=256)`：缓存命中同步返回 QPixmap，未命中
    入队后台生成
  - `thumbnail_ready` 信号 → MainWindow → `FileListModel.notify_thumbnail_ready`
    → 触发对应行 `dataChanged(DecorationRole)` 重绘
  - `shutdown()`：清空队列 + 等待当前 worker 退出（`closeEvent` 调用）
  - **注**：当前 UI 无 `request_thumbnail` 调用方（TD-M37），信号仅由测试链路验证

### 关键约束

- 关联键：`content_unit_id`（v4 起由旧 `asset_id` 改名）
- 源路径：`ContentUnit.path` + `cover_path`（仅 `cover_path` 非空时生成）
- 缩略图缓存目录：数据目录下 `thumbnails\`（数据目录解析见 §10）
- 缓存文件命名：`{content_unit_id}_{size}.webp`（v7 起多档位）
- 缓存有效性基于 `content_unit_id + size + source_size_bytes + source_modified_at + 文件存在`
- 后台线程生成（QThread + 独立 SQLite 连接），不冻结 UI
- 始终只读访问用户原图；不修改、不压缩、不覆盖
- UI 层当前不经过缩略图缓存：FileListModel 使用 Qt 标准图标（Task 1a 决策），
  CardListModel 与 MetadataPanel 直接 QPixmap 加载原图（内存缓存）。TD-M37 未解决前，
  UI 不依赖磁盘缩略图缓存文件

---

## 10. 应用数据目录

数据目录解析优先级（见 `app/app_paths.get_app_data_root()`）：

1. `SCW_DATA_DIR` 环境变量指定路径
2. 项目根 `data/`（开发环境默认）
3. `%LOCALAPPDATA%\SkyrimContentWorkbench\`（Windows 回退）
4. `~/.skyrimmodworkbench/`（非 Windows 回退）

**迁移策略（Task 0.5 用户决策）**：程序**不执行任何自动迁移、复制、删除操作**。
旧目录检测提示代码已于 UX 重构 Task 6（v0.47.0）移除；
`%LOCALAPPDATA%\SkyrimContentWorkbench\` 仍作为 Windows 回退路径保留
（open-questions §7 决策）。

```text
{data_root}/
  ├── app.db              # SQLite 数据库（schema v12）
  ├── thumbnails/         # 缩略图缓存（{content_unit_id}_{size}.webp）
  ├── exports/            # AI JSON 导出
  └── logs/               # 应用日志（app.log，UTF-8，滚动）
```

用户 Mod 文件不应被复制到应用数据目录。唯一例外是缩略图缓存（可随时删除并重建）。

---

## 11. 测试策略

### 11.1 优先测试

- 内容单元 CRUD 与中文路径
- 增量扫描逻辑与 mtime 判断
- 内容单元识别规则（含压缩包 → 候选）
- 文件夹操作（移动/重命名/删除/复制）与安全规则
- 操作历史读写、撤销与上限清理
- 标签 CRUD、自动补全、筛选
- 全局搜索（标题/备注/标签，仅 organized）
- 缩略图多档缓存（256/512）与孤儿清理
- 单面板 UI 数据联动（视图切换/排序/导航/装配面板钉住）
- 数据库迁移（v0→v12 幂等：rating 列移除、UNIQUE 约束、复合主键、CHECK 扩展、status→is_marked、staging_area 移除）

### 11.2 保留的旧测试

以下旧测试可保留或小幅修改继续使用：

- `test_path_utils.py` ✅
- `test_file_classify.py` ✅
- `test_thumbnail_*.py` ✅（需调整关联字段）
- `test_managed_root_*.py` ✅
- `test_scan_worker.py` ✅
- `test_thumbnail_ui.py` ⚠️（需调整关联；当前以 test_thumbnail_coordinator.py / test_thumbnail_service.py 等为准）
- `test_db.py` ✅
- `test_migrations.py` ⚠️（已扩展至 v12）

### 11.3 需重写或移除的旧测试

- `test_mod_assembly_service.py` ❌
- `test_pool_model.py` ❌
- `test_file_operation_service.py` ⚠️（需适配简化版接口）
- `test_main_window.py` ❌（已按主题拆分为多个 test_main_window_*.py）
- `test_folder_tree_*.py` ⚠️（需适配新数据源）

> **注**：上述两表为历史记录（阶段 2/3 时期）。UX 重构与 Stage 5 期间测试已按
> 主题重组（tests/ 下现有 60+ 文件），以当前代码为准。

---

## 12. 旧版架构迁移说明

当前代码（版本 ≤ v0.9.0）实现了旧版架构（ModItem / FileAsset / FileRole / OperationLog 四步状态机），与新架构不兼容。

迁移策略（详见 §6.4 迁移历史摘要）：
1. 阶段 2 Task 1：建立新数据库 schema v4，移除旧表（不迁移旧数据）。
2. 阶段 3 Task 1：schema v4→v5（staging_area 表 + folder_cache 简化）。
3. 阶段 4 Task 1：schema v5→v6（移除 content_unit.rating；tag_category.name 加 UNIQUE；tag (name, category_id) 加 UNIQUE）。
4. 阶段 5 Task 1a：schema v6→v7（thumbnail_cache 改复合主键，PNG → WebP 多档缓存）。
5. 阶段 5 Task 6：schema v7→v8（operation_history 加 undone_at 列，CHECK 扩展 'undo'）。
6. 阶段 5 Task 3b：schema v8→v9（operation_history CHECK 扩展 'copy'）。
7. 阶段 5 Task 7 收尾：schema v9→v10（content_unit.status 简化为 organized/unmarked 两态）。
8. Stage 5 Code Review：schema v10→v11（status→is_marked + path_key + 清理 undo 记录 + 冗余索引清理）。
9. UX 重构 Phase 1 Task 1：schema v11→v12（移除 staging_area 表）。
10. 旧版代码文件逐步改造或重写，不保留旧版 Service 和 UI。
11. 旧版文档已归档至 `archive/`。
