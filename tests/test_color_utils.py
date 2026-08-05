"""color_utils.hue_to_hex 换算测试（schema v15：tag_category 完整颜色）。

核心保证：迁移回填与 UI 显示共用同一换算，升级前后颜色观感完全一致。
"""

from __future__ import annotations

from infrastructure.color_utils import hue_to_hex


def test_hue_to_hex_known_values() -> None:
    """关键色相的大写 #RRGGBB 输出（固定 S=200 / L=120）。"""
    assert hue_to_hex(0) == "#D61A1A"
    assert hue_to_hex(30) == "#D6781A"
    assert hue_to_hex(120) == "#1AD61A"
    assert hue_to_hex(210) == "#1A78D6"
    assert hue_to_hex(280) == "#971AD6"


def test_hue_to_hex_uppercase() -> None:
    assert hue_to_hex(210).isupper()
    assert hue_to_hex(210).startswith("#")
    assert len(hue_to_hex(210)) == 7


def test_hue_normalized_to_range() -> None:
    assert hue_to_hex(360) == hue_to_hex(0)
    assert hue_to_hex(-30) == hue_to_hex(330)


def test_hue_to_hex_matches_qt_from_hsl(qapp) -> None:
    """与 Qt QColor.fromHsl 全量对照（0-359 全部一致，保证观感零变化）。"""
    from PySide6.QtGui import QColor

    for hue in range(360):
        q = QColor.fromHsl(hue, 200, 120)
        expected = f"#{q.red():02X}{q.green():02X}{q.blue():02X}"
        assert hue_to_hex(hue) == expected, f"hue={hue} 不一致"


def test_matches_default_tags_colors() -> None:
    """预置标签库 v2 的 color_hex 值应与换算一致。"""
    for hue, expected in (
        (210, "#1A78D6"),
        (30, "#D6781A"),
        (120, "#1AD61A"),
        (0, "#D61A1A"),
        (280, "#971AD6"),
    ):
        assert hue_to_hex(hue) == expected
