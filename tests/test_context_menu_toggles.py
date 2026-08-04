"""右键功能开关测试（设计合理性1，2026-08-04）。

直接构造 ContextMenuBuilder（轻量 fakes），验证关闭某项后对应菜单项
（含最近移动目标/最近标签子菜单）不再出现。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QMenu

from app import ui_constants as ui
from app.context_menu_builder import ContextMenuBuilder
from app.feature_toggle_config import FeatureToggleConfig
from domain.models import FileEntry


class _FakeClipboard:
    def get(self):
        return None


class _FakeRecent:
    def __init__(self, recent: list[str]) -> None:
        self._recent = list(recent)

    def list_recent(self) -> list[str]:
        return list(self._recent)


class _FakeHost:
    """缺失的 handler 属性返回 no-op 可调用对象（build 阶段不调用 handler）。"""

    def __getattr__(self, name: str):
        return lambda *args, **kwargs: None


def _make_entry(name: str, is_dir: bool = False, content_unit=None) -> FileEntry:
    return FileEntry(
        name=name,
        path=f"C:\\mods\\{name}",
        is_dir=is_dir,
        modified_at="2026-08-04T00:00:00Z",
        content_unit=content_unit,
    )


def _make_builder(feature_config: FeatureToggleConfig | None = None) -> ContextMenuBuilder:
    return ContextMenuBuilder(
        content_unit_creation_service=object(),
        tag_service=object(),
        assembly_service=None,
        assembly_panel=None,
        file_operation_service=object(),
        clipboard_service=_FakeClipboard(),
        strip_service=object(),
        content_view=None,
        card_view=None,
        content_list_model=None,
        card_list_model=None,
        tree_view=None,
        tree_model=None,
        current_view_index=lambda: 0,
        current_displayed_dir=lambda: None,
        dialog_parent=None,
        host=_FakeHost(),
        archive_settings=None,
        feature_toggle_config=feature_config,
    )


def _labels(actions: list[tuple[str, object, bool]]) -> set[str]:
    return {label for label, _, _ in actions}


class TestBuildContentActionsToggles:
    def test_default_all_enabled(self, qapp) -> None:
        builder = _make_builder()
        labels = _labels(builder.build_content_actions([_make_entry("a.zip")]))
        assert ui.MENU_OPEN in labels
        assert ui.MENU_CREATE_MOD_GROUP in labels
        assert ui.MENU_MARK_CONTENT_UNIT in labels
        assert ui.MENU_BROWSER_SEARCH in labels
        assert ui.MENU_OPEN_IN_EXPLORER in labels
        assert ui.CONTEXT_MENU_COPY_PATH in labels

    def test_disabled_features_hidden(self, qapp) -> None:
        config = FeatureToggleConfig.defaults()
        config.toggle("browser_search", False)
        config.toggle("copy_path", False)
        config.toggle("open_in_explorer", False)
        config.toggle("delete", False)
        config.toggle("move_to", False)
        builder = _make_builder(config)
        labels = _labels(builder.build_content_actions([_make_entry("a.zip")]))
        assert ui.MENU_BROWSER_SEARCH not in labels
        assert ui.CONTEXT_MENU_COPY_PATH not in labels
        assert ui.MENU_OPEN_IN_EXPLORER not in labels
        assert ui.MENU_DELETE not in labels
        assert ui.MENU_MOVE_TO not in labels
        assert ui.MENU_OPEN in labels

    def test_mark_content_unit_disabled_hides_mark_items(self, qapp) -> None:
        config = FeatureToggleConfig.defaults()
        config.toggle("mark_content_unit", False)
        builder = _make_builder(config)

        labels = _labels(builder.build_content_actions([_make_entry("a.zip")]))
        assert ui.MENU_MARK_CONTENT_UNIT not in labels

        labels = _labels(
            builder.build_content_actions([_make_entry("a.zip"), _make_entry("b.zip")])
        )
        assert ui.MENU_BATCH_MARK_CONTENT_UNIT not in labels
        assert ui.MENU_BATCH_UNMARK_CONTENT_UNIT not in labels

    def test_create_mod_group_disabled(self, qapp) -> None:
        config = FeatureToggleConfig.defaults()
        config.toggle("create_mod_group", False)
        builder = _make_builder(config)
        labels = _labels(builder.build_content_actions([_make_entry("a.zip")]))
        assert ui.MENU_CREATE_MOD_GROUP not in labels

    def test_strip_toggle(self, qapp) -> None:
        folder = _make_entry("folder", is_dir=True)
        builder = _make_builder()
        assert ui.MENU_STRIP_FOLDER in _labels(builder.build_content_actions([folder]))

        config = FeatureToggleConfig.defaults()
        config.toggle("strip", False)
        builder = _make_builder(config)
        assert ui.MENU_STRIP_FOLDER not in _labels(builder.build_content_actions([folder]))


class TestRecentSubmenuToggles:
    def test_recent_move_submenu_hidden_when_disabled(self, qapp) -> None:
        config = FeatureToggleConfig.defaults()
        config.toggle("move_to_recent", False)
        builder = _make_builder(config)
        menu = QMenu()
        builder.insert_recent_move_submenu(menu, [Path("C:\\mods\\a.zip")])
        assert menu.actions() == []

    def test_recent_move_submenu_shown_when_enabled(self, qapp) -> None:
        builder = _make_builder()
        builder._host = SimpleNamespace(  # noqa: SLF001
            _recent_move_targets=_FakeRecent(["C:\\mods\\Stash"]),
            _service=SimpleNamespace(list_roots=lambda: []),
        )
        menu = QMenu()
        menu.addAction(ui.MENU_MOVE_TO)
        builder.insert_recent_move_submenu(menu, [Path("C:\\mods\\a.zip")])
        titles = [action.text() for action in menu.actions()]
        assert ui.MENU_MOVE_TO_RECENT in titles

    def test_recent_tag_submenu_hidden_when_disabled(self, qapp) -> None:
        config = FeatureToggleConfig.defaults()
        config.toggle("recent_tag", False)
        builder = _make_builder(config)
        menu = QMenu()
        # host 无 _tag_service/_recent_tags，若未提前返回会 AttributeError
        builder.insert_recent_tag_submenu(menu, "unit-1")
        assert menu.actions() == []
