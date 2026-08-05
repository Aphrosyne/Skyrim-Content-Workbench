"""分类颜色共享 helper（BugFix2，2026-08-03；schema v15 起 hex 输入）。

统一 ``color_hex``（#RRGGBB，完整颜色）→ QColor / 样式表 hex / 色块图标
的换算，保证标签管理、元数据面板、标签筛选栏、批量打标签各处颜色一致。

schema v15（2026-08-05）：tag_category 存储完整颜色（color_hue → color_hex）。
选中/排除三态变体从存储色的色相按固定 S/L 重建（与既有显示一致，已验证
24 个预选色相 RGB→HSL 往返无偏差）。
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPixmap

# 分类颜色固定 S/L（Qt 0-255 范围），与既有显示一致
_SATURATION = 200
_LIGHTNESS = 120
# 已选中态：略微提饱和（UI合理性16）
_SELECTED_SATURATION = 255
_SELECTED_LIGHTNESS = 130
# 已排除态：降饱和/变淡但保留色相（UI合理性16）
_FADED_SATURATION = 60
_FADED_LIGHTNESS = 140


def _qcolor(color_hex: str) -> QColor:
    """color_hex（#RRGGBB）→ QColor；非法值回退灰色。"""
    color = QColor(color_hex or "")
    return color if color.isValid() else QColor("#808080")


def _hue_of(color_hex: str) -> int:
    """取存储色的色相（用于选中/排除态按原 S/L 重建）。"""
    return max(0, _qcolor(color_hex).hslHue())


def category_color(color_hex: str) -> QColor:
    """color_hex → 分类显示颜色。"""
    return _qcolor(color_hex)


def category_color_vivid(color_hex: str) -> QColor:
    """已选中态颜色（同色相，略微提饱和）。"""
    return QColor.fromHsl(_hue_of(color_hex), _SELECTED_SATURATION, _SELECTED_LIGHTNESS)


def category_color_vivid_hex(color_hex: str) -> str:
    """已选中态背景 hex。"""
    return category_color_vivid(color_hex).name().upper()


def category_color_faded(color_hex: str) -> QColor:
    """已排除态颜色（同色相，降饱和/变淡）。"""
    return QColor.fromHsl(_hue_of(color_hex), _FADED_SATURATION, _FADED_LIGHTNESS)


def category_color_faded_hex(color_hex: str) -> str:
    """已排除态背景 hex。"""
    return category_color_faded(color_hex).name().upper()


def category_color_hex(color_hex: str) -> str:
    """样式表用十六进制色值（大写 #RRGGBB，与存储一致）。"""
    return category_color(color_hex).name().upper()


def text_color_hex(color_hex: str) -> str:
    """按分类色相对亮度自动选择黑/白文字色 hex（高对比，BugFix2 验收反馈）。"""
    return _text_hex_for_color(category_color(color_hex))


def _text_hex_for_color(color: QColor) -> str:
    """按给定颜色的相对亮度自动选择黑/白文字色 hex。"""

    def _linear(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    luminance = (
        0.2126 * _linear(color.red())
        + 0.7152 * _linear(color.green())
        + 0.0722 * _linear(color.blue())
    )
    return "#1a1a1a" if luminance > 0.5 else "#ffffff"


def text_color_vivid_hex(color_hex: str) -> str:
    """已选中态背景 → 自动黑/白文字色 hex。"""
    return _text_hex_for_color(category_color_vivid(color_hex))


def text_color_faded_hex(color_hex: str) -> str:
    """已排除态背景 → 自动黑/白文字色 hex。"""
    return _text_hex_for_color(category_color_faded(color_hex))


def color_icon(color_hex: str, size: int = 16) -> QPixmap:
    """生成 size×size 的实心色块图标（color_hex 输入）。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(category_color(color_hex))
    return pixmap
