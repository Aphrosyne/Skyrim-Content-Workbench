"""输入控件右键菜单中文化测试（2026-08-04 验收反馈）。"""

from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QMenu, QPlainTextEdit, QWidget

from app import ui_constants as ui
from app.chinese_input_menu import ChineseInputContextMenuFilter


def _action_texts(menu: QMenu) -> list[str]:
    return [a.text() for a in menu.actions()]


class TestBuildMenu:
    def test_line_edit_menu_chinese_labels_and_states(self, qapp) -> None:
        """QLineEdit 有选中文本 + 剪贴板有内容 → 中文菜单且各项可用。"""
        QApplication.clipboard().setText("clip")
        edit = QLineEdit("hello world")
        edit.setSelection(0, 5)
        filter_ = ChineseInputContextMenuFilter()

        menu = filter_._build_menu(edit)  # noqa: SLF001

        assert _action_texts(menu) == [
            ui.INPUT_MENU_COPY,
            ui.INPUT_MENU_CUT,
            ui.INPUT_MENU_PASTE,
            "",
            ui.INPUT_MENU_SELECT_ALL,
        ]
        actions = menu.actions()
        assert actions[0].isEnabled()  # 复制
        assert actions[1].isEnabled()  # 剪切
        assert actions[2].isEnabled()  # 粘贴
        assert actions[4].isEnabled()  # 全选

    def test_readonly_disables_cut_and_paste(self, qapp) -> None:
        """只读控件 → 剪切/粘贴禁用。"""
        QApplication.clipboard().setText("clip")
        edit = QLineEdit("text")
        edit.setReadOnly(True)
        edit.setSelection(0, 2)
        filter_ = ChineseInputContextMenuFilter()

        menu = filter_._build_menu(edit)  # noqa: SLF001

        actions = menu.actions()
        assert actions[0].isEnabled()  # 复制仍可用
        assert not actions[1].isEnabled()  # 剪切禁用
        assert not actions[2].isEnabled()  # 粘贴禁用

    def test_no_selection_disables_copy_cut(self, qapp) -> None:
        """无选中文本 → 复制/剪切禁用。"""
        QApplication.clipboard().clear()
        edit = QLineEdit("text")
        filter_ = ChineseInputContextMenuFilter()

        menu = filter_._build_menu(edit)  # noqa: SLF001

        actions = menu.actions()
        assert not actions[0].isEnabled()
        assert not actions[1].isEnabled()
        assert not actions[2].isEnabled()  # 剪贴板为空 → 粘贴禁用

    def test_plain_text_edit_supported(self, qapp) -> None:
        """QPlainTextEdit 同样命中（备注等多行输入）。"""
        QApplication.clipboard().setText("clip")
        edit = QPlainTextEdit("multi\nline")
        filter_ = ChineseInputContextMenuFilter()

        menu = filter_._build_menu(edit)  # noqa: SLF001

        assert _action_texts(menu)[0] == ui.INPUT_MENU_COPY
        assert menu.actions()[4].isEnabled()  # 全选


class TestEventFilter:
    def test_consumes_context_menu_on_line_edit(self, qapp, monkeypatch) -> None:
        """QLineEdit 右键事件被消费，且弹出中文菜单。"""
        edit = QLineEdit("text")
        filter_ = ChineseInputContextMenuFilter()
        shown: list[QMenu] = []
        monkeypatch.setattr(filter_, "_exec_menu", lambda menu, pos: shown.append(menu) or None)

        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(1, 1), QPoint(10, 10))
        consumed = filter_.eventFilter(edit, event)

        assert consumed is True
        assert len(shown) == 1
        assert _action_texts(shown[0])[0] == ui.INPUT_MENU_COPY

    def test_passthrough_for_non_text_widget(self, qapp) -> None:
        """非文本控件 → 不拦截（返回 False）。"""
        widget = QWidget()
        filter_ = ChineseInputContextMenuFilter()

        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(1, 1), QPoint(10, 10))
        consumed = filter_.eventFilter(widget, event)

        assert consumed is False
