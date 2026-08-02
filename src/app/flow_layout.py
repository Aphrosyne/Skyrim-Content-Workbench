"""FlowLayout：自动换行布局（标签按钮流式排列）。

基于 Qt 官方 FlowLayout 示例（BSD-3-Clause，Qt Company）的简化实现：
https://doc.qt.io/qt-6/qtwidgets-layouts-flowlayout-example.html
仅保留本项目所需能力：addWidget / 清空重建 / heightForWidth 自适应换行。

用于元数据面板的「最近使用标签」与「已有标签」区域——标签按钮按行自动换行，
避免 QListWidget 流式模式下分组头与标签混排、空列表显示无意义矩形的问题
（UI合理性8 修复，2026-08-02）。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget


class FlowLayout(QLayout):
    """自动换行布局：子项超出宽度时换行，支持高度自适应。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        margin: int = 0,
        h_spacing: int = 6,
        v_spacing: int = 6,
    ) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 (Qt 命名)
        self._items.append(item)

    def count(self) -> int:  # noqa: N802 (Qt 命名)
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 (Qt 命名)
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 (Qt 命名)
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802 (Qt 命名)
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt 命名)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt 命名)
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 (Qt 命名)
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt 命名)
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 (Qt 命名)
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def clear(self) -> None:
        """清空所有子项并删除对应 widget（供重建列表使用）。"""
        while self._items:
            item = self.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        """执行布局；test_only=True 时只计算所需高度，不移动子项。"""
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x = effective.x()
        y = effective.y()
        line_height = 0
        total_height = effective.height()
        for item in self._items:
            widget = item.widget()
            if widget is None:
                continue
            hint = widget.sizeHint()
            next_x = x + hint.width() + self._h_spacing
            if next_x - self._h_spacing > effective.right() + 1 and line_height > 0:
                x = effective.x()
                y = y + line_height + self._v_spacing
                next_x = x + hint.width() + self._h_spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        total_height = y + line_height - rect.y()
        return total_height
