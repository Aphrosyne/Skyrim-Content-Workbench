"""快捷键配置测试（2026-08-04，设计合理性1 附带）。"""

from __future__ import annotations

from app.shortcut_config import SHORTCUT_IDS, ShortcutConfig, shortcut_definitions


class TestShortcutConfig:
    def test_defaults(self) -> None:
        cfg = ShortcutConfig.defaults()
        assert cfg.key_for("rename") == "F2"
        assert cfg.key_for("select_all") == "Ctrl+A"
        assert len(cfg.keys) == len(SHORTCUT_IDS)

    def test_load_empty_returns_defaults(self, settings_ini) -> None:
        cfg = ShortcutConfig.load(settings_ini)
        assert cfg == ShortcutConfig.defaults()

    def test_save_and_load_roundtrip(self, settings_ini) -> None:
        settings = settings_ini
        custom = ShortcutConfig.defaults()
        custom.set_key("rename", "Ctrl+E")
        custom.set_key("paste", "")  # 禁用
        custom.save(settings)

        loaded = ShortcutConfig.load(settings)
        assert loaded.key_for("rename") == "Ctrl+E"
        assert loaded.key_for("paste") == ""

    def test_invalid_value_falls_back_to_default(self, settings_ini) -> None:
        settings = settings_ini
        settings.setValue("shortcut/rename", "NotAKey")
        cfg = ShortcutConfig.load(settings)
        assert cfg.key_for("rename") == "F2"

    def test_set_key_normalizes(self) -> None:
        cfg = ShortcutConfig.defaults()
        cfg.set_key("undo", "Ctrl+Z")
        assert cfg.key_for("undo") == "Ctrl+Z"
        cfg.set_key("undo", "")
        assert cfg.key_for("undo") == ""

    def test_reset_defaults(self) -> None:
        cfg = ShortcutConfig.defaults()
        cfg.set_key("rename", "Ctrl+E")
        cfg.set_key("delete", "")
        cfg.reset_defaults()
        assert cfg == ShortcutConfig.defaults()

    def test_definitions_complete(self) -> None:
        definitions = shortcut_definitions()
        assert [d.shortcut_id for d in definitions] == list(SHORTCUT_IDS)
        assert all(d.label and d.default_key and d.scope for d in definitions)
