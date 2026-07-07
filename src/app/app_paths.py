r"""应用数据目录管理。

所有应用数据位于 %LOCALAPPDATA%\SkyrimModWorkbench\ 下。
本模块不复制、不修改用户 Mod 文件；仅管理应用自身数据目录。
"""

from __future__ import annotations

import os
from pathlib import Path

APP_DATA_DIR_NAME = "SkyrimModWorkbench"


def get_app_data_root() -> Path:
    """返回应用数据根目录。

    优先使用 LOCALAPPDATA 环境变量；若不存在（非 Windows 或异常情况），
    回退到用户主目录下的 .skyrim-mod-workbench。
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_DATA_DIR_NAME
    return Path.home() / f".{APP_DATA_DIR_NAME.lower()}"


def get_app_db_path() -> Path:
    """返回 SQLite 数据库文件路径。"""
    return get_app_data_root() / "app.db"


def get_thumbnails_dir() -> Path:
    """返回缩略图缓存目录路径。

    注意：缩略图写入逻辑在阶段 2+ 实现，本任务仅创建目录。
    """
    return get_app_data_root() / "thumbnails"


def get_exports_dir() -> Path:
    """返回 AI JSON 导出目录路径。"""
    return get_app_data_root() / "exports"


def get_logs_dir() -> Path:
    """返回日志目录路径。"""
    return get_app_data_root() / "logs"


def ensure_app_directories() -> Path:
    """创建应用数据根目录及子目录。返回根目录路径。

    目录已存在时不报错。权限错误向上抛出，由调用方转为用户可读错误。
    """
    root = get_app_data_root()
    for d in (root, get_thumbnails_dir(), get_exports_dir(), get_logs_dir()):
        d.mkdir(parents=True, exist_ok=True)
    return root
