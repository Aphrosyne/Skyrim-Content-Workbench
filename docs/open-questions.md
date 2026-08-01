# 待确认问题清单

> 本文档为方向 C 确认后的重写版。旧版已归档至 `archive/`。
>
> 旧版 Q1-Q21 中的大多数已在方向 C 的设计中定案，不再重复列出。
> 以下仅保留仍待决策或实现中可能遇到的具体问题。

---

## 1. 标签系统的初始预制库 ✅ 已关闭（Stage 4 Task 1）

- **问题**：第一批预制标签的具体内容（分类名称、各分类下的标签列表）。
- **背景**：spec §10.2 确定使用"预制 + 自定义"策略，但预制库的具体内容未枚举。
- **关闭**：Stage 4 Task 1 已实现 `default_tags.json`，含 6 分类（服装护甲 / 武器 / 作者 / 来源 / 状态 / 部位），预制库内容与原设想一致。

---

## 2. 搜索索引技术选型 ✅ 已关闭（Stage 5 Task 7）

- **问题**：搜索使用 SQLite FTS5 还是直接 LIKE 查询。
- **背景**：新 spec §8 定义搜索范围为内容单元标题 + 标签名 + 备注，第一阶段数据量有限。
- **关闭**：Stage 5 Task 7 采用方案 A（直接 `LIKE` 查询），Q2=B 仅搜索 `is_marked=1` 的内容单元。数据量有限时 LIKE 性能足够，FTF5 增加 schema 复杂度不划算。
- **后续**：若数据量增长后性能不足，可再评估迁移到 FTS5。
- **Task 6 更新**：UX 重构 Phase 2 Task 6 回归纯 DELETE 模式后，`is_marked` 字段移除，
  "仅搜索 is_marked=1"约束自然消失（content_unit 表中有记录即已标记）。

---

## 3. 导入预览图方式

- **问题**：从 Nexus Mods 导入预览图时使用官方接口还是网页解析。
- **背景**：roadmap 阶段 5 涉及的功能，当前不迫切。
- **可选方向**：官方 API / 网页解析 / 仅支持手动下载关联。
- **预计决定里程碑**：阶段 5 启动前。实施前必须核对相关网站规则。
- **当前状态**：Stage 5 已完成但未涉及此功能，归入 Stage 6 范围。

---

## 4. AI JSON Schema 格式

- **问题**：AI JSON 导入导出的具体字段和结构。
- **背景**：roadmap 阶段 6 涉及的功能。
- **当前设想**：
  - 导出：内容单元路径、文件名、大小、当前标签、候选标签
  - 导入：建议标题、建议标签、建议分类路径、置信度
- **预计决定里程碑**：阶段 6 Task 1 实施前。

---

## 5. 开源许可证

- **问题**：选择 MIT 还是 GPL-3.0（或其它）。
- **背景**：仓库已有 MIT LICENSE 文件（Copyright 2026 Aphrosyne），但正式发布前可复核。
- **可选方向**：维持 MIT / 改为 GPL-3.0 / 其他。
- **预计决定里程碑**：阶段 6 发布前。

---

## 6. 扫描取消机制

- **问题**：扫描一旦开始无法中断，是否需要取消功能。
- **背景**：当前设计使用 Qt 后台线程包裹同步扫描，没有取消入口。
- **可选方向**：
  - A) 不做取消（扫描通常很快，增量扫描更短）
  - B) 实现取消机制（需要 ScanWorker 层支持中断信号）
- **预计决定里程碑**：阶段 3 或阶段 5（取决于用户实际使用体验反馈）。
- **当前状态**：Stage 5 已完成，扫描速度可接受，按用户反馈决定。

---

## 7. FolderTreeModel 惰性加载的技术债 ✅ 已关闭（新架构）

- **问题**：`FolderTreeModel.rowCount` 在未加载时自动触发 `_fetch`，违反 Qt model/view 惯例。
- **背景**：旧版实现中存在此问题（曾导致无限递归崩溃），通过重入保护缓解但未根治。
- **关闭**：新架构 `canFetchMore` / `fetchMore` 已正确实现，`rowCount` 改为纯查询（返回 0 或缓存长度，不触发 `_fetch`），无无限递归问题。

---

## Stage 5 后 Code Review / UI 重构清单

> 以下为验收测试中发现的可优化项，不影响主功能。
> 计划在 Stage 5 全部完成后、UI 重构之前统一处理。
> 处理顺序：先功能修复优化 → 再 UI 重构。

### 1. 快捷键补全

- **现状**：部分右键菜单操作和整理模式下的「快速插入」没有对应快捷键。
- **待做**：补充缺失的快捷键绑定（如快速插入的快捷键），使高频操作全部可键盘触发。
- **状态**：✅ 已关闭（Stage 5 Task 4 快捷键 + Task 5 Ctrl+M + UX 重构 Phase 2
  Task 5 F5 补齐）。当前快捷键：
  F2（中栏/目录树重命名）、Delete（删除）、Ctrl+Z（撤销）、Ctrl+A（全选）、
  Ctrl+C/X/V（复制/剪切/粘贴）、Ctrl+M（移动到...）、F5（刷新当前目录）。
  「快速插入」本身已随功能移除（Phase 1 Task 4），不再需要对应快捷键。

### 2. 警告弹窗改用非系统警告方式

- **现状**：警告弹窗触发 Windows 系统提示音，频繁操作时很吵。
- **待做**：改用 `QMessageBox` 的 `information` / `warning` 级别控制，或自定义无声音提示组件。
- **状态**：✅ 已关闭（UX 重构 Phase 2 Task 5）。新增
  `message_box_helper.py`，patch QMessageBox 静态方法抑制 Windows 系统提示音，保留视觉图标。

### 3. 操作历史显示优化

- **现状**：操作历史面板显示了所有操作，包括已撤回的、撤回操作本身、以及删除操作。
- **待做**：
  - 不显示已撤回的操作
  - 不记录/不显示"撤回"这个操作本身
  - 不显示删除操作（删除由回收站兜底，历史面板无需展示）
- **Stage 5 Code Review 更新**：D4 决策已落地——撤销操作不再写入 `operation_history` 新记录，仅标记原记录 `undone_at`。"不记录/不显示撤回操作"已通过 schema v11 迁移在数据层消除，UI 层只需根据 `undone_at` 灰显原记录即可。
- **状态**：✅ 已关闭（UX 重构 Phase 2 Task 5）。操作历史对话框已移除描述列改用
  Tooltip、过滤已撤销记录、删除操作灰色显示、操作类型中文化。

### 4. 刷新按钮

- **现状**：在外部修改目录后，只能去左上角点扫描才能刷新，不够方便。
- **待做**：增加一个快速刷新按钮（或 F5 快捷键），仅刷新当前目录内容，不触发全量扫描。
- **状态**：✅ 已关闭（UX 重构 Phase 2 Task 5）。中栏标题栏新增刷新按钮 + F5 快捷键，
  仅刷新当前目录与目录树对应节点。

### 5. 状态栏提示导致布局抖动

- **现状**：非弹窗文字提示位置在左下角最下方，不属于任何栏。首次提示会把三个栏往上抬高。
- **待做**：将状态栏固定为独立行，或使用 `QStatusBar` 显示提示，避免布局抖动。
- **属性**：属于 UI 问题。
- **状态**：✅ 已关闭（UX 重构 Phase 2 Task 5）。统一使用 Qt 标准 `QStatusBar`。

### 6. 数据库清理

- **现状**：删除受管理目录配置后，旧目录相关的 `folder_cache` 记录未清理。
- **待做**：移除受管理根目录时，同步清理对应的 `folder_cache` 和内容单元记录。清理取消内容单元标记的条目
- **状态**：✅ 已关闭（UX 重构 Phase 2 Task 6，v0.47.0）。
  `remove_root` 同步清理根前缀下 folder_cache / content_unit（重叠守卫 + UoW）；
  is_marked 纯 DELETE 模式（schema v13）一并落地。

### 7. 旧数据库目录检测代码清理

- **现状**：数据库从 `%LOCALAPPDATA%` 迁移到 `{project_root}/data/` 后，代码中遗留了旧目录检测逻辑。
- **待做**：确认迁移稳定后，移除旧的 `%LOCALAPPDATA%\SkyrimContentWorkbench\` 检测/迁移代码。
- **状态**：✅ 已关闭（UX 重构 Phase 2 Task 6，v0.47.0）。检测/迁移提示代码已移除；
  `%LOCALAPPDATA%` 路径回退保留（路径解析优先级第 3 项不变，生产环境无
  pyproject.toml 时的回退策略）。

### 8. UI 重构

- **现状**：当前 UI 为功能驱动开发，布局和交互细节未针对日常使用频率优化。
- **计划**：Stage 5 全部完成 + Code Review 修复后，用多模态 AI 分析当前界面生成提示词，进行整体 UI 重构。
- **属性**：属于交互体验。
- **Stage 5 Code Review 更新**：用户决策 UI 重构单独开分支处理，不在当前主线进行。
- **状态**：⬜ 未完成。归入 UX 重构 Phase 3 Task 8（多模态 AI 分析 + 整体 UI 重构）。

### 9. 信息简化

- 拆分mainwindow。操作历史里面的操作记录简化，只显示操作类型，鼠标悬浮上去显示详细操作过程
- 所有路径都不显示绝对路径，只从管理目录作为根路径开始显示，或者寻找一些替代方式，简化路径
- **Stage 5 Code Review 更新**：MainWindow 拆分登记为 TD-M21 + TD-M31，归入 UI 重构版本处理。
- **状态**：部分完成。
  - ✅ 操作历史简化 + 路径简化显示已在 UX 重构 Phase 2 Task 5（v0.46.0）完成
    （`path_display.py`：相对路径含根目录名，外部路径加 `[外部]` 前缀）。
  - ⬜ MainWindow 拆分仍待 UX 重构 Task 7（TD-M21 + TD-M31）。

### 10. 图标美化
- 不同后缀文件有不同svg图标
- **状态**：⬜ 未完成。归入 UX 重构 Phase 3 Task 8（统一配色/间距/字体/图标）。

### 11. 拖动优化
- 拖动到的目标有高亮提示
- 拖动时能滚动中栏
- **状态**：部分完成。
  - ✅ 基础拖拽已在 Phase 1 Task 4（v0.45.0）完成（中栏→装配面板、中栏内拖到文件夹）。
  - ⬜ 视觉反馈（目标高亮、自动滚动）未完成，归入 UX 重构 Task 8。

---

## Stage 5 Code Review 决策记录（2026-07-31）

> Stage 5 完成后的全面 Code Review 发现 5 项需用户决策的问题（D1-D5），
> 用户已于 2026-07-31 完成决策，以下记录决策结果与落地状态。

### D1: ModGroupService 命名与职责重构 — 决策 A ✅ 已落地

- **决策**：A — 保留 "Mod 组" 作为 UI 术语（用户认知友好），但代码层面重命名。
- **落地**：`ModGroupService` → `ContentUnitCreationService`，`create_mod_group` → `create_content_unit_from_file`，错误类 `ModGroupSourceNotInStagingError` / `InvalidModGroupNameError` → `SourceNotInStagingError` / `InvalidContentUnitNameError`。UI 文本保留 "Mod 组"。测试文件名和 `TestCreateModGroup` 类名保留（代码层重命名，UI 术语保留）。
- **版本**：Stage 5 Code Review 批次 6（v0.41.0）。

### D2: status 字段是否重构为 is_marked: bool — 决策 B ✅ 已落地

- **决策**：B — 重构为 `is_marked: bool`，v11 迁移。
- **落地**：schema v11 迁移，content_unit 表移除 `status` 列，新增 `is_marked INTEGER NOT NULL DEFAULT 1 CHECK(is_marked IN (0, 1))`。数据迁移：`status='organized'` → `is_marked=1`，`status='unmarked'` → `is_marked=0`。Domain 层 `ContentUnit` / `SearchResult` 字段 `status: str` → `is_marked: bool`。Repository / Service / UI 全链路改用 `is_marked`。
- **版本**：Stage 5 Code Review 批次 7（v0.41.0）。

### D3: "organized" 状态值是否重命名 — 决策 C ✅ 与 D2 一并处理

- **决策**：C — 与 D2 一并决策。
- **落地**：随 D2 决策落地，status 字段直接重构为 `is_marked: bool`，"organized" / "unmarked" 字面值不再存在。
- **版本**：Stage 5 Code Review 批次 7（v0.41.0）。

### D4: operation_history.source_path 复用问题 — 决策 A（用户修正）✅ 已落地

- **决策**：A — 用户补充：删除操作记录默认灰色不可撤销；可撤销记录撤销后变灰；"撤销"操作本身不记录（因为原记录已有 `undone_at` 字段标记是否被撤销）。
- **落地**：schema v11 迁移清理历史 `operation_type='undo'` 记录。`UndoService.undo()` 不再创建新 OperationHistory 记录，仅调用 `_repo.mark_undone(history.id, self._now())` 标记原记录。保留 CHECK 约束含 `'undo'`（向后兼容，不重建表）。不新增 `original_op_id` 列（H3 问题自动消失）。
- **版本**：Stage 5 Code Review 批次 7（v0.41.0）。

### D5: TD-H10 FileOperationService 分层迁移时机 — 决策 B ✅ 已登记

- **决策**：B — UI 重构时一并处理。
- **落地**：登记为 TD-H10 + TD-L25，归入 UI 重构版本处理（用户决策 UI 重构单独开分支）。当前代码保持现状，FileOperationService 仍位于 infrastructure 层。

---

## 已决策索引

以下旧版 open questions 已在方向 C 的设计中定案，不再跟踪：

| 编号 | 主题 | 状态 | 新架构中的对应 |
|------|------|------|---------------|
| Q1 | ModItem.status | ✅ 关闭 | 由 ContentUnit.status 替代（v11 进一步重构为 is_marked） |
| Q2 | FileAsset.batch_id | ✅ 关闭 | FileAsset 概念已移除 |
| Q3 | 拖入目录树 vs 按钮 | ✅ 关闭 | 拖拽 + 快速插入按钮并存 |
| Q4 | 缩略图联系表给 AI | ✅ 关闭 | 阶段 6 决定 |
| Q5 | 缩略图缓存失效 | ✅ 关闭 | 保留现有策略 |
| Q6 | 资源管理器拖入 | ✅ 关闭 | 第一版不做 |
| Q7 | 导入预览图方式 | → 新 Q3 | 移至新文档 |
| Q8 | 开源许可证 | → 新 Q5 | 移至新文档 |
| Q9 | 英文国际化 | ✅ 关闭 | UI 确认仅中文 |
| Q10 | 候选成员关系 | ✅ 关闭 | ModItem 概念已移除 |
| Q11 | 素材池处置 | ✅ 关闭 | 由暂存区方案替代 |
| Q12 | 搜索索引更新 | → 新 Q2 | 移至新文档（Stage 5 Task 7 关闭，方案 A LIKE） |
| Q13 | 缩略图命名 | ✅ 关闭 | 保留现有策略 |
| Q14 | undo_payload 结构 | ✅ 关闭 | 旧版 OperationLog 已废弃 |
| Q15 | AI JSON Schema | → 新 Q4 | 移至新文档 |
| Q16 | OperationType 值集 | ✅ 关闭 | 旧版枚举已废弃 |
| Q17 | 增量扫描 | ✅ 关闭 | 已在新扫描策略中确定 |
| Q18 | 扫描并发与取消 | → 新 Q6 | 移至新文档 |
| Q19 | 成员角色限制 | ✅ 关闭 | 角色系统已移除 |
| Q20 | 部分失败回滚 | ✅ 关闭 | 旧版批量移动已废弃 |
| Q21 | FolderTreeModel 技术债 | → 新 Q7 | 移至新文档（新架构已修复） |
