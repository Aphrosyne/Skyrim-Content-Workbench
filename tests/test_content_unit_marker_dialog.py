"""内容单元标记设置对话框测试（UI合理性21，2026-08-04）。

覆盖：
- 字符框/颜色按钮在对应标记未启用时仍可编辑（预填后再启用）
- resulting_config 返回当前输入
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app import ui_constants as ui  # noqa: E402
from app.content_unit_marker_config import ContentUnitMarkerConfig  # noqa: E402
from app.content_unit_marker_dialog import ContentUnitMarkerDialog  # noqa: E402


def _config(
    *,
    icon_enabled: bool,
    stripe_enabled: bool,
) -> ContentUnitMarkerConfig:
    return ContentUnitMarkerConfig(
        icon_enabled=icon_enabled,
        icon_glyph=ui.CONTENT_UNIT_MARKER,
        stripe_enabled=stripe_enabled,
        stripe_color=ui.CONTENT_UNIT_STRIPE_COLOR,
    )


def test_glyph_editable_when_icon_disabled(qapp) -> None:  # noqa: ANN001
    dialog = ContentUnitMarkerDialog(_config(icon_enabled=False, stripe_enabled=True))
    try:
        assert not dialog.icon_checkbox().isChecked()
        assert dialog.glyph_edit().isEnabled()  # 验收反馈：未启用也能预填字符
    finally:
        dialog.close()


def test_color_button_editable_when_stripe_disabled(qapp) -> None:  # noqa: ANN001
    dialog = ContentUnitMarkerDialog(_config(icon_enabled=True, stripe_enabled=False))
    try:
        assert not dialog.stripe_checkbox().isChecked()
        assert dialog.color_button().isEnabled()  # 未启用也能预选颜色
    finally:
        dialog.close()


def test_glyph_editable_after_unchecking_icon(qapp) -> None:  # noqa: ANN001
    dialog = ContentUnitMarkerDialog(_config(icon_enabled=True, stripe_enabled=True))
    try:
        dialog.icon_checkbox().setChecked(False)
        assert dialog.glyph_edit().isEnabled()
    finally:
        dialog.close()


def test_resulting_config_reflects_edits(qapp) -> None:  # noqa: ANN001
    dialog = ContentUnitMarkerDialog(_config(icon_enabled=False, stripe_enabled=True))
    try:
        dialog.glyph_edit().setText("★")
        dialog.icon_checkbox().setChecked(True)
        dialog.stripe_checkbox().setChecked(False)
        config = dialog.resulting_config()
        assert config.icon_enabled is True
        assert config.icon_glyph == "★"
        assert config.stripe_enabled is False
        assert config.stripe_color == ui.CONTENT_UNIT_STRIPE_COLOR
    finally:
        dialog.close()
