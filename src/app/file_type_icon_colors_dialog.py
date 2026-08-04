"""文件类型图标颜色设置对话框（UI合理性4 二期，2026-08-04）。

四类文件类型图标颜色（文件夹 / 压缩包 / 图片 / 其他文档）均可自定义，
颜色选择使用 QColorDialog（全功能，含十六进制输入）；提供「恢复默认」。
确定后通过 ``resulting_colors()`` 取当前配置，由 MainWindow 保存并应用。
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app import ui_constants as ui

# 对话框管理的类型键顺序（与 FILE_TYPE_ICON_COLORS 键一致）
_TYPE_KEYS: tuple[str, ...] = ("folder", "archive", "image", "document")
# 标签统一对齐到 4 个全角字符宽（最长标签「其他文档」），颜色按钮起点一致
_LABEL_WIDTH_CHARS = 4


def _padded_label(text: str) -> str:
    """右侧用全角空格补齐到 4 字符宽，保证各行颜色按钮对齐。"""
    pad_count = _LABEL_WIDTH_CHARS - len(text)
    return text + "\u3000" * pad_count if pad_count > 0 else text


class FileTypeIconColorsDialog(QDialog):
    """文件类型图标颜色配置对话框。"""

    def __init__(
        self,
        initial_colors: dict[str, str],
        parent=None,
    ) -> None:  # noqa: ANN001 (Qt 签名)
        super().__init__(parent)
        self.setWindowTitle(ui.FILE_TYPE_ICON_COLORS_DIALOG_TITLE)
        self.setModal(True)
        self.resize(380, 240)
        self._colors: dict[str, QColor] = {
            type_key: QColor(initial_colors.get(type_key, ui.FILE_TYPE_ICON_COLORS[type_key]))
            for type_key in _TYPE_KEYS
        }
        self._color_buttons: dict[str, QPushButton] = {}
        self._labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        hint = QLabel(ui.FILE_TYPE_ICON_COLORS_HINT)
        layout.addWidget(hint)

        # 每类一行：名称 + 颜色按钮（文字 = 大写 hex，底色 = 当前颜色）
        for type_key in _TYPE_KEYS:
            row = QHBoxLayout()
            label = QLabel(_padded_label(ui.FILE_TYPE_ICON_COLORS_LABELS[type_key]))
            button = QPushButton()
            button.setFixedWidth(140)
            button.clicked.connect(lambda checked=False, key=type_key: self._pick_color(key))
            row.addWidget(label)
            row.addWidget(button)
            row.addStretch(1)
            layout.addLayout(row)
            self._color_buttons[type_key] = button
            self._labels[type_key] = label

        # 恢复默认 + 确定/取消
        reset_row = QHBoxLayout()
        reset_button = QPushButton(ui.FILE_TYPE_ICON_COLORS_RESET)
        reset_button.clicked.connect(self._reset_to_defaults)
        reset_row.addWidget(reset_button)
        reset_row.addStretch(1)
        layout.addLayout(reset_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_buttons()

    # --- 内部 ---

    def _update_buttons(self) -> None:
        """按当前颜色刷新各类型按钮（文字 + 底色）。"""
        for type_key, color in self._colors.items():
            button = self._color_buttons[type_key]
            button.setText(color.name().upper())
            button.setStyleSheet(
                f"background-color: {color.name()};"
                f"color: {'white' if color.lightness() < 128 else 'black'};"
            )

    def _pick_color(self, type_key: str) -> None:
        color = QColorDialog.getColor(
            self._colors[type_key],
            self,
            ui.FILE_TYPE_ICON_COLORS_LABELS[type_key],
        )
        if color.isValid():
            self._colors[type_key] = color
            self._update_buttons()

    def _reset_to_defaults(self) -> None:
        self._colors = {
            type_key: QColor(ui.FILE_TYPE_ICON_COLORS[type_key]) for type_key in _TYPE_KEYS
        }
        self._update_buttons()

    # --- 外部 ---

    def resulting_colors(self) -> dict[str, str]:
        """返回当前配置（大写 hex，仅应在 accepted 后调用）。"""
        return {type_key: color.name().upper() for type_key, color in self._colors.items()}

    # --- 测试辅助 ---

    def color_button(self, type_key: str) -> QPushButton:
        return self._color_buttons[type_key]

    def label(self, type_key: str) -> QLabel:
        return self._labels[type_key]
