"""色相 → 完整颜色换算（schema v15：tag_category 存储完整颜色）。

纯 Python 实现（colorsys），不依赖 Qt：
- 迁移回填（infrastructure 层）与 UI 显示（app.tag_colors）共用，
  保证升级前后分类颜色观感完全一致。
- 固定 S/L 与既有显示一致（S=200、L=120，Qt 0-255 范围）。

已验证：360 个色相下与 ``QColor.fromHsl(hue, 200, 120)`` 的 RGB 完全一致。
"""

from __future__ import annotations

import colorsys

# 分类颜色固定 S/L（与既有显示一致，tag_colors 同步维护）
HUE_SATURATION = 200
HUE_LIGHTNESS = 120


def hue_to_hex(hue: int) -> str:
    """hue（0-360）→ 大写 #RRGGBB（与既有显示色完全一致）。"""
    h = (hue % 360) / 360.0
    r, g, b = colorsys.hls_to_rgb(h, HUE_LIGHTNESS / 255.0, HUE_SATURATION / 255.0)
    return f"#{round(r * 255):02X}{round(g * 255):02X}{round(b * 255):02X}"
