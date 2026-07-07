# 项目进度

本文件追踪 roadmap 各阶段与原子任务的执行进度。每完成一项即更新此处，并在 [CHANGELOG.md](../CHANGELOG.md) 中记录。

图例：

- ✅ 已完成
- ⏳ 进行中
- ⬜ 未开始
- ⛔ 已决定不做（标注原因与决策来源）

---

## 阶段 0：项目初始化  ✅

| 任务 | 状态 | 备注 |
|---|---|---|
| Python 项目初始化 | ✅ | pyproject.toml，requires-python>=3.12 |
| PySide6 空窗口 | ✅ | [src/app/main_window.py](../src/app/main_window.py) |
| SQLite 初始化 | ✅ | [src/infrastructure/db.py](../src/infrastructure/db.py)，schema_version=0 |
| 基础目录结构 | ✅ | src/{app,domain,infrastructure,application}、tests、docs |
| ruff 和 pytest | ✅ | ruff check / format / pytest 全通过 |
| 基础日志 | ✅ | [src/app/logging_setup.py](../src/app/logging_setup.py) |
| 应用数据目录创建 | ✅ | [src/app/app_paths.py](../src/app/app_paths.py) |

**验收**：

- [x] Windows 上可启动空窗口
- [x] 自动创建本地数据库
- [x] 可运行测试和静态检查

**版本标签**：[0.1.0]

---

## 阶段 1：安全数据与文件操作基础  ⬜

| 任务 | 状态 | 备注 |
|---|---|---|
| 受管理根目录配置 | ⬜ | Task 2/3 |
| 文件和目录扫描 | ⬜ | Task 3 |
| FolderNode、FileAsset、ModItem、OperationLog 数据模型 | ⬜ | Task 2 |
| 手动创建 Mod 条目 | ⬜ | Task 4 |
| 手动关联多个 FileAsset | ⬜ | Task 4 |
| 移动预演 | ⬜ | Task 5 |
| 确认后移动 | ⬜ | Task 5 |
| 操作日志 | ⬜ | Task 2/5 |
| 撤销预演与撤销执行 | ⬜ | Task 5 |
| 中文路径测试 | ⬜ | Task 3/5 |

**验收（来自 roadmap）**：

- [ ] 能在测试目录中创建一个包含本体、汉化和预览图的 Mod 条目
- [ ] 能预演并执行整体移动
- [ ] 能在安全条件下撤销
- [ ] 能阻止重名、缺失、目标为子目录等危险操作

---

## 阶段 2：基础桌面工作台  ⬜

未开始。详见 [roadmap.md](roadmap.md) 阶段 2。

## 阶段 3：搜索与 AI JSON 交换  ⬜

未开始。

## 阶段 4：交互优化  ⬜

未开始。

## 阶段 5：预览增强  ⬜

未开始。

## 阶段 6：开源发布准备  ⬜

未开始。

---

## 已确认的关键决策（来自 A/B 类待确认项）

| 编号 | 决策 | 决策内容 | 影响阶段 |
|---|---|---|---|
| A1 | 第一阶段范围 | 仅做 roadmap 阶段 0+1 | 全局 |
| A2 | 路径比较键策略 | 原样存储 real_path，另存 path_key（normcase+normpath）用于比较与唯一约束 | Task 2/3/5 |
| A3 | 受管理根目录与扫描深度 | Mod 根目录与待整理目录均标记 is_managed_root=true；递归扫描；所有子目录生成 FolderNode；重叠目录去重 | Task 3 |
| B1 | 撤销不安全时的行为 | 完全阻止，留下当前文件状态，写日志+用户提示；不做部分回滚 | Task 5 |
| B2 | 跨盘移动的撤销路径 | 校验目标文件 size+mtime 与 OperationLog 记录一致才反向移动，否则拒绝 | Task 5 |
| B3 | conflict_policy 取值集合 | 阶段 1 仅 {ask}，任何重名即阻止 | Task 5 |
| B4 | 外部关联图存储策略 | 仅存原路径，不复制到应用缓存 | 阶段 2+ |

C 类待确认项见 [docs/open-questions.md](open-questions.md)。
