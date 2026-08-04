"""文件类型图标颜色配置测试（UI合理性4 二期，2026-08-04）。"""

from __future__ import annotations

from PySide6.QtCore import QSettings

from app import file_type_icon_colors as config
from app import ui_constants as ui


def _settings() -> QSettings:
    return QSettings(ui.QSETTINGS_ORGANIZATION, ui.QSETTINGS_APPLICATION)


def _clear_all() -> None:
    config.clear_colors(_settings())


def test_load_returns_defaults_when_nothing_saved() -> None:
    _clear_all()
    colors = config.load_colors(_settings())
    assert colors == ui.FILE_TYPE_ICON_COLORS


def test_save_and_load_roundtrip() -> None:
    _clear_all()
    custom = {
        "folder": "#111111",
        "archive": "#222222",
        "image": "#333333",
        "document": "#444444",
    }
    config.save_colors(_settings(), custom)
    assert config.load_colors(_settings()) == custom


def test_partial_save_falls_back_to_defaults() -> None:
    _clear_all()
    settings = _settings()
    settings.setValue(ui.QSETTINGS_KEY_ICON_COLOR_FOLDER, "#abcdef")
    colors = config.load_colors(settings)
    assert colors["folder"] == "#abcdef"
    assert colors["archive"] == ui.FILE_TYPE_ICON_COLORS["archive"]
    assert colors["image"] == ui.FILE_TYPE_ICON_COLORS["image"]
    assert colors["document"] == ui.FILE_TYPE_ICON_COLORS["document"]


def test_clear_removes_all_saved_keys() -> None:
    _clear_all()
    settings = _settings()
    settings.setValue(ui.QSETTINGS_KEY_ICON_COLOR_FOLDER, "#abcdef")
    settings.setValue(ui.QSETTINGS_KEY_ICON_COLOR_ARCHIVE, "#123456")
    config.clear_colors(settings)
    assert not settings.contains(ui.QSETTINGS_KEY_ICON_COLOR_FOLDER)
    assert not settings.contains(ui.QSETTINGS_KEY_ICON_COLOR_ARCHIVE)
