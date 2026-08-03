"""tag_colors 共享颜色 helper 测试（BugFix2，2026-08-03）。"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.tag_colors import (  # noqa: E402
    category_color,
    category_color_hex,
    color_icon,
    text_color_for,
    text_color_hex,
)


def test_category_color_fixed_saturation_lightness(qapp) -> None:
    color = category_color(210)
    assert color.hslHue() == 210
    assert color.hslSaturation() == 200
    assert color.lightness() == 120


def test_category_color_normalizes_hue(qapp) -> None:
    assert category_color(360).hslHue() == 0
    assert category_color(-30).hslHue() in (330, -1)  # Qt 归一化到 0-359 或 -1


def test_category_color_hex_matches_color_name(qapp) -> None:
    assert category_color_hex(210) == category_color(210).name()
    assert category_color_hex(210).startswith("#")


def test_color_icon_size(qapp) -> None:
    icon = color_icon(210)
    assert icon.width() == 16
    assert icon.height() == 16
    assert not icon.isNull()

    big = color_icon(120, size=32)
    assert big.width() == 32


def test_text_color_auto_black_or_white(qapp) -> None:
    """按相对亮度自动选择黑/白文字色（高对比）。"""
    # 黄色（相对亮度高）→ 黑字；蓝色（相对亮度低）→ 白字
    assert text_color_hex(60) == "#1a1a1a"
    assert text_color_hex(210) == "#ffffff"
    assert text_color_hex(60) == text_color_for(60).name()
