"""输入控件右键菜单中文化（2026-08-04 验收反馈）。

Qt 内置输入框右键菜单为英文（复制/粘贴/剪切/全选），不符合项目 UI 全中文
约定（文本集中在 ui_constants.py）。通过应用级事件过滤器拦截
``QEvent.ContextMenu``，对文本输入类控件弹出中文菜单并消费原事件。

覆盖控件：QLineEdit / QTextEdit / QPlainTextEdit（含各对话框搜索框、
元数据面板来源 URL / 备注、可编辑组合框内部行编辑等）。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QTextEdit,
)

from app import ui_constants as ui

_TEXT_WIDGET_TYPES = (QLineEdit, QTextEdit, QPlainTextEdit)


class ChineseInputContextMenuFilter(QObject):
    """拦截文本输入控件右键事件并显示中文菜单。"""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """ContextMenu 事件落在文本输入控件上 → 弹中文菜单并消费；否则放行。"""
        if event.type() == QEvent.Type.ContextMenu and isinstance(obj, _TEXT_WIDGET_TYPES):
            menu = self._build_menu(obj)
            if not menu.isEmpty():
                self._exec_menu(menu, event.globalPos())
            return True
        return super().eventFilter(obj, event)

    @staticmethod
    def _exec_menu(menu: QMenu, global_pos) -> None:
        """弹出菜单（独立方法便于测试替换，避免模态阻塞）。"""
        menu.exec(global_pos)

    def _build_menu(self, widget) -> QMenu:
        """按控件状态构建中文右键菜单（供测试直接调用）。

        启用规则：
        - 复制：有选中文本
        - 剪切：有选中文本且可编辑
        - 粘贴：可编辑且剪贴板有文本
        - 全选：有文本
        """
        menu = QMenu(widget)
        if isinstance(widget, QLineEdit):
            has_text = bool(widget.text())
        else:
            has_text = bool(widget.toPlainText())
        if isinstance(widget, QPlainTextEdit):
            has_selection = widget.textCursor().hasSelection()
        else:
            has_selection = widget.hasSelectedText()
        can_edit = not widget.isReadOnly()

        copy_action = menu.addAction(ui.INPUT_MENU_COPY)
        copy_action.setEnabled(has_selection)
        copy_action.triggered.connect(lambda checked=False: widget.copy())

        cut_action = menu.addAction(ui.INPUT_MENU_CUT)
        cut_action.setEnabled(has_selection and can_edit)
        cut_action.triggered.connect(lambda checked=False: widget.cut())

        paste_action = menu.addAction(ui.INPUT_MENU_PASTE)
        clipboard = QApplication.clipboard()
        can_paste = can_edit and clipboard is not None and bool(clipboard.text())
        paste_action.setEnabled(can_paste)
        paste_action.triggered.connect(lambda checked=False: widget.paste())

        menu.addSeparator()
        select_all_action = menu.addAction(ui.INPUT_MENU_SELECT_ALL)
        select_all_action.setEnabled(has_text)
        select_all_action.triggered.connect(lambda checked=False: widget.selectAll())
        return menu
