"""目录导航历史控制器（MainWindow 第二轮拆分，TD-M21 阶段 2）。

封装前进/后退栈、当前浏览目录与按钮可用性状态机（Stage 5 Task 2），
MainWindow 保留同名薄委托与测试镜像属性（``_nav_back_stack`` /
``_nav_forward_stack`` / ``_current_nav_path`` / ``_navigating_from_history``）。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QPushButton, QTreeView

from app.folder_tree_model import FolderTreeModel


class NavigationController(QObject):
    """目录导航历史状态机。

    状态：
    - ``_nav_back_stack`` / ``_nav_forward_stack``：浏览历史栈。
    - ``_current_nav_path``：当前浏览目录。
    - ``_navigating_from_history``：历史导航触发的切换标记，防止刷新时再次入栈。
    """

    def __init__(
        self,
        tree_model: FolderTreeModel,
        tree_view: QTreeView,
        nav_back_button: QPushButton,
        nav_forward_button: QPushButton,
        *,
        refresh_content_list: Callable[[str], None],
        set_metadata_not_selected: Callable[[], None],
        parent: QObject | None = None,
    ) -> None:
        """初始化导航控制器。

        Args:
            tree_model: 目录树模型（find_index_by_path 定位节点）。
            tree_view: 目录树视图（setCurrentIndex 触发中栏刷新链路）。
            nav_back_button / nav_forward_button: 前进/后退按钮。
            refresh_content_list: 未在目录树中找到节点时直接刷新中栏的回调。
            set_metadata_not_selected: 导航到新目录时重置元数据提示的回调。
        """
        super().__init__(parent)
        self._tree_model = tree_model
        self._tree_view = tree_view
        self._nav_back_button = nav_back_button
        self._nav_forward_button = nav_forward_button
        self._refresh_content_list = refresh_content_list
        self._set_metadata_not_selected = set_metadata_not_selected
        # Stage 5 Task 2：目录导航历史栈（UX 重构 Phase 1 移除模式后始终记录）
        self._nav_back_stack: list[str] = []
        self._nav_forward_stack: list[str] = []
        self._current_nav_path: str | None = None
        # 历史导航触发的切换标记，防止 _refresh_content_list 再次入栈导致循环
        self._navigating_from_history = False

    # --- 状态读取（MainWindow 镜像属性/测试使用） ---

    def back_stack(self) -> list[str]:
        """返回后退栈（同一列表对象，供测试读取）。"""
        return self._nav_back_stack

    def forward_stack(self) -> list[str]:
        """返回前进栈（同一列表对象，供测试读取）。"""
        return self._nav_forward_stack

    def current_path(self) -> str | None:
        """返回当前浏览目录路径。"""
        return self._current_nav_path

    def is_navigating_from_history(self) -> bool:
        """返回是否处于历史导航触发的切换中。"""
        return self._navigating_from_history

    # --- 导航操作 ---

    def navigate_back(self) -> None:
        """后退按钮：切换到上一个浏览目录。"""
        if not self._nav_back_stack:
            return
        current = self._current_nav_path
        target = self._nav_back_stack.pop()
        if current is not None:
            self._nav_forward_stack.append(current)
        self._navigating_from_history = True
        try:
            # 先更新当前路径，使导航期间恢复选中触发的 selectionChanged
            # 把记忆归属到正确目录（操作便捷性7）
            self._current_nav_path = target
            self.navigate_to(target)
        finally:
            self._navigating_from_history = False
        self.update_buttons()

    def navigate_forward(self) -> None:
        """前进按钮：切换到下一个浏览目录。"""
        if not self._nav_forward_stack:
            return
        current = self._current_nav_path
        target = self._nav_forward_stack.pop()
        if current is not None:
            self._nav_back_stack.append(current)
        self._navigating_from_history = True
        try:
            # 同上：先更新当前路径，避免恢复选中时记忆错归属目录
            self._current_nav_path = target
            self.navigate_to(target)
        finally:
            self._navigating_from_history = False
        self.update_buttons()

    def navigate_to(self, dir_path: str) -> None:
        """切换到指定目录（通过目录树选中触发，复用既有刷新链路）。

        未在目录树中找到节点时回退到直接刷新文件列表。
        """
        target_idx = self._tree_model.find_index_by_path(self._tree_view, dir_path)
        if target_idx.isValid():
            self._tree_view.setCurrentIndex(target_idx)
        else:
            # 未扫描的子目录：直接刷新中栏（不走 tree selection 链路）
            self._refresh_content_list(dir_path)
            self._set_metadata_not_selected()

    def record(self, dir_path: str) -> None:
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
        self.update_buttons()

    def update_buttons(self) -> None:
        """根据栈状态更新前进/后退按钮可用性。"""
        self._nav_back_button.setEnabled(len(self._nav_back_stack) > 0)
        self._nav_forward_button.setEnabled(len(self._nav_forward_stack) > 0)
