"""内容单元行左侧色条 + 行首徽章 delegate（UI合理性13/21，2026-08-04）。

列表视图名称列专用 delegate：
- 所有行（含非内容单元）内容整体右移 config.reserved_width 像素，
  保证图标/文本行与行对齐；先铺满整格背景保证选中态连续。
- 内容单元行按配置在预留区绘制淡紫色竖条 + 徽章位图（UI合理性21：
  图标字符/色条颜色与开关均来自 ContentUnitMarkerConfig）。
- 徽章不拼进 DisplayRole 文本：emoji 字体回退会抬高行高度量（实测
  "armor" 15.23px vs "🔗 armor" 15.98px），导致文字垂直偏移约 1px；
  徽章改为 QPixmap 固定绘制，文本保持纯文件名。
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from app import ui_constants as ui
from app.content_unit_marker_config import ContentUnitMarkerConfig

_BADGE_PIXMAP_CACHE: dict[str, QPixmap] = {}


def content_unit_badge_pixmap(glyph: str) -> QPixmap:
    """渲染并缓存指定字符的徽章位图（按 glyph 键控，emoji 不进文本）。"""
    if glyph not in _BADGE_PIXMAP_CACHE:
        size = ui.CONTENT_UNIT_BADGE_SIZE
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont()
        font.setPixelSize(size)
        painter.setFont(font)
        # 实测 emoji 墨迹偏下约 1px，微调上移使其视觉居中
        painter.drawText(
            pixmap.rect().adjusted(0, -1, 0, -1),
            Qt.AlignmentFlag.AlignCenter,
            glyph,
        )
        painter.end()
        _BADGE_PIXMAP_CACHE[glyph] = pixmap
    return _BADGE_PIXMAP_CACHE[glyph]


def content_rect_with_stripe_reserve(rect: QRect, reserve: int) -> QRect:
    """内容绘制区域：整体右移预留宽度，色条/徽章独占最左侧（供测试）。"""
    return QRect(
        rect.left() + reserve,
        rect.top(),
        max(0, rect.width() - reserve),
        rect.height(),
    )


def content_unit_stripe_color(config: ContentUnitMarkerConfig, entry: object) -> QColor | None:
    """内容单元行按配置返回色条颜色；非内容单元或色条关闭返回 None。"""
    if not config.stripe_enabled:
        return None
    content_unit = getattr(entry, "content_unit", None)
    if content_unit is None:
        return None
    return QColor(config.stripe_color)


class ContentUnitStripeDelegate(QStyledItemDelegate):
    """列表视图名称列 delegate：按配置绘制左侧色条 + 行首徽章。"""

    def __init__(
        self,
        parent=None,
        config: ContentUnitMarkerConfig | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config or ContentUnitMarkerConfig.defaults()

    def set_config(self, config: ContentUnitMarkerConfig) -> None:
        """更新配置（调用方负责触发视图重绘）。"""
        self._config = config

    def config(self) -> ContentUnitMarkerConfig:
        return self._config

    def paint(  # noqa: N802 (Qt 命名)
        self,
        painter: QPainter,
        option,
        index: QModelIndex,
    ) -> None:
        entry = index.data(Qt.ItemDataRole.UserRole)
        stripe_color = content_unit_stripe_color(self._config, entry)
        # 1) 先铺满整格背景（含选中/悬停态），避免内容右移后预留区出现缺口
        style = option.widget.style() if option.widget is not None else QApplication.style()
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem,
            option,
            painter,
            option.widget,
        )
        # 2) 内容单元行按配置在预留区绘制色条 + 徽章
        x = option.rect.left()
        if stripe_color is not None:
            painter.save()
            painter.fillRect(
                x,
                option.rect.top(),
                ui.CONTENT_UNIT_STRIPE_WIDTH,
                option.rect.height(),
                stripe_color,
            )
            painter.restore()
            x += ui.CONTENT_UNIT_STRIPE_WIDTH + ui.CONTENT_UNIT_BADGE_LEADING_GAP
        if self._config.icon_enabled and getattr(entry, "content_unit", None) is not None:
            badge = content_unit_badge_pixmap(self._config.icon_glyph)
            badge_y = option.rect.top() + (option.rect.height() - badge.height()) // 2
            painter.drawPixmap(x, badge_y, badge)
            x += ui.CONTENT_UNIT_BADGE_SIZE + ui.CONTENT_UNIT_BADGE_TRAILING_GAP
        # 3) 所有行内容整体右移预留宽度，色条/徽章不覆盖图标且行与行对齐
        shifted = QStyleOptionViewItem(option)
        shifted.rect = content_rect_with_stripe_reserve(option.rect, self._config.reserved_width)
        self._paint_content(painter, shifted, index)

    def _paint_content(
        self,
        painter: QPainter,
        option,
        index: QModelIndex,
    ) -> None:
        """绘制右移后的内容（图标 + 文本），供测试子类观测传入 rect。"""
        super().paint(painter, option, index)
