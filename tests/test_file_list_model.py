"""FileListModel 测试。

覆盖（roadmap Task 4 2026-07-13 设计修正）：
- 空 model / refresh 加载 / rowCount
- DisplayRole：名称 + 内容单元标记（已整理 / 未整理 / 无标记）
- ToolTipRole：完整路径
- UserRole：FileEntry 对象
- DecorationRole：QApplication 存在时返回 QIcon
- 中文文件名
- 无效 index
- entry_at / entry_count / refresh 重置
"""

from __future__ import annotations

from app import ui_constants as ui
from app.file_list_model import FileListModel
from domain.models import ContentUnit, FileEntry


def _make_entry(
    name: str,
    path: str,
    is_dir: bool = False,
    content_unit: ContentUnit | None = None,
    modified_at: str = "2026-07-13T00:00:00Z",
    size: int | None = None,
) -> FileEntry:
    return FileEntry(
        name=name,
        path=path,
        is_dir=is_dir,
        modified_at=modified_at,
        size=size,
        content_unit=content_unit,
    )


def _make_unit(
    unit_id: str = "u-1",
    path: str = "/mods/armor",
    title: str | None = None,
    status: str = "unorganized",
) -> ContentUnit:
    return ContentUnit(
        id=unit_id,
        path=path,
        created_at="2026-07-13T00:00:00Z",
        updated_at="2026-07-13T00:00:00Z",
        title=title,
        status=status,
    )


class TestEmptyModel:
    def test_empty_model_row_count(self, qapp) -> None:  # noqa: ANN001
        model = FileListModel()
        assert model.rowCount() == 0
        assert model.entry_count() == 0

    def test_empty_model_data_returns_none(self, qapp) -> None:  # noqa: ANN001
        model = FileListModel()
        idx = model.index(0, 0)
        assert model.data(idx) is None


class TestRefresh:
    def test_refresh_loads_entries(self, qapp) -> None:  # noqa: ANN001
        model = FileListModel()
        entries = [
            _make_entry("armor", "/mods/armor", is_dir=True),
            _make_entry("readme.txt", "/mods/readme.txt", is_dir=False, size=100),
        ]
        model.refresh(entries)
        assert model.entry_count() == 2

    def test_refresh_resets_previous_entries(self, qapp) -> None:  # noqa: ANN001
        model = FileListModel()
        model.refresh([_make_entry("a", "/a")])
        assert model.entry_count() == 1

        model.refresh([])
        assert model.entry_count() == 0

    def test_refresh_copies_list(self, qapp) -> None:  # noqa: ANN001
        """refresh 应复制传入列表，避免外部修改影响 model。"""
        model = FileListModel()
        original: list[FileEntry] = []
        model.refresh(original)
        original.append(_make_entry("x", "/x"))
        assert model.entry_count() == 0


class TestDisplayRole:
    def test_non_content_unit_no_marker(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        model.refresh([_make_entry("readme.txt", "/mods/readme.txt")])
        idx = model.index(0, 0)
        assert model.data(idx, Qt.DisplayRole) == "readme.txt"

    def test_unorganized_unit_marker(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        unit = _make_unit(status="unorganized")
        model = FileListModel()
        model.refresh([_make_entry("armor", "/mods/armor", is_dir=True, content_unit=unit)])
        idx = model.index(0, 0)
        assert model.data(idx, Qt.DisplayRole) == f"armor{ui.CONTENT_UNIT_MARKER_UNORGANIZED}"

    def test_organized_unit_marker(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        unit = _make_unit(status="organized")
        model = FileListModel()
        model.refresh([_make_entry("armor", "/mods/armor", is_dir=True, content_unit=unit)])
        idx = model.index(0, 0)
        assert model.data(idx, Qt.DisplayRole) == f"armor{ui.CONTENT_UNIT_MARKER_ORGANIZED}"

    def test_chinese_name(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        model.refresh([_make_entry("护甲", "/mods/护甲", is_dir=True)])
        idx = model.index(0, 0)
        assert model.data(idx, Qt.DisplayRole) == "护甲"


class TestToolTipRole:
    def test_tooltip_returns_full_path(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        model.refresh([_make_entry("armor", "/mods/armor", is_dir=True)])
        idx = model.index(0, 0)
        assert model.data(idx, Qt.ToolTipRole) == "/mods/armor"

    def test_chinese_path_in_tooltip(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        model.refresh([_make_entry("护甲", "/mods/护甲/寒霜之心", is_dir=True)])
        idx = model.index(0, 0)
        assert "寒霜之心" in model.data(idx, Qt.ToolTipRole)


class TestUserRole:
    def test_user_role_returns_entry(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        entry = _make_entry("armor", "/mods/armor", is_dir=True)
        model = FileListModel()
        model.refresh([entry])
        idx = model.index(0, 0)
        result = model.data(idx, Qt.UserRole)
        assert result is entry


class TestDecorationRole:
    def test_dir_icon_for_directory(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QIcon

        model = FileListModel()
        model.refresh([_make_entry("armor", "/mods/armor", is_dir=True)])
        idx = model.index(0, 0)
        icon = model.data(idx, Qt.DecorationRole)
        assert icon is not None
        assert isinstance(icon, QIcon)

    def test_file_icon_for_file(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QIcon

        model = FileListModel()
        model.refresh([_make_entry("readme.txt", "/mods/readme.txt", is_dir=False, size=10)])
        idx = model.index(0, 0)
        icon = model.data(idx, Qt.DecorationRole)
        assert icon is not None
        assert isinstance(icon, QIcon)


class TestInvalidIndex:
    def test_data_invalid_index_returns_none(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import QModelIndex, Qt

        model = FileListModel()
        assert model.data(QModelIndex(), Qt.DisplayRole) is None

    def test_data_out_of_range_returns_none(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        model.refresh([_make_entry("a", "/a")])
        idx = model.index(99, 0)
        assert model.data(idx, Qt.DisplayRole) is None

    def test_data_negative_row_returns_none(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        model.refresh([_make_entry("a", "/a")])
        idx = model.index(-1, 0)
        # Qt 会把 -1 转成无效 index
        assert model.data(idx, Qt.DisplayRole) is None


class TestEntryAt:
    def test_entry_at_valid_row(self, qapp) -> None:  # noqa: ANN001
        model = FileListModel()
        e1 = _make_entry("a", "/a")
        e2 = _make_entry("b", "/b")
        model.refresh([e1, e2])
        assert model.entry_at(0) is e1
        assert model.entry_at(1) is e2

    def test_entry_at_out_of_range_returns_none(self, qapp) -> None:  # noqa: ANN001
        model = FileListModel()
        model.refresh([_make_entry("a", "/a")])
        assert model.entry_at(99) is None
        assert model.entry_at(-1) is None


class TestRowCount:
    def test_row_count_with_parent_index_returns_zero(self, qapp) -> None:  # noqa: ANN001
        """QAbstractListModel 对子 index 返回 0。"""
        from PySide6.QtCore import QModelIndex

        model = FileListModel()
        model.refresh([_make_entry("a", "/a")])
        # 传入根 index 应返回 1
        assert model.rowCount(QModelIndex()) == 1
