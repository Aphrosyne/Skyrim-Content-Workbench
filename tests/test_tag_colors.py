"""tag_colors 共享颜色 helper 测试（BugFix2，2026-08-03；schema v15 hex 输入）。"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.tag_colors import (  # noqa: E402
    category_color,
    category_color_faded_hex,
    category_color_hex,
    category_color_vivid_hex,
    color_icon,
    text_color_faded_hex,
    text_color_hex,
    text_color_vivid_hex,
)


def test_category_color_fixed_saturation_lightness(qapp) -> None:
    color = category_color("#1A78D6")
    assert color.hslHue() == 210
    assert color.hslSaturation() == 200
    assert color.lightness() == 120


def test_category_color_invalid_falls_back(qapp) -> None:
    assert category_color("").name().upper() == "#808080"


def test_category_color_hex_matches_color_name(qapp) -> None:
    assert category_color_hex("#1A78D6") == "#1A78D6"
    assert category_color_hex("#1a78d6") == "#1A78D6"  # 统一大写


def test_color_icon_size(qapp) -> None:
    icon = color_icon("#1A78D6")
    assert icon.width() == 16
    assert icon.height() == 16
    assert not icon.isNull()

    big = color_icon("#1AD61A", size=32)
    assert big.width() == 32


def test_text_color_auto_black_or_white(qapp) -> None:
    """按相对亮度自动选择黑/白文字色（高对比）。"""
    # 黄色（相对亮度高）→ 黑字；蓝色（相对亮度低）→ 白字
    assert text_color_hex("#D6D61A") == "#1a1a1a"
    assert text_color_hex("#1A78D6") == "#ffffff"


def test_vivid_and_faded_variants(qapp) -> None:
    """选中/排除态：同色相按固定 S/L 重建（观感与旧 hue 方案一致）。"""
    assert category_color_vivid_hex("#1A78D6") == "#0582FF"
    assert category_color_faded_hex("#1A78D6") == "#718CA7"
    assert text_color_vivid_hex("#1A78D6") == "#ffffff"
    assert text_color_faded_hex("#1A78D6") == "#ffffff"
