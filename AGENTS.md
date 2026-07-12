# Skyrim Content Workbench — Coding Agent 工作说明

> 本文档为方向 C 确认后的重写版。旧版已归档至 `archive/`。
>
> 开发依据：`docs/spec.md`、`docs/architecture.md`、`docs/roadmap.md`

---

## 项目目标

实现 Skyrim Content Workbench 第一版：一个本地优先的 Windows 桌面数字资产管理工具。数据库是元数据增强层，真实文件系统是唯一的事实来源。核心概念是"内容单元"（一个文件夹或一个单文件），替代旧版的 ModItem + FileAsset 虚拟映射体系。

## 不可违反的规则

1. **真实文件系统是唯一的事实来源**。数据库不定义文件组织关系，仅保存目录无法表达的信息（标签、评分、备注、来源、封面关联等）。
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

## 代码质量

- 使用类型标注（Python 3.12+）。
- 使用 `pathlib.Path` 处理路径。
- 使用 ruff 格式化和静态检查（line-length=100）。
- 核心文件操作必须有单元测试。
- 数据库 schema 变更必须使用迁移函数（在 `migrations.py` 中注册，幂等）。
- UI 文本使用中文，集中在 `ui_constants.py` 中定义。
- 路径比较和唯一约束统一使用 `make_path_key()`（`normcase + normpath`），不依赖字符串大小写比较。

## 领域模型概览

（完整定义见 `docs/spec.md §4`）

```text
ContentUnit        → 内容单元（路径、标题、类型、来源、评分、封面、状态、备注）
TagCategory        → 标签分类（名称、色相值）
Tag                → 标签（名称、所属分类）
ContentUnitTag     → 内容单元 ↔ 标签（多对多）
OperationHistory   → 操作历史（类型、源路径、目标路径、可撤销标记）
ManagedRoot        → 受管理根目录（保留旧版）
FolderCache        → 目录树性能缓存（路径、父节点、上次扫描 mtime）
ThumbnailCache     → 缩略图缓存（保留旧版，关联键改为 content_unit_id）
```

所有 Domain 实体为纯 dataclass，不包含数据库或文件系统知识。

## 架构约束

- **Schema 版本**：当前 v3，方向 C 下一阶段迁移到 v4（新建 content_unit 等表，移除旧表）。
- **文件操作流程**：不再使用预演→确认→执行四步状态机。每次操作（move/delete/rename/new_folder）直接执行，写入 operation_history，支持撤销。
- **扫描**：启动时自动增量扫描（基于目录 mtime），用户可手动全量重扫。不做实时文件系统监听。
- **缩略图**：关联键从 `asset_id` 改为 `content_unit_id`，缓存命名 `{content_unit_id}.png`。
- **应用数据目录**：`%LOCALAPPDATA%\SkyrimContentWorkbench\`（含 app.db、thumbnails/、exports/、logs/）。
- **UI 双模式**：浏览模式（内容单元列表 + 标签筛选 + 大图预览）和整理模式（暂存区固定 + 装配面板 + 快速插入）。通过顶部按钮切换。

## 完成定义

一个功能只有在以下条件都满足时才算完成：

- 有明确输入、输出和失败行为。
- 有至少一个自动化测试（纯 UI 微调可例外）。
- 不会绕过安全规则（文件操作确认、冲突处理、回收站删除）。
- 不会破坏中文路径支持。
- 不会引入未讨论的产品范围（超出 `docs/spec.md` 定义）。
- 文档或注释说明了关键约束。
