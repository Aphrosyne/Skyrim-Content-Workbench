"""主窗口。阶段 2 Task 1：工作台骨架与根目录扫描。

布局：
- 左侧：受管理根目录区域（列表 + 添加目录按钮 + 扫描选中目录按钮）。
- 右侧上方：扫描状态/结果区域。
- 右侧中部：为目录树、素材池、详情面板预留占位区域（本任务不实现数据展示）。

约束（AGENTS 规则 3）：
- UI 不直接调用 shutil / Path.rename / Path.unlink 等文件写 API。
- 添加根目录只写应用数据库；不移动、不复制、不修改该目录。
- 扫描通过 ScanWorker 在后台线程执行，不冻结 UI。
- 扫描期间禁用重复扫描入口。
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
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from app.scan_worker import ScanWorker
from application.errors import (
    DuplicateManagedRootError,
    InvalidRootPathError,
)
from application.managed_root_service import ManagedRootService
from application.scan_workflow_service import ScanSummary
from domain.models import ManagedRoot

logger = logging.getLogger(__name__)

# 错误摘要最多展示条数
MAX_ERROR_SUMMARY_LINES = 5


class MainWindow(QMainWindow):
    """应用主窗口。

    通过构造注入 ManagedRootService 与 db_path，便于测试。
    db_path 用于 ScanWorker 在后台线程创建独立连接。
    """

    def __init__(
        self,
        managed_root_service: ManagedRootService,
        db_path: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = managed_root_service
        self._db_path = db_path
        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None
        self._is_scanning = False

        self.setWindowTitle(ui.APP_TITLE)
        self.resize(ui.WINDOW_DEFAULT_WIDTH, ui.WINDOW_DEFAULT_HEIGHT)

        self._setup_ui()
        self._refresh_root_list()

    # --- UI 构建 ---

    def _setup_ui(self) -> None:
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：受管理根目录
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

        # 右侧：状态 + 占位
        right = QWidget()
        right_layout = QVBoxLayout(right)

        # 扫描状态区域
        status_box = QGroupBox("扫描状态")
        status_layout = QVBoxLayout(status_box)
        self._status_label = QLabel(ui.STATUS_IDLE)
        self._status_label.setWordWrap(True)
        status_layout.addWidget(self._status_label)
        right_layout.addWidget(status_box)

        # 占位区域：目录树 / 素材池 / 详情
        placeholder_splitter = QSplitter(Qt.Vertical)

        tree_box = QGroupBox(ui.PLACEHOLDER_TREE_TITLE)
        tree_layout = QVBoxLayout(tree_box)
        tree_layout.addWidget(QLabel(ui.PLACEHOLDER_TREE_HINT))
        placeholder_splitter.addWidget(tree_box)

        pool_box = QGroupBox(ui.PLACEHOLDER_POOL_TITLE)
        pool_layout = QVBoxLayout(pool_box)
        pool_layout.addWidget(QLabel(ui.PLACEHOLDER_POOL_HINT))
        placeholder_splitter.addWidget(pool_box)

        detail_box = QGroupBox(ui.PLACEHOLDER_DETAIL_TITLE)
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.addWidget(QLabel(ui.PLACEHOLDER_DETAIL_HINT))
        placeholder_splitter.addWidget(detail_box)

        right_layout.addWidget(placeholder_splitter, stretch=1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

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
        self._worker.scan_started.connect(self._on_scan_started)
        self._worker.scan_finished.connect(self._on_scan_finished)
        self._worker.scan_failed.connect(self._on_scan_failed)
        self._worker.scan_finished.connect(self._thread.quit)
        self._worker.scan_failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _begin_scanning(self) -> None:
        self._is_scanning = True
        self._scan_button.setText(ui.SCAN_BUTTON_SCANNING)
        self._scan_button.setEnabled(False)
        self._add_button.setEnabled(False)
        self._set_status(ui.STATUS_SCANNING)

    def _end_scanning(self) -> None:
        self._is_scanning = False
        self._scan_button.setText(ui.SCAN_BUTTON)
        self._add_button.setEnabled(True)
        has_selection = self._selected_root_id() is not None
        self._scan_button.setEnabled(has_selection)
        self._worker = None
        self._thread = None

    def _on_scan_started(self) -> None:
        self._set_status(ui.STATUS_SCANNING)

    def _on_scan_finished(self, summary: ScanSummary) -> None:
        """扫描完成：展示摘要。该方法可独立测试。"""
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
        """返回扫描按钮是否可用（供测试）。"""
        return self._scan_button.isEnabled()
