"""右键菜单构建器（MainWindow 第二轮拆分，TD-M21 阶段 5）。

封装目录树 / 中栏 / 空白区域三类右键菜单的构建与分发，以及「移动到最近目录」
「添加最近标签」子菜单插入（Stage 5 Task 1/3a/3b + UX 重构 Phase 2 Task 5）。

设计：纯构建 helper，不持有 Qt 信号；服务/控件经构造注入，动作 handler
通过 ``host``（MainWindow，保留同名薄委托）回调，菜单行为不变。
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QAbstractItemView, QMenu, QWidget

from app import ui_constants as ui
from app.archive_settings import ArchiveSettings
from app.card_list_model import CardListModel
from app.content_views import _DragDropListView, _RubberBandTableView
from app.feature_toggle_config import FeatureToggleConfig
from app.file_list_model import FileListModel
from app.folder_tree_model import FolderTreeModel
from app.path_display import make_display_path_from_service
from application.assembly_service import AssemblyService
from application.clipboard_service import ClipboardService
from application.content_unit_creation_service import ContentUnitCreationService
from application.errors import ApplicationError
from application.file_operation_service import FileOperationService
from application.strip_service import StripService
from application.tag_service import TagService
from domain.models import FileEntry
from infrastructure.path_utils import make_path_key

# 视图索引（QStackedWidget，与 view_state_controller 一致）
VIEW_INDEX_LIST = 0
VIEW_INDEX_CARD = 1


class ContextMenuBuilder:
    """目录树 / 中栏 / 空白区域右键菜单构建与分发。"""

    def __init__(
        self,
        content_unit_creation_service: ContentUnitCreationService | None,
        tag_service: TagService | None,
        assembly_service: AssemblyService | None,
        assembly_panel,
        file_operation_service: FileOperationService | None,
        clipboard_service: ClipboardService | None,
        strip_service: StripService | None = None,
        *,
        content_view: _RubberBandTableView,
        card_view: _DragDropListView,
        content_list_model: FileListModel,
        card_list_model: CardListModel,
        tree_view,
        tree_model: FolderTreeModel,
        current_view_index: Callable[[], int],
        current_displayed_dir: Callable[[], str | None],
        dialog_parent: QWidget,
        host: object,
        archive_settings: ArchiveSettings | None = None,
        feature_toggle_config: FeatureToggleConfig | None = None,
    ) -> None:
        """初始化菜单构建器。

        Args:
            host: 动作 handler 宿主（MainWindow，保留同名薄委托）。
            其余参数为菜单可见性规则所需的服务/控件与状态回调。
        """
        self._content_unit_creation_service = content_unit_creation_service
        self._tag_service = tag_service
        self._assembly_service = assembly_service
        self._assembly_panel = assembly_panel
        self._file_operation_service = file_operation_service
        self._clipboard_service = clipboard_service
        self._strip_service = strip_service
        self._content_view = content_view
        self._card_view = card_view
        self._content_list_model = content_list_model
        self._card_list_model = card_list_model
        self._tree_view = tree_view
        self._tree_model = tree_model
        self._current_view_index = current_view_index
        self._current_displayed_dir = current_displayed_dir
        self._dialog_parent = dialog_parent
        self._host = host
        self._archive_settings = archive_settings
        self._feature_toggle_config = feature_toggle_config

    def _feature_enabled(self, feature_id: str) -> bool:
        """右键功能开关：未注入配置时默认全部启用（向前兼容）。"""
        return self._feature_toggle_config is None or self._feature_toggle_config.is_enabled(
            feature_id
        )

    def _add_action(
        self,
        menu: QMenu,
        label: str,
        feature_id: str,
        enabled: bool = True,
    ) -> QAction | None:
        """添加受开关控制的菜单项；关闭时返回 None，调用方身份判断自然跳过。"""
        if not self._feature_enabled(feature_id):
            return None
        action = menu.addAction(label)
        action.setEnabled(enabled)
        return action

    def _make_menu(self) -> QMenu:
        """构造右键菜单。

        通过 ``app.main_window`` 模块动态取 QMenu：既有测试以
        ``app.main_window.QMenu`` 命名空间补丁拦截菜单构建（FakeMenu），
        保持该补丁路径有效。
        """
        from app import main_window as mw_module  # noqa: PLC0415

        return mw_module.QMenu(self._dialog_parent)

    def _make_submenu(self, title: str, parent: QWidget) -> QMenu:
        """构造子菜单（标题 + 父菜单）。

        与 ``_make_menu`` 同理由：保持 ``app.main_window.QMenu`` 命名空间补丁
        对全部菜单构建（含最近目标/最近标签子菜单）生效。
        """
        from app import main_window as mw_module  # noqa: PLC0415

        return mw_module.QMenu(title, parent)

    def _is_archive_root(self, path: Path) -> bool:
        """判断路径是否为当前归档根目录（功能增加1，2026-08-04）。"""
        return self._archive_settings is not None and self._archive_settings.is_root(path)

    def _is_inside_archive_root(self, path: Path) -> bool:
        """判断路径是否位于归档根目录内（含归档根自身）（功能增加1，2026-08-04）。"""
        if self._archive_settings is None:
            return False
        root = self._archive_settings.root_path()
        if root is None:
            return False
        key = make_path_key(path)
        root_key = make_path_key(root)
        if key == root_key:
            return True
        return key.startswith(root_key.rstrip(os.sep) + os.sep)

    # --- 目录树右键菜单 ---

    def show_tree_menu(self, pos: QPoint) -> None:  # noqa: N802 (Qt 命名)
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

        menu = self._make_menu()
        # 节点相关菜单项（仅在选中有效节点时显示）
        new_folder_action = None
        delete_action = None
        copy_action = None
        cut_action = None
        paste_action = None
        move_to_action = None
        archive_quick_action = None
        archive_to_action = None
        mark_archive_action = None
        unmark_archive_action = None
        manifest_action = None
        explorer_action = None
        pin_action = None
        unpin_action = None
        if node is not None:
            # 新建文件夹 / 删除（Stage 5 Task 3a，仅需 FileOperationService）
            if self._file_operation_service is not None:
                new_folder_action = self._add_action(menu, ui.MENU_NEW_FOLDER, "new_folder")
                if self._clipboard_service is not None:
                    copy_action = self._add_action(menu, ui.MENU_COPY, "copy")
                    cut_action = self._add_action(menu, ui.MENU_CUT, "cut")
                    # 粘贴项仅在剪贴板非空时启用
                    paste_action = self._add_action(menu, ui.MENU_PASTE, "paste")
                    if paste_action is not None:
                        paste_action.setEnabled(self._clipboard_service.get() is not None)
                move_to_action = self._add_action(menu, ui.MENU_MOVE_TO, "move_to")
                # 功能增加1（2026-08-04）：归档根内部条目不再显示归档移动/标记入口；
                # 归档根内文件夹（含归档根自身）仅保留「生成归档内容清单」
                node_path = Path(node.real_path)
                node_inside_archive = self._is_inside_archive_root(node_path)
                if not node_inside_archive:
                    archive_quick_action = self._add_action(
                        menu, ui.MENU_ARCHIVE_QUICK, "archive_quick"
                    )
                    archive_to_action = self._add_action(menu, ui.MENU_ARCHIVE_TO, "archive_to")
                if self._archive_settings is not None:
                    if self._is_archive_root(node_path):
                        unmark_archive_action = self._add_action(
                            menu, ui.MENU_UNMARK_ARCHIVE_ROOT, "mark_archive"
                        )
                        manifest_action = self._add_action(
                            menu, ui.MENU_GENERATE_ARCHIVE_MANIFEST, "generate_manifest"
                        )
                    elif node_inside_archive:
                        # 归档根内的子文件夹：生成该子目录的归档内容清单
                        manifest_action = self._add_action(
                            menu, ui.MENU_GENERATE_ARCHIVE_MANIFEST, "generate_manifest"
                        )
                    else:
                        mark_archive_action = self._add_action(
                            menu, ui.MENU_MARK_ARCHIVE_ROOT, "mark_archive"
                        )
                delete_action = self._add_action(menu, ui.MENU_DELETE, "delete")
            # 在资源管理器中打开（Stage 5 Task 1，节点有效时显示）
            explorer_action = self._add_action(menu, ui.MENU_OPEN_IN_EXPLORER, "open_in_explorer")

            # UX 重构 Phase 2 Task 5（Q2=C）：钉住/取消钉住
            if self._assembly_panel is not None:
                if self._assembly_panel.is_pinned():
                    unpin_action = self._add_action(menu, ui.MENU_UNPIN_FOLDER, "pin_folder")
                else:
                    # 未钉住 → 显示「钉住此文件夹」
                    pin_action = self._add_action(menu, ui.MENU_PIN_FOLDER, "pin_folder")

        # 折叠全部（Stage 5 Task 7，无论是否选中节点都显示）
        if node is not None:
            menu.addSeparator()
        collapse_action = self._add_action(menu, ui.MENU_COLLAPSE_ALL, "collapse_all")

        # 操作便捷性3：在「移动到...」后插入「移动到最近目录」子菜单（节点有效时）
        if node is not None and move_to_action is not None:
            self.insert_recent_move_submenu(menu, [Path(node.real_path)])

        chosen = menu.exec(self._tree_view.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if new_folder_action is not None and chosen is new_folder_action:
            self._host._on_new_folder_in_dir(node.real_path)
        elif copy_action is not None and chosen is copy_action:
            self._host._on_shortcut_copy_tree()
        elif cut_action is not None and chosen is cut_action:
            self._host._on_shortcut_cut_tree()
        elif paste_action is not None and chosen is paste_action:
            self._host._on_shortcut_paste_tree()
        elif move_to_action is not None and chosen is move_to_action:
            self._host._on_move_to_tree(node)
        elif archive_quick_action is not None and chosen is archive_quick_action:
            self._host._on_archive_quick_tree(node)
        elif archive_to_action is not None and chosen is archive_to_action:
            self._host._on_archive_to_tree(node)
        elif mark_archive_action is not None and chosen is mark_archive_action:
            self._host._on_mark_archive_root(Path(node.real_path))
        elif unmark_archive_action is not None and chosen is unmark_archive_action:
            self._host._on_unmark_archive_root(Path(node.real_path))
        elif manifest_action is not None and chosen is manifest_action:
            self._host._on_generate_archive_manifest(Path(node.real_path))
        elif delete_action is not None and chosen is delete_action:
            self._host._on_shortcut_delete_tree()
        elif explorer_action is not None and chosen is explorer_action:
            self._host._on_open_in_explorer(node.real_path)
        elif pin_action is not None and chosen is pin_action:
            self._host._pin_folder_from_context(Path(node.real_path))
        elif unpin_action is not None and chosen is unpin_action:
            self._host._unpin_from_context()
        elif chosen is collapse_action:
            self._host._collapse_all_tree()

    # --- 中栏右键菜单 ---

    def show_content_menu(self, pos: QPoint) -> None:  # noqa: N802 (Qt 命名)
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
        selected_rows = sm.selectedRows()

        entries: list[FileEntry] = []
        for idx in selected_rows:
            entry = active_model.entry_at(idx.row())
            if entry is not None:
                entries.append(entry)

        # Stage 5 Task 3a：空白区域右键 → 显示"新建文件夹"（基于当前目录）
        if not entries:
            self.show_empty_area_menu(active_view, pos)
            return

        actions = self.build_content_actions(entries)
        if not actions:
            return

        menu = self._make_menu()
        for label, _, enabled in actions:
            act = menu.addAction(label)
            act.setEnabled(enabled)

        # 操作便捷性3：在「移动到...」后插入「移动到最近目录」子菜单
        self.insert_recent_move_submenu(menu, [Path(e.path) for e in entries])
        # UI合理性8：内容单元右键 → 「添加最近标签 ▸」子菜单
        if (
            len(entries) == 1
            and entries[0].content_unit is not None
            and self._tag_service is not None
        ):
            self.insert_recent_tag_submenu(menu, entries[0].content_unit.id)

        chosen = menu.exec(active_view.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        for label, handler, _ in actions:
            if chosen.text() == label:
                handler()
                break

    def show_empty_area_menu(self, active_view: QAbstractItemView, pos: QPoint) -> None:
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
        menu = self._make_menu()
        new_folder_action = self._add_action(menu, ui.MENU_NEW_FOLDER, "new_folder")
        # 粘贴项（Stage 5 Task 3b，仅注入 ClipboardService 且剪贴板非空时显示）
        paste_action = None
        if self._clipboard_service is not None:
            paste_action = self._add_action(menu, ui.MENU_PASTE, "paste")
            if paste_action is not None:
                paste_action.setEnabled(self._clipboard_service.get() is not None)

        # UX 重构 Phase 2 Task 5（Q2=C）：钉住/取消钉住
        pin_action = None
        unpin_action = None
        if self._assembly_panel is not None:
            if self._assembly_panel.is_pinned():
                unpin_action = self._add_action(menu, ui.MENU_UNPIN_FOLDER, "pin_folder")
            else:
                # 当前目录未钉住 → 显示「钉住此文件夹」
                pin_action = self._add_action(menu, ui.MENU_PIN_FOLDER, "pin_folder")

        chosen = menu.exec(active_view.viewport().mapToGlobal(pos))
        if chosen is new_folder_action:
            self._host._on_new_folder_in_dir(current_dir)
        elif paste_action is not None and chosen is paste_action:
            self._host._perform_paste(Path(current_dir))
        elif pin_action is not None and chosen is pin_action:
            self._host._pin_folder_from_context(Path(current_dir))
        elif unpin_action is not None and chosen is unpin_action:
            self._host._unpin_from_context()

    def build_content_actions(
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
        if self._feature_enabled("open") and len(entries) == 1:
            entry = entries[0]
            actions.append(
                (ui.MENU_OPEN, lambda: self._host._on_entry_activated_for_entry(entry), True)
            )

        # 创建 Mod 组：单选或多选 + 全部为文件（非目录）+ 注入了 ContentUnitCreationService
        # UX 重构 Phase 1 Task 1 Commit 3：支持多选（E1：仅全文件时显示）
        if (
            self._feature_enabled("create_mod_group")
            and self._content_unit_creation_service is not None
            and len(entries) >= 1
            and all(not e.is_dir for e in entries)
        ):
            actions.append(
                (ui.MENU_CREATE_MOD_GROUP, lambda: self._host._on_create_mod_group(entries), True)
            )

        # 「加入装配」菜单项已移除（UX 重构 Phase 1 Task 2 B2-2 决策）：
        # Task 4 将由「添加到钉住文件夹」+ 拖拽替代。

        # 标记/取消标记
        if self._feature_enabled("mark_content_unit") and len(entries) == 1:
            entry = entries[0]
            if entry.content_unit is None:
                actions.append(
                    (
                        ui.MENU_MARK_CONTENT_UNIT,
                        lambda: self._host._on_mark_content_unit(entry),
                        True,
                    )
                )
            else:
                actions.append(
                    (
                        ui.MENU_UNMARK_CONTENT_UNIT,
                        lambda: self._host._on_unmark_content_unit(entry),
                        True,
                    )
                )
        elif self._feature_enabled("mark_content_unit"):
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
                        lambda: self._host._on_batch_mark_content_unit(entries),
                        True,
                    )
                )
            if has_any_marked:
                actions.append(
                    (
                        ui.MENU_BATCH_UNMARK_CONTENT_UNIT,
                        lambda: self._host._on_batch_unmark_content_unit(entries),
                        True,
                    )
                )

        # 批量打标签（Stage 4 Task 2）：多选且至少一个内容单元 + 注入了 TagService
        if (
            self._feature_enabled("batch_tag")
            and self._tag_service is not None
            and len(entries) > 1
        ):
            has_any_unit = any(e.content_unit is not None for e in entries)
            if has_any_unit:
                actions.append((ui.MENU_BATCH_TAG, lambda: self._host._on_batch_tag(entries), True))

        # 添加到钉住文件夹（UX 重构 Phase 1 Task 4）：
        # A1：仅装配面板钉住时显示；B1：支持多选；B6：放在「移动到...」之前。
        if (
            self._feature_enabled("add_to_pinned")
            and self._assembly_service is not None
            and self._assembly_panel is not None
            and self._assembly_panel.is_pinned()
            and self._assembly_panel.current_folder_path() is not None
        ):
            actions.append(
                (ui.MENU_ADD_TO_PINNED, lambda: self._host._on_add_to_pinned_folder(entries), True)
            )

        # UX 重构 Phase 2 Task 5（Q2=C）：钉住/取消钉住右键菜单
        if self._feature_enabled("pin_folder") and self._assembly_panel is not None:
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
                            lambda: self._host._pin_folder_from_context(folder_path),
                            True,
                        )
                    )
            # 有钉住文件夹时，任意选中都显示「取消钉住」
            if self._assembly_panel.is_pinned():
                actions.append((ui.MENU_UNPIN_FOLDER, self._host._unpin_from_context, True))

        # Stage 5 Task 3a：新建文件夹 / 重命名 / 删除（仅需 FileOperationService）
        # Stage 5 Task 3b：复制 / 剪切（需 FileOperationService + ClipboardService）
        # Stage 5 Task 5：移动到...（仅需 FileOperationService）
        if self._file_operation_service is not None:
            # 新建文件夹：单选时基于该条目所在目录；列表空白区域另处理
            # 这里仅在选中条目时显示（空白区域由 show_empty_area_menu 处理）
            if len(entries) == 1:
                entry = entries[0]
                # 新建文件夹：基于选中条目的父目录创建子文件夹
                if self._feature_enabled("new_folder"):
                    actions.append(
                        (
                            ui.MENU_NEW_FOLDER,
                            lambda: self._host._on_new_folder_for_entry(entry),
                            True,
                        )
                    )
                # 重命名：单选
                if self._feature_enabled("rename"):
                    actions.append(
                        (ui.MENU_RENAME, lambda: self._host._on_rename_entry(entry), True)
                    )
            # 复制 / 剪切：需 ClipboardService
            if self._clipboard_service is not None:
                if self._feature_enabled("copy"):
                    actions.append((ui.MENU_COPY, self._host._on_shortcut_copy, True))
                if self._feature_enabled("cut"):
                    actions.append((ui.MENU_CUT, self._host._on_shortcut_cut, True))
                # 粘贴：粘贴到当前中栏目录（不是右键的文件夹内部）
                # 剪贴板空时灰显
                if self._feature_enabled("paste"):
                    has_clipboard = self._clipboard_service.get() is not None
                    actions.append((ui.MENU_PASTE, self._host._on_shortcut_paste, has_clipboard))
            # Stage 5 Task 5：移动到...（Q4=A 中栏 + 目录树均添加）
            if self._feature_enabled("move_to"):
                actions.append((ui.MENU_MOVE_TO, lambda: self._host._on_move_to(entries), True))
            # 功能增加1（2026-08-04）：快速归档 / 归档到…（归档根内部条目不显示）
            if self._feature_enabled("archive_quick") and all(
                not self._is_inside_archive_root(Path(e.path)) for e in entries
            ):
                actions.append(
                    (ui.MENU_ARCHIVE_QUICK, lambda: self._host._on_archive_quick(entries), True)
                )
            if self._feature_enabled("archive_to") and all(
                not self._is_inside_archive_root(Path(e.path)) for e in entries
            ):
                actions.append(
                    (ui.MENU_ARCHIVE_TO, lambda: self._host._on_archive_to(entries), True)
                )
            # 归档根自身：取消标记 + 生成清单；根内子文件夹：生成该子目录清单；
            # 普通文件夹：标记为归档根目录（单选文件夹）
            if (
                self._feature_enabled("mark_archive")
                and len(entries) == 1
                and entries[0].is_dir
                and self._archive_settings is not None
            ):
                folder_path = Path(entries[0].path)
                if self._is_archive_root(folder_path):
                    actions.append(
                        (
                            ui.MENU_UNMARK_ARCHIVE_ROOT,
                            lambda: self._host._on_unmark_archive_root(folder_path),
                            True,
                        )
                    )
                    if self._feature_enabled("generate_manifest"):
                        actions.append(
                            (
                                ui.MENU_GENERATE_ARCHIVE_MANIFEST,
                                lambda: self._host._on_generate_archive_manifest(folder_path),
                                True,
                            )
                        )
                elif self._is_inside_archive_root(folder_path) and self._feature_enabled(
                    "generate_manifest"
                ):
                    actions.append(
                        (
                            ui.MENU_GENERATE_ARCHIVE_MANIFEST,
                            lambda: self._host._on_generate_archive_manifest(folder_path),
                            True,
                        )
                    )
                else:
                    actions.append(
                        (
                            ui.MENU_MARK_ARCHIVE_ROOT,
                            lambda: self._host._on_mark_archive_root(folder_path),
                            True,
                        )
                    )
            # 操作便捷性1（2026-08-04）：剥离（提取内容）
            # 单选普通文件夹（未标记内容单元）+ 注入 StripService 时显示
            if (
                self._feature_enabled("strip")
                and self._strip_service is not None
                and len(entries) == 1
                and entries[0].is_dir
                and entries[0].content_unit is None
            ):
                actions.append(
                    (
                        ui.MENU_STRIP_FOLDER,
                        lambda: self._host._on_strip_folder(entries[0]),
                        True,
                    )
                )
            # 删除：单选或批量
            if self._feature_enabled("delete"):
                actions.append(
                    (ui.MENU_DELETE, lambda: self._host._on_delete_entries(entries), True)
                )

        # 操作便捷性8（2026-08-04）：单选内容单元 → 自动填入网址 / 打开网址
        # 打开网址内部会先尝试自动填入（source_url 为空时），故两项都常显。
        if len(entries) == 1 and entries[0].content_unit is not None:
            if self._feature_enabled("autofill_url"):
                actions.append(
                    (
                        ui.MENU_AUTOFILL_URL,
                        lambda: self._host._on_autofill_url(entries[0]),
                        True,
                    )
                )
            if self._feature_enabled("open_url"):
                actions.append(
                    (ui.MENU_OPEN_URL, lambda: self._host._on_open_url(entries[0]), True)
                )

        # 操作便捷性9（2026-08-04）：单选条目（文件或文件夹）→ 浏览器搜索
        if self._feature_enabled("browser_search") and len(entries) == 1:
            actions.append(
                (
                    ui.MENU_BROWSER_SEARCH,
                    lambda: self._host._on_browser_search(entries[0]),
                    True,
                )
            )

        # 在资源管理器中打开（Stage 5 Task 1，始终显示，单选时可用）
        if self._feature_enabled("open_in_explorer") and len(entries) == 1:
            actions.append(
                (
                    ui.MENU_OPEN_IN_EXPLORER,
                    lambda: self._host._on_open_in_explorer(entries[0].path),
                    True,
                )
            )

        # 复制路径（始终）
        if self._feature_enabled("copy_path"):
            actions.append(
                (
                    ui.CONTEXT_MENU_COPY_PATH,
                    lambda: self._host._copy_path_to_clipboard(entries[0].path),
                    True,
                )
            )

        return actions

    # --- 最近移动目标 / 最近标签子菜单 ---

    def insert_recent_move_submenu(self, menu: QMenu, src_paths: list[Path]) -> None:
        """在「移动到...」菜单项后插入「移动到最近目录」子菜单。

        操作便捷性3（2026-08-02）：最近移动目标快捷入口。
        无最近目标时不插入；子菜单项文本用路径简化显示，Tooltip 为完整路径。
        """
        if not self._feature_enabled("move_to_recent"):
            return
        recent = self._host._recent_move_targets.list_recent()
        if not recent:
            return
        submenu = self._make_submenu(ui.MENU_MOVE_TO_RECENT, menu)
        for target in recent:
            display = make_display_path_from_service(target, self._host._service)
            act = submenu.addAction(display)
            act.setToolTip(target)
            act.triggered.connect(
                lambda checked=False, t=target: self._host._on_move_to_recent(src_paths, t)
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

    def insert_recent_tag_submenu(self, menu: QMenu, unit_id: str) -> None:
        """在右键菜单追加「添加最近标签 ▸」子菜单（UI合理性8）。

        列出最近使用标签，点击直接 attach + 提交，避免打开完整标签面板。
        无最近标签或 TagService 未注入时不插入。
        """
        if not self._feature_enabled("recent_tag"):
            return
        if self._host._tag_service is None or self._host._recent_tags is None:
            return
        tag_ids = self._host._recent_tags.list_recent()
        if not tag_ids:
            return
        # id → name 映射（list_categories_with_tags 一次获取全部）
        id_to_name: dict[str, str] = {}
        try:
            for _category, tags in self._host._tag_service.list_categories_with_tags():
                for t in tags:
                    id_to_name[t.id] = t.name
        except ApplicationError:
            return
        submenu = self._make_submenu(ui.MENU_ADD_RECENT_TAG, menu)
        for tag_id in tag_ids:
            name = id_to_name.get(tag_id)
            if name is None:
                continue  # 标签已删除，跳过
            act = submenu.addAction(name)
            act.triggered.connect(
                lambda checked=False, tid=tag_id: self._host._on_add_recent_tag(unit_id, tid)
            )
        menu.addMenu(submenu)
