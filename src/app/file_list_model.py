"""文件列表 Qt Model（roadmap Task 4 2026-07-13 设计修正）。

数据源为 FileEntry 列表（来自文件系统 + content_unit 表关联）。
内容单元不是可见性门槛——所有文件系统条目均可见。

数据角色：
- DisplayRole：name + 内容单元标记（[内容单元 ✓] / [内容单元] / 无标记）。
- ToolTipRole：完整路径。
- UserRole：FileEntry 对象。
- DecorationRole：Qt 内置标准图标（文件夹 / 文件）。

refresh(entries) 重置列表。本 Task 为只读展示，不实现编辑。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle

from app import ui_constants as ui
from domain.models import FileEntry

logger = logging.getLogger(__name__)


def _display_text(entry: FileEntry) -> str:
    """构造 DisplayRole 文本：名称 + 内容单元标记。"""
    unit = entry.content_unit
    if unit is None:
        return entry.name
    if unit.status == "organized":
        return f"{entry.name}{ui.CONTENT_UNIT_MARKER_ORGANIZED}"
    return f"{entry.name}{ui.CONTENT_UNIT_MARKER_UNORGANIZED}"


class FileListModel(QAbstractListModel):
    """文件列表 model。

    使用方式：
        model = FileListModel()
        model.refresh(entries)
        list_view.setModel(model)
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[FileEntry] = []
        # 图标缓存：避免 hover/paint 高频事件中反复调用 standardIcon（性能优化）
        self._dir_icon: QIcon | None = None
        self._file_icon: QIcon | None = None
        self._icons_initialized = False

    # --- QAbstractListModel 必需方法 ---

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802 (Qt 命名)
        if parent is None:
            parent = QModelIndex()
        if parent.isValid():
            return 0
        return len(self._entries)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:  # noqa: N802 (Qt 命名)
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._entries):
            return None

        entry = self._entries[row]

        if role == Qt.DisplayRole:
            return _display_text(entry)
        if role == Qt.ToolTipRole:
            return entry.path
        if role == Qt.UserRole:
            return entry
        if role == Qt.DecorationRole:
            return self._icon_for(entry)
        return None

    # --- 刷新 ---

    def refresh(self, entries: list[FileEntry]) -> None:
        """重置列表。"""
        self.beginResetModel()
        self._entries = list(entries)
        self.endResetModel()

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
