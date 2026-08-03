"""分类颜色选择子对话框（BugFix2，2026-08-03 验收反馈改为预选色表）。

提供一屏固定 S/L 的色相预选表（所见即所得）：
点击色块即选中，选中的 hue 与存储/显示完全一致；
不再使用 QColorDialog 的 RGB 快速色板（"快速颜色与实际颜色不一致"根因）
也不再用单一滑块（验收反馈：滑块调色不直观）。
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
from app.tag_colors import category_color, category_color_hex

# 预选色相：每 15° 一档（24 色）
_PRESET_HUES = tuple(range(0, 360, 15))
_GRID_COLUMNS = 8


class ColorPickerDialog(QDialog):
    """预选色表选色对话框。确定后通过 selected_hue() 取色相（0-359）。"""

    def __init__(self, initial_hue: int = 210, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(ui.TAG_COLOR_DIALOG_TITLE)
        self.setModal(True)
        self.resize(380, 320)

        self._selected_hue = initial_hue % 360
        self._swatch_buttons: list[tuple[int, QPushButton]] = []

        layout = QVBoxLayout(self)

        # 色块预览 + 当前 hue 数值
        preview_row = QHBoxLayout()
        self._preview = QLabel()
        self._preview.setFixedSize(64, 64)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_row.addWidget(self._preview)
        self._hue_value_label = QLabel("")
        preview_row.addWidget(self._hue_value_label)
        preview_row.addStretch(1)
        layout.addLayout(preview_row)

        # 预选色表
        grid = QGridLayout()
        grid.setSpacing(4)
        for index, hue in enumerate(_PRESET_HUES):
            btn = QPushButton()
            btn.setFixedSize(30, 30)
            btn.setToolTip(f"H={hue}（{category_color_hex(hue)}）")
            btn.clicked.connect(lambda checked=False, h=hue: self._select_hue(h))
            grid.addWidget(btn, index // _GRID_COLUMNS, index % _GRID_COLUMNS)
            self._swatch_buttons.append((hue, btn))
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

    def _select_hue(self, hue: int) -> None:
        """点击色块 → 更新选中色相与预览。"""
        self._selected_hue = hue
        self._apply_swatch_highlight()
        self._refresh_preview()

    def _apply_swatch_highlight(self) -> None:
        """当前选中色块加边框高亮。"""
        for hue, btn in self._swatch_buttons:
            border = "#1976d2" if hue == self._selected_hue else "#888888"
            btn.setStyleSheet(
                f"QPushButton {{ background: {category_color_hex(hue)}; "
                f"border: 2px solid {border}; border-radius: 4px; }}"
            )

    def _refresh_preview(self) -> None:
        """更新预览色块与数值文本。"""
        color = category_color(self._selected_hue)
        self._preview.setStyleSheet(
            f"background: {color.name()}; border: 1px solid #888; border-radius: 4px;"
        )
        self._hue_value_label.setText(f"{color.name()}（H={self._selected_hue}）")

    # --- 公共接口 ---

    def selected_hue(self) -> int:
        """返回当前选中的 hue（0-359）。"""
        return self._selected_hue

    # --- 测试辅助 ---

    def preset_hues(self) -> tuple[int, ...]:
        return _PRESET_HUES

    def click_swatch(self, hue: int) -> None:
        """程序化点击指定色块（供测试）。"""
        for h, btn in self._swatch_buttons:
            if h == hue:
                btn.click()
                return

    def preview_color(self) -> QColor:
        return category_color(self.selected_hue())
