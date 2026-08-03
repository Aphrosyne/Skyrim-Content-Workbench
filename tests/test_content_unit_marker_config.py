"""内容单元标记配置模型测试（UI合理性21，2026-08-04）。

覆盖：
- 默认配置：仅启用色条（紫色），🔗 预填但不启用
- reserved_width：仅色条 5 / 仅图标 18 / 双启用 23
- QSettings 读写 roundtrip 与缺省回退
- validate_config：双关被拒、单字符校验
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from app import ui_constants as ui
from app.content_unit_marker_config import (
    ContentUnitMarkerConfig,
    validate_config,
)


def _settings(path: Path) -> QSettings:
    return QSettings(str(path), QSettings.Format.IniFormat)


def test_defaults_only_stripe_enabled() -> None:
    config = ContentUnitMarkerConfig.defaults()
    assert config.icon_enabled is False
    assert config.icon_glyph == ui.CONTENT_UNIT_MARKER
    assert config.stripe_enabled is True
    assert config.stripe_color == ui.CONTENT_UNIT_STRIPE_COLOR
    assert config.reserved_width == 5


def test_reserved_width_combos() -> None:
    assert (
        ContentUnitMarkerConfig(
            icon_enabled=False,
            icon_glyph="🔗",
            stripe_enabled=True,
            stripe_color="#B39DDB",
        ).reserved_width
        == 5
    )  # 仅色条
    assert (
        ContentUnitMarkerConfig(
            icon_enabled=True,
            icon_glyph="🔗",
            stripe_enabled=False,
            stripe_color="#B39DDB",
        ).reserved_width
        == 18
    )  # 仅图标
    assert (
        ContentUnitMarkerConfig(
            icon_enabled=True,
            icon_glyph="🔗",
            stripe_enabled=True,
            stripe_color="#B39DDB",
        ).reserved_width
        == 23
    )  # 双启用


def test_save_load_roundtrip(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "settings.ini")
    config = ContentUnitMarkerConfig(
        icon_enabled=True,
        icon_glyph="★",
        stripe_enabled=False,
        stripe_color="#FF0000",
    )
    config.save(settings)
    loaded = ContentUnitMarkerConfig.load(settings)
    assert loaded == config


def test_load_missing_keys_falls_back_to_defaults(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "settings.ini")
    assert ContentUnitMarkerConfig.load(settings) == ContentUnitMarkerConfig.defaults()


def test_validate_requires_at_least_one() -> None:
    assert validate_config(False, "🔗", False) == ui.MARKER_CONFIG_NEED_ONE
    assert validate_config(True, "🔗", False) is None
    assert validate_config(False, "🔗", True) is None


def test_validate_glyph_single_character() -> None:
    assert validate_config(True, "ab", True) == ui.MARKER_CONFIG_GLYPH_INVALID
    assert validate_config(True, "  ", True) == ui.MARKER_CONFIG_GLYPH_INVALID
    assert validate_config(True, " 🔗 ", True) is None  # 去空格后单个字符
