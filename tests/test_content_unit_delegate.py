"""内容单元左侧色条 + 行首徽章 delegate 测试（UI合理性13/21，2026-08-04）。

覆盖：
- content_unit_badge_pixmap：按 glyph 渲染非空位图，缓存按字符区分
- content_unit_stripe_color：按配置返回色条颜色（关闭/非内容单元返回 None）
- content_rect_with_stripe_reserve：内容绘制区右移指定预留宽度
- delegate.paint：所有行统一右移；色条/徽章按配置开关绘制
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem, QTableView  # noqa: E402

from app import ui_constants as ui  # noqa: E402
from app.content_unit_delegate import (  # noqa: E402
    ContentUnitStripeDelegate,
    content_rect_with_stripe_reserve,
    content_unit_badge_pixmap,
    content_unit_stripe_color,
)
from app.content_unit_marker_config import ContentUnitMarkerConfig  # noqa: E402


def _entry(*, is_unit: bool) -> SimpleNamespace:
    unit = None if not is_unit else SimpleNamespace(id="u1", path="/mods/armor")
    return SimpleNamespace(
        name="armor",
        is_dir=True,
        content_unit=unit,
    )


def _config(
    *,
    icon_enabled: bool = True,
    glyph: str = ui.CONTENT_UNIT_MARKER,
    stripe_enabled: bool = True,
    stripe_color: str = ui.CONTENT_UNIT_STRIPE_COLOR,
) -> ContentUnitMarkerConfig:
    return ContentUnitMarkerConfig(
        icon_enabled=icon_enabled,
        icon_glyph=glyph,
        stripe_enabled=stripe_enabled,
        stripe_color=stripe_color,
    )


class _FakeModel(QAbstractTableModel):
    """单行单列模型：UserRole 返回测试 entry。"""

    def __init__(self, entry: SimpleNamespace) -> None:
        super().__init__()
        self._entry = entry

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else 1

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else 1

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:  # noqa: N802
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.UserRole:
            return self._entry
        if role == Qt.ItemDataRole.DisplayRole:
            return self._entry.name
        return None


def test_badge_pixmap_rendered(qapp) -> None:  # noqa: ANN001
    badge = content_unit_badge_pixmap("🔗")
    assert not badge.isNull()
    assert badge.width() == ui.CONTENT_UNIT_BADGE_SIZE
    assert badge.height() == ui.CONTENT_UNIT_BADGE_SIZE


def test_badge_pixmap_cached_by_glyph(qapp) -> None:  # noqa: ANN001
    assert content_unit_badge_pixmap("A") is content_unit_badge_pixmap("A")
    assert content_unit_badge_pixmap("A") is not content_unit_badge_pixmap("B")


def test_stripe_color_content_unit() -> None:
    assert content_unit_stripe_color(_config(), _entry(is_unit=True)) == QColor(
        ui.CONTENT_UNIT_STRIPE_COLOR
    )


def test_stripe_color_no_content_unit() -> None:
    assert content_unit_stripe_color(_config(), _entry(is_unit=False)) is None


def test_stripe_color_disabled() -> None:
    assert content_unit_stripe_color(_config(stripe_enabled=False), _entry(is_unit=True)) is None


def test_content_rect_shifted_right_by_reserve() -> None:
    shifted = content_rect_with_stripe_reserve(QRect(0, 0, 120, 24), 23)
    assert shifted == QRect(23, 0, 120 - 23, 24)


def test_content_rect_clamps_when_narrower_than_reserve() -> None:
    shifted = content_rect_with_stripe_reserve(QRect(0, 0, 4, 24), 23)
    assert shifted == QRect(23, 0, 0, 24)


def _paint(
    delegate: ContentUnitStripeDelegate,
    index: QModelIndex,
) -> QPixmap:
    view = QTableView()
    view.setModel(index.model())
    view.setItemDelegateForColumn(0, delegate)
    view.resize(200, 40)
    option = QStyleOptionViewItem()
    option.initFrom(view)
    option.rect = QRect(0, 0, 120, 24)
    option.state |= QStyle.StateFlag.State_Enabled
    pixmap = QPixmap(120, 24)
    pixmap.fill(Qt.GlobalColor.white)
    painter = QPainter(pixmap)
    try:
        delegate.paint(painter, option, index)
    finally:
        painter.end()
    return pixmap


def test_paint_draws_stripe_for_content_unit(qapp) -> None:  # noqa: ANN001
    delegate = ContentUnitStripeDelegate(config=_config())
    model = _FakeModel(_entry(is_unit=True))
    pixmap = _paint(delegate, model.index(0, 0))
    pixel = pixmap.toImage().pixelColor(1, 12)
    expected = QColor(ui.CONTENT_UNIT_STRIPE_COLOR)
    assert (pixel.red(), pixel.green(), pixel.blue()) == (
        expected.red(),
        expected.green(),
        expected.blue(),
    )


def test_paint_nothing_when_all_disabled(qapp) -> None:  # noqa: ANN001
    """双关配置下 delegate 不绘制任何标记（配置模型层面仍禁止双关）。"""
    delegate = ContentUnitStripeDelegate(config=_config(icon_enabled=False, stripe_enabled=False))
    model = _FakeModel(_entry(is_unit=True))
    pixmap = _paint(delegate, model.index(0, 0))
    assert pixmap.toImage().pixelColor(1, 12) == QColor(Qt.GlobalColor.white)


def test_paint_skips_stripe_for_plain_row(qapp) -> None:  # noqa: ANN001
    delegate = ContentUnitStripeDelegate(config=_config())
    model = _FakeModel(_entry(is_unit=False))
    pixmap = _paint(delegate, model.index(0, 0))
    assert pixmap.toImage().pixelColor(1, 12) == QColor(Qt.GlobalColor.white)


class _SpyDelegate(ContentUnitStripeDelegate):
    """记录 _paint_content 收到的 rect，验证所有行统一右移。"""

    def __init__(self, config: ContentUnitMarkerConfig) -> None:
        super().__init__(config=config)
        self.content_rects: list[QRect] = []

    def _paint_content(self, painter, option, index) -> None:  # noqa: ANN001
        self.content_rects.append(QRect(option.rect))


def test_all_rows_shifted_for_alignment(qapp) -> None:  # noqa: ANN001
    for is_unit in (True, False):
        config = _config()
        delegate = _SpyDelegate(config)
        model = _FakeModel(_entry(is_unit=is_unit))
        _paint(delegate, model.index(0, 0))
        assert delegate.content_rects
        assert delegate.content_rects[0] == content_rect_with_stripe_reserve(
            QRect(0, 0, 120, 24), config.reserved_width
        )
