"""开源资产致谢对话框测试（UI合理性4 资产引用，2026-08-04）。"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLabel, QPushButton  # noqa: E402

from app import ui_constants as ui  # noqa: E402
from app.asset_credits_dialog import AssetCreditsDialog  # noqa: E402


def test_dialog_title_and_content(qapp) -> None:
    dialog = AssetCreditsDialog()
    try:
        assert dialog.windowTitle() == ui.ASSET_CREDITS_DIALOG_TITLE
        labels = [label.text() for label in dialog.findChildren(QLabel)]
        body = "".join(labels)
        assert ui.ASSET_CREDITS_ICON_PACK_NAME in body
        assert ui.ASSET_CREDITS_ICON_PACK_SOURCE_URL in body
        assert ui.ASSET_CREDITS_ICON_PACK_LICENSE_URL in body
        assert ui.ASSET_CREDITS_ICON_PACK_LOCAL in body
    finally:
        dialog.close()


def test_close_button_closes_dialog(qapp) -> None:
    """关闭按钮触发 accept（QDialog.Accepted）。"""
    dialog = AssetCreditsDialog()
    try:
        buttons = dialog.findChildren(QPushButton)
        assert buttons, "应存在关闭按钮"
        result = []
        dialog.accepted.connect(lambda: result.append(True))
        buttons[0].click()
        assert result == [True]
    finally:
        dialog.close()
