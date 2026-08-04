"""PressSelectComboBox 单元测试（BugFix3，2026-08-04）。

覆盖"鼠标按下即选中 + 释放去重 + 显示恢复 + hidePopup 复位"状态机：
- 鼠标路径：press 触发一次 userSelected，后续 release activated 被去重；
- 键盘路径：无 press 时 activated 正常放行；
- 方向项：按下/键盘选择触发 directionRequested，显示恢复为当前字段项；
- 程序化 setCurrentIndex 不触发 userSelected（供排序控件同步使用）。
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QComboBox  # noqa: E402

from app.file_list_model import (  # noqa: E402
    SORT_DIRECTION_ASC,
    SORT_DIRECTION_DESC,
    SORT_MODIFIED,
    SORT_NAME,
    SORT_SIZE,
    SORT_TYPE,
)
from app.sort_combo_box import PressSelectComboBox  # noqa: E402


def _make_combo(qapp) -> PressSelectComboBox:
    combo = PressSelectComboBox()
    combo.addItem("名称", SORT_NAME)
    combo.addItem("类型", SORT_TYPE)
    combo.addItem("大小", SORT_SIZE)
    combo.addItem("时间", SORT_MODIFIED)
    combo.insertSeparator(combo.count())
    combo.addItem("升序 ▲", SORT_DIRECTION_ASC)
    combo.addItem("降序 ▼", SORT_DIRECTION_DESC)
    return combo


def test_press_emits_user_selected_once(qapp) -> None:
    combo = _make_combo(qapp)
    received: list[int] = []
    combo.userSelected.connect(received.append)

    combo.view().pressed.emit(combo.model().index(1, 0))

    assert received == [1]


def test_press_then_activated_is_deduped(qapp) -> None:
    combo = _make_combo(qapp)
    received: list[int] = []
    combo.userSelected.connect(received.append)

    combo.view().pressed.emit(combo.model().index(1, 0))
    combo.activated.emit(2)  # release 触发（鼠标路径，应被去重）

    assert received == [1]


def test_activated_without_press_passes_through(qapp) -> None:
    """键盘路径（无鼠标 press）：activated 正常转发。"""
    combo = _make_combo(qapp)
    received: list[int] = []
    combo.userSelected.connect(received.append)

    combo.activated.emit(2)

    assert received == [2]


def test_hide_popup_resets_press_flag(qapp) -> None:
    """press 后 release 被吞（无 activated）：hidePopup 复位标志。"""
    combo = _make_combo(qapp)
    received: list[int] = []
    combo.userSelected.connect(received.append)

    combo.view().pressed.emit(combo.model().index(1, 0))
    combo.hidePopup()
    combo.activated.emit(3)  # 下一次键盘选择不应被残留标志吞掉

    assert received == [1, 3]


def test_press_direction_item_emits_direction_requested(qapp) -> None:
    combo = _make_combo(qapp)
    received: list[bool] = []
    combo.directionRequested.connect(received.append)
    desc_row = combo.count() - 1

    combo.view().pressed.emit(combo.model().index(desc_row, 0))

    assert received == [False]


def test_press_direction_then_release_restores_field_display(qapp) -> None:
    """按下降序项后 release 覆盖 currentIndex：显示恢复为当前字段项。"""
    combo = _make_combo(qapp)
    received: list[bool] = []
    combo.directionRequested.connect(received.append)
    field_row = combo.currentIndex()  # 当前字段项（默认第 0 项）
    desc_row = combo.count() - 1

    combo.view().pressed.emit(combo.model().index(desc_row, 0))
    # release：Qt 把 currentIndex 覆盖为方向项并触发 activated（鼠标路径去重）
    combo.activated.emit(desc_row)

    assert received == [False]
    assert combo.currentIndex() == field_row


def test_keyboard_direction_activated_passes_through(qapp) -> None:
    """键盘路径（无 press）：方向项 activated 正常触发 directionRequested。"""
    combo = _make_combo(qapp)
    received: list[bool] = []
    combo.directionRequested.connect(received.append)
    asc_row = combo.count() - 2

    combo.activated.emit(asc_row)

    assert received == [True]


def test_press_field_then_release_other_item_restores_pressed_display(qapp) -> None:
    """快速滑动：按下字段 B 释放到字段 C，显示恢复为按下的 B（与排序一致）。"""
    combo = _make_combo(qapp)
    received: list[int] = []
    combo.userSelected.connect(received.append)

    combo.view().pressed.emit(combo.model().index(1, 0))  # 按下"类型"
    combo.activated.emit(2)  # 释放到"大小"（Qt 会覆盖 currentIndex）

    assert received == [1]
    assert combo.currentIndex() == 1


def test_programmatic_set_current_index_no_signal(qapp) -> None:
    combo = _make_combo(qapp)
    received: list[int] = []
    combo.userSelected.connect(received.append)

    combo.setCurrentIndex(2)

    assert received == []


def test_invalid_press_index_ignored(qapp) -> None:
    combo = _make_combo(qapp)
    received: list[int] = []
    combo.userSelected.connect(received.append)

    combo.view().pressed.emit(combo.model().index(99, 0))  # 越界无效索引

    assert received == []


def test_subclass_of_qcombobox(qapp) -> None:
    assert isinstance(_make_combo(qapp), QComboBox)
