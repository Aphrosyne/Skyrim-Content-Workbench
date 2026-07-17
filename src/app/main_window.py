"""主窗口。阶段 2 Task 5：双模式切换 + 扫描联动（2026-07-13）。

布局（顶部模式切换 + 三栏，与 spec §7.1 一致）：
- 顶部：[浏览 | 整理] 模式切换按钮（默认浏览）。
- 左栏：受管理根目录列表 + 添加/移除按钮 + 扫描按钮 + 扫描状态 + 目录树 + 选中目录详情。
- 中栏：文件列表（浏览模式跟随目录树节点；整理模式只加载 [S] 节点递归列表）。
- 右栏：元数据面板（双击内容单元时显示；双击非内容单元不响应）。

模式行为（spec §5.1/§5.2，roadmap 阶段 2 Task 5）：
- 浏览模式：目录树点击节点 → 中栏刷新该目录文件列表 + 详情区更新。
- 整理模式：中栏只加载 [S] 节点递归列表，目录树点击非 [S] 节点只高亮目标
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

交互行为（2026-07-16 调整）：
- 单击选中内容单元 → 右侧立即显示元数据（详情面板交互方式）。
- 浏览模式双击文件夹 → 进入该目录（无论是否内容单元，优先于元数据显示）。
  文件夹的元数据通过单击查看。
- 双击文件类型内容单元（压缩包）→ 显示元数据面板。
- 整理模式双击文件夹 / 双击普通文件 → 不响应。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QThread
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from app.assembly_panel import AssemblyPanel
from app.file_list_model import FileListModel
from app.folder_tree_model import FolderTreeModel
from app.mode_manager import ModeManager
from app.scan_worker import ScanWorker
from application.assembly_service import AssemblyService
from application.content_service import ContentService
from application.errors import (
    ConflictError,
    ContentUnitNotFoundError,
    CrossDriveError,
    DuplicateManagedRootError,
    DuplicateStagingAreaError,
    FileOperationError,
    InvalidContentUnitPathError,
    InvalidModGroupNameError,
    InvalidRootPathError,
    ManagedRootNotFoundError,
    ModGroupSourceNotInStagingError,
    SelfSubdirectoryError,
    StagingAreaNestingError,
    StagingAreaNotFoundError,
)
from application.folder_tree_service import FolderTreeService
from application.managed_root_service import ManagedRootService
from application.mod_group_service import ModGroupService
from application.quick_insert_service import QuickInsertService
from application.scan_service import ScanSummary
from application.staging_service import StagingService
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
        staging_service: StagingService | None = None,
        mod_group_service: ModGroupService | None = None,
        assembly_service: AssemblyService | None = None,
        quick_insert_service: QuickInsertService | None = None,
        rollback_callback: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = managed_root_service
        self._tree_service = folder_tree_service
        self._content_service = content_service
        self._db_path = db_path
        self._commit_callback = commit_callback
        self._rollback_callback = rollback_callback
        self._staging_service = staging_service
        self._mod_group_service = mod_group_service
        self._assembly_service = assembly_service
        self._quick_insert_service = quick_insert_service
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

    def _rollback(self) -> None:
        """回滚当前数据库事务。

        文件操作失败时调用，释放 SQLite 写锁，避免后续操作 "database is locked"。
        注意：文件系统层面的变更无法回滚（文件已移动），仅回滚数据库事务。
        """
        if self._rollback_callback is not None:
            try:
                self._rollback_callback()
            except Exception:  # noqa: BLE001
                logger.exception("数据库回滚失败")

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

        # 快速插入按钮（阶段 3 Task 5）：仅整理模式 + 装配面板已绑定 + 目录树选中目标时可用
        self._quick_insert_button = QPushButton(ui.QUICK_INSERT_BUTTON)
        self._quick_insert_button.setToolTip(ui.QUICK_INSERT_TOOLTIP)
        self._quick_insert_button.clicked.connect(self._on_quick_insert_clicked)
        self._quick_insert_button.setVisible(False)  # 默认浏览模式隐藏
        top_layout.addWidget(self._quick_insert_button)

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
        self._tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree_model = FolderTreeModel(self._tree_service)
        self._tree_view.setModel(self._tree_model)
        self._tree_view.selectionModel().selectionChanged.connect(self._on_tree_selection_changed)
        self._tree_view.customContextMenuRequested.connect(self._on_tree_context_menu)
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

        # === 中栏：文件列表 + 装配面板（roadmap Task 4 + 阶段 3 Task 4） ===
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

        # 上下分割：上方文件列表，下方装配面板（仅整理模式可见）
        self._middle_splitter = QSplitter(Qt.Vertical)

        self._content_group = QGroupBox(ui.CONTENT_LIST_GROUP_TITLE)
        content_layout = QVBoxLayout(self._content_group)

        # 文件列表（整理模式下右键菜单「加入装配」替代原拖拽方案）
        self._content_view = QTableView()
        self._content_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._content_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._content_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._content_view.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self._content_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._content_view.verticalHeader().setVisible(False)
        self._content_view.horizontalHeader().setHighlightSections(False)
        self._content_view.horizontalHeader().setStretchLastSection(False)
        self._content_view.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._content_view.horizontalHeader().setSectionsClickable(True)
        self._content_list_model = FileListModel()
        self._content_view.setModel(self._content_list_model)
        self._content_view.doubleClicked.connect(self._on_entry_activated)
        self._content_view.customContextMenuRequested.connect(self._on_content_context_menu)
        self._content_view.horizontalHeader().sectionClicked.connect(
            self._on_content_header_clicked
        )
        # 单击选中内容单元 → 显示元数据（selectionChanged 在选中变化时触发）
        # 延迟连接，确保 selectionModel 已创建
        self._content_view.selectionModel().selectionChanged.connect(
            self._on_content_selection_changed
        )
        content_layout.addWidget(self._content_view)

        self._content_empty_hint = QLabel(ui.CONTENT_LIST_NO_SELECTION)
        self._content_empty_hint.setWordWrap(True)
        content_layout.addWidget(self._content_empty_hint)

        self._middle_splitter.addWidget(self._content_group)

        # 装配面板（阶段 3 Task 4）：默认隐藏，创建/双击 Mod 组时显示
        if self._assembly_service is not None:
            self._assembly_panel = AssemblyPanel(
                self._assembly_service,
                on_file_removed=self._on_assembly_remove_file,
                on_cover_renamed=self._on_assembly_rename_cover,
                on_panel_closed=self._on_assembly_closed,
            )
            self._assembly_panel.setVisible(False)
            self._middle_splitter.addWidget(self._assembly_panel)
            # 初始拉伸比例：文件列表占大头，装配面板占小头
            self._middle_splitter.setStretchFactor(0, 3)
            self._middle_splitter.setStretchFactor(1, 1)
        else:
            self._assembly_panel = None  # type: ignore[assignment]

        middle_layout.addWidget(self._middle_splitter)

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

        2026-07-16 优化：刷新前保存展开状态与选中节点，刷新后递归恢复，
        避免每次扫描/创建 Mod 组后目录树全部折叠。
        整理模式下不清空中栏文件列表（保留冻结的工作区）。
        """
        # 保存展开状态与选中节点
        expanded_paths = self._tree_model.save_expanded_paths(self._tree_view)
        selected_path = self._tree_model.save_selected_path(self._tree_view)

        self._tree_model.refresh()

        # 恢复展开状态与选中节点
        self._tree_model.restore_expanded_paths(self._tree_view, expanded_paths, selected_path)

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
            # 整理模式：点选 [S] 节点 → 中栏切换为该暂存区递归列表；
            # 点选非 [S] 节点 → 只更新目标提示，不刷新中栏内容。
            if node.is_staging:
                self._organize_workarea_path = node.real_path
                self._organize_target_path = node.real_path
                self._refresh_staging_content_list(node.real_path)
            else:
                self._organize_target_path = node.real_path
            self._update_organize_hint()
            # 整理模式下：选中 Mod 组文件夹 → 绑定装配面板
            # （非 Mod 组节点保持当前绑定，便于用户从其他目录拖入文件）
            self._maybe_bind_assembly_panel_for_tree_node(node)
            # 同步快速插入按钮可用性（目标路径可能已变）
            self._update_quick_insert_button_state()

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

    def _refresh_staging_content_list(self, staging_path: str) -> None:
        """刷新暂存区文件列表（递归遍历暂存区下所有文件与子目录）。

        阶段 3 Task 2：整理模式下中栏显示暂存区递归文件列表。
        若路径不存在或为空，显示友好提示。
        """
        try:
            entries = self._content_service.list_staging_entries(staging_path)
        except Exception:  # noqa: BLE001 - UI 边界需捕获所有异常
            logger.exception("加载暂存区文件列表失败：staging_path=%s", staging_path)
            entries = []

        self._content_list_model.refresh(entries)
        if not entries:
            # 路径不存在或为空：显示具体提示
            if not Path(staging_path).is_dir():
                self._content_empty_hint.setText(
                    ui.STAGING_LIST_PATH_INVALID.format(path=staging_path)
                )
            else:
                self._content_empty_hint.setText(ui.CONTENT_LIST_EMPTY_HINT)
        else:
            self._content_empty_hint.setText("")

    # --- 文件条目 ---

    def _on_entry_activated(self, index) -> None:  # noqa: ANN001 (Qt 信号)
        """双击文件条目。

        交互行为（2026-07-17 调整）：
        - 浏览模式下双击文件夹 → 进入该目录（无论是否内容单元，优先于元数据显示）。
          文件夹的元数据通过单击选中查看（_on_content_selection_changed）。
        - 双击文件类型内容单元（压缩包）→ 显示元数据面板。
        - 整理模式下双击 Mod 组文件夹（ContentUnit + is_dir）→ 绑定装配面板。
          （单击仅选中显示元数据，不切换装配面板，避免误触）
        - 整理模式下双击普通文件 / 普通文件夹 → 不响应。
        """
        entry = self._content_list_model.entry_at(index.row())
        if entry is None:
            return

        # 浏览模式下双击文件夹 → 进入该目录（优先于内容单元判断）
        # 文件夹即使被标记为内容单元（如 Mod 组），双击也进入目录；
        # 元数据通过单击查看。
        if entry.is_dir and self._mode_manager.is_browse():
            # 同步目录树选中节点到当前浏览目录（2026-07-17 修复）：
            # 原实现只刷新中栏，不更新 tree_view.selectionModel()，导致后续依赖
            # 该 selection 的刷新逻辑（_refresh_content_list_for_current_mode /
            # _refresh_content_list_after_scan / _refresh_content_for_current_tree_selection）
            # 误用陈旧的选中节点，中栏在标记内容单元后"退回"父目录显示。
            # 通过 find_index_by_path 找到对应节点并 setCurrentIndex，
            # 触发 _on_tree_selection_changed 完成中栏刷新 + 详情区更新。
            # 未找到节点时（如未扫描根目录的子项），回退到原保底逻辑手动刷新。
            target_idx = self._tree_model.find_index_by_path(self._tree_view, entry.path)
            if target_idx.isValid():
                self._tree_view.setCurrentIndex(target_idx)
                self._set_metadata_text(ui.METADATA_NOT_SELECTED)
            else:
                logger.warning(
                    "双击导航：未在目录树中找到匹配节点，回退到手动刷新：path=%s",
                    entry.path,
                )
                self._refresh_content_list(entry.path)
                self._set_metadata_text(ui.METADATA_NOT_SELECTED)
            return

        # 整理模式下双击 Mod 组文件夹 → 绑定装配面板
        # spec §7.4（2026-07-17 调整）：装配面板通过双击切换，单击仅选中
        if entry.is_dir and self._mode_manager.is_organize() and entry.content_unit is not None:
            self._bind_assembly_panel(entry.content_unit)
            return

        # 双击文件类型内容单元 → 显示元数据
        if entry.content_unit is not None:
            self._update_metadata(entry.content_unit)
            return

        # 其他情况（整理模式普通文件 / 普通文件夹）：不响应

    def _on_content_selection_changed(self, *args) -> None:  # noqa: N802, ANN001 (Qt 信号)
        """文件列表选中变化：单击选中内容单元 → 右侧立即显示元数据。

        交互优化（2026-07-15）：元数据作为"详情面板"，单击查看更符合
        资源管理器/IDE/DAM 软件的交互方式。
        - 选中内容单元 → 显示元数据。
        - 选中非内容单元 → 清空元数据面板（或保持现状，这里选择清空以避免误导）。
        - 整理模式下同样生效（暂存区列表中的内容单元也响应）。

        注（2026-07-17 调整）：单击不再切换装配面板绑定。装配面板切换
        通过双击 Mod 组文件夹触发（_on_entry_activated）。
        """
        sm = self._content_view.selectionModel()
        if sm is None:
            return
        indexes = sm.selectedRows()
        if not indexes:
            return
        # 只在单选时显示元数据（多选时清空避免混淆）
        if len(indexes) > 1:
            self._set_metadata_text(ui.METADATA_NOT_SELECTED)
            return
        entry = self._content_list_model.entry_at(indexes[0].row())
        if entry is None:
            return
        if entry.content_unit is not None:
            self._update_metadata(entry.content_unit)
        else:
            self._set_metadata_text(ui.METADATA_NOT_SELECTED)

    def _on_content_header_clicked(self, column: int) -> None:  # noqa: N802 (Qt 命名)
        """文件列表列头点击：切换排序键，同列再点切换升降序。

        阶段 3 Task 2：列头排序。点击不同列切换排序键；点击同列切换升降序。
        """
        from app.file_list_model import (
            SORT_MODIFIED,
            SORT_NAME,
            SORT_SIZE,
            SORT_TYPE,
        )

        key_map = {
            0: SORT_NAME,
            1: SORT_TYPE,
            2: SORT_SIZE,
            3: SORT_MODIFIED,
        }
        new_key = key_map.get(column)
        if new_key is None:
            return
        current_key = self._content_list_model.current_sort_key()
        if new_key == current_key:
            # 同列：翻转升降序
            self._content_list_model.set_sort_key(
                new_key, not self._content_list_model.is_sort_ascending()
            )
        else:
            # 不同列：切换排序键，默认升序
            self._content_list_model.set_sort_key(new_key, True)

    def _on_tree_context_menu(self, pos: QPoint) -> None:  # noqa: N802 (Qt 命名)
        """目录树右键菜单：标记/取消暂存区（阶段 3 Task 1）。

        仅当注入了 StagingService 时显示菜单。根据节点当前 is_staging 状态
        显示"标记为暂存区"或"取消暂存区标记"。
        """
        if self._staging_service is None:
            return
        index = self._tree_view.indexAt(pos)
        if not index.isValid():
            return
        node = self._tree_model.node_at(index)
        if node is None:
            return

        menu = QMenu(self)
        if node.is_staging:
            action = menu.addAction(ui.MENU_UNMARK_STAGING)
            chosen = menu.exec(self._tree_view.viewport().mapToGlobal(pos))
            if chosen is action:
                self._unmark_staging_from_node(node)
        else:
            action = menu.addAction(ui.MENU_MARK_STAGING)
            chosen = menu.exec(self._tree_view.viewport().mapToGlobal(pos))
            if chosen is action:
                self._mark_staging_from_node(node)

    def _mark_staging_from_node(self, node) -> None:
        """通过目录树节点标记暂存区。"""
        if self._staging_service is None:
            return
        try:
            self._staging_service.mark_staging(Path(node.real_path))
            self._commit()
            self._tree_service.refresh_staging_cache()
            self._tree_model.refresh()
            self.statusBar().showMessage("已标记为暂存区", 3000)
        except DuplicateStagingAreaError:
            QMessageBox.warning(self, "提示", "该目录已是暂存区。")
        except StagingAreaNestingError as e:
            QMessageBox.warning(self, "无法标记", f"暂存区不允许嵌套：\n{e}")
        except StagingAreaNotFoundError as e:
            QMessageBox.warning(self, "无法标记", f"路径无效：\n{e}")
        except Exception:  # noqa: BLE001
            logger.exception("标记暂存区失败")
            QMessageBox.critical(self, "错误", "标记暂存区失败，请查看日志。")

    def _unmark_staging_from_node(self, node) -> None:
        """通过目录树节点取消暂存区标记。"""
        if self._staging_service is None:
            return
        try:
            # 通过 is_staging + list_staging 找到对应记录 ID
            target_path = Path(node.real_path)
            staging_id: str | None = None
            for staging in self._staging_service.list_staging():
                if Path(staging.real_path) == target_path:
                    staging_id = staging.id
                    break
            if staging_id is None:
                QMessageBox.warning(self, "提示", "未找到该目录的暂存区标记。")
                return
            self._staging_service.unmark_staging(staging_id)
            self._commit()
            self._tree_service.refresh_staging_cache()
            self._tree_model.refresh()
            self.statusBar().showMessage("已取消暂存区标记", 3000)
        except StagingAreaNotFoundError:
            QMessageBox.warning(self, "提示", "该目录未标记为暂存区。")
        except Exception:  # noqa: BLE001
            logger.exception("取消暂存区标记失败")
            QMessageBox.critical(self, "错误", "取消暂存区标记失败，请查看日志。")

    def _on_content_context_menu(self, pos: QPoint) -> None:  # noqa: N802 (Qt 命名)
        """文件列表右键菜单：根据选中条目与模式动态构造。

        菜单项：
        - 创建 Mod 组：仅整理模式 + 单选文件 + 注入了 ModGroupService 时显示。
        - 加入装配：仅整理模式 + 单选文件（非目录）+ 装配面板已绑定 Mod 组时显示。
        - 标记为内容单元 / 把每个文件标记为内容单元：未标记条目。
        - 取消标记：已标记 ContentUnit。
        - 复制路径：始终显示。
        """
        # 取所有选中行（ExtendedSelection 支持多选）
        sm = self._content_view.selectionModel()
        if sm is None:
            return
        selected_rows = sm.selectedRows()
        if not selected_rows:
            return

        entries: list[FileEntry] = []
        for idx in selected_rows:
            entry = self._content_list_model.entry_at(idx.row())
            if entry is not None:
                entries.append(entry)
        if not entries:
            return

        menu = QMenu(self)
        actions: list[tuple[str, Callable[[], None]]] = []

        # 创建 Mod 组：仅整理模式 + 单选 + 文件（非目录）+ 注入了 ModGroupService
        if (
            self._mod_group_service is not None
            and self._mode_manager.is_organize()
            and len(entries) == 1
            and not entries[0].is_dir
        ):
            actions.append(
                (ui.MENU_CREATE_MOD_GROUP, lambda: self._on_create_mod_group(entries[0]))
            )

        # 加入装配：仅整理模式 + 单选 + 文件（非目录）+ 装配面板已绑定 Mod 组
        # spec §7.4（2026-07-17 调整）：取消拖拽方案，改用右键菜单触发 add_file
        if (
            self._assembly_service is not None
            and self._assembly_panel is not None
            and self._mode_manager.is_organize()
            and self._assembly_panel.current_unit() is not None
            and len(entries) == 1
            and not entries[0].is_dir
        ):
            actions.append(
                (ui.MENU_ADD_TO_ASSEMBLY, lambda: self._on_assembly_add_file(Path(entries[0].path)))
            )

        # 标记/取消标记
        if len(entries) == 1:
            entry = entries[0]
            if entry.content_unit is None:
                actions.append(
                    (ui.MENU_MARK_CONTENT_UNIT, lambda: self._on_mark_content_unit(entry))
                )
            else:
                actions.append(
                    (ui.MENU_UNMARK_CONTENT_UNIT, lambda: self._on_unmark_content_unit(entry))
                )
        else:
            # 多选：始终显示批量标记（已标记项在 handler 内跳过）
            actions.append(
                (
                    ui.MENU_BATCH_MARK_CONTENT_UNIT,
                    lambda: self._on_batch_mark_content_unit(entries),
                )
            )

        # 复制路径（始终）
        actions.append(
            (ui.CONTEXT_MENU_COPY_PATH, lambda: self._copy_path_to_clipboard(entries[0].path))
        )

        for label, _ in actions:
            menu.addAction(label)

        chosen = menu.exec(self._content_view.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        for label, handler in actions:
            if chosen.text() == label:
                handler()
                break

    def _copy_path_to_clipboard(self, path: str) -> None:
        """复制路径到剪贴板。"""
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(path)
        self.statusBar().showMessage(ui.CONTEXT_MENU_COPY_PATH_OK, 3000)

    def _on_create_mod_group(self, entry: FileEntry) -> None:
        """创建 Mod 组：弹出对话框选择/编辑名称，调用 ModGroupService。"""
        if self._mod_group_service is None:
            return
        if self._organize_workarea_path is None:
            QMessageBox.warning(self, ui.CREATE_MOD_GROUP_FAILED, "未选中暂存区工作区。")
            return

        # 提取两种命名选项
        from application.mod_group_service import extract_mod_name

        pure_name = extract_mod_name(entry.name)
        # 完整原名：去扩展名
        full_name = Path(entry.name).stem

        # 弹出对话框
        chosen_name = self._show_create_mod_group_dialog(pure_name, full_name)
        if chosen_name is None:
            return  # 用户取消

        try:
            unit = self._mod_group_service.create_mod_group(
                Path(entry.path),
                Path(self._organize_workarea_path),
                name=chosen_name,
            )
            self._commit()
            # 刷新目录树（新文件夹已写入 folder_cache）
            self._refresh_tree()
            # 刷新暂存区文件列表
            self._refresh_staging_content_list(self._organize_workarea_path)
            # 绑定装配面板到新创建的 Mod 组
            self._bind_assembly_panel(unit)
            self.statusBar().showMessage(
                ui.CREATE_MOD_GROUP_DEFAULT_OK.format(name=chosen_name), 3000
            )
        except ConflictError:
            self._rollback()
            QMessageBox.warning(
                self, ui.CREATE_MOD_GROUP_FAILED, f"目标文件夹已存在：{chosen_name}"
            )
        except ModGroupSourceNotInStagingError as e:
            self._rollback()
            QMessageBox.warning(self, ui.CREATE_MOD_GROUP_FAILED, f"源文件不在暂存区下：\n{e}")
        except InvalidModGroupNameError as e:
            self._rollback()
            QMessageBox.warning(self, ui.CREATE_MOD_GROUP_FAILED, f"名称无效：\n{e}")
        except FileOperationError as e:
            self._rollback()
            QMessageBox.warning(self, ui.CREATE_MOD_GROUP_FAILED, f"文件操作失败：\n{e}")
        except Exception:  # noqa: BLE001
            self._rollback()
            logger.exception("创建 Mod 组失败")
            QMessageBox.critical(self, ui.CREATE_MOD_GROUP_FAILED, "创建 Mod 组失败，请查看日志。")

    def _show_create_mod_group_dialog(self, pure_name: str, full_name: str) -> str | None:
        """弹出创建 Mod 组对话框，返回用户选择的名称；取消返回 None。

        下拉框直接以名称作为显示文本（不带"纯 Mod 名："等前缀），
        避免前缀被写入最终名称。若 pure_name == full_name 只添加一项。
        """
        dialog = QDialog(self)
        dialog.setWindowTitle(ui.CREATE_MOD_GROUP_DIALOG_TITLE)
        layout = QVBoxLayout(dialog)

        label = QLabel(ui.CREATE_MOD_GROUP_DIALOG_LABEL)
        layout.addWidget(label)

        combo = QComboBox()
        combo.setEditable(True)
        # 显示文本直接用名称，data 也存名称；选择后编辑框即为纯名称
        combo.addItem(pure_name, pure_name)
        if full_name != pure_name:
            combo.addItem(full_name, full_name)
        combo.setCurrentIndex(0)
        # 设置编辑框初始文本为纯 Mod 名
        combo.setEditText(pure_name)
        layout.addWidget(combo)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 优先返回用户编辑后的文本
            return combo.currentText().strip()
        return None

    def _on_mark_content_unit(self, entry: FileEntry) -> None:
        """标记单个条目为内容单元。"""
        try:
            self._content_service.mark_as_content_unit(Path(entry.path))
            self._commit()
            self._refresh_content_list_for_current_mode()
            self.statusBar().showMessage(ui.MARK_CONTENT_UNIT_OK, 3000)
        except InvalidContentUnitPathError as e:
            QMessageBox.warning(self, ui.MARK_CONTENT_UNIT_FAILED, f"路径无效：\n{e}")
        except Exception:  # noqa: BLE001
            logger.exception("标记内容单元失败")
            QMessageBox.critical(self, ui.MARK_CONTENT_UNIT_FAILED, "标记失败，请查看日志。")

    def _on_unmark_content_unit(self, entry: FileEntry) -> None:
        """取消单个条目的内容单元标记。"""
        if entry.content_unit is None:
            return
        try:
            self._content_service.unmark_content_unit(entry.content_unit.id)
            self._commit()
            self._refresh_content_list_for_current_mode()
            self.statusBar().showMessage(ui.UNMARK_CONTENT_UNIT_OK, 3000)
        except ContentUnitNotFoundError:
            QMessageBox.warning(
                self, ui.UNMARK_CONTENT_UNIT_FAILED, "内容单元不存在（可能已被删除）。"
            )
        except Exception:  # noqa: BLE001
            logger.exception("取消标记失败")
            QMessageBox.critical(self, ui.UNMARK_CONTENT_UNIT_FAILED, "取消标记失败，请查看日志。")

    def _on_batch_mark_content_unit(self, entries: list[FileEntry]) -> None:
        """批量标记多个条目为内容单元（各自独立，已标记项跳过）。"""
        success_count = 0
        failure_count = 0
        for entry in entries:
            if entry.content_unit is not None:
                continue  # 已标记，跳过
            try:
                self._content_service.mark_as_content_unit(Path(entry.path))
                success_count += 1
            except Exception:  # noqa: BLE001
                logger.exception("批量标记失败：path=%s", entry.path)
                failure_count += 1
        if success_count > 0:
            self._commit()
            self._refresh_content_list_for_current_mode()
            self.statusBar().showMessage(
                ui.BATCH_MARK_CONTENT_UNIT_OK.format(count=success_count), 3000
            )
        if failure_count > 0:
            QMessageBox.warning(
                self,
                ui.BATCH_MARK_CONTENT_UNIT_FAILED,
                f"{failure_count} 个文件标记失败，请查看日志。",
            )

    def _refresh_content_list_for_current_mode(self) -> None:
        """根据当前模式刷新中栏文件列表。"""
        if self._mode_manager.is_organize():
            if self._organize_workarea_path is not None:
                self._refresh_staging_content_list(self._organize_workarea_path)
        else:
            # 浏览模式：刷新当前目录树节点
            sm = self._tree_view.selectionModel()
            if sm is None:
                return
            indexes = sm.selectedIndexes()
            if not indexes:
                return
            node = self._tree_model.node_at(indexes[0])
            if node is not None:
                self._refresh_content_list(node.real_path)

    # --- 装配面板（阶段 3 Task 4） ---

    def _bind_assembly_panel(self, unit: ContentUnit | None) -> None:
        """绑定/解绑装配面板到指定 Mod 组 ContentUnit。

        - 整理模式：绑定 unit 时显示装配面板并刷新文件列表；unit 为 None 时隐藏面板。
        - 浏览模式：始终隐藏装配面板（spec §7.4：装配功能仅存在于整理模式）。
        - staging_path 取 self._organize_workarea_path（移除文件时移回该路径）。
        """
        if self._assembly_panel is None:
            return
        if not self._mode_manager.is_organize():
            self._assembly_panel.setVisible(False)
            return
        staging_path = (
            Path(self._organize_workarea_path) if self._organize_workarea_path is not None else None
        )
        self._assembly_panel.bind_mod_group(unit, staging_path)
        self._assembly_panel.setVisible(unit is not None)
        # 同步快速插入按钮可用性（Task 5）
        self._update_quick_insert_button_state()

    def _maybe_bind_assembly_panel_for_tree_node(self, node) -> None:  # noqa: ANN001 (内部)
        """整理模式下：若目录树节点对应一个 Mod 组 ContentUnit（文件夹类型），
        则绑定装配面板到该 ContentUnit；否则保持当前绑定不变。

        通过 ContentService.get_by_path 查询节点路径对应的 ContentUnit。
        仅当节点是文件夹且存在 ContentUnit 时绑定（spec §7.4）。
        """
        if self._assembly_panel is None:
            return
        if not self._mode_manager.is_organize():
            return
        try:
            unit = self._content_service.get_by_path(node.real_path)
        except Exception:  # noqa: BLE001
            logger.exception("查询 ContentUnit 失败：path=%s", node.real_path)
            return
        if unit is None or unit.status == "unmarked":
            return  # 非 Mod 组节点：保持当前绑定
        # 仅绑定文件夹类型的 ContentUnit（Mod 组本质是文件夹）
        try:
            is_dir = Path(unit.path).is_dir()
        except OSError:
            return
        if is_dir:
            self._bind_assembly_panel(unit)

    def _on_assembly_add_file(self, src_path: Path) -> None:
        """装配面板拖入文件：调用 AssemblyService.add_file + 刷新双方 + 提交。

        add_file 不自动重命名（spec §7.4：自动整理阶段不修改任何文件名）。
        """
        if self._assembly_service is None or self._assembly_panel is None:
            return
        unit = self._assembly_panel.current_unit()
        if unit is None:
            return
        try:
            self._assembly_service.add_file(unit.id, src_path)
            self._commit()
            self._assembly_panel.refresh_current()
            # 刷新暂存区文件列表（源文件已离开暂存区）
            if self._organize_workarea_path is not None:
                self._refresh_staging_content_list(self._organize_workarea_path)
            self.statusBar().showMessage(ui.ASSEMBLY_ADD_FILE_OK.format(name=src_path.name), 3000)
        except ConflictError:
            self._rollback()
            QMessageBox.warning(
                self,
                ui.ASSEMBLY_ADD_FILE_FAILED,
                f"目标已存在同名文件：{src_path.name}",
            )
        except FileOperationError as e:
            self._rollback()
            QMessageBox.warning(self, ui.ASSEMBLY_ADD_FILE_FAILED, f"文件操作失败：\n{e}")
        except Exception:  # noqa: BLE001
            self._rollback()
            logger.exception("装配面板加入文件失败")
            QMessageBox.critical(self, ui.ASSEMBLY_ADD_FILE_FAILED, "加入文件失败，请查看日志。")

    def _on_assembly_remove_file(self, filename: str) -> None:
        """装配面板移除文件：移回暂存区根目录 + 刷新双方 + 提交。

        remove_file 不保留原子目录结构（统一移到 staging_path 根目录）。
        """
        if self._assembly_service is None or self._assembly_panel is None:
            return
        unit = self._assembly_panel.current_unit()
        if unit is None:
            return
        if self._organize_workarea_path is None:
            QMessageBox.warning(self, ui.ASSEMBLY_REMOVE_FILE_FAILED, "未选中暂存区工作区。")
            return
        staging_path = Path(self._organize_workarea_path)
        try:
            self._assembly_service.remove_file(unit.id, filename, staging_path)
            self._commit()
            self._assembly_panel.refresh_current()
            self._refresh_staging_content_list(self._organize_workarea_path)
            self.statusBar().showMessage(ui.ASSEMBLY_REMOVE_FILE_OK.format(name=filename), 3000)
        except ConflictError:
            self._rollback()
            QMessageBox.warning(
                self,
                ui.ASSEMBLY_REMOVE_FILE_FAILED,
                f"暂存区已存在同名文件：{filename}",
            )
        except FileOperationError as e:
            self._rollback()
            QMessageBox.warning(self, ui.ASSEMBLY_REMOVE_FILE_FAILED, f"文件操作失败：\n{e}")
        except Exception:  # noqa: BLE001
            self._rollback()
            logger.exception("装配面板移除文件失败")
            QMessageBox.critical(self, ui.ASSEMBLY_REMOVE_FILE_FAILED, "移除文件失败，请查看日志。")

    def _on_assembly_rename_cover(self, image_path: Path) -> None:
        """装配面板右键重命名预览图：rename_as_cover + 刷新 + 提交。

        命名规则：单张 {Mod组名}.{扩展名}；多张 {Mod组名}_2、_3……；
        冲突走 ConflictError 流程（spec §7.4）。
        """
        if self._assembly_service is None or self._assembly_panel is None:
            return
        unit = self._assembly_panel.current_unit()
        if unit is None:
            return
        try:
            new_path = self._assembly_service.rename_as_cover(unit.id, image_path)
            self._commit()
            self._assembly_panel.refresh_current()
            self.statusBar().showMessage(
                ui.ASSEMBLY_RENAME_COVER_OK.format(name=new_path.name), 3000
            )
        except ConflictError:
            self._rollback()
            QMessageBox.warning(
                self,
                ui.ASSEMBLY_RENAME_COVER_FAILED,
                f"目标名称已存在：{image_path.name}",
            )
        except InvalidContentUnitPathError as e:
            self._rollback()
            QMessageBox.warning(self, ui.ASSEMBLY_RENAME_COVER_FAILED, f"无法重命名：\n{e}")
        except FileOperationError as e:
            self._rollback()
            QMessageBox.warning(self, ui.ASSEMBLY_RENAME_COVER_FAILED, f"文件操作失败：\n{e}")
        except Exception:  # noqa: BLE001
            self._rollback()
            logger.exception("装配面板重命名失败")
            QMessageBox.critical(self, ui.ASSEMBLY_RENAME_COVER_FAILED, "重命名失败，请查看日志。")

    def _on_assembly_closed(self) -> None:
        """关闭装配面板：隐藏（不解绑，便于用户再次打开时恢复）。"""
        if self._assembly_panel is not None:
            self._assembly_panel.setVisible(False)

    # --- 快速插入（阶段 3 Task 5） ---

    def _update_quick_insert_button_state(self) -> None:
        """根据当前状态更新「快速插入」按钮可用性。

        可用条件（全部满足）：
        - 整理模式
        - 装配面板已绑定 Mod 组（current_unit 不为 None）
        - 目录树选中了目标路径（_organize_target_path 不为 None）
        - 目标路径与源 Mod 组位置不同
        - 目标路径是目录
        - 目标路径不是源 Mod 组的子目录（不能移到自身内部）
        """
        if not self._mode_manager.is_organize():
            self._quick_insert_button.setEnabled(False)
            return
        if self._assembly_panel is None or self._assembly_panel.current_unit() is None:
            self._quick_insert_button.setEnabled(False)
            return
        if self._organize_target_path is None:
            self._quick_insert_button.setEnabled(False)
            return
        # 目标与源相同 / 目标不是目录 / 目标在源子树内：按钮禁用
        unit = self._assembly_panel.current_unit()
        src_folder = Path(unit.path)
        target = Path(self._organize_target_path)
        try:
            if not target.is_dir():
                self._quick_insert_button.setEnabled(False)
                return
            # 源父目录 == 目标 → 已经在该目录下，无需移动
            if src_folder.parent == target:
                self._quick_insert_button.setEnabled(False)
                return
            # 目标在源子树内 → 禁用（SelfSubdirectoryError）
            import os

            sep = os.sep
            src_str = str(src_folder).rstrip(sep) + sep
            if str(target).startswith(src_str):
                self._quick_insert_button.setEnabled(False)
                return
        except OSError:
            self._quick_insert_button.setEnabled(False)
            return
        self._quick_insert_button.setEnabled(True)

    def _on_quick_insert_clicked(self) -> None:
        """快速插入按钮点击：弹出确认 → 调用 QuickInsertService → 刷新 UI。

        安全规则（spec §6.1）：
        - 移动前弹出确认对话框（显示源路径 → 目标路径）。
        - 跨盘 / 子目录 / 冲突等错误转为用户可读提示。
        - 成功后：解绑装配面板 + 刷新目录树 + 刷新暂存区列表 + 状态栏提示。
        """
        if self._quick_insert_service is None or self._assembly_panel is None:
            return
        unit = self._assembly_panel.current_unit()
        if unit is None:
            QMessageBox.information(self, ui.QUICK_INSERT_FAILED, ui.QUICK_INSERT_NO_BINDING)
            return
        if self._organize_target_path is None:
            QMessageBox.information(self, ui.QUICK_INSERT_FAILED, ui.QUICK_INSERT_NO_TARGET)
            return

        src_folder = Path(unit.path)
        target_dir = Path(self._organize_target_path)

        # 二次校验目标有效性（按钮状态可能因文件系统变化而过时）
        try:
            if not target_dir.is_dir():
                QMessageBox.warning(self, ui.QUICK_INSERT_FAILED, ui.QUICK_INSERT_TARGET_NOT_DIR)
                return
            if src_folder.parent == target_dir:
                QMessageBox.information(
                    self, ui.QUICK_INSERT_FAILED, ui.QUICK_INSERT_SAME_AS_SOURCE
                )
                return
        except OSError as e:
            QMessageBox.warning(self, ui.QUICK_INSERT_FAILED, f"无法访问路径：\n{e}")
            return

        dst_folder = target_dir / src_folder.name

        # 弹出确认对话框
        confirm_text = ui.QUICK_INSERT_CONFIRM_TEXT.format(src=str(src_folder), dst=str(dst_folder))
        reply = QMessageBox.question(
            self,
            ui.QUICK_INSERT_CONFIRM_TITLE,
            confirm_text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # 调用 QuickInsertService
        try:
            updated_unit = self._quick_insert_service.quick_insert(unit.id, target_dir)
            self._commit()
        except ConflictError:
            self._rollback()
            QMessageBox.warning(self, ui.QUICK_INSERT_FAILED, ui.QUICK_INSERT_CONFLICT_HINT)
            return
        except CrossDriveError:
            self._rollback()
            QMessageBox.warning(self, ui.QUICK_INSERT_FAILED, ui.QUICK_INSERT_CROSS_DRIVE_HINT)
            return
        except SelfSubdirectoryError:
            self._rollback()
            QMessageBox.warning(self, ui.QUICK_INSERT_FAILED, ui.QUICK_INSERT_SELF_SUBDIR_HINT)
            return
        except FileOperationError as e:
            self._rollback()
            QMessageBox.warning(self, ui.QUICK_INSERT_FAILED, f"文件操作失败：\n{e}")
            return
        except Exception:  # noqa: BLE001
            self._rollback()
            logger.exception("快速插入失败")
            QMessageBox.critical(self, ui.QUICK_INSERT_FAILED, "快速插入失败，请查看日志。")
            return

        # 成功后 UI 刷新：
        # 1. 解绑装配面板（Mod 组已移走，原路径不再有效）
        self._assembly_panel.bind_mod_group(None, None)
        self._assembly_panel.setVisible(False)
        # 2. 刷新目录树（源目录和目标目录都变了）
        self._refresh_tree()
        # 3. 刷新暂存区列表（Mod 组已离开暂存区）
        if self._organize_workarea_path is not None:
            self._refresh_staging_content_list(self._organize_workarea_path)
        # 4. 更新按钮状态
        self._update_quick_insert_button_state()
        # 5. 状态栏提示
        self.statusBar().showMessage(
            ui.QUICK_INSERT_OK.format(name=updated_unit.title, target=str(target_dir)),
            5000,
        )

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
        """QThread 真正退出后清理 Python 引用。

        仅当退出的线程是当前扫描线程（self._thread）时才清除引用，
        避免旧线程退出时误清除新扫描线程的引用（TD-H4 竞态修复）。

        竞态场景：扫描完成 → _on_scan_finished 恢复按钮 → 用户立即点击扫描
        → 新 QThread 覆盖 self._thread → 旧线程退出触发本方法。
        若不校验 sender，会盲目清除指向新扫描的引用，导致 closeEvent
        无法等待新线程（TD-H5 崩溃风险）。
        """
        sender = self.sender()
        if sender is self._thread:
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
        - 整理模式：若有暂存区工作区，重新读取该暂存区递归文件列表。
        - 否则：无操作。
        """
        if self._mode_manager.is_organize():
            workarea = self._organize_workarea_path
            if workarea is not None:
                self._refresh_staging_content_list(workarea)
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
        """模式变化时更新 UI 状态与中栏提示。

        阶段 3 Task 4（2026-07-17 调整：取消拖拽方案）：
        - 整理模式：装配面板按当前绑定显隐。
        - 浏览模式：隐藏装配面板（spec §7.4）。

        阶段 3 Task 5：快速插入按钮在整理模式可见，浏览模式隐藏。
        """
        if mode == AppMode.organize:
            # 切换到整理模式：若当前选中节点是 [S] 则加载暂存区递归列表
            self._enter_organize_mode()
            self._update_organize_hint()
            # 装配面板显隐：根据当前绑定（无绑定时隐藏）
            if self._assembly_panel is not None:
                self._assembly_panel.setVisible(self._assembly_panel.current_unit() is not None)
            # 快速插入按钮：整理模式可见（可用性由 _update_quick_insert_button_state 控制）
            self._quick_insert_button.setVisible(True)
            self._update_quick_insert_button_state()
        else:
            # 切换回浏览模式：恢复跟随目录树刷新
            self._organize_workarea_path = None
            self._organize_target_path = None
            self._set_mode_hint_text(ui.MODE_BROWSE_HINT)
            # 恢复显示当前选中目录树节点的内容
            self._refresh_content_for_current_tree_selection()
            # 隐藏装配面板
            if self._assembly_panel is not None:
                self._assembly_panel.setVisible(False)
            # 隐藏快速插入按钮
            self._quick_insert_button.setVisible(False)

    def _enter_organize_mode(self) -> None:
        """进入整理模式：根据当前选中节点状态加载中栏。

        - 当前选中节点是 [S]：加载该暂存区递归列表，工作区=目标=该节点路径。
        - 当前选中节点非 [S] 或无选中：工作区为 None，中栏显示
          "请在目录树中选中一个暂存区 [S] 节点" 提示，清空文件列表。
        """
        sm = self._tree_view.selectionModel()
        indexes = sm.selectedIndexes() if sm is not None else []
        if not indexes:
            self._organize_workarea_path = None
            self._content_list_model.refresh([])
            self._content_empty_hint.setText(ui.STAGING_LIST_NO_STAGING_SELECTED)
            return
        node = self._tree_model.node_at(indexes[0])
        if node is None:
            self._organize_workarea_path = None
            self._content_list_model.refresh([])
            self._content_empty_hint.setText(ui.STAGING_LIST_NO_STAGING_SELECTED)
            return
        if node.is_staging:
            # 选中节点是暂存区：加载递归列表
            self._organize_workarea_path = node.real_path
            self._organize_target_path = node.real_path
            self._refresh_staging_content_list(node.real_path)
        else:
            # 选中节点不是暂存区：清空中栏，提示用户选中 [S] 节点
            self._organize_workarea_path = None
            self._organize_target_path = node.real_path
            self._content_list_model.refresh([])
            self._content_empty_hint.setText(ui.STAGING_LIST_NO_STAGING_SELECTED)

    def _update_organize_hint(self) -> None:
        """更新整理模式下的中栏顶部提示（走 Elide 流程）。"""
        if self._organize_workarea_path is None:
            # 无暂存区工作区：显示"请选中 [S] 节点"提示（可能附带目标路径）
            target = self._organize_target_path
            if target is not None:
                target_hint = ui.MODE_ORGANIZE_TARGET_HINT.format(path=target)
                self._set_mode_hint_text(f"{ui.STAGING_LIST_NO_STAGING_SELECTED}\n{target_hint}")
            else:
                self._set_mode_hint_text(ui.STAGING_LIST_NO_STAGING_SELECTED)
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

    # --- 装配面板测试接口（阶段 3 Task 4） ---

    def assembly_panel_visible(self) -> bool:
        """返回装配面板当前是否可见（供测试）。

        使用 not isHidden() 而非 isVisible()：isVisible() 要求父组件也可见，
        在测试环境中主窗口未 show() 时始终返回 False；isHidden() 仅反映
        setVisible(False) 的显式调用，符合测试需求。
        """
        if self._assembly_panel is None:
            return False
        return not self._assembly_panel.isHidden()

    def assembly_panel_current_unit_id(self) -> str | None:
        """返回装配面板当前绑定的 Mod 组 ContentUnit ID（供测试）。"""
        if self._assembly_panel is None:
            return None
        unit = self._assembly_panel.current_unit()
        return unit.id if unit is not None else None

    def assembly_panel_entry_count(self) -> int:
        """返回装配面板当前文件列表条数（供测试）。"""
        if self._assembly_panel is None:
            return 0
        return self._assembly_panel.entry_count()
