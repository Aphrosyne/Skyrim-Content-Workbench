"""封面选择对话框（Stage 4 Task 2）。

spec §9 / §10.3：用户点击 MetadataPanel 的「设置封面」按钮 →
MainWindow 弹出本对话框。显示内容单元目录下所有支持的图片格式文件，
用户选择一张 → 返回相对内容单元路径的相对路径。

UI：
- 顶部提示
- 中间：QListWidget IconMode + Wrap，每个 item 显示缩略图 + 文件名
- 底部：确定 / 取消按钮

数据流：
- MainWindow 在弹出前调用 ContentService.list_cover_candidates(unit_path)
  获取候选列表，传给本 dialog。
- 用户选择 + 确定后，dialog.exec() 返回 Accepted。
- MainWindow 调用 dialog.selected_relative_path() 获取相对路径，
  再传给 MetadataPanel.set_cover_path()。

设计决策 2：默认选中第一张图片。

约束：
- 候选列表为空时显示空状态提示，确定按钮禁用。
- 不修改任何文件，仅返回选择结果。
- 缩略图大小固定（120x120），按 KeepAspectRatio 缩放。
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui

logger = logging.getLogger(__name__)

# 缩略图尺寸
_THUMB_SIZE = 120
# 缩略图 + 文本的总 item 尺寸
_ITEM_SIZE = QSize(_THUMB_SIZE + 20, _THUMB_SIZE + 40)


class CoverPickerDialog(QDialog):
    """封面选择对话框。

    通过构造注入候选图片路径列表 + 内容单元路径。
    用户选择后通过 selected_relative_path() 获取相对路径。
    """

    def __init__(
        self,
        candidates: list[Path],
        unit_path: Path,
        current_cover: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._candidates: list[Path] = list(candidates)
        self._unit_path = Path(unit_path)
        self._current_cover = current_cover
        self._selected: Path | None = None

        self.setWindowTitle(ui.COVER_PICKER_DIALOG_TITLE)
        self.resize(640, 480)

        self._setup_ui()
        self._load_candidates()
        # 决策 2：默认选中第一张
        self._select_first_or_current()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # 提示
        self._hint_label = QLabel(ui.COVER_PICKER_DIALOG_HINT)
        layout.addWidget(self._hint_label)

        # 空状态提示
        self._empty_label = QLabel(ui.COVER_PICKER_DIALOG_EMPTY)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #999; padding: 40px;")
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)

        # 图片网格列表
        self._list_widget = QListWidget()
        self._list_widget.setViewMode(QListWidget.ViewMode.IconMode)
        self._list_widget.setIconSize(QSize(_THUMB_SIZE, _THUMB_SIZE))
        self._list_widget.setGridSize(_ITEM_SIZE)
        self._list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list_widget.setMovement(QListWidget.Movement.Static)
        self._list_widget.setWordWrap(True)
        self._list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list_widget, 1)

        # 按钮栏
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._ok_button = QPushButton(ui.COVER_PICKER_DIALOG_OK)
        self._ok_button.setAutoDefault(False)
        self._ok_button.clicked.connect(self.accept)
        button_row.addWidget(self._ok_button)
        self._cancel_button = QPushButton(ui.COVER_PICKER_DIALOG_CANCEL)
        self._cancel_button.setAutoDefault(False)
        self._cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self._cancel_button)
        layout.addLayout(button_row)

    def _load_candidates(self) -> None:
        """加载所有候选图片到 list widget。"""
        if not self._candidates:
            self._empty_label.setVisible(True)
            self._list_widget.setVisible(False)
            self._ok_button.setEnabled(False)
            return

        for image_path in self._candidates:
            item = QListWidgetItem(image_path.name)
            item.setToolTip(str(image_path))
            item.setData(Qt.UserRole, image_path)
            # 加载缩略图
            pixmap = QPixmap(str(image_path))
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    _THUMB_SIZE,
                    _THUMB_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                item.setIcon(QIcon(scaled))
            self._list_widget.addItem(item)

    def _select_first_or_current(self) -> None:
        """默认选中第一张，或当前封面（若存在）。"""
        if not self._candidates:
            return

        target_row = 0
        if self._current_cover:
            current_path = (self._unit_path / self._current_cover).resolve()
            for i, candidate in enumerate(self._candidates):
                try:
                    if candidate.resolve() == current_path:
                        target_row = i
                        break
                except OSError:
                    continue

        self._list_widget.setCurrentRow(target_row)
        self._selected = self._candidates[target_row]

    def _on_selection_changed(self) -> None:
        """选中变化 → 更新 self._selected。"""
        items = self._list_widget.selectedItems()
        if not items:
            self._selected = None
            return
        path = items[0].data(Qt.UserRole)
        if isinstance(path, Path):
            self._selected = path

    # --- 公共接口 ---

    def selected_path(self) -> Path | None:
        """返回选中的图片完整路径（None 表示未选中）。"""
        return self._selected

    def selected_relative_path(self) -> str | None:
        """返回选中的图片相对内容单元路径的相对路径（None 表示未选中）。

        使用 POSIX 风格分隔符（正斜杠），便于跨平台存储。
        """
        if self._selected is None:
            return None
        try:
            rel = self._selected.relative_to(self._unit_path)
            return rel.as_posix()
        except ValueError:
            # 不在 unit_path 下（理论上不应发生），降级为文件名
            return self._selected.name

    def candidate_count(self) -> int:
        """返回候选图片数量（供测试）。"""
        return len(self._candidates)

    def current_selection_row(self) -> int:
        """返回当前选中的 row（-1 表示无选中，供测试）。"""
        return self._list_widget.currentRow()

    def click_item(self, index: int) -> None:
        """程序化选中指定 row（供测试）。"""
        if 0 <= index < self._list_widget.count():
            self._list_widget.setCurrentRow(index)

    def click_ok_button(self) -> None:
        """程序化触发「确定」按钮（供测试）。"""
        self.accept()

    def click_cancel_button(self) -> None:
        """程序化触发「取消」按钮（供测试）。"""
        self.reject()

    def is_ok_button_enabled(self) -> bool:
        """返回确定按钮是否启用（供测试）。"""
        return self._ok_button.isEnabled()
