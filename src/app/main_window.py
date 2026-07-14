"""主窗口。阶段 2 Task 5：双模式切换 + 扫描联动（2026-07-13）。

布局（顶部模式切换 + 三栏，与 spec §7.1 一致）：
- 顶部：[浏览 | 整理] 模式切换按钮（默认浏览）。
- 左栏：受管理根目录列表 + 添加/移除按钮 + 扫描按钮 + 扫描状态 + 目录树 + 选中目录详情。
- 中栏：文件列表（浏览模式跟随目录树节点；整理模式冻结为切换前工作区）。
- 右栏：元数据面板（双击内容单元时显示；双击非内容单元不响应）。

模式行为（spec §5.1/§5.2，roadmap 阶段 2 Task 5）：
- 浏览模式：目录树点击节点 → 中栏刷新该目录文件列表 + 详情区更新。
- 整理模式：中栏内容冻结（保留切换前的文件列表），目录树点击节点只高亮目标
  并在中栏顶部显示"目标：xxx"，不切换中栏内容。

扫描联动（roadmap 阶段 2 Task 5 验收项 5）：
- 扫描完成 → 刷新目录树 + 刷新当前中栏文件列表
  （新扫描出的压缩包文件立即显示 [内容单元] 标记）。

约束（AGENTS 规则 3）：
- UI 不直接调用 shutil / Path.rename / Path.unlink 等文件写 API。
- 添加根目录只写应用数据库；不移动、不复制、不修改该目录。
- 扫描通过 ScanWorker 在后台线程执行，不冻结 UI。
- 扫描期间禁用重复扫描入口。

目录树数据源严格为 SQLite folder_cache 表，不重新扫描文件系统。
文件列表数据源为文件系统（Path.iterdir），通过 ContentService.list_directory_entries
读取条目并按 path 关联 content_unit 表。内容单元不是可见性门槛——
所有文件系统条目均可见可操作（spec §5.1 关键设计）。
元数据面板只读显示（编辑在阶段 4 Task 4）。
双击非内容单元不响应（spec §5.1 L205）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QThread
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from app.file_list_model import FileListModel
from app.folder_tree_model import FolderTreeModel
from app.mode_manager import ModeManager
from app.scan_worker import ScanWorker
from application.content_service import ContentService
from application.errors import (
    DuplicateManagedRootError,
    InvalidRootPathError,
    ManagedRootNotFoundError,
)
from application.folder_tree_service import FolderTreeService
from application.managed_root_service import ManagedRootService
from application.scan_service import ScanSummary
from domain.models import AppMode, ContentUnit, FileEntry, ManagedRoot

logger = logging.getLogger(__name__)

# 错误摘要最多展示条数
MAX_ERROR_SUMMARY_LINES = 5

# 详情区路径 / 元数据路径字段在 Elide 时保留的左右字符比例参考
# 详情区第 2 行为路径，元数据面板第 2 行为路径（详见 _apply_elide）


class MainWindow(QMainWindow):
    """应用主窗口。

    通过构造注入 ManagedRootService、FolderTreeService、ContentService 与 db_path，便于测试。
    db_path 用于 ScanWorker 在后台线程创建独立连接。
    """

    def __init__(
        self,
        managed_root_service: ManagedRootService,
        folder_tree_service: FolderTreeService,
        content_service: ContentService,
        db_path: Path,
        commit_callback: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = managed_root_service
        self._tree_service = folder_tree_service
        self._content_service = content_service
        self._db_path = db_path
        self._commit_callback = commit_callback
        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None
        self._is_scanning = False

        # 模式管理器（默认浏览模式）
        self._mode_manager = ModeManager(self)
        # 整理模式冻结的工作区目录路径（None 表示未设置，切换到整理模式时填充）
        self._organize_workarea_path: str | None = None
        # 整理模式下目录树选中的目标路径（用于显示"目标：xxx"提示）
        self._organize_target_path: str | None = None

        self.setWindowTitle(ui.APP_TITLE)
        self.resize(ui.WINDOW_DEFAULT_WIDTH, ui.WINDOW_DEFAULT_HEIGHT)

        self._setup_ui()
        self._mode_manager.mode_changed.connect(self._on_mode_changed)
        self._refresh_root_list()
        self._refresh_tree()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """关闭窗口前等待后台线程退出，避免 QThread Running 状态析构 CTD。"""
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)
        super().closeEvent(event)

    def _commit(self) -> None:
        """提交当前数据库事务。"""
        if self._commit_callback is not None:
            try:
                self._commit_callback()
            except Exception:  # noqa: BLE001
                logger.exception("数据库提交失败")

    # --- UI 构建 ---

    def _setup_ui(self) -> None:
        # === 顶部模式切换栏（spec §7.1，roadmap 阶段 2 Task 5） ===
        top_bar = QWidget()
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(8, 4, 8, 4)

        mode_label = QLabel(ui.MODE_SWITCH_GROUP_TITLE)
        top_layout.addWidget(mode_label)

        self._mode_browse_button = QPushButton(ui.MODE_BROWSE)
        self._mode_browse_button.setCheckable(True)
        self._mode_browse_button.setChecked(True)  # 默认浏览模式
        self._mode_browse_button.clicked.connect(lambda: self._set_mode(AppMode.browse))
        top_layout.addWidget(self._mode_browse_button)

        self._mode_organize_button = QPushButton(ui.MODE_ORGANIZE)
        self._mode_organize_button.setCheckable(True)
        self._mode_organize_button.clicked.connect(lambda: self._set_mode(AppMode.organize))
        top_layout.addWidget(self._mode_organize_button)

        # 互斥分组
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self._mode_browse_button)
        self._mode_group.addButton(self._mode_organize_button)

        top_layout.addStretch(1)
        # 右侧预留空间（搜索框、置顶按钮等属后续 Task）

        # === 三栏 Splitter ===
        splitter = QSplitter(Qt.Horizontal)

        # === 左栏：受管理根目录 + 扫描控制 + 目录树 + 详情 ===
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 受管理根目录
        self._roots_group = QGroupBox(ui.ROOTS_GROUP_TITLE)
        roots_layout = QVBoxLayout(self._roots_group)

        self._root_list = QListWidget()
        self._root_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._root_list.itemSelectionChanged.connect(self._on_selection_changed)
        roots_layout.addWidget(self._root_list)

        self._empty_hint = QLabel(ui.ROOTS_EMPTY_HINT)
        self._empty_hint.setWordWrap(True)
        roots_layout.addWidget(self._empty_hint)

        self._add_button = QPushButton(ui.ADD_ROOT_BUTTON)
        self._add_button.clicked.connect(self._on_add_root)
        roots_layout.addWidget(self._add_button)

        self._remove_button = QPushButton(ui.REMOVE_ROOT_BUTTON)
        self._remove_button.clicked.connect(self._on_remove_root)
        self._remove_button.setEnabled(False)
        roots_layout.addWidget(self._remove_button)

        # 扫描按钮行：增量 + 全量
        scan_row = QHBoxLayout()
        self._scan_button = QPushButton(ui.SCAN_BUTTON)
        self._scan_button.clicked.connect(lambda: self._on_scan(incremental=True))
        self._scan_button.setEnabled(False)
        scan_row.addWidget(self._scan_button)

        self._scan_full_button = QPushButton(ui.SCAN_BUTTON_FULL)
        self._scan_full_button.clicked.connect(lambda: self._on_scan(incremental=False))
        self._scan_full_button.setEnabled(False)
        scan_row.addWidget(self._scan_full_button)
        roots_layout.addLayout(scan_row)

        left_layout.addWidget(self._roots_group)

        # 扫描状态
        status_box = QGroupBox("扫描状态")
        status_layout = QVBoxLayout(status_box)
        self._status_label = QLabel(ui.STATUS_IDLE)
        self._status_label.setWordWrap(True)
        status_layout.addWidget(self._status_label)
        left_layout.addWidget(status_box)

        # 目录树
        self._tree_group = QGroupBox(ui.TREE_GROUP_TITLE)
        tree_layout = QVBoxLayout(self._tree_group)

        self._tree_view = QTreeView()
        self._tree_view.setHeaderHidden(True)
        self._tree_view.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self._tree_view.setSelectionMode(QTreeView.SelectionMode.SingleSelection)
        self._tree_view.setDragDropMode(QTreeView.DragDropMode.NoDragDrop)
        self._tree_model = FolderTreeModel(self._tree_service)
        self._tree_view.setModel(self._tree_model)
        self._tree_view.selectionModel().selectionChanged.connect(self._on_tree_selection_changed)
        tree_layout.addWidget(self._tree_view)

        self._tree_empty_hint = QLabel(ui.TREE_EMPTY_HINT)
        self._tree_empty_hint.setWordWrap(True)
        tree_layout.addWidget(self._tree_empty_hint)

        left_layout.addWidget(self._tree_group, stretch=2)

        # 选中目录详情
        self._detail_group = QGroupBox(ui.DETAIL_GROUP_TITLE)
        detail_layout = QVBoxLayout(self._detail_group)
        self._detail_label = QLabel(ui.DETAIL_NOT_SELECTED)
        # 详情区路径需要 Elide，整体不自动换行；多行字段之间用 \n 分隔
        self._detail_label.setWordWrap(False)
        self._detail_label.setTextFormat(Qt.PlainText)
        self._detail_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        # 缓存原始文本供 resizeEvent 重新 Elide
        self._detail_full_text = ui.DETAIL_NOT_SELECTED
        detail_layout.addWidget(self._detail_label)
        left_layout.addWidget(self._detail_group, stretch=1)

        splitter.addWidget(left)

        # === 中栏：文件列表（roadmap Task 4 2026-07-13 设计修正） ===
        middle = QWidget()
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(0, 0, 0, 0)

        # 模式提示标签（显示当前模式 + 目标路径/工作区）
        # 与详情区/元数据面板一致：关闭自动换行 + PlainText，走 Elide 流程
        self._mode_hint_label = QLabel(ui.MODE_BROWSE_HINT)
        self._mode_hint_label.setWordWrap(False)
        self._mode_hint_label.setTextFormat(Qt.PlainText)
        self._mode_hint_label.setStyleSheet("padding: 4px; color: #666;")
        self._mode_hint_full_text = ui.MODE_BROWSE_HINT
        middle_layout.addWidget(self._mode_hint_label)

        self._content_group = QGroupBox(ui.CONTENT_LIST_GROUP_TITLE)
        content_layout = QVBoxLayout(self._content_group)

        self._content_view = QListView()
        self._content_view.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self._content_view.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self._content_view.setDragDropMode(QListView.DragDropMode.NoDragDrop)
        self._content_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._content_list_model = FileListModel()
        self._content_view.setModel(self._content_list_model)
        self._content_view.doubleClicked.connect(self._on_entry_activated)
        self._content_view.customContextMenuRequested.connect(self._on_content_context_menu)
        content_layout.addWidget(self._content_view)

        self._content_empty_hint = QLabel(ui.CONTENT_LIST_NO_SELECTION)
        self._content_empty_hint.setWordWrap(True)
        content_layout.addWidget(self._content_empty_hint)

        middle_layout.addWidget(self._content_group)

        splitter.addWidget(middle)

        # === 右栏：元数据面板 ===
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._metadata_group = QGroupBox(ui.METADATA_GROUP_TITLE)
        metadata_layout = QVBoxLayout(self._metadata_group)
        self._metadata_label = QLabel(ui.METADATA_NOT_SELECTED)
        # 元数据路径字段需要 Elide，整体不自动换行
        self._metadata_label.setWordWrap(False)
        self._metadata_label.setTextFormat(Qt.PlainText)
        self._metadata_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._metadata_full_text = ui.METADATA_NOT_SELECTED
        metadata_layout.addWidget(self._metadata_label)
        right_layout.addWidget(self._metadata_group)

        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)

        # 主布局：顶部模式栏 + 三栏 splitter
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(top_bar)
        central_layout.addWidget(splitter, stretch=1)
        self.setCentralWidget(central)

    # --- 根目录列表 ---

    def _refresh_root_list(self) -> None:
        """从服务重新加载根目录列表。"""
        self._root_list.clear()
        roots = self._service.list_roots()
        for root in roots:
            self._add_root_item(root)
        self._empty_hint.setVisible(len(roots) == 0)
        self._on_selection_changed()

    def _add_root_item(self, root: ManagedRoot) -> None:
        text = root.display_name or root.real_path
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, root.id)
        item.setToolTip(root.real_path)
        self._root_list.addItem(item)

    def _selected_root_id(self) -> str | None:
        items = self._root_list.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.UserRole)

    def _on_selection_changed(self) -> None:
        has_selection = self._selected_root_id() is not None
        self._scan_button.setEnabled(has_selection and not self._is_scanning)
        self._scan_full_button.setEnabled(has_selection and not self._is_scanning)
        self._remove_button.setEnabled(has_selection and not self._is_scanning)

    # --- 目录树 ---

    def _refresh_tree(self) -> None:
        """刷新目录树模型。

        整理模式下不清空中栏文件列表（保留冻结的工作区）。
        """
        self._tree_model.refresh()
        root_count = self._tree_model.root_node_count()
        self._tree_empty_hint.setVisible(root_count == 0)
        # 清空详情区
        self._set_detail_text(ui.DETAIL_NOT_SELECTED)
        if self._mode_manager.is_browse():
            # 浏览模式：清空文件列表与元数据
            self._content_list_model.refresh([])
            self._content_empty_hint.setText(ui.CONTENT_LIST_NO_SELECTION)
            self._set_metadata_text(ui.METADATA_NOT_SELECTED)
        # 整理模式：保留冻结的工作区内容，不清空中栏

    def _on_tree_selection_changed(self, *args) -> None:  # noqa: ANN001 (Qt 信号)
        """目录树选中变化时更新详情区与文件列表。

        模式行为分支：
        - 浏览模式：刷新详情区 + 刷新中栏文件列表 + 清空元数据。
        - 整理模式：刷新详情区 + 更新整理目标提示，**不刷新中栏内容**（中栏冻结）。
        """
        indexes = self._tree_view.selectionModel().selectedIndexes()
        if not indexes:
            self._set_detail_text(ui.DETAIL_NOT_SELECTED)
            if self._mode_manager.is_browse():
                self._content_list_model.refresh([])
                self._content_empty_hint.setText(ui.CONTENT_LIST_NO_SELECTION)
            return

        index = indexes[0]
        node = self._tree_model.node_at(index)
        if node is None:
            self._set_detail_text(ui.DETAIL_NOT_SELECTED)
            if self._mode_manager.is_browse():
                self._content_list_model.refresh([])
                self._content_empty_hint.setText(ui.CONTENT_LIST_NO_SELECTION)
            return

        # 查询子目录数
        child_count = self._tree_service.count_children(node.node_id)

        if node.category == "managed_root":
            type_text = ui.DETAIL_TYPE_MANAGED_ROOT
        elif node.category == "unscanned_root":
            type_text = ui.DETAIL_TYPE_UNSCANNED_ROOT
        else:
            type_text = ui.DETAIL_TYPE_FOLDER

        lines = [
            f"{ui.DETAIL_NAME_LABEL}：{node.display_name}",
            f"{ui.DETAIL_PATH_LABEL}：{node.real_path}",
            f"{ui.DETAIL_IS_ROOT_LABEL}：{'是' if node.is_managed_root else '否'}",
            f"{ui.DETAIL_TYPE_LABEL}：{type_text}",
            f"{ui.DETAIL_CHILD_COUNT_LABEL}：{child_count}",
        ]
        self._set_detail_text("\n".join(lines))

        if self._mode_manager.is_browse():
            # 浏览模式：刷新文件列表（使用 node.real_path 读取目录条目）
            self._refresh_content_list(node.real_path)
            # 清空元数据面板（切换目录时重置）
            self._set_metadata_text(ui.METADATA_NOT_SELECTED)
        else:
            # 整理模式：只更新目标路径提示，不刷新中栏内容
            self._organize_target_path = node.real_path
            self._update_organize_hint()

    def _refresh_content_list(self, dir_path: str) -> None:
        """刷新文件列表（数据源为文件系统，content_unit 表仅作标记）。"""
        try:
            entries = self._content_service.list_directory_entries(dir_path)
        except Exception:  # noqa: BLE001 - UI 边界需捕获所有异常
            logger.exception("加载文件列表失败：dir_path=%s", dir_path)
            entries = []

        self._content_list_model.refresh(entries)
        if not entries:
            self._content_empty_hint.setText(ui.CONTENT_LIST_EMPTY_HINT)
        else:
            self._content_empty_hint.setText("")

    # --- 文件条目 ---

    def _on_entry_activated(self, index) -> None:  # noqa: ANN001 (Qt 信号)
        """双击文件条目：仅内容单元响应（显示元数据），非内容单元不响应。

        spec §5.1 L205：双击非内容单元不响应。
        """
        entry = self._content_list_model.entry_at(index.row())
        if entry is None:
            return

        if entry.content_unit is not None:
            self._update_metadata(entry.content_unit)
            return

        # 非内容单元（文件或文件夹）：不响应，右栏保持现状

    def _on_content_context_menu(self, pos: QPoint) -> None:  # noqa: N802 (Qt 命名)
        """文件列表右键菜单：本 Task 仅实现「复制路径」（决策问题 2）。"""
        index = self._content_view.indexAt(pos)
        if not index.isValid():
            return
        entry = self._content_list_model.entry_at(index.row())
        if entry is None:
            return

        menu = QMenu(self)
        action = menu.addAction(ui.CONTEXT_MENU_COPY_PATH)
        chosen = menu.exec(self._content_view.viewport().mapToGlobal(pos))
        if chosen is action:
            self._copy_path_to_clipboard(entry.path)

    def _copy_path_to_clipboard(self, path: str) -> None:
        """复制路径到剪贴板。"""
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(path)
        self.statusBar().showMessage(ui.CONTEXT_MENU_COPY_PATH_OK, 3000)

    def _update_metadata(self, unit: ContentUnit) -> None:
        """更新元数据面板。"""
        title = unit.title or "（无标题）"
        status_text = (
            ui.METADATA_STATUS_ORGANIZED
            if unit.status == "organized"
            else ui.METADATA_STATUS_UNORGANIZED
        )
        rating_text = f"{unit.rating} / 5" if unit.rating is not None else ui.METADATA_RATING_EMPTY
        source_url = unit.source_url or ui.METADATA_SOURCE_URL_EMPTY
        notes = unit.notes or ui.METADATA_NOTES_EMPTY

        lines = [
            f"{ui.METADATA_TITLE_LABEL}：{title}",
            f"{ui.METADATA_PATH_LABEL}：{unit.path}",
            f"{ui.METADATA_TYPE_LABEL}：{unit.content_type}",
            f"{ui.METADATA_SOURCE_URL_LABEL}：{source_url}",
            f"{ui.METADATA_RATING_LABEL}：{rating_text}",
            f"{ui.METADATA_STATUS_LABEL}：{status_text}",
            f"{ui.METADATA_NOTES_LABEL}：{notes}",
            f"{ui.METADATA_CREATED_AT_LABEL}：{unit.created_at}",
        ]
        self._set_metadata_text("\n".join(lines))

    # --- Elide 路径文本（决策问题 4，Task 5 统一路径显示策略） ---

    # 需要对值部分做 ElideMiddle 的路径前缀列表
    _ELIDE_PATH_PREFIXES = ("路径：", "完整路径：", "目标：")

    def _set_detail_text(self, text: str) -> None:
        """设置详情区文本（缓存原文，触发 Elide 重算）。"""
        self._detail_full_text = text
        self._apply_elide()

    def _set_metadata_text(self, text: str) -> None:
        """设置元数据面板文本（缓存原文，触发 Elide 重算）。"""
        self._metadata_full_text = text
        self._apply_elide()

    def _set_mode_hint_text(self, text: str) -> None:
        """设置模式提示文本（缓存原文，触发 Elide 重算）。"""
        self._mode_hint_full_text = text
        self._apply_elide()

    def _apply_elide(self) -> None:
        """对详情区、元数据面板、模式提示的路径行应用 ElideMiddle。

        多行文本按 \\n 拆分，仅对路径行（"路径：..." / "完整路径：..." / "目标：..."）
        做值部分省略，其他行原样保留。文本超长时用 QFontMetrics.elidedText 替换为中间省略形式。
        同时设置 Tooltip 显示完整文本，便于鼠标悬停查看。
        """
        self._elide_label_lines(self._detail_label, self._detail_full_text)
        self._elide_label_lines(self._metadata_label, self._metadata_full_text)
        self._elide_label_lines(self._mode_hint_label, self._mode_hint_full_text)

    def _elide_label_lines(self, label: QLabel, full_text: str) -> None:
        """对 label 的多行文本逐行 Elide，并设置 Tooltip 显示完整文本。"""
        if not full_text:
            label.setText("")
            label.setToolTip("")
            return

        fm = QFontMetrics(label.font())
        # 减去内边距，预留 16px 余量
        max_width = max(50, label.width() - 16)

        lines = full_text.split("\n")
        out: list[str] = []
        for line in lines:
            elided_line = self._elide_single_line(line, fm, max_width)
            out.append(elided_line)
        label.setText("\n".join(out))
        # Tooltip 显示完整原文（统一路径显示策略：Elide + 悬停查看完整路径）
        label.setToolTip(full_text)

    def _elide_single_line(self, line: str, fm: QFontMetrics, max_width: int) -> str:
        """对单行文本应用 Elide。

        识别路径前缀（"路径：" / "完整路径：" / "目标："），对值部分 ElideMiddle；
        其他行若超宽则整体 ElideMiddle。
        """
        for prefix_str in self._ELIDE_PATH_PREFIXES:
            if prefix_str in line:
                idx = line.index(prefix_str)
                prefix = line[: idx + len(prefix_str)]
                value = line[idx + len(prefix_str) :]
                available = max_width - fm.horizontalAdvance(prefix)
                elided = fm.elidedText(value, Qt.TextElideMode.ElideMiddle, available)
                return prefix + elided
        # 非路径行：若仍超宽，整体 ElideMiddle
        if fm.horizontalAdvance(line) > max_width:
            return fm.elidedText(line, Qt.TextElideMode.ElideMiddle, max_width)
        return line

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """窗口尺寸变化时重新 Elide。"""
        super().resizeEvent(event)
        self._apply_elide()

    # --- 添加根目录 ---

    def _on_add_root(self) -> None:
        """打开目录选择对话框，添加受管理根目录。"""
        if self._is_scanning:
            return
        start_dir = ""
        existing = self._service.list_roots()
        if existing:
            start_dir = existing[0].real_path
        chosen = QFileDialog.getExistingDirectory(self, ui.ADD_ROOT_BUTTON, start_dir)
        if not chosen:
            return
        try:
            self._service.add_root(Path(chosen))
            self._commit()
        except DuplicateManagedRootError:
            QMessageBox.warning(self, ui.ERR_ADD_ROOT_FAILED, ui.ERR_DUPLICATE_ROOT)
            return
        except InvalidRootPathError as e:
            QMessageBox.warning(self, ui.ERR_ADD_ROOT_FAILED, f"{ui.ERR_INVALID_ROOT}\n{e}")
            return
        except Exception as e:  # noqa: BLE001 - UI 边界需捕获所有异常
            logger.exception("添加根目录失败")
            QMessageBox.critical(self, ui.ERR_ADD_ROOT_FAILED, f"{ui.ERR_ADD_ROOT_FAILED}：{e}")
            return
        self._refresh_root_list()
        self._refresh_tree()

    # --- 移除根目录配置 ---

    def _on_remove_root(self) -> None:
        """移除选中的受管理根目录配置。

        仅删除应用数据库中的 managed_root 记录；不删除、不移动、不修改
        磁盘上的任何用户文件；不清理扫描记录。
        """
        if self._is_scanning:
            return
        root_id = self._selected_root_id()
        if root_id is None:
            self._set_status(ui.ERR_NO_ROOT_SELECTED)
            return

        try:
            root = self._service.get_root(root_id)
        except ManagedRootNotFoundError:
            self._refresh_root_list()
            return

        confirm_text = ui.REMOVE_ROOT_CONFIRM_TEXT.format(path=root.real_path)
        reply = QMessageBox.question(
            self,
            ui.REMOVE_ROOT_CONFIRM_TITLE,
            confirm_text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self._service.remove_root(root_id)
            self._commit()
        except ManagedRootNotFoundError:
            self._refresh_root_list()
            return
        except Exception as e:  # noqa: BLE001 - UI 边界需捕获所有异常
            logger.exception("移除根目录配置失败")
            QMessageBox.critical(
                self, ui.ERR_REMOVE_ROOT_FAILED, f"{ui.ERR_REMOVE_ROOT_FAILED}：{e}"
            )
            return

        self._refresh_root_list()
        self._refresh_tree()

    # --- 扫描 ---

    def _on_scan(self, incremental: bool = True) -> None:
        """启动后台扫描。扫描期间禁用扫描入口。"""
        if self._is_scanning:
            return
        root_id = self._selected_root_id()
        if root_id is None:
            self._set_status(ui.ERR_NO_ROOT_SELECTED)
            return

        self._begin_scanning()

        self._thread = QThread()
        self._worker = ScanWorker(self._db_path, root_id, incremental=incremental)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.scan_started.connect(self._on_scan_started)
        self._worker.scan_finished.connect(self._thread.quit)
        self._worker.scan_failed.connect(self._thread.quit)
        self._worker.scan_finished.connect(self._on_scan_finished)
        self._worker.scan_failed.connect(self._on_scan_failed)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _begin_scanning(self) -> None:
        self._is_scanning = True
        self._scan_button.setText(ui.SCAN_BUTTON_SCANNING)
        self._scan_button.setEnabled(False)
        self._scan_full_button.setEnabled(False)
        self._add_button.setEnabled(False)
        self._remove_button.setEnabled(False)
        self._set_status(ui.STATUS_SCANNING)

    def _end_scanning(self) -> None:
        """恢复按钮状态。"""
        self._is_scanning = False
        self._scan_button.setText(ui.SCAN_BUTTON)
        self._add_button.setEnabled(True)
        has_selection = self._selected_root_id() is not None
        self._scan_button.setEnabled(has_selection)
        self._scan_full_button.setEnabled(has_selection)
        self._remove_button.setEnabled(has_selection)

    def _on_thread_finished(self) -> None:
        """QThread 真正退出后清理 Python 引用。"""
        self._worker = None
        self._thread = None

    def _on_scan_started(self) -> None:
        self._set_status(ui.STATUS_SCANNING)

    def _on_scan_finished(self, summary: ScanSummary) -> None:
        """扫描完成：展示摘要、刷新目录树、刷新当前中栏文件列表。

        扫描联动（roadmap 阶段 2 Task 5 验收项 5）：
        - 浏览模式：若当前选中目录树节点，刷新该目录的文件列表，
          使新扫描出的压缩包文件立即显示 [内容单元] 标记。
        - 整理模式：刷新冻结的工作区目录的文件列表。
        """
        text = ui.format_scan_summary(
            scanned_dirs=summary.scanned_dirs,
            content_units_found=summary.content_units_found,
            skipped_unchanged=summary.skipped_unchanged,
            errors=len(summary.errors),
        )
        if summary.errors:
            lines = [text, ""]
            lines.append(f"错误摘要（前 {MAX_ERROR_SUMMARY_LINES} 条）：")
            for err in summary.errors[:MAX_ERROR_SUMMARY_LINES]:
                lines.append(f"• {err}")
            if len(summary.errors) > MAX_ERROR_SUMMARY_LINES:
                lines.append(f"…（共 {len(summary.errors)} 个错误）")
            text = "\n".join(lines)
        self._set_status(f"{ui.STATUS_SCAN_COMPLETE}\n{text}")
        self._end_scanning()
        # 扫描完成 → 刷新目录树
        self._refresh_tree()
        # 扫描完成 → 刷新当前中栏文件列表（扫描联动）
        self._refresh_content_list_after_scan()

    def _refresh_content_list_after_scan(self) -> None:
        """扫描完成后刷新中栏文件列表（扫描联动）。

        - 浏览模式：若目录树有选中节点，重新读取该目录文件列表。
        - 整理模式：若有冻结的工作区，重新读取工作区目录文件列表。
        - 否则：无操作。
        """
        if self._mode_manager.is_organize():
            workarea = self._organize_workarea_path
            if workarea is not None:
                self._refresh_content_list(workarea)
            return

        # 浏览模式：读取当前选中目录树节点
        sm = self._tree_view.selectionModel()
        indexes = sm.selectedIndexes() if sm is not None else []
        if not indexes:
            return
        node = self._tree_model.node_at(indexes[0])
        if node is not None:
            self._refresh_content_list(node.real_path)

    def _on_scan_failed(self, message: str) -> None:
        self._set_status(f"{ui.STATUS_SCAN_FAILED}\n{message}")
        self._end_scanning()

    # --- 状态 ---

    def _set_status(self, text: str) -> None:
        self._status_label.setText(text)

    def status_text(self) -> str:
        """返回当前状态文本（供测试）。"""
        return self._status_label.text()

    def root_count(self) -> int:
        """返回当前根目录列表条数（供测试）。"""
        return self._root_list.count()

    def is_scan_button_enabled(self) -> bool:
        """返回增量扫描按钮是否可用（供测试）。"""
        return self._scan_button.isEnabled()

    def is_remove_button_enabled(self) -> bool:
        """返回移除按钮是否可用（供测试）。"""
        return self._remove_button.isEnabled()

    # --- 文件列表测试接口 ---

    def entry_count(self) -> int:
        """返回当前文件列表条数（供测试）。"""
        return self._content_list_model.entry_count()

    def entry_at(self, row: int) -> FileEntry | None:
        """返回指定行的 FileEntry（供测试）。"""
        return self._content_list_model.entry_at(row)

    def metadata_text(self) -> str:
        """返回元数据面板当前显示文本（已 Elide，供测试）。"""
        return self._metadata_label.text()

    def metadata_full_text(self) -> str:
        """返回元数据面板原始文本（未 Elide，供测试）。"""
        return self._metadata_full_text

    def detail_full_text(self) -> str:
        """返回详情区原始文本（未 Elide，供测试）。"""
        return self._detail_full_text

    # --- 模式切换（spec §5.1/§5.2，roadmap 阶段 2 Task 5） ---

    def _set_mode(self, mode: AppMode) -> None:
        """切换应用模式（按钮回调）。"""
        self._mode_manager.set_mode(mode)

    def _on_mode_changed(self, mode: AppMode) -> None:
        """模式变化时更新 UI 状态与中栏提示。"""
        if mode == AppMode.organize:
            # 切换到整理模式：冻结当前工作区
            self._freeze_workarea_for_organize()
            self._update_organize_hint()
        else:
            # 切换回浏览模式：恢复跟随目录树刷新
            self._organize_workarea_path = None
            self._organize_target_path = None
            self._set_mode_hint_text(ui.MODE_BROWSE_HINT)
            # 恢复显示当前选中目录树节点的内容
            self._refresh_content_for_current_tree_selection()

    def _freeze_workarea_for_organize(self) -> None:
        """切换到整理模式时冻结当前工作区。

        若目录树有选中节点，将其 real_path 作为冻结工作区；
        否则工作区为 None，中栏显示提示。
        """
        sm = self._tree_view.selectionModel()
        indexes = sm.selectedIndexes() if sm is not None else []
        if not indexes:
            self._organize_workarea_path = None
            return
        node = self._tree_model.node_at(indexes[0])
        if node is not None:
            self._organize_workarea_path = node.real_path
            self._organize_target_path = node.real_path
        else:
            self._organize_workarea_path = None

    def _update_organize_hint(self) -> None:
        """更新整理模式下的中栏顶部提示（走 Elide 流程）。"""
        if self._organize_workarea_path is None:
            self._set_mode_hint_text(ui.MODE_ORGANIZE_NO_WORKAREA)
            return
        workarea_name = Path(self._organize_workarea_path).name
        base_hint = ui.MODE_ORGANIZE_WORKAREA_HINT.format(name=workarea_name)
        target = self._organize_target_path
        if target is not None and target != self._organize_workarea_path:
            target_hint = ui.MODE_ORGANIZE_TARGET_HINT.format(path=target)
            self._set_mode_hint_text(f"{base_hint}\n{target_hint}")
        else:
            self._set_mode_hint_text(base_hint)

    def _refresh_content_for_current_tree_selection(self) -> None:
        """切回浏览模式时，根据目录树当前选中节点刷新中栏。"""
        sm = self._tree_view.selectionModel()
        if sm is None:
            return
        indexes = sm.selectedIndexes()
        if not indexes:
            return
        node = self._tree_model.node_at(indexes[0])
        if node is not None:
            self._refresh_content_list(node.real_path)

    # --- 模式测试接口 ---

    def current_mode(self) -> AppMode:
        """返回当前应用模式（供测试）。"""
        return self._mode_manager.mode

    def mode_hint_text(self) -> str:
        """返回中栏顶部模式提示显示文本（已 Elide，供测试）。"""
        return self._mode_hint_label.text()

    def mode_hint_full_text(self) -> str:
        """返回中栏顶部模式提示原始文本（未 Elide，供测试）。"""
        return self._mode_hint_full_text

    def organize_workarea_path(self) -> str | None:
        """返回整理模式冻结的工作区路径（供测试）。"""
        return self._organize_workarea_path
