"""内容单元左侧色条 + 行首徽章 delegate 测试（UI合理性13，2026-08-04）。

覆盖：
- content_unit_stripe_color：内容单元行返回色条颜色，非内容单元返回 None
- content_unit_badge_pixmap：渲染出非空、尺寸正确的 🔗 徽章位图
- content_rect_with_stripe_reserve：内容绘制区整体右移预留宽度（色条不覆盖图标）
- delegate.paint：所有行内容统一右移（对齐），内容单元行额外绘制淡紫色竖条
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


def _entry(*, is_unit: bool) -> SimpleNamespace:
    unit = None if not is_unit else SimpleNamespace(id="u1", path="/mods/armor")
    return SimpleNamespace(
        name="armor",
        is_dir=True,
        content_unit=unit,
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


def test_stripe_color_content_unit() -> None:
    assert content_unit_stripe_color(_entry(is_unit=True)) == QColor(ui.CONTENT_UNIT_STRIPE_COLOR)


def test_stripe_color_no_content_unit() -> None:
    assert content_unit_stripe_color(_entry(is_unit=False)) is None


def test_content_rect_shifted_right_by_reserve() -> None:
    shifted = content_rect_with_stripe_reserve(QRect(0, 0, 120, 24))
    assert shifted == QRect(
        ui.CONTENT_UNIT_STRIPE_RESERVED_WIDTH,
        0,
        120 - ui.CONTENT_UNIT_STRIPE_RESERVED_WIDTH,
        24,
    )


def test_content_rect_clamps_when_narrower_than_reserve() -> None:
    shifted = content_rect_with_stripe_reserve(QRect(0, 0, 4, 24))
    assert shifted == QRect(ui.CONTENT_UNIT_STRIPE_RESERVED_WIDTH, 0, 0, 24)


def _paint(delegate: ContentUnitStripeDelegate, index: QModelIndex) -> QPixmap:
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
    delegate = ContentUnitStripeDelegate()
    model = _FakeModel(_entry(is_unit=True))
    index = model.index(0, 0)
    pixmap = _paint(delegate, index)
    pixel = pixmap.toImage().pixelColor(1, 12)
    expected = QColor(ui.CONTENT_UNIT_STRIPE_COLOR)
    assert (pixel.red(), pixel.green(), pixel.blue()) == (
        expected.red(),
        expected.green(),
        expected.blue(),
    )


def test_paint_skips_stripe_for_plain_row(qapp) -> None:  # noqa: ANN001
    delegate = ContentUnitStripeDelegate()
    model = _FakeModel(_entry(is_unit=False))
    index = model.index(0, 0)
    pixmap = _paint(delegate, index)
    assert pixmap.toImage().pixelColor(1, 12) == QColor(Qt.GlobalColor.white)


class _SpyDelegate(ContentUnitStripeDelegate):
    """记录 _paint_content 收到的 rect，验证所有行统一右移。"""

    def __init__(self) -> None:
        super().__init__()
        self.content_rects: list[QRect] = []

    def _paint_content(self, painter, option, index) -> None:  # noqa: ANN001
        self.content_rects.append(QRect(option.rect))


def test_all_rows_shifted_for_alignment(qapp) -> None:  # noqa: ANN001
    for is_unit in (True, False):
        delegate = _SpyDelegate()
        model = _FakeModel(_entry(is_unit=is_unit))
        index = model.index(0, 0)
        _paint(delegate, index)
        assert delegate.content_rects
        assert delegate.content_rects[0] == content_rect_with_stripe_reserve(QRect(0, 0, 120, 24))


def test_badge_pixmap_rendered(qapp) -> None:  # noqa: ANN001
    badge = content_unit_badge_pixmap()
    assert not badge.isNull()
    assert badge.width() == ui.CONTENT_UNIT_BADGE_SIZE
    assert badge.height() == ui.CONTENT_UNIT_BADGE_SIZE
