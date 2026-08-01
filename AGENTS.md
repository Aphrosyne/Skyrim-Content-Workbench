# Skyrim Content Workbench — Coding Agent 工作说明

> 本文档为方向 C + UX 重构后的版本（2026-08-01 重写）。
>
> 开发依据（按优先级）：
> 1. `docs/PROJECT_HANDOVER.md`（最新工程交接，v0.47.0 / schema v13 / `ux-redesign` 分支）
> 2. `docs/ux-redesign-roadmap.md`（当前分支的权威计划文档）
> 3. `docs/spec.md`、`docs/architecture.md`（存在部分过时章节，以代码 + CHANGELOG 为准）
> 4. `docs/open-questions.md`、`docs/technical-debt.md`

**文档与代码冲突时，以代码为准，以 CHANGELOG.md 为修订史。**

---

## 项目目标

实现 Skyrim Content Workbench：一个本地优先的 Windows 桌面数字资产管理工具。数据库是元数据增强层，真实文件系统是唯一的事实来源。核心概念是"内容单元"（一个文件夹或一个单文件），替代旧版的 ModItem + FileAsset 虚拟映射体系。

## 不可违反的规则

1. **真实文件系统是唯一的事实来源**。数据库不定义文件组织关系，仅保存目录无法表达的信息（中文别名、标签、备注、来源 URL、封面关联等）。
2. **不实现未经确认的自动文件移动、删除、覆盖或重命名**。所有文件操作必须经过用户确认。
3. **UI 层不得直接调用 `shutil`、`os.rename`、`Path.rename` 或其他文件写操作**。所有文件操作通过 `FileOperationService` 进行。
4. **不引入 ModItem、FileAsset、FileRole、OperationLog（旧版四步状态机）等旧版概念**。新代码使用 ContentUnit、TagCategory、Tag、OperationHistory。
5. **不假设文件名有统一格式**。Nexus Mods、汉化包、社区分享文件、预览图文件名之间没有可靠规律。
6. **不读写压缩包内部内容**。
7. **不修改用户原始图片**。缩略图缓存写入应用数据目录，不写入用户 Mod 目录。
8. **所有新功能必须优先支持中文路径和 UTF-8**。数据库 TEXT 字段使用 Unicode，JSON 使用 UTF-8。
9. **不得扩展到云端、账号、MO2 管理、自动爬取 Nexus 或未在规格中定义的功能**。
10. **所有待确认需求必须保留 TODO 或明确注释**，不得自行假定产品决策。

## 开发方式

- **分层开发**：UI → Application → Domain → Infrastructure，上层依赖下层。
  - UI 不直接访问 Repository 或文件系统写操作，通过 Application Service 调用。
  - Application 不包含领域规则（领域规则在 Domain 层实体校验中）。
  - Infrastructure 为唯一允许直接操作数据库和文件系统的模块。
- **每个 Task 完成后运行测试**：`ruff check src tests` + `ruff format --check src tests` + `pytest`。
- **每次改动保持小而可审查**。一个 Task 对应一次有明确边界的改动。
- **优先编写领域逻辑与测试，再接入 UI**。
- **对涉及真实文件的测试，必须使用 pytest 临时目录**（`tmp_path` fixture）。
- **不得用真实用户目录作为测试目录**。
- **所有异常必须转换为用户可理解的错误信息**，并保留技术日志。
- **不再往 MainWindow 堆方法**（UX 重构 Phase 2 编码约束）：新增逻辑尽量抽到独立 controller / helper / view 中，为 Task 7 拆分减负。

## 代码质量

- 使用类型标注（Python 3.12+）。
- 使用 `pathlib.Path` 处理路径。
- 使用 ruff 格式化和静态检查（line-length=100）。
- 核心文件操作必须有单元测试。
- 数据库 schema 变更必须使用迁移函数（在 `migrations.py` 中注册，幂等）。
- UI 文本使用中文，集中在 `ui_constants.py` 中定义。
- 路径比较和唯一约束统一使用 `make_path_key()`（`normcase + normpath`），不依赖字符串大小写比较。

## 领域模型概览

（完整定义见 `docs/spec.md §4`；与代码冲突时以 `src/domain/models.py` 为准）

```text
ContentUnit        → 内容单元（path、path_key、title、content_type、source_url、cover_path、notes）
TagCategory        → 标签分类（名称、色相值）
Tag                → 标签（名称、所属分类，一个标签只属于一个分类）
ContentUnitTag     → 内容单元 ↔ 标签（多对多）
OperationHistory   → 操作历史（类型、源路径、目标路径、undone_at、can_undo）
ManagedRoot        → 受管理根目录
FolderCache        → 目录树性能缓存（路径、父节点、上次扫描 mtime）
ThumbnailCache     → 缩略图缓存（关联 content_unit_id，WebP 多档缓存）
```

**ContentUnit 关键语义：**

- 标记 = 数据库有记录；取消标记 = 删除记录（纯 DELETE 模式，已随 UX 重构 Task 6
  / schema v13 落地，`is_marked` 字段已移除）。
- ContentUnit **不存 status、rating 字段**。

所有 Domain 实体为纯 dataclass，不包含数据库或文件系统知识。

## 架构约束

- **Schema 版本**：当前 `CURRENT_SCHEMA_VERSION = 13`（见 `src/infrastructure/db.py`；
  v13 起回归纯 DELETE 模式，content_unit 无 is_marked 字段）。
- **分支**：当前工作在 `ux-redesign` 分支，权威计划是 `docs/ux-redesign-roadmap.md`。
- **应用数据目录解析优先级**：`SCW_DATA_DIR` 环境变量 > 项目根 `data/` > `%LOCALAPPDATA%\SkyrimContentWorkbench\` > `~/.skyrimmodworkbench/`。默认位于项目根 `data/`（app.db、thumbnails/、exports/、logs/），`.gitignore` 已忽略 `/data/`。
- **UI 单面板**：无浏览/整理模式切换，无暂存区，无快速插入。统一为目录树（左）+ 文件列表/卡片（中）+ 元数据/可钉住装配面板（右）。
- **文件操作流程**：直接执行（move/rename/delete/new_folder），写入 operation_history，支持撤销。撤销不产生新记录，仅标记原记录 `undone_at`。
- **扫描**：启动时自动增量扫描（基于目录 mtime），用户可手动全量重扫。不做实时文件系统监听。识别规则：所有压缩包文件自动标记为内容单元候选，文件夹由用户手动标记。
- **缩略图**：关联键 `content_unit_id`，缓存格式 `{content_unit_id}_{size}.webp`（多档）。
- **路径显示**：相对受管理根目录显示（含根目录名），外部路径加 `[外部]` 前缀，不显示绝对路径。

## 完成定义

一个功能只有在以下条件都满足时才算完成：

- 有明确输入、输出和失败行为。
- 有至少一个自动化测试（纯 UI 微调可例外）。
- 不会绕过安全规则（文件操作确认、冲突处理、回收站删除）。
- 不会破坏中文路径支持。
- 不会引入未讨论的产品范围（超出 `docs/spec.md` 定义）。
- 文档或注释说明了关键约束。
