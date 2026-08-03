"""分类颜色共享 helper（BugFix2，2026-08-03）。

统一 ``color_hue`` → QColor / 样式表 hex / 色块图标 的换算，
保证标签管理、元数据面板、标签筛选栏、批量打标签各处颜色一致。
分类颜色语义 = "色相"（固定饱和度/亮度，与既有显示一致）。
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPixmap

# 分类颜色固定 S/L（Qt 0-255 范围），与既有显示一致
_SATURATION = 200
_LIGHTNESS = 120


def category_color(hue: int) -> QColor:
    """hue（0-360）→ 分类显示颜色（固定 S/L）。"""
    return QColor.fromHsl(hue % 360, _SATURATION, _LIGHTNESS)


def category_color_hex(hue: int) -> str:
    """hue → 样式表用十六进制色值（如 '#7fb0e0'）。"""
    return category_color(hue).name()


def text_color_for(hue: int) -> QColor:
    """按分类色相对亮度自动选择黑/白文字色（高对比，BugFix2 验收反馈）。"""
    color = category_color(hue)

    def _linear(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    luminance = (
        0.2126 * _linear(color.red())
        + 0.7152 * _linear(color.green())
        + 0.0722 * _linear(color.blue())
    )
    return QColor("#1a1a1a") if luminance > 0.5 else QColor("#ffffff")


def text_color_hex(hue: int) -> str:
    """hue → 自动黑/白文字色的 hex。"""
    return text_color_for(hue).name()


def color_icon(hue: int, size: int = 16) -> QPixmap:
    """生成 size×size 的实心色块图标。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(category_color(hue))
    return pixmap
