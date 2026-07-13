"""主窗口。阶段 2 Task 3：目录树浏览。

布局：
- 左栏：受管理根目录列表 + 添加/移除按钮 + 扫描按钮（增量/全量）+ 扫描状态。
- 右栏：目录树（FolderTreeModel）+ 选中目录详情。

约束（AGENTS 规则 3）：
- UI 不直接调用 shutil / Path.rename / Path.unlink 等文件写 API。
- 添加根目录只写应用数据库；不移动、不复制、不修改该目录。
- 扫描通过 ScanWorker 在后台线程执行，不冻结 UI。
- 扫描期间禁用重复扫描入口。

目录树数据源严格为 SQLite folder_cache 表，不重新扫描文件系统。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
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
    ManagedRootNotFoundError,
)
from application.folder_tree_service import FolderTreeService
from application.managed_root_service import ManagedRootService
from application.scan_service import ScanSummary
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
        commit_callback: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = managed_root_service
        self._tree_service = folder_tree_service
        self._db_path = db_path
        self._commit_callback = commit_callback
        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None
        self._is_scanning = False

        self.setWindowTitle(ui.APP_TITLE)
        self.resize(ui.WINDOW_DEFAULT_WIDTH, ui.WINDOW_DEFAULT_HEIGHT)

        self._setup_ui()
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
        splitter = QSplitter(Qt.Horizontal)

        # === 左栏：受管理根目录 + 扫描控制 ===
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

        left_layout.addStretch(1)
        splitter.addWidget(left)

        # === 右栏：目录树 + 详情 ===
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

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

        right_layout.addWidget(self._tree_group, stretch=2)

        # 选中目录详情
        self._detail_group = QGroupBox(ui.DETAIL_GROUP_TITLE)
        detail_layout = QVBoxLayout(self._detail_group)
        self._detail_label = QLabel(ui.DETAIL_NOT_SELECTED)
        self._detail_label.setWordWrap(True)
        self._detail_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        detail_layout.addWidget(self._detail_label)
        right_layout.addWidget(self._detail_group, stretch=1)

        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self.setCentralWidget(splitter)

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
        """刷新目录树模型。"""
        self._tree_model.refresh()
        root_count = self._tree_model.root_node_count()
        self._tree_empty_hint.setVisible(root_count == 0)
        # 清空详情区
        self._detail_label.setText(ui.DETAIL_NOT_SELECTED)

    def _on_tree_selection_changed(self, *args) -> None:  # noqa: ANN001 (Qt 信号)
        """目录树选中变化时更新详情区。"""
        indexes = self._tree_view.selectionModel().selectedIndexes()
        if not indexes:
            self._detail_label.setText(ui.DETAIL_NOT_SELECTED)
            return

        index = indexes[0]
        node = self._tree_model.node_at(index)
        if node is None:
            self._detail_label.setText(ui.DETAIL_NOT_SELECTED)
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
        self._detail_label.setText("\n".join(lines))

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
        """扫描完成：展示摘要并刷新目录树。"""
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
        # 扫描完成后刷新目录树
        self._refresh_tree()

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
