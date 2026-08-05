"""分类颜色选择子对话框（BugFix2，2026-08-03 验收反馈改为预选色表）。

提供一屏固定 S/L 的色相预选表（所见即所得）：
点击色块即选中，选中的颜色与存储/显示完全一致；
不再使用 QColorDialog 的 RGB 快速色板（"快速颜色与实际颜色不一致"根因）
也不再用单一滑块（验收反馈：滑块调色不直观）。

schema v15（2026-08-05）：对话框返回完整颜色（#RRGGBB），
与 tag_category.color_hex 存储一致；预选色块由 hue_to_hex 统一换算。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from app.tag_colors import category_color
from infrastructure.color_utils import hue_to_hex

# 预选色相：每 15° 一档（24 色）
_PRESET_HUES = tuple(range(0, 360, 15))
_GRID_COLUMNS = 8


class ColorPickerDialog(QDialog):
    """预选色表选色对话框。确定后通过 selected_hex() 取完整颜色（#RRGGBB）。"""

    def __init__(self, initial_hex: str = "#1A78D6", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(ui.TAG_COLOR_DIALOG_TITLE)
        self.setModal(True)
        self.resize(380, 320)

        self._selected_hex = category_color(initial_hex).name().upper()
        self._swatch_buttons: list[tuple[str, QPushButton]] = []

        layout = QVBoxLayout(self)

        # 色块预览 + 当前颜色数值
        preview_row = QHBoxLayout()
        self._preview = QLabel()
        self._preview.setFixedSize(64, 64)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_row.addWidget(self._preview)
        self._color_value_label = QLabel("")
        preview_row.addWidget(self._color_value_label)
        preview_row.addStretch(1)
        layout.addLayout(preview_row)

        # 预选色表
        grid = QGridLayout()
        grid.setSpacing(4)
        for index, hue in enumerate(_PRESET_HUES):
            hex_color = hue_to_hex(hue)
            btn = QPushButton()
            btn.setFixedSize(30, 30)
            btn.setToolTip(hex_color)
            btn.clicked.connect(lambda checked=False, h=hex_color: self._select_hex(h))
            grid.addWidget(btn, index // _GRID_COLUMNS, index % _GRID_COLUMNS)
            self._swatch_buttons.append((hex_color, btn))
        layout.addLayout(grid)

        # 按钮
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._ok_button = QPushButton(ui.TAG_COLOR_DIALOG_OK)
        self._ok_button.setAutoDefault(False)
        self._ok_button.clicked.connect(self.accept)
        button_row.addWidget(self._ok_button)
        self._cancel_button = QPushButton(ui.TAG_COLOR_DIALOG_CANCEL)
        self._cancel_button.setAutoDefault(False)
        self._cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self._cancel_button)
        layout.addLayout(button_row)

        self._apply_swatch_highlight()
        self._refresh_preview()

    def _select_hex(self, color_hex: str) -> None:
        """点击色块 → 更新选中颜色与预览。"""
        self._selected_hex = category_color(color_hex).name().upper()
        self._apply_swatch_highlight()
        self._refresh_preview()

    def _apply_swatch_highlight(self) -> None:
        """当前选中色块加边框高亮。"""
        for hex_color, btn in self._swatch_buttons:
            border = "#1976d2" if hex_color == self._selected_hex else "#888888"
            btn.setStyleSheet(
                f"QPushButton {{ background: {hex_color}; "
                f"border: 2px solid {border}; border-radius: 4px; }}"
            )

    def _refresh_preview(self) -> None:
        """更新预览色块与数值文本。"""
        color = category_color(self._selected_hex)
        self._preview.setStyleSheet(
            f"background: {color.name()}; border: 1px solid #888; border-radius: 4px;"
        )
        self._color_value_label.setText(self._selected_hex)

    # --- 公共接口 ---

    def selected_hex(self) -> str:
        """返回当前选中的完整颜色（大写 #RRGGBB）。"""
        return self._selected_hex

    # --- 测试辅助 ---

    def preset_hues(self) -> tuple[int, ...]:
        return _PRESET_HUES

    def click_swatch(self, hue: int) -> None:
        """程序化点击指定色相（0-359）对应的色块（供测试）。"""
        target = hue_to_hex(hue)
        for hex_color, btn in self._swatch_buttons:
            if hex_color == target:
                btn.click()
                return

    def preview_color(self) -> QColor:
        return category_color(self.selected_hex())
