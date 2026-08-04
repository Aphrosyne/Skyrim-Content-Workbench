r"""应用数据目录管理（Task 0.5 数据目录迁移）。

路径决策优先级：
1. SCW_DATA_DIR 环境变量（显式指定，生产环境用）
2. 项目根目录/data/（开发环境默认，通过向上查找 pyproject.toml 判定）
3. 程序文件所在位置/data/（打包/独立运行回退）

2026-08-04（用户反馈）：不再回退 %LOCALAPPDATA% 或用户主目录——
应用数据（数据库/缩略图/日志/设置）始终位于程序所在位置内，避免外部残留。
本模块只负责路径决策与目录创建，**不执行任何数据迁移、复制、删除操作**。
（UX 重构 Task 6：旧 `%LOCALAPPDATA%\SkyrimContentWorkbench\` 检测/迁移提示代码已移除；
相关旧路径不再使用。）

本模块不复制、不修改用户 Mod 文件；仅管理应用自身数据目录。"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QSettings

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

    优先级（Task 0.5 + 2026-08-04 收紧）：
    1. SCW_DATA_DIR 环境变量（显式指定，生产环境用）
    2. 项目根目录/data/（开发环境默认）
    3. 程序文件所在位置/data/（打包/独立运行回退）

    2026-08-04（用户反馈）：所有数据写入始终位于程序所在位置内，
    不再回退 %LOCALAPPDATA% 或用户主目录。
    """
    # 1. 环境变量优先
    env_data_dir = os.environ.get(ENV_DATA_DIR)
    if env_data_dir:
        return Path(env_data_dir)

    # 2. 开发环境默认：项目根目录/data/
    project_root = _find_project_root()
    if project_root is not None:
        return project_root / "data"

    # 3. 程序文件所在位置：src/app/app_paths.py → 上溯 3 层到程序根
    return Path(__file__).resolve().parent.parent.parent / "data"


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


def get_app_settings_path() -> Path:
    """返回应用设置文件路径（settings.ini）。

    2026-08-04（用户反馈）：QSettings 默认 NativeFormat 在 Windows 写入注册表，
    统一改用应用数据目录下的 settings.ini 文件存储（跟随 SCW_DATA_DIR / data/ 解析）。
    """
    return get_app_data_root() / "settings.ini"


def get_app_settings() -> QSettings:
    """返回文件形式的应用设置（settings.ini，避免写 Windows 注册表）。"""
    return QSettings(str(get_app_settings_path()), QSettings.Format.IniFormat)


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

    本函数不执行任何迁移、复制、删除操作。
    """
    root = get_app_data_root()
    # 创建目录
    for d in (root, get_thumbnails_dir(), get_exports_dir(), get_logs_dir()):
        d.mkdir(parents=True, exist_ok=True)

    return root
