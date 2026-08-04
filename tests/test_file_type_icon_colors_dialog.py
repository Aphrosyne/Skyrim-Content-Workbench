"""文件类型图标颜色设置对话框测试（UI合理性4 二期，2026-08-04）。"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QPushButton  # noqa: E402

from app import ui_constants as ui  # noqa: E402
from app.file_type_icon_colors_dialog import FileTypeIconColorsDialog  # noqa: E402


def _initial() -> dict[str, str]:
    return {
        "folder": "#F6E03B",
        "archive": "#72E9A1",
        "image": "#8AB8E6",
        "document": "#FFFFFF",
    }


def test_dialog_title_and_four_color_buttons(qapp) -> None:
    dialog = FileTypeIconColorsDialog(_initial())
    try:
        assert dialog.windowTitle() == ui.FILE_TYPE_ICON_COLORS_DIALOG_TITLE
        assert dialog.resulting_colors() == _initial()
        for type_key in ("folder", "archive", "image", "document"):
            button = dialog.color_button(type_key)
            assert button.text() == _initial()[type_key].upper()
    finally:
        dialog.close()


def test_labels_aligned_to_four_chars(qapp) -> None:
    """验收反馈（2026-08-04）：四行标签统一补齐到 4 字符宽，颜色按钮对齐。"""
    dialog = FileTypeIconColorsDialog(_initial())
    try:
        widths = {key: dialog.label(key).sizeHint().width() for key in _initial()}
        assert len(set(widths.values())) == 1
        for key in _initial():
            assert dialog.label(key).text().startswith(ui.FILE_TYPE_ICON_COLORS_LABELS[key])
    finally:
        dialog.close()


def test_reset_restores_defaults(qapp) -> None:
    custom = {
        "folder": "#111111",
        "archive": "#222222",
        "image": "#333333",
        "document": "#444444",
    }
    dialog = FileTypeIconColorsDialog(custom)
    try:
        assert dialog.resulting_colors() == custom
        # 触发恢复默认（点击「恢复默认」按钮）
        buttons = dialog.findChildren(QPushButton)
        reset = [b for b in buttons if b.text() == ui.FILE_TYPE_ICON_COLORS_RESET]
        assert reset
        reset[0].click()
        defaults = {k: v.upper() for k, v in ui.FILE_TYPE_ICON_COLORS.items()}
        assert dialog.resulting_colors() == defaults
    finally:
        dialog.close()
