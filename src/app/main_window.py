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

import logging
import sqlite3
import subprocess
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,  # noqa: F401 - 测试以 app.main_window.QInputDialog 命名空间补丁拦截对话框
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QMainWindow,
    QMenu,  # noqa: F401 - 测试以 app.main_window.QMenu 命名空间补丁拦截右键菜单构建
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app import file_type_icon_colors, file_type_icons
from app import ui_constants as ui
from app.app_paths import get_app_settings
from app.archive_settings import ArchiveSettings
from app.assembly_controller import AssemblyController
from app.assembly_panel import AssemblyPanel
from app.asset_credits_dialog import AssetCreditsDialog
from app.batch_tag_dialog import BatchTagDialog
from app.card_list_model import CardListModel
from app.content_list_controller import ContentListController
from app.content_unit_delegate import ContentUnitStripeDelegate
from app.content_unit_marker_config import ContentUnitMarkerConfig
from app.content_unit_marker_dialog import ContentUnitMarkerDialog
from app.content_views import _DragDropListView, _RubberBandTableView
from app.context_menu_builder import ContextMenuBuilder
from app.entry_dialogs import show_create_mod_group_dialog, show_rename_dialog
from app.feature_toggle_config import FeatureToggleConfig
from app.file_list_model import (
    COL_MODIFIED,
    COL_NAME,
    COL_SIZE,
    COL_TYPE,
    SORT_DIRECTION_ASC,
    SORT_DIRECTION_DESC,
    SORT_MODIFIED,
    SORT_NAME,
    SORT_SIZE,
    SORT_TYPE,
    FileListModel,
)
from app.file_operations_controller import FileOperationsController
from app.file_type_icon_colors_dialog import FileTypeIconColorsDialog
from app.folder_tree_model import FolderTreeModel
from app.main_menu_bar import MainMenuBar
from app.metadata_helpers import elide_label_lines, format_metadata_lines
from app.metadata_panel import MetadataPanel
from app.metadata_view import MetadataView
from app.navigation_controller import NavigationController
from app.recent_move_targets import RecentMoveTargets
from app.recent_tags import RecentTags
from app.scan_controller import ScanController
from app.scan_ui_state import ScanUiState
from app.search_controller import SearchController
from app.selection_memory import SelectionMemory
from app.settings_dialog import SettingsDialog
from app.shortcut_config import ShortcutConfig
from app.shortcut_registry import ShortcutRegistry
from app.sort_combo_box import PressSelectComboBox
from app.splitter_state import SplitterStateHelper
from app.tag_filter import TagFilterBar
from app.thumbnail_coordinator import ThumbnailCoordinator
from app.transaction_scope import TransactionScope
from app.tree_roots_controller import TreeRootsController
from app.url_settings import UrlSettingsConfig, UrlSettingsDialog
from app.view_state_controller import ViewStateController
from application.archive_manifest_service import ArchiveManifestService
from application.assembly_service import AssemblyService
from application.clipboard_service import ClipboardService
from application.content_service import ContentService
from application.content_unit_creation_service import ContentUnitCreationService
from application.errors import (
    ApplicationError,
)
from application.file_operation_service import FileOperationService
from application.folder_tree_service import FolderTreeService
from application.managed_root_service import ManagedRootService
from application.scan_service import ScanSummary
from application.search_service import SearchService
from application.strip_service import StripService
from application.tag_service import TagService
from application.undo_service import UndoService
from domain.models import ContentUnit, FileEntry
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
        strip_service: StripService | None = None,
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
        # 操作便捷性1（2026-08-04）：剥离（提取内容）
        self._strip_service = strip_service
        # Stage 5 Task 7：全局搜索服务
        self._search_service = search_service
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
        # 2026-08-04（用户反馈）：QSettings 文件化（settings.ini），不写 Windows 注册表
        self._qsettings = get_app_settings()
        self._splitter_state = SplitterStateHelper(self._qsettings)
        # UI合理性4 二期：文件类型图标颜色配置（自定义颜色启动即生效）
        file_type_icons.set_type_colors(file_type_icon_colors.load_colors(self._qsettings))
        # UI合理性21：内容单元标记配置（行首徽章 + 色条），QSettings 持久化
        self._marker_config = ContentUnitMarkerConfig.load(self._qsettings)
        # 操作便捷性3（2026-08-02）：最近移动目标（右键子菜单 / Ctrl+Q / 对话框快捷区）
        self._recent_move_targets = RecentMoveTargets(self._qsettings)
        # UI合理性8（2026-08-02）：最近使用标签（面板最近区 / 右键「添加最近标签」）
        self._recent_tags = RecentTags(self._qsettings)
        # 功能增加1（2026-08-04）：归档设置（归档根目录 + 上次归档位置）
        self._archive_settings = ArchiveSettings(self._qsettings)
        self._archive_manifest_service = ArchiveManifestService()
        # 设计合理性1（2026-08-04）：右键功能开关 + 快捷键配置（QSettings 持久化）
        self._feature_toggle_config = FeatureToggleConfig.load(self._qsettings)
        self._shortcut_config = ShortcutConfig.load(self._qsettings)
        # 操作便捷性7：目录 → 最后一次选中路径列表（后退/前进时恢复）
        self._selection_memory = SelectionMemory()

        self.setWindowTitle(ui.APP_TITLE)
        self.resize(ui.WINDOW_DEFAULT_WIDTH, ui.WINDOW_DEFAULT_HEIGHT)

        self._setup_ui()
        # TD-M21 阶段 8：扫描 UI 状态联动（按钮/状态栏/刷新）
        self._scan_ui_state = ScanUiState(
            self._scan_button,
            self._scan_full_button,
            self._add_button,
            self._remove_button,
            self._tree_view,
            self._tree_model,
            self._scan_controller,
            selected_root_id=self._selected_root_id,
            set_status=self._set_status,
            refresh_tree=self._refresh_tree,
            refresh_content_list=self._refresh_content_list,
            archive_root_provider=self._archive_settings.root_path,
        )
        # TD-M21 阶段 2：导航历史与视图状态控制器（状态归控制器，MainWindow 镜像/委托）
        self._navigation_controller = NavigationController(
            self._tree_model,
            self._tree_view,
            self._nav_back_button,
            self._nav_forward_button,
            refresh_content_list=self._refresh_content_list,
            set_metadata_not_selected=lambda: self._set_metadata_text(ui.METADATA_NOT_SELECTED),
            parent=self,
        )
        self._view_state_controller = ViewStateController(
            content_stack=self._content_stack,
            content_view=self._content_view,
            card_view=self._card_view,
            content_list_model=self._content_list_model,
            card_list_model=self._card_list_model,
            menu_bar=self._menu_bar,
            view_list_button=self._view_list_button,
            view_card_button=self._view_card_button,
            zoom_combo=self._zoom_combo,
            sort_field_combo=self._sort_field_combo,
            qsettings=self._qsettings,
            parent=self,
        )
        # TD-M21 阶段 3：全局搜索控制器（对话框复用 + 结果跳转）
        self._search_controller = SearchController(
            self._search_service,
            self._search_box,
            self._content_service,
            navigate_to=self._navigate_to_directory,
            content_view_current=self._content_view_current,
            dialog_parent=self,
            parent=self,
        )
        # TD-M21 阶段 4：目录树/根目录控制器
        self._tree_roots_controller = TreeRootsController(
            root_list=self._root_list,
            empty_hint=self._empty_hint,
            remove_button=self._remove_button,
            scan_button=self._scan_button,
            scan_full_button=self._scan_full_button,
            tree_view=self._tree_view,
            tree_model=self._tree_model,
            tree_empty_hint=self._tree_empty_hint,
            content_empty_hint=self._content_empty_hint,
            content_list_model=self._content_list_model,
            managed_root_service=self._service,
            tree_service=self._tree_service,
            scan_controller=self._scan_controller,
            transaction_scope=self._transaction_scope,
            refresh_content_list=self._refresh_content_list,
            set_detail_text=self._set_detail_text,
            set_metadata_text=self._set_metadata_text,
            set_status=self._set_status,
            handle_error=self._handle_service_error,
            dialog_parent=self,
            parent=self,
        )
        # TD-M21 阶段 5：右键菜单构建器（纯构建，handler 经 host 回调）
        self._context_menu_builder = ContextMenuBuilder(
            content_unit_creation_service=self._content_unit_creation_service,
            tag_service=self._tag_service,
            assembly_service=self._assembly_service,
            assembly_panel=self._assembly_panel,
            file_operation_service=self._file_operation_service,
            clipboard_service=self._clipboard_service,
            strip_service=self._strip_service,
            content_view=self._content_view,
            card_view=self._card_view,
            content_list_model=self._content_list_model,
            card_list_model=self._card_list_model,
            tree_view=self._tree_view,
            tree_model=self._tree_model,
            current_view_index=lambda: self._current_view_index,
            current_displayed_dir=self._current_displayed_dir,
            dialog_parent=self,
            host=self,
            archive_settings=self._archive_settings,
            feature_toggle_config=self._feature_toggle_config,
        )
        # TD-M21 阶段 6：文件操作编排控制器（新建/重命名/删除/粘贴/移动到/撤销）
        self._file_operations_controller = FileOperationsController(
            file_operation_service=self._file_operation_service,
            clipboard_service=self._clipboard_service,
            undo_service=self._undo_service,
            content_list_model=self._content_list_model,
            tree_view=self._tree_view,
            tree_model=self._tree_model,
            tree_service=self._tree_service,
            content_service=self._content_service,
            managed_root_service=self._service,
            assembly_panel=self._assembly_panel,
            strip_service=self._strip_service,
            transaction_scope=self._transaction_scope,
            status_bar=self.statusBar(),
            refresh_tree=self._refresh_tree,
            refresh_middle_current=self._refresh_content_list_for_current_mode,
            refresh_middle=self._refresh_content_list,
            refresh_assembly_if_affected=self._refresh_assembly_if_affected,
            get_selected_entries=self._get_selected_entries,
            current_displayed_dir=self._current_displayed_dir,
            current_nav_path=lambda: self._current_nav_path,
            handle_error=self._handle_service_error,
            dialog_parent=self,
            host=self,
            archive_settings=self._archive_settings,
            archive_manifest_service=self._archive_manifest_service,
            parent=self,
        )
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
        # TD-M21 阶段 7：中栏内容列表控制器（刷新/选中联动/筛选/条目级动作）
        self._content_list_controller = ContentListController(
            content_service=self._content_service,
            content_unit_creation_service=self._content_unit_creation_service,
            tag_service=self._tag_service,
            content_list_model=self._content_list_model,
            card_list_model=self._card_list_model,
            content_view=self._content_view,
            card_view=self._card_view,
            content_empty_hint=self._content_empty_hint,
            cover_filter_button=self._cover_filter_button,
            tag_filter_bar=self._tag_filter_bar,
            tree_model=self._tree_model,
            tree_view=self._tree_view,
            metadata_panel=self._metadata_panel,
            metadata_label=self._metadata_label,
            metadata_view=self._metadata_view,
            selection_memory=self._selection_memory,
            transaction_scope=self._transaction_scope,
            status_bar=self.statusBar(),
            set_metadata_text=self._set_metadata_text,
            update_metadata=self._update_metadata,
            bind_assembly_panel=self._bind_assembly_panel,
            bind_assembly_folder=self._bind_assembly_folder,
            is_assembly_pinned=self._is_assembly_pinned,
            current_nav_path=lambda: self._current_nav_path,
            navigating_from_history=lambda: self._navigating_from_history,
            current_view_index=lambda: self._current_view_index,
            record_nav_history=self._record_nav_history,
            handle_error=self._handle_service_error,
            dialog_parent=self,
            host=self,
            parent=self,
        )
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
        # UI合理性5：列表视图封面图标 provider（只读复用现有缓存，不产生新缓存）
        self._content_list_model.set_cover_icon_provider(self._list_cover_icon_provider)

    # --- TD-M21 阶段 2：导航/视图状态镜像属性（测试兼容，状态归控制器） ---

    @property
    def _nav_back_stack(self) -> list[str]:
        """后退栈（NavigationController 持有的同一列表对象，供测试读取）。"""
        return self._navigation_controller.back_stack()

    @property
    def _nav_forward_stack(self) -> list[str]:
        """前进栈（NavigationController 持有的同一列表对象，供测试读取）。"""
        return self._navigation_controller.forward_stack()

    @property
    def _current_nav_path(self) -> str | None:
        """当前浏览目录路径（状态归 NavigationController）。"""
        return self._navigation_controller.current_path()

    @property
    def _navigating_from_history(self) -> bool:
        """历史导航切换标记（状态归 NavigationController）。"""
        return self._navigation_controller.is_navigating_from_history()

    @property
    def _current_view_index(self) -> int:
        """当前活动视图索引（0=列表，1=卡片，状态归 ViewStateController）。"""
        return self._view_state_controller.current_view_index()

    @property
    def _card_icon_size(self) -> int:
        """当前卡片图标尺寸（状态归 ViewStateController）。"""
        return self._view_state_controller.card_icon_size()

    def _list_cover_icon_provider(self, content_unit_id: str, source_path: str) -> QIcon | None:
        """列表视图封面图标：只读复用 256 档封面缓存，缩放到 64×64（UI合理性5）。"""
        if self._thumbnail_coordinator is None:
            return None
        return self._thumbnail_coordinator.get_cover_icon(content_unit_id, Path(source_path))

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
        top_bar = self._build_top_bar()

        # === 三栏 Splitter（UI合理性2：尺寸保存/恢复由 SplitterStateHelper 管理） ===
        self._splitter = QSplitter(Qt.Horizontal, self)
        splitter = self._splitter
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_middle_panel())
        splitter.addWidget(self._build_right_panel())

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
        self._menu_bar.settings_requested.connect(self._on_settings_clicked)
        self._menu_bar.marker_config_requested.connect(self._on_marker_config_clicked)
        self._menu_bar.url_settings_requested.connect(self._on_url_settings_clicked)
        self._menu_bar.tag_manager_requested.connect(self._on_tag_manager_clicked)
        self._menu_bar.operation_history_requested.connect(self._on_operation_history_clicked)
        self._menu_bar.asset_credits_requested.connect(self._on_asset_credits_clicked)
        self._menu_bar.file_type_icon_colors_requested.connect(
            self._on_file_type_icon_colors_clicked
        )
        # 工具菜单项按注入服务开关（与工具栏按钮可见性一致）
        self._menu_bar.set_tag_manager_visible(self._tag_service is not None)
        self._menu_bar.set_operation_history_visible(self._undo_service is not None)
        self.setMenuBar(self._menu_bar)

        # UX 重构 Phase 2 Task 5（Q7=A）：状态栏统一到 QStatusBar
        self._setup_status_bar()

    def _build_top_bar(self) -> QWidget:
        """构建顶部工具栏（搜索框 + 标签管理按钮 + 操作历史按钮）。"""
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
        return top_bar

    def _build_left_panel(self) -> QWidget:
        """构建左栏（受管理根目录 + 扫描控制 + 目录树 + 详情）。"""
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
        self._tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # 功能增加1（2026-08-04）：归档根目录在目录树中显示标记（图标 + 〔归档〕后缀）
        self._tree_model = FolderTreeModel(
            self._tree_service,
            is_archive_root=self._archive_settings.is_root,
        )
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
        return left

    def _build_middle_panel(self) -> QWidget:
        """构建中栏（视图切换/排序/缩放 + 标签筛选 + 文件列表）。"""
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

        # 排序下拉框：字段 + 升降序项（Stage 5 Task 2，Q2=A 列表/卡片视图共享；
        # BugFix3 后升降序并入下拉框，不再有独立按钮）
        sort_label = QLabel(ui.SORT_FIELD_LABEL)
        view_switch_layout.addWidget(sort_label)
        self._sort_field_combo = PressSelectComboBox()
        self._sort_field_combo.addItem(ui.SORT_FIELD_NAME, SORT_NAME)
        self._sort_field_combo.addItem(ui.SORT_FIELD_TYPE, SORT_TYPE)
        self._sort_field_combo.addItem(ui.SORT_FIELD_SIZE, SORT_SIZE)
        self._sort_field_combo.addItem(ui.SORT_FIELD_MODIFIED, SORT_MODIFIED)
        # BugFix3（2026-08-04）：下拉框内置升降序项（资源管理器式）
        self._sort_field_combo.insertSeparator(self._sort_field_combo.count())
        self._sort_field_combo.addItem(ui.SORT_DIRECTION_ASC_LABEL, SORT_DIRECTION_ASC)
        self._sort_field_combo.addItem(ui.SORT_DIRECTION_DESC_LABEL, SORT_DIRECTION_DESC)
        self._sort_field_combo.setToolTip(ui.SORT_FIELD_TOOLTIP)
        self._sort_field_combo.setFixedWidth(90)
        # Stage 5 Task 2 验收修复：取消 popup 当前项的蓝色高亮背景，
        # 避免"当前选中项"在视觉上误导用户以为需要先取消高亮才能选择。
        # hover 仍保留浅色提示，selected 改为透明（与未选中视觉一致）。
        self._sort_field_combo.setStyleSheet(
            "QComboBox::item:selected { background: transparent; color: black; }"
            "QComboBox::item:hover { background: #e0e0e0; }"
        )
        # BugFix3（2026-08-04）：改用 PressSelectComboBox 的 userSelected 信号。
        # - 鼠标在弹窗项上按下即应用排序，微量位移不再导致 release 丢 activated
        #   （表现为"点一次不生效、要点两次"）；
        # - 键盘路径（无鼠标 press）仍由 activated 转发，程序化 setCurrentIndex
        #   不触发（避免 _sync_sort_controls 同步时死循环）；
        # - 去重标志在控件内部维护，"选当前项重新排序"无产品意义，不予支持。
        self._sort_field_combo.userSelected.connect(self._on_sort_field_activated)
        self._sort_field_combo.directionRequested.connect(self._on_sort_direction_requested)
        view_switch_layout.addWidget(self._sort_field_combo)

        # 缩放下拉框（Task 1b 修正：滑块改为预选尺寸下拉框，避免拖动频繁重绘原图）
        zoom_label = QLabel(ui.ZOOM_SLIDER_LABEL)
        view_switch_layout.addWidget(zoom_label)
        self._zoom_combo = PressSelectComboBox()
        # UI合理性19（2026-08-04）：档位由 ViewStateController 按当前视图
        # （列表/卡片各自独立）在 restore_state / switch_view 时重灌
        self._zoom_combo.setToolTip(ui.ZOOM_SLIDER_TOOLTIP)
        self._zoom_combo.setFixedWidth(80)
        # BugFix3 同款方案（2026-08-04）：按下即选中，快速滑动不再"点一次不生效"
        self._zoom_combo.userSelected.connect(self._on_zoom_combo_user_selected)
        view_switch_layout.addWidget(self._zoom_combo)

        # 封面筛选（操作便捷性5，2026-08-03）：切换按钮，按下=只看有封面，不持久化
        self._cover_filter_button = QPushButton(ui.COVER_FILTER_BUTTON)
        self._cover_filter_button.setCheckable(True)
        self._cover_filter_button.setToolTip(ui.COVER_FILTER_TOOLTIP)
        self._cover_filter_button.toggled.connect(self._on_cover_filter_toggled)
        view_switch_layout.addWidget(self._cover_filter_button)

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
            self._tag_filter_bar.on_exclusion_changed.connect(self._on_tag_exclusion_changed)
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
        # UI合理性13/21（2026-08-04）：内容单元行左侧色条 + 行首徽章
        # （名称列专用 delegate，按配置绘制预留区内容，其余渲染交给基类）
        self._content_view.setItemDelegateForColumn(
            COL_NAME, ContentUnitStripeDelegate(self._content_view, config=self._marker_config)
        )
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
        return middle

    def _build_right_panel(self) -> QWidget:
        """构建右栏（元数据面板（上）+ 装配面板（下））。"""
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
                shortcut_config=self._shortcut_config,
            )
            self._right_splitter.addWidget(self._assembly_panel)
            # 初始比例与持久化由 SplitterStateHelper 恢复（默认值见 ui_constants）
            self._right_splitter.setStretchFactor(0, 5)
            self._right_splitter.setStretchFactor(1, 1)
        else:
            self._assembly_panel = None  # type: ignore[assignment]

        right_layout.addWidget(self._right_splitter)
        return right

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
        """从服务重新加载根目录列表（委托 TreeRootsController）。"""
        self._tree_roots_controller.refresh_root_list()

    def _selected_root_id(self) -> str | None:
        """返回当前选中根目录 ID（委托 TreeRootsController）。"""
        return self._tree_roots_controller.selected_root_id()

    def _on_selection_changed(self) -> None:
        """根目录选中变化（委托 TreeRootsController）。"""
        self._tree_roots_controller.on_selection_changed()

    # --- 目录树 ---

    def _refresh_tree(self) -> None:
        """刷新目录树模型（委托 TreeRootsController）。"""
        self._tree_roots_controller.refresh_tree()

    def _on_tree_selection_changed(self, *args) -> None:  # noqa: ANN001 (Qt 信号)
        """目录树选中变化时更新详情区与文件列表（委托 TreeRootsController）。"""
        self._tree_roots_controller.on_tree_selection_changed(*args)

    def _refresh_content_list(self, dir_path: str) -> None:
        """刷新文件列表（委托 ContentListController）。"""
        self._content_list_controller.refresh_content_list(dir_path)

    # --- 标签筛选（Stage 4 Task 3） ---

    def _is_tag_filter_active(self) -> bool:
        """返回 TagFilterBar 是否激活（委托 ContentListController）。"""
        return self._content_list_controller.is_tag_filter_active()

    def _apply_tag_filter(self, entries: list) -> list:
        """按标签/封面筛选过滤条目（委托 ContentListController）。"""
        return self._content_list_controller.apply_tag_filter(entries)

    def _on_cover_filter_toggled(self, _checked: bool) -> None:
        """封面筛选切换（委托 ContentListController）。"""
        self._content_list_controller.on_cover_filter_toggled(_checked)

    def _on_tag_exclusion_changed(self, _excluded_tag_ids: set) -> None:
        """TagFilterBar 反选标签变化（委托 ContentListController）。"""
        self._content_list_controller.on_tag_exclusion_changed(_excluded_tag_ids)

    def _refresh_filters_current_dir(self) -> None:
        """刷新当前显示目录（委托 ContentListController）。"""
        self._content_list_controller.refresh_filters_current_dir()

    def _on_tag_filter_changed(self, selected_tag_ids: set[str]) -> None:
        """TagFilterBar 选中标签变化时重新刷新中栏（委托 ContentListController）。"""
        self._content_list_controller.on_tag_filter_changed(selected_tag_ids)

    def _refresh_tag_filter_bar(self) -> None:
        """刷新 TagFilterBar 的可选标签（委托 ContentListController）。"""
        self._content_list_controller.refresh_tag_filter_bar()

    # --- 文件条目 ---

    def _on_entry_activated(self, index) -> None:  # noqa: ANN001 (Qt 信号)
        """双击文件条目（委托 ContentListController）。"""
        self._content_list_controller.on_entry_activated(index)

    def _on_entry_activated_for_entry(self, entry: FileEntry) -> None:
        """右键菜单「打开」项 handler（委托 ContentListController）。"""
        self._content_list_controller.on_entry_activated_for_entry(entry)

    def _on_content_selection_changed(self, *args) -> None:  # noqa: N802, ANN001 (Qt 信号)
        """文件列表选中变化（委托 ContentListController）。"""
        self._content_list_controller.on_content_selection_changed(*args)

    def _on_content_header_clicked(self, column: int) -> None:  # noqa: N802 (Qt 命名)
        """文件列表列头点击：切换排序键，同列再点切换升降序（委托 ViewStateController）。"""
        self._view_state_controller.on_content_header_clicked(column)

    # --- Stage 5 Task 2：排序下拉框 ---

    def _on_sort_field_activated(self, combo_index: int) -> None:
        """排序字段下拉框用户选择信号（委托 ViewStateController）。"""
        self._view_state_controller.on_sort_field_activated(combo_index)

    def _on_sort_direction_requested(self, ascending: bool) -> None:
        """下拉框内升降序项选择（BugFix3，委托 ViewStateController）。"""
        self._view_state_controller.on_sort_direction_requested(ascending)

    def _sync_sort_controls(self) -> None:
        """同步排序下拉框（委托 ViewStateController）。"""
        self._view_state_controller.sync_sort_controls()

    # --- Stage 5 Task 2：前进/后退目录导航 ---

    def _on_nav_back_clicked(self) -> None:
        """后退按钮：切换到上一个浏览目录（委托 NavigationController）。"""
        self._navigation_controller.navigate_back()

    def _on_nav_forward_clicked(self) -> None:
        """前进按钮：切换到下一个浏览目录（委托 NavigationController）。"""
        self._navigation_controller.navigate_forward()

    def _navigate_to_directory(self, dir_path: str) -> None:
        """切换到指定目录（委托 NavigationController）。"""
        self._navigation_controller.navigate_to(dir_path)

    # === Stage 5 Task 7：全局搜索 ===

    def _on_search_triggered(self) -> None:
        """搜索框回车触发（委托 SearchController）。"""
        self._search_controller.on_triggered()

    def _on_search_result_clicked(self, unit_id: str) -> None:
        """搜索结果双击跳转回调（委托 SearchController）。"""
        self._search_controller.on_result_clicked(unit_id)

    def _content_view_current(self) -> QAbstractItemView | None:
        """返回当前激活的内容视图（列表或卡片，委托 ViewStateController）。"""
        return self._view_state_controller.content_view_current()

    def _record_nav_history(self, dir_path: str) -> None:
        """记录浏览历史（委托 NavigationController）。"""
        self._navigation_controller.record(dir_path)

    def _update_nav_buttons(self) -> None:
        """根据栈状态更新前进/后退按钮可用性（委托 NavigationController）。"""
        self._navigation_controller.update_buttons()

    # --- Stage 5 Task 1：视图切换 + 缩放 ---

    def _switch_view(self, view_index: int) -> None:
        """切换文件列表视图（列表 ↔ 卡片，委托 ViewStateController）。"""
        self._view_state_controller.switch_view(view_index)

    def _on_zoom_combo_user_selected(self, index: int) -> None:
        """缩放下拉框用户选择：按下即应用并同步显示（委托 ViewStateController）。"""
        self._view_state_controller.on_zoom_user_selected(index)

    def _apply_zoom(self, value: int) -> None:
        """应用缩放值：调整卡片图标尺寸并持久化（委托 ViewStateController）。"""
        self._view_state_controller.apply_zoom(value)

    def _restore_view_state(self) -> None:
        """从 QSettings 恢复缩放值与视图模式（委托 ViewStateController）。"""
        self._view_state_controller.restore_state()

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

    def _on_marker_config_clicked(self) -> None:
        """UI合理性21：菜单「内容单元标记设置…」→ 配置对话框，确定后保存并重绘。"""
        dialog = ContentUnitMarkerDialog(self._marker_config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_config = dialog.resulting_config()
        new_config.save(self._qsettings)
        self._marker_config = new_config
        delegate = self._content_view.itemDelegateForColumn(COL_NAME)
        if isinstance(delegate, ContentUnitStripeDelegate):
            delegate.set_config(new_config)
        self._content_view.viewport().update()

    def _on_url_settings_clicked(self) -> None:
        """操作便捷性8/9：菜单「网址与搜索设置…」→ 配置对话框，确定后保存。"""
        current = UrlSettingsConfig.load(self._qsettings)
        dialog = UrlSettingsDialog(current, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        dialog.resulting_config().save(self._qsettings)

    def _on_settings_clicked(self) -> None:
        """设计合理性1：菜单「工具 → 设置…」→ 保存并立即生效。"""
        dialog = SettingsDialog(self._feature_toggle_config, self._shortcut_config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._feature_toggle_config = dialog.resulting_feature_config()
        self._feature_toggle_config.save(self._qsettings)
        self._shortcut_config = dialog.resulting_shortcut_config()
        self._shortcut_config.save(self._qsettings)
        # 快捷键立即重注册：中栏/目录树由 ShortcutRegistry，文件夹预览由面板重装
        self._setup_shortcuts()
        if self._assembly_panel is not None:
            self._assembly_panel.reload_shortcuts(self._shortcut_config)
        self.statusBar().showMessage(ui.SETTINGS_APPLIED, 3000)

    def _on_asset_credits_clicked(self) -> None:
        """UI合理性4 资产引用：菜单「帮助 → 开源资产致谢…」打开致谢对话框。"""
        AssetCreditsDialog(self).exec()

    def _on_file_type_icon_colors_clicked(self) -> None:
        """UI合理性4 二期：菜单「视图 → 文件类型图标颜色…」→ 保存并应用。"""
        current = file_type_icon_colors.load_colors(self._qsettings)
        dialog = FileTypeIconColorsDialog(current, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        colors = dialog.resulting_colors()
        file_type_icon_colors.save_colors(self._qsettings, colors)
        # 应用：注入新颜色（内部清空图标缓存）→ 重绘各视图图标
        file_type_icons.set_type_colors(colors)
        self._content_view.viewport().update()
        self._card_list_model.invalidate_icons()
        self._assembly_panel.refresh_icons()

    def _on_menu_view_switch(self, mode: str) -> None:
        """UI合理性3：菜单视图切换（委托 ViewStateController）。"""
        self._view_state_controller.menu_view_switch(mode)

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
        """目录树右键菜单（委托 ContextMenuBuilder）。"""
        self._context_menu_builder.show_tree_menu(pos)

    def _collapse_all_tree(self) -> None:
        """折叠目录树所有展开的节点（委托 TreeRootsController）。"""
        self._tree_roots_controller.collapse_all()

    def _on_content_context_menu(self, pos: QPoint) -> None:  # noqa: N802 (Qt 命名)
        """文件列表右键菜单（委托 ContextMenuBuilder）。"""
        self._context_menu_builder.show_content_menu(pos)

    def _show_empty_area_context_menu(self, active_view, pos: QPoint) -> None:
        """空白区域右键菜单（委托 ContextMenuBuilder）。"""
        self._context_menu_builder.show_empty_area_menu(active_view, pos)

    def _build_content_menu_actions(
        self, entries: list[FileEntry]
    ) -> list[tuple[str, Callable[[], None], bool]]:
        """构造文件列表右键菜单 actions（委托 ContextMenuBuilder，供测试）。"""
        return self._context_menu_builder.build_content_actions(entries)

    def _copy_path_to_clipboard(self, path: str) -> None:
        """复制路径到剪贴板。"""
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(path)
        self.statusBar().showMessage(ui.CONTEXT_MENU_COPY_PATH_OK, 3000)

    def _on_autofill_url(self, entry: FileEntry) -> None:
        """右键「自动填入网址」（委托 ContentListController）。"""
        self._content_list_controller.on_autofill_url(entry)

    def _on_open_url(self, entry: FileEntry) -> None:
        """右键「打开网址」（委托 ContentListController）。"""
        self._content_list_controller.on_open_url(entry)

    def _on_browser_search(self, entry: FileEntry) -> None:
        """右键「浏览器搜索」（委托 ContentListController）。"""
        self._content_list_controller.on_browser_search(entry)

    def _on_create_mod_group(self, entries: list[FileEntry]) -> None:
        """创建 Mod 组（委托 ContentListController）。"""
        self._content_list_controller.on_create_mod_group(entries)

    def _show_create_mod_group_dialog(self, pure_name: str, full_name: str) -> str | None:
        """弹出创建 Mod 组对话框（委托 entry_dialogs.show_create_mod_group_dialog）。"""
        return show_create_mod_group_dialog(self, pure_name, full_name)

    def _on_mark_content_unit(self, entry: FileEntry) -> None:
        """标记单个条目为内容单元（委托 ContentListController）。"""
        self._content_list_controller.on_mark_content_unit(entry)

    def _on_unmark_content_unit(self, entry: FileEntry) -> None:
        """取消单个条目的内容单元标记（委托 ContentListController）。"""
        self._content_list_controller.on_unmark_content_unit(entry)

    def _on_batch_mark_content_unit(self, entries: list[FileEntry]) -> None:
        """批量标记多个条目为内容单元（委托 ContentListController）。"""
        self._content_list_controller.on_batch_mark_content_unit(entries)

    def _on_batch_unmark_content_unit(self, entries: list[FileEntry]) -> None:
        """批量取消多个条目的内容单元标记（委托 ContentListController）。"""
        self._content_list_controller.on_batch_unmark_content_unit(entries)

    def _refresh_content_list_for_current_mode(self) -> None:
        """刷新中栏文件列表（委托 ContentListController）。"""
        self._content_list_controller.refresh_content_list_for_current_mode()

    def _current_displayed_dir(self) -> str | None:
        """获取当前中栏显示的目录路径（委托 ContentListController）。"""
        return self._content_list_controller.current_displayed_dir()

    def _refresh_content_list_after_file_op(self, dir_path: str | None) -> None:
        """文件操作后刷新中栏（委托 FileOperationsController）。"""
        self._file_operations_controller.refresh_content_list_after_file_op(dir_path)

    # === Stage 5 Task 3a：文件操作 handler ===

    def _on_new_folder_for_entry(self, entry: FileEntry) -> None:
        """右键条目 → 新建文件夹（委托 FileOperationsController）。"""
        self._file_operations_controller.new_folder_for_entry(entry)

    def _on_new_folder_in_dir(self, dir_path: str) -> None:
        """在指定目录下新建文件夹（委托 FileOperationsController）。"""
        self._file_operations_controller.new_folder_in_dir(dir_path)

    def _show_rename_dialog(self, old_name: str) -> tuple[str, bool]:
        """弹出重命名对话框（委托 entry_dialogs.show_rename_dialog）。"""
        return show_rename_dialog(self, old_name)

    def _rename_entry_core(self, entry: FileEntry, refresh_middle: bool = True) -> bool:
        """重命名核心逻辑（委托 FileOperationsController）。"""
        return self._file_operations_controller.rename_entry_core(entry, refresh_middle)

    def _restore_middle_after_tree_refresh(self, dir_path: str) -> None:
        """_refresh_tree 后恢复中栏显示（委托 FileOperationsController）。"""
        self._file_operations_controller.restore_middle_after_tree_refresh(dir_path)

    def _refresh_assembly_if_affected(self, *affected_dirs: str | Path) -> None:
        """文件操作后，若受影响目录与装配面板当前透视文件夹相同则刷新装配面板。

        修复1（含用户补充）：双击进入被钉住的文件夹内进行任何操作（重命名、删除、
        新建文件夹、粘贴、移动等）都应当同步刷新被钉住的装配面板。
        UX 重构 Task 7 Step 3：委托 AssemblyController。
        """
        self._assembly_controller.refresh_if_affected(*affected_dirs)

    def _on_rename_entry(self, entry: FileEntry) -> None:
        """右键条目 → 重命名（委托 FileOperationsController）。"""
        self._file_operations_controller.rename_entry(entry)

    def _on_delete_entries(self, entries: list[FileEntry], *, refresh_middle: bool = True) -> None:
        """右键条目 → 删除（移至回收站，委托 FileOperationsController）。"""
        self._file_operations_controller.delete_entries(entries, refresh_middle=refresh_middle)

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
        elif action == "move_to_recent":
            # 操作便捷性10（2026-08-04）：装配面板 Ctrl+Q 移动到最近目标
            self._on_assembly_move_to_recent(entries)
        elif action == "delete":
            # 修复：装配面板删除不刷新中栏到被删文件父目录，
            # 避免中栏跳入被钉住的文件夹（保留中栏当前显示目录）
            self._on_delete_entries(entries, refresh_middle=False)
            self._assembly_panel.refresh_current()
        elif action == "copy_path" and len(entries) == 1:
            self._copy_path_to_clipboard(entries[0].path)

    def _on_assembly_move_to_recent(self, entries: list[FileEntry]) -> None:
        """装配面板 Ctrl+Q：选中条目移动到最近目标（操作便捷性10）。"""
        if not entries:
            return
        latest = self._recent_move_targets.latest()
        if latest is None:
            self.statusBar().showMessage(ui.SHORTCUT_MOVE_TO_LATEST_NO_TARGET, 3000)
            return
        src_paths = [Path(e.path) for e in entries]
        self._perform_move_to(src_paths, Path(latest), refresh_assembly=True)

    def _on_tag_manager_clicked(self) -> None:
        """打开标签管理对话框（委托 ContentListController）。"""
        self._content_list_controller.tag_manager_clicked()

    # === Stage 5 Task 6：操作历史与撤销 ===

    def _on_operation_history_clicked(self) -> None:
        """打开操作历史对话框（委托 FileOperationsController）。"""
        self._file_operations_controller.operation_history_clicked()

    def _on_refresh_current(self) -> None:
        """刷新当前目录（委托 ContentListController）。"""
        self._content_list_controller.refresh_current()

    def _on_shortcut_toggle_pin(self) -> None:
        """Ctrl+P：钉住/取消钉住文件夹预览（操作便捷性10，2026-08-04）。"""
        if self._assembly_panel is None:
            return
        if self._assembly_panel.is_pinned():
            self._assembly_panel.unpin()
            # B4：取消钉住后跟随中栏当前选中
            self._on_assembly_pin_changed(False)
            self.statusBar().showMessage(ui.ASSEMBLY_PIN_STATUS_UNPINNED_FOLLOW, 2000)
        else:
            folder = self._assembly_panel.current_folder_path()
            if folder is None:
                return  # 未绑定任何文件夹 → 无操作
            self._assembly_panel.pin()
            self.statusBar().showMessage(
                ui.ASSEMBLY_PIN_STATUS_PINNED.format(name=folder.name), 2000
            )

    # === Stage 5 Task 4：键盘快捷键 ===

    def _get_selected_entries(self) -> list[FileEntry]:
        """获取中栏当前活动视图中选中的条目（委托 ContentListController）。"""
        return self._content_list_controller.get_selected_entries()

    def _setup_shortcuts(self) -> None:
        """注册键盘快捷键（委托 ShortcutRegistry，_shortcut_* 属性挂在窗口上）。"""
        ShortcutRegistry(self, self._shortcut_config).register()

    def _on_shortcut_rename_content(self) -> None:
        """F2：重命名中栏选中条目（委托 FileOperationsController）。"""
        self._file_operations_controller.on_shortcut_rename_content()

    def _on_shortcut_rename_tree(self) -> None:
        """F2：重命名目录树选中节点（委托 FileOperationsController）。"""
        self._file_operations_controller.on_shortcut_rename_tree()

    def _on_shortcut_delete(self) -> None:
        """Delete：删除中栏选中条目（委托 FileOperationsController）。"""
        self._file_operations_controller.on_shortcut_delete()

    def _on_shortcut_select_all(self) -> None:
        """Ctrl+A：全选中栏内容。"""
        self._content_view.selectAll()

    def _on_shortcut_undo(self) -> None:
        """Ctrl+Z：撤销最近一条可撤销操作（委托 FileOperationsController）。"""
        self._file_operations_controller.on_shortcut_undo()

    # === Stage 5 Task 3b：剪贴板快捷键 handler ===

    def _on_shortcut_copy(self) -> None:
        """Ctrl+C：复制中栏选中条目（委托 FileOperationsController）。"""
        self._file_operations_controller.on_shortcut_copy()

    def _on_shortcut_cut(self) -> None:
        """Ctrl+X：剪切中栏选中条目（委托 FileOperationsController）。"""
        self._file_operations_controller.on_shortcut_cut()

    def _on_shortcut_paste(self) -> None:
        """Ctrl+V：粘贴到中栏当前目录（委托 FileOperationsController）。"""
        self._file_operations_controller.on_shortcut_paste()

    def _on_shortcut_copy_tree(self) -> None:
        """Ctrl+C：复制目录树选中节点（委托 FileOperationsController）。"""
        self._file_operations_controller.on_shortcut_copy_tree()

    def _on_shortcut_cut_tree(self) -> None:
        """Ctrl+X：剪切目录树选中节点（委托 FileOperationsController）。"""
        self._file_operations_controller.on_shortcut_cut_tree()

    def _on_shortcut_paste_tree(self) -> None:
        """Ctrl+V：粘贴到目录树选中节点（委托 FileOperationsController）。"""
        self._file_operations_controller.on_shortcut_paste_tree()

    def _on_shortcut_delete_tree(self) -> None:
        """Delete：删除目录树选中节点（委托 FileOperationsController）。"""
        self._file_operations_controller.on_shortcut_delete_tree()

    def _get_selected_tree_node(self):
        """获取目录树当前选中节点（委托 TreeRootsController）。"""
        return self._tree_roots_controller.selected_tree_node()

    def _perform_paste(self, dst_dir: Path) -> None:
        """执行粘贴操作（共享逻辑，委托 FileOperationsController）。"""
        self._file_operations_controller.perform_paste(dst_dir)

    # === Stage 5 Task 5：「移动到……」快捷对话框 ===

    def _on_shortcut_move_to(self) -> None:
        """Ctrl+M 中栏：触发移动到对话框（委托 FileOperationsController）。"""
        self._file_operations_controller.on_shortcut_move_to()

    def _on_shortcut_move_to_latest(self) -> None:
        """Ctrl+Q：移动到最近目标（委托 FileOperationsController）。"""
        self._file_operations_controller.on_shortcut_move_to_latest()

    def _tree_selected_path(self) -> Path | None:
        """返回目录树当前选中节点的路径（委托 TreeRootsController）。"""
        return self._tree_roots_controller.tree_selected_path()

    def _on_shortcut_move_to_tree(self) -> None:
        """Ctrl+M 目录树：触发移动到对话框（委托 FileOperationsController）。"""
        self._file_operations_controller.on_shortcut_move_to_tree()

    def _on_move_to(self, entries: list[FileEntry]) -> None:
        """中栏右键「移动到...」入口（委托 FileOperationsController）。"""
        self._file_operations_controller.on_move_to(entries)

    def _on_move_to_tree(self, node) -> None:
        """目录树右键「移动到...」入口（委托 FileOperationsController）。"""
        self._file_operations_controller.on_move_to_tree(node)

    def _on_move_to_recent(self, src_paths: list[Path], target: str) -> None:
        """执行移动到最近目标（委托 FileOperationsController）。"""
        self._file_operations_controller.on_move_to_recent(src_paths, target)

    def _on_strip_folder(self, entry: FileEntry) -> None:
        """中栏右键「提取内容」入口（委托 FileOperationsController）。"""
        self._file_operations_controller.on_strip_folder(entry)

    # --- 功能增加1（2026-08-04）：归档入口（委托 FileOperationsController） ---

    def _on_shortcut_archive_quick(self) -> None:
        """Ctrl+W：快速归档（目录树/中栏选中项 → 上次归档位置）。"""
        self._file_operations_controller.on_shortcut_archive_quick()

    def _on_archive_quick(self, entries: list[FileEntry]) -> None:
        """中栏右键「快速归档」入口。"""
        self._file_operations_controller.on_archive_quick(entries)

    def _on_archive_to(self, entries: list[FileEntry]) -> None:
        """中栏右键「归档到…」入口。"""
        self._file_operations_controller.on_archive_to(entries)

    def _on_archive_quick_tree(self, node) -> None:
        """目录树右键「快速归档」入口。"""
        self._file_operations_controller.on_archive_quick_tree(node)

    def _on_archive_to_tree(self, node) -> None:
        """目录树右键「归档到…」入口。"""
        self._file_operations_controller.on_archive_to_tree(node)

    def _on_mark_archive_root(self, path: Path) -> None:
        """右键「标记为归档根目录」入口。"""
        self._file_operations_controller.on_mark_archive_root(path)

    def _on_unmark_archive_root(self, path: Path) -> None:
        """右键「取消归档根目录标记」入口。"""
        self._file_operations_controller.on_unmark_archive_root(path)

    def _on_generate_archive_manifest(self, path: Path) -> None:
        """右键「生成归档内容清单」入口。"""
        self._file_operations_controller.on_generate_archive_manifest(path)

    def _insert_recent_move_submenu(self, menu, src_paths: list[Path]) -> None:
        """插入「移动到最近目录」子菜单（委托 ContextMenuBuilder）。"""
        self._context_menu_builder.insert_recent_move_submenu(menu, src_paths)

    def _insert_recent_tag_submenu(self, menu, unit_id: str) -> None:
        """追加「添加最近标签 ▸」子菜单（委托 ContextMenuBuilder）。"""
        self._context_menu_builder.insert_recent_tag_submenu(menu, unit_id)

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
        """打开「移动到...」对话框并处理结果（委托 FileOperationsController）。"""
        self._file_operations_controller.open_move_to_dialog(src_paths, default_expand)

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
        """执行移动到目标目录（委托 FileOperationsController）。"""
        self._file_operations_controller.perform_move_to(
            src_paths,
            target_dir,
            refresh_assembly=refresh_assembly,
            ok_msg=ok_msg,
            fail_title=fail_title,
            partial_msg=partial_msg,
        )

    def _update_metadata(self, unit: ContentUnit) -> None:
        """更新元数据面板。

        Stage 4 Task 2：若有 MetadataPanel，加载到编辑表单；同时保留
        `_metadata_full_text` 多行文本格式以兼容现有测试（metadata_full_text()）。

        Stage 5 Task 7 收尾：移除"整理状态"显示行。v13（UX 重构 Task 6）纯 DELETE
        模式下记录存在即已标记，能进入此方法的状态恒为已标记，显示无意义。
        """
        # 兼容旧测试：缓存多行文本（metadata_full_text()）
        self._metadata_full_text = format_metadata_lines(unit, self._service)
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
        """元数据面板重命名栏回车（委托 FileOperationsController）。"""
        self._file_operations_controller.metadata_rename_requested(unit_id, new_name)

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
        """对详情区、元数据面板的路径行应用 ElideMiddle（委托 metadata_helpers）。"""
        elide_label_lines(self._detail_label, self._detail_full_text)
        elide_label_lines(self._metadata_label, self._metadata_full_text)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """窗口尺寸变化时重新 Elide。"""
        super().resizeEvent(event)
        self._apply_elide()

    # --- 添加根目录 ---

    def _on_add_root(self) -> None:
        """打开目录选择对话框，添加受管理根目录（委托 TreeRootsController）。"""
        self._tree_roots_controller.on_add_root()

    # --- 移除根目录配置 ---

    def _on_remove_root(self) -> None:
        """移除选中的受管理根目录配置（委托 TreeRootsController）。"""
        self._tree_roots_controller.on_remove_root()

    # --- 扫描 ---

    def _on_scan(self, incremental: bool = True) -> None:
        """启动后台扫描（委托 ScanUiState）。"""
        self._scan_ui_state.on_scan(incremental)

    def _begin_scanning(self) -> None:
        """扫描开始（委托 ScanUiState）。"""
        self._scan_ui_state.begin()

    def _end_scanning(self) -> None:
        """恢复按钮状态（委托 ScanUiState）。"""
        self._scan_ui_state.end()

    def _on_scan_started(self) -> None:
        """扫描开始信号（委托 ScanUiState）。"""
        self._scan_ui_state.on_started()

    def _on_scan_progress(self, text: str) -> None:
        """扫描进度文本（委托 ScanUiState）。"""
        self._scan_ui_state.on_progress(text)

    def _on_scan_finished(self, summary: ScanSummary) -> None:
        """扫描完成（委托 ScanUiState）。"""
        self._scan_ui_state.on_finished(summary)

    def _refresh_content_list_after_scan(self) -> None:
        """扫描完成后刷新中栏文件列表（委托 ScanUiState）。"""
        self._scan_ui_state.refresh_content_list_after_scan()

    def _on_scan_failed(self, message: str) -> None:
        """扫描失败（委托 ScanUiState）。"""
        self._scan_ui_state.on_failed(message)

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

    def list_icon_size(self) -> int:
        """返回当前列表图标尺寸（UI合理性19，供测试）。"""
        return self._view_state_controller.list_icon_size()

    def zoom_combo_value(self) -> int:
        """返回缩放下拉框当前值（当前视图档位，供测试）。"""
        return self._zoom_combo.currentData()

    def set_card_icon_size_for_test(self, size: int) -> None:
        """测试辅助：直接设置卡片图标尺寸（不依赖当前视图/下拉框档位）。"""
        self._view_state_controller.set_view_icon_size(VIEW_INDEX_CARD, size)

    def set_list_icon_size_for_test(self, size: int) -> None:
        """测试辅助：直接设置列表图标尺寸（UI合理性19，不依赖当前视图）。"""
        self._view_state_controller.set_view_icon_size(VIEW_INDEX_LIST, size)

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
