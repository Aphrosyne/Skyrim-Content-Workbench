# Skyrim Content Workbench

本地优先的 Windows 桌面数字资产管理工具（Skyrim Mod 整理工作台）。真实文件系统是唯一的事实来源，数据库仅作为元数据增强层（标签、备注、来源 URL、封面关联等）。

> **开发状态**：当前为开发版本（[CHANGELOG.md](CHANGELOG.md) 最新 v0.51.0），工作集中在 `ux-redesign` 分支，尚未合并到 `master`、未发布正式版。

## 特性

- 内容单元管理：标记 / 取消标记、标签分类（分类色）、备注、来源 URL、封面关联
- 双视图浏览：目录树（左）+ 列表 / 卡片（中）+ 元数据与文件夹预览面板（右）
- 文件操作：新建、重命名、移动、复制、剪切、粘贴、删除（回收站）、提取内容；冲突处理、操作历史与撤销
- 搜索与筛选：按名称 / 标签 / 备注搜索；标签三态筛选（正选 / 反选 / 排除）、只看有封面
- 文件夹预览面板：钉住 / 透视任意文件夹 / 拖入添加
- 文件类型图标（SVG + 代码染色，CC0 图标包）与内容单元标记配置（行首徽章 + 色条）
- 设置与布局固化：settings.ini 文件化存储，不依赖 Windows 注册表
- 扫描：启动自动增量扫描 + 手动全量重扫

## 快速开始（从源码运行）

环境要求：Windows 10 / 11，Python 3.12+（开发环境实测 3.14）。详细步骤见 [docs/deployment.md](docs/deployment.md)。

```powershell
git clone https://github.com/Aphrosyne/Skyrim-Content-Workbench.git
cd Skyrim-Content-Workbench
python -m venv .venv
.venv\Scripts\python -m pip install -U pip
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python src/app/main.py
```

## 数据目录

应用数据目录解析优先级：`SCW_DATA_DIR` 环境变量 > 项目根 `data/` > 程序所在位置 `data/`。内容包含 `app.db`、`thumbnails/`、`logs/`、`exports/`、`settings.ini`，已被 `.gitignore` 忽略。

## 开发

```powershell
.venv\Scripts\python -m pytest                     # 全量测试
.venv\Scripts\python -m ruff check src tests
.venv\Scripts\python -m ruff format --check src tests
```

- 分层：`src/app`（UI）→ `src/application` → `src/domain` → `src/infrastructure`，上层依赖下层
- 规则：真实文件系统是唯一事实来源；UI 不直接做文件写操作，一律经 `FileOperationService`；路径比较统一用 `make_path_key()`；UI 文本集中在 `src/app/ui_constants.py`

## 文档

- [工程交接](docs/PROJECT_HANDOVER.md) · [规格](docs/spec.md) · [架构](docs/architecture.md)
- [UX 重构路线图](docs/ux-redesign-roadmap.md) · [部署](docs/deployment.md)
- [工作流测试问题记录](docs/workflow-test-issues.md) · [技术债](docs/technical-debt.md) · [未决问题](docs/open-questions.md)
- [变更日志](CHANGELOG.md)

## 许可

[MIT](LICENSE)
