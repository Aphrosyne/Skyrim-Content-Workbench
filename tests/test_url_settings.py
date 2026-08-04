"""网址与搜索设置（操作便捷性8/9，2026-08-04）测试。"""

from __future__ import annotations

from PySide6.QtCore import QSettings

from app import ui_constants as ui
from app.url_settings import UrlSettingsConfig, UrlSettingsDialog


def _default_settings() -> QSettings:
    return QSettings(ui.QSETTINGS_ORGANIZATION, ui.QSETTINGS_APPLICATION)


class TestUrlSettingsConfig:
    def test_defaults(self) -> None:
        cfg = UrlSettingsConfig.defaults()
        assert cfg.nexus_url_prefix == "https://www.nexusmods.com/skyrimspecialedition/mods/"
        assert cfg.search_engine_url == "https://www.bing.com/search"
        assert cfg.search_prefix == "skyrim "

    def test_load_empty_returns_defaults(self) -> None:
        settings = _default_settings()
        cfg = UrlSettingsConfig.load(settings)
        assert cfg == UrlSettingsConfig.defaults()

    def test_save_and_load_roundtrip(self) -> None:
        settings = _default_settings()
        custom = UrlSettingsConfig(
            nexus_url_prefix="https://www.nexusmods.com/skyrim/mods/",
            search_engine_url="https://www.google.com/search?q=",
            search_prefix="skyrimse ",
        )
        custom.save(settings)

        loaded = UrlSettingsConfig.load(settings)
        assert loaded == custom


class TestUrlSettingsDialog:
    def test_resulting_config(self, qapp) -> None:
        dialog = UrlSettingsDialog(UrlSettingsConfig.defaults())
        try:
            cfg = dialog.resulting_config()
            assert cfg == UrlSettingsConfig.defaults()

            dialog._nexus_prefix_edit.setText("https://example.com/mods/")  # noqa: SLF001
            dialog._search_prefix_edit.setText("skyrimse ")  # noqa: SLF001
            cfg = dialog.resulting_config()
            assert cfg.nexus_url_prefix == "https://example.com/mods/"
            assert cfg.search_prefix == "skyrimse "
        finally:
            dialog.close()

    def test_reset_to_defaults(self, qapp) -> None:
        dialog = UrlSettingsDialog(
            UrlSettingsConfig(
                nexus_url_prefix="https://x/",
                search_engine_url="https://y/?q=",
                search_prefix="z ",
            )
        )
        try:
            dialog._reset_to_defaults()  # noqa: SLF001
            assert dialog.resulting_config() == UrlSettingsConfig.defaults()
        finally:
            dialog.close()
