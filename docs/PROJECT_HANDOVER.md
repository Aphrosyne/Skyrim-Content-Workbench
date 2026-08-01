# Skyrim Content Workbench — 项目交接文档

> **本文档用途**：为接手本项目的下一个 AI Coding Agent 提供完整的工程上下文。
> 本文档基于截至 2026-08-01 的代码与文档状态撰写，对应版本 **v0.47.0**，schema_version **v13**，分支 **`ux-redesign`**。
>
> 阅读顺序建议：先读第 1、2、9 章 → 建立宏观认知 → 再读第 3、4 章理解技术细节 → 第 5、6 章了解下一步方向 → 第 7、8 章作为日常开发参考。

---

## ⚠️ 文档与代码冲突提示（先读这一节）

> 本项目经历了方向 C 重写 + UX 重构两轮大调整，部分老文档（特别是 `architecture.md`、`spec.md`、`roadmap.md` 的早期章节）描述的是**重构前**的状态，与当前代码不一致。新 Agent 必须以**代码 + `CHANGELOG.md` + `ux-redesign-roadmap.md`** 为准。下列已知冲突点请在第一次阅读文档时同步校正认知：

| 冲突位置 | 文档描述 | 代码实际状态 | 权威来源 |
|----------|----------|--------------|----------|
| [architecture.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/architecture.md) §2 架构图 | Application Services 列出 `StagingService` | `StagingService` / `StagingAreaRepository` / `staging_area` 表已全部移除（UX 重构 Phase 1 Task 1 + v11→v12 迁移） | [CHANGELOG.md v0.43.0](file:///c:/AphrosyneData/Skyrim-Content-Workbench/CHANGELOG.md) / [main.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main.py) |
| [architecture.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/architecture.md) §3.1 主窗口布局 | `TopBar: 标题 + 置顶按钮 + 搜索框 + [浏览\|整理] 模式切换` | 双模式切换按钮已移除，统一为单面板（UX 重构 Phase 1 Task 1） | [ux-redesign-roadmap.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/ux-redesign-roadmap.md) Phase 1 Task 1 |
| [architecture.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/architecture.md) §3 | `BrowseMode` / `OrganizeMode` 两套中间区布局 | 已无此概念。中栏为统一文件列表（卡片/列表两种视图切换），装配面板已迁移到右栏下方（📌 钉住机制） | [ux-redesign-roadmap.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/ux-redesign-roadmap.md) Phase 1 Task 2/3 |
| [architecture.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/architecture.md) 全文 | schema 描述停留在早期版本 | 当前 `CURRENT_SCHEMA_VERSION = 13`：content_unit 移除 `status`/`is_marked`（纯 DELETE 模式，Task 6）+ `path_key`；operation_history 新增 `undone_at`；staging_area 表已删除 | [db.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/db.py) / [migrations.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/migrations.py) |
| [architecture.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/architecture.md) §Application | 提及 `ModGroupService` | 已重命名为 `ContentUnitCreationService`（D1 决策 A，UI 文本仍保留"Mod 组"） | [content_unit_creation_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/content_unit_creation_service.py) |
| [architecture.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/architecture.md) §Infrastructure | `FileOperationService` 描述为简化版 | `FileOperationService` 实际位于 `src/infrastructure/`，注入了 `FolderCacheSyncHelper` + `ContentUnitRepository`，分层归属存在 TD-H10 待处理 | [file_operation_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/file_operation_service.py) |
| [architecture.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/architecture.md) §缩略图 | `thumbnail_cache.asset_id → content_unit_id` 关联 | 关联键已改为 `content_unit_id`，缓存格式**已实现为 WebP 多档** `{content_unit_id}_{size}.webp`（Task 1a 完成）；仅 `ui_constants.py` 遗留 PNG 单档死常量（THUMBNAIL_FORMAT/FILENAME_TEMPLATE/SIZE，已登记 TD-L31）待 Task 6 清理 | [thumbnail_cache.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/repositories/thumbnail_cache.py) |
| [spec.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/spec.md) §5.2、§7.3 | "整理模式"作为独立模式描述 | 已合并入统一面板，"暂存区"概念已移除，"快速插入"按钮已移除（UX 重构 Phase 1 Task 1 + Phase 1 Task 4） | [ux-redesign-roadmap.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/ux-redesign-roadmap.md) Phase 1 Task 1/4 |
| [spec.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/spec.md) §4.1 ContentUnit | 字段含 `status` | `status` 已重构为 `is_marked: bool`（D2 决策 B，schema v11） | [models.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/domain/models.py) |
| [roadmap.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/roadmap.md) Stage 5 Task 3c | 丢失路径检测 | 已暂停开发，代码归档到 `stage5-task3c-suspended` 分支，主线不包含 | [git branch -vv](file:///c:/AphrosyneData/Skyrim-Content-Workbench/) 输出 |
| [AGENTS.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/AGENTS.md) §架构约束 | "Schema 版本：当前 v3，方向 C 下一阶段迁移到 v4" | 当前已到 v13 | [db.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/db.py) |

**核心原则**：当 `architecture.md` / `spec.md` / `roadmap.md` 与代码或 `CHANGELOG.md` 冲突时，**以代码为准，以 CHANGELOG 为修订史**。`ux-redesign-roadmap.md` 是当前分支的权威计划文档。

---

# 1. 项目概述

## 1.1 项目目标

**Skyrim Content Workbench** 是一个面向 Windows 的、**本地优先（local-first）** 的桌面数字资产管理工具（DAM, Digital Asset Management）。

第一阶段专门优化 Skyrim Mod 的整理与浏览工作流，但核心模型（内容单元 + 路径 + 元数据）设计为可扩展到教程、截图、视频项目等其他资产类型。

项目计划开源，第一版不包含云同步、账号系统或用户数据上传。

## 1.2 解决的问题

用户拥有大量零散放置的本地数字资产（Mod 文件、教程、素材、截图），存在以下痛点：

1. **目录树过深**：旧分类体系 `Armor/Heavy/Female/Black/HDT/BDOR/` 这类深层目录难以维护
2. **文件名不可靠**：Nexus Mods、汉化包、社区分享、预览图之间没有统一命名规律
3. **元数据缺失**：资源管理器只能看文件名，无法显示中文标题、标签、来源、备注
4. **预览图太小**：在资源管理器里查看图片效率低下
5. **整理流程割裂**：下载 → 汉化补丁 → 预览图 → 分类归档散落在多个目录，缺乏统一工作台

本项目通过"内容单元 + 标签系统 + 双视图 + 安全文件操作"组合解决上述问题，**不替代** MO2、Everything 或资源管理器，而是补齐它们都不覆盖的"本地数字资产元数据管理"空白。

## 1.3 当前产品定位

- **本地优先**：所有数据保存在本机，不上传用户文件、路径、图片或元数据
- **真实文件系统是唯一的事实来源**：数据库是元数据增强层，不定义文件组织关系
- **内容单元替代 ModItem + FileAsset**：一个内容单元 = 一个文件夹或一个单文件
- **标签替代深层目录**：目录树保持扁平（建议最多二级分类），细分类由标签承担
- **中文优先**：完整支持中文路径、中文文件名、中文元数据、中文 UI

## 1.4 核心用户流程

### 浏览流程
```
启动应用 → 自动增量扫描（基于目录 mtime）
  → 左栏目录树显示基础分类
  → 选中目录 → 中栏显示该目录下所有文件和文件夹
    ├─ 已标记为内容单元的 → 显示 [内容单元] 标记 + 封面缩略图
    └─ 未标记的 → 正常显示
  → 单击内容单元 → 右栏上半显示元数据，下半显示装配面板（透视其内部文件）
  → 双击文件夹 → 中栏进入该目录
  → 顶部标签筛选栏（同分类 OR，跨分类 AND）
```

### 整理流程（已合并入统一面板，原"整理模式"已移除）
```
选中零散文件（单/多选） → 右键"创建 Mod 组"
  → 自动从文件名提取 Mod 名（剔除版本号/后缀）
  → 在当前目录原地创建文件夹 → 选中文件移入 → 文件夹标记为内容单元
装配面板 📌 钉住 → 中栏右键其他文件 → "添加到钉住文件夹"
  或直接拖拽到装配面板
右栏装配面板空白处 → "移动到……" → 选择目标分类目录 → 文件夹整体移入
```

### 文件操作流程
```
右键文件/文件夹 → 重命名 / 复制 / 剪切 / 粘贴 / 删除 / 移动到…… / 复制路径
  ├─ 重命名：弹窗输入（自动选中文件名部分，不含扩展名）+ 同步更新 ContentUnit.path
  ├─ 删除：移至 Windows 回收站（ctypes SHFileOperation，不引入 send2trash）
  ├─ 移动到：弹出对话框选目标 → 冲突解决（重命名/跳过/覆盖）→ 跨盘检测 → 子目录检测
  └─ 所有操作写入 operation_history，支持撤销（delete 除外）
```

---

# 2. 当前完成状态

> 本项目历经 6 个 Stage + UX 重构 2 个 Phase。版本号遵循 `0.MINOR.PATCH` 语义：MINOR 标记里程碑，PATCH 为同里程碑内修复。

## Stage 1：项目初始化 ✅（v0.1.0，2026-07-07）

**完成内容**：
- Python 3.12+ 项目初始化
- PySide6 空窗口
- SQLite 初始化（schema v0）
- 分层目录结构 `src/{app, application, domain, infrastructure}` + `tests` + `docs`
- ruff + pytest 基础配置
- 应用数据目录创建

**关键技术实现**：
- 数据目录解析优先级：`SCW_DATA_DIR` 环境变量 > 项目根 `data/` > `%LOCALAPPDATA%\SkyrimContentWorkbench\` > `~/.skyrimmodworkbench/`
- 程序**不执行任何自动迁移**，仅提示用户手动迁移（安全约束）
- 测试通过 `SCW_DATA_DIR` 严格隔离测试数据目录

## Stage 2：新骨架 + 基础浏览 ✅（v0.10.0 ~ v0.14.0，2026-07-12 ~ 2026-07-13）

**完成内容**：
- 数据库 Schema v4（新建 content_unit / tag_category / tag / content_unit_tag / operation_history / folder_cache，移除 mod_item / file_asset / folder_node / operation_log 旧表）
- 增量扫描器（基于目录 mtime，跳过未变更目录）
- 内容单元识别规则：所有压缩包文件（.7z/.zip/.rar 等）自动标记，文件夹由用户手动标记
- 目录树浏览（FolderTreeModel 惰性加载，canFetchMore / fetchMore）
- 文件列表显示（中栏显示目录下所有文件，内容单元仅显示标记）
- 双模式切换（**注：已于 UX 重构 Phase 1 Task 1 移除**）
- 扫描完成联动目录树刷新

**关键技术实现**：
- `FileScanner` 递归扫描 + 扩展名分类 + 中文路径支持
- `FolderCache` 作为目录树性能缓存，`parent_id` 用 `make_path_key` 归一化比较
- 扫描后清理已删除目录的 folder_cache 残留（按路径深度降序删除避免 FK 约束冲突）
- 目录树展开状态保持（`save_expanded_paths` / `restore_expanded_paths`）

## Stage 3：暂存区 + 整理工作流 ✅（v0.20.0 ~ v0.20.1，2026-07-17）

**完成内容**：
- 暂存区标记与管理（**注：已于 UX 重构 Phase 1 Task 1 移除**）
- 暂存区文件列表（排序：名称/日期/类型/大小）
- 创建 Mod 组 + 手动修正（Nexus 命名规则适配）
- 装配面板（加入装配 / 移除文件 / 重命名预览图为 Mod 组同名）
- 快速插入（**注：已于 UX 重构 Phase 1 Task 4 移除，由"添加到钉住文件夹" + 拖拽替代**）

**Code Review 修复内容（v0.20.1）**：
- **TD-H7 修复**：`list_by_path_prefix` 分隔符分歧漏匹配 → 新增 `list_by_path_prefix_normalized` 用 `make_path_key` 归一化比较
- **TD-H8 修复**：folder_cache 同步"吞异常 + 上层 commit"导致部分提交态 → 改为抛 `FileOperationError` 触发上层 `_rollback`
- 浏览模式双击导航 UI 状态保持修复
- 新增 10 项技术债（TD-M21 ~ TD-M27、TD-L18 ~ TD-L20）

**关键技术实现**：
- `ContentUnitCreationService.create_content_unit_from_file`（原 `create_mod_group`）：提取名称 → 建文件夹 → 移入文件 → 标记内容单元
- `AssemblyService` 装配面板：`bind_mod_group` / `bind_folder` / `rename_as_cover_by_path`
- Nexus 命名规则：`Mod名称-数字ID-版本号-时间戳` 模式提取

## Stage 4：元数据 + 标签系统 ✅（v0.21.0 ~ v0.34.0，2026-07-19 ~ 2026-07-29）

**完成内容**：
- 标签分类管理 + JSON 导入导出（6 预置分类：服装护甲 / 武器 / 作者 / 来源 / 状态 / 部位）
- 元数据编辑（标题 / 来源 URL / 备注 / 标签 / 封面）
- 批量打标签（多选 → 弹窗 → chip 列表 + 预选标签 + 回车仅添加 chip 不关闭）
- 标签筛选（同分类 OR，跨分类 AND，互斥展开，边框高亮，清除全部）
- 封面预览 + 缩略图缓存（ThumbnailGenerator + ThumbnailService + ThumbnailCacheRepository）
- Stage 4.5：多项技术债修复（TD-H2 扫描事务边界 / TD-M22 folder_cache_sync_helper 抽取 / TD-L18 mtime 同步策略统一 / TD-H4 FileOperationService 自动同步 folder_cache + ContentUnit.path）

**UI 状态**：
- 右栏 MetadataPanel：标题 / 标签 chip / 来源 / 备注 / 封面预览 / 保存按钮（显式保存，非自动保存）
- 顶部 TagFilterBar：分类按钮（互斥展开）→ 标签多选 → 实时筛选
- 列表缩略图：小图标显示封面，缓存命中同步返回，缓存 miss 异步生成

**关键技术实现**：
- `UnitOfWork` 管理多步写事务，Service 内部 `transaction()` 保证原子性
- `FolderCacheSyncHelper`：`on_folder_created` / `on_folder_moved` / `on_folder_deleted` / `update_folder_mtime` 语义化方法，多步同步失败抛 `FileOperationError`
- `ThumbnailCoordinator` + `ThumbnailWorker`：单 worker + FIFO 任务队列，缓存命中同步加载，缓存 miss 异步生成
- 启动 GC 清理孤立缩略图缓存

## Stage 5：浏览增强 + 文件操作 + 交互优化 ✅（v0.35.0 ~ v0.41.0，2026-07-29 ~ 2026-07-31）

**完成内容**：
- Task 0：前置技术债修复（TD-H1 OperationHistory 一致性校验 / TD-L19 delete can_undo=False / TD-M11 _commit 失败 UI 反馈）
- Task 1：卡片视图（FileListModel + CardListModel）
- Task 2：标签筛选交互完善
- Task 3a：新建文件夹 / 重命名 / 删除（移至回收站）
- Task 4：键盘快捷键（14 个）
- Task 6：操作历史与撤销框架（UndoService + 安全校验）
- Task 3b：应用内复制/剪切/粘贴 + 冲突解决（重命名/跳过/覆盖）
- Task 5：移动到...快捷对话框
- Task 7：全局搜索（LIKE 查询，仅搜索 is_marked=1）+ ContentUnit.status 简化
- Code Review：8 批次修复 + schema v11 迁移（D1 代码层重命名 / D2-D3 status→is_marked / D4 撤销不记录 / H5 path_key / M12 冗余索引清理）

**当前达到的能力**：
- 完整的浏览 + 整理 + 元数据 + 标签 + 搜索 + 文件操作 + 撤销工作流
- 中文路径全链路支持
- 操作历史与安全撤销（move / rename / new_folder 可撤销，delete 由回收站兜底）
- 冲突解决（重命名/跳过/覆盖）
- 跨盘移动检测与拒绝
- 子目录检测与阻止

## UX 重构 Phase 1：Workspace 重构 ✅（v0.42.0 ~ v0.45.0，2026-08-01）

**完成内容**：
- Task 1：移除双模式切换 + 移除暂存区功能（staging_area 表 v11→v12 迁移删除） + 多选创建 Mod 组
- Task 2：装配面板从中间区分割区迁移到右栏下方（元数据上 + 装配下，3:2 比例）+ 装配面板语义扩展为"文件夹透视器"（可透视任意文件夹）
- Task 3：📌 钉住功能（钉住后中栏操作不切换装配面板绑定，取消钉住跟随中栏）
- Task 4：移除"快速插入"功能 + 新增"添加到钉住文件夹"菜单项 + 中栏/装配面板拖拽支持 + 3 项验收修复（钉住文件夹内操作后装配面板同步刷新 / 重命名后中栏内容消失系统性修复 / 程序启动多个小窗口闪过修复）

**UI 状态**：
- 单面板统一工作区（无模式切换）
- 左栏目录树 + 中栏文件列表（卡片/列表两种视图） + 右栏（元数据上 + 装配下）
- 装配面板支持 📌 钉住 + 拖拽接受文件 + 右键菜单完整继承中栏操作

## UX 重构 Phase 2 Task 5：交互细节优化 ✅（v0.46.0，2026-08-01）

**完成内容**：
- 右键菜单统一（新增"打开" / "钉住此文件夹" / "取消钉住" / 中栏"粘贴"项）
- QMessageBox 系统提示音抑制（`message_box_helper.py` patch `setIcon(NoIcon)` + `setIconPixmap`）
- 操作历史显示优化（移除描述列改用 Tooltip / 过滤已撤销 / 删除操作灰色 / 操作类型中文化 / 新增 copy 分支文案）
- 撤销循环 bug 修复（`FileOperationService.move/rename` 新增 `record_history: bool = True` 参数，UndoService 调用时传 `False`）
- 刷新按钮 + F5 快捷键（仅刷新当前目录和目录树对应节点）
- 状态栏统一（Qt 标准 QStatusBar，移除左侧扫描状态 QGroupBox）
- 路径简化显示（`path_display.py`，左栏目录详情 + 右栏元数据 + 操作历史 Tooltip 均应用，相对路径包含根目录名，外部路径加 `[外部]` 前缀）
- 空状态提示（搜索无结果 / 目录为空）

---

# 3. 当前架构说明

## 3.1 分层架构总览

```text
┌──────────────────────────────────────────────────────────┐
│  UI 层 (src/app/)                                         │
│  PySide6 主窗口 / TreeView / ListView / 元数据面板 /     │
│  装配面板 / 各类对话框                                    │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Application 层 (src/application/)                 │  │
│  │  ContentService / ContentUnitCreationService /     │  │
│  │  AssemblyService / TagService / SearchService /    │  │
│  │  ScanService / FolderTreeService /                 │  │
│  │  ManagedRootService / UndoService /                │  │
│  │  ClipboardService / ThumbnailService               │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Domain 层 (src/domain/)                           │  │
│  │  ContentUnit / TagCategory / Tag /                 │  │
│  │  ContentUnitTag / OperationHistory /               │  │
│  │  ManagedRoot / FolderCache / ThumbnailCache        │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Infrastructure 层 (src/infrastructure/)           │  │
│  │  db.py / migrations.py / path_utils.py /           │  │
│  │  file_scanner.py / file_operation_service.py /     │  │
│  │  file_classify.py / folder_cache_sync_helper.py /  │  │
│  │  thumbnail_generator.py / windows_recycle_bin.py / │  │
│  │  unit_of_work.py / repositories/*                  │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### 分层规则（不可违反）

- **UI 层**不直接访问 Repository 或文件系统写操作，通过 Application Service 调用
- **Application 层**协调 UI 与领域逻辑，不包含领域规则（领域规则在 Domain 层实体校验中）
- **Domain 层**为纯 dataclass，不包含数据库或文件系统知识
- **Infrastructure 层**为唯一允许直接操作数据库和文件系统的模块
- **已知分层违反**（TD-H10，待 UI 重构 Task 7 处理）：`FileOperationService` 位于 infrastructure 层，但注入了 `FolderCacheSyncHelper` + `ContentUnitRepository`，长期应迁移到 application 层

## 3.2 UI 层（`src/app/`）

### 主要模块职责

| 文件 | 职责 | 当前状态 |
|------|------|----------|
| [main.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main.py) | 应用入口 + 组合根（依赖注入装配） | 稳定 |
| [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py) | 主窗口（**约 3490 行 / 150 方法 God Object，TD-M31**） | 风险高，待 Task 7 拆分 |
| [folder_tree_model.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/folder_tree_model.py) | 目录树 QAbstractItemModel（惰性加载） | 稳定 |
| [file_list_model.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/file_list_model.py) | 中栏文件列表 QAbstractListModel（详细列表视图） | 稳定 |
| [card_list_model.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/card_list_model.py) | 中栏卡片视图 QAbstractListModel | 稳定 |
| [metadata_panel.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/metadata_panel.py) | 右栏元数据编辑面板 | 稳定 |
| [assembly_panel.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/assembly_panel.py) | 右栏装配面板（文件夹透视器 + 📌 钉住 + drop target） | 稳定 |
| [tag_filter.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/tag_filter.py) | 顶部标签筛选栏 | 稳定 |
| [tag_manager_dialog.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/tag_manager_dialog.py) | 标签管理对话框（CRUD + JSON 导入导出） | 稳定 |
| [batch_tag_dialog.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/batch_tag_dialog.py) | 批量打标签对话框 | 稳定 |
| [cover_picker_dialog.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/cover_picker_dialog.py) | 封面选择对话框 | 稳定 |
| [operation_history_dialog.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/operation_history_dialog.py) | 操作历史对话框（含撤销） | 稳定 |
| [move_to_dialog.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/move_to_dialog.py) | 移动到...目标选择对话框 | 稳定 |
| [conflict_resolution_dialog.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/conflict_resolution_dialog.py) | 冲突解决对话框（重命名/跳过/覆盖） | 稳定 |
| [search_dialog.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/search_dialog.py) | 全局搜索对话框 | 稳定 |
| [scan_worker.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/scan_worker.py) | 扫描后台 QThread worker | 稳定（TD-M13 进度信号未连接） |
| [thumbnail_worker.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/thumbnail_worker.py) | 缩略图生成 QThread worker | 稳定 |
| [thumbnail_coordinator.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/thumbnail_coordinator.py) | 缩略图任务队列协调器（单 worker + FIFO） | 稳定 |
| [app_paths.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/app_paths.py) | 应用数据目录路径解析 | 稳定 |
| [logging_setup.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/logging_setup.py) | 日志初始化（写入 `data/logs/app.log`） | 稳定 |
| [ui_constants.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/ui_constants.py) | UI 文案常量集中定义 | 稳定 |
| [path_display.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/path_display.py) | 路径简化显示工具（v0.46.0 新增） | 稳定 |
| [message_box_helper.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/message_box_helper.py) | QMessageBox 提示音抑制（v0.46.0 新增） | 稳定 |

## 3.3 Application Service 层（`src/application/`）

| 文件 | 职责 | 关键接口 |
|------|------|----------|
| [content_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/content_service.py) | 内容单元管理（元数据 CRUD + 目录列表 + 标记/取消标记） | `list_directory_entries` / `update_metadata` / `mark_as_content_unit` / `unmark_content_unit` |
| [content_unit_creation_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/content_unit_creation_service.py) | 创建 Mod 组（提取名称 → 建文件夹 → 移入文件 → 标记） | `create_content_unit_from_file` / `create_content_unit_from_files` |
| [assembly_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/assembly_service.py) | 装配面板（文件夹透视 + 图片重命名为封面） | `list_folder_files` / `bind_mod_group` / `rename_as_cover_by_path` |
| [tag_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/tag_service.py) | 标签系统（分类 CRUD + 标签 CRUD + JSON 导入导出 + 预置加载） | `get_categories` / `search_tags` / `filter_by_tags` / `load_default_tags_if_empty` |
| [search_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/search_service.py) | 全局搜索（LIKE 查询标题 + 标签 + 备注；v13 纯 DELETE 模式：记录存在即已标记，无过滤条件） | `search` |
| [scan_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/scan_service.py) | 扫描（增量 + 全量，UnitOfWork 事务边界） | `scan_all` / `scan_root` |
| [folder_tree_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/folder_tree_service.py) | 目录树数据源（从 FolderCache + ManagedRoot 构建 TreeNode） | `list_root_nodes` / `list_children` / `count_children` |
| [managed_root_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/managed_root_service.py) | 受管理根目录 CRUD | `add_root` / `remove_root` / `list_roots` |
| [undo_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/undo_service.py) | 操作历史撤销（安全校验 + 反向操作 + 标记 undone_at） | `undo` / `list_history` |
| [clipboard_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/clipboard_service.py) | 应用内剪贴板（Q3=A 不与系统剪贴板混用） | `copy` / `cut` / `paste` / `has_entries` |
| [thumbnail_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/thumbnail_service.py) | 缩略图缓存管理（生成 + 取 + GC 清理孤立） | `get_thumbnail` / `cleanup_orphans` |
| [errors.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/errors.py) | 应用层异常基类 | `ApplicationError` / `ContentUnitNotFoundError` 等 |

## 3.4 Domain 层（`src/domain/models.py`）

所有实体为纯 dataclass，`__post_init__` 中包含领域校验：

```python
ContentUnit
  - id: str (UUID)
  - path: str (真实路径，可为中文)
  - path_key 为 DB 层列（UNIQUE 约束），Domain 实体不含该字段
  - title: str | None (中文别名)
  - content_type: str (VALID_CONTENT_TYPES = frozenset({"mod"}))
  - source_url: str | None
  - cover_path: str | None (相对内容单元路径)
  - notes: str | None
  - created_at: str (ISO 8601 UTC)
  - updated_at: str (ISO 8601 UTC)

> v13（UX 重构 Task 6）移除 is_marked 字段：标记 = 记录存在，取消标记 = DELETE 记录。

TagCategory
  - id, name, color_hue: int

Tag
  - id, name, category_id

ContentUnitTag (多对多)
  - content_unit_id, tag_id

OperationHistory
  - id, operation_type (VALID: move/delete/rename/new_folder/copy/undo)
  - source_path, target_path: str | None
  - created_at, can_undo: bool
  - undone_at: str | None (D4 决策：撤销标记原记录，不写新记录)
  - 校验：move/rename/new_folder 要求 target_path 非空；delete 要求 target_path 为 None 且 can_undo=False

ManagedRoot
  - id, real_path, path_key (UNIQUE), display_name, created_at, updated_at

FolderCache
  - id, path (UNIQUE), parent_id: str | None, mtime: float, created_at

ThumbnailCache
  - content_unit_id (FK), source_size_bytes, source_modified_at, cache_filename, status, ...
```

## 3.5 Infrastructure 层（`src/infrastructure/`）

| 文件 | 职责 |
|------|------|
| [db.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/db.py) | SQLite 连接管理 + `init_db` 迁移执行（`CURRENT_SCHEMA_VERSION = 12`） |
| [migrations.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/migrations.py) | v0→v12 迁移函数注册表（每步独立事务，幂等） |
| [path_utils.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/path_utils.py) | `make_path_key`（normcase + normpath）路径归一化 |
| [file_scanner.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/file_scanner.py) | 递归扫描 + 增量扫描（mtime 比较）+ 压缩包识别 |
| [file_operation_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/file_operation_service.py) | 文件操作（move/rename/delete/new_folder/copy）+ folder_cache 自动同步 + operation_history 记录（`record_history` 参数） |
| [file_classify.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/file_classify.py) | `ARCHIVE_EXTENSIONS` + `get_extension`（其余死代码已清理） |
| [folder_cache_sync_helper.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/folder_cache_sync_helper.py) | folder_cache 语义化同步（on_folder_created/moved/deleted + update_folder_mtime） |
| [thumbnail_generator.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/thumbnail_generator.py) | Pillow 只读加载 + 缩略图生成（不修改原图） |
| [windows_recycle_bin.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/windows_recycle_bin.py) | ctypes 调用 `SHFileOperation` 移至回收站（Q1=B 不引入 send2trash） |
| [unit_of_work.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/unit_of_work.py) | UnitOfWork 事务管理（`transaction()` 上下文管理器） |
| [repositories/](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/repositories/) | 各表 Repository（content_unit / content_unit_tag / folder_cache / managed_root / operation_history / search / tag / tag_category / thumbnail_cache） |

**关键约束**：Repository 不自提交（H5 修复后），由 Service 层通过 UnitOfWork 控制事务边界。

## 3.6 数据库结构

### 当前 Schema（v13）

```sql
-- schema 版本管理
CREATE TABLE schema_version (
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 受管理根目录（扫描范围限定）
CREATE TABLE managed_root (
    id TEXT PRIMARY KEY,
    real_path TEXT NOT NULL,
    path_key TEXT NOT NULL UNIQUE,
    display_name TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 内容单元（核心元数据）
CREATE TABLE content_unit (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    path_key TEXT NOT NULL UNIQUE,  -- v11 新增，DB 层强制路径归一化唯一
    title TEXT,
    content_type TEXT NOT NULL DEFAULT 'mod',
    source_url TEXT,
    cover_path TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 标签分类
CREATE TABLE tag_category (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    color_hue INTEGER NOT NULL
);

-- 标签
CREATE TABLE tag (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category_id TEXT NOT NULL,
    UNIQUE(name, category_id),
    FOREIGN KEY (category_id) REFERENCES tag_category(id)
);

-- 内容单元 ↔ 标签（多对多）
CREATE TABLE content_unit_tag (
    content_unit_id TEXT NOT NULL,
    tag_id TEXT NOT NULL,
    PRIMARY KEY (content_unit_id, tag_id),
    FOREIGN KEY (content_unit_id) REFERENCES content_unit(id),
    FOREIGN KEY (tag_id) REFERENCES tag(id)
);

-- 目录树性能缓存
CREATE TABLE folder_cache (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    parent_id TEXT,
    mtime REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (parent_id) REFERENCES folder_cache(id)
);

-- 操作历史
CREATE TABLE operation_history (
    id TEXT PRIMARY KEY,
    operation_type TEXT NOT NULL CHECK(operation_type IN
        ('move', 'delete', 'rename', 'new_folder', 'copy', 'undo')),
    source_path TEXT NOT NULL,
    target_path TEXT,
    created_at TEXT NOT NULL,
    can_undo INTEGER NOT NULL DEFAULT 1,
    undone_at TEXT  -- v11 新增，撤销标记原记录（D4 决策：不写新记录）
);

-- 缩略图缓存（关联键 content_unit_id）
CREATE TABLE thumbnail_cache (
    content_unit_id TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 64,  -- 缓存档位（64 旧档/256/512），复合主键
    source_size_bytes INTEGER NOT NULL,
    source_modified_at TEXT NOT NULL,
    cache_filename TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('ok','missing','corrupt','unsupported','error')),
    error_message TEXT,
    generated_at TEXT NOT NULL,
    PRIMARY KEY (content_unit_id, size)
);
```

### 数据关系

- `content_unit.path_key` UNIQUE 约束防止"同一路径不同表示"的重复记录（Windows 大小写不敏感）
- `content_unit_tag` 多对多关联；schema 未声明 ON DELETE CASCADE，
  由 `ContentUnitRepository.delete` 显式清理关联（仓储 docstring 说明）
- `folder_cache.parent_id` 自引用 FK；无 CASCADE，扫描清理按路径深度降序删除
  避免 FK 冲突，文件操作同步由 `FolderCacheSyncHelper` 语义化处理
- `thumbnail_cache` 复合主键 (content_unit_id, size)，一个内容单元多档缓存；
  无 FK 声明，孤儿记录/文件由启动 GC（ThumbnailService.cleanup_orphans）清理
- `operation_history` 无 FK 关联其他表，独立历史记录

### 迁移历史

| 版本 | 内容 |
|------|------|
| v0→v1 | 初始 schema（旧版 ModItem/FileAsset 体系） |
| v3→v4 | 方向 C 重写：新建 content_unit/tag/operation_history/folder_cache，移除旧表 |
| v4→v5 | staging_area 表（**v12 已删除**） |
| v9→v10 | operation_history 增加 copy 操作 |
| v10→v11 | **重大变更**：status→is_marked + path_key UNIQUE + 清理 undo 记录 + 冗余索引清理 |
| v11→v12 | 移除 staging_area 表（UX 重构 Phase 1 Task 1） |
| v12→v13 | **纯 DELETE 模式**：清理 is_marked=0 记录及关联 → 移除 is_marked 列（UX 重构 Task 6） |

## 3.7 文件扫描流程

```
应用启动
  ↓
ScanService.scan_all() 触发
  ↓
ScanWorker（独立 QThread + 独立 connection）
  ↓
FileScanner.scan_directory(managed_root)
  ├─ 增量扫描：对比 folder_cache.mtime 与当前目录 mtime
  │   ├─ 相等 → 跳过
  │   └─ 不等 → 重新扫描该目录及子目录
  ├─ 内容单元识别：所有压缩包文件（.7z/.zip/.rar 等）自动标记
  ├─ 跳过已被标记为内容单元的目录内部
  └─ 收集 all_visited_dirs（用于清理已删除目录的 folder_cache 残留）
  ↓
ScanService._persist_scan_result（UnitOfWork 事务边界）
  ├─ upsert folder_cache（path / parent_id / mtime）
  ├─ upsert content_unit（压缩包文件 → is_marked=1）
  └─ 删除 all_visited_dirs 之外的 folder_cache 残留（按路径深度降序避免 FK 冲突）
  ↓
ScanWorker.finished 信号 → MainWindow._refresh_content_list_after_scan
  ├─ 目录树刷新（保持展开状态与选中节点）
  └─ 中栏文件列表刷新
```

**关键设计**：
- 增量扫描不是绝对保证（某些操作可能不更新 mtime），用户可手动全量重扫兜底
- 不做实时文件系统监听（避免 CPU 负载影响游戏）
- 扫描结果持久化在 UnitOfWork 事务内，任一失败整体回滚

## 3.8 文件操作流程

### 移动操作（move）

```
UI 触发（右键"移动到……" / 拖拽 / "添加到钉住文件夹"）
  ↓
MainWindow._perform_move_to(src_paths, dst_dir, refresh_assembly=False)
  ├─ 跨盘检测 → CrossDriveError（move）/ FileOperationError（rename，TD-M35 不一致）
  ├─ 子目录检测 → SelfSubdirectoryError
  ├─ 冲突检测 → ConflictResolutionDialog（重命名/跳过/覆盖）
  └─ FileOperationService.move(src, dst, conflict_policy, record_history=True)
      ├─ shutil.move 真实移动
      ├─ FolderCacheSyncHelper.on_folder_moved（删旧 folder_cache + 插新 + 更新父 mtime）
      ├─ ContentUnitRepository.update_path（同步 ContentUnit.path + path_key）
      └─ OperationHistoryRepository.insert（move 记录，can_undo=True）
  ↓
UnitOfWork.transaction() 提交
  ├─ 成功 → 刷新中栏 / 目录树 / 装配面板（如受影响）
  └─ 失败 → _rollback + QMessageBox.critical（TD-M11 修复）
```

**已知风险**（TD-H12）：文件已成功 + DB 同步失败时，文件无法回滚，仅抛 `FileOperationError` 让 UoW 回滚 DB。导致文件系统与 DB 状态不一致。待 Stage 6 引入补偿日志机制。

### 删除操作（delete）

```
UI 触发 → FileOperationService.delete(path)
  ├─ windows_recycle_bin.send_to_recycle_bin(path)（ctypes SHFileOperation）
  ├─ FolderCacheSyncHelper.on_folder_deleted（删除 folder_cache 记录）
  ├─ ContentUnitRepository.delete（删除 content_unit 记录）
  └─ OperationHistoryRepository.insert（delete 记录，can_undo=False）
```

撤销能力由 Windows 回收站提供，应用内不可撤销。

### 撤销操作（undo）

```
OperationHistoryDialog → 选中可撤销记录 → UndoService.undo(history_id)
  ├─ _safety_check：文件存在性 + 路径有效性（TD-M32：无 size/mtime 比对）
  ├─ 反向操作：
  │   ├─ move → 反向 move（target → source，record_history=False 避免循环）
  │   ├─ rename → 反向 rename（record_history=False）
  │   └─ new_folder → 反向 delete（移至回收站）
  └─ mark_undone：标记原记录 undone_at（D4 决策：不写新记录）
```

**关键修复**（v0.46.0）：`record_history=False` 参数避免撤销时产生新的可撤销记录导致无限循环。

---

# 4. 当前代码状态

## 4.1 已经稳定的模块

### UI 层

#### [main.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main.py)
- **职责**：应用入口 + 组合根（依赖注入装配所有 Service）
- **当前状态**：稳定。所有 Service 在此实例化并注入 MainWindow。UnitOfWork 绑定主线程连接，所有 Service 共享同一实例支持嵌套事务。

#### [folder_tree_model.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/folder_tree_model.py)
- **职责**：目录树 QAbstractItemModel，惰性加载（canFetchMore / fetchMore）
- **当前状态**：稳定。rowCount 纯查询不触发 _fetch（无无限递归问题，Q7 已关闭）。

#### [file_list_model.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/file_list_model.py) / [card_list_model.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/card_list_model.py)
- **职责**：中栏文件列表（详细列表 / 卡片视图）QAbstractListModel
- **当前状态**：稳定。支持 mimeData 拖拽（v0.45.0 新增）。两套模型存在维护成本，Task 7 考虑统一（登记为技术债）。

#### [metadata_panel.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/metadata_panel.py)
- **职责**：右栏元数据编辑面板（标题 / 标签 chip / 来源 / 备注 / 封面预览 / 保存按钮）
- **当前状态**：稳定。v0.46.0 注入 `set_managed_root_service` 支持路径简化显示。

#### [assembly_panel.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/assembly_panel.py)
- **职责**：右栏装配面板（文件夹透视器 + 📌 钉住 + drop target）
- **当前状态**：稳定。语义已从"Mod 组装配"扩展为"任意文件夹透视器"。支持 dragEnterEvent/dragMoveEvent/dropEvent（仅钉住时接受）。

#### 各对话框（tag_manager / batch_tag / cover_picker / operation_history / move_to / conflict_resolution / search）
- **当前状态**：稳定。各自独立 QDialog，复用 ui_constants 文案。

#### [thumbnail_coordinator.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/thumbnail_coordinator.py) + [thumbnail_worker.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/thumbnail_worker.py)
- **职责**：缩略图任务队列（单 worker + FIFO）
- **当前状态**：稳定。缓存命中同步返回，缓存 miss 异步生成。Coordinator 生命周期由 MainWindow 管理，closeEvent 等待退出。

#### [ui_constants.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/ui_constants.py)
- **职责**：UI 文案常量集中定义
- **当前状态**：稳定。所有 UI 文本必须在此定义（AGENTS 规则）。

#### [path_display.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/path_display.py)（v0.46.0 新增）
- **职责**：路径简化显示（从受管理根目录开始显示，含根目录名；外部路径加 `[外部]` 前缀）
- **当前状态**：稳定。8 个测试用例覆盖。

#### [message_box_helper.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/message_box_helper.py)（v0.46.0 新增）
- **职责**：抑制 QMessageBox 系统提示音（patch `setIcon(NoIcon)` + `setIconPixmap` 保留视觉图标）
- **当前状态**：稳定。MainWindow.__init__ 调用一次，幂等。

### Application 层

所有 Service 均稳定，关键约束：
- Service 不自提交，通过 UnitOfWork 控制事务
- Service 间调用支持嵌套事务（共享同一 UnitOfWork 实例）
- `except Exception` 已收窄为具体异常类型（TD-M25 修复），编程错误在开发期直接冒泡

### Domain 层

[models.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/domain/models.py) 稳定。所有实体 `__post_init__` 包含领域校验（content_type 取值范围 / is_marked bool 类型 / OperationHistory operation_type 与 target_path 一致性）。

### Infrastructure 层

#### [db.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/db.py) / [migrations.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/migrations.py)
- **当前状态**：稳定。`CURRENT_SCHEMA_VERSION = 12`，12 个迁移函数注册表，每步独立事务，幂等。

#### [path_utils.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/path_utils.py)
- **当前状态**：稳定。`make_path_key`（normcase + normpath）是全项目路径比较与唯一约束的基础。

#### [file_scanner.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/file_scanner.py)
- **当前状态**：稳定。增量扫描 + 压缩包识别 + 中文路径支持。

#### [folder_cache_sync_helper.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/folder_cache_sync_helper.py)
- **当前状态**：稳定。Stage 4.5 抽取，消除 4 处重复同步逻辑。语义化方法：`on_folder_created` / `on_folder_moved` / `on_folder_deleted` / `update_folder_mtime`。

#### [windows_recycle_bin.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/windows_recycle_bin.py)
- **当前状态**：稳定。ctypes `SHFileOperation` 实现，不引入 send2trash。

#### [unit_of_work.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/unit_of_work.py)
- **当前状态**：稳定。`transaction()` 上下文管理器保证原子性。

#### repositories/
- **当前状态**：稳定。Repository 不自提交（H5 修复后）。`ContentUnitRepository.list_by_path_prefix_normalized` 是分隔符分歧场景下的正确接口（TD-H7 修复，旧 `list_by_path_prefix` 已删除）。

## 4.2 存在风险的模块

### [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py)（**最高风险**）

- **技术债**：TD-M21 + TD-M31
- **现状**：约 3490 行 / 150 个方法 / 60+ 实例变量 / 6 个并行状态机（2026-08-01 复核）
- **承担职责**：UI 搭建 + 信号槽 + 扫描线程生命周期 + 装配面板绑定 + 文件操作编排 + 冲突解决编排（2 个重复方法）+ 21 处 `_commit()` + 事务边界 + 14 个快捷键 handler + 导航历史栈
- **影响**：任何 UI 改动成本极高，UI 层承担了本应在 Application 层的事务边界职责
- **修复方案**：UX 重构 Phase 2 Task 7 拆分（至少拆出 `ScanController` / `AssemblyController` / `MetadataView` / `ModeController` / `TransactionScope`）
- **当前状态**：登记为技术债，待 Task 7 处理。Phase 2 编码约束"不再往 MainWindow 堆方法，新增逻辑尽量抽到独立 controller / helper / view 中"

### [file_operation_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/file_operation_service.py)

- **技术债**：TD-H10（分层违反）+ TD-L25（访问 helper 私有 `_repo`）+ TD-M35（rename/move 跨盘异常类型不一致）+ TD-H12（文件操作与 DB 事务不一致窗口未补偿）
- **现状**：位于 infrastructure 层，但注入了 `FolderCacheSyncHelper` + `ContentUnitRepository`，分层归属违反
- **修复方案**：UI 重构 Task 7 时迁移到 application 层
- **当前状态**：D5 决策 B（延后处理），当前代码保持现状

### [undo_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/undo_service.py)

- **技术债**：TD-M32（安全校验无 size/mtime 比对）+ TD-M33（mark_undone 失败可能导致重复撤销）
- **现状**：撤销安全校验仅诊断记录，未存储操作前快照，无法检测文件已被外部修改
- **修复方案**：Stage 6 schema 扩展存储操作前快照（size + mtime），undo 前比对
- **当前状态**：登记为技术债，Stage 6 处理

### [scan_worker.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/scan_worker.py)

- **技术债**：TD-M13（scan_progress 信号声明但不更新进度）+ TD-M15（线程生命周期无集成测试）+ TD-M27（SQLite 并发写未测试）
- **现状**：扫描进度信号仅在 run() 开头发送一次，大型目录扫描持续数十秒用户只看到静态"正在扫描…"
- **修复方案**：ScanService 增加进度回调，ScanWorker 转发，MainWindow 连接更新状态栏
- **当前状态**：登记为技术债，非阻塞

### 性能风险（TD-H3 + TD-M28 + TD-M9）

- **位置**：[content_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/content_service.py) `list_directory_entries` + [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py) `_refresh_content_list`
- **现状**：每个目录条目执行 3 次系统调用（is_symlink/is_dir/stat）+ 1 次独立 DB 查询（get_by_path）。大目录（数百文件）UI 可冻结数百毫秒至数秒
- **修复方案**：批量查询替代 N+1；将 list_directory_entries 移入后台线程或加 mtime 缓存
- **当前状态**：登记为技术债，非阻塞但影响基本可用性

### 设计妥协

1. **`is_marked` 字段语义偏离纯 DELETE 模式**：✅ 已解决（UX 重构 Phase 2 Task 6，
   schema v13 移除 is_marked，取消标记 = DELETE 记录）
2. **FileListView 未统一**：FileListModel（中栏）和 AssemblyListModel（装配面板）两套模型，维护两份，Task 7 考虑统一
3. **schema CHECK 约束保留 'undo'**：D4 决策撤销不再写入新记录，但 CHECK 约束含 'undo'（向后兼容，不重建表）
4. **`content_unit.content_type` 默认 'mod'**：与实体名 ContentUnit 不一致（TD-L23），未来支持多类型时重构
5. **缩略图 Coordinator 链路未接入 UI（TD-M37）**：磁盘 WebP 缓存基础设施已实现，
   但 UI（卡片视图/元数据面板）直接加载原图 QPixmap，`request_thumbnail` 无生产调用方

---

# 5. 当前开发重点

## 5.1 UX redesign 阶段目标

当前处于 **UX 重构 Phase 2**，已完成 Task 5（交互细节优化）与 Task 6（数据库与死代码清理，
v0.47.0），下一步重点：

### Phase 2 剩余任务

#### Task 6：数据库与死代码清理
- 移除受管理根目录时同步清理 `folder_cache` 和内容单元记录 — ✅ 已完成（重叠守卫 + UoW）
- 清理 `is_marked=0` 记录、取消标记改为 DELETE、移除 `is_marked` 字段（schema v13），回归纯 DELETE 模式 — ✅ 已完成
- 移除 `%LOCALAPPDATA%\SkyrimContentWorkbench\` 旧目录检测/迁移代码 — ✅ 已完成（`%LOCALAPPDATA%` 路径回退保留）
- 确保 `data/` 目录结构完整并加入 `.gitignore` — ✅ 已完成（目录齐全，`.gitignore` 含 `/data/`）
- 死代码清理 TD-L31/L32/L33 — ✅ 已完成（ui_constants 死常量 / AssemblyService.remove_file / 模式注释）

#### Task 7：MainWindow 拆分（**重点**）
- 来源：TD-M21 + TD-M31
- 至少拆出：
  - `ScanController`（扫描线程生命周期 + 信号转发）
  - `AssemblyController`（装配面板绑定 / 回调）
  - `MetadataView`（元数据编辑面板）
  - `TransactionScope`（`_commit` / `_rollback` 从事务编排中解耦）
- 同步处理：TD-H10（FileOperationService 分层归属）+ TD-L25（helper 私有访问）+ TD-M26（MainWindow 集成测试）+ TD-M35（跨盘异常类型统一）

### Phase 3：UI 美化（Task 8）
- 用多模态 AI 分析当前界面截图，生成 UI 重构提示词
- 统一配色、间距、字体、图标
- 暗色模式支持（QSS 颜色变量提取，TD-L21）
- 考虑引入轻量 Toast 通知组件替代部分 QMessageBox

### Phase 4：真实 Mod 库验证（Task 9）
- 导入现有 Mod 库，执行完整整理流程
- 记录不符合预期的行为 → 形成修复清单

## 5.2 当前痛点

1. **MainWindow God Object**：约 3490 行 / 150 方法（2026-08-01 复核），任何改动成本极高，事务边界泄漏到 UI 层
2. **文件列表加载性能**：大目录 N+1 查询导致 UI 冻结
3. **撤销安全性不足**：无 size/mtime 比对，可能覆盖用户外部修改
4. **文件操作与 DB 事务不一致窗口**：文件已移动 + DB 同步失败时无法回滚
5. **`is_marked` 字段语义偏离**：✅ 已解决（UX 重构 Task 6，schema v13 纯 DELETE 模式）
6. **文档与代码不同步**：architecture.md / spec.md / roadmap.md 部分内容过时（见第 0 节冲突表）

## 5.3 计划修改方向

- **拆分 MainWindow**：Phase 2 Task 7，将事务边界移到 Application 层
- **清理 is_marked 字段**：✅ 已完成（Phase 2 Task 6，schema v13 纯 DELETE 模式）
- **性能优化**：批量查询替代 N+1，后台线程加载文件列表
- **撤销安全增强**：Stage 6 schema 扩展存储操作前快照
- **数据一致性补偿**：Stage 6 引入补偿日志机制处理文件操作与 DB 事务不一致

## 5.4 不应该破坏的已有能力

新 Agent 在任何改动中必须保证以下能力不被破坏：

1. **中文路径全链路支持**（扫描 / 数据库 / UI / 文件操作 / 撤销）
2. **真实文件系统是唯一事实来源**（数据库仅保存目录无法表达的信息）
3. **所有文件操作经用户确认**（移动确认 / 冲突解决 / 跨盘提示 / 子目录阻止 / 删除至回收站）
4. **所有文件操作通过 FileOperationService**（UI 层不直接调用 shutil / os.rename / Path.rename）
5. **路径比较与唯一约束使用 `make_path_key`**（不依赖字符串大小写比较）
6. **缩略图缓存写入应用数据目录**（不修改用户原图）
7. **数据库 schema 变更使用迁移函数**（在 migrations.py 中注册，幂等）
8. **UI 文本集中在 ui_constants.py**
9. **分层架构**（UI → Application → Domain → Infrastructure，上层依赖下层）
10. **操作历史与撤销**（move/rename/new_folder 可撤销，delete 由回收站兜底，撤销不写新记录）

---

# 6. 未完成事项列表

> 优先级：P0 必须解决 / P1 重要优化 / P2 未来功能

## P0：必须解决

### P0-1：MainWindow God Object 拆分（TD-M21 + TD-M31）

- **问题**：约 3490 行 / 150 方法 / 60+ 实例变量（2026-08-01 复核），事务边界泄漏到 UI 层
- **原因**：Stage 4/5 期间 Q8:C 决策"边开发边小规模拆分"实际未执行
- **推荐方案**：UX 重构 Phase 2 Task 7，至少拆出 `ScanController` / `AssemblyController` / `MetadataView` / `TransactionScope`
- **影响范围**：UI 层全部，但不动业务逻辑，仅结构调整
- **权威来源**：[ux-redesign-roadmap.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/ux-redesign-roadmap.md) Task 7

### P0-2：文档与代码同步

- **问题**：architecture.md / spec.md / roadmap.md 部分内容描述重构前状态，误导新 Agent
- **原因**：UX 重构 Phase 1 移除双模式 + 暂存区后未同步更新老文档
- **推荐方案**：以本交接文档第 0 节冲突表为指引，逐项更新 architecture.md（特别是 §2 架构图、§3.1 主窗口布局、§Application Services 列表、§schema 描述）
- **影响范围**：文档可维护性，不影响代码正确性
- **状态**：✅ 已处理（2026-08-01 文档一致性同步提交 ca819e4 + Task 6 文档更新）

### P0-3：is_marked 字段清理（UX 重构 Task 6）

- **问题**：当前保留 is_marked=0 记录，与"标记 = 数据库有记录，取消标记 = DELETE 记录"原则不一致
- **原因**：D2 决策重构为 bool 但保留字段，未回归纯 DELETE 模式
- **推荐方案**：清理 is_marked=0 记录，取消标记操作改为 DELETE，移除 is_marked 字段（schema 迁移）
- **影响范围**：Domain / Repository / Service / UI 全链路，需 schema 迁移
- **状态**：✅ 已解决（UX 重构 Phase 2 Task 6，v0.47.0，schema v13）
- **权威来源**：[ux-redesign-roadmap.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/ux-redesign-roadmap.md) Task 6

## P1：重要优化

### P1-1：文件操作与 DB 事务不一致窗口（TD-H12）

- **问题**：文件已成功 + DB 同步失败时，文件无法回滚，仅抛 `FileOperationError` 让 UoW 回滚 DB
- **原因**：shutil 不支持事务，文件系统固有约束
- **推荐方案**：引入"补偿日志"机制，下次启动时尝试补偿；或在错误提示中明确告知用户
- **影响范围**：极端场景下数据一致性
- **建议阶段**：Stage 6

### P1-2：UndoService 安全校验不足（TD-M32 + TD-M33）

- **问题**：撤销安全校验仅诊断记录，未存储操作前快照，无法检测文件已被外部修改；mark_undone 失败可能导致重复撤销
- **原因**：schema 未扩展存储操作前快照
- **推荐方案**：schema 扩展存储操作前快照（size + mtime），undo 前比对；引入版本号或乐观锁
- **影响范围**：撤销安全性
- **建议阶段**：Stage 6

### P1-3：文件列表加载性能（TD-H3 + TD-M28 + TD-M9）

- **问题**：每个目录条目 3 次系统调用 + 1 次 DB 查询，大目录 UI 冻结
- **原因**：N+1 查询模式
- **推荐方案**：批量查询（`list_by_directory` 一次查全部子项 ContentUnit）；移入后台线程或加 mtime 缓存
- **影响范围**：大目录浏览体验
- **建议阶段**：Stage 5 中期或 UI 重构时

### P1-4：FileOperationService 分层迁移（TD-H10 + TD-L25 + TD-M35）

- **问题**：位于 infrastructure 层但注入 application 层依赖；访问 helper 私有 `_repo`；rename/move 跨盘异常类型不一致
- **原因**：Stage 4.5 H4 修复后注入了 FolderCacheSyncHelper + ContentUnitRepository
- **推荐方案**：UI 重构 Task 7 时迁移到 application 层
- **影响范围**：架构层次清晰度
- **建议阶段**：UX 重构 Task 7

### P1-5：扫描进度反馈（TD-M13）

- **问题**：scan_progress 信号仅在 run() 开头发送一次，大型目录扫描持续数十秒用户只看到静态"正在扫描…"
- **原因**：ScanService 无进度回调
- **推荐方案**：ScanService 增加进度回调，ScanWorker 转发，MainWindow 连接更新状态栏
- **影响范围**：用户体验

### P1-6：MainWindow 集成测试缺失（TD-M26）

- **问题**：信号槽 / 状态同步 / 扫描线程生命周期无自动化测试，纯靠手动验收
- **原因**：MainWindow 体量过大难以测试
- **推荐方案**：与 TD-M21 拆分同步进行，拆分后更易为各 Controller 写测试
- **建议阶段**：UX 重构 Task 7

## P2：未来功能

### P2-1：AI JSON 导入导出（Stage 6）

- **问题**：spec §5.5 定义但未实现
- **原因**：优先级靠后，先完成手动整理体验
- **推荐方案**：导出未整理内容单元 JSON（路径 / 文件名 / 大小 / 当前标签）→ 外部 AI 分析 → 导入建议 JSON（建议标题 / 标签 / 分类路径 / 置信度）→ 用户审阅确认
- **影响范围**：新功能，需设计 JSON Schema（open-questions Q4）
- **权威来源**：[spec.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/spec.md) §5.5 + [roadmap.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/roadmap.md) Stage 6

### P2-2：多模态 AI UI 重构（UX 重构 Task 8）

- **问题**：当前 UI 为功能驱动开发，布局和交互细节未针对日常使用频率优化
- **推荐方案**：用多模态 AI 分析当前界面截图生成提示词，统一配色/间距/字体/图标，暗色模式支持
- **影响范围**：UI 层全面重构
- **权威来源**：[ux-redesign-roadmap.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/ux-redesign-roadmap.md) Phase 3

### P2-3：真实 Mod 库验证（UX 重构 Task 9）

- **问题**：开发期未用真实 Mod 库系统性验证
- **推荐方案**：导入现有 Mod 库跑完整整理流程，记录不符合预期的行为
- **影响范围**：形成修复清单

### P2-4：导入预览图方式（open-questions Q3）

- **问题**：从 Nexus Mods 导入预览图使用官方接口还是网页解析
- **当前状态**：归入 Stage 6 范围，实施前必须核对相关网站规则

### P2-5：扫描取消机制（open-questions Q6）

- **问题**：扫描一旦开始无法中断
- **当前状态**：扫描速度可接受，按用户反馈决定

### P2-6：开源许可证确认（open-questions Q5）

- **问题**：仓库已有 MIT LICENSE 文件，但正式发布前可复核
- **当前状态**：维持 MIT / 改为 GPL-3.0 / 其他，Stage 6 发布前决定

### P2-7：性能优化批量处理

- TD-M23（folder_cache 同步多次 list_all 全表扫描）
- TD-M16（文件列表无缓存）
- TD-M34（覆盖模式子节点 folder_cache 不立即重建）
- TD-M29（测试组织风格不统一）

### P2-8：代码质量优化

- TD-L21（UI 样式表硬编码颜色，暗色模式时处理）
- TD-L23（content_unit.content_type 默认 'mod' 与实体名不一致）
- TD-L24（FileEntry 类名与注释不一致）
- TD-L26（time 字段后缀不统一）
- TD-L27（ClipboardEntry.timestamp 字段未使用）
- TD-L28（UI 中"目录"和"文件夹"混用）

---

# 7. 给新 Agent 的开发原则

## 7.1 不可违反的规则（来自 AGENTS.md）

1. **真实文件系统是唯一的事实来源**。数据库不定义文件组织关系，仅保存目录无法表达的信息
2. **不实现未经确认的自动文件移动、删除、覆盖或重命名**。所有文件操作必须经过用户确认
3. **UI 层不得直接调用 `shutil`、`os.rename`、`Path.rename` 或其他文件写操作**。所有文件操作通过 `FileOperationService` 进行
4. **不引入 ModItem、FileAsset、FileRole、OperationLog（旧版四步状态机）等旧版概念**。新代码使用 ContentUnit、TagCategory、Tag、OperationHistory
5. **不假设文件名有统一格式**。Nexus Mods、汉化包、社区分享文件、预览图文件名之间没有可靠规律
6. **不读写压缩包内部内容**
7. **不修改用户原始图片**。缩略图缓存写入应用数据目录
8. **所有新功能必须优先支持中文路径和 UTF-8**
9. **不得扩展到云端、账号、MO2 管理、自动爬取 Nexus 或未在规格中定义的功能**
10. **所有待确认需求必须保留 TODO 或明确注释**，不得自行假定产品决策

## 7.2 开发方式

- **分层开发**：UI → Application → Domain → Infrastructure，上层依赖下层
- **每个 Task 完成后运行测试**：`ruff check src tests` + `ruff format --check src tests` + `pytest`
- **每次改动保持小而可审查**。一个 Task 对应一次有明确边界的改动
- **优先编写领域逻辑与测试，再接入 UI**
- **对涉及真实文件的测试，必须使用 pytest 临时目录**（`tmp_path` fixture）
- **不得用真实用户目录作为测试目录**
- **所有异常必须转换为用户可理解的错误信息**，并保留技术日志

## 7.3 代码质量

- 使用类型标注（Python 3.12+）
- 使用 `pathlib.Path` 处理路径
- 使用 ruff 格式化和静态检查（line-length=100）
- 核心文件操作必须有单元测试
- 数据库 schema 变更必须使用迁移函数（在 `migrations.py` 中注册，幂等）
- UI 文本使用中文，集中在 `ui_constants.py` 中定义
- 路径比较和唯一约束统一使用 `make_path_key()`（`normcase + normpath`），不依赖字符串大小写比较

## 7.4 新 Agent 特别注意

1. **修改前阅读相关文档**：动任何模块前先读 `AGENTS.md` + `docs/spec.md` 相关章节 + `docs/technical-debt.md` 对应 TD 条目 + `docs/ux-redesign-roadmap.md` 当前 Task
2. **不要破坏现有架构**：分层规则不可违反，FileOperationService 分层问题待 Task 7 处理，不要在 Task 7 之前随意迁移
3. **保持分层**：UI 不直接访问 Repository，Application 不包含领域规则，Domain 不包含数据库知识
4. **优先修复已有技术债**：特别是 P0 级别的 MainWindow 拆分和 is_marked 字段清理
5. **新功能必须更新文档**：CHANGELOG.md 必须为每个版本条目详细记录变更，ux-redesign-roadmap.md 必须记录 Task 实施情况
6. **遇到文档与代码冲突**：以代码为准，以 CHANGELOG 为修订史，参考本交接文档第 0 节冲突表
7. **不要自行假定产品决策**：所有待确认需求保留 TODO 或明确注释，归类为 A/B/C 阻塞级别后与用户确认
8. **使用项目虚拟环境**：禁止使用全局 Python 或 TRAE 自带 Python 跑项目命令，找不到 venv 时先检查 `setup.bat` / `pyproject.toml` 确认约定路径
9. **Task 完成后不自动提交**：必须用户手动验收通过后才提交，不自动进入下一个 Task
10. **缩略图相关**：缓存已实现为 WebP 多档 `{content_unit_id}_{size}.webp`（256/512，Task 1a）；
    默认档位接线不一致（generator 默认 256，main.py 装配 ThumbnailService/Coordinator 时传 64，待统一，
    登记 TD 处理）；圆角边框，Qt 标准文件图标作为加载占位，缓存命中同步加载 + 缓存 miss 异步生成，
    单 worker + FIFO 队列，启动时清理孤立缓存

---

# 8. 当前 Git 状态

## 8.1 分支状态

```
当前分支：ux-redesign
远程跟踪：origin/ux-redesign（up to date）
工作树状态：clean（无未提交修改；注：本文档 PROJECT_HANDOVER.md 当时未跟踪）
stash：空
```

## 8.2 最近 commit 历史

```
5e5883c UX 重构 Phase 2 Task 5：交互细节优化 + 验收修复 (v0.46.0)
6f5cec1 UX 重构 Phase 1 Task 4：添加到钉住文件夹 + 基础拖拽 + 验收修复 (v0.45.0)
464581d UX 重构 Phase 1 Task 3：装配面板 📌 钉住功能 (v0.44.0)
52ab54c UX 重构 Phase 1 Task 2 Commit 2 + 验收修复 1-3 (v0.43.0)
08d3df6 UX 重构 Phase 1 Task 2 Commit 1：布局迁移 + 单击绑定 + 装配面板透视器语义
5f2aa9c UX 重构 Phase 1 Task 1 Commit 3：工作流调整（多选创建 Mod + 装配逻辑调整）
9894436 UX 重构 Phase 1 Task 1 Commit 2：移除暂存区功能
425c049 UX 重构 Phase 1 Task 1 Commit 1：移除双模式切换
9d104fe Stage 5 Code Review: 8 批次修复 + schema v11 迁移 (v0.41.0)
a84bebf Stage 5 Task 7: 全局搜索 + ContentUnit.status 简化 (v0.40.0)
```

## 8.3 其他分支

- `master`（9d104fe，origin/master）：Stage 5 Code Review 完成点，UX 重构前的稳定基线
- `stage5-task3c-suspended`（f7ba9fa）：Stage 5 Task 3c 丢失路径检测与重新关联，**已暂停开发，代码归档**，主线不包含

## 8.4 临时文件检查

- 工作树 clean，无未提交修改
- 无 stash
- `data/` 目录（应用数据）已在 `.gitignore` 中（`/data/`，已验证）
- 无其他临时文件残留

---

# 9. 新 Agent 启动第一轮建议

> **不要直接编码**。接手后第一轮按以下顺序建立认知：

## 9.1 第一步：建立宏观认知（不写代码）

1. **通读本交接文档**，特别是第 0 节冲突表和第 5 节开发重点
2. **通读 [AGENTS.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/AGENTS.md)**：不可违反的规则、开发方式、代码质量、领域模型概览、完成定义
3. **通读 [docs/ux-redesign-roadmap.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/ux-redesign-roadmap.md)**：当前分支的权威计划文档，理解 Phase 1 已完成内容 + Phase 2 剩余 Task
4. **通读 [docs/spec.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/spec.md)**：产品规格（注意 §5.2 / §7.3 整理模式描述已过时，以代码为准）
5. **通读 [docs/technical-debt.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/technical-debt.md)**：所有 TD 条目，特别是 High 级别

## 9.2 第二步：建立代码认知（不写代码）

6. **阅读 [src/app/main.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main.py)**：组合根，理解所有 Service 的依赖注入关系
7. **阅读 [src/domain/models.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/domain/models.py)**：所有 Domain 实体与领域校验
8. **阅读 [src/infrastructure/db.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/db.py) + [migrations.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/migrations.py)**：当前 schema v12 结构与迁移历史
9. **浏览 [src/app/main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py) 结构**（不必逐行读）：理解约 3500 行的职责分布，识别可拆分边界
10. **浏览 [src/application/](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/) 各 Service**：理解 Application 层职责划分

## 9.3 第三步：建立测试认知（不写代码）

11. **阅读 [tests/conftest.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/tests/conftest.py)**：测试 fixture 体系（`db_connection` / `temp_app_data`）
12. **运行测试套件**：定位项目 venv（检查 `pyproject.toml` / `setup.bat`），运行 `pytest` 确认基线绿（预期 1288 passed, 4 skipped）
13. **运行 ruff 检查**：`ruff check src tests` + `ruff format --check src tests` 确认基线绿

## 9.4 第四步：建立 Git 认知（不写代码）

14. **检查 Git 状态**：`git status` + `git log --oneline -15` + `git branch -vv`
15. **确认在 `ux-redesign` 分支**，工作树 clean
16. **理解 commit 风格**：每个 Task 一个 commit，message 含 Task 编号 + 简述 + 版本号

## 9.5 第五步：与用户对齐方向（不写代码）

17. **向用户确认下一个 Task**：根据 [ux-redesign-roadmap.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/ux-redesign-roadmap.md) Phase 2，Task 6（数据库与死代码清理）已完成（v0.47.0），下一个是 Task 7（MainWindow 拆分）
18. **理解用户工作流**：确认实现计划后再编码；Task 完成后运行自动化检查 + 提供手动验收步骤；用户验收通过后才提交；不自动进入下一个 Task
19. **理解用户决策风格**：待确认需求按 A/B/C 阻塞级别分类，先解决 A/B

## 9.6 第六步：开始第一个 Task（在用户确认后）

20. **按 Task 流程执行**：阅读相关文档 → 输出实施计划 → 用户确认 → 编码 → 运行 `ruff check src tests` + `ruff format --check src tests` + `pytest` → 提供手动验收步骤 → 用户验收 → 提交 → 更新 CHANGELOG + roadmap

---

## 附录：关键文件快速索引

| 类别 | 文件 | 用途 |
|------|------|------|
| 工作说明 | [AGENTS.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/AGENTS.md) | Agent 工作说明（不可违反规则） |
| 产品规格 | [docs/spec.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/spec.md) | 产品规格说明（部分过时） |
| 架构设计 | [docs/architecture.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/architecture.md) | 架构设计（部分过时） |
| UX 重构计划 | [docs/ux-redesign-roadmap.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/ux-redesign-roadmap.md) | 当前分支权威计划 |
| 主线 roadmap | [docs/roadmap.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/roadmap.md) | 分阶段开发计划 |
| 技术债 | [docs/technical-debt.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/technical-debt.md) | 技术债登记 |
| 设计工作手册 | [docs/design-workbook.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/design-workbook.md) | 六项核心设计讨论结论 |
| 待确认问题 | [docs/open-questions.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/open-questions.md) | 待决策问题清单 |
| 变更历史 | [CHANGELOG.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/CHANGELOG.md) | 版本变更记录 |
| 组合根 | [src/app/main.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main.py) | 依赖注入装配 |
| 主窗口 | [src/app/main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py) | God Object（待拆分） |
| Domain | [src/domain/models.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/domain/models.py) | 实体定义 + 领域校验 |
| 数据库 | [src/infrastructure/db.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/db.py) | 连接管理 + 迁移执行 |
| 迁移 | [src/infrastructure/migrations.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/migrations.py) | v0→v12 迁移函数 |
| 路径工具 | [src/infrastructure/path_utils.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/path_utils.py) | `make_path_key` 路径归一化 |
| 文件操作 | [src/infrastructure/file_operation_service.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/file_operation_service.py) | 文件操作 + folder_cache 自动同步 |
| folder_cache 同步 | [src/infrastructure/folder_cache_sync_helper.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/folder_cache_sync_helper.py) | 语义化同步方法 |
| UI 文案 | [src/app/ui_constants.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/ui_constants.py) | UI 文案常量 |
| 路径简化 | [src/app/path_display.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/path_display.py) | 路径简化显示 |
| 提示音抑制 | [src/app/message_box_helper.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/message_box_helper.py) | QMessageBox 提示音抑制 |

---

**交接文档结束。**

如发现文档与代码冲突，以代码为准，并在 [docs/technical-debt.md](file:///c:/AphrosyneData/Skyrim-Content-Workbench/docs/technical-debt.md) 登记或通知用户更新本文档。
