"""ColorPickerDialog 预选色表测试（BugFix2，2026-08-03 验收反馈）。"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.color_picker_dialog import ColorPickerDialog  # noqa: E402
from app.tag_colors import category_color  # noqa: E402


def test_initial_hue_and_preview(qapp) -> None:
    dialog = ColorPickerDialog(initial_hue=210)
    try:
        assert dialog.selected_hue() == 210
        assert dialog.preview_color() == category_color(210)
        assert 210 in dialog.preset_hues()
    finally:
        dialog.close()


def test_click_swatch_updates_selected_and_preview(qapp) -> None:
    dialog = ColorPickerDialog(initial_hue=210)
    try:
        dialog.click_swatch(120)
        assert dialog.selected_hue() == 120
        assert dialog.preview_color() == category_color(120)

        dialog.click_swatch(345)
        assert dialog.selected_hue() == 345
    finally:
        dialog.close()


def test_preset_hues_cover_full_circle(qapp) -> None:
    dialog = ColorPickerDialog()
    try:
        hues = dialog.preset_hues()
        assert hues == tuple(range(0, 360, 15))
        assert len(hues) == 24
    finally:
        dialog.close()


def test_hue_normalized_to_range(qapp) -> None:
    dialog = ColorPickerDialog(initial_hue=400)
    try:
        assert dialog.selected_hue() == 40
    finally:
        dialog.close()
