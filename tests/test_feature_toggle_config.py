"""右键功能开关配置测试（设计合理性1，2026-08-04）。"""

from __future__ import annotations

from PySide6.QtCore import QSettings

from app import ui_constants as ui
from app.feature_toggle_config import FEATURE_TOGGLE_IDS, FeatureToggleConfig


def _settings() -> QSettings:
    return QSettings(ui.QSETTINGS_ORGANIZATION, ui.QSETTINGS_APPLICATION)


class TestFeatureToggleConfig:
    def test_defaults_all_enabled(self) -> None:
        cfg = FeatureToggleConfig.defaults()
        assert len(cfg.enabled) == len(FEATURE_TOGGLE_IDS)
        assert all(cfg.is_enabled(fid) for fid in FEATURE_TOGGLE_IDS)

    def test_load_empty_returns_defaults(self) -> None:
        cfg = FeatureToggleConfig.load(_settings())
        assert cfg == FeatureToggleConfig.defaults()

    def test_save_and_load_roundtrip(self) -> None:
        settings = _settings()
        custom = FeatureToggleConfig.defaults()
        custom.toggle("browser_search", False)
        custom.toggle("strip", False)
        custom.save(settings)

        loaded = FeatureToggleConfig.load(settings)
        assert not loaded.is_enabled("browser_search")
        assert not loaded.is_enabled("strip")
        assert loaded.is_enabled("open")

    def test_unknown_feature_id_defaults_enabled(self) -> None:
        cfg = FeatureToggleConfig.defaults()
        assert cfg.is_enabled("future_feature")

    def test_reset_defaults(self) -> None:
        cfg = FeatureToggleConfig.defaults()
        cfg.toggle("open", False)
        cfg.reset_defaults()
        assert cfg == FeatureToggleConfig.defaults()
