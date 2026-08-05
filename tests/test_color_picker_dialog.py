"""ColorPickerDialog 预选色表测试（BugFix2，2026-08-03 验收反馈；schema v15 hex）。"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.color_picker_dialog import ColorPickerDialog  # noqa: E402
from app.tag_colors import category_color  # noqa: E402


def test_initial_color_and_preview(qapp) -> None:
    dialog = ColorPickerDialog(initial_hex="#1A78D6")
    try:
        assert dialog.selected_hex() == "#1A78D6"
        assert dialog.preview_color() == category_color("#1A78D6")
        assert 210 in dialog.preset_hues()
    finally:
        dialog.close()


def test_click_swatch_updates_selected_and_preview(qapp) -> None:
    dialog = ColorPickerDialog(initial_hex="#1A78D6")
    try:
        dialog.click_swatch(120)
        assert dialog.selected_hex() == "#1AD61A"
        assert dialog.preview_color() == category_color("#1AD61A")

        dialog.click_swatch(345)
        assert dialog.selected_hex() == "#D61A49"
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


def test_invalid_initial_color_falls_back(qapp) -> None:
    dialog = ColorPickerDialog(initial_hex="not-a-color")
    try:
        assert dialog.selected_hex() == "#808080"
    finally:
        dialog.close()
