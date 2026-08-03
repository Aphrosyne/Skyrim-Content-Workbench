# scripts/

开发辅助脚本目录。

## clean.py — 开发环境清理脚本

清理开发过程中产生的临时文件和缓存，保持工作目录整洁。

### 用法

```bash
# 安全清理（默认）
python scripts/clean.py

# 深度清理（额外清理 pytest tmp_path 临时目录）
python scripts/clean.py --all

# 仅查看待清理内容，不实际删除
python scripts/clean.py --dry-run

# 显示详细清理信息
python scripts/clean.py --verbose
```

### 清理范围

**安全清理（默认）**：

| 类型 | 目标 |
|---|---|
| 目录 | `__pycache__/`、`.pytest_cache/`、`.ruff_cache/`、`.cache/`、`build/`、`dist/`、`*.egg-info/` |
| 文件 | `*.pyc`、`*.pyo` |

**深度清理（`--all`）额外清理**：

| 类型 | 目标 | 位置 |
|---|---|---|
| 目录 | `pytest-of-<用户名>/` | 系统 Temp（`%TEMP%`） |

> pytest 在系统 Temp 下创建 `pytest-of-<用户名>/pytest-N/` 目录，用于 `tmp_path` fixture。
> 这些目录包含测试临时文件，可安全删除。深度清理可能释放数百 MB 磁盘空间。

### 不会删除的内容

以下内容**永不会被删除**，可放心运行清理脚本：

**源码与文档**：
- `src/` — 源代码
- `tests/` — 测试代码
- `docs/` — 文档
- `archive/` — 归档文档
- `scripts/` — 脚本

**应用数据**（位于 `%LOCALAPPDATA%\SkyrimContentWorkbench\` 或项目内 `local_appdata/`）：
- `app.db` — 数据库
- `thumbnails/` — 缩略图缓存
- `exports/` — 导出文件
- `logs/` — 日志
- `local_appdata/` — 本地开发运行时数据

**开发工具**：
- `.git/` — 版本控制
- `.venv/`、`venv/` — 虚拟环境
- `.env` — 环境变量
- `LICENSE`、`README.md`、`CHANGELOG.md`、`AGENTS.md`、`pyproject.toml`、`.gitignore`

**用户数据**：
- 用户 Mod 文件不受影响
- 项目外的任何文件不受影响

## clear_legacy_titles.py — 遗留别名清除脚本（UI合理性13）

清除 content_unit 中 title ≠ 文件名（basename）的遗留别名行（title → NULL），
用于 title 列停用后的历史数据清理。

### 用法

```bash
python scripts/clear_legacy_titles.py            # 仅预览（dry-run，不修改）
python scripts/clear_legacy_titles.py --apply    # 实际清除
python scripts/clear_legacy_titles.py --db PATH  # 指定数据库（测试用）
```

### 约束

- 只修改 content_unit.title，不触碰文件系统、不删除记录。
- 幂等：重复执行结果一致。
- 数据库路径默认由 `app.app_paths` 解析（SCW_DATA_DIR > 项目 data/ > LOCALAPPDATA 回退）。

### 测试

```bash
python -m pytest tests/test_clean.py -v
python -m pytest tests/test_clear_legacy_titles.py -v
```

测试覆盖：
- 正确识别缓存目录和 `.pyc` 文件
- 受保护目录（源码、应用数据、虚拟环境）不会被误删
- `--dry-run` 模式不删除任何内容
- 深度清理正确识别 pytest 临时目录
