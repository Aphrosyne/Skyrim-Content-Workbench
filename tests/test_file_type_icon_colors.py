"""文件类型图标颜色配置测试（UI合理性4 二期，2026-08-04）。"""

from __future__ import annotations

from app import file_type_icon_colors as config
from app import ui_constants as ui


def _clear_all(settings) -> None:
    config.clear_colors(settings)


def test_load_returns_defaults_when_nothing_saved(settings_ini) -> None:
    _clear_all(settings_ini)
    colors = config.load_colors(settings_ini)
    assert colors == ui.FILE_TYPE_ICON_COLORS


def test_save_and_load_roundtrip(settings_ini) -> None:
    _clear_all(settings_ini)
    custom = {
        "folder": "#111111",
        "archive": "#222222",
        "image": "#333333",
        "document": "#444444",
    }
    config.save_colors(settings_ini, custom)
    assert config.load_colors(settings_ini) == custom


def test_partial_save_falls_back_to_defaults(settings_ini) -> None:
    _clear_all(settings_ini)
    settings = settings_ini
    settings.setValue(ui.QSETTINGS_KEY_ICON_COLOR_FOLDER, "#abcdef")
    colors = config.load_colors(settings)
    assert colors["folder"] == "#abcdef"
    assert colors["archive"] == ui.FILE_TYPE_ICON_COLORS["archive"]
    assert colors["image"] == ui.FILE_TYPE_ICON_COLORS["image"]
    assert colors["document"] == ui.FILE_TYPE_ICON_COLORS["document"]


def test_clear_removes_all_saved_keys(settings_ini) -> None:
    _clear_all(settings_ini)
    settings = settings_ini
    settings.setValue(ui.QSETTINGS_KEY_ICON_COLOR_FOLDER, "#abcdef")
    settings.setValue(ui.QSETTINGS_KEY_ICON_COLOR_ARCHIVE, "#123456")
    config.clear_colors(settings)
    assert not settings.contains(ui.QSETTINGS_KEY_ICON_COLOR_FOLDER)
    assert not settings.contains(ui.QSETTINGS_KEY_ICON_COLOR_ARCHIVE)
