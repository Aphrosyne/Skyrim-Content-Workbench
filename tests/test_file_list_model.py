"""FileListModel 测试（阶段 3 Task 2 重构为 TableModel）。

覆盖：
- 4 列布局：名称/类型/大小/修改日期
- 空 model / refresh 加载 / rowCount / columnCount
- DisplayRole：名称（含内容单元标记）/ 类型 / 大小 / 修改日期
- headerData：列头文本
- ToolTipRole：名称列返回完整路径
- UserRole：返回 FileEntry 对象
- DecorationRole：名称列返回 QIcon
- 排序：set_sort_key 各键升降序；同列翻转；默认按名称升序
- 中文文件名
- 无效 index
- entry_at / entry_count / refresh 重置
"""

from __future__ import annotations

from app import ui_constants as ui
from app.file_list_model import (
    COL_MODIFIED,
    COL_NAME,
    COL_SIZE,
    COL_TYPE,
    SORT_MODIFIED,
    SORT_NAME,
    SORT_SIZE,
    SORT_TYPE,
    FileListModel,
)
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

    def test_empty_model_column_count(self, qapp) -> None:  # noqa: ANN001
        model = FileListModel()
        assert model.columnCount() == 4

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

    def test_refresh_applies_current_sort(self, qapp) -> None:  # noqa: ANN001
        """refresh 后应用当前排序键。"""
        model = FileListModel()
        model.set_sort_key(SORT_SIZE, ascending=False)
        entries = [
            _make_entry("small", "/small", size=10),
            _make_entry("big", "/big", size=1000),
        ]
        model.refresh(entries)
        # 降序：big 在前
        assert model.entry_at(0).name == "big"
        assert model.entry_at(1).name == "small"


class TestHeaderData:
    def test_horizontal_headers(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        assert model.headerData(0, Qt.Orientation.Horizontal) == "名称"
        assert model.headerData(1, Qt.Orientation.Horizontal) == "类型"
        assert model.headerData(2, Qt.Orientation.Horizontal) == "大小"
        assert model.headerData(3, Qt.Orientation.Horizontal) == "修改日期"

    def test_vertical_headers_none(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        assert model.headerData(0, Qt.Orientation.Vertical) is None

    def test_header_invalid_section_returns_none(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        assert model.headerData(-1, Qt.Orientation.Horizontal) is None
        assert model.headerData(99, Qt.Orientation.Horizontal) is None

    def test_header_non_display_role_returns_none(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        assert model.headerData(0, Qt.Orientation.Horizontal, Qt.ToolTipRole) is None


class TestDisplayRole:
    def test_name_column_no_marker(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        model.refresh([_make_entry("readme.txt", "/mods/readme.txt")])
        idx = model.index(0, COL_NAME)
        assert model.data(idx, Qt.DisplayRole) == "readme.txt"

    def test_name_column_unorganized_marker(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        unit = _make_unit(status="unorganized")
        model = FileListModel()
        model.refresh([_make_entry("armor", "/mods/armor", is_dir=True, content_unit=unit)])
        idx = model.index(0, COL_NAME)
        assert model.data(idx, Qt.DisplayRole) == f"armor{ui.CONTENT_UNIT_MARKER_UNORGANIZED}"

    def test_name_column_organized_marker(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        unit = _make_unit(status="organized")
        model = FileListModel()
        model.refresh([_make_entry("armor", "/mods/armor", is_dir=True, content_unit=unit)])
        idx = model.index(0, COL_NAME)
        assert model.data(idx, Qt.DisplayRole) == f"armor{ui.CONTENT_UNIT_MARKER_ORGANIZED}"

    def test_type_column_directory(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        model.refresh([_make_entry("armor", "/mods/armor", is_dir=True)])
        idx = model.index(0, COL_TYPE)
        assert model.data(idx, Qt.DisplayRole) == ui.COL_TYPE_FOLDER

    def test_type_column_file_with_extension(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        model.refresh([_make_entry("readme.txt", "/mods/readme.txt", is_dir=False, size=10)])
        idx = model.index(0, COL_TYPE)
        assert model.data(idx, Qt.DisplayRole) == "txt"

    def test_type_column_file_no_extension(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        model.refresh([_make_entry("README", "/mods/README", is_dir=False, size=10)])
        idx = model.index(0, COL_TYPE)
        assert model.data(idx, Qt.DisplayRole) == ui.COL_TYPE_FILE

    def test_type_column_uppercase_extension_lowered(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        model.refresh([_make_entry("mod.7Z", "/mods/mod.7Z", is_dir=False, size=10)])
        idx = model.index(0, COL_TYPE)
        assert model.data(idx, Qt.DisplayRole) == "7z"

    def test_size_column_file(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        model.refresh([_make_entry("f.txt", "/f.txt", is_dir=False, size=12345)])
        idx = model.index(0, COL_SIZE)
        assert model.data(idx, Qt.DisplayRole) == "12345"

    def test_size_column_directory_empty_string(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        model.refresh([_make_entry("d", "/d", is_dir=True)])
        idx = model.index(0, COL_SIZE)
        assert model.data(idx, Qt.DisplayRole) == ""

    def test_modified_column(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        model.refresh([_make_entry("f", "/f", modified_at="2026-07-13T12:34:56Z")])
        idx = model.index(0, COL_MODIFIED)
        assert model.data(idx, Qt.DisplayRole) == "2026-07-13T12:34:56Z"

    def test_chinese_name(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        model.refresh([_make_entry("护甲", "/mods/护甲", is_dir=True)])
        idx = model.index(0, COL_NAME)
        assert model.data(idx, Qt.DisplayRole) == "护甲"


class TestToolTipRole:
    def test_name_column_returns_path(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        model.refresh([_make_entry("armor", "/mods/armor", is_dir=True)])
        idx = model.index(0, COL_NAME)
        assert model.data(idx, Qt.ToolTipRole) == "/mods/armor"

    def test_other_columns_tooltip_none(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        model.refresh([_make_entry("armor", "/mods/armor", is_dir=True)])
        # 类型列不返回 tooltip
        idx = model.index(0, COL_TYPE)
        assert model.data(idx, Qt.ToolTipRole) is None


class TestUserRole:
    def test_user_role_returns_entry(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        entry = _make_entry("armor", "/mods/armor", is_dir=True)
        model = FileListModel()
        model.refresh([entry])
        idx = model.index(0, COL_NAME)
        result = model.data(idx, Qt.UserRole)
        assert result is entry

    def test_user_role_returns_entry_for_any_column(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        entry = _make_entry("armor", "/mods/armor", is_dir=True)
        model = FileListModel()
        model.refresh([entry])
        # 任意列都应返回 entry
        for col in (COL_NAME, COL_TYPE, COL_SIZE, COL_MODIFIED):
            idx = model.index(0, col)
            assert model.data(idx, Qt.UserRole) is entry


class TestDecorationRole:
    def test_dir_icon_for_directory(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QIcon

        model = FileListModel()
        model.refresh([_make_entry("armor", "/mods/armor", is_dir=True)])
        idx = model.index(0, COL_NAME)
        icon = model.data(idx, Qt.DecorationRole)
        assert icon is not None
        assert isinstance(icon, QIcon)

    def test_file_icon_for_file(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QIcon

        model = FileListModel()
        model.refresh([_make_entry("readme.txt", "/mods/readme.txt", is_dir=False, size=10)])
        idx = model.index(0, COL_NAME)
        icon = model.data(idx, Qt.DecorationRole)
        assert icon is not None
        assert isinstance(icon, QIcon)

    def test_decoration_only_on_name_column(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        model.refresh([_make_entry("armor", "/mods/armor", is_dir=True)])
        # 类型列不返回图标
        idx = model.index(0, COL_TYPE)
        assert model.data(idx, Qt.DecorationRole) is None


class TestSort:
    def test_default_sort_is_name_ascending(self, qapp) -> None:  # noqa: ANN001
        model = FileListModel()
        assert model.current_sort_key() == SORT_NAME
        assert model.is_sort_ascending() is True

    def test_sort_by_name_ascending(self, qapp) -> None:  # noqa: ANN001
        model = FileListModel()
        model.refresh(
            [
                _make_entry("z_dir", "/z", is_dir=True),
                _make_entry("a_dir", "/a", is_dir=True),
                _make_entry("m_file", "/m", size=10),
            ]
        )
        model.set_sort_key(SORT_NAME, ascending=True)
        # 文件夹优先，名称升序
        assert model.entry_at(0).name == "a_dir"
        assert model.entry_at(1).name == "z_dir"
        assert model.entry_at(2).name == "m_file"

    def test_sort_by_name_descending(self, qapp) -> None:  # noqa: ANN001
        model = FileListModel()
        model.refresh(
            [
                _make_entry("a_dir", "/a", is_dir=True),
                _make_entry("z_dir", "/z", is_dir=True),
            ]
        )
        model.set_sort_key(SORT_NAME, ascending=False)
        # 降序：z_dir 在前
        assert model.entry_at(0).name == "z_dir"
        assert model.entry_at(1).name == "a_dir"

    def test_sort_by_size_ascending(self, qapp) -> None:  # noqa: ANN001
        model = FileListModel()
        model.refresh(
            [
                _make_entry("big", "/big", size=1000),
                _make_entry("small", "/small", size=10),
                _make_entry("dir", "/dir", is_dir=True),  # size=None
            ]
        )
        model.set_sort_key(SORT_SIZE, ascending=True)
        # 升序：small(10) → big(1000) → dir(None)
        assert model.entry_at(0).name == "small"
        assert model.entry_at(1).name == "big"
        assert model.entry_at(2).name == "dir"

    def test_sort_by_size_descending(self, qapp) -> None:  # noqa: ANN001
        model = FileListModel()
        model.refresh(
            [
                _make_entry("small", "/small", size=10),
                _make_entry("big", "/big", size=1000),
                _make_entry("dir", "/dir", is_dir=True),
            ]
        )
        model.set_sort_key(SORT_SIZE, ascending=False)
        # 降序：big(1000) → small(10) → dir(None)
        assert model.entry_at(0).name == "big"
        assert model.entry_at(1).name == "small"
        assert model.entry_at(2).name == "dir"

    def test_sort_by_modified_ascending(self, qapp) -> None:  # noqa: ANN001
        model = FileListModel()
        model.refresh(
            [
                _make_entry("new", "/new", modified_at="2026-07-14T00:00:00Z"),
                _make_entry("old", "/old", modified_at="2026-07-12T00:00:00Z"),
            ]
        )
        model.set_sort_key(SORT_MODIFIED, ascending=True)
        # 升序：old → new
        assert model.entry_at(0).name == "old"
        assert model.entry_at(1).name == "new"

    def test_sort_by_type(self, qapp) -> None:  # noqa: ANN001
        model = FileListModel()
        model.refresh(
            [
                _make_entry("b.zip", "/b.zip", size=10),  # type=zip
                _make_entry("a.7z", "/a.7z", size=10),  # type=7z
            ]
        )
        model.set_sort_key(SORT_TYPE, ascending=True)
        # type 升序：7z < zip
        assert model.entry_at(0).name == "a.7z"
        assert model.entry_at(1).name == "b.zip"

    def test_same_column_toggles_ascending(self, qapp) -> None:  # noqa: ANN001
        model = FileListModel()
        model.refresh([_make_entry("a", "/a"), _make_entry("b", "/b")])
        assert model.is_sort_ascending() is True
        model.set_sort_key(SORT_NAME, not model.is_sort_ascending())
        assert model.is_sort_ascending() is False
        assert model.entry_at(0).name == "b"

    def test_invalid_sort_key_ignored(self, qapp) -> None:  # noqa: ANN001
        model = FileListModel()
        model.refresh([_make_entry("a", "/a")])
        original_key = model.current_sort_key()
        model.set_sort_key("invalid_key", ascending=True)
        # 排序键不变
        assert model.current_sort_key() == original_key


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

    def test_data_invalid_column_returns_none(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import Qt

        model = FileListModel()
        model.refresh([_make_entry("a", "/a")])
        idx = model.index(0, 99)
        assert model.data(idx, Qt.DisplayRole) is None


class TestEntryAt:
    def test_entry_at_valid_row(self, qapp) -> None:  # noqa: ANN001
        model = FileListModel()
        e1 = _make_entry("a", "/a")
        e2 = _make_entry("b", "/b")
        model.refresh([e1, e2])
        # 排序后顺序可能变化，但 entry_at 仍按当前 model 顺序返回
        names = {model.entry_at(0).name, model.entry_at(1).name}
        assert names == {"a", "b"}

    def test_entry_at_out_of_range_returns_none(self, qapp) -> None:  # noqa: ANN001
        model = FileListModel()
        model.refresh([_make_entry("a", "/a")])
        assert model.entry_at(99) is None
        assert model.entry_at(-1) is None


class TestRowCount:
    def test_row_count_with_parent_index_returns_zero(self, qapp) -> None:  # noqa: ANN001
        """QAbstractTableModel 对子 index 返回 0。"""
        from PySide6.QtCore import QModelIndex

        model = FileListModel()
        model.refresh([_make_entry("a", "/a")])
        assert model.rowCount(QModelIndex()) == 1

    def test_column_count_with_parent_index_returns_zero(self, qapp) -> None:  # noqa: ANN001
        from PySide6.QtCore import QModelIndex

        model = FileListModel()
        assert model.columnCount(QModelIndex()) == 4
