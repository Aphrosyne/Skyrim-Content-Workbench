"""中栏内部拖拽目标高亮测试（操作便捷性2 调整版，2026-08-04）。"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, QPoint, QRect, QUrl  # noqa: E402
from PySide6.QtGui import QDragLeaveEvent, QPaintEvent  # noqa: E402

from app.content_views import _DragDropListView, _RubberBandTableView  # noqa: E402
from app.file_list_model import FileListModel  # noqa: E402
from domain.models import FileEntry  # noqa: E402


def _entry(name: str, is_dir: bool) -> FileEntry:
    return FileEntry(
        name=name,
        path=str(Path("/tmp") / name),
        is_dir=is_dir,
        modified_at="2026-08-04T00:00:00Z",
        size=None if is_dir else 10,
        content_unit=None,
    )


class _FakeDropEvent:
    """模拟同视图内部拖拽事件（source 固定为视图本身）。"""

    def __init__(self, source, pos: QPoint, urls: list[str]) -> None:
        self._source = source
        self._pos = pos
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(u) for u in urls])
        self._mime = mime
        self.accepted = False

    def source(self):
        return self._source

    def mimeData(self) -> QMimeData:
        return self._mime

    def pos(self) -> QPoint:
        return self._pos

    def acceptProposedAction(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.accepted = False


@pytest.fixture(params=[_RubberBandTableView, _DragDropListView])
def table_view(qapp, request):
    """参数化：列表视图与卡片视图共用同一套拖拽高亮逻辑。"""
    view = request.param()
    model = FileListModel()
    model.refresh([_entry("目标文件夹", True), _entry("a.txt", False)])
    view.setModel(model)
    view.resize(400, 300)
    view.show()
    qapp.processEvents()
    yield view
    view.close()


class TestDropHighlight:
    def test_drag_over_folder_highlights_row(self, qapp, table_view) -> None:
        """悬停文件夹行 → 高亮该行。"""
        view = table_view
        folder_idx = view.model().index(0, 0)
        event = _FakeDropEvent(view, view.visualRect(folder_idx).center(), ["/tmp/a.txt"])

        view.dragMoveEvent(event)

        assert event.accepted
        assert view._drop_highlight_row == 0  # noqa: SLF001

    def test_drag_over_file_clears_highlight(self, qapp, table_view) -> None:
        """悬停文件行 → 不高亮（清除）。"""
        view = table_view
        file_idx = view.model().index(1, 0)
        view._drop_highlight_row = 0  # noqa: SLF001 预置高亮

        event = _FakeDropEvent(view, view.visualRect(file_idx).center(), ["/tmp/a.txt"])
        view.dragMoveEvent(event)

        assert view._drop_highlight_row == -1  # noqa: SLF001

    def test_drag_leave_clears_highlight(self, qapp, table_view) -> None:
        """拖离视图 → 清除高亮。"""
        view = table_view
        view._drop_highlight_row = 0  # noqa: SLF001

        view.dragLeaveEvent(QDragLeaveEvent())

        assert view._drop_highlight_row == -1  # noqa: SLF001

    def test_drop_on_folder_calls_callback_and_clears(self, qapp, table_view) -> None:
        """放到文件夹行 → 回调目标 + 源路径，并清除高亮。"""
        view = table_view
        dropped: list[tuple[Path, list[Path]]] = []
        view.on_drop_to_folder = lambda target, srcs: dropped.append((target, srcs))
        folder_idx = view.model().index(0, 0)
        view._drop_highlight_row = 0  # noqa: SLF001

        event = _FakeDropEvent(view, view.visualRect(folder_idx).center(), ["/tmp/a.txt"])
        view.dropEvent(event)

        assert event.accepted
        assert dropped == [(Path("/tmp/目标文件夹"), [Path("/tmp/a.txt")])]
        assert view._drop_highlight_row == -1  # noqa: SLF001

    def test_drop_on_file_ignored_and_clears(self, qapp, table_view) -> None:
        """放到文件行 → 忽略，并清除高亮。"""
        view = table_view
        dropped: list[tuple[Path, list[Path]]] = []
        view.on_drop_to_folder = lambda target, srcs: dropped.append((target, srcs))
        file_idx = view.model().index(1, 0)
        view._drop_highlight_row = 1  # noqa: SLF001

        event = _FakeDropEvent(view, view.visualRect(file_idx).center(), ["/tmp/a.txt"])
        view.dropEvent(event)

        assert not event.accepted
        assert dropped == []
        assert view._drop_highlight_row == -1  # noqa: SLF001

    def test_paint_event_with_highlight_does_not_crash(self, qapp, table_view) -> None:
        """高亮状态下 paintEvent 正常（QPainter 正确释放）。"""
        view = table_view
        view._drop_highlight_row = 0  # noqa: SLF001

        view.paintEvent(QPaintEvent(QRect(0, 0, 100, 100)))
