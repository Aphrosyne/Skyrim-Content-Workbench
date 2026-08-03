"""内容单元标记设置对话框（UI合理性21，2026-08-04）。

配置项：
- 行首图标标记开关 + 标记字符（单个 Unicode 字符）
- 左侧色条开关 + 颜色（QColorDialog 全功能，含十六进制输入）
- 恢复默认按钮；确定时校验"至少启用一个"
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from app.content_unit_marker_config import ContentUnitMarkerConfig, validate_config


class ContentUnitMarkerDialog(QDialog):
    """内容单元标记配置对话框。确定后通过 resulting_config() 取配置。"""

    def __init__(
        self,
        initial: ContentUnitMarkerConfig | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(ui.MARKER_CONFIG_DIALOG_TITLE)
        self.setModal(True)
        self.resize(360, 200)
        self._initial = initial or ContentUnitMarkerConfig.defaults()
        self._stripe_color = QColor(self._initial.stripe_color)

        layout = QVBoxLayout(self)

        # 行首图标标记
        self._icon_checkbox = QCheckBox(ui.MARKER_CONFIG_ICON_ENABLED)
        layout.addWidget(self._icon_checkbox)
        glyph_row = QHBoxLayout()
        glyph_row.addWidget(QLabel(ui.MARKER_CONFIG_ICON_LABEL))
        self._glyph_edit = QLineEdit()
        self._glyph_edit.setMaxLength(4)  # 宽松输入上限，校验仍按单个字符
        # 验收反馈（2026-08-04）：字符框始终可编辑——图标未启用时也能预填字符，
        # 之后勾选启用即可生效，无需"先启用→确认→重开"才能输入。
        self._glyph_edit.setMaximumWidth(80)
        glyph_row.addWidget(self._glyph_edit)
        glyph_row.addStretch(1)
        layout.addLayout(glyph_row)

        # 左侧色条
        self._stripe_checkbox = QCheckBox(ui.MARKER_CONFIG_STRIPE_ENABLED)
        layout.addWidget(self._stripe_checkbox)
        stripe_row = QHBoxLayout()
        stripe_row.addWidget(QLabel(ui.MARKER_CONFIG_STRIPE_LABEL))
        self._color_button = QPushButton()
        # 同字符框：色条未启用时也可预选颜色（验收反馈，2026-08-04）
        self._color_button.setFixedWidth(120)
        self._color_button.clicked.connect(self._pick_color)
        stripe_row.addWidget(self._color_button)
        stripe_row.addStretch(1)
        layout.addLayout(stripe_row)

        # 恢复默认 + 确定/取消
        reset_row = QHBoxLayout()
        reset_button = QPushButton(ui.MARKER_CONFIG_RESET)
        reset_button.clicked.connect(self._reset_to_defaults)
        reset_row.addWidget(reset_button)
        reset_row.addStretch(1)
        layout.addLayout(reset_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load(self._initial)

    # --- 内部 ---

    def _load(self, config: ContentUnitMarkerConfig) -> None:
        self._icon_checkbox.setChecked(config.icon_enabled)
        self._glyph_edit.setText(config.icon_glyph)
        self._stripe_checkbox.setChecked(config.stripe_enabled)
        self._stripe_color = QColor(config.stripe_color)
        self._update_color_button()

    def _update_color_button(self) -> None:
        """刷新色条颜色按钮（文字 + 底色），始终可点击预选。"""
        self._color_button.setText(self._stripe_color.name().upper())
        self._color_button.setStyleSheet(
            f"background-color: {self._stripe_color.name()};"
            f"color: {'white' if self._stripe_color.lightness() < 128 else 'black'};"
        )

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(self._stripe_color, self, ui.MARKER_CONFIG_STRIPE_LABEL)
        if color.isValid():
            self._stripe_color = color
            self._update_color_button()

    def _reset_to_defaults(self) -> None:
        self._load(ContentUnitMarkerConfig.defaults())

    def _on_accept(self) -> None:
        glyph = self._glyph_edit.text().strip()
        error = validate_config(
            icon_enabled=self._icon_checkbox.isChecked(),
            icon_glyph=glyph,
            stripe_enabled=self._stripe_checkbox.isChecked(),
        )
        if error is not None:
            QMessageBox.warning(self, ui.MARKER_CONFIG_DIALOG_TITLE, error)
            return
        self.accept()

    # --- 外部 ---

    def resulting_config(self) -> ContentUnitMarkerConfig:
        """返回对话框当前配置（仅应在 accepted 后调用）。"""
        return ContentUnitMarkerConfig(
            icon_enabled=self._icon_checkbox.isChecked(),
            icon_glyph=self._glyph_edit.text().strip(),
            stripe_enabled=self._stripe_checkbox.isChecked(),
            stripe_color=self._stripe_color.name().upper(),
        )

    # --- 测试辅助 ---

    def icon_checkbox(self) -> QCheckBox:
        return self._icon_checkbox

    def glyph_edit(self) -> QLineEdit:
        return self._glyph_edit

    def stripe_checkbox(self) -> QCheckBox:
        return self._stripe_checkbox

    def color_button(self) -> QPushButton:
        return self._color_button
