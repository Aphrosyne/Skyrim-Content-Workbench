# Stage 5 Code Review Report

> 审查日期：2026-07-30
> 审查范围：Stage 5 全部完成后代码现状（schema v10，CHANGELOG v0.40.0）
> 审查依据：architecture.md / design-workbook.md / spec.md / roadmap.md / technical-debt.md / open-questions.md + 实际代码

---

## 1. 总体评价

### 1.1 项目完成度

**Stage 5 范围内的功能闭环已完整实现**。手动整理分类闭环流程（扫描 → 素材池 → 查看/预览 → 手动分类 → 创建内容单元 → 关联资源 → 移动整理文件 → 基础管理）全部可用，覆盖 spec §3 第一版目标的 14 项中的 13 项（仅 AI JSON 交换属 Stage 6 范围未实现）。测试规模 1341 passed + 5 skipped，ruff 全通过。

### 1.2 架构健康程度

**功能可用，但架构债显著累积**。主要矛盾：

- **MainWindow God Object 已突破临界点**：3823 行、95 个方法、60+ 实例变量、6 个并行状态机。Stage 4/5 期间虽然 TD-M21 已登记，但 Q8:C 决策"边开发边小规模拆分"实际未执行，反而新增了快捷键 handler（14 个）、冲突解决编排（2 个重复方法）、导航历史栈等逻辑。**这是当前最大的架构债**。
- **分层违规固化**：FileOperationService 在 infrastructure 层但承担 application 层职责（TD-H10），UndoService 通过 TYPE_CHECKING 反向导入，形成分层倒置。MainWindow 直接 import infrastructure 层并承担事务边界（21 处 `_commit()`）。
- **文档与代码严重脱节**：architecture.md 仍停留在 schema v6，实际代码已到 v10；staging_area 表未在文档列出；thumbnail_cache 描述过时。

### 1.3 是否达到下一阶段开发要求

**勉强达到，但不建议直接进入 Stage 6**。当前架构对后续 UI 大修和 Stage 6 功能扩展存在以下阻塞：

- MainWindow 单文件 3823 行已使任何 UI 改动成本极高，UI 重构前必须先拆分
- 文件操作与 DB 事务不一致窗口、undo 安全校验缺失快照，会在 Stage 6 多用户场景（AI JSON 导入批量操作）放大风险
- 文档滞后使新开发者（或 AI 协作）难以准确理解系统现状

**推荐先做一轮聚焦的 Code Review 修复（详见第 7 节），再进入 UI 重构版本**。

---

## 2. 必须修复问题（High Priority）

### H1: 文档与代码严重脱节

- **问题**：`docs/architecture.md` 描述 schema v6，实际代码已到 v10（`src/infrastructure/db.py:21`）。具体不一致：
  - 第 375/559 行声称 "Schema v6"，缺少 v7（thumbnail 复合主键）、v8（undone_at）、v9（copy 类型）、v10（status 重命名）的迁移说明
  - 第 431 行 `thumbnail_cache` 描述仍写 `asset_id TEXT PRIMARY KEY`，实际已是 `(content_unit_id, size)` 复合主键（`migrations.py:367-377`）
  - 第 6.4 节表清单未列出 `staging_area` 表（v5 已引入）
  - 第 612 行迁移说明止于 v5→v6
- **原因**：每个 Task 完成后未同步更新 architecture.md
- **影响**：新开发者/AI 依据过时文档做决策会引入错误；spec/architecture/roadmap 之间出现事实性矛盾
- **建议方案**：当前 Code Review 阶段一次性更新 architecture.md 到 v10 现状，包含所有迁移说明和表结构。**修改成本：低（纯文档）**。

### H2: search_service.py 注释与实现矛盾

- **问题**：`src/application/search_service.py:7` 注释 `Q2=A：搜索所有状态的内容单元（含 unmarked / missing）`，但实际 `src/infrastructure/repositories/search.py:104` 是 `WHERE cu.status = 'organized'`（Q2=B 仅搜 organized）。注释提及的 `missing` status 从未实现过。
- **原因**：Stage 5 Task 7 收尾时决策从 Q2=A 改为 Q2=B，但未同步注释
- **影响**：误导后续维护者认为搜索包含 unmarked，可能基于错误假设做扩展
- **建议方案**：修正 `search_service.py:7` 注释为 Q2=B，删除 missing 提及。**修改成本：极低**。

### H3: operation_history.source_path 在 undo 记录中存 ID 而非路径

- **问题**：`src/application/undo_service.py:198` 写入 undo 记录时 `source_path=history.id`，但字段名 `source_path` 语义是"源路径"。CHECK 约束 `source_path TEXT NOT NULL`（`migrations.py:500`）允许任意字符串通过，因此 schema 层不报错。
- **原因**：undo 记录需要审计链指向被撤销的原记录，但没有专门字段，复用了 source_path
- **影响**：
  - 字段名与实际用途不符，维护者读 undo 记录的 source_path 会误以为是文件路径
  - 未来若加 "按路径查 history" 查询，undo 记录会污染结果集
  - 与 OperationHistory.__post_init__ 的 source_path 非空校验语义冲突（校验的是"路径非空"，实际存的是 UUID）
- **建议方案**：当前 Code Review 阶段仅添加注释说明 undo 记录的 source_path 语义特殊（指向原 history.id），并在 domain 层 `OperationHistory.__post_init__` 中对 `operation_type='undo'` 的 source_path 做特殊文档化。**真正的修复（新增 `original_op_id` 列）需 v11 schema 迁移，建议记入技术债**。

### H4: 文件操作与 DB 事务不一致窗口未文档化

- **问题**：`file_operation_service.py` 的 move/rename/copy 中"文件已成功 + DB 同步失败"时，文件无法回滚，仅抛 FileOperationError 让 UoW 回滚 DB（`file_operation_service.py:301-305, 487-489, 795-798`）。这会导致**文件系统与 DB 状态不一致**——文件已在新位置，DB 仍记录旧路径。
- **原因**：shutil.move/Path.rename 不支持事务，是文件系统固有约束
- **影响**：
  - 极端场景下（DB 锁、磁盘满）用户文件已移动但应用显示旧位置
  - 用户下次扫描会重新识别新路径，但旧 ContentUnit 记录会残留为"路径丢失"状态（虽然 Task 3c 延期，但实际行为存在）
  - 当前代码注释虽承认此约束，但无用户可见的错误提示
- **建议方案**：
  1. 当前 Code Review 阶段：在 `_handle_service_error` 中针对此类错误提供更明确的用户提示（"文件已移动但元数据更新失败，请手动刷新或重新扫描"）
  2. 长期：考虑写入"补偿日志"（记录文件已成功移动但 DB 未更新），下次启动时尝试补偿。记入技术债。

### H5: TD-H9 content_unit.path UNIQUE 约束绕过 make_path_key（未修复）

- **问题**：`content_unit` 表 `path` 列有 UNIQUE 约束（`migrations.py:191`），但 Windows 大小写不敏感场景下，同一路径的不同表示（如 `C:\Mods` vs `c:\mods`）无法被 UNIQUE 约束拦截。`make_path_key`（normcase+normpath）在应用层统一了比较，但 DB 层未使用 path_key。
- **原因**：v7 迁移时本应处理此问题，但 v7 实际用于 thumbnail_cache，未处理 content_unit
- **影响**：极端场景下可能产生重复 ContentUnit 记录（不同大小写路径）。当前应用层 make_path_key 已规避大部分场景，但非完全保障。
- **建议方案**：v11 schema 迁移时新增 `path_key` 列并加 UNIQUE 约束（与 managed_root/staging_area 模式一致）。**不建议当前 Code Review 阶段处理（涉及 schema 迁移和数据回填）**，记入技术债更新。

---

## 3. 建议当前修复问题（Medium Priority）

### M1: TD-L11 file_classify.py 部分死代码

- **问题**：`AssetHint` 枚举、`classify_by_extension` 函数、`IMAGE_EXTENSIONS` 常量（`src/infrastructure/file_classify.py:16-44,94-101`）无外部引用，仅 tests/test_file_classify.py 引用。docstring 引用已不存在的 FileAsset 表。
- **修改成本**：低（删除 3 个符号 + 对应测试）
- **收益**：消除认知负担，移除过时文档引用
- **是否推荐现在修复**：是。保留 `ARCHIVE_EXTENSIONS` 和 `get_extension`（仍被 file_scanner.py 使用）。

### M2: TD-M3 application.errors.ScanError 死代码

- **问题**：`src/application/errors.py:25-26` 的 `ScanError` 从未被 raise/except/import，与 `file_scanner.ScanError` dataclass 同名易混淆。
- **修改成本**：极低（删除 2 行）
- **收益**：消除同名歧义
- **是否推荐现在修复**：是。

### M3: TD-L12 conftest.py sample_mod_tree fixture 死代码

- **问题**：`tests/conftest.py:70-106` 的 `sample_mod_tree` fixture 无任何测试引用。
- **修改成本**：极低（删除 36 行）
- **收益**：减少测试基础设施噪音
- **是否推荐现在修复**：是。

### M4: TD-M18 误导性测试（2 处）

- **问题**：`tests/test_managed_root_repository.py:223-249` `test_delete_commits_without_explicit_commit` 和 `tests/test_managed_root_service.py:338-371` `test_remove_root_persists_without_explicit_commit` 声称"自提交"，实际因未 commit 时 create 也被回滚，测试通过是假阳性。
- **修改成本**：中（重写测试为正确验证事务边界，或删除）
- **收益**：消除虚假保障，避免维护者基于错误假设扩展
- **是否推荐现在修复**：是。建议删除这两个测试，因为当前 Repository 不自提交是设计契约，测试"自提交"本身已无意义。

### M5: TD-M20 局部 db_connection fixture 遮蔽 conftest

- **问题**：`tests/test_content_service.py:26-34` 局部 `db_connection` fixture 用 `tmp_path / "test.db"`，遮蔽 conftest 的同名 fixture（用 `temp_app_data` 隔离路径）。
- **修改成本**：极低（删除 9 行局部 fixture）
- **收益**：统一测试隔离路径，避免污染
- **是否推荐现在修复**：是。

### M6: TD-L17 __import__ hack

- **问题**：`tests/test_managed_root_service.py:352, 366` 用 `__import__("sqlite3").Row` 而非顶部 `import sqlite3`。
- **修改成本**：极低（替换为正常 import）
- **收益**：可读性提升
- **是否推荐现在修复**：是。配合 M4 删除误导性测试后，这两处也可能随之删除。

### M7: TD-M4 FolderTreeService 类型标注缺失

- **问题**：`src/application/folder_tree_service.py:126` `fc_root_map: dict[str, object]` 应为 `dict[str, FolderCache]`，导致第 144 行需要 `# type: ignore[union-attr]`。
- **修改成本**：极低（添加 import + 修改类型标注 + 删除 type: ignore）
- **收益**：类型安全提升
- **是否推荐现在修复**：是。

### M8: TD-M19 upsert_mtime path 参数冗余

- **问题**：`src/infrastructure/repositories/folder_cache.py:105` `upsert_mtime(path, mtime, folder_id)` 的 `path` 参数从未参与 SQL。
- **修改成本**：中（需同步修改 3 处调用方：`folder_cache_sync_helper.py:165,214`、`scan_service.py:222`）
- **收益**：消除误导性 API
- **是否推荐现在修复**：是。

### M9: TD-L6 logging_setup.py docstring 路径名过时

- **问题**：`src/app/logging_setup.py:3` 写 `SkyrimModWorkbench`，实际为 `SkyrimContentWorkbench`。
- **修改成本**：极低（改 1 行）
- **收益**：文档准确性
- **是否推荐现在修复**：是。

### M10: TD-L15 init_db schema_version 初始化与首次迁移同事务

- **问题**：`src/infrastructure/db.py:78-96` 中 `_ensure_schema_version_table` + v0 基线 INSERT 实际与 v0→v1 迁移落在同一隐式事务，与 docstring "每步迁移在独立事务中执行" 不一致。
- **修改成本**：低（在 v0 基线 INSERT 后显式 commit）
- **收益**：与文档契约一致
- **是否推荐现在修复**：是。

### M11: TD-L10 _on_scan_started 与 _begin_scanning 状态设置重复

- **问题**：`src/app/main_window.py:692,709-710` 两处都设置 `STATUS_SCANNING`。
- **修改成本**：极低
- **收益**：消除冗余
- **是否推荐现在修复**：是（如果在 MainWindow 拆分时一并处理则更优）。

### M12: 冗余索引清理

- **问题**：5 处对 UNIQUE 列额外建普通索引（`idx_managed_root_path_key`、`idx_content_unit_path`、`idx_folder_cache_path`、`idx_staging_area_path_key`、`idx_content_unit_tag_cu`）。
- **修改成本**：中（需 v11 迁移 DROP INDEX，并验证无查询计划依赖）
- **收益**：减少写入开销和存储
- **是否推荐现在修复**：否（涉及 schema 迁移，与 H5 一并处理）。记入技术债。

### M13: Domain 层校验缺口

- **问题**：`ContentUnit.status`、`ContentUnit.content_type`、`ThumbnailCache.status` 在 domain 层 `__post_init__` 无取值范围校验，与 `OperationHistory.operation_type` 的严格校验形成对比。
- **修改成本**：低（添加 VALID_STATUS 常量 + 校验逻辑 + 测试）
- **收益**：早期暴露非法取值，避免到 repository 层才报错
- **是否推荐现在修复**：是（仅添加校验，不改 schema）。

### M14: TD-M1 ScanSummary.success 恒返回 True

- **问题**：`src/application/scan_service.py` `ScanSummary.success` 属性实现为 `return True`，docstring 暗示会基于 errors 判定。
- **修改成本**：极低（改为 `return not self.has_errors`）
- **收益**：消除误导性 API
- **是否推荐现在修复**：是。

---

## 4. Technical Debt 更新建议

### 新增

| 编号   | 严重级别 | 问题                                                                                  | 建议修复阶段                                             |
| ------ | -------- | ------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| TD-H11 | High     | operation_history.source_path 在 undo 记录中存 ID 而非路径（H3）                      | v11 schema 迁移时新增 `original_op_id` 列                |
| TD-H12 | High     | 文件操作与 DB 事务不一致窗口未补偿（H4）                                              | Stage 6 或后续迭代，引入补偿日志机制                     |
| TD-M31 | Medium   | MainWindow 业务逻辑泄漏：21 处 `_commit()` + 文件操作编排 + 冲突解决编排 2 个重复方法 | UI 重构版本（与 TD-M21 拆分同步）                        |
| TD-M32 | Medium   | UndoService 安全校验无 size/mtime 比对（仅诊断记录）                                  | Stage 6 或后续，需 schema 扩展存储操作前快照             |
| TD-M33 | Medium   | mark_undone 失败可能导致重复撤销（依赖调用方重新查询）                                | 与 TD-M32 一并处理，引入版本号或乐观锁                   |
| TD-M34 | Medium   | 覆盖模式子节点 folder_cache 不立即重建，需等下次扫描                                  | 下次扫描优化时处理                                       |
| TD-M35 | Medium   | rename 跨盘抛 FileOperationError，move 抛 CrossDriveError，异常类型不一致             | 统一异常类型                                             |
| TD-L23 | Low      | content_unit.content_type 默认 'mod' 与实体名不一致                                   | 未来支持多类型时重构                                     |
| TD-L24 | Low      | FileEntry 类名与注释不一致（类名 FileEntry，注释"目录条目"）                          | UI 重构时一并考虑                                        |
| TD-L25 | Low      | FileOperationService._sync_on_delete 访问 helper 私有 `_repo`（`# noqa: SLF001`）     | FolderCacheSyncHelper 增加"按路径前缀批量删除"语义化方法 |
| TD-L26 | Low      | time 字段后缀不统一（`_mtime` vs `_at`，REAL vs TEXT）                                | 文档统一约定                                             |
| TD-L27 | Low      | ClipboardEntry.timestamp 字段未使用（潜在死代码）                                     | 确认是否预留，否则删除                                   |
| TD-L28 | Low      | UI 中"目录"和"文件夹"混用                                                             | UI 重构时统一                                            |

### 完成（已修复，可标记关闭）

| 编号   | 修复版本         |
| ------ | ---------------- |
| TD-H1  | Stage 5 Task 0 ✅ |
| TD-H2  | Stage 4.5 ✅      |
| TD-H4  | v0.15.1 ✅        |
| TD-H5  | v0.15.1 ✅        |
| TD-H6  | v0.15.1 ✅        |
| TD-H7  | v0.16.0 ✅        |
| TD-H8  | v0.16.0 ✅        |
| TD-M11 | Stage 5 Task 0 ✅ |
| TD-M22 | Stage 4.5 ✅      |
| TD-M25 | Stage 4 Task 0 ✅ |
| TD-L18 | Stage 4.5 ✅      |
| TD-L19 | Stage 5 Task 0 ✅ |
| TD-L20 | Stage 4 Task 0 ✅ |

### 延期（保持 open，理由说明）

| 编号            | 延期理由                                                      |
| --------------- | ------------------------------------------------------------- |
| TD-H3           | UI 冻结问题，建议与 TD-M21 MainWindow 拆分一并处理            |
| TD-H9           | content_unit.path_key 列，需 v11 schema 迁移，与 H5 一并处理  |
| TD-H10          | FileOperationService 分层迁移，D5=B 决策延后，UI 重构时评估   |
| TD-M21          | MainWindow God Object 拆分，明确 UI 重构版本处理              |
| TD-M23          | folder_cache 全表扫描性能，非阻塞，Stage 6 评估               |
| TD-M26          | MainWindow 集成测试，与 TD-M21 拆分同步                       |
| TD-M27          | SQLite 并发写测试，非阻塞                                     |
| TD-M28          | N+1 查询性能优化，与 TD-H3 一并处理                           |
| TD-M29          | 测试组织风格统一，非阻塞                                      |
| TD-M30          | "最近常用置顶"标签排序，需用户决策                            |
| TD-L21          | UI 样式表硬编码颜色，暗色模式时处理                           |
| TD-L22          | status 字段重构为 is_marked: bool，破坏性重构，当前两态已满足 |
| 其余 Medium/Low | 非阻塞，择机处理                                              |

---

## 5. Open Questions 更新建议

### 已关闭

| 编号 | 主题                           | 关闭理由                                                               |
| ---- | ------------------------------ | ---------------------------------------------------------------------- |
| Q1   | 标签预制库内容                 | Stage 4 Task 1 已实现 `default_tags.json`，含 6 分类                   |
| Q2   | 搜索索引选型                   | Stage 5 Task 7 已确认 Q2=A（实际实现 Q2=B 仅搜 organized，注释需修正） |
| Q7   | FolderTreeModel 惰性加载技术债 | 新架构 `canFetchMore`/`fetchMore` 已正确实现，无无限递归问题           |

### 待处理（未解决但当前不阻塞）

| 编号 | 主题           | 现状                                     |
| ---- | -------------- | ---------------------------------------- |
| Q3   | 导入预览图方式 | Stage 6 范围，当前不迫切                 |
| Q4   | AI JSON Schema | Stage 6 Task 1 实施前决定                |
| Q5   | 开源许可证     | 仓库已有 MIT LICENSE，Stage 6 发布前复核 |
| Q6   | 扫描取消机制   | 当前扫描速度可接受，按用户反馈决定       |

### 需要我决定

#### D1: ModGroupService 命名与职责重构

**现状**：`src/application/mod_group_service.py` 实际创建的是 ContentUnit，但文件名/类名/方法名/UI 文本都沿用 "Mod 组"。`content_service.py:433` 注释直接承认 "若某个文件夹已被标记为内容单元（即 Mod 组文件夹）"。UI 中 "Mod 组" 与 "内容单元" 混用。

**方案 A（推荐）**：保留 "Mod 组" 作为 UI 术语（用户认知友好），但代码层面重命名为 `ContentUnitCreationService` 或合并到 `ContentService`。
- 影响：代码重构（1 个文件 + 调用方），UI 文本不变
- 收益：消除代码层面概念混乱

**方案 B**：UI 和代码统一改为 "内容单元"，删除 "Mod 组" 术语。
- 影响：UI 文本大量修改 + 用户认知变化
- 收益：完全统一命名

**方案 C**：保持现状，仅在文档中明确"Mod 组 = 内容单元"。
- 影响：无
- 收益：消除歧义但无代码改动

请选择：A / B / C？

#### D2: status 字段是否重构为 is_marked: bool

**现状**：`ContentUnit.status` 仅剩两态（organized / unmarked），语义等价于布尔 `is_marked`。schema DEFAULT 仍为旧值 'unorganized'（由应用层接管）。

**方案 A**：保持现状，仅修复 schema DEFAULT 和注释。
- 影响：v11 迁移改 DEFAULT
- 收益：低风险

**方案 B**：重构为 `is_marked: bool`，v11 迁移。
- 影响：破坏性 schema 迁移 + 全代码字段重命名
- 收益：语义清晰，消除 "organized" 字面歧义

请选择：A / B？

#### D3: "organized" 状态值是否重命名

**现状**：`status='organized'` 字面意思是"已整理归类"，实际语义是"已标记为内容单元"。`unmarked` 是"已取消标记"。

**方案 A**：重命名为 `marked` / `unmarked`（与 is_marked 一致）。
**方案 B**：保持 `organized` / `unmarked`，仅文档说明。
**方案 C**：与 D2 一并决策。

请选择：A / B / C？

#### D4: operation_history.source_path 复用问题

**现状**：undo 记录的 `source_path` 存的是原 history.id 而非路径（H3）。

**方案 A（推荐）**：v11 迁移新增 `original_op_id` 列，undo 记录的 source_path 留空或存原操作路径。
**方案 B**：保持复用，仅添加注释和 domain 层校验。
**方案 C**：新增 `op_metadata` JSON 列存储 undo 关联信息。

请选择：A / B / C？

#### D5: TD-H10 FileOperationService 分层迁移时机

**现状**：FileOperationService 在 infrastructure 层但承担 application 层职责，UndoService 通过 TYPE_CHECKING 反向导入。

**方案 A**：UI 重构版本前先迁移到 application 层。
**方案 B**：UI 重构时一并处理。
**方案 C**：保持现状，文档说明特殊角色。

请选择：A / B / C？

---

## 6. Stage 5 后任务分类

### A. 建议当前 Code Review 一起修复

| 项  | 类型            | 说明                                         |
| --- | --------------- | -------------------------------------------- |
| H1  | 文档同步        | architecture.md 更新到 v10 现状              |
| H2  | 注释修正        | search_service.py:7 Q2=A→Q2=B                |
| H3  | 文档说明        | undo 记录 source_path 语义说明 + domain 校验 |
| M1  | 死代码          | TD-L11 file_classify.py 部分                 |
| M2  | 死代码          | TD-M3 errors.ScanError                       |
| M3  | 死代码          | TD-L12 sample_mod_tree fixture               |
| M4  | 误导性测试      | TD-M18 删除 2 个测试                         |
| M5  | fixture 遮蔽    | TD-M20 删除局部 fixture                      |
| M6  | __import__ hack | TD-L17                                       |
| M7  | 类型标注        | TD-M4                                        |
| M8  | 冗余参数        | TD-M19 upsert_mtime                          |
| M9  | docstring       | TD-L6 logging_setup                          |
| M10 | 事务边界        | TD-L15 init_db                               |
| M11 | 冗余状态        | TD-L10                                       |
| M13 | Domain 校验     | status/content_type 取值校验                 |
| M14 | 误导性 API      | TD-M1 ScanSummary.success                    |

**理由**：均为低风险、明确范围、不涉及 UI 设计、修复收益明显。预计可在 1-2 个小批次内完成。

### B. 建议单独开版本修复

| 项                   | 类型                                                       | 建议版本                      |
| -------------------- | ---------------------------------------------------------- | ----------------------------- |
| TD-M21 + TD-M31      | MainWindow God Object 拆分 + 业务逻辑泄漏                  | UI 重构版本（前置）           |
| TD-H10               | FileOperationService 分层迁移                              | UI 重构版本（与 D5 决策一致） |
| TD-H3 + TD-M28       | UI 冻结 + N+1 查询性能优化                                 | 性能优化版本                  |
| H4 + TD-M32 + TD-M33 | 文件操作事务一致性 + undo 安全校验 + mark_undone 重复撤销  | 数据一致性版本（Stage 6 前）  |
| H5 + TD-H9 + M12     | v11 schema 迁移（path_key + 冗余索引清理 + D2/D3/D4 决策） | schema 迁移版本               |
| UI 重构清单 8 项     | UI 交互优化                                                | UI 重构版本                   |
| TD-M26               | MainWindow 集成测试                                        | 与 TD-M21 拆分同步            |
| TD-M29               | 测试组织风格统一                                           | 独立批次                      |

**理由**：涉及大量代码调整、UI 架构变化、schema 迁移或需要重新设计交互，适合作为独立版本。

### C. 暂时不处理

| 项            | 理由                                              |
| ------------- | ------------------------------------------------- |
| TD-M23        | folder_cache 全表扫描，当前规模无感，Stage 6 评估 |
| TD-M27        | SQLite 并发写测试，极端场景，非阻塞               |
| TD-M30        | "最近常用置顶"需用户产品决策                      |
| TD-L21        | UI 样式表硬编码颜色，暗色模式时处理               |
| TD-L22        | status 重构为 is_marked，破坏性，当前两态已满足   |
| TD-L23        | content_type 默认 'mod'，未来支持多类型时重构     |
| TD-L24        | FileEntry 类名，UI 重构时一并考虑                 |
| TD-L26        | time 字段后缀不统一，文档约定即可                 |
| TD-L27        | ClipboardEntry.timestamp，确认用途后决定          |
| archive/ 目录 | 有意保留的历史归档                                |
| Q3/Q4/Q5/Q6   | Stage 6 范围                                      |

---

## 7. 下一步推荐

### 推荐执行顺序

**第一批：当前 Code Review 修复（1-2 批次）**

1. **文档同步**（H1）：更新 architecture.md 到 v10，补充 v7-v10 迁移说明、staging_area 表、thumbnail_cache 复合主键描述
2. **注释与文档修正**（H2、H3、M9）：search_service.py 注释、undo source_path 说明、logging_setup docstring
3. **死代码清理**（M1、M2、M3）：file_classify.py 部分、errors.ScanError、sample_mod_tree fixture
4. **测试修正**（M4、M5、M6）：删除误导性测试、删除局部 fixture、修复 __import__ hack
5. **类型与 API 修正**（M7、M8、M14）：FolderTreeService 类型标注、upsert_mtime 参数、ScanSummary.success
6. **Domain 校验增强**（M13）：ContentUnit.status/content_type、ThumbnailCache.status 取值校验
7. **事务边界修正**（M10、M11）：init_db 事务、扫描状态冗余

每批完成后运行 `ruff check src tests` + `ruff format --check src tests` + `pytest`，确保不回归。

**第二批：等待用户决策后处理（D1-D5）**

- 根据用户对 D1-D5 的选择，决定是否在当前批次处理 ModGroupService 重命名、status 字段重构、operation_history schema 等。

**第三批：进入 UI 重构版本（独立版本）**

1. 先做 MainWindow 拆分（TD-M21 + TD-M31），至少拆出：
   - `ScanController`（扫描线程生命周期）
   - `AssemblyController`（装配面板绑定 + 快速插入流程）
   - `MetadataView`（元数据 + Elide 渲染）
   - `ModeController`（模式切换）
   - `TransactionScope`（事务边界，从 UI 移到 Application 层）
2. 同步处理 TD-H10（FileOperationService 分层迁移）
3. 拆分完成后补充 MainWindow 集成测试（TD-M26）
4. 再处理 UI 重构清单 8 项

**第四批：schema 迁移版本（v11）**

- 等待 D2/D3/D4 决策后，统一处理：
  - content_unit 新增 path_key 列（H5 + TD-H9）
  - operation_history 新增 original_op_id 列（D4）
  - 冗余索引清理（M12）
  - status DEFAULT 修正或 is_marked 重构（D2/D3）

**第五批：数据一致性版本（Stage 6 前）**

- 文件操作事务不一致补偿机制（H4 + TD-M32 + TD-M33）
- undo 安全校验增强（存储操作前快照）
- 性能优化（TD-H3 + TD-M28）

### 关键建议

1. **不要在当前 Code Review 阶段动 MainWindow**。任何对 MainWindow 的修改都会牵连多个状态机，风险极高。MainWindow 的所有问题留给 UI 重构版本一次性处理。

2. **schema 迁移集中到 v11 一次性完成**。当前有 H5、TD-H9、D2/D3/D4 多个 schema 待办，分散迁移成本高。建议收集所有 schema 变更需求后统一 v11 迁移。

3. **文档同步是当前最高优先级**。架构文档滞后 4 个版本是事实性错误，会误导所有后续工作。H1 必须在当前 Code Review 阶段完成。

4. **D1-D5 决策影响后续版本规划**。请先回答 D1-D5，再确定下一阶段的具体 Task 拆分。

---

需要你回答的关键问题：

1. **D1-D5 的选择**（详见第 5 节"需要我决定"部分）
2. **第一批修复是否授权开始执行**？（建议分 3-4 个小批次，每批完成后 review）
3. **是否同意"不动 MainWindow"原则**？（MainWindow 所有问题留到 UI 重构版本）

请确认后我再制定具体的 Task 拆分和执行计划。