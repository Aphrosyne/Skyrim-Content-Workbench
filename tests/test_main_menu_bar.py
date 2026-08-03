"""MainMenuBar 视图单元测试（UI合理性3，2026-08-03）。

覆盖：菜单/动作构建、动作触发信号、视图动作 checkable 互斥、
工具菜单可用性切换、快捷键占位项禁用。
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app import ui_constants as ui  # noqa: E402
from app.main_menu_bar import MainMenuBar  # noqa: E402


def _capture_signals(menu_bar: MainMenuBar) -> dict[str, list]:
    """挂接信号捕获列表。"""
    captured = {
        "view": [],
        "reset": [],
        "tag": [],
        "history": [],
    }
    menu_bar.switch_view_requested.connect(captured["view"].append)
    menu_bar.layout_reset_requested.connect(lambda: captured["reset"].append(True))
    menu_bar.tag_manager_requested.connect(lambda: captured["tag"].append(True))
    menu_bar.operation_history_requested.connect(lambda: captured["history"].append(True))
    return captured


def test_menu_structure(qapp) -> None:
    menu_bar = MainMenuBar()
    titles = [action.text() for action in menu_bar.actions()]
    assert ui.MENU_BAR_VIEW in titles
    assert ui.MENU_BAR_TOOLS in titles


def test_view_actions_emit_switch_request(qapp) -> None:
    menu_bar = MainMenuBar()
    captured = _capture_signals(menu_bar)

    menu_bar.view_list_action().trigger()
    menu_bar.view_card_action().trigger()

    assert captured["view"] == ["list", "card"]


def test_view_actions_exclusive_checkable(qapp) -> None:
    menu_bar = MainMenuBar()
    menu_bar.view_list_action().setChecked(True)
    assert menu_bar.view_list_action().isChecked()

    menu_bar.view_card_action().setChecked(True)

    assert menu_bar.view_card_action().isChecked()
    assert not menu_bar.view_list_action().isChecked()


def test_set_view_syncs_checked_state(qapp) -> None:
    menu_bar = MainMenuBar()

    menu_bar.set_view("card")
    assert menu_bar.view_card_action().isChecked()
    assert not menu_bar.view_list_action().isChecked()

    menu_bar.set_view("list")
    assert menu_bar.view_list_action().isChecked()
    assert not menu_bar.view_card_action().isChecked()


def test_reset_layout_action_emits_signal(qapp) -> None:
    menu_bar = MainMenuBar()
    captured = _capture_signals(menu_bar)

    menu_bar.reset_layout_action().trigger()

    assert captured["reset"] == [True]


def test_shortcuts_action_disabled_placeholder(qapp) -> None:
    menu_bar = MainMenuBar()
    assert not menu_bar.shortcuts_action().isEnabled()
    assert ui.MENU_VIEW_SHORTCUTS_TODO in menu_bar.shortcuts_action().toolTip()


def test_tools_actions_emit_signals_and_toggle_visibility(qapp) -> None:
    menu_bar = MainMenuBar()
    captured = _capture_signals(menu_bar)

    menu_bar.tag_manager_action().trigger()
    menu_bar.operation_history_action().trigger()
    assert captured["tag"] == [True]
    assert captured["history"] == [True]

    menu_bar.set_tag_manager_visible(False)
    menu_bar.set_operation_history_visible(False)
    assert not menu_bar.tag_manager_action().isVisible()
    assert not menu_bar.operation_history_action().isVisible()

    menu_bar.set_tag_manager_visible(True)
    assert menu_bar.tag_manager_action().isVisible()
