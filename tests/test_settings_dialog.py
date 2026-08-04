"""统一设置对话框测试（设计合理性1 + 快捷键配置，2026-08-04）。"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence

from app import ui_constants as ui
from app.feature_toggle_config import FeatureToggleConfig
from app.settings_dialog import SettingsDialog
from app.shortcut_config import ShortcutConfig


class TestSettingsDialog:
    def test_tabs(self, qapp) -> None:
        dialog = SettingsDialog(FeatureToggleConfig.defaults(), ShortcutConfig.defaults())
        try:
            assert dialog._tabs.count() == 2  # noqa: SLF001
            assert dialog._tabs.tabText(0) == ui.SETTINGS_TAB_FEATURES
            assert dialog._tabs.tabText(1) == ui.SETTINGS_TAB_SHORTCUTS
        finally:
            dialog.close()

    def test_resulting_defaults(self, qapp) -> None:
        dialog = SettingsDialog(FeatureToggleConfig.defaults(), ShortcutConfig.defaults())
        try:
            assert dialog.resulting_feature_config() == FeatureToggleConfig.defaults()
            assert dialog.resulting_shortcut_config() == ShortcutConfig.defaults()
        finally:
            dialog.close()

    def test_feature_toggle_changes_result(self, qapp) -> None:
        dialog = SettingsDialog(FeatureToggleConfig.defaults(), ShortcutConfig.defaults())
        try:
            dialog.feature_checkbox("browser_search").setChecked(False)
            dialog.feature_checkbox("strip").setChecked(False)
            result = dialog.resulting_feature_config()
            assert not result.is_enabled("browser_search")
            assert not result.is_enabled("strip")
            assert result.is_enabled("open")
        finally:
            dialog.close()

    def test_shortcut_edit_changes_result(self, qapp) -> None:
        dialog = SettingsDialog(FeatureToggleConfig.defaults(), ShortcutConfig.defaults())
        try:
            dialog.shortcut_edit("rename").setKeySequence(QKeySequence("Ctrl+E"))
            dialog.shortcut_edit("paste").setKeySequence(QKeySequence(""))
            result = dialog.resulting_shortcut_config()
            assert result.key_for("rename") == "Ctrl+E"
            assert result.key_for("paste") == ""
        finally:
            dialog.close()

    def test_reset_features(self, qapp) -> None:
        dialog = SettingsDialog(FeatureToggleConfig.defaults(), ShortcutConfig.defaults())
        try:
            dialog.feature_checkbox("open").setChecked(False)
            dialog._reset_features()  # noqa: SLF001
            assert dialog.resulting_feature_config() == FeatureToggleConfig.defaults()
        finally:
            dialog.close()

    def test_reset_shortcuts(self, qapp) -> None:
        dialog = SettingsDialog(FeatureToggleConfig.defaults(), ShortcutConfig.defaults())
        try:
            dialog.shortcut_edit("rename").setKeySequence(QKeySequence("Ctrl+E"))
            dialog._reset_shortcuts()  # noqa: SLF001
            assert dialog.resulting_shortcut_config() == ShortcutConfig.defaults()
        finally:
            dialog.close()

    def test_conflict_highlight_and_clear(self, qapp) -> None:
        dialog = SettingsDialog(FeatureToggleConfig.defaults(), ShortcutConfig.defaults())
        try:
            dialog.shortcut_edit("rename").setKeySequence(QKeySequence("Ctrl+E"))
            dialog.shortcut_edit("delete").setKeySequence(QKeySequence("Ctrl+E"))
            tooltip = dialog.shortcut_edit("rename").toolTip()
            assert ui.SETTINGS_SHORTCUTS_CONFLICT_TOOLTIP.format(others="删除") == tooltip
            assert "background-color" in dialog.shortcut_edit("rename").styleSheet()

            dialog.shortcut_edit("delete").setKeySequence(QKeySequence("Delete"))
            assert dialog.shortcut_edit("rename").toolTip() == ""
            assert dialog.shortcut_edit("rename").styleSheet() == ""
        finally:
            dialog.close()
