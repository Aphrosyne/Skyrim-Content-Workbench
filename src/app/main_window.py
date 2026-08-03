"""主窗口。UX 重构 Phase 1 起为单面板统一工作区（无浏览/整理模式切换）。

布局（统一面板，与 spec §7.1 一致）：
- 顶部工具栏：搜索框 + 标签管理按钮 + 操作历史按钮。
- 左栏：受管理根目录列表 + 添加/移除按钮 + 增量/全量扫描按钮 + 目录树 + 选中目录详情。
- 中栏：标签筛选栏 + 文件列表（列表/卡片视图切换 + 排序 + 缩放 + 前进/后退 + 刷新）。
- 右栏：元数据面板（上）+ 装配面板（下，文件夹透视器 + 📌 钉住）。

目录树行为（spec §5.1）：
- 目录树点击节点 → 中栏刷新该目录文件列表 + 详情区更新。

扫描联动（roadmap 阶段 2 Task 5 验收项 5）：
- 扫描完成 → 刷新目录树 + 刷新当前中栏文件列表
  （新扫描出的压缩包文件立即显示 -- 标记）。

约束（AGENTS 规则 3）：
- UI 不直接调用 shutil / Path.rename / Path.unlink 等文件写 API。
- 添加根目录只写应用数据库；不移动、不复制、不修改该目录。
- 扫描通过 ScanWorker 在后台线程执行，不冻结 UI。
- 扫描期间禁用重复扫描入口。

目录树数据源严格为 SQLite folder_cache 表，不重新扫描文件系统。
文件列表数据源为文件系统（Path.iterdir），通过 ContentService.list_directory_entries
读取条目并按 path 关联 content_unit 表。内容单元不是可见性门槛——
所有文件系统条目均可见可操作（spec §5.1 关键设计）。
元数据面板只读显示（编辑在阶段 4 Task 2）。

交互行为（2026-07-16 调整）：
- 单击选中内容单元 → 右侧立即显示元数据（详情面板交互方式）。
- 双击文件夹 → 进入该目录（无论是否内容单元，优先于元数据显示）。
  文件夹的元数据通过单击查看。
- 双击文件类型内容单元（压缩包）→ 显示元数据面板。
- 双击普通文件 → 不响应（右键「打开」可用系统默认程序打开）。
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
import subprocess
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QPoint, QRect, QSettings, QSize, Qt
from PySide6.QtGui import QFontMetrics, QKeySequence, QPixmap, QShortcut
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
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QRubberBand,
    QSplitter,
    QStackedWidget,
    QTableView,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from app.assembly_controller import AssemblyController
from app.assembly_panel import AssemblyPanel
from app.batch_tag_dialog import BatchTagDialog
from app.card_list_model import CardListModel
from app.file_list_model import (
    COL_MODIFIED,
    COL_NAME,
    COL_SIZE,
    COL_TYPE,
    SORT_MODIFIED,
    SORT_NAME,
    SORT_SIZE,
    SORT_TYPE,
    FileListModel,
)
from app.folder_tree_model import FolderTreeModel
from app.main_menu_bar import MainMenuBar
from app.metadata_panel import MetadataPanel
from app.metadata_view import MetadataView
from app.path_display import make_display_path_from_service
from app.recent_move_targets import RecentMoveTargets
from app.recent_tags import RecentTags
from app.scan_controller import ScanController
from app.splitter_state import SplitterStateHelper
from app.tag_filter import TagFilterBar
from app.tag_manager_dialog import TagManagerDialog
from app.thumbnail_coordinator import ThumbnailCoordinator
from app.transaction_scope import TransactionScope
from application.assembly_service import AssemblyService
from application.clipboard_service import ClipboardService
from application.content_service import ContentService
from application.content_unit_creation_service import ContentUnitCreationService
from application.errors import (
    ApplicationError,
    ConflictError,
    CrossDriveError,
    FileOperationError,
    ManagedRootNotFoundError,
    SelfSubdirectoryError,
    SourceNotFoundError,
)
from application.file_operation_service import FileOperationService
from application.folder_tree_service import FolderTreeService
from application.managed_root_service import ManagedRootService
from application.scan_service import ScanSummary
from application.search_service import SearchService
from application.tag_service import TagService
from application.undo_service import UndoService
from domain.models import ContentUnit, FileEntry, ManagedRoot
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.errors import RepositoryError

logger = logging.getLogger(__name__)

# 错误摘要最多展示条数
MAX_ERROR_SUMMARY_LINES = 5

# QSettings 配置键与布局默认值见 ui_constants（UI合理性2/3 迁移，2026-08-03）

# 视图索引（QStackedWidget）
VIEW_INDEX_LIST = 0
VIEW_INDEX_CARD = 1

# 详情区路径 / 元数据路径字段在 Elide 时保留的左右字符比例参考
# 详情区第 2 行为路径，元数据面板第 2 行为路径（详见 _apply_elide）


class _RubberBandTableView(QTableView):
    """支持空白区域拖动框选的 QTableView。

    Stage 5 Task 2 验收修复（决策 3A）：QTableView 不支持 setSelectionRectVisible
    （仅 QListView 有），通过自定义 mousePress/Drag/Release + QRubberBand 实现
    与 Windows Explorer 一致的空白区域拖动框选行为。

    交互规则：
    - 在空白区域（非任何 item 上）按下左键 → 启动 rubber band
    - 拖动 → 更新 rubber band 矩形，选中范围内所有行（替换选择）
    - 松开 → 隐藏 rubber band
    - 在 item 上按下 → 交给父类处理（保留单击/Ctrl/Shift 选择行为）
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rubber_band: QRubberBand | None = None
        self._origin = QPoint()
        self._drag_selecting = False
        # UX 重构 Phase 1 Task 4：内部拖拽到文件夹的回调
        # 签名：(target_folder: Path, src_paths: list[Path]) -> None
        self.on_drop_to_folder: Callable[[Path, list[Path]], None] | None = None

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.pos())
            if not index.isValid():
                # 空白区域：启动 rubber band 框选
                self._origin = event.pos()
                self._drag_selecting = True
                if self._rubber_band is None:
                    # UX 重构 Phase 1 Task 2：rubber band 父对象改为 viewport()，
                    # 使其几何坐标与 event.pos() / rowAt() 一致（原父对象为 self，
                    # 受 header 高度偏移影响，框选框与鼠标指针存在垂直错位）。
                    self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
                self._rubber_band.setGeometry(QRect(self._origin, QSize()))
                self._rubber_band.show()
                # 清空当前选择（与 Explorer 行为一致：空白拖动开始新选择）
                self.selectionModel().clear()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self._drag_selecting and self._rubber_band is not None:
            rect = QRect(self._origin, event.pos()).normalized()
            self._rubber_band.setGeometry(rect)
            self._select_rows_in_rect(rect)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self._drag_selecting:
            self._drag_selecting = False
            if self._rubber_band is not None:
                self._rubber_band.hide()
            return
        super().mouseReleaseEvent(event)

    def _select_rows_in_rect(self, rect: QRect) -> None:
        """根据 rubber band 矩形选中相交的行（替换选择）。"""
        from PySide6.QtCore import QItemSelection

        # 计算矩形覆盖的行范围
        top_row = self.rowAt(rect.top())
        bottom_row = self.rowAt(rect.bottom())
        last_row = self.model().rowCount() - 1 if self.model() else -1
        # 修复（操作合理性4，2026-08-03）：矩形边缘落在行区外时扩展到首末行。
        # 此前仅处理超出视口的情况，导致在末行下方空白区起框（从下往上拉）
        # 时 bottom_row=-1 直接 return、选不中。
        if top_row == -1 and rect.top() <= 0:
            top_row = 0
        if bottom_row == -1 and rect.bottom() >= 0:
            # 下边缘在首行之下（含视口内空白区与视口外）→ 扩展到末行；
            # 若下边缘在视口上方（rect.bottom() < 0）则保持 -1，无可选。
            bottom_row = last_row
        if top_row == -1 or bottom_row == -1 or top_row > bottom_row:
            return
        # 选中范围内的所有行（ClearAndSelect 替换当前选择）
        top_index = self.model().index(top_row, 0)
        bottom_index = self.model().index(bottom_row, 0)
        sel = QItemSelection(top_index, bottom_index)
        self.selectionModel().select(
            sel,
            QItemSelectionModel.SelectionFlag.ClearAndSelect
            | QItemSelectionModel.SelectionFlag.Rows,
        )

    # --- UX 重构 Phase 1 Task 4：内部拖拽到文件夹 ---

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.source() is self and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.source() is self and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.source() is not self or not event.mimeData().hasUrls():
            event.ignore()
            return
        index = self.indexAt(event.pos())
        if not index.isValid():
            event.ignore()
            return
        entry = self.model().data(index, Qt.UserRole)
        if entry is None or not entry.is_dir:
            event.ignore()
            return
        src_paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.toLocalFile() and url.toLocalFile() != entry.path
        ]
        if not src_paths:
            event.ignore()
            return
        if self.on_drop_to_folder is not None:
            self.on_drop_to_folder(Path(entry.path), src_paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class _DragDropListView(QListView):
    """支持内部拖拽到文件夹的 QListView（卡片视图用）。

    UX 重构 Phase 1 Task 4：与 _RubberBandTableView 相同的拖拽逻辑，
    用于卡片视图内拖拽文件到同目录文件夹。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.on_drop_to_folder: Callable[[Path, list[Path]], None] | None = None

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.source() is self and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.source() is self and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.source() is not self or not event.mimeData().hasUrls():
            event.ignore()
            return
        index = self.indexAt(event.pos())
        if not index.isValid():
            event.ignore()
            return
        entry = self.model().data(index, Qt.UserRole)
        if entry is None or not entry.is_dir:
            event.ignore()
            return
        src_paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.toLocalFile() and url.toLocalFile() != entry.path
        ]
        if not src_paths:
            event.ignore()
            return
        if self.on_drop_to_folder is not None:
            self.on_drop_to_folder(Path(entry.path), src_paths)
            event.acceptProposedAction()
        else:
            event.ignore()


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
        content_unit_creation_service: ContentUnitCreationService | None = None,
        assembly_service: AssemblyService | None = None,
        rollback_callback: Callable[[], None] | None = None,
        tag_service: TagService | None = None,
        thumbnail_coordinator: ThumbnailCoordinator | None = None,
        file_operation_service: FileOperationService | None = None,
        undo_service: UndoService | None = None,
        clipboard_service: ClipboardService | None = None,
        search_service: SearchService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # UX 重构 Phase 2 Task 5 修复：抑制 QMessageBox 系统提示音
        from app.message_box_helper import suppress_message_box_sound

        suppress_message_box_sound()

        self._service = managed_root_service
        self._tree_service = folder_tree_service
        self._content_service = content_service
        self._db_path = db_path
        # UX 重构 Task 7 Step 1：事务边界封装（TD-M31）
        self._transaction_scope = TransactionScope(commit_callback, rollback_callback, parent=self)
        self._content_unit_creation_service = content_unit_creation_service
        self._assembly_service = assembly_service
        self._tag_service = tag_service
        # Stage 5 Task 3a：文件操作服务（new_folder / rename / delete）
        self._file_operation_service = file_operation_service
        # Stage 5 Task 6：操作历史撤销服务
        self._undo_service = undo_service
        # Stage 5 Task 3b：应用内剪贴板服务（Q3=A 不与系统剪贴板混用）
        self._clipboard_service = clipboard_service
        # Stage 5 Task 7：全局搜索服务
        self._search_service = search_service
        # 搜索结果对话框实例（非模态，保持引用避免被 GC）
        self._search_dialog: QDialog | None = None
        # Stage 4 Task 4：缩略图调度器（可选注入，便于测试）
        self._thumbnail_coordinator = thumbnail_coordinator
        # UX 重构 Task 7 Step 2：扫描线程生命周期控制器（TD-M21/M26）
        self._scan_controller = ScanController(db_path, self)
        self._scan_controller.scan_started.connect(self._on_scan_started)
        self._scan_controller.scan_progress.connect(self._on_scan_progress)
        self._scan_controller.scan_finished.connect(self._on_scan_finished)
        self._scan_controller.scan_failed.connect(self._on_scan_failed)

        # Stage 5 Task 1：QSettings 持久化缩放值与视图模式（Q1=A）
        # UI合理性2：分割线状态 helper（键与默认值见 ui_constants）
        self._qsettings = QSettings(ui.QSETTINGS_ORGANIZATION, ui.QSETTINGS_APPLICATION)
        self._splitter_state = SplitterStateHelper(self._qsettings)
        # 操作便捷性3（2026-08-02）：最近移动目标（右键子菜单 / Ctrl+Q / 对话框快捷区）
        self._recent_move_targets = RecentMoveTargets(self._qsettings)
        # UI合理性8（2026-08-02）：最近使用标签（面板最近区 / 右键「添加最近标签」）
        self._recent_tags = RecentTags(self._qsettings)
        self._current_view_index: int = VIEW_INDEX_LIST  # 默认列表视图
        self._card_icon_size: int = ui.ZOOM_SLIDER_DEFAULT

        # Stage 5 Task 2：目录导航历史栈（UX 重构 Phase 1 移除模式后始终记录）
        self._nav_back_stack: list[str] = []
        self._nav_forward_stack: list[str] = []
        self._current_nav_path: str | None = None
        # 历史导航触发的切换标记，防止 _refresh_content_list 再次入栈导致循环
        self._navigating_from_history: bool = False

        self.setWindowTitle(ui.APP_TITLE)
        self.resize(ui.WINDOW_DEFAULT_WIDTH, ui.WINDOW_DEFAULT_HEIGHT)

        self._setup_ui()
        # UX 重构 Task 7 Step 3/4：装配面板与元数据控制器
        self._assembly_controller = AssemblyController(self._assembly_panel, self)
        self._metadata_view = MetadataView(
            self._metadata_panel,
            self._content_service,
            self._transaction_scope,
            dialog_parent=self,
        )
        self._metadata_view.saved.connect(self._on_metadata_saved)
        # 操作便捷性6（2026-08-03）：封面即时保存成功 → 刷新中栏
        self._metadata_view.cover_saved.connect(self._on_cover_saved)
        # UI合理性13（2026-08-03）：面板重命名栏回车 → 执行文件重命名
        self._metadata_view.rename_requested.connect(self._on_metadata_rename_requested)
        self._refresh_root_list()
        self._refresh_tree()
        # Stage 5 Task 4：注册键盘快捷键
        self._setup_shortcuts()

        # Stage 4 Task 4：初始化缩略图调度器
        self._init_thumbnail_coordinator()

        # Stage 5 Task 1：从 QSettings 恢复缩放值与视图模式
        self._restore_view_state()
        # UI合理性2：分割线状态在首次 showEvent 恢复（窗口尚未布局时 setSizes 会按 0 宽缩放清零）
        self._splitter_restored = False

        # Stage 5 Task 2：同步排序控件初始状态（与 FileListModel 默认值一致）
        self._sync_sort_controls()

    def _init_thumbnail_coordinator(self) -> None:
        """初始化缩略图调度器并连接信号。

        UI合理性16（2026-08-03）：卡片视图恢复 256 档缩略图缓存链路
        （Task 1b 曾改为直接加载原图，多内容下全尺寸解码卡顿）。
        """
        if self._thumbnail_coordinator is None:
            return
        self._thumbnail_coordinator.start()
        self._thumbnail_coordinator.thumbnail_ready.connect(
            self._on_thumbnail_ready,
            Qt.QueuedConnection,  # noqa: UP037
        )
        # 注入卡片缩略图 provider（缓存命中同步返回，未命中投递后台生成）
        self._card_list_model.set_thumbnail_provider(self._card_thumbnail_provider)

    def _card_thumbnail_provider(
        self,
        content_unit_id: str,
        source_path: str,
        size: int,
    ) -> QPixmap | None:
        """卡片视图缩略图查询回调（UI合理性16）。

        缓存命中同步返回 QPixmap；未命中投递后台生成并返回 None
        （由模型显示占位图标，生成完成后经 thumbnail_ready 刷新）。
        """
        if self._thumbnail_coordinator is None:
            return None
        return self._thumbnail_coordinator.request_thumbnail(
            content_unit_id, Path(source_path), size=size
        )

    def _on_thumbnail_ready(self, content_unit_id: str, size: int) -> None:
        """后台缩略图生成完成：刷新对应行 DecorationRole。"""
        self._card_list_model.notify_thumbnail_ready(content_unit_id, size)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """关闭窗口前等待后台线程退出，避免 QThread Running 状态析构 CTD。"""
        # UI合理性2：关闭前保存分割线状态（重启保留）
        self._splitter_state.save(self._splitter, ui.QSETTINGS_KEY_SPLITTER_MAIN)
        self._splitter_state.save(self._right_splitter, ui.QSETTINGS_KEY_SPLITTER_RIGHT)
        # UX 重构 Task 7 Step 2：扫描线程生命周期由 ScanController 管理
        self._scan_controller.shutdown()
        # Stage 4 Task 4：等待缩略图 coordinator 退出
        if self._thumbnail_coordinator is not None:
            self._thumbnail_coordinator.shutdown()
        super().closeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """UI合理性2：首次显示并完成布局后恢复分割线尺寸。"""
        super().showEvent(event)
        if not self._splitter_restored:
            self._splitter_restored = True
            self._restore_splitter_state()

    def _commit(self) -> None:
        """提交当前数据库事务（UX 重构 Task 7 Step 1：委托 TransactionScope）。"""
        self._transaction_scope.commit()

    def _rollback(self) -> None:
        """回滚当前数据库事务（UX 重构 Task 7 Step 1：委托 TransactionScope）。"""
        self._transaction_scope.rollback()

    def _handle_service_error(self, e: Exception, title: str, *, rollback: bool = True) -> None:
        """统一处理 Service 调用异常（H7 修复，UX 重构 Task 7 Step 1：委托 TransactionScope）。"""
        self._transaction_scope.handle_service_error(e, title, rollback=rollback)

    # --- UI 构建 ---

    def _setup_ui(self) -> None:
        # === 顶部工具栏（UX 重构 Phase 1 Task 1：移除模式切换按钮） ===
        # 修复3：所有容器 QWidget/QSplitter 创建时传入 self 作为 parent，
        # 避免短暂成为顶层窗口导致 Windows 上启动时小窗口闪烁。
        top_bar = QWidget(self)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(8, 4, 8, 4)

        top_layout.addStretch(1)

        # Stage 5 Task 7：全局搜索框（Q1=A 回车触发）
        # 仅注入 search_service 时显示
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText(ui.SEARCH_BOX_PLACEHOLDER)
        self._search_box.setClearButtonEnabled(True)
        # 固定宽度：避免输入内容或清除按钮(×)出现时撑宽搜索框
        self._search_box.setFixedWidth(360)
        # UX 重构 Phase 1 Task 2：启动时不自动聚焦搜索栏（ClickFocus：点击才聚焦）
        self._search_box.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._search_box.returnPressed.connect(self._on_search_triggered)
        self._search_box.setVisible(self._search_service is not None)
        top_layout.addWidget(self._search_box)

        # 标签管理按钮（阶段 4 Task 1）：打开标签管理对话框
        self._tag_manager_button = QPushButton(ui.TAG_MANAGER_BUTTON)
        self._tag_manager_button.setToolTip(ui.TAG_MANAGER_TOOLTIP)
        self._tag_manager_button.clicked.connect(self._on_tag_manager_clicked)
        self._tag_manager_button.setVisible(self._tag_service is not None)
        top_layout.addWidget(self._tag_manager_button)

        # Stage 5 Task 6：操作历史按钮
        # 仅注入 UndoService 时显示
        self._operation_history_button = QPushButton(ui.TOOLBAR_OPERATION_HISTORY)
        self._operation_history_button.setToolTip(ui.TOOLBAR_OPERATION_HISTORY)
        self._operation_history_button.clicked.connect(self._on_operation_history_clicked)
        self._operation_history_button.setVisible(self._undo_service is not None)
        top_layout.addWidget(self._operation_history_button)

        # === 三栏 Splitter（UI合理性2：尺寸保存/恢复由 SplitterStateHelper 管理） ===
        self._splitter = QSplitter(Qt.Horizontal, self)
        splitter = self._splitter

        # === 左栏：受管理根目录 + 扫描控制 + 目录树 + 详情 ===
        left = QWidget(self)
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

        # UX 重构 Phase 2 Task 5（Q7=A）：移除左侧"扫描状态" QGroupBox，
        # 扫描状态统一到 QStatusBar 的持久 QLabel（_status_label），避免布局抖动。
        # _status_label 在 _setup_status_bar 中创建并 addWidget 到 QStatusBar。
        # 单行显示（不换行），完整摘要通过 Tooltip 查看，避免 QStatusBar 高度抖动。
        self._status_label = QLabel(ui.STATUS_IDLE)
        self._status_label.setWordWrap(False)
        self._status_label.setToolTip("扫描状态")

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

        # === 中栏：文件列表（UX 重构 Phase 1 Task 2：装配面板迁至右栏） ===
        middle = QWidget(self)
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(0, 0, 0, 0)

        self._content_group = QGroupBox(ui.CONTENT_LIST_GROUP_TITLE)
        content_layout = QVBoxLayout(self._content_group)

        # 视图切换栏（Stage 5 Task 1，Q1=A：独立一行，在 TagFilterBar 之上）
        # Stage 5 Task 2：左侧增加前进/后退导航按钮 + 排序下拉框
        self._view_switch_bar = QWidget(self)
        view_switch_layout = QHBoxLayout(self._view_switch_bar)
        view_switch_layout.setContentsMargins(0, 0, 0, 0)

        # 前进/后退导航按钮（Stage 5 Task 2，类似资源管理器）
        self._nav_back_button = QPushButton("←")
        self._nav_back_button.setToolTip(ui.NAV_BACK_TOOLTIP)
        self._nav_back_button.setFixedWidth(32)
        self._nav_back_button.setEnabled(False)
        self._nav_back_button.clicked.connect(self._on_nav_back_clicked)
        view_switch_layout.addWidget(self._nav_back_button)

        self._nav_forward_button = QPushButton("→")
        self._nav_forward_button.setToolTip(ui.NAV_FORWARD_TOOLTIP)
        self._nav_forward_button.setFixedWidth(32)
        self._nav_forward_button.setEnabled(False)
        self._nav_forward_button.clicked.connect(self._on_nav_forward_clicked)
        view_switch_layout.addWidget(self._nav_forward_button)

        view_switch_layout.addSpacing(8)

        view_label = QLabel(ui.VIEW_SWITCH_GROUP_LABEL)
        view_switch_layout.addWidget(view_label)

        self._view_list_button = QPushButton(ui.VIEW_SWITCH_LIST)
        self._view_list_button.setCheckable(True)
        self._view_list_button.setChecked(True)  # 默认列表视图
        self._view_list_button.setToolTip(ui.VIEW_SWITCH_LIST_TOOLTIP)
        self._view_list_button.clicked.connect(lambda: self._switch_view(VIEW_INDEX_LIST))
        view_switch_layout.addWidget(self._view_list_button)

        self._view_card_button = QPushButton(ui.VIEW_SWITCH_CARD)
        self._view_card_button.setCheckable(True)
        self._view_card_button.setToolTip(ui.VIEW_SWITCH_CARD_TOOLTIP)
        self._view_card_button.clicked.connect(lambda: self._switch_view(VIEW_INDEX_CARD))
        view_switch_layout.addWidget(self._view_card_button)

        # 互斥分组
        self._view_button_group = QButtonGroup(self)
        self._view_button_group.setExclusive(True)
        self._view_button_group.addButton(self._view_list_button)
        self._view_button_group.addButton(self._view_card_button)

        view_switch_layout.addStretch(1)

        # 排序字段下拉框 + 方向按钮（Stage 5 Task 2，Q2=A 列表/卡片视图共享）
        sort_label = QLabel(ui.SORT_FIELD_LABEL)
        view_switch_layout.addWidget(sort_label)
        self._sort_field_combo = QComboBox()
        self._sort_field_combo.addItem(ui.SORT_FIELD_NAME, SORT_NAME)
        self._sort_field_combo.addItem(ui.SORT_FIELD_TYPE, SORT_TYPE)
        self._sort_field_combo.addItem(ui.SORT_FIELD_SIZE, SORT_SIZE)
        self._sort_field_combo.addItem(ui.SORT_FIELD_MODIFIED, SORT_MODIFIED)
        self._sort_field_combo.setToolTip(ui.SORT_FIELD_TOOLTIP)
        self._sort_field_combo.setFixedWidth(90)
        # Stage 5 Task 2 验收修复：取消 popup 当前项的蓝色高亮背景，
        # 避免"当前选中项"在视觉上误导用户以为需要先取消高亮才能选择。
        # hover 仍保留浅色提示，selected 改为透明（与未选中视觉一致）。
        self._sort_field_combo.setStyleSheet(
            "QComboBox::item:selected { background: transparent; color: black; }"
            "QComboBox::item:hover { background: #e0e0e0; }"
        )
        # Stage 5 Task 2 验收修复（最终版）：仅用 activated 信号。
        # 放弃 currentIndexChanged + activated 双信号方案：双信号在 Qt popup 关闭顺序
        # 不确定时存在 deduplication 边界失效，导致重复执行或漏执行。
        # activated 在用户主动点击下拉项时触发，程序化 setCurrentIndex 不触发（避免
        # _sync_sort_controls 同步时死循环）。“选当前项重新排序”无产品意义，不予支持。
        self._sort_field_combo.activated.connect(self._on_sort_field_activated)
        view_switch_layout.addWidget(self._sort_field_combo)

        # 升降序切换按钮：文本显示 ▲/▼，点击翻转
        # 不用 checkable：checked 状态会有蓝色高亮，方向由文本 ▲/▼ 表达即可
        self._sort_dir_button = QPushButton(ui.SORT_ASC_SYMBOL)
        self._sort_dir_button.setToolTip(ui.SORT_DIRECTION_ASC_TOOLTIP)
        self._sort_dir_button.setFixedWidth(32)
        self._sort_dir_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._sort_dir_button.clicked.connect(self._on_sort_direction_clicked)
        view_switch_layout.addWidget(self._sort_dir_button)

        # 缩放下拉框（Task 1b 修正：滑块改为预选尺寸下拉框，避免拖动频繁重绘原图）
        zoom_label = QLabel(ui.ZOOM_SLIDER_LABEL)
        view_switch_layout.addWidget(zoom_label)
        self._zoom_combo = QComboBox()
        for size in ui.ZOOM_PRESET_SIZES:
            self._zoom_combo.addItem(f"{size}", size)
        # 设置默认值
        default_index = ui.ZOOM_PRESET_SIZES.index(ui.ZOOM_SLIDER_DEFAULT)
        self._zoom_combo.setCurrentIndex(default_index)
        self._zoom_combo.setToolTip(ui.ZOOM_SLIDER_TOOLTIP)
        self._zoom_combo.setFixedWidth(80)
        self._zoom_combo.currentIndexChanged.connect(self._on_zoom_combo_changed)
        view_switch_layout.addWidget(self._zoom_combo)

        # UX 重构 Phase 2 Task 5（Q5=B）：刷新按钮（中栏标题栏）
        # 仅刷新当前目录 + 目录树对应节点，不触发全量扫描（Q6=A 同步刷新装配面板）
        self._refresh_button = QPushButton(ui.REFRESH_BUTTON)
        self._refresh_button.setToolTip(ui.REFRESH_BUTTON_TOOLTIP)
        self._refresh_button.setFixedWidth(32)
        self._refresh_button.clicked.connect(self._on_refresh_current)
        view_switch_layout.addWidget(self._refresh_button)

        content_layout.addWidget(self._view_switch_bar)

        # 标签筛选栏（Stage 4 Task 3）：注入 TagService 时可见（常驻中栏顶部）
        if self._tag_service is not None:
            self._tag_filter_bar = TagFilterBar(self._tag_service)
            self._tag_filter_bar.on_filter_changed.connect(self._on_tag_filter_changed)
            self._tag_filter_bar.refresh_categories()
            content_layout.addWidget(self._tag_filter_bar)
        else:
            self._tag_filter_bar = None  # type: ignore[assignment]

        # 文件列表 Model（两个视图共享，Q6:B 复用 FileListModel）
        self._content_list_model = FileListModel()
        # 卡片视图 Model（轻量代理，委托给 FileListModel）
        self._card_list_model = CardListModel()
        self._card_list_model.set_source(self._content_list_model)

        # QStackedWidget 切换两种视图（Stage 5 Task 1）
        self._content_stack = QStackedWidget()

        # 列表视图（_RubberBandTableView，支持空白区域拖动框选，决策 3A）
        self._content_view = _RubberBandTableView()
        self._content_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._content_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._content_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # UX 重构 Phase 1 Task 4：启用拖拽（DragDrop 支持内部拖到文件夹）
        self._content_view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self._content_view.setDragEnabled(True)
        self._content_view.on_drop_to_folder = self._on_drop_to_folder
        self._content_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._content_view.verticalHeader().setVisible(False)
        self._content_view.horizontalHeader().setHighlightSections(False)
        self._content_view.horizontalHeader().setStretchLastSection(False)
        self._content_view.horizontalHeader().setSectionsClickable(True)
        self._content_view.setModel(self._content_list_model)
        # UI合理性2 + 验收反馈（2026-08-03）：setModel 会重置表头 resize 模式，
        # 须在 setModel 之后设置。四列全部 Interactive 固定默认宽度（Explorer 风格）：
        # 右侧留出空白供 rubber band 框选；列不随滚动条出现/消失而横移（中栏不跳）。
        # 宽度见 FILE_LIST_COLUMN_WIDTHS，用户可手动调整后重启生效。
        for col in (COL_NAME, COL_TYPE, COL_SIZE, COL_MODIFIED):
            self._content_view.setColumnWidth(col, ui.FILE_LIST_COLUMN_WIDTHS[col])
        # 固化（2026-08-03 验收反馈）：中栏列宽持久化——恢复存档（无则默认）、
        # 拖动即保存；重置布局时恢复默认。连接放在 restore 之后避免恢复触发保存。
        file_header = self._content_view.horizontalHeader()
        self._splitter_state.restore_header(
            file_header, ui.QSETTINGS_KEY_HEADER_FILE_LIST, ui.FILE_LIST_COLUMN_WIDTHS
        )
        file_header.sectionResized.connect(
            lambda *_: self._splitter_state.save_header(
                file_header, ui.QSETTINGS_KEY_HEADER_FILE_LIST
            )
        )
        self._content_view.doubleClicked.connect(self._on_entry_activated)
        self._content_view.customContextMenuRequested.connect(self._on_content_context_menu)
        self._content_view.horizontalHeader().sectionClicked.connect(
            self._on_content_header_clicked
        )
        self._content_view.selectionModel().selectionChanged.connect(
            self._on_content_selection_changed
        )
        self._content_stack.addWidget(self._content_view)  # index 0

        # 卡片视图（QListView，IconMode，大图）
        self._card_view = _DragDropListView()
        self._card_view.setViewMode(QListView.ViewMode.IconMode)
        self._card_view.setIconSize(QSize(ui.ZOOM_SLIDER_DEFAULT, ui.ZOOM_SLIDER_DEFAULT))
        # Task 2 验收修复：固定 gridSize 避免长文件名撑大卡片
        self._card_view.setGridSize(
            QSize(
                ui.ZOOM_SLIDER_DEFAULT + ui.CARD_GRID_PADDING_H,
                ui.ZOOM_SLIDER_DEFAULT + ui.CARD_GRID_PADDING_V,
            )
        )
        self._card_view.setResizeMode(QListView.ResizeMode.Adjust)
        self._card_view.setMovement(QListView.Movement.Static)
        self._card_view.setWordWrap(False)  # 长文件名 elide 不换行
        # Task 2 验收修复：尺寸固定后启用 uniformItemSizes 提升布局性能
        self._card_view.setUniformItemSizes(True)
        self._card_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._card_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._card_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # UX 重构 Phase 1 Task 4：启用拖拽（DragDrop 支持内部拖到文件夹）
        self._card_view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self._card_view.setDragEnabled(True)
        self._card_view.on_drop_to_folder = self._on_drop_to_folder
        self._card_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._card_view.setModel(self._card_list_model)
        self._card_view.doubleClicked.connect(self._on_entry_activated)
        self._card_view.customContextMenuRequested.connect(self._on_content_context_menu)
        self._card_view.selectionModel().selectionChanged.connect(
            self._on_content_selection_changed
        )
        # 卡片视图显式启用 rubber band（IconMode 默认启用，显式设置以保持一致）
        self._card_view.setSelectionRectVisible(True)
        self._content_stack.addWidget(self._card_view)  # index 1

        self._content_stack.setCurrentIndex(VIEW_INDEX_LIST)  # 默认列表视图
        content_layout.addWidget(self._content_stack)

        self._content_empty_hint = QLabel(ui.CONTENT_LIST_NO_SELECTION)
        self._content_empty_hint.setWordWrap(True)
        content_layout.addWidget(self._content_empty_hint)

        middle_layout.addWidget(self._content_group)

        splitter.addWidget(middle)

        # === 右栏：元数据（上）+ 装配面板（下），垂直分割（UX 重构 Phase 1 Task 2） ===
        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 上下分割：上方元数据，下方装配面板（初始比例 3:2，可拖拽调整）
        self._right_splitter = QSplitter(Qt.Vertical, self)

        self._metadata_group = QGroupBox(ui.METADATA_GROUP_TITLE)
        metadata_layout = QVBoxLayout(self._metadata_group)
        self._metadata_label = QLabel(ui.METADATA_NOT_SELECTED)
        # 元数据路径字段需要 Elide，整体不自动换行
        self._metadata_label.setWordWrap(False)
        self._metadata_label.setTextFormat(Qt.PlainText)
        self._metadata_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._metadata_full_text = ui.METADATA_NOT_SELECTED
        metadata_layout.addWidget(self._metadata_label)
        # Stage 4 Task 2：MetadataPanel 编辑表单（仅当注入 TagService 时启用）
        if self._tag_service is not None:
            self._metadata_panel = MetadataPanel(
                self._content_service,
                self._tag_service,
                # 操作便捷性4：标签即时保存（chip 增删立即提交）
                commit_callback=self._transaction_scope.commit,
                # UI合理性8：最近使用标签区域
                recent_tags=self._recent_tags,
                parent=self._metadata_group,
            )
            # UX 重构 Phase 2 Task 5 修复：注入 managed_root_service 用于路径简化显示
            self._metadata_panel.set_managed_root_service(self._service)
            # 面板信号由 MetadataView 接管（UX 重构 Task 7 Step 4）
            self._metadata_panel.setVisible(False)
            metadata_layout.addWidget(self._metadata_panel)
        else:
            self._metadata_panel = None  # type: ignore[assignment]
        self._right_splitter.addWidget(self._metadata_group)

        # 装配面板（UX 重构 Phase 1 Task 2：从中间区迁至右栏下方）：
        # 始终可见，未绑定时显示空状态占位「无固定内容」。
        # 移除关闭按钮（B1-1），on_panel_closed 回调不再注入。
        # UX 重构 Phase 1 Task 3：注入 on_pin_changed 回调处理钉住状态变化（B4）。
        if self._assembly_service is not None:
            self._assembly_panel = AssemblyPanel(
                self._assembly_service,
                on_cover_renamed=self._on_assembly_rename_cover,
                on_file_op=self._on_assembly_file_op,
                on_pin_changed=self._on_assembly_pin_changed,
                on_drop_files=self._on_drop_to_assembly,
            )
            self._right_splitter.addWidget(self._assembly_panel)
            # 初始比例与持久化由 SplitterStateHelper 恢复（默认值见 ui_constants）
            self._right_splitter.setStretchFactor(0, 5)
            self._right_splitter.setStretchFactor(1, 1)
        else:
            self._assembly_panel = None  # type: ignore[assignment]

        right_layout.addWidget(self._right_splitter)

        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        # UI合理性2 固化（2026-08-03 验收反馈）：拖动分隔线即实时保存，
        # 重启保留；closeEvent 保存作为兜底。setSizes 不触发 splitterMoved，无回环。
        self._splitter.splitterMoved.connect(
            lambda *_: self._splitter_state.save(self._splitter, ui.QSETTINGS_KEY_SPLITTER_MAIN)
        )
        self._right_splitter.splitterMoved.connect(
            lambda *_: self._splitter_state.save(
                self._right_splitter, ui.QSETTINGS_KEY_SPLITTER_RIGHT
            )
        )

        # 主布局：顶部模式栏 + 三栏 splitter
        central = QWidget(self)
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(top_bar)
        central_layout.addWidget(splitter, stretch=1)
        self.setCentralWidget(central)

        # UI合理性3：顶部菜单栏（独立 view，MainWindow 仅接线）
        self._menu_bar = MainMenuBar(self)
        self._menu_bar.layout_reset_requested.connect(self._on_layout_reset)
        self._menu_bar.switch_view_requested.connect(self._on_menu_view_switch)
        self._menu_bar.tag_manager_requested.connect(self._on_tag_manager_clicked)
        self._menu_bar.operation_history_requested.connect(self._on_operation_history_clicked)
        # 工具菜单项按注入服务开关（与工具栏按钮可见性一致）
        self._menu_bar.set_tag_manager_visible(self._tag_service is not None)
        self._menu_bar.set_operation_history_visible(self._undo_service is not None)
        self.setMenuBar(self._menu_bar)

        # UX 重构 Phase 2 Task 5（Q7=A）：状态栏统一到 QStatusBar
        self._setup_status_bar()

    def _setup_status_bar(self) -> None:
        """统一状态栏（Q7=A）。

        - 持久 QLabel（_status_label）：显示扫描状态（就绪/扫描中/完成/失败），
          通过 addWidget 挂到 QStatusBar 左侧，不会被 showMessage 临时消息覆盖。
        - showMessage：用于操作提示（复制路径/重命名成功等），短暂显示后自动消失。
        - 消除原左侧 QGroupBox + 底部 QLabel 并存导致的布局抖动。
        """
        status_bar = self.statusBar()
        status_bar.setSizeGripEnabled(False)
        status_bar.addWidget(self._status_label)

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
        scanning = self._scan_controller.is_scanning()
        self._scan_button.setEnabled(has_selection and not scanning)
        self._scan_full_button.setEnabled(has_selection and not scanning)
        self._remove_button.setEnabled(has_selection and not scanning)

    # --- 目录树 ---

    def _refresh_tree(self) -> None:
        """刷新目录树模型。

        2026-07-16 优化：刷新前保存展开状态与选中节点，刷新后递归恢复，
        避免每次扫描/创建 Mod 组后目录树全部折叠。
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
        # 清空文件列表与元数据
        self._content_list_model.refresh([])
        self._content_empty_hint.setText(ui.CONTENT_LIST_NO_SELECTION)
        self._set_metadata_text(ui.METADATA_NOT_SELECTED)

    def _on_tree_selection_changed(self, *args) -> None:  # noqa: ANN001 (Qt 信号)
        """目录树选中变化时更新详情区与文件列表。

        UX 重构 Phase 1 Task 1：移除模式分支，统一为 browse 行为。
        - 刷新详情区 + 刷新中栏文件列表 + 清空元数据。
        """
        indexes = self._tree_view.selectionModel().selectedIndexes()
        if not indexes:
            self._set_detail_text(ui.DETAIL_NOT_SELECTED)
            self._content_list_model.refresh([])
            self._content_empty_hint.setText(ui.CONTENT_LIST_NO_SELECTION)
            return

        index = indexes[0]
        node = self._tree_model.node_at(index)
        if node is None:
            self._set_detail_text(ui.DETAIL_NOT_SELECTED)
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

        display_path = make_display_path_from_service(node.real_path, self._service)
        lines = [
            f"{ui.DETAIL_NAME_LABEL}：{node.display_name}",
            f"{ui.DETAIL_PATH_LABEL}：{display_path}",
            f"{ui.DETAIL_IS_ROOT_LABEL}：{'是' if node.is_managed_root else '否'}",
            f"{ui.DETAIL_TYPE_LABEL}：{type_text}",
            f"{ui.DETAIL_CHILD_COUNT_LABEL}：{child_count}",
        ]
        self._set_detail_text("\n".join(lines))

        # 刷新文件列表（使用 node.real_path 读取目录条目）
        self._refresh_content_list(node.real_path)
        # 清空元数据面板（切换目录时重置）
        self._set_metadata_text(ui.METADATA_NOT_SELECTED)

    def _refresh_content_list(self, dir_path: str) -> None:
        """刷新文件列表（数据源为文件系统，content_unit 表仅作标记）。

        Stage 4 Task 3：若 TagFilterBar 筛选激活，按筛选结果过滤条目。
        - 筛选激活时：仅显示匹配的内容单元条目（Q1: B）。非内容单元条目与
          不匹配的内容单元条目全部隐藏，列表变成纯结果集。
        - 筛选未激活：显示全量条目。
        - 切换目录时筛选状态保留（Q3: A），自动应用于新目录。
        """
        try:
            entries = self._content_service.list_directory_entries(dir_path)
        except Exception:  # noqa: BLE001 - UI 边界需捕获所有异常
            logger.exception("加载文件列表失败：dir_path=%s", dir_path)
            entries = []

        entries = self._apply_tag_filter(entries)
        self._content_list_model.refresh(entries)
        if not entries:
            if self._is_tag_filter_active():
                self._content_empty_hint.setText(ui.TAG_FILTER_NO_RESULT_HINT)
            else:
                self._content_empty_hint.setText(ui.CONTENT_LIST_EMPTY_HINT)
        else:
            self._content_empty_hint.setText("")
        # Stage 5 Task 2：记录目录导航历史
        self._record_nav_history(dir_path)

    # --- 标签筛选（Stage 4 Task 3） ---

    def _is_tag_filter_active(self) -> bool:
        """返回 TagFilterBar 是否激活（已选标签数 > 0）。

        TagService 未注入时返回 False。
        """
        return self._tag_filter_bar is not None and self._tag_filter_bar.is_filter_active()

    def _apply_tag_filter(self, entries: list) -> list:
        """按当前 TagFilterBar 筛选状态过滤条目。

        - 筛选未激活：原样返回。
        - 筛选激活：仅保留 entry.content_unit is not None 且
          entry.content_unit.id 在筛选结果集合中的条目（Q1: B）。
        """
        if not self._is_tag_filter_active():
            return entries
        if self._tag_filter_bar is None:
            return entries

        selected_tag_ids = self._tag_filter_bar.current_selected_tag_ids()
        try:
            allowed_unit_ids = self._tag_service.filter_unit_ids_by_category_and(
                list(selected_tag_ids)
            )
        except Exception:  # noqa: BLE001
            logger.exception("标签筛选失败，回退到无筛选")
            return entries

        return [
            entry
            for entry in entries
            if entry.content_unit is not None and entry.content_unit.id in allowed_unit_ids
        ]

    def _on_tag_filter_changed(self, selected_tag_ids: set[str]) -> None:
        """TagFilterBar 选中标签变化时重新刷新中栏（应用筛选）。

        Stage 4 Task 3（Q6: A 修正）：筛选激活时保留 MetadataPanel 可见性，
        用户可继续查看选中条目的元数据。若当前选中行被筛选过滤掉，
        MetadataPanel 保持上一次加载的内容（不主动清空），避免干扰用户。
        - 仅中栏可见时响应（TagFilterBar 常驻中栏顶部）。
        """
        self._refresh_content_list_for_current_mode()

    def _refresh_tag_filter_bar(self) -> None:
        """刷新 TagFilterBar 的可选标签（标签管理对话框关闭后调用）。"""
        if self._tag_filter_bar is not None:
            self._tag_filter_bar.refresh_categories()

    # --- 文件条目 ---

    def _on_entry_activated(self, index) -> None:  # noqa: ANN001 (Qt 信号)
        """双击文件条目。

        交互行为（2026-07-17 调整）：
        - 双击文件夹 → 进入该目录（无论是否内容单元，优先于元数据显示）。
          文件夹的元数据通过单击选中查看（_on_content_selection_changed）。
        - 双击文件类型内容单元（压缩包）→ 显示元数据面板。
        - 双击普通文件 / 普通文件夹 → 不响应（右键「打开」可用系统默认程序打开）。

        Stage 5 Task 1：支持列表视图和卡片视图，两个视图共享同一份 FileEntry 数据
        （行号一致），因此用任一 model 取 entry 均可。这里用当前活动视图对应的 model。
        """
        # 两个视图共享同一份数据（行号一致），用任一 model 取 entry 均可
        active_model = (
            self._card_list_model
            if self._current_view_index == VIEW_INDEX_CARD
            else self._content_list_model
        )
        entry = active_model.entry_at(index.row())
        if entry is None:
            return

        # 双击文件夹 → 进入该目录（优先于内容单元判断）
        # 文件夹即使被标记为内容单元（如 Mod 组），双击也进入目录；
        # 元数据通过单击查看。
        # UX 重构 Phase 1 Task 1：移除模式分支，双击始终进入目录。
        if entry.is_dir:
            # 同步目录树选中节点到当前浏览目录（2026-07-17 修复）：
            # 原实现只刷新中栏，不更新 tree_view.selectionModel()，导致后续依赖
            # 该 selection 的刷新逻辑（_refresh_content_list_for_current_mode /
            # _refresh_content_list_after_scan）误用陈旧的选中节点，
            # 中栏在标记内容单元后"退回"父目录显示。
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

        # 双击文件类型内容单元 → 显示元数据
        if entry.content_unit is not None:
            self._update_metadata(entry.content_unit)
            return

        # 其他情况（普通文件）：不响应

    def _on_entry_activated_for_entry(self, entry: FileEntry) -> None:
        """右键菜单「打开」项的 handler（UX 重构 Phase 2 Task 5，Q1=B）。

        行为与双击（_on_entry_activated）一致：
        - 文件夹 → 进入该目录
        - 文件类型内容单元 → 显示元数据面板
        - 普通文件 → 尝试用系统默认程序打开

        Args:
            entry: 要打开的条目。
        """
        # 复用双击逻辑：构造一个伪 index 不可行（需要 model），
        # 直接内联双击的关键逻辑。
        if entry.is_dir:
            # 进入文件夹：同步目录树选中
            target_idx = self._tree_model.find_index_by_path(self._tree_view, entry.path)
            if target_idx.isValid():
                self._tree_view.setCurrentIndex(target_idx)
                self._set_metadata_text(ui.METADATA_NOT_SELECTED)
            else:
                logger.warning(
                    "右键打开：未在目录树中找到匹配节点，回退到手动刷新：path=%s",
                    entry.path,
                )
                self._refresh_content_list(entry.path)
                self._set_metadata_text(ui.METADATA_NOT_SELECTED)
            return

        # 文件类型内容单元 → 显示元数据
        if entry.content_unit is not None:
            self._update_metadata(entry.content_unit)
            return

        # 普通文件 → 用系统默认程序打开
        try:
            subprocess.run(
                ["cmd", "/c", "start", "", entry.path],
                check=False,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):  # noqa: BLE001
            logger.exception("系统打开文件失败：path=%s", entry.path)
            QMessageBox.information(
                self, ui.MENU_OPEN, ui.MENU_OPERATION_FAILED.format(error="无法打开文件")
            )

    def _on_content_selection_changed(self, *args) -> None:  # noqa: N802, ANN001 (Qt 信号)
        """文件列表选中变化：单击选中条目 → 右栏同步更新元数据与装配面板。

        UX 重构 Phase 1 Task 2（A1-1 决策）：
        - 单选文件夹内容单元 → 显示元数据 + 绑定装配面板显示其内部文件。
        - 单选文件类型内容单元 → 显示元数据 + 装配面板解绑显空状态。
        - 单选非内容单元 → 清空元数据 + 装配面板解绑显空状态。
        - 多选 → 清空元数据 + 装配面板解绑显空状态（避免混淆）。
        - 双击文件夹 → 进入目录（_on_entry_activated 处理，与单击不冲突）。

        信号循环防护（用户补充注意）：
        _bind_assembly_panel → bind_mod_group → _refresh_file_list 仅刷新装配面板
        内部 AssemblyListModel，不反向修改 content_view 选区，因此 selectionChanged
        不会再次触发本方法。元数据更新同理。

        Stage 5 Task 1：支持列表视图和卡片视图，根据当前活动视图获取选中。
        """
        # 取当前活动视图（列表 or 卡片）
        active_view = (
            self._card_view if self._current_view_index == VIEW_INDEX_CARD else self._content_view
        )
        active_model = (
            self._card_list_model
            if self._current_view_index == VIEW_INDEX_CARD
            else self._content_list_model
        )
        sm = active_view.selectionModel()
        if sm is None:
            return
        indexes = sm.selectedRows()
        if not indexes:
            return
        # 多选：清空元数据 + 解绑装配面板
        if len(indexes) > 1:
            self._set_metadata_text(ui.METADATA_NOT_SELECTED)
            self._bind_assembly_panel(None)
            return
        entry = active_model.entry_at(indexes[0].row())
        if entry is None:
            return
        if entry.content_unit is not None:
            # 显示元数据
            self._update_metadata(entry.content_unit)
            # 文件夹内容单元 → 绑定装配面板（保留 unit 关联用于封面重命名）
            # 文件类型内容单元 → 解绑装配面板
            self._bind_assembly_panel(entry.content_unit if entry.is_dir else None)
        elif entry.is_dir:
            # UX 重构 Phase 1 Task 2：非内容单元文件夹 → 装配面板透视（文件夹透视器语义）
            # 清空元数据（非内容单元无元数据），装配面板按路径透视显示其内部文件
            self._set_metadata_text(ui.METADATA_NOT_SELECTED)
            self._bind_assembly_folder(Path(entry.path))
        else:
            # 非内容单元文件
            # 操作合理性2（2026-08-03）：图片文件 → 元数据面板直接预览原图
            # （无缓存、不写数据库）；其他文件 → 清空元数据（显示提示文本）。
            if self._metadata_panel is not None and self._content_service.is_image_file(entry.path):
                self._metadata_label.setVisible(False)
                self._metadata_view.show_image_preview(Path(entry.path))
            else:
                self._set_metadata_text(ui.METADATA_NOT_SELECTED)
            self._bind_assembly_panel(None)

    def _on_content_header_clicked(self, column: int) -> None:  # noqa: N802 (Qt 命名)
        """文件列表列头点击：切换排序键，同列再点切换升降序。

        阶段 3 Task 2：列头排序。点击不同列切换排序键；点击同列切换升降序。
        Stage 5 Task 2：同步排序下拉框与方向按钮状态。
        """
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
        self._sync_sort_controls()

    # --- Stage 5 Task 2：排序下拉框 + 方向按钮 ---

    _SORT_KEY_TO_INDEX = {
        SORT_NAME: 0,
        SORT_TYPE: 1,
        SORT_SIZE: 2,
        SORT_MODIFIED: 3,
    }

    def _on_sort_field_activated(self, combo_index: int) -> None:
        """排序字段下拉框 activated 信号：用户主动点击下拉项时触发。

        Stage 5 Task 2 验收修复（最终版）：仅用 activated 单信号。
        - activated 在用户点击下拉项时触发，程序化 setCurrentIndex 不触发
          （避免 _sync_sort_controls 同步时死循环）
        - “选当前项重新排序”无产品意义，不予支持（currentIndex 不变时
          Qt 不会触发 activated，此场景下排序不变是预期行为）
        - 幂等保护：若 sort_key 与当前一致且方向也未变，set_sort_key 内部
          会提前返回，避免重复 reset model 造成 view 异常
        """
        sort_key = self._sort_field_combo.itemData(combo_index)
        if sort_key is None:
            return
        ascending = self._content_list_model.is_sort_ascending()
        self._content_list_model.set_sort_key(sort_key, ascending)
        self._sync_sort_direction_button(ascending)

    def _on_sort_direction_clicked(self) -> None:
        """升降序按钮点击：翻转方向（不依赖 checked 状态，从 model 读取当前方向取反）。"""
        ascending = not self._content_list_model.is_sort_ascending()
        current_key = self._content_list_model.current_sort_key()
        self._content_list_model.set_sort_key(current_key, ascending)
        self._sync_sort_direction_button(ascending)

    def _sync_sort_controls(self) -> None:
        """同步排序下拉框与方向按钮到 FileListModel 当前状态。

        Stage 5 Task 2 验收修复（最终版）：activated 不受 blockSignals 影响
        （程序化 setCurrentIndex 本就不触发 activated），blockSignals 仅用于
        阻止 currentIndexChanged——当前已不连接该信号，保留 blockSignals 作为
        防御性措施，避免未来误连接其他信号时死循环。
        """
        current_key = self._content_list_model.current_sort_key()
        ascending = self._content_list_model.is_sort_ascending()
        target_index = self._SORT_KEY_TO_INDEX.get(current_key, 0)
        if self._sort_field_combo.currentIndex() != target_index:
            self._sort_field_combo.blockSignals(True)
            self._sort_field_combo.setCurrentIndex(target_index)
            self._sort_field_combo.blockSignals(False)
        self._sync_sort_direction_button(ascending)

    def _sync_sort_direction_button(self, ascending: bool) -> None:
        """同步方向按钮文本与 tooltip（不使用 checked 状态）。"""
        if ascending:
            self._sort_dir_button.setText(ui.SORT_ASC_SYMBOL)
            self._sort_dir_button.setToolTip(ui.SORT_DIRECTION_ASC_TOOLTIP)
        else:
            self._sort_dir_button.setText(ui.SORT_DESC_SYMBOL)
            self._sort_dir_button.setToolTip(ui.SORT_DIRECTION_DESC_TOOLTIP)

    # --- Stage 5 Task 2：前进/后退目录导航 ---

    def _on_nav_back_clicked(self) -> None:
        """后退按钮：切换到上一个浏览目录。"""
        if not self._nav_back_stack:
            return
        current = self._current_nav_path
        target = self._nav_back_stack.pop()
        if current is not None:
            self._nav_forward_stack.append(current)
        self._navigating_from_history = True
        try:
            self._navigate_to_directory(target)
            # _record_nav_history 被 navigating_from_history 跳过，需手动更新
            self._current_nav_path = target
        finally:
            self._navigating_from_history = False
        self._update_nav_buttons()

    def _on_nav_forward_clicked(self) -> None:
        """前进按钮：切换到下一个浏览目录。"""
        if not self._nav_forward_stack:
            return
        current = self._current_nav_path
        target = self._nav_forward_stack.pop()
        if current is not None:
            self._nav_back_stack.append(current)
        self._navigating_from_history = True
        try:
            self._navigate_to_directory(target)
            # _record_nav_history 被 navigating_from_history 跳过，需手动更新
            self._current_nav_path = target
        finally:
            self._navigating_from_history = False
        self._update_nav_buttons()

    def _navigate_to_directory(self, dir_path: str) -> None:
        """切换到指定目录（通过目录树选中触发，复用既有刷新链路）。

        未在目录树中找到节点时回退到直接刷新文件列表。
        """
        target_idx = self._tree_model.find_index_by_path(self._tree_view, dir_path)
        if target_idx.isValid():
            self._tree_view.setCurrentIndex(target_idx)
        else:
            # 未扫描的子目录：直接刷新中栏（不走 tree selection 链路）
            self._refresh_content_list(dir_path)
            self._set_metadata_text(ui.METADATA_NOT_SELECTED)

    # === Stage 5 Task 7：全局搜索 ===

    def _on_search_triggered(self) -> None:
        """搜索框回车触发（Q1=A）。

        - 空白输入不触发
        - 调用 SearchService.search 获取结果
        - 弹出非模态 SearchDialog（Q3=B）
        - 复用已有对话框实例（避免重复弹出）
        """
        if self._search_service is None:
            return
        query = self._search_box.text().strip()
        if not query:
            return

        from application.errors import SearchError  # noqa: PLC0415

        try:
            results = self._search_service.search(query)
        except SearchError as e:
            QMessageBox.information(
                self,
                ui.SEARCH_DIALOG_TITLE,
                ui.SEARCH_DIALOG_ERROR.format(error=str(e)),
            )
            return
        except Exception as e:  # noqa: BLE001 - 兜底，确保 UI 收到友好错误
            logger.exception("搜索发生未预期异常：query=%s", query)
            QMessageBox.information(
                self,
                ui.SEARCH_DIALOG_TITLE,
                ui.SEARCH_DIALOG_ERROR.format(error=str(e)),
            )
            return

        # 复用对话框实例：若已存在则更新内容，否则新建
        from app.search_dialog import SearchDialog  # noqa: PLC0415

        if self._search_dialog is not None and isinstance(self._search_dialog, SearchDialog):
            # 更新现有对话框内容
            self._search_dialog.update_results(query, results)
        else:
            self._search_dialog = SearchDialog(
                query=query,
                results=results,
                jump_callback=self._on_search_result_clicked,
                parent=self,
            )
        # Q3=B 非模态：show() 而非 exec()
        self._search_dialog.show()
        self._search_dialog.raise_()
        self._search_dialog.activateWindow()

    def _on_search_result_clicked(self, unit_id: str) -> None:
        """搜索结果双击跳转回调（Q4=B）。

        - Q4=B：跳转到所在目录 + 选中条目 + 保持对话框打开
        - UX 重构 Phase 1 Task 1：移除模式分支，搜索跳转始终允许。
        """
        if self._content_service is None:
            return

        unit = self._content_service.get_by_id(unit_id)
        if unit is None:
            # 内容单元可能已被删除，提示并刷新搜索结果
            QMessageBox.information(
                self,
                ui.SEARCH_DIALOG_TITLE,
                ui.SEARCH_DIALOG_EMPTY,
            )
            return

        # 跳转到内容单元所在目录
        parent_dir = str(Path(unit.path).parent)
        self._navigate_to_directory(parent_dir)

        # 延迟选中中栏对应条目（目录刷新后才能匹配）
        # 使用 QTimer.singleShot 给目录树 selection 信号链路留出刷新时间
        from PySide6.QtCore import QTimer  # noqa: PLC0415

        target_path = unit.path

        def _select_in_content_list() -> None:
            """在文件列表中选中对应条目（若可见）。"""
            view = self._content_view_current()
            if view is None:
                return
            model = view.model()
            if model is None:
                return
            # 在 model 中查找 path 匹配的行
            for row in range(model.rowCount()):
                idx = model.index(row, 0)
                data = idx.data(Qt.UserRole)
                if isinstance(data, FileEntry) and data.path == target_path:
                    view.setCurrentIndex(idx)
                    return

        QTimer.singleShot(100, _select_in_content_list)

    def _content_view_current(self) -> QAbstractItemView | None:
        """返回当前激活的内容视图（列表或卡片）。"""
        current_widget = self._content_stack.currentWidget()
        if current_widget is self._content_view:
            return self._content_view
        if current_widget is self._card_view:
            return self._card_view
        return None

    def _record_nav_history(self, dir_path: str) -> None:
        """记录浏览历史（非历史导航时调用）。

        - 相邻相同路径不入栈（避免重复）
        - 历史导航触发的切换不记录（避免循环）
        """
        if self._navigating_from_history:
            return
        # 相邻相同路径去重
        if self._current_nav_path == dir_path:
            return
        if self._current_nav_path is not None:
            self._nav_back_stack.append(self._current_nav_path)
        # 进入新目录时清空前进栈（标准浏览器行为）
        self._nav_forward_stack.clear()
        self._current_nav_path = dir_path
        self._update_nav_buttons()

    def _update_nav_buttons(self) -> None:
        """根据栈状态更新前进/后退按钮可用性。"""
        self._nav_back_button.setEnabled(len(self._nav_back_stack) > 0)
        self._nav_forward_button.setEnabled(len(self._nav_forward_stack) > 0)

    # --- Stage 5 Task 1：视图切换 + 缩放 ---

    def _switch_view(self, view_index: int) -> None:
        """切换文件列表视图（列表 ↔ 卡片）。

        Q1=A：视图切换按钮组独立一行。
        Q4=A：选中状态跨视图保持（用 entry.path 匹配，行号可能因排序不同而变化）。
        """
        if view_index == self._current_view_index:
            return
        # 记录当前选中条目的 path 集合（从当前活动视图读取）
        selected_paths: set[str] = set()
        current_view = (
            self._card_view if self._current_view_index == VIEW_INDEX_CARD else self._content_view
        )
        current_model = (
            self._card_list_model
            if self._current_view_index == VIEW_INDEX_CARD
            else self._content_list_model
        )
        sm = current_view.selectionModel()
        if sm is not None:
            for idx in sm.selectedRows():
                entry = current_model.entry_at(idx.row())
                if entry is not None:
                    selected_paths.add(entry.path)
        # 切换视图
        self._content_stack.setCurrentIndex(view_index)
        self._current_view_index = view_index
        # 在新视图中恢复选中
        target_view = self._card_view if view_index == VIEW_INDEX_CARD else self._content_view
        target_model = (
            self._card_list_model if view_index == VIEW_INDEX_CARD else self._content_list_model
        )
        target_sm = target_view.selectionModel()
        if target_sm is not None and selected_paths:
            # 清除现有选中
            target_sm.clearSelection()
            # 按 path 重新选中对应行（select 会自动触发 selectionChanged 信号）
            # 注意：QTableView 多列场景必须用 Select | Rows 才能选中整行，
            # 仅 Select 只选中 (row, 0) 单元格，selectedRows() 返回空。
            for row in range(target_model.rowCount()):
                entry = target_model.entry_at(row) if hasattr(target_model, "entry_at") else None
                if entry is not None and entry.path in selected_paths:
                    idx = target_model.index(row, 0)
                    target_sm.select(
                        idx,
                        QItemSelectionModel.SelectionFlag.Select
                        | QItemSelectionModel.SelectionFlag.Rows,
                    )
        # 持久化视图模式（Q1=A）
        view_mode = "card" if view_index == VIEW_INDEX_CARD else "list"
        self._qsettings.setValue(ui.QSETTINGS_KEY_VIEW_MODE, view_mode)
        # UI合理性3：同步菜单栏视图选中态
        self._menu_bar.set_view(view_mode)
        # UI合理性3 验收反馈：菜单切换时同步中栏列表/卡片按钮选中态
        # （按钮自身点击时 Qt 已自动勾选，此处幂等）
        if view_index == VIEW_INDEX_CARD:
            self._view_card_button.setChecked(True)
        else:
            self._view_list_button.setChecked(True)

    def _on_zoom_combo_changed(self, index: int) -> None:
        """缩放下拉框变化：应用缩放并持久化。"""
        size = self._zoom_combo.itemData(index)
        if not isinstance(size, int):
            return
        self._apply_zoom(size)

    def _apply_zoom(self, value: int) -> None:
        """应用缩放值：调整卡片图标尺寸并持久化。"""
        self._card_icon_size = value
        self._card_view.setIconSize(QSize(value, value))
        # Task 2 验收修复：iconSize 变化时同步 gridSize，保持固定网格
        self._card_view.setGridSize(
            QSize(
                value + ui.CARD_GRID_PADDING_H,
                value + ui.CARD_GRID_PADDING_V,
            )
        )
        self._card_list_model.set_icon_size(value)
        self._card_view.doItemsLayout()
        self._qsettings.setValue(ui.QSETTINGS_KEY_ZOOM, value)

    def _restore_view_state(self) -> None:
        """从 QSettings 恢复缩放值与视图模式（Q1=A）。"""
        zoom = self._qsettings.value(ui.QSETTINGS_KEY_ZOOM, ui.ZOOM_SLIDER_DEFAULT, type=int)
        if zoom in ui.ZOOM_PRESET_SIZES:
            index = ui.ZOOM_PRESET_SIZES.index(zoom)
            self._zoom_combo.setCurrentIndex(index)
            self._card_view.setIconSize(QSize(zoom, zoom))
            # Task 2 验收修复：恢复时同步 gridSize
            self._card_view.setGridSize(
                QSize(
                    zoom + ui.CARD_GRID_PADDING_H,
                    zoom + ui.CARD_GRID_PADDING_V,
                )
            )
            self._card_list_model.set_icon_size(zoom)
            self._card_view.doItemsLayout()
            self._card_icon_size = zoom
        # 恢复视图模式
        view_mode = self._qsettings.value(ui.QSETTINGS_KEY_VIEW_MODE, "list", type=str)
        if view_mode == "card":
            self._view_card_button.setChecked(True)
            self._switch_view(VIEW_INDEX_CARD)
        else:
            self._view_list_button.setChecked(True)
            self._switch_view(VIEW_INDEX_LIST)

    def _restore_splitter_state(self) -> None:
        """UI合理性2：恢复分割线尺寸（无存档时应用默认比例，接线级）。"""
        # 主栏：默认 220/480/324（中栏加宽，解决名称列过窄）；
        # 右栏：默认 625:125（保持既有行为）。默认值见 ui_constants，可手动调整。
        self._splitter_state.restore(
            self._splitter,
            ui.QSETTINGS_KEY_SPLITTER_MAIN,
            default_sizes=ui.LAYOUT_MAIN_SPLITTER_DEFAULT_SIZES,
        )
        self._splitter_state.restore(
            self._right_splitter,
            ui.QSETTINGS_KEY_SPLITTER_RIGHT,
            default_sizes=ui.LAYOUT_RIGHT_SPLITTER_DEFAULT_SIZES,
        )

    def _on_layout_reset(self) -> None:
        """UI合理性2/3：菜单「重置布局」→ 分割线与操作历史列宽恢复默认比例。"""
        self._splitter_state.reset(
            self._splitter,
            ui.QSETTINGS_KEY_SPLITTER_MAIN,
            ui.LAYOUT_MAIN_SPLITTER_DEFAULT_SIZES,
        )
        self._splitter_state.reset(
            self._right_splitter,
            ui.QSETTINGS_KEY_SPLITTER_RIGHT,
            ui.LAYOUT_RIGHT_SPLITTER_DEFAULT_SIZES,
        )
        # 中栏文件列表列宽：实时恢复默认（非模态，可立即生效）
        self._splitter_state.reset_header(
            self._content_view.horizontalHeader(),
            ui.QSETTINGS_KEY_HEADER_FILE_LIST,
            ui.FILE_LIST_COLUMN_WIDTHS,
        )
        # 操作历史对话框为模态，无法实时重置；删除存档使下次打开即回默认
        self._splitter_state.remove_key(ui.QSETTINGS_KEY_HEADER_OPERATION_HISTORY)
        self.statusBar().showMessage(ui.LAYOUT_RESET_STATUS, 3000)

    def _on_menu_view_switch(self, mode: str) -> None:
        """UI合理性3：菜单视图切换 → 复用既有 _switch_view。"""
        view_index = VIEW_INDEX_CARD if mode == "card" else VIEW_INDEX_LIST
        self._switch_view(view_index)

    def _on_open_in_explorer(self, path: str) -> None:
        """在 Windows 资源管理器中打开并选中指定路径（Stage 5 Task 1）。

        使用 explorer /select, 命令定位到文件并选中。中文路径通过 list 形式传参自动处理。
        """
        try:
            subprocess.run(
                ["explorer", "/select,", path],
                check=False,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):  # noqa: BLE001
            logger.exception("打开资源管理器失败：path=%s", path)
            QMessageBox.information(self, ui.MENU_OPEN_IN_EXPLORER, ui.MENU_OPEN_IN_EXPLORER_FAILED)

    def _on_tree_context_menu(self, pos: QPoint) -> None:  # noqa: N802 (Qt 命名)
        """目录树右键菜单：新建文件夹 + 在资源管理器中打开 + 折叠全部。

        Stage 5 Task 1：新增「在资源管理器中打开」项，无论是否选中节点都可用。
        Stage 5 Task 3a：新增「新建文件夹」项，仅注入 FileOperationService 时显示。
            选中节点即在其目录下创建子文件夹，与中栏右键入口行为一致。
        Stage 5 Task 7：新增「折叠全部」项，无论是否选中节点都显示。
            搜索跳转会导致目录树展开很多节点，此入口用于快速收起。
        UX 重构 Phase 1 Task 1 Commit 2：移除暂存区标记/取消菜单项。
        """
        index = self._tree_view.indexAt(pos)
        node = self._tree_model.node_at(index) if index.isValid() else None

        menu = QMenu(self)
        # 节点相关菜单项（仅在选中有效节点时显示）
        new_folder_action = None
        delete_action = None
        copy_action = None
        cut_action = None
        paste_action = None
        move_to_action = None
        explorer_action = None
        pin_action = None
        unpin_action = None
        if node is not None:
            # 新建文件夹 / 删除（Stage 5 Task 3a，仅需 FileOperationService）
            if self._file_operation_service is not None:
                new_folder_action = menu.addAction(ui.MENU_NEW_FOLDER)
                if self._clipboard_service is not None:
                    copy_action = menu.addAction(ui.MENU_COPY)
                    cut_action = menu.addAction(ui.MENU_CUT)
                    # 粘贴项仅在剪贴板非空时启用
                    paste_action = menu.addAction(ui.MENU_PASTE)
                    paste_action.setEnabled(self._clipboard_service.get() is not None)
                move_to_action = menu.addAction(ui.MENU_MOVE_TO)
                delete_action = menu.addAction(ui.MENU_DELETE)
            # 在资源管理器中打开（Stage 5 Task 1，节点有效时显示）
            explorer_action = menu.addAction(ui.MENU_OPEN_IN_EXPLORER)

            # UX 重构 Phase 2 Task 5（Q2=C）：钉住/取消钉住
            if self._assembly_panel is not None:
                if self._assembly_panel.is_pinned():
                    unpin_action = menu.addAction(ui.MENU_UNPIN_FOLDER)
                else:
                    # 未钉住 → 显示「钉住此文件夹」
                    pin_action = menu.addAction(ui.MENU_PIN_FOLDER)

        # 折叠全部（Stage 5 Task 7，无论是否选中节点都显示）
        if node is not None:
            menu.addSeparator()
        collapse_action = menu.addAction(ui.MENU_COLLAPSE_ALL)

        # 操作便捷性3：在「移动到...」后插入「移动到最近目录」子菜单（节点有效时）
        if node is not None and move_to_action is not None:
            self._insert_recent_move_submenu(menu, [Path(node.real_path)])

        chosen = menu.exec(self._tree_view.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if new_folder_action is not None and chosen is new_folder_action:
            self._on_new_folder_in_dir(node.real_path)
        elif copy_action is not None and chosen is copy_action:
            self._on_shortcut_copy_tree()
        elif cut_action is not None and chosen is cut_action:
            self._on_shortcut_cut_tree()
        elif paste_action is not None and chosen is paste_action:
            self._on_shortcut_paste_tree()
        elif move_to_action is not None and chosen is move_to_action:
            self._on_move_to_tree(node)
        elif delete_action is not None and chosen is delete_action:
            self._on_shortcut_delete_tree()
        elif explorer_action is not None and chosen is explorer_action:
            self._on_open_in_explorer(node.real_path)
        elif pin_action is not None and chosen is pin_action:
            self._pin_folder_from_context(Path(node.real_path))
        elif unpin_action is not None and chosen is unpin_action:
            self._unpin_from_context()
        elif chosen is collapse_action:
            self._collapse_all_tree()

    def _collapse_all_tree(self) -> None:
        """折叠目录树所有展开的节点（Stage 5 Task 7）。

        搜索跳转会展开大量节点，此功能用于快速收起。
        折叠后保留根节点的展开状态（顶层受管理根目录列表仍可见）。
        """
        self._tree_view.collapseAll()
        # 重新展开 model 根节点（其子节点 = 受管理根目录列表）
        root_idx = self._tree_model.index(0, 0)
        if root_idx.isValid():
            self._tree_view.setExpanded(root_idx, True)

    def _on_content_context_menu(self, pos: QPoint) -> None:  # noqa: N802 (Qt 命名)
        """文件列表右键菜单：根据选中条目与模式动态构造。

        Stage 5 Task 1：支持列表视图和卡片视图，根据当前活动视图获取选中条目。
        Stage 5 Task 3a：空白区域右键显示"新建文件夹"（基于当前目录）。

        菜单项：
        - 创建 Mod 组：单选或多选文件 + 注入了 ContentUnitCreationService 时显示。
        - 标记为内容单元 / 把每个文件标记为内容单元：未标记条目。
        - 取消标记：已标记 ContentUnit。
        - 快速设置封面：已标记文件夹内容单元（压缩包内容单元灰显）。
        - 新建文件夹 / 重命名 / 删除（Stage 5 Task 3a）。
        - 在资源管理器中打开：始终显示（Stage 5 Task 1）。
        - 复制路径：始终显示。

        UX 重构 Phase 1 Task 2（B2-2）：「加入装配」菜单项已移除，
        Task 4 将由「添加到钉住文件夹」+ 拖拽替代。
        """
        # 取当前活动视图（列表 or 卡片）
        active_view = (
            self._card_view if self._current_view_index == VIEW_INDEX_CARD else self._content_view
        )
        active_model = (
            self._card_list_model
            if self._current_view_index == VIEW_INDEX_CARD
            else self._content_list_model
        )
        sm = active_view.selectionModel()
        if sm is None:
            return
        selected_rows = sm.selectedRows()

        entries: list[FileEntry] = []
        for idx in selected_rows:
            entry = active_model.entry_at(idx.row())
            if entry is not None:
                entries.append(entry)

        # Stage 5 Task 3a：空白区域右键 → 显示"新建文件夹"（基于当前目录）
        if not entries:
            self._show_empty_area_context_menu(active_view, pos)
            return

        actions = self._build_content_menu_actions(entries)
        if not actions:
            return

        menu = QMenu(self)
        for label, _, enabled in actions:
            act = menu.addAction(label)
            act.setEnabled(enabled)

        # 操作便捷性3：在「移动到...」后插入「移动到最近目录」子菜单
        self._insert_recent_move_submenu(menu, [Path(e.path) for e in entries])
        # UI合理性8：内容单元右键 → 「添加最近标签 ▸」子菜单
        if (
            len(entries) == 1
            and entries[0].content_unit is not None
            and self._tag_service is not None
        ):
            self._insert_recent_tag_submenu(menu, entries[0].content_unit.id)

        chosen = menu.exec(active_view.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        for label, handler, _ in actions:
            if chosen.text() == label:
                handler()
                break

    def _show_empty_area_context_menu(self, active_view, pos: QPoint) -> None:
        """空白区域右键菜单（Stage 5 Task 3a + Task 3b + UX 重构 Phase 2 Task 5）。

        显示"新建文件夹"、"粘贴"（基于当前显示的目录）、"钉住此文件夹"/"取消钉住"。
        需注入 FileOperationService + ClipboardService。
        UX 重构 Phase 2 Task 5（Q2=C）：
        - 当前目录未钉住时显示「钉住此文件夹」
        - 有钉住文件夹时显示「取消钉住」
        """
        if self._file_operation_service is None:
            return
        # 获取当前显示的目录路径
        current_dir = self._current_displayed_dir()
        if current_dir is None:
            return
        menu = QMenu(self)
        new_folder_action = menu.addAction(ui.MENU_NEW_FOLDER)
        # 粘贴项（Stage 5 Task 3b，仅注入 ClipboardService 且剪贴板非空时显示）
        paste_action = None
        if self._clipboard_service is not None:
            paste_action = menu.addAction(ui.MENU_PASTE)
            paste_action.setEnabled(self._clipboard_service.get() is not None)

        # UX 重构 Phase 2 Task 5（Q2=C）：钉住/取消钉住
        pin_action = None
        unpin_action = None
        if self._assembly_panel is not None:
            if self._assembly_panel.is_pinned():
                unpin_action = menu.addAction(ui.MENU_UNPIN_FOLDER)
            else:
                # 当前目录未钉住 → 显示「钉住此文件夹」
                pin_action = menu.addAction(ui.MENU_PIN_FOLDER)

        chosen = menu.exec(active_view.viewport().mapToGlobal(pos))
        if chosen is new_folder_action:
            self._on_new_folder_in_dir(current_dir)
        elif paste_action is not None and chosen is paste_action:
            from pathlib import Path  # noqa: PLC0415

            self._perform_paste(Path(current_dir))
        elif pin_action is not None and chosen is pin_action:
            from pathlib import Path  # noqa: PLC0415

            self._pin_folder_from_context(Path(current_dir))
        elif unpin_action is not None and chosen is unpin_action:
            self._unpin_from_context()

    def _build_content_menu_actions(
        self, entries: list[FileEntry]
    ) -> list[tuple[str, Callable[[], None], bool]]:
        """构造文件列表右键菜单 actions（Stage 5 Task 1 抽取便于测试）。

        返回 (label, handler, enabled) 三元组列表。
        enabled=False 时菜单项灰显。

        UX 重构 Phase 2 Task 5（Q1=B）：已标记内容单元也显示「打开」项，
        内容单元标记不改变文件基本操作语义。
        """
        # actions 元素：(label, handler, enabled)
        actions: list[tuple[str, Callable[[], None], bool]] = []

        # UX 重构 Phase 2 Task 5（Q1=B）：「打开」项（单选时显示，行为与双击一致）
        # 所有类型（普通文件/文件夹/已标记内容单元）都显示
        if len(entries) == 1:
            entry = entries[0]
            actions.append((ui.MENU_OPEN, lambda: self._on_entry_activated_for_entry(entry), True))

        # 创建 Mod 组：单选或多选 + 全部为文件（非目录）+ 注入了 ContentUnitCreationService
        # UX 重构 Phase 1 Task 1 Commit 3：支持多选（E1：仅全文件时显示）
        if (
            self._content_unit_creation_service is not None
            and len(entries) >= 1
            and all(not e.is_dir for e in entries)
        ):
            actions.append(
                (ui.MENU_CREATE_MOD_GROUP, lambda: self._on_create_mod_group(entries), True)
            )

        # 「加入装配」菜单项已移除（UX 重构 Phase 1 Task 2 B2-2 决策）：
        # Task 4 将由「添加到钉住文件夹」+ 拖拽替代。

        # 标记/取消标记
        if len(entries) == 1:
            entry = entries[0]
            if entry.content_unit is None:
                actions.append(
                    (ui.MENU_MARK_CONTENT_UNIT, lambda: self._on_mark_content_unit(entry), True)
                )
            else:
                actions.append(
                    (
                        ui.MENU_UNMARK_CONTENT_UNIT,
                        lambda: self._on_unmark_content_unit(entry),
                        True,
                    )
                )
        else:
            # 多选：根据选中项状态动态显示批量操作
            # - 全部未标记：仅显示"批量标记"
            # - 全部已标记：仅显示"批量取消"
            # - 混合状态：同时显示两个（handler 内部各自跳过不适用项）
            has_any_marked = any(e.content_unit is not None for e in entries)
            has_any_unmarked = any(e.content_unit is None for e in entries)
            if has_any_unmarked:
                actions.append(
                    (
                        ui.MENU_BATCH_MARK_CONTENT_UNIT,
                        lambda: self._on_batch_mark_content_unit(entries),
                        True,
                    )
                )
            if has_any_marked:
                actions.append(
                    (
                        ui.MENU_BATCH_UNMARK_CONTENT_UNIT,
                        lambda: self._on_batch_unmark_content_unit(entries),
                        True,
                    )
                )

        # 批量打标签（Stage 4 Task 2）：多选且至少一个内容单元 + 注入了 TagService
        if self._tag_service is not None and len(entries) > 1:
            has_any_unit = any(e.content_unit is not None for e in entries)
            if has_any_unit:
                actions.append((ui.MENU_BATCH_TAG, lambda: self._on_batch_tag(entries), True))

        # 快速设置封面（Stage 5 Task 1）：单选已标记文件夹内容单元
        if len(entries) == 1 and entries[0].content_unit is not None:
            entry = entries[0]
            # 仅文件夹内容单元可用；压缩包内容单元灰显
            enabled = entry.is_dir
            actions.append(
                (
                    ui.MENU_QUICK_SET_COVER,
                    lambda: self._on_quick_set_cover(entry.content_unit.id),
                    enabled,
                )
            )

        # 添加到钉住文件夹（UX 重构 Phase 1 Task 4）：
        # A1：仅装配面板钉住时显示；B1：支持多选；B6：放在「移动到...」之前。
        if (
            self._assembly_service is not None
            and self._assembly_panel is not None
            and self._assembly_panel.is_pinned()
            and self._assembly_panel.current_folder_path() is not None
        ):
            actions.append(
                (ui.MENU_ADD_TO_PINNED, lambda: self._on_add_to_pinned_folder(entries), True)
            )

        # UX 重构 Phase 2 Task 5（Q2=C）：钉住/取消钉住右键菜单
        if self._assembly_panel is not None:
            # 单选文件夹 → 显示「钉住此文件夹」（若该文件夹未钉住）
            if len(entries) == 1 and entries[0].is_dir:
                folder_path = Path(entries[0].path)
                pinned_path = self._assembly_panel.current_folder_path()
                is_this_pinned = (
                    pinned_path is not None
                    and make_path_key(pinned_path) == make_path_key(folder_path)
                    and self._assembly_panel.is_pinned()
                )
                if not is_this_pinned:
                    actions.append(
                        (
                            ui.MENU_PIN_FOLDER,
                            lambda: self._pin_folder_from_context(folder_path),
                            True,
                        )
                    )
            # 有钉住文件夹时，任意选中都显示「取消钉住」
            if self._assembly_panel.is_pinned():
                actions.append((ui.MENU_UNPIN_FOLDER, self._unpin_from_context, True))

        # Stage 5 Task 3a：新建文件夹 / 重命名 / 删除（仅需 FileOperationService）
        # Stage 5 Task 3b：复制 / 剪切（需 FileOperationService + ClipboardService）
        # Stage 5 Task 5：移动到...（仅需 FileOperationService）
        if self._file_operation_service is not None:
            # 新建文件夹：单选时基于该条目所在目录；列表空白区域另处理
            # 这里仅在选中条目时显示（空白区域由 _on_content_context_menu 处理）
            if len(entries) == 1:
                entry = entries[0]
                # 新建文件夹：基于选中条目的父目录创建子文件夹
                actions.append(
                    (ui.MENU_NEW_FOLDER, lambda: self._on_new_folder_for_entry(entry), True)
                )
                # 重命名：单选
                actions.append((ui.MENU_RENAME, lambda: self._on_rename_entry(entry), True))
            # 复制 / 剪切：需 ClipboardService
            if self._clipboard_service is not None:
                actions.append((ui.MENU_COPY, lambda: self._on_shortcut_copy(), True))
                actions.append((ui.MENU_CUT, lambda: self._on_shortcut_cut(), True))
                # 粘贴：粘贴到当前中栏目录（不是右键的文件夹内部）
                # 剪贴板空时灰显
                has_clipboard = self._clipboard_service.get() is not None
                actions.append((ui.MENU_PASTE, lambda: self._on_shortcut_paste(), has_clipboard))
            # Stage 5 Task 5：移动到...（Q4=A 中栏 + 目录树均添加）
            actions.append((ui.MENU_MOVE_TO, lambda: self._on_move_to(entries), True))
            # 删除：单选或批量
            actions.append((ui.MENU_DELETE, lambda: self._on_delete_entries(entries), True))

        # 在资源管理器中打开（Stage 5 Task 1，始终显示，单选时可用）
        if len(entries) == 1:
            actions.append(
                (
                    ui.MENU_OPEN_IN_EXPLORER,
                    lambda: self._on_open_in_explorer(entries[0].path),
                    True,
                )
            )

        # 复制路径（始终）
        actions.append(
            (ui.CONTEXT_MENU_COPY_PATH, lambda: self._copy_path_to_clipboard(entries[0].path), True)
        )

        return actions

    def _copy_path_to_clipboard(self, path: str) -> None:
        """复制路径到剪贴板。"""
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(path)
        self.statusBar().showMessage(ui.CONTEXT_MENU_COPY_PATH_OK, 3000)

    def _on_quick_set_cover(self, unit_id: str) -> None:
        """快速设置封面（Stage 5 Task 1）。

        调用 ContentService.quick_set_cover 取目录内第一张图设为封面。
        根据返回值在状态栏反馈结果，无图片或已有封面均不报错。
        """
        if self._content_service is None:
            return
        try:
            ok = self._content_service.quick_set_cover(unit_id)
        except Exception as e:  # noqa: BLE001
            self._handle_service_error(e, "快速设置封面失败")
            return

        if ok:
            self._commit()
            self.statusBar().showMessage(ui.MENU_QUICK_SET_COVER_OK, 3000)
        else:
            # quick_set_cover 返回 False 的语义：无图片或已有封面
            # 需要区分两种情况给用户更精准的反馈
            unit = self._content_service.get_by_id(unit_id)
            if unit is None:
                return
            if unit.cover_path:
                # 已有封面，未覆盖
                self.statusBar().showMessage(ui.MENU_QUICK_SET_COVER_ALREADY_SET, 3000)
            else:
                # 无图片
                self.statusBar().showMessage(ui.MENU_QUICK_SET_COVER_NO_IMAGE, 3000)

    def _on_create_mod_group(self, entries: list[FileEntry]) -> None:
        """创建 Mod 组：弹出对话框选择/编辑名称，调用 ContentUnitCreationService。

        UX 重构 Phase 1 Task 1 Commit 3：支持多选。
        - E1：仅全部为文件（非目录）时显示菜单项（由 _build_content_menu_actions 保证）
        - F1：按文件列表显示顺序的第一项提取 Mod 名
        - D1 调整：原 D1 逐个调用因文件夹已存在冲突不可行，改用批量接口
          create_content_unit_from_files（一次建文件夹 + 逐个移入 + 容错汇总）
        """
        if self._content_unit_creation_service is None or not entries:
            return

        # F1：按显示顺序第一项提取名（entries 由调用方按显示顺序传入）
        first_entry = entries[0]
        # 选中文件所在父目录作为 staging_path
        staging_path = Path(first_entry.path).parent

        # 提取两种命名选项
        from application.content_unit_creation_service import extract_mod_name

        pure_name = extract_mod_name(first_entry.name)
        # 完整原名：去扩展名
        full_name = Path(first_entry.name).stem

        # 弹出对话框
        chosen_name = self._show_create_mod_group_dialog(pure_name, full_name)
        if chosen_name is None:
            return  # 用户取消

        source_files = [Path(e.path) for e in entries]
        try:
            result = self._content_unit_creation_service.create_content_unit_from_files(
                source_files,
                staging_path,
                name=chosen_name,
            )
            # D3：ContentUnitCreationService 已注入 UoW，事务由 Service 内部管理，无需 _commit
            # 刷新目录树（新文件夹已写入 folder_cache）
            self._refresh_tree()
            # 刷新当前目录文件列表
            self._refresh_content_list(str(staging_path))
            # 绑定装配面板到新创建的 Mod 组
            # UX 重构 Phase 1 Task 3（B1）：钉住状态下不自动绑定新 Mod 组
            if not self._is_assembly_pinned():
                self._bind_assembly_panel(result.unit)
            # 状态栏汇总
            if result.failure_count == 0:
                if result.success_count == 1:
                    self.statusBar().showMessage(
                        ui.CREATE_MOD_GROUP_DEFAULT_OK.format(name=chosen_name), 3000
                    )
                else:
                    self.statusBar().showMessage(
                        ui.CREATE_MOD_GROUP_MULTI_OK.format(
                            name=chosen_name, count=result.success_count
                        ),
                        5000,
                    )
            else:
                self.statusBar().showMessage(
                    ui.CREATE_MOD_GROUP_MULTI_PARTIAL.format(
                        ok=result.success_count, fail=result.failure_count
                    ),
                    5000,
                )
        except Exception as e:  # noqa: BLE001
            self._handle_service_error(e, ui.CREATE_MOD_GROUP_FAILED, rollback=False)

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
            # D3：ContentService 已注入 UoW，事务由 Service 内部管理，无需 _commit
            self._refresh_content_list_for_current_mode()
            self.statusBar().showMessage(ui.MARK_CONTENT_UNIT_OK, 3000)
        except Exception as e:  # noqa: BLE001
            self._handle_service_error(e, ui.MARK_CONTENT_UNIT_FAILED, rollback=False)

    def _on_unmark_content_unit(self, entry: FileEntry) -> None:
        """取消单个条目的内容单元标记。"""
        if entry.content_unit is None:
            return
        try:
            self._content_service.unmark_content_unit(entry.content_unit.id)
            # unmark_content_unit 是单步写方法，未使用 UoW（仅 mark_as_content_unit
            # 的多步写在 UoW 事务内）。调用方需显式提交。
            self._commit()
            self._refresh_content_list_for_current_mode()
            self.statusBar().showMessage(ui.UNMARK_CONTENT_UNIT_OK, 3000)
        except Exception as e:  # noqa: BLE001
            self._handle_service_error(e, ui.UNMARK_CONTENT_UNIT_FAILED, rollback=True)

    def _on_batch_mark_content_unit(self, entries: list[FileEntry]) -> None:
        """批量标记多个条目为内容单元（各自独立，已标记项跳过）。

        容错策略：循环内单条失败仅计数不中断。ContentService 已注入 UoW，
        每条 mark_as_content_unit 成功时内部已 commit，失败时内部已 rollback。
        """
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
            # D3：ContentService 已注入 UoW，事务由 Service 内部管理，无需 _commit
            self._refresh_content_list_for_current_mode()
            self.statusBar().showMessage(
                ui.BATCH_MARK_CONTENT_UNIT_OK.format(count=success_count), 3000
            )
        if failure_count > 0:
            QMessageBox.information(
                self,
                ui.BATCH_MARK_CONTENT_UNIT_FAILED,
                f"{failure_count} 个文件标记失败，请查看日志。",
            )

    def _on_batch_unmark_content_unit(self, entries: list[FileEntry]) -> None:
        """批量取消多个条目的内容单元标记（各自独立，未标记项跳过）。

        容错策略与批量标记一致：循环内单条失败仅计数不中断。
        unmark_content_unit 是单步写方法，未使用 UoW，每条独立 commit。
        """
        success_count = 0
        failure_count = 0
        for entry in entries:
            if entry.content_unit is None:
                continue  # 未标记，跳过
            try:
                self._content_service.unmark_content_unit(entry.content_unit.id)
                # unmark_content_unit 未使用 UoW，调用方需显式提交
                self._commit()
                success_count += 1
            except Exception:  # noqa: BLE001
                logger.exception("批量取消标记失败：path=%s", entry.path)
                failure_count += 1
                # 单条失败时回滚该条事务（避免未提交残留）
                self._rollback()
        if success_count > 0:
            self._refresh_content_list_for_current_mode()
            self.statusBar().showMessage(
                ui.BATCH_UNMARK_CONTENT_UNIT_OK.format(count=success_count), 3000
            )
        if failure_count > 0:
            QMessageBox.information(
                self,
                ui.BATCH_UNMARK_CONTENT_UNIT_FAILED,
                f"{failure_count} 个内容单元取消标记失败，请查看日志。",
            )

    def _refresh_content_list_for_current_mode(self) -> None:
        """刷新中栏文件列表（基于当前目录树选中节点）。

        UX 重构 Phase 1 Task 1：移除模式分支，统一为原 browse 行为。
        方法名保留 _for_current_mode 仅为最小改动，Task 7 重命名。
        """
        sm = self._tree_view.selectionModel()
        if sm is None:
            return
        indexes = sm.selectedIndexes()
        if not indexes:
            return
        node = self._tree_model.node_at(indexes[0])
        if node is not None:
            self._refresh_content_list(node.real_path)

    def _current_displayed_dir(self) -> str | None:
        """获取当前中栏显示的目录路径（Stage 5 Task 3a）。

        UX 重构 Phase 1 Task 1：移除模式分支，取目录树当前选中节点的 real_path。
        """
        sm = self._tree_view.selectionModel()
        if sm is None:
            return None
        indexes = sm.selectedIndexes()
        if not indexes:
            return None
        node = self._tree_model.node_at(indexes[0])
        if node is None:
            return None
        return node.real_path

    def _refresh_content_list_after_file_op(self, dir_path: str | None) -> None:
        """文件操作后刷新中栏（Stage 5 Task 3a）。

        _refresh_tree 会 reset tree 模型，selectionModel 可能暂时无选中节点，
        此时 _refresh_content_list_for_current_mode 不会刷新列表。
        本方法直接用传入的 dir_path 刷新，避免依赖 selection 状态。
        """
        if dir_path is None:
            return
        self._refresh_content_list(dir_path)

    # === Stage 5 Task 3a：文件操作 handler ===

    def _on_new_folder_for_entry(self, entry: FileEntry) -> None:
        """右键条目 → 新建文件夹（基于该条目所在父目录）。"""
        # 父目录：文件所在目录或文件夹本身的父目录
        target_dir = str(Path(entry.path).parent)
        self._on_new_folder_in_dir(target_dir)

    def _on_new_folder_in_dir(self, dir_path: str) -> None:
        """在指定目录下新建文件夹。"""
        if self._file_operation_service is None:
            return
        # 弹出输入对话框，默认填"新建文件夹"
        name, ok = QInputDialog.getText(
            self,
            ui.MENU_NEW_FOLDER_DIALOG_TITLE,
            ui.MENU_NEW_FOLDER_DIALOG_LABEL,
            text=ui.MENU_NEW_FOLDER_DEFAULT_NAME,
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        try:
            new_path = Path(dir_path) / name
            self._file_operation_service.new_folder(new_path)
            self._commit()
            self._refresh_tree()
            # _refresh_tree 会清空列表，必须用保存的 dir_path 直接刷新
            # （_refresh_content_list_for_current_mode 依赖 selection 可能失效）
            self._refresh_content_list_after_file_op(dir_path)
            # 修复1：若新建文件夹发生在钉住的装配面板文件夹内，同步刷新装配面板
            self._refresh_assembly_if_affected(dir_path)
            self.statusBar().showMessage(ui.MENU_NEW_FOLDER_SUCCESS.format(name=name), 3000)
        except Exception as e:  # noqa: BLE001
            self._handle_service_error(e, ui.MENU_OPERATION_FAILED.format(error=str(e)))

    def _show_rename_dialog(self, old_name: str) -> tuple[str, bool]:
        """弹出重命名对话框，预填当前名称，选中文件名部分（不含扩展名）。

        UX 重构 Phase 1 Task 2 修复2：避免重命名时误改后缀，
        初始选区忽略扩展名（如 "readme.txt" 只选中 "readme"）。

        Returns:
            (new_name, ok)：new_name 为去空白后的名称；ok 为是否确认。
        """
        dialog = QDialog(self)
        dialog.setWindowTitle(ui.MENU_RENAME_DIALOG_TITLE)
        layout = QVBoxLayout(dialog)

        label = QLabel(ui.MENU_RENAME_DIALOG_LABEL)
        layout.addWidget(label)

        edit = QLineEdit(old_name)
        layout.addWidget(edit)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        # 选中文件名部分（不含扩展名）
        # .gitignore 等以点开头的文件 suffix 为整个名称，此时全选
        old_path = Path(old_name)
        suffix = old_path.suffix
        if suffix and len(suffix) < len(old_name):
            select_len = len(old_name) - len(suffix)
        else:
            select_len = len(old_name)
        if 0 < select_len < len(old_name):
            edit.setSelection(0, select_len)
        else:
            edit.selectAll()
        edit.setFocus()

        # UI合理性6（2026-08-02）：重命名弹窗适当调宽（约为默认宽度的 3/2）
        dialog.adjustSize()
        hint = dialog.sizeHint()
        dialog.resize(int(hint.width() * 1.5), hint.height())

        if dialog.exec() == QDialog.DialogCode.Accepted:
            return edit.text().strip(), True
        return "", False

    def _rename_entry_core(self, entry: FileEntry, refresh_middle: bool = True) -> bool:
        """重命名核心逻辑。

        UX 重构 Phase 1 Task 2 修复1：抽取核心逻辑，装配面板调用时
        refresh_middle=False，避免中栏被刷新到文件父目录（错误进入文件夹）。

        修复5（系统性修复）：_refresh_tree 会清空中栏列表（content_list_model.refresh([])），
        且 restore_expanded_paths 可能在 _refresh_tree 内部已恢复目录树选中节点。
        若选中节点已被恢复，再调用 setCurrentIndex 设置相同节点不会触发
        selectionChanged 信号，导致 _on_tree_selection_changed 不执行，
        中栏内容保持空白。

        解决方案：_refresh_tree 后统一通过 _restore_middle_after_tree_refresh
        恢复目录树选中 + 直接刷新中栏内容（不依赖 selectionChanged 信号）。

        Args:
            entry: 待重命名的条目。
            refresh_middle: True 刷新中栏到文件父目录；False 保持中栏原显示目录。

        Returns:
            True 表示执行了重命名；False 表示用户取消或无变化。
        """
        if self._file_operation_service is None:
            return False
        old_path = Path(entry.path)
        old_name = old_path.name
        # 保存父目录路径：rename 后 _refresh_tree 会清空列表，需用此路径直接刷新
        dir_path = str(old_path.parent)
        # 修复5：refresh_middle=False 时记录原显示目录，_refresh_tree 后恢复
        # （_refresh_tree 会清空中栏，不恢复会导致中栏空白）
        preserved_display_dir = self._current_displayed_dir() if not refresh_middle else None
        name, ok = self._show_rename_dialog(old_name)
        if not ok or not name:
            return False
        # 同名跳过（无变化）
        if name == old_name:
            return False
        try:
            self._file_operation_service.rename(old_path, name)
            self._commit()
            self._refresh_tree()
            # 修复5：统一恢复中栏显示（不依赖 selectionChanged 信号）
            if refresh_middle:
                self._restore_middle_after_tree_refresh(dir_path)
            elif preserved_display_dir is not None:
                self._restore_middle_after_tree_refresh(preserved_display_dir)
            self.statusBar().showMessage(ui.MENU_RENAME_SUCCESS.format(name=name), 3000)
            return True
        except Exception as e:  # noqa: BLE001
            self._handle_service_error(e, ui.MENU_OPERATION_FAILED.format(error=str(e)))
            return False

    def _restore_middle_after_tree_refresh(self, dir_path: str) -> None:
        """_refresh_tree 后恢复中栏显示：恢复目录树选中 + 直接刷新中栏内容。

        _refresh_tree 会：
        1. reset tree model（beginResetModel/endResetModel）
        2. restore_expanded_paths 尝试恢复选中（仅在父节点已展开时成功）
        3. 清空 content_list_model

        问题：若步骤 2 已恢复选中节点，再 setCurrentIndex 相同节点不会触发
        selectionChanged 信号，_on_tree_selection_changed 不执行，中栏空白。
        若步骤 2 未恢复选中（父节点未展开），setCurrentIndex 新节点会触发信号，
        但信号处理内的 _refresh_content_list 依赖 selectionModel，时序不可控。

        解决方案：始终通过 find_index_by_path 恢复目录树选中（处理父节点未展开情况），
        然后直接调用 _refresh_content_list 刷新中栏（不依赖 selectionChanged 信号）。

        Args:
            dir_path: 需要在中栏显示的目录路径。
        """
        # 恢复目录树选中节点（find_index_by_path 会 fetchMore 加载未展开的子节点）
        target_idx = self._tree_model.find_index_by_path(self._tree_view, dir_path)
        if target_idx.isValid():
            self._tree_view.setCurrentIndex(target_idx)
        # 直接刷新中栏内容（_refresh_tree 已清空列表，
        # 不能依赖 setCurrentIndex 触发 selectionChanged，因为选中可能未变）
        self._refresh_content_list(dir_path)
        # 修复1：若受影响目录与装配面板钉住文件夹相同，同步刷新装配面板
        self._refresh_assembly_if_affected(dir_path)

    def _refresh_assembly_if_affected(self, *affected_dirs: str | Path) -> None:
        """文件操作后，若受影响目录与装配面板当前透视文件夹相同则刷新装配面板。

        修复1（含用户补充）：双击进入被钉住的文件夹内进行任何操作（重命名、删除、
        新建文件夹、粘贴、移动等）都应当同步刷新被钉住的装配面板。
        UX 重构 Task 7 Step 3：委托 AssemblyController。
        """
        self._assembly_controller.refresh_if_affected(*affected_dirs)

    def _on_rename_entry(self, entry: FileEntry) -> None:
        """右键条目 → 重命名（中栏，刷新中栏到父目录）。"""
        self._rename_entry_core(entry, refresh_middle=True)

    def _on_delete_entries(self, entries: list[FileEntry]) -> None:
        """右键条目 → 删除（移至回收站）。"""
        if self._file_operation_service is None:
            return
        # 确认对话框
        n = len(entries)
        if n == 1:
            text = ui.MENU_DELETE_CONFIRM_TEXT_SINGLE
        else:
            text = ui.MENU_DELETE_CONFIRM_TEXT_MULTI.format(n=n)
        # 操作合理性3（2026-08-02）：删除确认时提示文件夹内部条目数（顶层，快速）
        dir_file_count = 0
        for e in entries:
            if e.is_dir:
                with contextlib.suppress(OSError):
                    dir_file_count += sum(1 for _ in Path(e.path).iterdir())
        if dir_file_count > 0:
            text = text.replace(
                "此操作不可撤销。",
                ui.MENU_DELETE_CONFIRM_FOLDER_FILES.format(n=dir_file_count),
            )
        reply = QMessageBox.question(
            self,
            ui.MENU_DELETE_CONFIRM_TITLE,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        # 批量删除
        paths = [Path(e.path) for e in entries]
        # 保存删除条目所在父目录路径（取第一个条目的父目录）：
        # _refresh_tree 后 selection 可能失效，用此路径直接刷新列表
        dir_path = str(paths[0].parent) if paths else None
        try:
            # delete_to_recycle_bin 返回 (histories, sync_errors)：
            # - SHFileOperation 失败时抛 FileOperationError（文件未删除，可 rollback）
            # - 同步失败时返回 sync_errors（文件已删除，需 commit 保留历史）
            histories, sync_errors = self._file_operation_service.delete_to_recycle_bin(paths)
            self._commit()
            self._refresh_tree()
            self._refresh_content_list_after_file_op(dir_path)
            # 修复1：若删除发生在钉住的装配面板文件夹内，同步刷新装配面板
            if dir_path is not None:
                self._refresh_assembly_if_affected(dir_path)
            ok_count = len(histories)
            fail_count = n - ok_count
            if sync_errors:
                # 同步有错误但文件已删除：弹窗提示部分成功 + 错误明细
                QMessageBox.information(
                    self,
                    ui.MENU_DELETE_CONFIRM_TITLE,
                    ui.MENU_DELETE_PARTIAL.format(ok=ok_count, fail=fail_count),
                )
            elif fail_count == 0:
                self.statusBar().showMessage(ui.MENU_DELETE_SUCCESS.format(n=ok_count), 3000)
            else:
                QMessageBox.information(
                    self,
                    ui.MENU_DELETE_CONFIRM_TITLE,
                    ui.MENU_DELETE_PARTIAL.format(ok=ok_count, fail=fail_count),
                )
        except Exception as e:  # noqa: BLE001
            self._handle_service_error(e, ui.MENU_OPERATION_FAILED.format(error=str(e)))

    # --- 装配面板（阶段 3 Task 4） ---

    def _bind_assembly_panel(self, unit: ContentUnit | None) -> None:
        """绑定/解绑装配面板（UX 重构 Task 7 Step 3：委托 AssemblyController）。"""
        self._assembly_controller.bind_to_unit(unit)

    def _bind_assembly_folder(self, folder_path: Path | None) -> None:
        """装配面板透视任意文件夹路径（UX 重构 Task 7 Step 3：委托 AssemblyController）。"""
        self._assembly_controller.bind_to_folder(folder_path)

    def _is_assembly_pinned(self) -> bool:
        """返回装配面板当前是否处于钉住状态（委托 AssemblyController）。"""
        return self._assembly_controller.is_pinned()

    def _follow_middle_selection_after_unpin(self) -> None:
        """取消钉住后立即跟随中栏当前选中（B4 决策，委托 AssemblyController）。"""
        self._assembly_controller.follow_selection(self._current_middle_selection_entry())

    def _current_middle_selection_entry(self) -> FileEntry | None:
        """返回中栏当前活动视图的单选条目（无选中/多选返回 None）。"""
        active_view = (
            self._card_view if self._current_view_index == VIEW_INDEX_CARD else self._content_view
        )
        active_model = (
            self._card_list_model
            if self._current_view_index == VIEW_INDEX_CARD
            else self._content_list_model
        )
        sm = active_view.selectionModel() if active_view is not None else None
        if sm is None:
            return None
        indexes = sm.selectedRows()
        if not indexes or len(indexes) > 1:
            return None
        return active_model.entry_at(indexes[0].row())

    def _on_assembly_pin_changed(self, pinned: bool) -> None:
        """装配面板钉住状态变化回调（UX 重构 Phase 1 Task 3）。

        Args:
            pinned: True 表示已钉住，False 表示已取消钉住。

        - 已钉住：无需额外动作（装配面板内部已短路 bind_* 调用）
        - 已取消钉住：立即跟随中栏当前选中（B4 决策）
        """
        if not pinned:
            self._follow_middle_selection_after_unpin()

    def _pin_folder_from_context(self, folder_path: Path) -> None:
        """右键菜单「钉住此文件夹」（Q2=C，委托 AssemblyController）。"""
        self._assembly_controller.pin_folder(folder_path)
        name = folder_path.name
        self.statusBar().showMessage(ui.ASSEMBLY_PIN_STATUS_PINNED.format(name=name), 3000)

    def _unpin_from_context(self) -> None:
        """右键菜单「取消钉住」（UX 重构 Phase 2 Task 5，Q2=C）。

        中栏/目录树右键取消钉住：调用 AssemblyPanel.unpin + 触发跟随中栏逻辑。
        """
        if not self._assembly_controller.is_pinned():
            return
        self._assembly_controller.unpin()
        self._follow_middle_selection_after_unpin()
        self.statusBar().showMessage(ui.ASSEMBLY_PIN_STATUS_UNPINNED_FOLLOW, 3000)

    def _on_add_to_pinned_folder(self, entries: list[FileEntry]) -> None:
        """添加选中文件到钉住的文件夹（UX 重构 Phase 1 Task 4）。

        - A2：移动后立即刷新中栏。
        - B1：支持多选。
        - 修复3：冲突走 ConflictResolutionDialog 询问（重命名/跳过/覆盖）。
        - 修复4：嵌套检查（SelfSubdirectoryError）由 FileOperationService.move 保证。
        - C2：状态栏提示。
        - C3：保留历史记录（FileOperationService.move 自动写 operation_history）。
        """
        if self._assembly_service is None or self._assembly_panel is None:
            return
        folder_path = self._assembly_panel.current_folder_path()
        if folder_path is None:
            return
        src_paths = [Path(e.path) for e in entries]
        self._perform_move_to(
            src_paths,
            folder_path,
            refresh_assembly=True,
            ok_msg=ui.ADD_TO_PINNED_OK,
            fail_title=ui.ADD_TO_PINNED_FAILED,
            partial_msg=ui.ADD_TO_PINNED_PARTIAL,
        )

    def _on_drop_to_folder(self, target_folder: Path, src_paths: list[Path]) -> None:
        """中栏内部拖拽文件到同目录文件夹（UX 重构 Phase 1 Task 4）。

        - A5：拖拽无需确认。
        - B4：文件夹可拖拽（move 支持文件和文件夹）。
        - 修复1：target_folder 命中装配面板钉住文件夹时同步刷新装配面板
          （由 _perform_move_to 内部判断）。
        - 修复3：冲突走 ConflictResolutionDialog 询问。
        - 修复4：嵌套检查由 FileOperationService.move 保证。
        """
        self._perform_move_to(
            src_paths,
            target_folder,
            refresh_assembly=False,
            ok_msg=ui.DROP_TO_FOLDER_OK,
            fail_title=ui.DROP_TO_FOLDER_FAILED,
            partial_msg=ui.DROP_TO_FOLDER_PARTIAL,
        )

    def _on_drop_to_assembly(self, file_paths: list[Path]) -> None:
        """拖拽文件/文件夹到装配面板（UX 重构 Phase 1 Task 4）。

        - A3：拖拽无需确认。
        - 修复2：同时接受文件和文件夹（与右键添加行为一致）。
        - 修复3：冲突走 ConflictResolutionDialog 询问。
        - 修复4：嵌套检查由 FileOperationService.move 保证。
        """
        if self._assembly_panel is None:
            return
        folder_path = self._assembly_panel.current_folder_path()
        if folder_path is None:
            return
        self._perform_move_to(
            file_paths,
            folder_path,
            refresh_assembly=True,
            ok_msg=ui.ADD_TO_PINNED_OK,
            fail_title=ui.ADD_TO_PINNED_FAILED,
            partial_msg=ui.ADD_TO_PINNED_PARTIAL,
        )

    def _on_assembly_rename_cover(self, image_path: Path) -> None:
        """装配面板右键重命名预览图：rename_as_cover_by_path + 刷新 + 提交。

        UX 重构 Phase 1 Task 2 Commit 2：改用 rename_as_cover_by_path，
        支持非内容单元文件夹（按文件夹名重命名图片）。
        """
        if self._assembly_service is None or self._assembly_panel is None:
            return
        folder_path = self._assembly_panel.current_folder_path()
        if folder_path is None:
            return
        try:
            new_path = self._assembly_service.rename_as_cover_by_path(folder_path, image_path)
            self._commit()
            self._assembly_panel.refresh_current()
            self.statusBar().showMessage(
                ui.ASSEMBLY_RENAME_COVER_OK.format(name=new_path.name), 3000
            )
        except Exception as e:  # noqa: BLE001
            self._handle_service_error(e, ui.ASSEMBLY_RENAME_COVER_FAILED)

    def _on_assembly_file_op(self, action: str, entries: list[FileEntry]) -> None:
        """装配面板文件操作委托（UX 重构 Phase 1 Task 2 Commit 2）。

        复用中栏现有文件操作逻辑，操作后刷新装配面板。
        空白处移动整个文件夹后解绑装配面板（A3-1）。

        Args:
            action: 操作类型 rename/copy/cut/paste/move_to/delete/copy_path。
            entries: 选中的 FileEntry 列表。
        """
        if self._assembly_panel is None:
            return
        if action == "rename" and len(entries) == 1:
            # 修复1：装配面板重命名不刷新中栏（避免中栏错误进入文件夹）
            if self._rename_entry_core(entries[0], refresh_middle=False):
                self._assembly_panel.refresh_current()
        elif action == "copy":
            if self._clipboard_service is not None:
                paths = [e.path for e in entries]
                self._clipboard_service.set_copy(paths)
                self._content_list_model.set_cut_paths(set())
                self.statusBar().showMessage(ui.SHORTCUT_COPIED.format(n=len(paths)), 3000)
        elif action == "cut":
            if self._clipboard_service is not None:
                paths = [e.path for e in entries]
                self._clipboard_service.set_cut(paths)
                self._content_list_model.set_cut_paths(set(paths))
                self.statusBar().showMessage(ui.SHORTCUT_CUT.format(n=len(paths)), 3000)
        elif action == "paste":
            folder_path = self._assembly_panel.current_folder_path()
            if folder_path is not None:
                self._perform_paste(folder_path)
                self._assembly_panel.refresh_current()
        elif action == "move_to":
            self._on_move_to(entries)
            # A3-1：移动整个透视文件夹后解绑（文件夹路径已变）
            # UX 重构 Phase 1 Task 3（A4）：钉住状态下移动自身 → 强制解除钉住并清空
            folder_path = self._assembly_panel.current_folder_path()
            if folder_path is not None and any(Path(e.path) == folder_path for e in entries):
                if not folder_path.exists():
                    if self._assembly_panel.is_pinned():
                        self._assembly_panel.force_unpin_and_clear()
                    else:
                        self._bind_assembly_panel(None)
            else:
                self._assembly_panel.refresh_current()
        elif action == "delete":
            self._on_delete_entries(entries)
            self._assembly_panel.refresh_current()
        elif action == "copy_path" and len(entries) == 1:
            self._copy_path_to_clipboard(entries[0].path)

    def _on_tag_manager_clicked(self) -> None:
        """打开标签管理对话框（阶段 4 Task 1）。

        - 仅当注入了 tag_service 时响应（按钮可见性已通过 __init__ 控制，
          此处为防御性二次校验）。
        - Dialog 持有 TransactionScope 的 commit / rollback 引用，每次增删改操作
          后立即提交（事务边界由 Dialog 内部控制）。
        - Dialog 关闭后无需刷新目录树（标签不影响文件系统）。
        """
        if self._tag_service is None:
            return
        dialog = TagManagerDialog(
            self._tag_service,
            commit_callback=self._transaction_scope.commit,
            rollback_callback=self._transaction_scope.rollback,
            parent=self,
        )
        dialog.exec()
        # Stage 4 Task 3：标签库可能变更，刷新 TagFilterBar 可选标签。
        # refresh_categories 会自动剔除已删除的已选标签并重新筛选。
        self._refresh_tag_filter_bar()
        # BugFix2 验收反馈：标签库可能变更，刷新元数据面板当前单元的标签显示
        # （refresh_tags 不触碰表单字段，保留未保存的来源/备注编辑）
        if self._metadata_panel is not None:
            self._metadata_panel.refresh_tags()

    # === Stage 5 Task 6：操作历史与撤销 ===

    def _on_operation_history_clicked(self) -> None:
        """打开操作历史对话框。

        - 仅当注入了 undo_service 时响应（按钮可见性已通过 __init__ 控制）。
        - Dialog 内部完成 undo 流程（反向文件操作 + 同步 + 写 undo 记录 + mark_undone），
          但不自提交；由 MainWindow 在 dialog.exec() 返回后 commit。
        - Dialog 撤销成功后通过 callback 通知 MainWindow 刷新中栏/目录树。
        - 失败时（UndoSafetyError 等）Dialog 内部已弹窗提示，MainWindow 仅 rollback。
        """
        if self._undo_service is None:
            return

        had_undone = [False]  # 闭包变量，记录是否发生过撤销

        def _on_undone() -> None:
            had_undone[0] = True

        from app.operation_history_dialog import OperationHistoryDialog  # noqa: PLC0415

        dialog = OperationHistoryDialog(self._undo_service, parent=self, limit=100)
        # UX 重构 Phase 2 Task 5：注入 managed_root_service 用于路径简化显示
        dialog.set_managed_root_service(self._service)
        dialog.set_on_undone_callback(_on_undone)
        dialog.exec()

        if had_undone[0]:
            # 发生过撤销：commit + 刷新 UI
            self._commit()
            self._refresh_tree()
            self._refresh_content_list_for_current_mode()
            self.statusBar().showMessage("已撤销操作", 3000)

    def _on_refresh_current(self) -> None:
        """刷新当前目录（UX 重构 Phase 2 Task 5，Q5=B + Q6=A）。

        - 仅刷新中栏当前显示的目录 + 目录树对应节点，不触发全量扫描
        - 若受影响目录与装配面板钉住文件夹相同，同步刷新装配面板（Q6=A）
        - 外部修改文件后 F5 能看到变化

        实现说明：FolderTreeService 无单节点刷新接口，使用 _refresh_tree（从 DB 重载
        目录树，不触发扫描）+ _restore_middle_after_tree_refresh 恢复中栏。
        _restore_middle_after_tree_refresh 已含 _refresh_assembly_if_affected。
        """
        current_dir = self._current_displayed_dir()
        if current_dir is None:
            self.statusBar().showMessage(ui.REFRESH_NO_DIR, 2000)
            return
        # 刷新目录树（从 DB 重载，不触发扫描）+ 恢复中栏选中 + 同步装配面板
        self._refresh_tree()
        self._restore_middle_after_tree_refresh(current_dir)
        self.statusBar().showMessage(ui.REFRESH_DONE, 2000)

    # === Stage 5 Task 4：键盘快捷键 ===

    def _get_selected_entries(self) -> list[FileEntry]:
        """获取中栏当前活动视图中选中的条目（列表视图或卡片视图）。

        Stage 5 Task 4：供快捷键 handler 复用，避免重复实现选中逻辑。
        """
        active_view = (
            self._card_view if self._current_view_index == VIEW_INDEX_CARD else self._content_view
        )
        active_model = (
            self._card_list_model
            if self._current_view_index == VIEW_INDEX_CARD
            else self._content_list_model
        )
        sm = active_view.selectionModel()
        if sm is None:
            return []
        entries: list[FileEntry] = []
        for idx in sm.selectedRows():
            entry = active_model.entry_at(idx.row())
            if entry is not None:
                entries.append(entry)
        return entries

    def _setup_shortcuts(self) -> None:
        """注册键盘快捷键。

        Q5=A：context=WidgetShortcut，仅在该控件聚焦时生效。
        用户补充（Task 3b）：目录树支持全部快捷键（F2/Delete/Ctrl+C/X/V）。

        快捷键列表：
        - F2（中栏）：重命名选中条目（Q1=A：多选取第一个）
        - F2（目录树）：重命名选中目录树节点
        - Delete（中栏/目录树）：删除选中条目
        - Ctrl+Z：撤销最近可撤销操作（Q2=A 二次确认；Q3=B 跳过不可撤销/已撤销）
        - Ctrl+A（中栏）：全选
        - Ctrl+C/X/V（中栏/目录树）：复制/剪切/粘贴（Task 3b 接入真实逻辑）
        """
        # 中栏 Ctrl+A 始终注册
        self._shortcut_select_all = QShortcut(QKeySequence("Ctrl+A"), self._content_view)
        self._shortcut_select_all.setContext(Qt.ShortcutContext.WidgetShortcut)
        self._shortcut_select_all.activated.connect(self._on_shortcut_select_all)

        # Ctrl+Z：窗口级（任意位置聚焦均可触发，因为撤销是全局操作）
        # 仅在注入 UndoService 时注册
        if self._undo_service is not None:
            self._shortcut_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
            self._shortcut_undo.setContext(Qt.ShortcutContext.WindowShortcut)
            self._shortcut_undo.activated.connect(self._on_shortcut_undo)

        # F2 / Delete 依赖 FileOperationService
        if self._file_operation_service is not None:
            # 中栏 F2 重命名（Q1=A：多选取第一个）
            self._shortcut_rename = QShortcut(QKeySequence("F2"), self._content_view)
            self._shortcut_rename.setContext(Qt.ShortcutContext.WidgetShortcut)
            self._shortcut_rename.activated.connect(self._on_shortcut_rename_content)

            # 中栏 Delete 删除
            self._shortcut_delete = QShortcut(QKeySequence("Delete"), self._content_view)
            self._shortcut_delete.setContext(Qt.ShortcutContext.WidgetShortcut)
            self._shortcut_delete.activated.connect(self._on_shortcut_delete)

            # 目录树 F2 / Delete（用户补充：目录树也支持 F2/Delete）
            self._shortcut_rename_tree = QShortcut(QKeySequence("F2"), self._tree_view)
            self._shortcut_rename_tree.setContext(Qt.ShortcutContext.WidgetShortcut)
            self._shortcut_rename_tree.activated.connect(self._on_shortcut_rename_tree)

            self._shortcut_delete_tree = QShortcut(QKeySequence("Delete"), self._tree_view)
            self._shortcut_delete_tree.setContext(Qt.ShortcutContext.WidgetShortcut)
            self._shortcut_delete_tree.activated.connect(self._on_shortcut_delete_tree)

            # Stage 5 Task 5：Ctrl+M 移动到...（Q3=B 中栏 + 目录树 WidgetShortcut）
            self._shortcut_move_to = QShortcut(QKeySequence("Ctrl+M"), self._content_view)
            self._shortcut_move_to.setContext(Qt.ShortcutContext.WidgetShortcut)
            self._shortcut_move_to.activated.connect(self._on_shortcut_move_to)

            self._shortcut_move_to_tree = QShortcut(QKeySequence("Ctrl+M"), self._tree_view)
            self._shortcut_move_to_tree.setContext(Qt.ShortcutContext.WidgetShortcut)
            self._shortcut_move_to_tree.activated.connect(self._on_shortcut_move_to_tree)

            # 操作便捷性3：Ctrl+Q 移动到最近目标（窗口级，任意位置可触发）。
            # 默认快捷键暂定 Ctrl+Q，后续做自定义快捷键菜单时再开放配置。
            self._shortcut_move_to_latest = QShortcut(QKeySequence("Ctrl+Q"), self)
            self._shortcut_move_to_latest.setContext(Qt.ShortcutContext.WindowShortcut)
            self._shortcut_move_to_latest.activated.connect(self._on_shortcut_move_to_latest)

        # Ctrl+C / Ctrl+X / Ctrl+V 依赖 FileOperationService + ClipboardService
        if self._file_operation_service is not None and self._clipboard_service is not None:
            # 中栏 Ctrl+C / Ctrl+X / Ctrl+V（Task 3b 真实逻辑）
            self._shortcut_copy = QShortcut(QKeySequence("Ctrl+C"), self._content_view)
            self._shortcut_copy.setContext(Qt.ShortcutContext.WidgetShortcut)
            self._shortcut_copy.activated.connect(self._on_shortcut_copy)

            self._shortcut_cut = QShortcut(QKeySequence("Ctrl+X"), self._content_view)
            self._shortcut_cut.setContext(Qt.ShortcutContext.WidgetShortcut)
            self._shortcut_cut.activated.connect(self._on_shortcut_cut)

            self._shortcut_paste = QShortcut(QKeySequence("Ctrl+V"), self._content_view)
            self._shortcut_paste.setContext(Qt.ShortcutContext.WidgetShortcut)
            self._shortcut_paste.activated.connect(self._on_shortcut_paste)

            # 目录树 Ctrl+C / Ctrl+X / Ctrl+V（用户补充：目录树也支持复制/剪切/粘贴）
            self._shortcut_copy_tree = QShortcut(QKeySequence("Ctrl+C"), self._tree_view)
            self._shortcut_copy_tree.setContext(Qt.ShortcutContext.WidgetShortcut)
            self._shortcut_copy_tree.activated.connect(self._on_shortcut_copy_tree)

            self._shortcut_cut_tree = QShortcut(QKeySequence("Ctrl+X"), self._tree_view)
            self._shortcut_cut_tree.setContext(Qt.ShortcutContext.WidgetShortcut)
            self._shortcut_cut_tree.activated.connect(self._on_shortcut_cut_tree)

            self._shortcut_paste_tree = QShortcut(QKeySequence("Ctrl+V"), self._tree_view)
            self._shortcut_paste_tree.setContext(Qt.ShortcutContext.WidgetShortcut)
            self._shortcut_paste_tree.activated.connect(self._on_shortcut_paste_tree)

        # UX 重构 Phase 2 Task 5（Q5=B）：F5 刷新当前目录（窗口级，任意位置聚焦可触发）
        self._shortcut_refresh = QShortcut(QKeySequence("F5"), self)
        self._shortcut_refresh.setContext(Qt.ShortcutContext.WindowShortcut)
        self._shortcut_refresh.activated.connect(self._on_refresh_current)

    def _on_shortcut_rename_content(self) -> None:
        """F2：重命名中栏选中条目（Q1=A：多选取第一个）。"""
        if self._file_operation_service is None:
            return
        entries = self._get_selected_entries()
        if not entries:
            self.statusBar().showMessage(ui.SHORTCUT_NO_SELECTION, 2000)
            return
        # Q1=A：多选取第一个选中条目
        self._on_rename_entry(entries[0])

    def _on_shortcut_rename_tree(self) -> None:
        """F2：重命名目录树选中节点（用户补充：目录树也需要重命名快捷键）。

        复用 _on_rename_entry 逻辑，从目录树节点构造 FileEntry。
        """
        if self._file_operation_service is None:
            return
        # 获取目录树选中节点
        sm = self._tree_view.selectionModel()
        if sm is None:
            return
        indexes = sm.selectedIndexes()
        if not indexes:
            self.statusBar().showMessage(ui.SHORTCUT_NO_SELECTION, 2000)
            return
        node = self._tree_model.node_at(indexes[0])
        if node is None:
            return
        # 构造 FileEntry 并复用 _on_rename_entry
        from domain.models import FileEntry  # noqa: PLC0415

        entry = FileEntry(
            path=node.real_path,
            name=Path(node.real_path).name,
            is_dir=True,
            size=0,
            modified_at="1970-01-01T00:00:00Z",
            content_unit=None,
        )
        self._on_rename_entry(entry)

    def _on_shortcut_delete(self) -> None:
        """Delete：删除中栏选中条目。"""
        if self._file_operation_service is None:
            return
        entries = self._get_selected_entries()
        if not entries:
            self.statusBar().showMessage(ui.SHORTCUT_NO_SELECTION, 2000)
            return
        self._on_delete_entries(entries)

    def _on_shortcut_select_all(self) -> None:
        """Ctrl+A：全选中栏内容。"""
        self._content_view.selectAll()

    def _on_shortcut_undo(self) -> None:
        """Ctrl+Z：撤销最近一条可撤销操作。

        Q2=A：二次确认弹窗。
        Q3=B：跳过 delete 和已撤销的记录，取第一条可撤销且未撤销的。
        """
        if self._undo_service is None:
            return

        # Q3=B：取 list_recent 中第一条 can_undo=True 且 undone_at IS NULL 的记录
        try:
            histories = self._undo_service.list_recent(limit=100)
        except Exception as e:  # noqa: BLE001
            self.statusBar().showMessage(ui.SHORTCUT_UNDO_FAILED.format(error=str(e)), 3000)
            return

        target = None
        for h in histories:
            if h.can_undo and h.undone_at is None and h.operation_type != "undo":
                target = h
                break

        if target is None:
            self.statusBar().showMessage(ui.SHORTCUT_NO_UNDOABLE, 2000)
            return

        # Q2=A：二次确认弹窗
        from app.operation_history_dialog import _format_history_description  # noqa: PLC0415

        desc = _format_history_description(target, self._service)
        reply = QMessageBox.question(
            self,
            ui.SHORTCUT_UNDO_CONFIRM_TITLE,
            ui.SHORTCUT_UNDO_CONFIRM_TEXT.format(desc=desc),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # 执行撤销
        from application.errors import (  # noqa: PLC0415
            UndoAlreadyUndoneError,
            UndoNotAllowedError,
            UndoSafetyError,
        )

        try:
            self._undo_service.undo(target)
            self._commit()
            self._refresh_tree()
            self._refresh_content_list_for_current_mode()
            self.statusBar().showMessage(ui.SHORTCUT_UNDO_SUCCESS.format(desc=desc), 3000)
        except UndoNotAllowedError:
            QMessageBox.information(
                self,
                ui.SHORTCUT_UNDO_CONFIRM_TITLE,
                ui.SHORTCUT_UNDO_NOT_ALLOWED,
            )
        except UndoAlreadyUndoneError:
            self.statusBar().showMessage(ui.SHORTCUT_NO_UNDOABLE, 2000)
        except UndoSafetyError as e:
            QMessageBox.information(
                self,
                ui.SHORTCUT_UNDO_CONFIRM_TITLE,
                ui.SHORTCUT_UNDO_SAFETY_FAILED.format(reason=e.reason),
            )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self,
                ui.SHORTCUT_UNDO_CONFIRM_TITLE,
                ui.SHORTCUT_UNDO_FAILED.format(error=str(e)),
            )

    # === Stage 5 Task 3b：剪贴板快捷键 handler ===

    def _on_shortcut_copy(self) -> None:
        """Ctrl+C：复制中栏选中条目到应用内剪贴板。"""
        if self._clipboard_service is None:
            return
        entries = self._get_selected_entries()
        if not entries:
            self.statusBar().showMessage(ui.SHORTCUT_NO_SELECTION, 2000)
            return
        paths = [e.path for e in entries]
        self._clipboard_service.set_copy(paths)
        # 清除之前的剪切高亮
        self._content_list_model.set_cut_paths(set())
        self.statusBar().showMessage(ui.SHORTCUT_COPIED.format(n=len(paths)), 3000)

    def _on_shortcut_cut(self) -> None:
        """Ctrl+X：剪切中栏选中条目到应用内剪贴板。"""
        if self._clipboard_service is None:
            return
        entries = self._get_selected_entries()
        if not entries:
            self.statusBar().showMessage(ui.SHORTCUT_NO_SELECTION, 2000)
            return
        paths = [e.path for e in entries]
        self._clipboard_service.set_cut(paths)
        # 更新剪切高亮（Q12=A 50% 透明度）
        self._content_list_model.set_cut_paths(set(paths))
        self.statusBar().showMessage(ui.SHORTCUT_CUT.format(n=len(paths)), 3000)

    def _on_shortcut_paste(self) -> None:
        """Ctrl+V：粘贴到中栏当前目录。"""
        if self._clipboard_service is None or self._file_operation_service is None:
            return
        dst_dir = self._current_displayed_dir()
        if dst_dir is None:
            return
        self._perform_paste(Path(dst_dir))

    def _on_shortcut_copy_tree(self) -> None:
        """Ctrl+C：复制目录树选中节点到应用内剪贴板。"""
        if self._clipboard_service is None:
            return
        node = self._get_selected_tree_node()
        if node is None:
            self.statusBar().showMessage(ui.SHORTCUT_NO_SELECTION, 2000)
            return
        self._clipboard_service.set_copy([node.real_path])
        self._content_list_model.set_cut_paths(set())
        self.statusBar().showMessage(ui.SHORTCUT_COPIED.format(n=1), 3000)

    def _on_shortcut_cut_tree(self) -> None:
        """Ctrl+X：剪切目录树选中节点到应用内剪贴板。"""
        if self._clipboard_service is None:
            return
        node = self._get_selected_tree_node()
        if node is None:
            self.statusBar().showMessage(ui.SHORTCUT_NO_SELECTION, 2000)
            return
        self._clipboard_service.set_cut([node.real_path])
        self._content_list_model.set_cut_paths({node.real_path})
        self.statusBar().showMessage(ui.SHORTCUT_CUT.format(n=1), 3000)

    def _on_shortcut_paste_tree(self) -> None:
        """Ctrl+V：粘贴到目录树选中节点。"""
        if self._clipboard_service is None or self._file_operation_service is None:
            return
        node = self._get_selected_tree_node()
        if node is None:
            self.statusBar().showMessage(ui.SHORTCUT_NO_SELECTION, 2000)
            return
        self._perform_paste(Path(node.real_path))

    def _on_shortcut_delete_tree(self) -> None:
        """Delete：删除目录树选中节点。"""
        if self._file_operation_service is None:
            return
        node = self._get_selected_tree_node()
        if node is None:
            self.statusBar().showMessage(ui.SHORTCUT_NO_SELECTION, 2000)
            return
        entry = FileEntry(
            path=node.real_path,
            name=Path(node.real_path).name,
            is_dir=True,
            size=0,
            modified_at="1970-01-01T00:00:00Z",
            content_unit=None,
        )
        self._on_delete_entries([entry])

    def _get_selected_tree_node(self):
        """获取目录树当前选中节点，无选中返回 None。"""
        sm = self._tree_view.selectionModel()
        if sm is None:
            return None
        indexes = sm.selectedIndexes()
        if not indexes:
            return None
        return self._tree_model.node_at(indexes[0])

    def _perform_paste(self, dst_dir: Path) -> None:
        """执行粘贴操作（共享逻辑，供中栏/目录树 Ctrl+V 调用）。

        流程：
        1. 检查剪贴板是否为空
        2. 跨盘剪切检测（Q7=B 拒绝）
        3. 扫描冲突（ConflictResolutionService）
        4. 若有冲突，弹出 ConflictResolutionDialog（Q3=C 用户选择覆盖/跳过/重命名）
        5. 按 ResolvedAction 执行 copy/move，收集成功与失败
        6. 刷新 UI + 状态栏提示
        """
        from application.conflict_resolution_service import (  # noqa: PLC0415
            ConflictResolutionService,
            has_conflict,
            has_cross_drive_cut,
        )

        entry = self._clipboard_service.get()
        if entry is None or not entry.paths:
            self.statusBar().showMessage(ui.SHORTCUT_PASTE_EMPTY, 2000)
            return

        src_paths = [Path(p) for p in entry.paths]
        operation = entry.operation  # 'copy' or 'cut'

        # 跨盘剪切检测（Q7=B）
        conflict_service = ConflictResolutionService()
        conflicts = conflict_service.scan_conflicts(src_paths, dst_dir, operation)
        if operation == "cut" and has_cross_drive_cut(conflicts):
            QMessageBox.information(
                self, ui.CONFLICT_DIALOG_TITLE, ui.SHORTCUT_PASTE_CROSS_DRIVE_CUT
            )
            return

        # 冲突解决（Q3=C）
        if has_conflict(conflicts):
            from app.conflict_resolution_dialog import ConflictResolutionDialog  # noqa: PLC0415

            dialog = ConflictResolutionDialog(conflicts, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return  # 用户取消
            decisions = dialog.decisions()
        else:
            # 无冲突，全部用默认目标路径
            decisions = ["overwrite"] * len(conflicts)

        actions = conflict_service.resolve(conflicts, decisions)

        # 执行 copy/move
        ok_count = 0
        fail_count = 0
        errors: list[str] = []
        for action in actions:
            if action.skipped:
                continue
            try:
                if operation == "copy":
                    self._file_operation_service.copy(
                        action.src, action.dst, overwrite=action.overwrite
                    )
                else:  # cut
                    self._file_operation_service.move(
                        action.src, action.dst, overwrite=action.overwrite
                    )
                ok_count += 1
            except SourceNotFoundError:
                fail_count += 1
                errors.append(ui.SHORTCUT_PASTE_SRC_NOT_FOUND.format(name=action.src.name))
            except (ConflictError, CrossDriveError, SelfSubdirectoryError, FileOperationError) as e:
                fail_count += 1
                errors.append(ui.SHORTCUT_PASTE_FAILED.format(error=str(e)))

        # cut 模式粘贴后清空剪贴板 + 清除剪切高亮
        if operation == "cut":
            self._clipboard_service.clear()
            self._content_list_model.set_cut_paths(set())

        # 提交事务 + 刷新 UI
        self._commit()
        self._refresh_tree()
        self._refresh_content_list_for_current_mode()
        # 修复1：若粘贴目标目录与钉住的装配面板文件夹相同，同步刷新装配面板。
        # 若为 cut 操作，源目录内容也变化，需一并检查。
        affected_dirs: list[Path] = [dst_dir]
        if operation == "cut":
            affected_dirs.extend(Path(p).parent for p in entry.paths if p)
        self._refresh_assembly_if_affected(*affected_dirs)

        # 状态栏提示
        if fail_count == 0:
            self.statusBar().showMessage(
                ui.SHORTCUT_PASTED.format(n=ok_count, dir_name=dst_dir.name), 3000
            )
        else:
            QMessageBox.information(
                self,
                ui.CONFLICT_DIALOG_TITLE,
                ui.SHORTCUT_PASTE_PARTIAL.format(ok=ok_count, fail=fail_count)
                + "\n\n"
                + "\n".join(errors[:5]),
            )

    # === Stage 5 Task 5：「移动到……」快捷对话框 ===

    def _on_shortcut_move_to(self) -> None:
        """Ctrl+M 中栏：触发移动到对话框。"""
        entries = self._get_selected_entries()
        if not entries:
            self.statusBar().showMessage(ui.SHORTCUT_MOVE_TO_NO_SELECTION, 2000)
            return
        self._on_move_to(entries)

    def _on_shortcut_move_to_latest(self) -> None:
        """Ctrl+Q：目录树/中栏选中条目 → 直接移动到最近目标（操作便捷性3）。

        BugFix1（2026-08-02）：目录树获得焦点时优先移动树选中节点（与 Ctrl+M
        的树版本行为对称），否则移动中栏选中条目；移动后统一 _refresh_tree。
        """
        src_paths: list[Path] = []
        if self._tree_view.hasFocus():
            tree_path = self._tree_selected_path()
            if tree_path is None:
                self.statusBar().showMessage(ui.SHORTCUT_MOVE_TO_NO_SELECTION, 2000)
                return
            src_paths = [tree_path]
        else:
            entries = self._get_selected_entries()
            if not entries:
                self.statusBar().showMessage(ui.SHORTCUT_MOVE_TO_NO_SELECTION, 2000)
                return
            src_paths = [Path(e.path) for e in entries]
        latest = self._recent_move_targets.latest()
        if latest is None:
            self.statusBar().showMessage(ui.SHORTCUT_MOVE_TO_LATEST_NO_TARGET, 3000)
            return
        self._perform_move_to(src_paths, Path(latest))

    def _tree_selected_path(self) -> Path | None:
        """返回目录树当前选中节点的路径；无选中返回 None。"""
        sm = self._tree_view.selectionModel()
        if sm is None:
            return None
        indexes = sm.selectedIndexes()
        if not indexes:
            return None
        node = self._tree_model.node_at(indexes[0])
        if node is None:
            return None
        return Path(node.real_path)

    def _on_shortcut_move_to_tree(self) -> None:
        """Ctrl+M 目录树：触发移动到对话框。"""
        sm = self._tree_view.selectionModel()
        if sm is None:
            return
        indexes = sm.selectedIndexes()
        if not indexes:
            self.statusBar().showMessage(ui.SHORTCUT_MOVE_TO_NO_SELECTION, 2000)
            return
        node = self._tree_model.node_at(indexes[0])
        if node is None:
            return
        self._on_move_to_tree(node)

    def _on_move_to(self, entries: list[FileEntry]) -> None:
        """中栏右键「移动到...」入口。

        Args:
            entries: 选中的文件/文件夹条目列表。
        """
        if self._file_operation_service is None:
            return
        if not entries:
            self.statusBar().showMessage(ui.SHORTCUT_MOVE_TO_NO_SELECTION, 2000)
            return
        src_paths = [Path(e.path) for e in entries]
        # Q7=A：默认展开源所在目录的父目录
        default_expand = Path(entries[0].path).parent
        self._open_move_to_dialog(src_paths, default_expand)

    def _on_move_to_tree(self, node) -> None:
        """目录树右键「移动到...」入口。

        Args:
            node: 选中的 TreeNode。
        """
        if self._file_operation_service is None:
            return
        src_path = Path(node.real_path)
        # Q7=A：默认展开源所在目录的父目录
        default_expand = src_path.parent
        self._open_move_to_dialog([src_path], default_expand)

    def _on_move_to_recent(self, src_paths: list[Path], target: str) -> None:
        """执行移动到最近目标（复用 _perform_move_to 完整安全流程）。"""
        self._perform_move_to(src_paths, Path(target))

    def _insert_recent_move_submenu(self, menu, src_paths: list[Path]) -> None:
        """在「移动到...」菜单项后插入「移动到最近目录」子菜单。

        操作便捷性3（2026-08-02）：最近移动目标快捷入口。
        无最近目标时不插入；子菜单项文本用路径简化显示，Tooltip 为完整路径。
        """
        recent = self._recent_move_targets.list_recent()
        if not recent:
            return
        submenu = QMenu(ui.MENU_MOVE_TO_RECENT, menu)
        for target in recent:
            display = make_display_path_from_service(target, self._service)
            act = submenu.addAction(display)
            act.setToolTip(target)
            act.triggered.connect(
                lambda checked=False, t=target: self._on_move_to_recent(src_paths, t)
            )
        # 插到「移动到...」之后（insertMenu 在指定 action 之前插入，故用下一项）
        actions = menu.actions()
        for i, act in enumerate(actions):
            if act.text() == ui.MENU_MOVE_TO:
                if i + 1 < len(actions):
                    menu.insertMenu(actions[i + 1], submenu)
                else:
                    menu.addMenu(submenu)
                break

    def _insert_recent_tag_submenu(self, menu, unit_id: str) -> None:
        """在右键菜单追加「添加最近标签 ▸」子菜单（UI合理性8）。

        列出最近使用标签，点击直接 attach + 提交，避免打开完整标签面板。
        无最近标签或 TagService 未注入时不插入。
        """
        if self._tag_service is None or self._recent_tags is None:
            return
        tag_ids = self._recent_tags.list_recent()
        if not tag_ids:
            return
        # id → name 映射（list_categories_with_tags 一次获取全部）
        id_to_name: dict[str, str] = {}
        try:
            for _category, tags in self._tag_service.list_categories_with_tags():
                for t in tags:
                    id_to_name[t.id] = t.name
        except ApplicationError:
            return
        submenu = QMenu(ui.MENU_ADD_RECENT_TAG, menu)
        for tag_id in tag_ids:
            name = id_to_name.get(tag_id)
            if name is None:
                continue  # 标签已删除，跳过
            act = submenu.addAction(name)
            act.triggered.connect(
                lambda checked=False, tid=tag_id: self._on_add_recent_tag(unit_id, tid)
            )
        menu.addMenu(submenu)

    def _on_add_recent_tag(self, unit_id: str, tag_id: str) -> None:
        """右键「添加最近标签」点击：立即 attach + 提交（操作便捷性4）。"""
        if self._tag_service is None:
            return
        try:
            self._tag_service.attach_tag_to_unit(unit_id, tag_id)
        except (ApplicationError, RepositoryError, sqlite3.Error) as e:
            self._handle_service_error(e, ui.METADATA_PANEL_SAVE_FAILED, rollback=False)
            return
        self._commit()
        self._recent_tags.record(tag_id)
        # 元数据面板正显示该 unit 时同步刷新标签状态
        if self._metadata_panel is not None:
            current = self._metadata_panel.current_unit()
            if current is not None and current.id == unit_id:
                unit = self._content_service.get_by_id(unit_id)
                if unit is not None:
                    self._metadata_view.load_unit(unit)

    def _open_move_to_dialog(self, src_paths: list[Path], default_expand: Path | None) -> None:
        """打开「移动到...」对话框并处理结果。

        Args:
            src_paths: 待移动的源路径列表。
            default_expand: 对话框默认展开的目录路径。
        """
        from app.move_to_dialog import MoveToDialog  # noqa: PLC0415

        dialog = MoveToDialog(
            folder_tree_service=self._tree_service,
            src_paths=src_paths,
            default_expand_path=default_expand,
            recent_targets=self._recent_move_targets.list_recent(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.statusBar().showMessage(ui.SHORTCUT_MOVE_TO_CANCELLED, 2000)
            return
        target_dir = dialog.selected_target_path()
        if target_dir is None:
            self.statusBar().showMessage(ui.SHORTCUT_MOVE_TO_NO_TARGET, 2000)
            return
        self._perform_move_to(src_paths, target_dir)

    def _perform_move_to(
        self,
        src_paths: list[Path],
        target_dir: Path,
        *,
        refresh_assembly: bool = False,
        ok_msg: str = ui.SHORTCUT_MOVE_TO_OK,
        fail_title: str = ui.MOVE_TO_DIALOG_TITLE,
        partial_msg: str = ui.SHORTCUT_MOVE_TO_PARTIAL,
    ) -> None:
        """执行移动到目标目录（复用 ConflictResolutionService 处理冲突）。

        流程与 _perform_paste 类似，但 operation 固定为 'cut'（移动），
        且不涉及剪贴板清理。

        UX 重构 Phase 1 Task 4 修复3：拖拽 / 添加到钉住文件夹也走此路径，
        统一冲突解决流程（重命名/跳过/覆盖询问），统一自目录检测（修复4）。

        Args:
            src_paths: 源路径列表。
            target_dir: 目标目录。
            refresh_assembly: 是否强制刷新装配面板（拖入装配面板时为 True）。
                修复1：无论此参数为何，只要 target_dir 与装配面板当前透视的
                文件夹相同，就会刷新装配面板（覆盖拖拽到中栏被钉住文件夹场景）。
            ok_msg: 成功状态栏提示模板，支持 {n}/{dir_name}/{name} 占位符。
            fail_title: 失败弹窗标题。
            partial_msg: 部分失败摘要模板，支持 {ok}/{fail} 占位符。
        """
        from application.conflict_resolution_service import (  # noqa: PLC0415
            ConflictResolutionService,
            has_conflict,
            has_cross_drive_cut,
        )

        if self._file_operation_service is None:
            return

        conflict_service = ConflictResolutionService()
        conflicts = conflict_service.scan_conflicts(src_paths, target_dir, operation="cut")

        # 跨盘剪切检测（Q7=B 拒绝）
        if has_cross_drive_cut(conflicts):
            QMessageBox.information(self, fail_title, ui.SHORTCUT_MOVE_TO_CROSS_DRIVE)
            return

        # 冲突解决（Q5=A 复用 ConflictResolutionDialog）
        if has_conflict(conflicts):
            from app.conflict_resolution_dialog import ConflictResolutionDialog  # noqa: PLC0415

            conflict_dialog = ConflictResolutionDialog(conflicts, self)
            if conflict_dialog.exec() != QDialog.DialogCode.Accepted:
                return  # 用户取消
            decisions = conflict_dialog.decisions()
        else:
            # 无冲突，全部用默认目标路径
            decisions = ["overwrite"] * len(conflicts)

        actions = conflict_service.resolve(conflicts, decisions)

        # 执行 move
        ok_count = 0
        fail_count = 0
        errors: list[str] = []
        for action in actions:
            if action.skipped:
                continue
            try:
                self._file_operation_service.move(
                    action.src, action.dst, overwrite=action.overwrite
                )
                ok_count += 1
            except SourceNotFoundError:
                fail_count += 1
                errors.append(ui.SHORTCUT_MOVE_TO_SRC_NOT_FOUND.format(name=action.src.name))
            except SelfSubdirectoryError:
                fail_count += 1
                errors.append(ui.SHORTCUT_MOVE_TO_SELF_SUBDIR)
            except CrossDriveError:
                fail_count += 1
                errors.append(ui.SHORTCUT_MOVE_TO_CROSS_DRIVE)
            except (ConflictError, FileOperationError) as e:
                fail_count += 1
                errors.append(ui.SHORTCUT_MOVE_TO_FAILED.format(error=str(e)))

        # 操作便捷性3：记录最近移动目标（至少 1 项成功）
        if ok_count > 0:
            self._recent_move_targets.record(target_dir)

        # 提交事务 + 刷新 UI
        self._commit()
        self._refresh_tree()
        self._refresh_content_list_for_current_mode()
        # 修复1：拖拽到中栏被钉住文件夹后同步刷新装配面板。
        # 检查 target_dir（目标）和各 src 的父目录（源），任一命中钉住文件夹则刷新。
        # refresh_assembly=True（拖入装配面板）时无条件刷新。
        if refresh_assembly:
            if self._assembly_panel is not None:
                self._assembly_panel.refresh_current()
        else:
            affected_dirs = [target_dir] + [Path(p).parent for p in src_paths]
            self._refresh_assembly_if_affected(*affected_dirs)

        # 状态栏提示
        if fail_count == 0:
            self.statusBar().showMessage(
                ok_msg.format(n=ok_count, dir_name=target_dir.name, name=target_dir.name),
                3000,
            )
        else:
            QMessageBox.information(
                self,
                fail_title,
                partial_msg.format(ok=ok_count, fail=fail_count)
                + "\n\n"
                + "\n".join(errors[:MAX_ERROR_SUMMARY_LINES]),
            )

    def _update_metadata(self, unit: ContentUnit) -> None:
        """更新元数据面板。

        Stage 4 Task 2：若有 MetadataPanel，加载到编辑表单；同时保留
        `_metadata_full_text` 多行文本格式以兼容现有测试（metadata_full_text()）。

        Stage 5 Task 7 收尾：移除"整理状态"显示行。v13（UX 重构 Task 6）纯 DELETE
        模式下记录存在即已标记，能进入此方法的状态恒为已标记，显示无意义。
        """
        source_url = unit.source_url or ui.METADATA_SOURCE_URL_EMPTY
        notes = unit.notes or ui.METADATA_NOTES_EMPTY

        lines = [
            f"{ui.METADATA_PATH_LABEL}：{make_display_path_from_service(unit.path, self._service)}",
            f"{ui.METADATA_TYPE_LABEL}：{unit.content_type}",
            f"{ui.METADATA_SOURCE_URL_LABEL}：{source_url}",
            f"{ui.METADATA_NOTES_LABEL}：{notes}",
            f"{ui.METADATA_CREATED_AT_LABEL}：{unit.created_at}",
        ]
        # 兼容旧测试：缓存多行文本（metadata_full_text()）
        self._metadata_full_text = "\n".join(lines)
        # 切换显示：若有 MetadataPanel，隐藏 label 显示 panel
        if self._metadata_panel is not None:
            self._metadata_label.setVisible(False)
            # UX 重构 Task 7 Step 4：面板加载委托 MetadataView
            self._metadata_view.load_unit(unit)
        else:
            self._metadata_label.setText(self._metadata_full_text)
            self._metadata_label.setToolTip(self._metadata_full_text)

    # --- Stage 4 Task 2：MetadataPanel 信号处理 ---

    def _on_metadata_saved(self, updated_unit: ContentUnit) -> None:
        """MetadataView 保存成功（事务已提交）→ 刷新中栏 + 状态栏提示。

        UX 重构 Task 7 Step 4：事务提交由 MetadataView 在保存时完成，
        MainWindow 仅负责刷新联动。
        """
        # 刷新中栏文件列表（名称/封面图标可能变化）
        self._refresh_content_list_for_current_mode()
        # 同步元数据面板状态（updated_unit 包含最新字段）
        self._update_metadata(updated_unit)
        self.statusBar().showMessage(ui.METADATA_PANEL_SAVE_OK, 3000)

    def _on_cover_saved(self, updated_unit: ContentUnit) -> None:
        """封面即时保存成功（操作便捷性6，2026-08-03）→ 刷新中栏 + 状态栏提示。

        仅刷新中栏（封面图标/缩略图变化），不重载元数据面板——
        未保存的来源/备注编辑保留在表单中。
        """
        self._refresh_content_list_for_current_mode()
        self.statusBar().showMessage(ui.METADATA_PANEL_COVER_SAVED, 3000)

    def _on_metadata_rename_requested(self, unit_id: str, new_name: str) -> None:
        """元数据面板重命名栏回车（UI合理性13）→ 执行文件重命名。

        复用 FileOperationService.rename 的既有链路（冲突/非法名处理、operation_history、
        目录树与中栏刷新），成功后仅更新面板的当前 unit 与重命名栏文本
        （不重载表单，保留未保存的来源/备注编辑，与 apply_cover 同策略）。
        """
        if self._file_operation_service is None or self._content_service is None:
            return
        unit = self._content_service.get_by_id(unit_id)
        if unit is None:
            return
        old_path = Path(unit.path)
        new_name = new_name.strip()
        if not new_name or new_name == old_path.name:
            return
        dir_path = str(old_path.parent)
        try:
            self._file_operation_service.rename(old_path, new_name)
            self._commit()
            self._refresh_tree()
            # 恢复中栏显示（rename 后 _refresh_tree 会清空列表）
            self._restore_middle_after_tree_refresh(dir_path)
            # 更新面板状态（保留未保存编辑）
            updated = self._content_service.get_by_id(unit_id)
            if updated is not None and self._metadata_panel is not None:
                self._metadata_panel.apply_renamed_unit(updated)
            self.statusBar().showMessage(ui.MENU_RENAME_SUCCESS.format(name=new_name), 3000)
        except Exception as e:  # noqa: BLE001 - UI 边界统一兜底
            self._handle_service_error(e, ui.MENU_OPERATION_FAILED.format(error=str(e)))

    def _on_batch_tag(self, entries: list[FileEntry]) -> None:
        """批量打标签：弹出 BatchTagDialog。

        spec §7.5 / §10.3：文件列表多选内容单元 → 右键「批量打标签」。
        事务边界：BatchTagDialog 不自提交，由 MainWindow 在 exec() 后提交。
        """
        if self._tag_service is None:
            return
        content_unit_ids: list[str] = []
        for entry in entries:
            if entry.content_unit is not None:
                content_unit_ids.append(entry.content_unit.id)
        if not content_unit_ids:
            QMessageBox.information(self, ui.BATCH_TAG_DIALOG_TITLE, "选中的条目均不是内容单元。")
            return

        dialog = BatchTagDialog(self._tag_service, content_unit_ids, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._commit()
        # 刷新中栏文件列表（标签标记可能需要更新）
        self._refresh_content_list_for_current_mode()
        # 状态栏显示结果摘要
        messages = dialog.result_messages()
        if messages:
            self.statusBar().showMessage("；".join(messages), 5000)

    # --- Elide 路径文本（决策问题 4，Task 5 统一路径显示策略） ---

    # 需要对值部分做 ElideMiddle 的路径前缀列表
    _ELIDE_PATH_PREFIXES = ("路径：", "完整路径：", "目标：")

    def _set_detail_text(self, text: str) -> None:
        """设置详情区文本（缓存原文，触发 Elide 重算）。"""
        self._detail_full_text = text
        self._apply_elide()

    def _set_metadata_text(self, text: str) -> None:
        """设置元数据面板文本（缓存原文，触发 Elide 重算）。

        Stage 4 Task 2：若有 MetadataPanel，隐藏 panel 显示 label 提示文本，
        并清空 panel 表单。
        """
        self._metadata_full_text = text
        if self._metadata_panel is not None:
            self._metadata_panel.setVisible(False)
            self._metadata_panel.clear_panel()
            self._metadata_label.setVisible(True)
        self._apply_elide()

    def _apply_elide(self) -> None:
        """对详情区、元数据面板的路径行应用 ElideMiddle。

        多行文本按 \\n 拆分，仅对路径行（"路径：..." / "完整路径：..." / "目标：..."）
        做值部分省略，其他行原样保留。文本超长时用 QFontMetrics.elidedText 替换为中间省略形式。
        同时设置 Tooltip 显示完整文本，便于鼠标悬停查看。
        """
        self._elide_label_lines(self._detail_label, self._detail_full_text)
        self._elide_label_lines(self._metadata_label, self._metadata_full_text)

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
        if self._scan_controller.is_scanning():
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
        except Exception as e:  # noqa: BLE001 - UI 边界需捕获所有异常
            self._handle_service_error(e, ui.ERR_ADD_ROOT_FAILED)
            return
        self._refresh_root_list()
        self._refresh_tree()

    # --- 移除根目录配置 ---

    def _on_remove_root(self) -> None:
        """移除选中的受管理根目录配置。

        UX 重构 Task 6：ManagedRootService.remove_root 同步清理该根路径前缀下的
        folder_cache / content_unit 扫描记录（重叠守卫 + UoW 事务，Service 内部提交）。
        仅删除应用数据库记录；不删除、不移动、不修改磁盘上的任何用户文件。
        """
        if self._scan_controller.is_scanning():
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
        except ManagedRootNotFoundError:
            self._refresh_root_list()
            return
        except Exception as e:  # noqa: BLE001 - UI 边界需捕获所有异常
            self._handle_service_error(e, ui.ERR_REMOVE_ROOT_FAILED)
            return

        self._refresh_root_list()
        self._refresh_tree()

    # --- 扫描 ---

    def _on_scan(self, incremental: bool = True) -> None:
        """启动后台扫描。扫描期间禁用扫描入口。"""
        if self._scan_controller.is_scanning():
            return
        root_id = self._selected_root_id()
        if root_id is None:
            self._set_status(ui.ERR_NO_ROOT_SELECTED)
            return

        self._begin_scanning()
        # UX 重构 Task 7 Step 2：线程生命周期由 ScanController 管理
        self._scan_controller.start_scan(root_id, incremental=incremental)

    def _begin_scanning(self) -> None:
        """扫描开始：禁用扫描入口与根目录操作按钮（UI 状态）。"""
        self._scan_button.setText(ui.SCAN_BUTTON_SCANNING)
        self._scan_button.setEnabled(False)
        self._scan_full_button.setEnabled(False)
        self._add_button.setEnabled(False)
        self._remove_button.setEnabled(False)
        self._set_status(ui.STATUS_SCANNING)

    def _end_scanning(self) -> None:
        """恢复按钮状态。"""
        self._scan_button.setText(ui.SCAN_BUTTON)
        self._add_button.setEnabled(True)
        has_selection = self._selected_root_id() is not None
        self._scan_button.setEnabled(has_selection)
        self._scan_full_button.setEnabled(has_selection)
        self._remove_button.setEnabled(has_selection)

    def _on_scan_started(self) -> None:
        self._set_status(ui.STATUS_SCANNING)

    def _on_scan_progress(self, text: str) -> None:
        """TD-M13：扫描进度文本 → 状态栏（ScanWorker 当前仅发送"正在扫描…"）。"""
        self._set_status(text)

    def _on_scan_finished(self, summary: ScanSummary) -> None:
        """扫描完成：展示摘要、刷新目录树、刷新当前中栏文件列表。

        扫描联动（roadmap 阶段 2 Task 5 验收项 5）：
        - 若当前选中目录树节点，刷新该目录的文件列表，
          使新扫描出的压缩包文件立即显示 -- 标记。
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

        UX 重构 Phase 1 Task 1：移除模式分支，统一为原 browse 行为。
        若目录树有选中节点，重新读取该目录文件列表；否则无操作。
        """
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
        """设置扫描状态文本（Q7=A 统一状态栏）。

        多行文本（如扫描摘要含错误列表）只显示第一行，完整内容通过 Tooltip 查看，
        避免 QStatusBar 高度抖动。
        """
        if "\n" in text:
            first_line = text.split("\n", 1)[0]
            self._status_label.setText(first_line)
            self._status_label.setToolTip(text)
        else:
            self._status_label.setText(text)
            self._status_label.setToolTip("扫描状态")

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

    def is_metadata_panel_visible(self) -> bool:
        """返回右栏元数据面板（含 label 与编辑表单）是否可见（供测试）。

        Stage 4 Task 2（2026-07-25 决策修正：原决策 4/8 推翻，方案 B）：
        两种模式下右栏 MetadataPanel 均保留可见。
        """
        return self._metadata_group.isVisibleTo(self)

    def metadata_panel(self) -> MetadataPanel | None:
        """返回 MetadataPanel 实例（仅当注入 TagService 时存在，供测试）。"""
        return self._metadata_panel

    def tag_filter_bar(self) -> TagFilterBar | None:
        """返回 TagFilterBar 实例（仅当注入 TagService 时存在，供测试）。"""
        return self._tag_filter_bar

    # --- Stage 5 Task 1：视图切换测试接口 ---

    def current_view_index(self) -> int:
        """返回当前活动视图索引（0=列表，1=卡片，供测试）。"""
        return self._current_view_index

    def view_switch_bar_visible(self) -> bool:
        """返回视图切换栏是否可见（供测试）。"""
        return self._view_switch_bar.isVisibleTo(self)

    def card_icon_size(self) -> int:
        """返回当前卡片图标尺寸（供测试）。"""
        return self._card_icon_size

    def zoom_combo_value(self) -> int:
        """返回缩放下拉框当前值（供测试）。"""
        return self._zoom_combo.currentData()

    def set_card_icon_size_for_test(self, size: int) -> None:
        """测试辅助：通过下拉框设置卡片图标尺寸。"""
        if size not in ui.ZOOM_PRESET_SIZES:
            return
        index = ui.ZOOM_PRESET_SIZES.index(size)
        self._zoom_combo.setCurrentIndex(index)  # 触发 currentIndexChanged → _on_zoom_combo_changed

    def switch_view_for_test(self, view_index: int) -> None:
        """测试辅助：切换视图（供测试）。"""
        self._switch_view(view_index)

    def build_content_menu_actions(
        self, entries: list[FileEntry]
    ) -> list[tuple[str, object, bool]]:
        """测试辅助：返回右键菜单项列表（供测试）。"""
        return self._build_content_menu_actions(entries)

    def open_in_explorer_handler(self) -> Callable[[str], None]:
        """测试辅助：返回「在资源管理器中打开」handler（供测试）。"""
        return self._on_open_in_explorer

    def card_list_model(self) -> CardListModel:
        """返回 CardListModel 实例（供测试）。"""
        return self._card_list_model

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

    def assembly_panel_is_pinned(self) -> bool:
        """返回装配面板当前是否处于钉住状态（供测试，UX 重构 Phase 1 Task 3）。"""
        if self._assembly_panel is None:
            return False
        return self._assembly_panel.is_pinned()

    def assembly_panel_pin_button_enabled(self) -> bool:
        """返回装配面板 📌 按钮是否可点击（供测试，A5 决策）。"""
        if self._assembly_panel is None:
            return False
        return self._assembly_panel._pin_button.isEnabled()  # noqa: SLF001
