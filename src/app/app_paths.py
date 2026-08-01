r"""应用数据目录管理（Task 0.5 数据目录迁移）。

路径决策优先级：
1. SCW_DATA_DIR 环境变量（显式指定，生产环境用）
2. 项目根目录/data/（开发环境默认，通过向上查找 pyproject.toml 判定）
3. %LOCALAPPDATA%\SkyrimContentWorkbench\（Windows 回退）
4. ~/.skyrimmodworkbench/（非 Windows 回退）

本模块只负责路径决策与目录创建，**不执行任何数据迁移、复制、删除操作**。
（UX 重构 Task 6：旧 `%LOCALAPPDATA%\SkyrimContentWorkbench\` 检测/迁移提示代码已移除；
`%LOCALAPPDATA%` 仍作为 Windows 回退路径保留，见 open-questions §7。）

本模块不复制、不修改用户 Mod 文件；仅管理应用自身数据目录。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

APP_DATA_DIR_NAME = "SkyrimContentWorkbench"

# 环境变量名（Task 0.5 决策 Q6=A）
ENV_DATA_DIR = "SCW_DATA_DIR"

# 项目根目录标志文件（用于判断是否在开发环境运行）
_PROJECT_MARKER = "pyproject.toml"

# 向上查找项目根的最大层数
_MAX_PARENT_DEPTH = 5


def get_app_data_root() -> Path:
    r"""返回应用数据根目录。

    优先级（Task 0.5）：
    1. SCW_DATA_DIR 环境变量（显式指定，生产环境用）
    2. 项目根目录/data/（开发环境默认）
    3. %LOCALAPPDATA%\SkyrimContentWorkbench\（Windows 回退）
    4. ~/.skyrimmodworkbench/（非 Windows 回退）
    """
    # 1. 环境变量优先
    env_data_dir = os.environ.get(ENV_DATA_DIR)
    if env_data_dir:
        return Path(env_data_dir)

    # 2. 开发环境默认：项目根目录/data/
    project_root = _find_project_root()
    if project_root is not None:
        return project_root / "data"

    # 3. 回退：%LOCALAPPDATA%\SkyrimContentWorkbench\
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_DATA_DIR_NAME

    # 4. 非 Windows 回退
    return Path.home() / f".{APP_DATA_DIR_NAME.lower()}"


def _find_project_root() -> Path | None:
    """向上查找项目根目录（含 pyproject.toml 的目录）。

    用于判断是否在开发环境运行。找不到则返回 None（生产环境）。
    从本文件所在目录向上查找，最多 _MAX_PARENT_DEPTH 层。
    """
    current = Path(__file__).resolve().parent  # src/app/
    for _ in range(_MAX_PARENT_DEPTH):
        if (current / _PROJECT_MARKER).exists():
            return current
        current = current.parent
    return None


def get_app_db_path() -> Path:
    """返回 SQLite 数据库文件路径。"""
    return get_app_data_root() / "app.db"


def get_thumbnails_dir() -> Path:
    """返回缩略图缓存目录路径。"""
    return get_app_data_root() / "thumbnails"


def get_exports_dir() -> Path:
    """返回 AI JSON 导出目录路径。"""
    return get_app_data_root() / "exports"


def get_logs_dir() -> Path:
    """返回日志目录路径。"""
    return get_app_data_root() / "logs"


def ensure_app_directories() -> Path:
    """创建应用数据根目录及子目录。

    返回应用数据根目录路径。

    目录已存在时不报错。权限错误向上抛出，由调用方转为用户可读错误。

    本函数不执行任何迁移、复制、删除操作。若检测到旧
    %LOCALAPPDATA%\\SkyrimContentWorkbench\\ 有数据，仅输出日志提示
    用户手动迁移（用户决策：程序不动数据）。
    """
    root = get_app_data_root()
    # 创建目录
    for d in (root, get_thumbnails_dir(), get_exports_dir(), get_logs_dir()):
        d.mkdir(parents=True, exist_ok=True)

    return root
