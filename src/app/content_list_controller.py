"""中栏内容列表控制器（MainWindow 第二轮拆分，TD-M21 阶段 7）。

封装中栏文件列表的刷新 / 双击进入 / 单击选中 → 元数据与装配面板联动 /
标签与封面筛选，以及条目级内容单元动作（创建 Mod 组 / 标记 / 批量标记 /
快速设置封面）。MainWindow 保留同名薄委托与信号接线。
"""

from __future__ import annotations

import logging
import subprocess
import webbrowser
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlencode

from PySide6.QtCore import QObject, QSettings
from PySide6.QtWidgets import QLabel, QMessageBox, QStatusBar

from app import ui_constants as ui
from app.card_list_model import CardListModel
from app.content_filter import filter_entries
from app.content_views import _DragDropListView, _RubberBandTableView
from app.file_list_model import FileListModel
from app.folder_tree_model import FolderTreeModel
from app.metadata_panel import MetadataPanel
from app.metadata_view import MetadataView
from app.selection_memory import SelectionMemory
from app.tag_filter import TagFilterBar
from app.tag_manager_dialog import TagManagerDialog
from app.transaction_scope import TransactionScope
from app.url_settings import UrlSettingsConfig
from application.content_service import ContentService
from application.content_unit_creation_service import ContentUnitCreationService
from application.nexus_filename import build_nexus_url, mod_search_query
from application.tag_service import TagService
from domain.models import ContentUnit, FileEntry

logger = logging.getLogger(__name__)

# 视图索引（QStackedWidget，与 view_state_controller 一致）
VIEW_INDEX_LIST = 0
VIEW_INDEX_CARD = 1


class ContentListController(QObject):
    """中栏内容列表刷新 / 选中联动 / 筛选 / 条目级动作控制器。"""

    def __init__(
        self,
        content_service: ContentService,
        content_unit_creation_service: ContentUnitCreationService | None,
        tag_service: TagService | None,
        content_list_model: FileListModel,
        card_list_model: CardListModel,
        content_view: _RubberBandTableView,
        card_view: _DragDropListView,
        content_empty_hint: QLabel,
        cover_filter_button,
        tag_filter_bar: TagFilterBar | None,
        tree_model: FolderTreeModel,
        tree_view,
        metadata_panel: MetadataPanel | None,
        metadata_label: QLabel,
        metadata_view: MetadataView | None,
        selection_memory: SelectionMemory,
        transaction_scope: TransactionScope,
        status_bar: QStatusBar,
        *,
        set_metadata_text: Callable[[str], None],
        update_metadata: Callable[[ContentUnit], None],
        bind_assembly_panel: Callable[[ContentUnit | None], None],
        bind_assembly_folder: Callable[[Path], None],
        is_assembly_pinned: Callable[[], bool],
        current_nav_path: Callable[[], str | None],
        navigating_from_history: Callable[[], bool],
        current_view_index: Callable[[], int],
        record_nav_history: Callable[[str], None],
        handle_error: Callable[..., None],
        dialog_parent,
        host: object,
        parent: QObject | None = None,
    ) -> None:
        """初始化中栏内容列表控制器。

        Args:
            host: 运行时状态宿主（MainWindow）——创建 Mod 组对话框经 host 读取，
            兼容测试对 ``window._show_create_mod_group_dialog`` 的实例替换。
        """
        super().__init__(parent)
        self._content_service = content_service
        self._content_unit_creation_service = content_unit_creation_service
        self._tag_service = tag_service
        self._content_list_model = content_list_model
        self._card_list_model = card_list_model
        self._content_view = content_view
        self._card_view = card_view
        self._content_empty_hint = content_empty_hint
        self._cover_filter_button = cover_filter_button
        self._tag_filter_bar = tag_filter_bar
        self._tree_model = tree_model
        self._tree_view = tree_view
        self._metadata_panel = metadata_panel
        self._metadata_label = metadata_label
        self._metadata_view = metadata_view
        self._selection_memory = selection_memory
        self._tx = transaction_scope
        self._status_bar = status_bar
        self._set_metadata_text = set_metadata_text
        self._update_metadata = update_metadata
        self._bind_assembly_panel = bind_assembly_panel
        self._bind_assembly_folder = bind_assembly_folder
        self._is_assembly_pinned = is_assembly_pinned
        self._current_nav_path = current_nav_path
        self._navigating_from_history = navigating_from_history
        self._current_view_index = current_view_index
        self._record_nav_history = record_nav_history
        self._handle_error = handle_error
        self._dialog_parent = dialog_parent
        self._host = host

    # --- 中栏刷新 ---

    def refresh_content_list(self, dir_path: str) -> None:
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

        entries = self.apply_tag_filter(entries)
        self._content_list_model.refresh(entries)
        if not entries:
            if self.is_tag_filter_active() or self._cover_filter_button.isChecked():
                self._content_empty_hint.setText(ui.TAG_FILTER_NO_RESULT_HINT)
            else:
                self._content_empty_hint.setText(ui.CONTENT_LIST_EMPTY_HINT)
        else:
            self._content_empty_hint.setText("")
        # 操作便捷性7：历史导航（后退/前进）恢复该目录记忆的选中
        if self._navigating_from_history():
            active_view = (
                self._card_view
                if self._current_view_index() == VIEW_INDEX_CARD
                else self._content_view
            )
            self._selection_memory.restore(dir_path, self._content_list_model, active_view)
        # Stage 5 Task 2：记录目录导航历史
        self._record_nav_history(dir_path)

    def refresh_content_list_for_current_mode(self) -> None:
        """刷新中栏文件列表（基于当前目录树选中节点）。

        UX 重构 Phase 1 Task 1：移除模式分支，统一为原 browse 行为。
        """
        sm = self._tree_view.selectionModel()
        if sm is None:
            return
        indexes = sm.selectedIndexes()
        if not indexes:
            return
        node = self._tree_model.node_at(indexes[0])
        if node is not None:
            self.refresh_content_list(node.real_path)

    def current_displayed_dir(self) -> str | None:
        """获取当前中栏显示的目录路径（Stage 5 Task 3a）。"""
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

    # --- 标签 / 封面筛选（Stage 4 Task 3） ---

    def is_tag_filter_active(self) -> bool:
        """返回 TagFilterBar 是否激活（已选标签数 > 0）。

        TagService 未注入时返回 False。
        """
        return self._tag_filter_bar is not None and self._tag_filter_bar.is_filter_active()

    def apply_tag_filter(self, entries: list) -> list:
        """按标签/封面筛选过滤条目（委托 ContentFilter）。"""
        if self._tag_filter_bar is None:
            return filter_entries(
                entries,
                tag_service=self._tag_service,
                selected_tag_ids=set(),
                excluded_tag_ids=set(),
                cover_only=self._cover_filter_button.isChecked(),
            )
        return filter_entries(
            entries,
            tag_service=self._tag_service,
            selected_tag_ids=self._tag_filter_bar.current_selected_tag_ids(),
            excluded_tag_ids=self._tag_filter_bar.current_excluded_tag_ids(),
            cover_only=self._cover_filter_button.isChecked(),
        )

    def on_cover_filter_toggled(self, _checked: bool) -> None:
        """封面筛选切换：按下=只看有封面；不持久化。"""
        self.refresh_filters_current_dir()

    def on_tag_exclusion_changed(self, _excluded_tag_ids: set) -> None:
        """TagFilterBar 反选标签变化 → 重新刷新中栏（应用排除筛选）。"""
        self.refresh_filters_current_dir()

    def refresh_filters_current_dir(self) -> None:
        """刷新当前显示目录（标签/封面筛选变化时；优先当前导航目录，回退目录树选中）。"""
        if self._current_nav_path() is not None:
            self.refresh_content_list(self._current_nav_path())
        else:
            self.refresh_content_list_for_current_mode()

    def on_tag_filter_changed(self, selected_tag_ids: set[str]) -> None:
        """TagFilterBar 选中标签变化时重新刷新中栏（应用筛选）。

        Stage 4 Task 3（Q6: A 修正）：筛选激活时保留 MetadataPanel 可见性，
        用户可继续查看选中条目的元数据。若当前选中行被筛选过滤掉，
        MetadataPanel 保持上一次加载的内容（不主动清空），避免干扰用户。
        - 仅中栏可见时响应（TagFilterBar 常驻中栏顶部）。
        """
        self.refresh_filters_current_dir()

    def refresh_tag_filter_bar(self) -> None:
        """刷新 TagFilterBar 的可选标签（标签管理对话框关闭后调用）。"""
        if self._tag_filter_bar is not None:
            self._tag_filter_bar.refresh_categories()

    def refresh_current(self) -> None:
        """刷新当前目录（UX 重构 Phase 2 Task 5，Q5=B + Q6=A）。

        - 仅刷新中栏当前显示的目录 + 目录树对应节点，不触发全量扫描
        - 若受影响目录与装配面板钉住文件夹相同，同步刷新装配面板（Q6=A）
        - 外部修改文件后 F5 能看到变化

        实现说明：FolderTreeService 无单节点刷新接口，使用 _refresh_tree（从 DB 重载
        目录树，不触发扫描）+ _restore_middle_after_tree_refresh 恢复中栏。
        _restore_middle_after_tree_refresh 已含装配面板受影响刷新。
        """
        current_dir = self.current_displayed_dir()
        if current_dir is None:
            self._status_bar.showMessage(ui.REFRESH_NO_DIR, 2000)
            return
        # 刷新目录树（从 DB 重载，不触发扫描）+ 恢复中栏选中 + 同步装配面板
        self._host._refresh_tree()
        self._host._restore_middle_after_tree_refresh(current_dir)
        self._status_bar.showMessage(ui.REFRESH_DONE, 2000)

    def tag_manager_clicked(self) -> None:
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
            commit_callback=self._tx.commit,
            rollback_callback=self._tx.rollback,
            parent=self._dialog_parent,
        )
        dialog.exec()
        # Stage 4 Task 3：标签库可能变更，刷新 TagFilterBar 可选标签。
        # refresh_categories 会自动剔除已删除的已选标签并重新筛选。
        self.refresh_tag_filter_bar()
        # BugFix2 验收反馈：标签库可能变更，刷新元数据面板当前单元的标签显示
        # （refresh_tags 不触碰表单字段，保留未保存的来源/备注编辑）
        if self._metadata_panel is not None:
            self._metadata_panel.refresh_tags()

    # --- 文件条目交互 ---

    def on_entry_activated(self, index) -> None:  # noqa: ANN001 (Qt 信号)
        """双击文件条目。

        交互行为（2026-08-04 调整，操作合理性1）：
        - 双击文件夹 → 进入该目录（无论是否内容单元，优先于元数据显示）。
          文件夹的元数据通过单击选中查看（on_content_selection_changed）。
        - 双击文件（内容单元或普通文件）→ 用系统默认程序打开
          （压缩包交给解压器、图片交给看图工具，即"快速预览"），
          与右键「打开」行为一致；元数据通过单击选中查看。

        Stage 5 Task 1：支持列表视图和卡片视图，两个视图共享同一份 FileEntry 数据
        （行号一致），因此用任一 model 取 entry 均可。这里用当前活动视图对应的 model。
        """
        # 两个视图共享同一份数据（行号一致），用任一 model 取 entry 均可
        active_model = (
            self._card_list_model
            if self._current_view_index() == VIEW_INDEX_CARD
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
            # 该 selection 的刷新逻辑（refresh_content_list_for_current_mode /
            # refresh_content_list_after_scan）误用陈旧的选中节点，
            # 中栏在标记内容单元后"退回"父目录显示。
            # 通过 find_index_by_path 找到对应节点并 setCurrentIndex，
            # 触发 on_tree_selection_changed 完成中栏刷新 + 详情区更新。
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
                self.refresh_content_list(entry.path)
                self._set_metadata_text(ui.METADATA_NOT_SELECTED)
            return

        # 双击文件 → 系统默认程序打开（操作合理性1，2026-08-04）
        self._open_file_with_default(entry)

    def on_entry_activated_for_entry(self, entry: FileEntry) -> None:
        """右键菜单「打开」项的 handler（UX 重构 Phase 2 Task 5，Q1=B）。

        行为与双击（on_entry_activated）一致：
        - 文件夹 → 进入该目录
        - 文件 → 尝试用系统默认程序打开（操作合理性1：与双击一致）
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
                self.refresh_content_list(entry.path)
                self._set_metadata_text(ui.METADATA_NOT_SELECTED)
            return

        # 文件 → 用系统默认程序打开
        self._open_file_with_default(entry)

    def _open_file_with_default(self, entry: FileEntry) -> None:
        """用系统默认程序打开文件（操作合理性1，2026-08-04）。

        双击与右键「打开」共用；失败提示用户可读错误。
        """
        try:
            subprocess.run(
                ["cmd", "/c", "start", "", entry.path],
                check=False,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):  # noqa: BLE001
            logger.exception("系统打开文件失败：path=%s", entry.path)
            QMessageBox.information(
                self._dialog_parent,
                ui.MENU_OPEN,
                ui.MENU_OPERATION_FAILED.format(error="无法打开文件"),
            )

    def on_content_selection_changed(self, *args) -> None:  # noqa: N802, ANN001 (Qt 信号)
        """文件列表选中变化：单击选中条目 → 右栏同步更新元数据与装配面板。

        UX 重构 Phase 1 Task 2（A1-1 决策）：
        - 单选文件夹内容单元 → 显示元数据 + 绑定装配面板显示其内部文件。
        - 单选文件类型内容单元 → 显示元数据 + 装配面板解绑显空状态。
        - 单选非内容单元 → 清空元数据 + 装配面板解绑显空状态。
        - 多选 → 清空元数据 + 装配面板解绑显空状态（避免混淆）。
        - 双击文件夹 → 进入目录（on_entry_activated 处理，与单击不冲突）。

        信号循环防护（用户补充注意）：
        bind_assembly_panel → bind_mod_group → _refresh_file_list 仅刷新装配面板
        内部模型，不反向修改 content_view 选区，因此 selectionChanged
        不会再次触发本方法。元数据更新同理。

        Stage 5 Task 1：支持列表视图和卡片视图，根据当前活动视图获取选中。
        """
        # 取当前活动视图（列表 or 卡片）
        active_view = (
            self._card_view if self._current_view_index() == VIEW_INDEX_CARD else self._content_view
        )
        active_model = (
            self._card_list_model
            if self._current_view_index() == VIEW_INDEX_CARD
            else self._content_list_model
        )
        sm = active_view.selectionModel()
        if sm is None:
            return
        indexes = sm.selectedRows()
        if not indexes:
            return
        # 操作便捷性7：记忆当前目录的选中（后退/前进时恢复）。
        # 仅在非空选中时记录，避免列表刷新/恢复过程中的空选中事件清空记忆。
        if self._current_nav_path() is not None:
            paths: list[str] = []
            for i in indexes:
                e = active_model.entry_at(i.row())
                if e is not None:
                    paths.append(e.path)
            self._selection_memory.record(self._current_nav_path(), paths)
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
                if self._metadata_view is not None:
                    self._metadata_view.show_image_preview(Path(entry.path))
            else:
                self._set_metadata_text(ui.METADATA_NOT_SELECTED)
            self._bind_assembly_panel(None)

    # --- 选中条目查询 ---

    def get_selected_entries(self) -> list[FileEntry]:
        """获取中栏当前活动视图中选中的条目（列表视图或卡片视图）。"""
        active_view = (
            self._card_view if self._current_view_index() == VIEW_INDEX_CARD else self._content_view
        )
        active_model = (
            self._card_list_model
            if self._current_view_index() == VIEW_INDEX_CARD
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

    # --- 条目级内容单元动作 ---

    # === 操作便捷性8（2026-08-04）：N 网网址自动填入 / 打开 ===

    def on_autofill_url(self, entry: FileEntry) -> None:
        """右键「自动填入网址」：source_url 为空时按规则补填，否则完全静默。"""
        unit = self._get_content_unit(entry)
        if unit is None or unit.source_url:
            return
        # 无法识别 / 写入失败均静默（用户确认 2026-08-04：不报错、不弹窗）
        self._try_fill_nexus_url(unit)

    def on_open_url(self, entry: FileEntry) -> None:
        """右键「打开网址」：URL 为空先尝试自动填入，仍无 URL 则静默不操作。"""
        unit = self._get_content_unit(entry)
        if unit is None:
            return
        url = unit.source_url
        if not url:
            if not self._try_fill_nexus_url(unit):
                return  # 静默
            unit = self._content_service.get_by_id(unit.id)
            if unit is None or not unit.source_url:
                return
            url = unit.source_url
        self._open_url_in_browser(url)

    def _get_content_unit(self, entry: FileEntry) -> ContentUnit | None:
        """按条目关联 ID 查最新内容单元（条目可能已过期）。"""
        if entry.content_unit is None:
            return None
        try:
            return self._content_service.get_by_id(entry.content_unit.id)
        except Exception:  # noqa: BLE001 - UI 边界静默降级
            logger.exception("查询内容单元失败：unit_id=%s", entry.content_unit.id)
            return None

    def _try_fill_nexus_url(self, unit: ContentUnit) -> bool:
        """按规则补填 source_url（文件自身名 / 文件夹内部最小 ID）。

        返回 True 表示已写入；无法识别或失败返回 False（调用方静默跳过，
        绝不允许"前缀+空值"）。
        """
        config = UrlSettingsConfig.load(QSettings())
        url = build_nexus_url(Path(unit.path), config.nexus_url_prefix)
        if url is None:
            return False
        try:
            updated = self._content_service.update_metadata(unit.id, source_url=url)
            self._tx.commit()
        except Exception:  # noqa: BLE001 - 静默降级
            logger.exception("自动填入网址失败：unit_id=%s", unit.id)
            return False
        # 刷新中栏（条目 source_url 变化）+ 元数据面板（若正显示该单元）
        self.refresh_content_list_for_current_mode()
        self._update_metadata(updated)
        return True

    def _open_url_in_browser(self, url: str) -> None:
        """打开外部浏览器；失败仅记日志（保持静默语义）。"""
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - 打开失败不打扰用户
            logger.exception("打开网址失败：%s", url)

    # === 操作便捷性9（2026-08-04）：快速浏览器搜索 ===

    def on_browser_search(self, entry: FileEntry) -> None:
        """右键「浏览器搜索」：前缀 + extract_mod_name(名字)（_/-→空格）。"""
        config = UrlSettingsConfig.load(QSettings())
        query = mod_search_query(entry.name, config.search_prefix)
        if not query:
            return  # 静默
        url = self._build_search_url(config.search_engine_url, query)
        self._open_url_in_browser(url)

    def _build_search_url(self, engine_url: str, query: str) -> str:
        """搜索引擎基础地址 + 查询参数。

        配置存基础地址（不含 ?q=，避免地址栏出现 `?q=q=…`）；
        兼容用户手动输入带 `?q=` / `&q=` 的地址（先剥掉尾随查询参数），
        地址已含其他 ? 参数时用 & 拼接。
        """
        base = engine_url.strip()
        for suffix in ("?q=", "&q="):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        if not base:
            base = engine_url
        sep = "&" if "?" in base else "?"
        return base + sep + urlencode({"q": query})

    def on_create_mod_group(self, entries: list[FileEntry]) -> None:
        """创建 Mod 组：弹出对话框选择/编辑名称，调用 ContentUnitCreationService。

        UX 重构 Phase 1 Task 1 Commit 3：支持多选。
        - E1：仅全部为文件（非目录）时显示菜单项（由菜单构建器保证）
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

        # 弹出对话框（经 host 调用，兼容测试实例替换）
        chosen_name = self._host._show_create_mod_group_dialog(pure_name, full_name)
        if chosen_name is None:
            return  # 用户取消

        source_files = [Path(e.path) for e in entries]
        try:
            result = self._content_unit_creation_service.create_content_unit_from_files(
                source_files,
                staging_path,
                name=chosen_name,
            )
            # D3：ContentUnitCreationService 已注入 UoW，事务由 Service 内部管理，无需 commit
            # 刷新目录树（新文件夹已写入 folder_cache）
            self._host._refresh_tree()
            # 刷新当前目录文件列表
            self.refresh_content_list(str(staging_path))
            # 绑定装配面板到新创建的 Mod 组
            # UX 重构 Phase 1 Task 3（B1）：钉住状态下不自动绑定新 Mod 组
            if not self._is_assembly_pinned():
                self._bind_assembly_panel(result.unit)
            # 状态栏汇总
            if result.failure_count == 0:
                inherited_hint = (
                    ui.CREATE_MOD_GROUP_INHERITED_HINT
                    if (self._has_inherited_metadata(result.unit))
                    else ""
                )
                if result.success_count == 1:
                    self._status_bar.showMessage(
                        ui.CREATE_MOD_GROUP_DEFAULT_OK.format(name=chosen_name) + inherited_hint,
                        3000,
                    )
                else:
                    self._status_bar.showMessage(
                        ui.CREATE_MOD_GROUP_MULTI_OK.format(
                            name=chosen_name, count=result.success_count
                        )
                        + inherited_hint,
                        5000,
                    )
            else:
                self._status_bar.showMessage(
                    ui.CREATE_MOD_GROUP_MULTI_PARTIAL.format(
                        ok=result.success_count, fail=result.failure_count
                    ),
                    5000,
                )
        except Exception as e:  # noqa: BLE001
            self._handle_error(e, ui.CREATE_MOD_GROUP_FAILED, rollback=False)

    def _has_inherited_metadata(self, unit: ContentUnit) -> bool:
        """判断新 Mod 组单元是否继承了来源/备注/标签（操作合理性5）。"""
        if unit.source_url or unit.notes:
            return True
        if self._tag_service is not None:
            try:
                for _category, tags in self._tag_service.list_tags_of_content_unit(unit.id):
                    if tags:
                        return True
            except Exception:  # noqa: BLE001 - 提示性判断失败不影响主流程
                return False
        return False

    def on_mark_content_unit(self, entry: FileEntry) -> None:
        """标记单个条目为内容单元。"""
        try:
            self._content_service.mark_as_content_unit(Path(entry.path))
            # D3：ContentService 已注入 UoW，事务由 Service 内部管理，无需 commit
            self.refresh_content_list_for_current_mode()
            self._status_bar.showMessage(ui.MARK_CONTENT_UNIT_OK, 3000)
        except Exception as e:  # noqa: BLE001
            self._handle_error(e, ui.MARK_CONTENT_UNIT_FAILED, rollback=False)

    def on_unmark_content_unit(self, entry: FileEntry) -> None:
        """取消单个条目的内容单元标记。"""
        if entry.content_unit is None:
            return
        try:
            self._content_service.unmark_content_unit(entry.content_unit.id)
            # unmark_content_unit 是单步写方法，未使用 UoW（仅 mark_as_content_unit
            # 的多步写在 UoW 事务内）。调用方需显式提交。
            self._tx.commit()
            self.refresh_content_list_for_current_mode()
            self._status_bar.showMessage(ui.UNMARK_CONTENT_UNIT_OK, 3000)
        except Exception as e:  # noqa: BLE001
            self._handle_error(e, ui.UNMARK_CONTENT_UNIT_FAILED)

    def on_batch_mark_content_unit(self, entries: list[FileEntry]) -> None:
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
            # D3：ContentService 已注入 UoW，事务由 Service 内部管理，无需 commit
            self.refresh_content_list_for_current_mode()
            self._status_bar.showMessage(
                ui.BATCH_MARK_CONTENT_UNIT_OK.format(count=success_count), 3000
            )
        if failure_count > 0:
            QMessageBox.information(
                self._dialog_parent,
                ui.BATCH_MARK_CONTENT_UNIT_FAILED,
                f"{failure_count} 个文件标记失败，请查看日志。",
            )

    def on_batch_unmark_content_unit(self, entries: list[FileEntry]) -> None:
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
                self._tx.commit()
                success_count += 1
            except Exception:  # noqa: BLE001
                logger.exception("批量取消标记失败：path=%s", entry.path)
                failure_count += 1
                # 单条失败时回滚该条事务（避免未提交残留）
                self._tx.rollback()
        if success_count > 0:
            self.refresh_content_list_for_current_mode()
            self._status_bar.showMessage(
                ui.BATCH_UNMARK_CONTENT_UNIT_OK.format(count=success_count), 3000
            )
        if failure_count > 0:
            QMessageBox.information(
                self._dialog_parent,
                ui.BATCH_UNMARK_CONTENT_UNIT_FAILED,
                f"{failure_count} 个内容单元取消标记失败，请查看日志。",
            )
