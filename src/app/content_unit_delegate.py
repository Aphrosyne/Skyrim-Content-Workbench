"""内容单元行左侧色条 + 行首徽章 delegate（UI合理性13，2026-08-04）。

列表视图名称列专用 delegate：
- 所有行（含非内容单元）内容整体右移 CONTENT_UNIT_STRIPE_RESERVED_WIDTH
  像素，保证图标/文本行与行对齐；先铺满整格背景保证选中态连续。
- 内容单元行在最左侧预留区绘制淡紫色竖条 + 🔗 位图徽章。
- 🔗 不拼进 DisplayRole 文本：emoji 字体回退会抬高行高度量（实测
  "armor" 15.23px vs "🔗 armor" 15.98px），导致文字垂直偏移约 1px；
  徽章改为 QPixmap 固定绘制，文本保持纯文件名。
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from app import ui_constants as ui

_BADGE_PIXMAP: QPixmap | None = None


def content_unit_badge_pixmap() -> QPixmap:
    """渲染并缓存 🔗 徽章位图（emoji 不进文本，避免行高度量变化）。"""
    global _BADGE_PIXMAP
    if _BADGE_PIXMAP is None:
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
            ui.CONTENT_UNIT_MARKER,
        )
        painter.end()
        _BADGE_PIXMAP = pixmap
    return _BADGE_PIXMAP


def content_rect_with_stripe_reserve(rect: QRect) -> QRect:
    """内容绘制区域：整体右移预留宽度，色条/徽章独占最左侧（供测试）。"""
    reserve = ui.CONTENT_UNIT_STRIPE_RESERVED_WIDTH
    return QRect(
        rect.left() + reserve,
        rect.top(),
        max(0, rect.width() - reserve),
        rect.height(),
    )


def content_unit_stripe_color(entry: object) -> QColor | None:
    """返回内容单元行的左侧色条颜色，非内容单元返回 None（供测试）。

    entry 为 domain.models.FileEntry（或等价带 content_unit 属性的对象），
    通过 UserRole 从模型取回。
    """
    content_unit = getattr(entry, "content_unit", None)
    if content_unit is None:
        return None
    return QColor(ui.CONTENT_UNIT_STRIPE_COLOR)


class ContentUnitStripeDelegate(QStyledItemDelegate):
    """列表视图名称列 delegate：内容单元行绘制左侧色条 + 行首徽章。"""

    def paint(  # noqa: N802 (Qt 命名)
        self,
        painter: QPainter,
        option,
        index: QModelIndex,
    ) -> None:
        entry = index.data(Qt.ItemDataRole.UserRole)
        color = content_unit_stripe_color(entry)
        # 1) 先铺满整格背景（含选中/悬停态），避免右侧内容右移后预留区出现缺口
        style = option.widget.style() if option.widget is not None else QApplication.style()
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem,
            option,
            painter,
            option.widget,
        )
        # 2) 内容单元行在预留区绘制色条 + 🔗 徽章
        if color is not None:
            painter.save()
            painter.fillRect(
                option.rect.left(),
                option.rect.top(),
                ui.CONTENT_UNIT_STRIPE_WIDTH,
                option.rect.height(),
                color,
            )
            painter.restore()
            badge = content_unit_badge_pixmap()
            badge_x = (
                option.rect.left()
                + ui.CONTENT_UNIT_STRIPE_WIDTH
                + ui.CONTENT_UNIT_BADGE_LEADING_GAP
            )
            badge_y = option.rect.top() + (option.rect.height() - badge.height()) // 2
            painter.drawPixmap(badge_x, badge_y, badge)
        # 3) 所有行内容整体右移预留宽度，色条不覆盖图标且行与行对齐
        shifted = QStyleOptionViewItem(option)
        shifted.rect = content_rect_with_stripe_reserve(option.rect)
        self._paint_content(painter, shifted, index)

    def _paint_content(
        self,
        painter: QPainter,
        option,
        index: QModelIndex,
    ) -> None:
        """绘制右移后的内容（图标 + 文本），供测试子类观测传入 rect。"""
        super().paint(painter, option, index)
