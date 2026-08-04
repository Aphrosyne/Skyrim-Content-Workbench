"""文件类型图标颜色配置（UI合理性4 二期，2026-08-04）。

QSettings 持久化，键 ``icon_color/{type}``；未保存的键回退
``ui_constants.FILE_TYPE_ICON_COLORS`` 默认值。
入口：顶部菜单「视图 → 文件类型图标颜色…」。
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

from app import ui_constants as ui

# 类型键 → QSettings 键
_QSETTINGS_KEYS: dict[str, str] = {
    "folder": ui.QSETTINGS_KEY_ICON_COLOR_FOLDER,
    "archive": ui.QSETTINGS_KEY_ICON_COLOR_ARCHIVE,
    "image": ui.QSETTINGS_KEY_ICON_COLOR_IMAGE,
    "document": ui.QSETTINGS_KEY_ICON_COLOR_DOCUMENT,
}


def load_colors(qsettings: QSettings) -> dict[str, str]:
    """读取配置：已保存的键取保存值，未保存的键回退默认值。"""
    colors: dict[str, str] = {}
    for type_key, default in ui.FILE_TYPE_ICON_COLORS.items():
        saved = qsettings.value(_QSETTINGS_KEYS[type_key], default, type=str)
        colors[type_key] = saved if isinstance(saved, str) and saved.strip() else default
    return colors


def save_colors(qsettings: QSettings, colors: dict[str, str]) -> None:
    """保存全部四类颜色（上层在对话框确定后调用）。"""
    for type_key, color_hex in colors.items():
        if type_key in _QSETTINGS_KEYS and color_hex:
            qsettings.setValue(_QSETTINGS_KEYS[type_key], color_hex)


def clear_colors(qsettings: QSettings) -> None:
    """清除全部颜色存档（恢复默认时调用）。"""
    for key in _QSETTINGS_KEYS.values():
        qsettings.remove(key)
