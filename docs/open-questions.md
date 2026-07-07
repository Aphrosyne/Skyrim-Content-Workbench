# 待确认问题清单（Open Questions）

本文件记录 Skyrim Mod Workbench 项目中尚未明确的产品/工程决策。
任何一项在实现中被触发前，必须先在此处更新决策结果，再进入实现。
未决策前，实现不得把任何一种选择写死。

来源标注：spec=docs/spec.md, arch=docs/architecture.md, roadmap=docs/roadmap.md, agents=AGENTS.md。

## 1. ModItem.status 字段是否实现 ✅ 已关闭
- 问题：第一版是否需要独立 status 字段（如 draft/ready/archived）。
- 背景：spec §6.1 列出 status 但标注待确认。
- 决策：阶段 2 不引入独立 status 字段。列表展示与可操作性由是否有关联成员、是否设置分类目录、是否有封面等现有字段表达。
- 决策来源：[docs/phase-2-plan.md](phase-2-plan.md) §3 D5。
- 兼容性约束：ModItem 表暂不建 status 列；未来引入须 ALTER TABLE 迁移，不破坏现有数据。

## 2. FileAsset.batch_id 是否实现（下载批次概念）
- 问题：是否在阶段 1 引入「下载批次」概念。
- 背景：spec §6.2 标注待确认。
- 可选方向：不实现 / 实现简单 batch 表 / 仅存 batch_id 字符串。
- 不决策原因：阶段 1 无批量导入场景。
- 预计决定里程碑：阶段 3（AI JSON 导入可能涉及批量）启动前。
- 兼容性约束：FileAsset 表暂不建 batch_id 列。

## 3. 卡片拖入目录树 vs「移动到…」按钮 ✅ 阶段 2 部分关闭
- 问题：第一版移动入口是单一拖拽还是拖拽+按钮并存。
- 背景：spec §8 待确认。
- 决策：阶段 2 仅提供按钮式「移动到选中目录」入口，不实现拖拽。
- 决策来源：[docs/phase-2-plan.md](phase-2-plan.md) §3 D2。
- 兼容性约束：application 层移动 API（plan_move/execute_move）与入口方式解耦，UI 层选择不影响服务层。拖拽为后续阶段待确认项，若未来仍要讨论可拆成新问题。

## 4. 预览图缩略图联系表是否导出给 AI
- 问题：AI JSON 导出是否包含缩略图联系表。
- 背景：spec §11 待确认。
- 可选方向：仅文本元数据 / 文本+缩略图联系表。
- 不决策原因：阶段 1 不涉及 AI JSON。
- 预计决定里程碑：阶段 3 启动前。
- 兼容性约束：导出格式需保留 schema_version 字段以便未来扩展。

## 5. 缩略图缓存失效策略
- 问题：原图变更/移动/删除后缩略图如何失效。
- 背景：arch §8 待确认。
- 可选方向：基于 mtime / 基于 asset_id 重建 / 全量重建。
- 不决策原因：阶段 1 不实现缩略图。
- 预计决定里程碑：阶段 2 缩略图服务实现前。
- 兼容性约束：缩略图缓存目录在本任务创建但写入逻辑后延。

## 6. 从 Windows 资源管理器拖入应用
- 问题：是否实现从资源管理器拖入。
- 背景：roadmap 阶段 4 待确认。
- 可选方向：实现 / 不实现。
- 不决策原因：阶段 1 无 UI。
- 预计决定里程碑：阶段 4。
- 兼容性约束：无。

## 7. 导入预览图方式
- 问题：官方接口 / 网页解析 / 手动下载关联。
- 背景：roadmap 阶段 5 待确认；实施前必须核对相关网站规则。
- 可选方向：三种之一或组合。
- 不决策原因：阶段 1 不涉及。
- 预计决定里程碑：阶段 5 启动前。
- 兼容性约束：无。

## 8. 开源许可证
- 问题：是否继续维持 MIT 许可证。
- 背景：roadmap 阶段 6 待确认；仓库已含 MIT LICENSE（Copyright 2026 Aphrosyne）。
- 可选方向：维持 MIT / 改为 GPL-3.0 / 其他。
- 不决策原因：阶段 1-2 不发布；正式开源发布前需复核。
- 预计决定里程碑：阶段 6。
- 兼容性约束：源文件头暂不添加 license header；现有 LICENSE 文件为 MIT。

## 9. 是否需要英文国际化
- 问题：UI 是否需要英文国际化。
- 背景：agents 代码质量待确认。
- 可选方向：仅中文 / 中文+英文 / i18n 框架。
- 不决策原因：阶段 1 无 UI 文本内容。
- 预计决定里程碑：阶段 2 UI 文本量确定后。
- 兼容性约束：UI 字符串集中在 ui 层常量，不散布；不硬编码到业务层。

## 10. 候选成员关系生成机制
- 问题：由谁、何时、如何生成本体/汉化/预览图的候选关系。
- 背景：agents 规则 7 提到「只能提供候选或人工操作」，但 spec/arch 未定义机制。
- 可选方向：手动 / AI 建议 / 启发式规则。
- 不决策原因：阶段 1 仅人工关联。
- 预计决定里程碑：阶段 3 AI 建议流程设计时。
- 兼容性约束：ModItem-FileAsset 关联完全由 application 层显式 API 接收，不内建候选生成。

## 11. 未归类素材如何移出素材池
- 问题：未归类素材无 ModItem 时的长期处置策略。
- 背景：spec §7.13 不提供删除；处置未定义。
- 阶段 2 决策：仅展示未关联素材，不提供忽略状态、不移动、不删除。用户可把素材关联到 ModItem；未关联内容继续保留在素材池。
- 决策来源：[docs/phase-2-plan.md](phase-2-plan.md) §3 D3。
- 未决部分：长期处置策略（永久保留 / 标记忽略 / 移到已忽略目录）保留未决。
- 预计决定里程碑：后续阶段素材池管理需求明确时。
- 兼容性约束：扫描结果全部留在 FileAsset 表，不删除；阶段 2 不引入忽略状态字段。

## 12. 搜索索引更新时机
- 问题：FTS5 索引在扫描后/移动后/编辑后哪个时机刷新。
- 背景：arch §7 未明确。
- 可选方向：实时 / 批量 / 手动触发。
- 不决策原因：阶段 1 不实现搜索。
- 预计决定里程碑：阶段 3 启动前。
- 兼容性约束：无。

## 13. 缩略图命名「内容标识」定义
- 问题：内容标识是哈希还是其他。
- 背景：arch §8「以 asset_id 或内容标识命名」。
- 可选方向：asset_id / 文件哈希 / mtime+size。
- 不决策原因：阶段 1 不实现缩略图。
- 预计决定里程碑：阶段 2 缩略图服务实现前。
- 兼容性约束：未来默认 asset_id。

## 14. OperationLog.undo_payload 内部结构 ✅ 已关闭
- 问题：字段结构未规定。
- 背景：spec §6.4。
- 决策：Task 5 已定义固定结构：`{version:1, members:[{asset_id, src_path, dst_path, size_bytes, mtime_iso}]}`，写入代码注释与 schema 注释。
- 决策来源：Task 5 实现（[src/infrastructure/file_operation_service.py](../src/infrastructure/file_operation_service.py)）。
- 兼容性约束：undo_payload 为 JSON 字符串，version=1；未来扩展需保持 version 字段并向后兼容。

## 15. AI JSON Schema 文件
- 问题：仓库未提供 schema 文件；字段为描述性。
- 背景：spec §5.2, §11。
- 可选方向：JSON Schema / Pydantic 模型 / dataclass。
- 不决策原因：阶段 1 不涉及。
- 预计决定里程碑：阶段 3 启动前。
- 兼容性约束：阶段 3 启动前需先产出 schema 文件并评审。

## 16. OperationType 完整值集 ✅ 已关闭
- 问题：spec §6.4 列出 operation_type 字段但未枚举完整值集。
- 背景：Task 2 实现领域模型时引入 OperationType 枚举，仅定义 MOVE 与 UNDO；
  DB 不加 CHECK 约束以避免限制未来扩展。
- 决策：Task 5 未引入新值，保持 `{move, undo}`。
- 决策来源：Task 5 实现。
- 兼容性约束：DB operation_log.operation_type 列为 TEXT 无 CHECK；
  代码层 OperationType 枚举仅定义已知值，新增值需同步更新枚举与文档；
  读取未知值时 Repository 抛 ValueError（不静默吞掉）。

## 17. 增量扫描与变更检测策略
- 问题：是否需要增量扫描、文件监听、变更检测。
- 背景：Task 3 实现全量扫描器；spec §4 明确「不实现完整文件监听」，
  但增量更新策略未定义。
- 阶段 2 决策：使用手动全量扫描，不做文件监听或增量扫描。
- 决策来源：[docs/phase-2-plan.md](phase-2-plan.md) §3 D4、§2 明确不做。
- 未决部分：长期增量扫描与文件监听策略保留未决。
- 预计决定里程碑：后续阶段实时性需求明确时。
- 兼容性约束：FileScanner.scan / scan_many 为全量扫描，不维护状态；
  未来增量扫描需新模块，不修改现有 FileScanner 接口。

## 18. 扫描并发与取消模型 ✅ 阶段 2 部分关闭
- 问题：扫描是否需要线程池、进度回调、取消机制。
- 背景：Task 3 为同步阻塞实现；阶段 2 UI 需要非阻塞扫描与进度显示。
- 阶段 2 决策：使用 Qt 后台线程包裹 `FileScanner.scan_many()`，提供进度文本与完成/失败状态；不承诺取消功能。
- 决策来源：[docs/phase-2-plan.md](phase-2-plan.md) §3 D4。
- 未决部分：取消机制拆为新问题，留待后续阶段评估。
- 预计决定里程碑：阶段 4（交互优化）或后续阶段。
- 兼容性约束：FileScanner 接口为同步；并发层包裹 FileScanner，不修改其同步签名。

## 19. 成员角色数量限制 ✅ 已关闭
- 问题：FileAsset 各角色（main_mod/translation/preview/readme/optional_file/unknown）
  的数量上限。
- 背景：spec §6.2 列出 6 种角色但未定义数量限制。Task 4 实现最小约束：
  MAIN_MOD≤1、README≤1；其他角色不限制。
- 决策：阶段 2 保持当前 `MAIN_MOD≤1`、`README≤1`、其余不限的实现，不改动。UI 只需把服务层返回的限制错误展示给用户。
- 决策来源：[docs/phase-2-plan.md](phase-2-plan.md) §3 D6。
- 兼容性约束：ROLE_LIMITS 字典在 application/mod_assembly_service.py 中定义，
  可独立调整；schema 无 CHECK 约束依赖角色数量；
  修改 ROLE_LIMITS 不影响已有关联数据。

## 20. 部分失败时的回滚策略 ✅ 已关闭
- 问题：移动操作中部分成员成功、部分失败时，已成功移动的成员是否需要回滚。
- 背景：spec §7.12 仅要求「不得将整个 Mod 条目标记为完全成功」，
  未定义已成功成员的处置。
- 决策：阶段 2 保持不自动回滚。执行结果必须明确列出成功成员、失败成员和可撤销范围；用户可对已成功部分执行撤销预演。
- 决策来源：[docs/phase-2-plan.md](phase-2-plan.md) §3 D7。
- 兼容性约束：FileOperationService.execute_move 单成员失败不中断其他成员；
  失败时 OperationLog.status=failed 但已成功成员的真实文件已被移动，
  undo_payload 仅记录已成功成员；
  不引入 status=partial 等新枚举值；未来引入自动回滚需扩展 OperationStatus
  并保持向后兼容。
