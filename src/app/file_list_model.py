"""文件列表 Qt Model（阶段 3 Task 2 重构为 TableModel）。

数据源为 FileEntry 列表（来自文件系统 + content_unit 表关联）。
内容单元不是可见性门槛——所有文件系统条目均可见。

4 列布局：
- 名称列（COL_NAME=0）：图标 + 名称 + 内容单元标记。
- 类型列（COL_TYPE=1）：文件夹 / 扩展名。
- 大小列（COL_SIZE=2）：字节数格式化；文件夹显示空字符串。
- 修改日期列（COL_MODIFIED=3）：ISO 8601 UTC 字符串。

排序：
- set_sort_key(key, ascending) 在 model 内部重新排序（不依赖 QSortFilterProxyModel）。
- 名称/类型列排序时文件夹优先在前；大小/日期列按值排序，文件夹（None）排到最后。
- 默认排序：文件夹优先 + 名称升序。

数据角色：
- DisplayRole：各列文本。
- DecorationRole：仅名称列返回 QIcon。
- ToolTipRole：名称列返回完整路径。
- UserRole：返回 FileEntry 对象（任意列均可）。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle

from app import ui_constants as ui
from domain.models import FileEntry

logger = logging.getLogger(__name__)

# 列索引常量
COL_NAME = 0
COL_TYPE = 1
COL_SIZE = 2
COL_MODIFIED = 3
COLUMN_COUNT = 4

# 排序键常量（不入 domain，UI 层局部使用）
SORT_NAME = "name"
SORT_TYPE = "type"
SORT_SIZE = "size"
SORT_MODIFIED = "modified"


def _display_name(entry: FileEntry) -> str:
    """构造名称列 DisplayRole 文本：名称 + 内容单元标记。"""
    unit = entry.content_unit
    if unit is None:
        return entry.name
    if unit.status == "organized":
        return f"{entry.name}{ui.CONTENT_UNIT_MARKER_ORGANIZED}"
    return f"{entry.name}{ui.CONTENT_UNIT_MARKER_UNORGANIZED}"


def _type_text(entry: FileEntry) -> str:
    """构造类型列文本：文件夹固定显示"文件夹"，文件显示扩展名（小写，无点）。"""
    if entry.is_dir:
        return ui.COL_TYPE_FOLDER
    suffix = ""
    if "." in entry.name:
        suffix = entry.name.rsplit(".", 1)[-1].lower()
    return suffix if suffix else ui.COL_TYPE_FILE


def _size_text(entry: FileEntry) -> str:
    """构造大小列文本：文件返回字节数；文件夹返回空字符串。"""
    if entry.is_dir or entry.size is None:
        return ""
    return str(entry.size)


def _modified_text(entry: FileEntry) -> str:
    """构造修改日期列文本：直接返回 modified_at（ISO 8601 UTC）。"""
    return entry.modified_at


def _sort_value_key(entry: FileEntry, sort_key: str) -> tuple:
    """返回纯值排序键（不含文件夹优先标志）。

    用于第一步排序，受 ascending 方向影响。
    文件夹的位置由第二步稳定排序处理，不受 ascending 影响。
    """
    if sort_key == SORT_NAME:
        return (entry.name.lower(), entry.name)
    if sort_key == SORT_TYPE:
        return (_type_text(entry).lower(), entry.name.lower())
    if sort_key == SORT_SIZE:
        size_val = entry.size if entry.size is not None else float("inf")
        return (size_val, entry.name.lower())
    if sort_key == SORT_MODIFIED:
        return (entry.modified_at, entry.name.lower())
    return (entry.name.lower(), entry.name)


class FileListModel(QAbstractTableModel):
    """文件列表 model（4 列 TableModel）。

    使用方式：
        model = FileListModel()
        model.refresh(entries)
        table_view.setModel(model)
        # 列头点击切换排序
        model.set_sort_key(SORT_NAME, ascending=True)
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[FileEntry] = []
        self._sort_key: str = SORT_NAME
        self._sort_ascending: bool = True
        # 图标缓存：避免 hover/paint 高频事件中反复调用 standardIcon（性能优化）
        self._dir_icon: QIcon | None = None
        self._file_icon: QIcon | None = None
        self._icons_initialized = False

    # --- QAbstractTableModel 必需方法 ---

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802 (Qt 命名)
        if parent is None:
            parent = QModelIndex()
        if parent.isValid():
            return 0
        return len(self._entries)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802 (Qt 命名)
        if parent is None:
            parent = QModelIndex()
        if parent.isValid():
            return 0
        return COLUMN_COUNT

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:  # noqa: N802 (Qt 命名)
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._entries):
            return None
        col = index.column()
        if col < 0 or col >= COLUMN_COUNT:
            return None

        entry = self._entries[row]

        if role == Qt.DisplayRole:
            if col == COL_NAME:
                return _display_name(entry)
            if col == COL_TYPE:
                return _type_text(entry)
            if col == COL_SIZE:
                return _size_text(entry)
            if col == COL_MODIFIED:
                return _modified_text(entry)
            return None
        if role == Qt.ToolTipRole and col == COL_NAME:
            return entry.path
        if role == Qt.UserRole:
            return entry
        if role == Qt.DecorationRole and col == COL_NAME:
            return self._icon_for(entry)
        return None

    def headerData(  # noqa: N802 (Qt 命名)
        self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole
    ) -> object:
        if role != Qt.DisplayRole:
            return None
        if orientation != Qt.Orientation.Horizontal:
            return None
        if section < 0 or section >= COLUMN_COUNT:
            return None
        return ui.FILE_LIST_COLUMN_HEADERS[section]

    # --- 刷新 ---

    def refresh(self, entries: list[FileEntry]) -> None:
        """重置列表并应用当前排序。"""
        self.beginResetModel()
        self._entries = list(entries)
        self._apply_sort()
        self.endResetModel()

    def set_sort_key(self, sort_key: str, ascending: bool) -> None:
        """切换排序键与方向，重新对现有条目排序。"""
        if sort_key not in (SORT_NAME, SORT_TYPE, SORT_SIZE, SORT_MODIFIED):
            return
        self.beginResetModel()
        self._sort_key = sort_key
        self._sort_ascending = ascending
        self._apply_sort()
        self.endResetModel()

    def current_sort_key(self) -> str:
        """返回当前排序键（供测试）。"""
        return self._sort_key

    def is_sort_ascending(self) -> bool:
        """返回当前是否升序（供测试）。"""
        return self._sort_ascending

    def _apply_sort(self) -> None:
        """对 self._entries 应用当前排序。

        两步排序（Python sort 稳定）：
        1. 按值排序（受 ascending 影响）。
        2. 稳定排序调整文件夹位置（不受 ascending 影响）：
           - 名称/类型列：文件夹优先在前。
           - 大小/日期列：文件夹排到最后（size=None 无法参与值比较）。
        """
        # 第一步：按值排序
        self._entries.sort(
            key=lambda e: _sort_value_key(e, self._sort_key),
            reverse=not self._sort_ascending,
        )
        # 第二步：稳定排序调整文件夹位置
        if self._sort_key in (SORT_NAME, SORT_TYPE):
            # 文件夹优先在前
            self._entries.sort(key=lambda e: not e.is_dir)
        else:
            # 大小/日期列：文件夹排到最后
            self._entries.sort(key=lambda e: e.is_dir)

    # --- 测试接口 ---

    def entry_at(self, row: int) -> FileEntry | None:
        """返回指定行的 FileEntry（供测试）。"""
        if row < 0 or row >= len(self._entries):
            return None
        return self._entries[row]

    def entry_count(self) -> int:
        """返回行数（供测试）。"""
        return len(self._entries)

    # --- 内部 ---

    def _icon_for(self, entry: FileEntry) -> QIcon | None:
        """返回 Qt 内置标准图标。使用缓存避免高频事件反复渲染（性能优化）。"""
        self._ensure_icons()
        return self._dir_icon if entry.is_dir else self._file_icon

    def _ensure_icons(self) -> None:
        """懒加载图标缓存。QApplication 未就绪时跳过，下次调用再尝试。"""
        if self._icons_initialized:
            return
        app = QApplication.instance()
        if app is None:
            return
        style = app.style()
        if style is None:
            return
        self._dir_icon = style.standardIcon(QStyle.SP_DirIcon)
        self._file_icon = style.standardIcon(QStyle.SP_FileIcon)
        self._icons_initialized = True
