"""内容列表专用视图类（MainWindow 第二轮拆分，TD-M21 阶段 1）。

从 ``app.main_window`` 迁出的两个私有视图类：
- ``_RubberBandTableView``：列表视图，支持空白区域拖动框选（决策 3A）。
- ``_DragDropListView``：卡片视图，复用同一套内部拖拽到文件夹逻辑
  （UX 重构 Phase 1 Task 4）。

``app.main_window`` 以原私有名 re-export，保持既有测试导入路径不变。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QListView, QRubberBand, QTableView, QWidget


class _RubberBandTableView(QTableView):
    """支持空白区域拖动框选的 QTableView。

    Stage 5 Task 2 验收修复（决策 3A）：QTableView 不支持 setSelectionRectVisible
    （仅 QListView 有），通过自定义 mousePress/Drag/Release + QRubberBand 实现
    与 Windows Explorer 一致的空白区域拖动框选行为。

    交互规则：
    - 在空白区域（非任何 item 上）按下左键 → 启动 rubber band
    - 拖动 → 更新 rubber band 矩形，选中范围内所有行（替换选择）
    - 松开 → 隐藏 rubber band
    - 在 item 上按下 → 交给父类处理（保留单击/Ctrl/Shift 选择行为）
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rubber_band: QRubberBand | None = None
        self._origin = QPoint()
        self._drag_selecting = False
        # UX 重构 Phase 1 Task 4：内部拖拽到文件夹的回调
        # 签名：(target_folder: Path, src_paths: list[Path]) -> None
        self.on_drop_to_folder: Callable[[Path, list[Path]], None] | None = None

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.pos())
            if not index.isValid():
                # 空白区域：启动 rubber band 框选
                self._origin = event.pos()
                self._drag_selecting = True
                if self._rubber_band is None:
                    # UX 重构 Phase 1 Task 2：rubber band 父对象改为 viewport()，
                    # 使其几何坐标与 event.pos() / rowAt() 一致（原父对象为 self，
                    # 受 header 高度偏移影响，框选框与鼠标指针存在垂直错位）。
                    self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
                self._rubber_band.setGeometry(QRect(self._origin, QSize()))
                self._rubber_band.show()
                # 清空当前选择（与 Explorer 行为一致：空白拖动开始新选择）
                self.selectionModel().clear()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self._drag_selecting and self._rubber_band is not None:
            rect = QRect(self._origin, event.pos()).normalized()
            self._rubber_band.setGeometry(rect)
            self._select_rows_in_rect(rect)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self._drag_selecting:
            self._drag_selecting = False
            if self._rubber_band is not None:
                self._rubber_band.hide()
            return
        super().mouseReleaseEvent(event)

    def _select_rows_in_rect(self, rect: QRect) -> None:
        """根据 rubber band 矩形选中相交的行（替换选择）。"""
        from PySide6.QtCore import QItemSelection

        # 计算矩形覆盖的行范围
        top_row = self.rowAt(rect.top())
        bottom_row = self.rowAt(rect.bottom())
        last_row = self.model().rowCount() - 1 if self.model() else -1
        # 修复（操作合理性4，2026-08-03）：矩形边缘落在行区外时扩展到首末行。
        # 此前仅处理超出视口的情况，导致在末行下方空白区起框（从下往上拉）
        # 时 bottom_row=-1 直接 return、选不中。
        if top_row == -1 and rect.top() <= 0:
            top_row = 0
        if bottom_row == -1 and rect.bottom() >= 0:
            # 下边缘在首行之下（含视口内空白区与视口外）→ 扩展到末行；
            # 若下边缘在视口上方（rect.bottom() < 0）则保持 -1，无可选。
            bottom_row = last_row
        if top_row == -1 or bottom_row == -1 or top_row > bottom_row:
            return
        # 选中范围内的所有行（ClearAndSelect 替换当前选择）
        top_index = self.model().index(top_row, 0)
        bottom_index = self.model().index(bottom_row, 0)
        sel = QItemSelection(top_index, bottom_index)
        self.selectionModel().select(
            sel,
            QItemSelectionModel.SelectionFlag.ClearAndSelect
            | QItemSelectionModel.SelectionFlag.Rows,
        )

    # --- UX 重构 Phase 1 Task 4：内部拖拽到文件夹 ---

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.source() is self and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.source() is self and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.source() is not self or not event.mimeData().hasUrls():
            event.ignore()
            return
        index = self.indexAt(event.pos())
        if not index.isValid():
            event.ignore()
            return
        entry = self.model().data(index, Qt.UserRole)
        if entry is None or not entry.is_dir:
            event.ignore()
            return
        src_paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.toLocalFile() and url.toLocalFile() != entry.path
        ]
        if not src_paths:
            event.ignore()
            return
        if self.on_drop_to_folder is not None:
            self.on_drop_to_folder(Path(entry.path), src_paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class _DragDropListView(QListView):
    """支持内部拖拽到文件夹的 QListView（卡片视图用）。

    UX 重构 Phase 1 Task 4：与 _RubberBandTableView 相同的拖拽逻辑，
    用于卡片视图内拖拽文件到同目录文件夹。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.on_drop_to_folder: Callable[[Path, list[Path]], None] | None = None

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.source() is self and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.source() is self and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.source() is not self or not event.mimeData().hasUrls():
            event.ignore()
            return
        index = self.indexAt(event.pos())
        if not index.isValid():
            event.ignore()
            return
        entry = self.model().data(index, Qt.UserRole)
        if entry is None or not entry.is_dir:
            event.ignore()
            return
        src_paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.toLocalFile() and url.toLocalFile() != entry.path
        ]
        if not src_paths:
            event.ignore()
            return
        if self.on_drop_to_folder is not None:
            self.on_drop_to_folder(Path(entry.path), src_paths)
            event.acceptProposedAction()
        else:
            event.ignore()
