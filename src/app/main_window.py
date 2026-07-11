"""主窗口。阶段 2 Task 1/Task 2/Task 3：工作台骨架、根目录扫描、只读目录树、素材池与 Mod 组装。

布局（三栏骨架）：
- 左栏：受管理根目录列表 + 添加目录/扫描按钮 + 扫描状态 + 受管理目录树 + 选中目录详情。
- 中栏：未归类素材池 + Mod 条目列表 + 新建/关联按钮。
- 右栏：Mod 条目详情编辑（元数据）+ 成员列表表格（角色/移除）。

约束（AGENTS 规则 3）：
- UI 不直接调用 shutil / Path.rename / Path.unlink 等文件写 API。
- 添加根目录只写应用数据库；不移动、不复制、不修改该目录。
- 扫描通过 ScanWorker 在后台线程执行，不冻结 UI。
- 扫描期间禁用重复扫描入口。
- 目录树数据源为 SQLite FolderNode，不在 UI 线程临时递归真实文件系统。
- 目录树严格只读：不实现拖拽移动、右键文件操作、重命名/删除/新建。
- 素材池与 Mod 组装只写应用数据库关联；不移动、不复制、不删除真实文件（Task 3）。
- 成员角色编辑通过 ModAssemblyService.set_member_role；UI 不复制关联规则。
- 移除成员只解除关联，不删除 FileAsset 记录。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from app.folder_tree_model import FolderTreeModel
from app.pool_model import (
    ROLE_DISPLAY_NAMES,
    ROLE_ORDER,
    ModItemListModel,
    UnassociatedPoolModel,
)
from app.scan_worker import ScanWorker
from app.thumbnail_worker import ThumbnailWorker
from application.errors import (
    ApplicationError,
    DuplicateManagedRootError,
    InvalidRootPathError,
    ManagedRootNotFoundError,
)
from application.folder_tree_service import FolderTreeService, TreeNode
from application.managed_root_service import ManagedRootService
from application.mod_assembly_service import ModAssemblyService
from application.scan_workflow_service import ScanSummary
from application.thumbnail_coordinator import ThumbnailCoordinator
from domain.models import AssetKind, FileRole, ManagedRoot, ModItem
from infrastructure.thumbnail_generator import ThumbnailStatus

logger = logging.getLogger(__name__)

# 错误摘要最多展示条数
MAX_ERROR_SUMMARY_LINES = 5

# 成员表格列索引
_COL_FILENAME = 0
_COL_KIND = 1
_COL_ROLE = 2
_COL_PATH = 3
_COL_COVER = 4
_COL_ACTION = 5

# 缩略图预览尺寸（详情区封面预览）
_COVER_PREVIEW_SIZE = 128


class MainWindow(QMainWindow):
    """应用主窗口。

    通过构造注入 ManagedRootService、FolderTreeService 与 db_path，便于测试。
    db_path 用于 ScanWorker 在后台线程创建独立连接。
    """

    def __init__(
        self,
        managed_root_service: ManagedRootService,
        folder_tree_service: FolderTreeService,
        mod_assembly_service: ModAssemblyService,
        db_path: Path,
        thumbnail_coordinator: ThumbnailCoordinator | None = None,
        commit_callback: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = managed_root_service
        self._tree_service = folder_tree_service
        self._mod_service = mod_assembly_service
        self._db_path = db_path
        self._thumbnail_coord = thumbnail_coordinator
        self._commit_callback = commit_callback
        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None
        self._is_scanning = False
        # 当前选中的 ModItem（供详情编辑与关联操作使用）
        self._current_mod_id: str | None = None
        # 缩略图后台线程
        self._thumb_thread: QThread | None = None
        self._thumb_worker: ThumbnailWorker | None = None

        self.setWindowTitle(ui.APP_TITLE)
        self.resize(ui.WINDOW_DEFAULT_WIDTH, ui.WINDOW_DEFAULT_HEIGHT)

        self._setup_ui()
        self._refresh_root_list()
        self._refresh_tree()
        self._refresh_pool()
        self._refresh_mod_list()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """关闭窗口前等待后台线程退出，避免 QThread Running 状态析构 CTD。"""
        if self._thumb_thread is not None and self._thumb_thread.isRunning():
            self._thumb_thread.quit()
            self._thumb_thread.wait(5000)
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)
        super().closeEvent(event)

    def _commit(self) -> None:
        """提交当前数据库事务。

        UI 层是用户操作的天然事务边界：每次写操作（创建/关联/角色/移除/元数据）
        完成后调用，确保数据持久化。service/repository 不自提交，以保持分层与
        多操作事务的原子性。
        """
        if self._commit_callback is not None:
            try:
                self._commit_callback()
            except Exception:  # noqa: BLE001
                logger.exception("数据库提交失败")

    # --- UI 构建 ---

    def _setup_ui(self) -> None:
        splitter = QSplitter(Qt.Horizontal)

        # === 左栏：受管理根目录 + 扫描状态 + 目录树 + 目录详情 ===
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

        self._scan_button = QPushButton(ui.SCAN_BUTTON)
        self._scan_button.clicked.connect(self._on_scan)
        self._scan_button.setEnabled(False)
        roots_layout.addWidget(self._scan_button)
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
        self._tree_view.setSelectionMode(QTreeView.SelectionMode.SingleSelection)
        self._tree_view.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        # 禁用拖拽：目录树严格只读
        self._tree_view.setDragEnabled(False)
        self._tree_view.setAcceptDrops(False)
        self._tree_view.setDropIndicatorShown(False)
        self._tree_view.setDragDropMode(QTreeView.DragDropMode.NoDragDrop)
        self._tree_model = FolderTreeModel(self._tree_service)
        self._tree_view.setModel(self._tree_model)
        self._tree_view.selectionModel().selectionChanged.connect(self._on_tree_selection_changed)
        tree_layout.addWidget(self._tree_view)

        self._tree_hint = QLabel(ui.TREE_EMPTY_HINT)
        self._tree_hint.setWordWrap(True)
        tree_layout.addWidget(self._tree_hint)
        left_layout.addWidget(self._tree_group, stretch=1)

        # 选中目录详情区域
        self._detail_group = QGroupBox(ui.DETAIL_GROUP_TITLE)
        detail_layout = QVBoxLayout(self._detail_group)
        self._detail_label = QLabel(ui.DETAIL_NONE_HINT)
        self._detail_label.setWordWrap(True)
        self._detail_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        detail_layout.addWidget(self._detail_label)
        left_layout.addWidget(self._detail_group)

        splitter.addWidget(left)

        # === 中栏：素材池 + ModItem 列表 ===
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)

        # 素材池
        self._pool_group = QGroupBox(ui.POOL_GROUP_TITLE)
        pool_layout = QVBoxLayout(self._pool_group)
        self._pool_model = UnassociatedPoolModel(self._mod_service)
        self._pool_view = QListView()
        self._pool_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._pool_view.setModel(self._pool_model)
        self._pool_view.selectionModel().selectionChanged.connect(self._on_pool_selection_changed)
        pool_layout.addWidget(self._pool_view)

        self._pool_hint = QLabel(ui.POOL_EMPTY_HINT)
        self._pool_hint.setWordWrap(True)
        pool_layout.addWidget(self._pool_hint)
        center_layout.addWidget(self._pool_group, stretch=3)

        # Mod 条目列表 + 操作按钮
        mod_list_box = QGroupBox(ui.MOD_LIST_GROUP_TITLE)
        mod_list_layout = QVBoxLayout(mod_list_box)
        self._mod_list_model = ModItemListModel(self._mod_service)
        self._mod_list_view = QListView()
        self._mod_list_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._mod_list_view.setModel(self._mod_list_model)
        self._mod_list_view.selectionModel().selectionChanged.connect(
            self._on_mod_selection_changed
        )
        mod_list_layout.addWidget(self._mod_list_view)

        self._mod_list_hint = QLabel(ui.MOD_LIST_EMPTY_HINT)
        self._mod_list_hint.setWordWrap(True)
        mod_list_layout.addWidget(self._mod_list_hint)

        # 新建 + 关联按钮行
        action_row = QHBoxLayout()
        self._new_mod_button = QPushButton(ui.NEW_MOD_BUTTON)
        self._new_mod_button.clicked.connect(self._on_new_mod)
        self._new_mod_button.setEnabled(False)
        action_row.addWidget(self._new_mod_button)

        self._associate_button = QPushButton(ui.ASSOCIATE_BUTTON)
        self._associate_button.clicked.connect(self._on_associate)
        self._associate_button.setEnabled(False)
        action_row.addWidget(self._associate_button)
        mod_list_layout.addLayout(action_row)

        center_layout.addWidget(mod_list_box, stretch=2)

        splitter.addWidget(center)

        # === 右栏：ModItem 详情编辑 + 成员列表 ===
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Mod 条目详情编辑区域（Task 3）
        self._mod_detail_group = QGroupBox(ui.MOD_DETAIL_GROUP_TITLE)
        mod_detail_layout = QVBoxLayout(self._mod_detail_group)

        self._mod_detail_hint = QLabel(ui.MOD_DETAIL_NONE_HINT)
        self._mod_detail_hint.setWordWrap(True)
        mod_detail_layout.addWidget(self._mod_detail_hint)

        # 元数据编辑表单
        form_row1 = QHBoxLayout()
        form_row1.addWidget(QLabel(ui.MOD_DETAIL_NAME_LABEL))
        self._name_edit = QLineEdit()
        form_row1.addWidget(self._name_edit, stretch=1)
        mod_detail_layout.addLayout(form_row1)

        mod_detail_layout.addWidget(QLabel(ui.MOD_DETAIL_DESC_LABEL))
        self._desc_edit = QTextEdit()
        self._desc_edit.setMaximumHeight(60)
        mod_detail_layout.addWidget(self._desc_edit)

        form_row3 = QHBoxLayout()
        form_row3.addWidget(QLabel(ui.MOD_DETAIL_URL_LABEL))
        self._url_edit = QLineEdit()
        form_row3.addWidget(self._url_edit, stretch=1)
        mod_detail_layout.addLayout(form_row3)

        form_row4 = QHBoxLayout()
        form_row4.addWidget(QLabel(ui.MOD_DETAIL_TAGS_LABEL))
        self._tags_edit = QLineEdit()
        self._tags_edit.setPlaceholderText("用逗号分隔，例如：护甲,魔法,沉浸式")
        form_row4.addWidget(self._tags_edit, stretch=1)
        mod_detail_layout.addLayout(form_row4)

        self._save_meta_button = QPushButton(ui.MOD_DETAIL_SAVE_BUTTON)
        self._save_meta_button.clicked.connect(self._on_save_metadata)
        self._save_meta_button.setEnabled(False)
        mod_detail_layout.addWidget(self._save_meta_button)

        # 封面预览（Task 4）
        cover_box = QGroupBox(ui.COVER_PREVIEW_TITLE)
        cover_layout = QHBoxLayout(cover_box)
        self._cover_label = QLabel(ui.COVER_PREVIEW_NONE_HINT)
        self._cover_label.setWordWrap(True)
        self._cover_label.setAlignment(Qt.AlignCenter)
        self._cover_label.setMinimumSize(_COVER_PREVIEW_SIZE, _COVER_PREVIEW_SIZE)
        self._cover_label.setStyleSheet("border: 1px solid #ccc;")
        cover_layout.addWidget(self._cover_label)
        mod_detail_layout.addWidget(cover_box)

        right_layout.addWidget(self._mod_detail_group, stretch=1)

        # 成员列表表格（Task 3）
        self._members_group = QGroupBox(ui.MEMBERS_GROUP_TITLE)
        members_layout = QVBoxLayout(self._members_group)
        self._members_hint = QLabel(ui.MEMBERS_EMPTY_HINT)
        self._members_hint.setWordWrap(True)
        members_layout.addWidget(self._members_hint)

        self._members_table = QTableWidget(0, 6)
        self._members_table.setHorizontalHeaderLabels(
            [
                ui.MEMBERS_COL_FILENAME,
                ui.MEMBERS_COL_KIND,
                ui.MEMBERS_COL_ROLE,
                ui.MEMBERS_COL_PATH,
                ui.MEMBERS_COL_COVER,
                ui.MEMBERS_COL_ACTION,
            ]
        )
        self._members_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._members_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._members_table.horizontalHeader().setStretchLastSection(False)
        self._members_table.setColumnWidth(_COL_FILENAME, 180)
        self._members_table.setColumnWidth(_COL_KIND, 60)
        self._members_table.setColumnWidth(_COL_ROLE, 100)
        self._members_table.setColumnWidth(_COL_COVER, 80)
        self._members_table.setColumnWidth(_COL_ACTION, 80)
        members_layout.addWidget(self._members_table)

        right_layout.addWidget(self._members_group, stretch=2)

        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 1)

        self.setCentralWidget(splitter)

    # --- 根目录列表 ---

    def _refresh_root_list(self) -> None:
        """从服务重新加载根目录列表，并同步刷新目录树。"""
        self._root_list.clear()
        roots = self._service.list_roots()
        for root in roots:
            self._add_root_item(root)
        self._empty_hint.setVisible(len(roots) == 0)
        self._on_selection_changed()
        self._refresh_tree()

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
        self._remove_button.setEnabled(has_selection and not self._is_scanning)

    # --- 目录树 ---

    def _refresh_tree(self) -> None:
        """从 FolderTreeService 重新加载目录树。"""
        self._tree_model.refresh()
        root_count = self._tree_model.root_node_count()
        self._tree_hint.setVisible(root_count == 0)

    def _on_tree_selection_changed(self, *args) -> None:  # noqa: ARG002
        """目录树选中变化时更新详情区域。"""
        indexes = self._tree_view.selectedIndexes()
        if not indexes:
            self._detail_label.setText(ui.DETAIL_NONE_HINT)
            return
        index = indexes[0]
        self._update_detail(index)

    def _update_detail(self, index) -> None:
        """根据选中节点更新详情文本。"""
        node = self._tree_model.node_at(index)
        if node is None:
            self._detail_label.setText(ui.DETAIL_NONE_HINT)
            return
        self._detail_label.setText(self._format_detail(node))

    def _format_detail(self, node: TreeNode) -> str:
        """格式化详情文本。"""
        if node.category == "managed_root":
            category_text = ui.DETAIL_CATEGORY_ROOT
        elif node.category == "unscanned_root":
            category_text = ui.DETAIL_CATEGORY_UNSCANNED
        else:
            category_text = ui.DETAIL_CATEGORY_FOLDER

        # 子目录数量：未扫描根目录为 0，其余查询 DB
        children_count = self._tree_service.count_children(node.node_id)

        lines = [
            f"{ui.DETAIL_NAME_LABEL}：{node.display_name}",
            f"{ui.DETAIL_PATH_LABEL}：{node.real_path}",
            f"{ui.DETAIL_IS_ROOT_LABEL}：{'是' if node.is_managed_root else '否'}",
            f"类型：{category_text}",
            f"{ui.DETAIL_CHILDREN_COUNT_LABEL}：{children_count}",
        ]
        if node.category == "unscanned_root":
            lines.append("")
            lines.append(ui.TREE_UNSCANNED_HINT)
        return "\n".join(lines)

    def detail_text(self) -> str:
        """返回当前详情文本（供测试）。"""
        return self._detail_label.text()

    def tree_root_count(self) -> int:
        """返回目录树顶层节点数（供测试）。"""
        return self._tree_model.root_node_count()

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

    # --- 移除根目录配置 ---

    def _on_remove_root(self) -> None:
        """移除选中的受管理根目录配置。

        仅删除应用数据库中的 managed_root 记录；不删除、不移动、不修改
        磁盘上的任何用户文件；不清理 folder_node / file_asset 扫描记录。
        """
        if self._is_scanning:
            return
        root_id = self._selected_root_id()
        if root_id is None:
            self._set_status(ui.ERR_NO_ROOT_SELECTED)
            return

        # 取出 real_path 用于确认对话框展示
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
        except ManagedRootNotFoundError:
            # 可能已被其他路径移除，刷新列表即可
            self._refresh_root_list()
            return
        except Exception as e:  # noqa: BLE001 - UI 边界需捕获所有异常
            logger.exception("移除根目录配置失败")
            QMessageBox.critical(
                self, ui.ERR_REMOVE_ROOT_FAILED, f"{ui.ERR_REMOVE_ROOT_FAILED}：{e}"
            )
            return

        self._refresh_root_list()

    # --- 扫描 ---

    def _on_scan(self) -> None:
        """启动后台扫描。扫描期间禁用扫描入口。"""
        if self._is_scanning:
            return
        root_id = self._selected_root_id()
        if root_id is None:
            self._set_status(ui.ERR_NO_ROOT_SELECTED)
            return

        self._begin_scanning()

        self._thread = QThread()
        self._worker = ScanWorker(self._db_path, root_id)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        # 先连 thread.quit，确保扫描完成/失败信号触发后线程尽快请求退出，
        # 再连 UI 处理槽。quit 是异步请求，实际退出由 thread.finished 信号通知。
        self._worker.scan_started.connect(self._on_scan_started)
        self._worker.scan_finished.connect(self._thread.quit)
        self._worker.scan_failed.connect(self._thread.quit)
        self._worker.scan_finished.connect(self._on_scan_finished)
        self._worker.scan_failed.connect(self._on_scan_failed)
        # 线程真正退出后再清理 worker/thread，避免 Running 状态下析构导致 CTD。
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _begin_scanning(self) -> None:
        self._is_scanning = True
        self._scan_button.setText(ui.SCAN_BUTTON_SCANNING)
        self._scan_button.setEnabled(False)
        self._add_button.setEnabled(False)
        self._remove_button.setEnabled(False)
        self._set_status(ui.STATUS_SCANNING)

    def _end_scanning(self) -> None:
        """恢复按钮状态。不在此处清空 _worker / _thread 引用——
        QThread 析构必须由 thread.finished 信号触发（_on_thread_finished），
        否则 Running 状态下析构会导致进程 CTD。
        """
        self._is_scanning = False
        self._scan_button.setText(ui.SCAN_BUTTON)
        self._add_button.setEnabled(True)
        has_selection = self._selected_root_id() is not None
        self._scan_button.setEnabled(has_selection)
        self._remove_button.setEnabled(has_selection)

    def _on_thread_finished(self) -> None:
        """QThread 真正退出后清理 Python 引用，让 deleteLater 生效。"""
        self._worker = None
        self._thread = None

    def _on_scan_started(self) -> None:
        self._set_status(ui.STATUS_SCANNING)

    def _on_scan_finished(self, summary: ScanSummary) -> None:
        """扫描完成：展示摘要并刷新目录树。该方法可独立测试。"""
        text = ui.format_summary(
            folders=summary.scanned_folders,
            files=summary.scanned_files,
            persisted_folders=summary.persisted_folders,
            persisted_files=summary.persisted_files,
            errors=summary.error_count,
        )
        if summary.error_count > 0:
            lines = [text, ""]
            lines.append(ui.SUMMARY_ERRORS_PREFIX.format(n=MAX_ERROR_SUMMARY_LINES))
            for err in summary.errors[:MAX_ERROR_SUMMARY_LINES]:
                lines.append(f"• {err.path}：{err.reason}")
            if summary.error_count > MAX_ERROR_SUMMARY_LINES:
                lines.append(f"…（共 {summary.error_count} 个错误）")
            text = "\n".join(lines)
        self._set_status(f"{ui.STATUS_SCAN_COMPLETE}\n{text}")
        self._end_scanning()
        # 扫描完成刷新目录树以展示新加载的 FolderNode
        self._refresh_tree()
        # 扫描后新素材进入素材池
        self._refresh_pool()

    def _on_scan_failed(self, message: str) -> None:
        self._set_status(f"{ui.STATUS_SCAN_FAILED}\n{message}")
        self._end_scanning()
        # 扫描失败仍刷新目录树（根目录可能已配置但无扫描数据）
        self._refresh_tree()
        self._refresh_pool()

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
        """返回扫描按钮是否可用（供测试）。"""
        return self._scan_button.isEnabled()

    def is_remove_button_enabled(self) -> bool:
        """返回移除按钮是否可用（供测试）。"""
        return self._remove_button.isEnabled()

    # === Task 3：素材池 / ModItem 组装 ===

    def _refresh_pool(self) -> None:
        """从未关联素材重新加载素材池。"""
        self._pool_model.refresh()
        count = self._pool_model.asset_count()
        self._pool_hint.setVisible(count == 0)
        self._update_associate_button()
        self._update_new_mod_button()

    def _refresh_mod_list(self) -> None:
        """重新加载 ModItem 列表。"""
        self._mod_list_model.refresh()
        count = self._mod_list_model.item_count()
        self._mod_list_hint.setVisible(count == 0)
        # 刷新后若当前选中的 ModItem 不再存在，清空选择
        if self._current_mod_id is not None:
            remaining_ids = {
                self._mod_list_model.mod_item_id_at(i)
                for i in range(self._mod_list_model.item_count())
            }
            if self._current_mod_id not in remaining_ids:
                self._current_mod_id = None
                self._clear_mod_detail()
        self._update_associate_button()
        # 刷新封面图标
        self._refresh_cover_icons()

    def pool_count(self) -> int:
        """返回素材池当前素材数（供测试）。"""
        return self._pool_model.asset_count()

    def mod_list_count(self) -> int:
        """返回 ModItem 列表条数（供测试）。"""
        return self._mod_list_model.item_count()

    def _selected_asset_ids(self) -> list[str]:
        """返回素材池中当前选中的 asset_id 列表。"""
        rows = {idx.row() for idx in self._pool_view.selectedIndexes()}
        ids: list[str] = []
        for row in sorted(rows):
            asset_id = self._pool_model.asset_id_at(row)
            if asset_id is not None:
                ids.append(asset_id)
        return ids

    def _update_associate_button(self) -> None:
        """根据素材池与 ModItem 列表选择状态更新关联按钮。"""
        has_assets = len(self._selected_asset_ids()) > 0
        has_mod = self._current_mod_id is not None
        self._associate_button.setEnabled(has_assets and has_mod)

    def _update_new_mod_button(self) -> None:
        """根据素材池选择状态更新新建按钮。"""
        has_assets = len(self._selected_asset_ids()) > 0
        self._new_mod_button.setEnabled(has_assets and not self._is_scanning)

    def _on_pool_selection_changed(self, *args) -> None:  # noqa: ARG002
        """素材池选择变化时更新按钮状态。"""
        self._update_associate_button()
        self._update_new_mod_button()

    def _on_mod_selection_changed(self, *args) -> None:  # noqa: ARG002
        """ModItem 列表选中变化时加载详情与成员。"""
        rows = self._mod_list_view.selectedIndexes()
        if not rows:
            self._current_mod_id = None
            self._clear_mod_detail()
            self._update_associate_button()
            return
        row = rows[0].row()
        item = self._mod_list_model.mod_item_at(row)
        if item is None:
            self._current_mod_id = None
            self._clear_mod_detail()
            self._update_associate_button()
            return
        self._current_mod_id = item.id
        self._load_mod_detail(item)
        self._load_members(item.id)
        self._update_associate_button()

    def _clear_mod_detail(self) -> None:
        """清空 ModItem 详情编辑区与成员表。"""
        self._mod_detail_hint.setText(ui.MOD_DETAIL_NONE_HINT)
        self._name_edit.clear()
        self._desc_edit.clear()
        self._url_edit.clear()
        self._tags_edit.clear()
        self._save_meta_button.setEnabled(False)
        self._members_table.setRowCount(0)
        self._members_hint.setText(ui.MEMBERS_EMPTY_HINT)
        self._members_hint.show()
        # 清空封面预览
        self._cover_label.clear()
        self._cover_label.setText(ui.COVER_PREVIEW_NONE_HINT)

    def _load_mod_detail(self, item: ModItem) -> None:
        """加载 ModItem 元数据到编辑表单。"""
        self._mod_detail_hint.setText(f"正在编辑：{item.display_name or '（未命名）'}")
        self._name_edit.setText(item.display_name or "")
        self._desc_edit.setPlainText(item.description or "")
        self._url_edit.setText(item.source_url or "")
        self._tags_edit.setText("，".join(sorted(item.tags)))
        self._save_meta_button.setEnabled(True)

    def _load_members(self, mod_item_id: str) -> None:
        """加载 ModItem 成员到表格。"""
        self._members_table.setRowCount(0)
        try:
            members = self._mod_service.get_members(mod_item_id)
        except ApplicationError as e:
            self._members_hint.setText(f"加载成员失败：{e}")
            self._members_hint.show()
            return

        mod_item = self._mod_service.get_mod_item(mod_item_id)
        cover_id = mod_item.cover_asset_id if mod_item else None

        self._members_table.setRowCount(len(members))
        for row, asset in enumerate(members):
            # 文件名
            name_item = QTableWidgetItem(asset.filename)
            name_item.setToolTip(asset.real_path)
            name_item.setData(Qt.UserRole, asset.id)
            self._members_table.setItem(row, _COL_FILENAME, name_item)

            # 类型
            kind_text = "文件夹" if asset.asset_kind == AssetKind.FOLDER else "文件"
            self._members_table.setItem(row, _COL_KIND, QTableWidgetItem(kind_text))

            # 角色（QComboBox）
            combo = QComboBox()
            for role in ROLE_ORDER:
                combo.addItem(ROLE_DISPLAY_NAMES[role], role)
            current_idx = (
                ROLE_ORDER.index(asset.role) if asset.role in ROLE_ORDER else len(ROLE_ORDER) - 1
            )
            combo.setCurrentIndex(current_idx)
            combo.currentIndexChanged.connect(
                lambda _idx, a=asset, c=combo: self._on_role_changed(a.id, c)
            )
            self._members_table.setCellWidget(row, _COL_ROLE, combo)

            # 完整路径
            path_item = QTableWidgetItem(asset.real_path)
            path_item.setToolTip(asset.real_path)
            self._members_table.setItem(row, _COL_PATH, path_item)

            # 封面列：preview 成员显示"设为封面"按钮或"★ 封面"标记
            if asset.role == FileRole.PREVIEW:
                if asset.id == cover_id:
                    cover_label = QLabel(ui.MEMBERS_COVER_MARK)
                    cover_label.setAlignment(Qt.AlignCenter)
                    self._members_table.setCellWidget(row, _COL_COVER, cover_label)
                else:
                    cover_btn = QPushButton(ui.MEMBERS_SET_COVER_BUTTON)
                    cover_btn.clicked.connect(
                        lambda _checked=False, a=asset: self._on_set_cover(a.id)
                    )
                    self._members_table.setCellWidget(row, _COL_COVER, cover_btn)
            else:
                self._members_table.setCellWidget(row, _COL_COVER, QLabel(""))

            # 移除按钮
            remove_btn = QPushButton(ui.MEMBERS_REMOVE_BUTTON)
            remove_btn.clicked.connect(lambda _checked=False, a=asset: self._on_remove_member(a.id))
            self._members_table.setCellWidget(row, _COL_ACTION, remove_btn)

        if members:
            self._members_hint.hide()
        else:
            self._members_hint.setText(ui.MEMBERS_EMPTY_HINT)
            self._members_hint.show()

        # 加载封面预览
        self._load_cover_preview(mod_item_id)

    def _on_role_changed(self, asset_id: str, combo: QComboBox) -> None:
        """成员角色下拉变化时更新角色。"""
        if self._current_mod_id is None:
            return
        role = combo.currentData()
        if not isinstance(role, FileRole):
            return
        try:
            self._mod_service.set_member_role(self._current_mod_id, asset_id, role)
            self._commit()
        except ApplicationError as e:
            QMessageBox.warning(self, ui.ERR_SET_ROLE_FAILED, str(e))
            # 回滚 UI：重新加载成员
            self._load_members(self._current_mod_id)

    def _on_remove_member(self, asset_id: str) -> None:
        """移除成员关联。不删除 FileAsset 记录。"""
        if self._current_mod_id is None:
            return
        try:
            self._mod_service.remove_member(self._current_mod_id, asset_id)
            self._commit()
        except ApplicationError as e:
            QMessageBox.warning(self, ui.ERR_REMOVE_MEMBER_FAILED, str(e))
            return
        # 刷新成员表与素材池
        self._load_members(self._current_mod_id)
        self._refresh_pool()

    def _on_set_cover(self, asset_id: str) -> None:
        """将 preview 成员设为封面。"""
        if self._current_mod_id is None:
            return
        try:
            self._mod_service.set_cover(self._current_mod_id, asset_id)
            self._commit()
        except ValueError as e:
            # 非 preview 成员被设为封面
            QMessageBox.warning(self, ui.MEMBERS_SET_COVER_BUTTON, str(e))
            return
        except ApplicationError as e:
            QMessageBox.warning(self, ui.MEMBERS_SET_COVER_BUTTON, str(e))
            return
        # 刷新成员表（更新封面标记）与封面预览
        self._load_members(self._current_mod_id)
        self._refresh_mod_list()

    def _load_cover_preview(self, mod_item_id: str) -> None:
        """加载当前 ModItem 的封面缩略图到详情区预览 QLabel。"""
        if self._thumbnail_coord is None:
            self._cover_label.clear()
            self._cover_label.setText(ui.COVER_PREVIEW_NONE_HINT)
            return

        try:
            mod_item = self._mod_service.get_mod_item(mod_item_id)
        except ApplicationError:
            self._cover_label.clear()
            self._cover_label.setText(ui.COVER_PREVIEW_NONE_HINT)
            return

        if mod_item.cover_asset_id is None:
            self._cover_label.clear()
            self._cover_label.setText(ui.COVER_PREVIEW_NONE_HINT)
            return

        # 查询缓存状态
        info = self._thumbnail_coord.get_thumbnail_info(mod_item.cover_asset_id)
        if info.valid and info.cache_path is not None:
            pixmap = QPixmap(str(info.cache_path))
            if not pixmap.isNull():
                self._cover_label.setPixmap(
                    pixmap.scaled(
                        _COVER_PREVIEW_SIZE,
                        _COVER_PREVIEW_SIZE,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                self._cover_label.setText(ui.COVER_PREVIEW_ERROR.format(reason="缓存文件损坏"))
        else:
            # 缓存无效，触发后台生成
            self._cover_label.setText(ui.COVER_PREVIEW_LOADING)
            self._request_thumbnail(mod_item.cover_asset_id)

    def _request_thumbnail(self, asset_id: str) -> None:
        """请求在后台生成单个缩略图。"""
        if self._thumbnail_coord is None:
            return
        # 若已有线程在运行，跳过（避免并发冲突；简单串行）
        if self._thumb_thread is not None and self._thumb_thread.isRunning():
            return
        self._thumb_thread = QThread()
        self._thumb_worker = ThumbnailWorker(
            self._db_path,
            self._thumbnail_coord.cache_dir,
            [asset_id],
        )
        self._thumb_worker.moveToThread(self._thumb_thread)
        self._thumb_thread.started.connect(self._thumb_worker.run)
        self._thumb_worker.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._thumb_worker.finished.connect(self._thumb_thread.quit)
        self._thumb_thread.finished.connect(self._thumb_worker.deleteLater)
        self._thumb_thread.finished.connect(self._thumb_thread.deleteLater)
        self._thumb_thread.finished.connect(self._on_thumb_thread_finished)
        self._thumb_thread.start()

    def _on_thumbnail_ready(self, asset_id: str, result) -> None:
        """后台缩略图生成完成回调。在主线程执行。"""
        if result.status == ThumbnailStatus.OK and result.cache_path is not None:
            pixmap = QPixmap(str(result.cache_path))
            if not pixmap.isNull():
                # 更新详情区封面预览（仅当当前选中 ModItem 的封面是此 asset）
                if self._current_mod_id is not None:
                    try:
                        mod_item = self._mod_service.get_mod_item(self._current_mod_id)
                        if mod_item.cover_asset_id == asset_id:
                            self._cover_label.setPixmap(
                                pixmap.scaled(
                                    _COVER_PREVIEW_SIZE,
                                    _COVER_PREVIEW_SIZE,
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation,
                                )
                            )
                    except ApplicationError:
                        pass
                # 更新列表封面图标
                self._update_cover_icons_for_asset(asset_id, pixmap)
        else:
            # 显示错误占位
            reason = result.error_message or result.status.value
            if self._current_mod_id is not None:
                try:
                    mod_item = self._mod_service.get_mod_item(self._current_mod_id)
                    if mod_item.cover_asset_id == asset_id:
                        self._cover_label.setText(ui.COVER_PREVIEW_ERROR.format(reason=reason))
                except ApplicationError:
                    pass

    def _update_cover_icons_for_asset(self, asset_id: str, pixmap: QPixmap) -> None:
        """当某个缩略图生成完成后，更新所有以该 asset 为封面的 ModItem 列表图标。"""
        from PySide6.QtGui import QIcon

        icon = QIcon(pixmap)
        for i in range(self._mod_list_model.item_count()):
            item = self._mod_list_model.mod_item_at(i)
            if item is not None and item.cover_asset_id == asset_id:
                self._mod_list_model.set_cover_icon(item.id, icon)

    def _on_thumb_thread_finished(self) -> None:
        """缩略图线程退出后清理引用。"""
        self._thumb_worker = None
        self._thumb_thread = None

    def _refresh_cover_icons(self) -> None:
        """刷新所有 ModItem 的封面图标（列表加载时调用）。"""
        if self._thumbnail_coord is None:
            return
        for i in range(self._mod_list_model.item_count()):
            item = self._mod_list_model.mod_item_at(i)
            if item is None or item.cover_asset_id is None:
                continue
            info = self._thumbnail_coord.get_thumbnail_info(item.cover_asset_id)
            if info.valid and info.cache_path is not None:
                from PySide6.QtGui import QIcon

                pixmap = QPixmap(str(info.cache_path))
                if not pixmap.isNull():
                    self._mod_list_model.set_cover_icon(item.id, QIcon(pixmap))
            else:
                # 缓存无效，后台生成（仅生成第一个，避免并发）
                self._request_thumbnail(item.cover_asset_id)
                break

    def _on_new_mod(self) -> None:
        """新建 ModItem 对话框，并自动关联素材池中选中的素材。"""
        if self._is_scanning:
            return
        asset_ids = self._selected_asset_ids()
        if not asset_ids:
            return
        name, ok = QInputDialog.getText(
            self,
            ui.NEW_MOD_DIALOG_TITLE,
            ui.NEW_MOD_DIALOG_LABEL,
            text=ui.NEW_MOD_DIALOG_DEFAULT_NAME,
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        try:
            new_item = self._mod_service.create_mod_item(display_name=name)
        except ApplicationError as e:
            QMessageBox.warning(self, ui.ERR_CREATE_MOD_FAILED, str(e))
            return
        except Exception as e:  # noqa: BLE001
            logger.exception("创建 ModItem 失败")
            QMessageBox.critical(self, ui.ERR_CREATE_MOD_FAILED, str(e))
            return

        # 自动将选中的素材关联到新 ModItem（默认 unknown 角色）
        success = 0
        errors: list[str] = []
        for asset_id in asset_ids:
            try:
                self._mod_service.add_member(new_item.id, asset_id, FileRole.UNKNOWN)
                success += 1
            except ApplicationError as e:
                errors.append(str(e))

        self._commit()

        # 刷新列表并选中新创建的条目
        self._refresh_mod_list()
        self._refresh_pool()
        for i in range(self._mod_list_model.item_count()):
            if self._mod_list_model.mod_item_id_at(i) == new_item.id:
                idx = self._mod_list_model.index(i)
                self._mod_list_view.setCurrentIndex(idx)
                break

        if errors:
            detail = "\n".join(errors[:5])
            if len(errors) > 5:
                detail += f"\n…（共 {len(errors)} 个错误）"
            QMessageBox.warning(
                self,
                ui.ASSOCIATE_FAILED,
                f"成功 {success} 个，失败 {len(errors)} 个：\n{detail}",
            )
        elif success > 0:
            self._set_status(ui.ASSOCIATE_SUCCESS.format(n=success, name=name))

    def _on_associate(self) -> None:
        """将素材池选中的素材关联到当前 ModItem。"""
        if self._current_mod_id is None:
            QMessageBox.information(self, ui.ASSOCIATE_BUTTON, ui.ERR_NO_MOD_SELECTED)
            return
        asset_ids = self._selected_asset_ids()
        if not asset_ids:
            QMessageBox.information(self, ui.ASSOCIATE_BUTTON, ui.ERR_NO_ASSET_SELECTED)
            return

        mod_item = self._mod_service.get_mod_item(self._current_mod_id)
        mod_name = mod_item.display_name or "（未命名）"

        success = 0
        errors: list[str] = []
        for asset_id in asset_ids:
            try:
                self._mod_service.add_member(self._current_mod_id, asset_id, FileRole.UNKNOWN)
                success += 1
            except ApplicationError as e:
                errors.append(str(e))

        self._commit()

        # 刷新成员表与素材池
        self._load_members(self._current_mod_id)
        self._refresh_pool()

        if errors:
            detail = "\n".join(errors[:5])
            if len(errors) > 5:
                detail += f"\n…（共 {len(errors)} 个错误）"
            QMessageBox.warning(
                self,
                ui.ASSOCIATE_FAILED,
                f"成功 {success} 个，失败 {len(errors)} 个：\n{detail}",
            )
        else:
            self._set_status(ui.ASSOCIATE_SUCCESS.format(n=success, name=mod_name))

    def _on_save_metadata(self) -> None:
        """保存 ModItem 元数据。"""
        if self._current_mod_id is None:
            return
        name = self._name_edit.text().strip()
        desc = self._desc_edit.toPlainText().strip() or None
        url = self._url_edit.text().strip() or None
        tags_text = self._tags_edit.text().strip()
        tags = {t.strip() for t in tags_text.split("，") if t.strip()} if tags_text else set()

        try:
            self._mod_service.update_mod_item(
                self._current_mod_id,
                display_name=name or None,
                description=desc,
                source_url=url,
                tags=tags,
            )
            self._commit()
        except ApplicationError as e:
            QMessageBox.warning(self, ui.ERR_UPDATE_MOD_FAILED, str(e))
            return
        except Exception as e:  # noqa: BLE001
            logger.exception("保存元数据失败")
            QMessageBox.critical(self, ui.ERR_UPDATE_MOD_FAILED, str(e))
            return
        self._set_status(ui.MOD_DETAIL_SAVED_HINT)
        # 刷新列表以反映新名称
        self._refresh_mod_list()

    def mod_detail_name(self) -> str:
        """返回当前编辑表单中的名称（供测试）。"""
        return self._name_edit.text()

    def members_table_row_count(self) -> int:
        """返回成员表格行数（供测试）。"""
        return self._members_table.rowCount()
