"""排序字段下拉框专用控件。

BugFix3（2026-08-04）：QComboBox 原生弹窗在鼠标按下后若发生微量位移，
release 时可能被 Qt 判定为"按下/释放位置不一致"而不再发出 ``activated``，
表现为"点一次不生效、需要点两次"。

修复方案：监听弹窗视图的 ``pressed`` 信号，鼠标**按下即选中**（不依赖
release）；``activated`` 仅保留给键盘路径（无 pressed），并用去重标志避免
鼠标路径按下 + 释放重复执行。

后续验收修复：
- 按下即排序后必须立即同步控件显示（控制器侧），否则快速滑动时出现
  "排序已生效但下拉框显示未变"的不一致；
- release 时 Qt 会把 ``currentIndex`` 覆盖为释放位置项，控件在去重分支里
  恢复为"按下即选中"的项，保证显示与已应用排序一致；
- 下拉框新增"升序/降序"方向项（资源管理器式），按下/键盘选择均通过
  ``directionRequested`` 信号委托，选择后下拉框显示恢复为当前字段项。

语义约定：
- 鼠标：以按下位置为准，立即应用选择（字段或方向）；
- 键盘（弹窗内 Enter / Space）：仍走 activated，正常应用；
- 程序化 ``setCurrentIndex``（如排序控件同步）不触发任何用户选择信号。
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Signal
from PySide6.QtWidgets import QComboBox

from app.file_list_model import SORT_DIRECTION_ASC, SORT_DIRECTION_DESC


class PressSelectComboBox(QComboBox):
    """鼠标按下即选中、释放去重的 QComboBox。"""

    userSelected = Signal(int)
    directionRequested = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mouse_press_applied = False
        self._pressed_index: int | None = None
        self._display_index_after_apply: int | None = None
        self.view().pressed.connect(self._on_popup_item_pressed)
        self.activated.connect(self._on_activated)

    def _on_popup_item_pressed(self, index: QModelIndex) -> None:
        """弹出列表鼠标按下：立即应用选择（不依赖 release）。"""
        if not index.isValid() or self._mouse_press_applied:
            return
        data = self.itemData(index.row())
        if data is None:
            return  # 分隔符等不可选项
        self._mouse_press_applied = True
        self._pressed_index = index.row()
        if data in (SORT_DIRECTION_ASC, SORT_DIRECTION_DESC):
            self.directionRequested.emit(data == SORT_DIRECTION_ASC)
            # 控制器已把显示同步回当前字段项，记录以便 release 覆盖后恢复
            self._display_index_after_apply = self.currentIndex()
        else:
            self.userSelected.emit(index.row())

    def _on_activated(self, index: int) -> None:
        """鼠标 release 去重 + 显示恢复；键盘路径直接放行。"""
        if self._mouse_press_applied:
            # 鼠标路径：release 时 Qt 会把 currentIndex 覆盖为释放位置项，
            # 恢复为"按下即选中"的项，保证显示与已应用排序一致
            self._mouse_press_applied = False
            target = (
                self._display_index_after_apply
                if self._display_index_after_apply is not None
                else self._pressed_index
            )
            self._set_index_quietly(target)
            return
        data = self.itemData(index)
        if data in (SORT_DIRECTION_ASC, SORT_DIRECTION_DESC):
            self.directionRequested.emit(data == SORT_DIRECTION_ASC)
            return
        self.userSelected.emit(index)

    def _set_index_quietly(self, row: int | None) -> None:
        """程序化设置显示项（blockSignals 防 currentIndexChanged 干扰）。"""
        if row is None or row < 0 or row >= self.count():
            return
        if self.currentIndex() != row:
            self.blockSignals(True)
            self.setCurrentIndex(row)
            self.blockSignals(False)

    def hidePopup(self) -> None:
        """弹窗关闭时复位去重标志，避免残留状态吞掉下一次键盘选择。"""
        self._mouse_press_applied = False
        self._pressed_index = None
        self._display_index_after_apply = None
        super().hidePopup()
