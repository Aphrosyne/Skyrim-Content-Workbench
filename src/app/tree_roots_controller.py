"""目录树 / 受管理根目录控制器（MainWindow 第二轮拆分，TD-M21 阶段 4）。

封装根目录列表刷新/选中、目录树刷新/选中、添加/移除根目录配置与折叠全部，
MainWindow 保留同名薄委托与信号接线。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTreeView,
    QWidget,
)

from app import ui_constants as ui
from app.file_list_model import FileListModel
from app.folder_tree_model import FolderTreeModel
from app.path_display import make_display_path_from_service
from app.scan_controller import ScanController
from app.transaction_scope import TransactionScope
from application.errors import ManagedRootNotFoundError
from application.folder_tree_service import FolderTreeService
from application.managed_root_service import ManagedRootService
from domain.models import ManagedRoot


class TreeRootsController(QObject):
    """根目录列表与目录树的刷新 / 选中 / 配置管理控制器。"""

    def __init__(
        self,
        root_list: QListWidget,
        empty_hint: QLabel,
        remove_button: QPushButton,
        scan_button: QPushButton,
        scan_full_button: QPushButton,
        tree_view: QTreeView,
        tree_model: FolderTreeModel,
        tree_empty_hint: QLabel,
        content_empty_hint: QLabel,
        content_list_model: FileListModel,
        managed_root_service: ManagedRootService,
        tree_service: FolderTreeService,
        scan_controller: ScanController,
        transaction_scope: TransactionScope,
        *,
        refresh_content_list: Callable[[str], None],
        set_detail_text: Callable[[str], None],
        set_metadata_text: Callable[[str], None],
        set_status: Callable[[str], None],
        handle_error: Callable[[Exception, str], None],
        dialog_parent: QWidget | None = None,
        parent: QObject | None = None,
    ) -> None:
        """初始化目录树/根目录控制器。"""
        super().__init__(parent)
        self._root_list = root_list
        self._empty_hint = empty_hint
        self._remove_button = remove_button
        self._scan_button = scan_button
        self._scan_full_button = scan_full_button
        self._tree_view = tree_view
        self._tree_model = tree_model
        self._tree_empty_hint = tree_empty_hint
        self._content_empty_hint = content_empty_hint
        self._content_list_model = content_list_model
        self._service = managed_root_service
        self._tree_service = tree_service
        self._scan_controller = scan_controller
        self._tx = transaction_scope
        self._refresh_content_list = refresh_content_list
        self._set_detail_text = set_detail_text
        self._set_metadata_text = set_metadata_text
        self._set_status = set_status
        self._handle_error = handle_error
        self._dialog_parent = dialog_parent

    # --- 受管理根目录列表 ---

    def refresh_root_list(self) -> None:
        """从服务重新加载根目录列表。"""
        self._root_list.clear()
        roots = self._service.list_roots()
        for root in roots:
            self.add_root_item(root)
        self._empty_hint.setVisible(len(roots) == 0)
        self.on_selection_changed()

    def add_root_item(self, root: ManagedRoot) -> None:
        """向根目录列表追加一个条目。"""
        text = root.display_name or root.real_path
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, root.id)
        item.setToolTip(root.real_path)
        self._root_list.addItem(item)

    def selected_root_id(self) -> str | None:
        """返回当前选中根目录 ID；无选中返回 None。"""
        items = self._root_list.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.UserRole)

    def on_selection_changed(self) -> None:
        """根目录选中变化：同步扫描/移除按钮可用性。"""
        has_selection = self.selected_root_id() is not None
        scanning = self._scan_controller.is_scanning()
        self._scan_button.setEnabled(has_selection and not scanning)
        self._scan_full_button.setEnabled(has_selection and not scanning)
        self._remove_button.setEnabled(has_selection and not scanning)

    # --- 目录树 ---

    def refresh_tree(self) -> None:
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

    def on_tree_selection_changed(self, *args) -> None:  # noqa: ANN001 (Qt 信号)
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

    def collapse_all(self) -> None:
        """折叠目录树所有展开的节点（Stage 5 Task 7）。

        搜索跳转会展开大量节点，此功能用于快速收起。
        折叠后保留根节点的展开状态（顶层受管理根目录列表仍可见）。
        """
        self._tree_view.collapseAll()
        # 重新展开 model 根节点（其子节点 = 受管理根目录列表）
        root_idx = self._tree_model.index(0, 0)
        if root_idx.isValid():
            self._tree_view.setExpanded(root_idx, True)

    # --- 选中节点查询 ---

    def selected_tree_node(self):
        """获取目录树当前选中节点，无选中返回 None。"""
        sm = self._tree_view.selectionModel()
        if sm is None:
            return None
        indexes = sm.selectedIndexes()
        if not indexes:
            return None
        return self._tree_model.node_at(indexes[0])

    def tree_selected_path(self) -> Path | None:
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

    # --- 添加 / 移除根目录配置 ---

    def on_add_root(self) -> None:
        """打开目录选择对话框，添加受管理根目录。"""
        if self._scan_controller.is_scanning():
            return
        start_dir = ""
        existing = self._service.list_roots()
        if existing:
            start_dir = existing[0].real_path
        chosen = QFileDialog.getExistingDirectory(
            self._dialog_parent, ui.ADD_ROOT_BUTTON, start_dir
        )
        if not chosen:
            return
        try:
            self._service.add_root(Path(chosen))
            self._tx.commit()
        except Exception as e:  # noqa: BLE001 - UI 边界需捕获所有异常
            self._handle_error(e, ui.ERR_ADD_ROOT_FAILED)
            return
        self.refresh_root_list()
        self.refresh_tree()

    def on_remove_root(self) -> None:
        """移除选中的受管理根目录配置。

        UX 重构 Task 6：ManagedRootService.remove_root 同步清理该根路径前缀下的
        folder_cache / content_unit 扫描记录（重叠守卫 + UoW 事务，Service 内部提交）。
        仅删除应用数据库记录；不删除、不移动、不修改磁盘上的任何用户文件。
        """
        if self._scan_controller.is_scanning():
            return
        root_id = self.selected_root_id()
        if root_id is None:
            self._set_status(ui.ERR_NO_ROOT_SELECTED)
            return

        try:
            root = self._service.get_root(root_id)
        except ManagedRootNotFoundError:
            self.refresh_root_list()
            return

        confirm_text = ui.REMOVE_ROOT_CONFIRM_TEXT.format(path=root.real_path)
        reply = QMessageBox.question(
            self._dialog_parent,
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
            self.refresh_root_list()
            return
        except Exception as e:  # noqa: BLE001 - UI 边界需捕获所有异常
            self._handle_error(e, ui.ERR_REMOVE_ROOT_FAILED)
            return

        self.refresh_root_list()
        self.refresh_tree()
