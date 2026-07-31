"""装配面板 UI（阶段 3 Task 4）。

spec §7.4：创建 Mod 组后自动绑定，显示当前 Mod 组文件夹内容，
支持手动重命名预览图。

设计要点（UX 重构 Phase 1 Task 2 调整）：
- 不自动重命名图片。装配保留原文件名。
- 手动重命名：右键图片 → "重命名为与 Mod 组同名"。
- 「移除文件」功能已移除（L2 决策）：Task 4 将由剪切/移动到……替代。
- 「加入装配」菜单项已移除（B2-2 决策）：Task 4 将由「添加到钉住文件夹」+ 拖拽替代。
- 装配面板迁移到右栏下方，始终可见，未绑定时显示空状态占位（「无固定内容」）。
- 装配面板绑定当前 Mod 组，切换 Mod 组时刷新内容。
- 移除关闭按钮（B1-1）：装配面板固定在右栏，不再支持手动隐藏。

交互方式：
- 单击文件夹内容单元 → 装配面板绑定（A1-1）；双击文件夹 → 进入目录。
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
    QLabel,
    QListView,
    QMenu,
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
    """装配面板（文件夹透视器）：透视任意文件夹内容，支持右键重命名预览图。

    信号回调（由 MainWindow 注入）：
    - on_cover_renamed(image_path)：右键重命名触发，MainWindow 调用 rename_as_cover。

    使用回调而非直接调用 AssemblyService，便于 MainWindow 统一处理刷新逻辑
    （装配后需同步刷新装配面板 + 当前目录列表 + 提交事务）。

    UX 重构 Phase 1 Task 1 Commit 3：「移除文件」功能已移除（L2 决策）。
    UX 重构 Phase 1 Task 2：移除关闭按钮（B1-1），装配面板固定在右栏下方；
    「加入装配」菜单项已移除（B2-2），Task 4 由「添加到钉住文件夹」替代；
    装配面板语义扩展为"文件夹透视器"：bind_folder 透视任意文件夹（不限于内容单元）。
    """

    def __init__(
        self,
        assembly_service: AssemblyService,
        on_cover_renamed: Callable[[Path], None] | None = None,
        on_file_op: Callable[[str, list[FileEntry]], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = assembly_service
        self._on_cover_renamed = on_cover_renamed
        # UX 重构 Phase 1 Task 2 Commit 2：文件操作委托回调
        # action ∈ {"rename", "copy", "cut", "paste", "move_to", "delete", "copy_path"}
        self._on_file_op = on_file_op
        self._current_unit: ContentUnit | None = None
        # 当前透视的文件夹路径（bind_folder 设置，bind_mod_group 同步设置）
        self._current_folder_path: Path | None = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # 标题栏（UX 重构 Task 2：移除关闭按钮，仅保留标题）
        self._title_label = QLabel(ui.ASSEMBLY_PANEL_TITLE)
        layout.addWidget(self._title_label)

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
        self._current_folder_path = Path(unit.path) if unit is not None else None

        if unit is None:
            self._title_label.setText(ui.ASSEMBLY_PANEL_TITLE)
            self._hint_label.setText(ui.ASSEMBLY_PANEL_EMPTY)
            self._list_model.refresh([])
            return

        # 显示 Mod 组名
        mod_name = Path(unit.path).name
        self._hint_label.setText(ui.ASSEMBLY_PANEL_HINT.format(name=mod_name))
        self._refresh_file_list()

    def bind_folder(self, folder_path: Path | None) -> None:
        """透视任意文件夹路径（不依赖 ContentUnit，用于非内容单元文件夹）。

        UX 重构 Phase 1 Task 2：装配面板语义扩展为"文件夹透视器"。
        单击非内容单元文件夹时调用，显示其内部文件。
        清空 _current_unit 关联（封面重命名功能在 Task 2 Commit 2 调整）。

        Args:
            folder_path: 待透视的文件夹路径；None 表示清空面板。
        """
        self._current_unit = None
        self._current_folder_path = folder_path

        if folder_path is None:
            self._title_label.setText(ui.ASSEMBLY_PANEL_TITLE)
            self._hint_label.setText(ui.ASSEMBLY_PANEL_EMPTY)
            self._list_model.refresh([])
            return

        # 显示文件夹名
        self._hint_label.setText(ui.ASSEMBLY_PANEL_FOLDER_HINT.format(name=folder_path.name))
        self._refresh_file_list()

    def refresh_current(self) -> None:
        """刷新当前透视的文件夹文件列表（装配操作后调用）。"""
        if self._current_unit is not None or self._current_folder_path is not None:
            self._refresh_file_list()

    def current_unit_id(self) -> str | None:
        """返回当前绑定的 Mod 组 ContentUnit ID（供测试）。

        非内容单元文件夹透视时返回 None。
        """
        return self._current_unit.id if self._current_unit is not None else None

    def current_unit(self) -> ContentUnit | None:
        """返回当前绑定的 Mod 组 ContentUnit（供 MainWindow 查询）。"""
        return self._current_unit

    def current_folder_path(self) -> Path | None:
        """返回当前透视的文件夹路径（供 MainWindow 查询）。

        内容单元文件夹和非内容单元文件夹都会返回路径。
        """
        return self._current_folder_path

    def entry_count(self) -> int:
        """返回当前文件列表条数（供测试）。"""
        return self._list_model.entry_count()

    def entry_at(self, row: int) -> FileEntry | None:
        """返回指定行的 FileEntry（供测试）。"""
        return self._list_model.entry_at(row)

    # --- 内部 ---

    def _refresh_file_list(self) -> None:
        """从 AssemblyService 重新加载当前透视文件夹的内容。

        优先使用 ContentUnit 关联（list_mod_group_files），其次使用路径（list_folder_files）。
        """
        if self._current_unit is not None:
            try:
                entries = self._service.list_mod_group_files(self._current_unit.id)
            except ContentUnitNotFoundError:
                logger.warning("装配面板：ContentUnit 不存在：%s", self._current_unit.id)
                entries = []
            except Exception:  # noqa: BLE001
                logger.exception("装配面板：加载文件列表失败")
                entries = []
        elif self._current_folder_path is not None:
            try:
                entries = self._service.list_folder_files(self._current_folder_path)
            except Exception:  # noqa: BLE001
                logger.exception("装配面板：加载文件夹列表失败")
                entries = []
        else:
            entries = []
        self._list_model.refresh(entries)

    def _on_context_menu(self, pos) -> None:  # noqa: ANN001 (Qt 信号)
        """右键菜单：文件操作 + 图片重命名封面 + 空白处移动文件夹。

        UX 重构 Phase 1 Task 2 Commit 2：
        - 选中文件时：重命名/复制/剪切/粘贴/移动到/删除/复制路径 + 图片重命名封面。
        - 空白处右键：移动到...（移动整个透视的文件夹）。
        文件操作通过 on_file_op 回调委托 MainWindow，复用中栏现有逻辑。
        """
        idx = self._list_view.indexAt(pos)
        if not idx.isValid():
            # 空白处右键：移动整个透视的文件夹
            self._show_empty_area_menu(pos)
            return
        entry = self._list_model.entry_at(idx.row())
        if entry is None:
            return

        # 收集所有选中条目（支持多选）
        selected_entries = self._selected_entries()
        if not selected_entries:
            selected_entries = [entry]

        menu = QMenu(self)
        actions: list[tuple[str, Callable[[], None], bool]] = []

        # 图片重命名封面（单选图片）
        if len(selected_entries) == 1 and is_image_file(Path(selected_entries[0].path)):
            actions.append(
                (
                    ui.ASSEMBLY_MENU_RENAME_COVER,
                    lambda: self._on_rename_cover(selected_entries[0]),
                    True,
                )
            )

        if self._on_file_op is not None:
            # 重命名（单选）
            if len(selected_entries) == 1:
                actions.append(
                    (
                        ui.MENU_RENAME,
                        lambda: self._on_file_op("rename", selected_entries),
                        True,
                    )
                )
            # 复制 / 剪切 / 粘贴
            actions.append((ui.MENU_COPY, lambda: self._on_file_op("copy", selected_entries), True))
            actions.append((ui.MENU_CUT, lambda: self._on_file_op("cut", selected_entries), True))
            actions.append(
                (ui.MENU_PASTE, lambda: self._on_file_op("paste", selected_entries), True)
            )
            # 移动到 / 删除
            actions.append(
                (ui.MENU_MOVE_TO, lambda: self._on_file_op("move_to", selected_entries), True)
            )
            actions.append(
                (ui.MENU_DELETE, lambda: self._on_file_op("delete", selected_entries), True)
            )

        # 复制路径（单选）
        if len(selected_entries) == 1:
            actions.append(
                (
                    ui.ASSEMBLY_MENU_COPY_PATH,
                    lambda: (
                        self._on_file_op("copy_path", selected_entries)
                        if self._on_file_op is not None
                        else self._copy_path(selected_entries[0].path)
                    ),
                    True,
                )
            )

        for label, _, enabled in actions:
            act = menu.addAction(label)
            act.setEnabled(enabled)

        chosen = menu.exec(self._list_view.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        for label, handler, _ in actions:
            if chosen.text() == label:
                handler()
                break

    def _show_empty_area_menu(self, pos) -> None:  # noqa: ANN001 (Qt 信号)
        """空白处右键：粘贴 + 移动整个透视的文件夹（A3-1 移动后解绑）。

        UX 重构 Phase 1 Task 2 修复3：空白处也支持粘贴。
        """
        if self._on_file_op is None or self._current_folder_path is None:
            return
        menu = QMenu(self)
        actions: list[tuple[str, Callable[[], None]]] = []

        # 粘贴（修复3：空白处也支持粘贴到当前透视文件夹）
        actions.append((ui.MENU_PASTE, lambda: self._on_file_op("paste", [])))
        # 移动到...（移动整个透视文件夹）
        actions.append((ui.ASSEMBLY_MENU_MOVE_FOLDER, self._move_current_folder))

        for label, _ in actions:
            menu.addAction(label)
        chosen = menu.exec(self._list_view.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        for label, handler in actions:
            if chosen.text() == label:
                handler()
                break

    def _move_current_folder(self) -> None:
        """移动当前透视的整个文件夹（构造文件夹自身的 FileEntry）。"""
        if self._current_folder_path is None:
            return
        folder_entry = FileEntry(
            name=self._current_folder_path.name,
            path=str(self._current_folder_path),
            is_dir=True,
            modified_at="1970-01-01T00:00:00Z",
            size=None,
            content_unit=None,
        )
        self._on_file_op("move_to", [folder_entry])

    def _selected_entries(self) -> list[FileEntry]:
        """返回当前选中的 FileEntry 列表。"""
        sm = self._list_view.selectionModel()
        if sm is None:
            return []
        result: list[FileEntry] = []
        for idx in sm.selectedRows():
            entry = self._list_model.entry_at(idx.row())
            if entry is not None:
                result.append(entry)
        return result

    def _on_rename_cover(self, entry: FileEntry) -> None:
        """右键重命名预览图。"""
        if self._on_cover_renamed is not None:
            self._on_cover_renamed(Path(entry.path))

    def _copy_path(self, path: str) -> None:
        """复制路径到剪贴板（回退实现，当 on_file_op 未注入时使用）。"""
        from PySide6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(path)
