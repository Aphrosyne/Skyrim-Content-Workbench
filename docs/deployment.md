# 部署文档（从源码运行）

> 状态说明：项目尚未打包发布 release，以下是从源码配置并运行的方法，
> 供感兴趣的人自行测试。

## 环境要求

- **操作系统**：Windows 10 / 11（应用面向 Windows 桌面，其他平台未验证）
- **Python**：3.12 及以上；当前开发环境实测为 **3.14.0**
  - 注意：Python 3.14 必须搭配 PySide6 ≥ 6.10（`pyproject.toml` 已声明
    `PySide6>=6.8,<7`，pip 会自动选择兼容版本）
- **git**：用于克隆仓库（也可以直接拷贝项目目录）

## 获取代码

```powershell
git clone https://github.com/Aphrosyne/Skyrim-Content-Workbench.git
cd Skyrim-Content-Workbench
git checkout ux-redesign
```

`ux-redesign` 是当前开发主线（默认分支 `master` 可能滞后）；使用 SSH 的话
克隆地址为 `git@github.com:Aphrosyne/Skyrim-Content-Workbench.git`。

## 创建虚拟环境并安装依赖

在项目根目录执行：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -U pip
.venv\Scripts\python -m pip install -e ".[dev]"
```

说明：

- `-e ".[dev]"` 为可编辑安装（editable），并同时安装开发依赖（pytest / ruff）。
- 运行时依赖声明在 `pyproject.toml`：`PySide6>=6.8,<7`、`Pillow>=10.0`。
- 仓库已附 `requirements.txt`（锁定 2026-08-05 实测版本，含 pytest/ruff）。
  想完全复现环境可执行 `pip install -r requirements.txt`——文件首行为 `-e .`，
  会一并安装项目本体（详见文件内注释）。

## 启动程序

任选其一（在项目根目录执行）：

```powershell
skyrim-mod-workbench
```

```powershell
.venv\Scripts\python -m app.main
```

```powershell
.venv\Scripts\python src/app/main.py
```

## 首次使用

1. 启动后在左侧「受管理根目录」点击「添加目录」，选择你的 Mod 目录。
2. 启动时会自动增量扫描；也可点击「全量重扫」手动扫描。
3. 所有设置保存在应用数据目录下的 `settings.ini`（**不写注册表**）。

## 数据目录（重要）

应用数据默认位于项目根 `data/`，全部内容如下：

| 内容 | 说明 |
|---|---|
| `app.db` | SQLite 数据库（内容单元元数据、标签、操作历史等） |
| `thumbnails/` | 缩略图缓存（不会修改你的原始图片） |
| `logs/` | 运行日志 |
| `settings.ini` | 全部设置（布局/缩放/归档目录/快捷键/右键功能开关等） |
| `exports/` | 导出目录 |

- 可通过环境变量 `SCW_DATA_DIR` 覆盖数据目录（便携运行 / 测试用）。
- 应用数据始终位于程序所在位置内，**不写 `%LOCALAPPDATA%`、不写注册表**。
- 数据库只是元数据增强层，**真实文件系统是唯一事实来源**：删除 `data/`
  不会影响你的 Mod 文件，最多丢失元数据（标签、备注、来源 URL、封面关联等）。

## 运行测试与代码检查

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check src tests
.venv\Scripts\python -m ruff format --check src tests
```

当前全量测试：**1646 passed / 4 skipped**（2026-08-05）。

## 设备迁移 / 备份

- 备份：整个 `data/` 目录拷贝走即可（数据库 + 缩略图 + 日志 + 设置）。
- 迁移：把 `data/` 放到新机器项目根，再按上文重新创建虚拟环境并安装依赖。

## 常见问题

1. **PySide6 安装慢或失败**：可换国内镜像（如
   `pip install -i https://pypi.tuna.tsinghua.edu.cn/simple ...`）；
   或确认 Python 版本（Python 3.14 需要 PySide6 ≥ 6.10）。
2. **运行报缺少模块**：确认 `pip install -e ".[dev]"` 成功，并在项目根目录运行。
3. **中文路径**：程序全面支持中文路径与 UTF-8。
4. **没有 release 安装包**：目前只能从源码运行，后续打包发布后会更新本文档。

## 当前开发环境实测版本（2026-08-05）

| 组件 | 版本 |
|---|---|
| Python | 3.14.0 |
| pip | 26.2 |
| PySide6 | 6.11.1 |
| Pillow | 12.3.0 |
| pytest | 9.1.1 |
| ruff | 0.16.0 |
