"""装配面板 UI（阶段 3 Task 4）。

spec §7.4：创建 Mod 组后自动绑定，显示当前 Mod 组文件夹内容，
支持手动重命名预览图。

设计要点（UX 重构 Phase 1 Task 1 Commit 3 调整）：
- 不自动重命名图片。加入装配保留原文件名。
- 手动重命名：右键图片 → "重命名为与 Mod 组同名"。
- 「移除文件」功能已移除（L2 决策）：Task 4 将由剪切/移动到……替代。
- 装配面板始终可见，未绑定时显示空状态占位（「无固定内容」）。
- 装配面板绑定当前 Mod 组，切换 Mod 组时刷新内容。

交互方式：
- 中栏文件列表右键菜单「加入装配」，由 MainWindow._on_assembly_add_file 触发。
- 装配面板本身只负责显示 + 右键重命名，不再接收拖拽。
- 创建 Mod 组成功后自动绑定装配面板（K1 决策）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListView,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from application.assembly_service import AssemblyService, is_image_file
from application.errors import ContentUnitNotFoundError
from domain.models import ContentUnit, FileEntry

logger = logging.getLogger(__name__)


class AssemblyListModel(QAbstractListModel):
    """装配面板文件列表 model。

    数据源为 FileEntry 列表（来自 AssemblyService.list_mod_group_files）。
    与 FileListModel 区别：装配面板只显示文件名 + 类型图标，不需要 4 列表格。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries: list[FileEntry] = []
        self._dir_icon: QIcon | None = None
        self._file_icon: QIcon | None = None
        self._icons_initialized = False

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
            return entry.name
        if role == Qt.ToolTipRole:
            return entry.path
        if role == Qt.UserRole:
            return entry
        if role == Qt.DecorationRole:
            return self._icon_for(entry)
        return None

    def refresh(self, entries: list[FileEntry]) -> None:
        """重置列表。"""
        self.beginResetModel()
        self._entries = list(entries)
        self.endResetModel()

    def entry_at(self, row: int) -> FileEntry | None:
        """返回指定行的 FileEntry（供测试）。"""
        if row < 0 or row >= len(self._entries):
            return None
        return self._entries[row]

    def entry_count(self) -> int:
        """返回行数（供测试）。"""
        return len(self._entries)

    def _icon_for(self, entry: FileEntry) -> QIcon | None:
        self._ensure_icons()
        return self._dir_icon if entry.is_dir else self._file_icon

    def _ensure_icons(self) -> None:
        """懒加载图标缓存。"""
        if self._icons_initialized:
            return
        from PySide6.QtWidgets import QApplication, QStyle

        app = QApplication.instance()
        if app is None:
            return
        style = app.style()
        if style is None:
            return
        self._dir_icon = style.standardIcon(QStyle.SP_DirIcon)
        self._file_icon = style.standardIcon(QStyle.SP_FileIcon)
        self._icons_initialized = True


class AssemblyPanel(QWidget):
    """装配面板：显示 Mod 组文件夹内容，支持右键重命名预览图。

    信号回调（由 MainWindow 注入）：
    - on_cover_renamed(image_path)：右键重命名触发，MainWindow 调用 rename_as_cover。
    - on_panel_closed()：用户点击关闭按钮，MainWindow 隐藏装配面板。

    使用回调而非直接调用 AssemblyService，便于 MainWindow 统一处理刷新逻辑
    （装配后需同步刷新装配面板 + 当前目录列表 + 提交事务）。

    注：「加入装配」由 MainWindow 中栏右键菜单触发，不经过本面板回调。
    UX 重构 Phase 1 Task 1 Commit 3：「移除文件」功能已移除（L2 决策）。
    """

    def __init__(
        self,
        assembly_service: AssemblyService,
        on_cover_renamed: Callable[[Path], None] | None = None,
        on_panel_closed: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = assembly_service
        self._on_cover_renamed = on_cover_renamed
        self._on_panel_closed = on_panel_closed
        self._current_unit: ContentUnit | None = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # 标题栏
        title_row = QHBoxLayout()
        self._title_label = QLabel(ui.ASSEMBLY_PANEL_TITLE)
        title_row.addWidget(self._title_label)
        title_row.addStretch(1)
        self._close_button = QPushButton("×")
        self._close_button.setFixedSize(24, 24)
        self._close_button.setToolTip(ui.ASSEMBLY_PANEL_CLOSE_BUTTON)
        self._close_button.clicked.connect(self._on_close_clicked)
        title_row.addWidget(self._close_button)
        layout.addLayout(title_row)

        # 当前 Mod 组提示
        self._hint_label = QLabel(ui.ASSEMBLY_PANEL_EMPTY)
        self._hint_label.setStyleSheet("color: #666;")
        layout.addWidget(self._hint_label)

        # 文件列表（仅显示，不接收拖拽）
        self._list_view = QListView()
        self._list_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._list_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list_model = AssemblyListModel()
        self._list_view.setModel(self._list_model)
        self._list_view.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._list_view)

    # --- 公共接口 ---

    def bind_mod_group(self, unit: ContentUnit | None) -> None:
        """绑定当前 Mod 组，刷新文件列表。

        Args:
            unit: Mod 组 ContentUnit；None 表示解绑（清空面板，显示空状态占位）。
        """
        self._current_unit = unit

        if unit is None:
            self._title_label.setText(ui.ASSEMBLY_PANEL_TITLE)
            self._hint_label.setText(ui.ASSEMBLY_PANEL_EMPTY)
            self._list_model.refresh([])
            return

        # 显示 Mod 组名
        mod_name = Path(unit.path).name
        self._hint_label.setText(ui.ASSEMBLY_PANEL_HINT.format(name=mod_name))
        self._refresh_file_list()

    def refresh_current(self) -> None:
        """刷新当前绑定的 Mod 组文件列表（装配操作后调用）。"""
        if self._current_unit is not None:
            self._refresh_file_list()

    def current_unit_id(self) -> str | None:
        """返回当前绑定的 Mod 组 ContentUnit ID（供测试）。"""
        return self._current_unit.id if self._current_unit is not None else None

    def current_unit(self) -> ContentUnit | None:
        """返回当前绑定的 Mod 组 ContentUnit（供 MainWindow 查询）。"""
        return self._current_unit

    def entry_count(self) -> int:
        """返回当前文件列表条数（供测试）。"""
        return self._list_model.entry_count()

    def entry_at(self, row: int) -> FileEntry | None:
        """返回指定行的 FileEntry（供测试）。"""
        return self._list_model.entry_at(row)

    # --- 内部 ---

    def _refresh_file_list(self) -> None:
        """从 AssemblyService 重新加载 Mod 组文件夹内容。"""
        if self._current_unit is None:
            self._list_model.refresh([])
            return
        try:
            entries = self._service.list_mod_group_files(self._current_unit.id)
        except ContentUnitNotFoundError:
            logger.warning("装配面板：ContentUnit 不存在：%s", self._current_unit.id)
            entries = []
        except Exception:  # noqa: BLE001
            logger.exception("装配面板：加载文件列表失败")
            entries = []
        self._list_model.refresh(entries)

    def _on_close_clicked(self) -> None:
        """关闭按钮 → 通知 MainWindow 隐藏装配面板。"""
        if self._on_panel_closed is not None:
            self._on_panel_closed()

    def _on_context_menu(self, pos) -> None:  # noqa: ANN001 (Qt 信号)
        """右键菜单：图片重命名 / 复制路径。

        UX 重构 Phase 1 Task 1 Commit 3：移除「移除文件」菜单项（L2 决策）。
        """
        idx = self._list_view.indexAt(pos)
        if not idx.isValid():
            return
        entry = self._list_model.entry_at(idx.row())
        if entry is None:
            return

        menu = QMenu(self)
        actions: list[tuple[str, Callable[[], None]]] = []

        # 图片：重命名为 Mod 组同名
        if is_image_file(Path(entry.path)):
            actions.append(
                (
                    ui.ASSEMBLY_MENU_RENAME_COVER,
                    lambda: self._on_rename_cover(entry),
                )
            )

        # 复制路径
        actions.append((ui.ASSEMBLY_MENU_COPY_PATH, lambda: self._copy_path(entry.path)))

        for label, _ in actions:
            menu.addAction(label)
        chosen = menu.exec(self._list_view.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        for label, handler in actions:
            if chosen.text() == label:
                handler()
                break

    def _on_rename_cover(self, entry: FileEntry) -> None:
        """右键重命名预览图。"""
        if self._on_cover_renamed is not None:
            self._on_cover_renamed(Path(entry.path))

    def _copy_path(self, path: str) -> None:
        """复制路径到剪贴板。"""
        from PySide6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(path)
