"""主窗口。阶段 2 Task 1/Task 2：工作台骨架、根目录扫描、只读目录树。

布局（三栏骨架）：
- 左栏：受管理根目录列表 + 添加目录 + 扫描选中目录按钮。
- 中栏：受管理目录树（Task 2 实现，以 FolderNode 为数据源）+ 占位素材池。
- 右栏：扫描状态 + 选中目录信息区域（Task 2 实现基础元数据展示）。

约束（AGENTS 规则 3）：
- UI 不直接调用 shutil / Path.rename / Path.unlink 等文件写 API。
- 添加根目录只写应用数据库；不移动、不复制、不修改该目录。
- 扫描通过 ScanWorker 在后台线程执行，不冻结 UI。
- 扫描期间禁用重复扫描入口。
- 目录树数据源为 SQLite FolderNode，不在 UI 线程临时递归真实文件系统。
- 目录树严格只读：不实现拖拽移动、右键文件操作、重命名/删除/新建。
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from app.folder_tree_model import FolderTreeModel
from app.scan_worker import ScanWorker
from application.errors import (
    DuplicateManagedRootError,
    InvalidRootPathError,
)
from application.folder_tree_service import FolderTreeService, TreeNode
from application.managed_root_service import ManagedRootService
from application.scan_workflow_service import ScanSummary
from domain.models import ManagedRoot

logger = logging.getLogger(__name__)

# 错误摘要最多展示条数
MAX_ERROR_SUMMARY_LINES = 5


class MainWindow(QMainWindow):
    """应用主窗口。

    通过构造注入 ManagedRootService、FolderTreeService 与 db_path，便于测试。
    db_path 用于 ScanWorker 在后台线程创建独立连接。
    """

    def __init__(
        self,
        managed_root_service: ManagedRootService,
        folder_tree_service: FolderTreeService,
        db_path: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = managed_root_service
        self._tree_service = folder_tree_service
        self._db_path = db_path
        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None
        self._is_scanning = False

        self.setWindowTitle(ui.APP_TITLE)
        self.resize(ui.WINDOW_DEFAULT_WIDTH, ui.WINDOW_DEFAULT_HEIGHT)

        self._setup_ui()
        self._refresh_root_list()
        self._refresh_tree()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """关闭窗口前等待后台扫描线程退出，避免 QThread Running 状态析构 CTD。"""
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)
        super().closeEvent(event)

    # --- UI 构建 ---

    def _setup_ui(self) -> None:
        splitter = QSplitter(Qt.Horizontal)

        # 左栏：受管理根目录
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

        self._scan_button = QPushButton(ui.SCAN_BUTTON)
        self._scan_button.clicked.connect(self._on_scan)
        self._scan_button.setEnabled(False)
        roots_layout.addWidget(self._scan_button)

        splitter.addWidget(self._roots_group)

        # 中栏：目录树 + 素材池占位
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)

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
        center_layout.addWidget(self._tree_group, stretch=3)

        # 素材池占位
        pool_box = QGroupBox(ui.PLACEHOLDER_POOL_TITLE)
        pool_layout = QVBoxLayout(pool_box)
        pool_layout.addWidget(QLabel(ui.PLACEHOLDER_POOL_HINT))
        center_layout.addWidget(pool_box, stretch=2)

        splitter.addWidget(center)

        # 右栏：扫描状态 + 选中目录详情
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 扫描状态区域
        status_box = QGroupBox("扫描状态")
        status_layout = QVBoxLayout(status_box)
        self._status_label = QLabel(ui.STATUS_IDLE)
        self._status_label.setWordWrap(True)
        status_layout.addWidget(self._status_label)
        right_layout.addWidget(status_box)

        # 选中目录详情区域
        self._detail_group = QGroupBox(ui.DETAIL_GROUP_TITLE)
        detail_layout = QVBoxLayout(self._detail_group)
        self._detail_label = QLabel(ui.DETAIL_NONE_HINT)
        self._detail_label.setWordWrap(True)
        self._detail_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        detail_layout.addWidget(self._detail_label)
        right_layout.addWidget(self._detail_group, stretch=1)

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

    def _on_scan_failed(self, message: str) -> None:
        self._set_status(f"{ui.STATUS_SCAN_FAILED}\n{message}")
        self._end_scanning()
        # 扫描失败仍刷新目录树（根目录可能已配置但无扫描数据）
        self._refresh_tree()

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
