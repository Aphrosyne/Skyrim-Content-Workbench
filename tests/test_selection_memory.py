"""SelectionMemory 测试（操作便捷性7，2026-08-03）。"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QTableView  # noqa: E402

from app.file_list_model import FileListModel  # noqa: E402
from app.selection_memory import SelectionMemory  # noqa: E402
from domain.models import FileEntry  # noqa: E402


def _entry(name: str, path: str) -> FileEntry:
    return FileEntry(
        name=name,
        path=path,
        is_dir=False,
        modified_at="2026-07-13T00:00:00Z",
    )


def _make_model_view() -> tuple[FileListModel, QTableView]:
    model = FileListModel()
    model.refresh(
        [
            _entry("a", "/dir/a"),
            _entry("b", "/dir/b"),
            _entry("c", "/dir/c"),
        ]
    )
    view = QTableView()
    view.setModel(model)
    view.resize(300, 300)
    return model, view


def test_record_and_restore_multiple(qapp) -> None:
    """记录多选并按路径恢复选中（含滚动）。"""
    model, view = _make_model_view()
    mem = SelectionMemory()
    mem.record("/dir", ["/dir/a", "/dir/c"])

    assert mem.restore("/dir", model, view)
    selected = {model.entry_at(r.row()).path for r in view.selectionModel().selectedRows()}
    assert selected == {"/dir/a", "/dir/c"}
    assert mem.remembered_paths("/dir") == ["/dir/a", "/dir/c"]


def test_restore_unknown_dir_or_missing_paths_returns_false(qapp) -> None:
    model, view = _make_model_view()
    mem = SelectionMemory()
    assert not mem.restore("/nope", model, view)

    mem.record("/dir", ["/dir/zzz"])  # 路径不存在
    assert not mem.restore("/dir", model, view)


def test_record_overwrites(qapp) -> None:
    mem = SelectionMemory()
    mem.record("/dir", ["/a"])
    mem.record("/dir", ["/b"])
    assert mem.remembered_paths("/dir") == ["/b"]
    assert mem.entries_count() == 1
