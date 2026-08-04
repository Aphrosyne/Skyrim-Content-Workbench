"""开源资产致谢对话框（UI合理性4 资产引用，2026-08-04）。

展示本软件引用的第三方开源资产（图标库 game-icon-pack）的来源、作者与许可，
尊重原作者。入口：顶部菜单「帮助 → 开源资产致谢…」。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app import ui_constants as ui


class AssetCreditsDialog(QDialog):
    """开源资产致谢对话框。"""

    def __init__(self, parent=None) -> None:  # noqa: ANN001 (Qt 签名)
        super().__init__(parent)
        self.setWindowTitle(ui.ASSET_CREDITS_DIALOG_TITLE)
        self.setMinimumWidth(480)

        heading = QLabel(ui.ASSET_CREDITS_HEADING)
        heading.setStyleSheet("font-weight: bold; font-size: 13px;")

        source_link = (
            f'<a href="{ui.ASSET_CREDITS_ICON_PACK_SOURCE_URL}">'
            f"{ui.ASSET_CREDITS_ICON_PACK_SOURCE_URL}</a>"
        )
        license_link = (
            f'<a href="{ui.ASSET_CREDITS_ICON_PACK_LICENSE_URL}">'
            f"{ui.ASSET_CREDITS_ICON_PACK_LICENSE_URL}</a>"
        )
        body = QLabel(
            "<p>"
            f"<b>{ui.ASSET_CREDITS_ICON_PACK_NAME}</b>　{ui.ASSET_CREDITS_ICON_PACK_AUTHOR}"
            "</p>"
            f"<p>{ui.ASSET_CREDITS_ICON_PACK_SOURCE}{source_link}</p>"
            f"<p>{ui.ASSET_CREDITS_ICON_PACK_LICENSE}<br>{license_link}</p>"
            f"<p>{ui.ASSET_CREDITS_ICON_PACK_LOCAL}</p>"
            f"<p>{ui.ASSET_CREDITS_THANKS}</p>"
        )
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        body.setOpenExternalLinks(True)
        body.setWordWrap(True)

        close_button = QPushButton(ui.ASSET_CREDITS_CLOSE)
        close_button.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addSpacing(8)
        layout.addWidget(body)
        layout.addSpacing(8)
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)
