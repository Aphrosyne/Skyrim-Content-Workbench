"""顶部菜单栏视图（UI合理性3，2026-08-03）。

只负责构建菜单/动作并发信号，不包含业务逻辑；MainWindow 仅接线：
- 「视图」：列表/卡片视图（checkable 互斥）、重置布局、快捷键设置（占位，二期实现）
- 「工具」：标签管理、操作历史（可用性由 MainWindow 按注入服务开关）、
  网址与搜索设置（操作便捷性8/9，2026-08-04）
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenuBar

from app import ui_constants as ui


class MainMenuBar(QMenuBar):
    """主窗口顶部菜单栏（UI合理性3）。"""

    # 视图切换请求：'list' | 'card'
    switch_view_requested = Signal(str)
    # 布局重置请求（UI合理性2：分割线/列宽恢复默认）
    layout_reset_requested = Signal()
    # 内容单元标记设置请求（UI合理性21）
    marker_config_requested = Signal()
    # 网址与搜索设置请求（操作便捷性8/9）
    url_settings_requested = Signal()
    # 快捷键设置请求（占位，二期实现自定义快捷键）
    shortcuts_requested = Signal()
    # 工具菜单请求（复用 MainWindow 既有 handler）
    tag_manager_requested = Signal()
    operation_history_requested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._build_view_menu()
        self._build_tools_menu()

    # --- 菜单构建 ---

    def _build_view_menu(self) -> None:
        view_menu = self.addMenu(ui.MENU_BAR_VIEW)

        self._view_list_action = QAction(ui.MENU_VIEW_LIST, self)
        self._view_list_action.setCheckable(True)
        self._view_list_action.triggered.connect(
            lambda checked=False: self.switch_view_requested.emit("list")
        )
        self._view_card_action = QAction(ui.MENU_VIEW_CARD, self)
        self._view_card_action.setCheckable(True)
        self._view_card_action.triggered.connect(
            lambda checked=False: self.switch_view_requested.emit("card")
        )
        self._view_group = QActionGroup(self)
        self._view_group.setExclusive(True)
        self._view_group.addAction(self._view_list_action)
        self._view_group.addAction(self._view_card_action)
        self._view_list_action.setChecked(True)
        view_menu.addAction(self._view_list_action)
        view_menu.addAction(self._view_card_action)

        view_menu.addSeparator()

        self._reset_layout_action = QAction(ui.MENU_VIEW_RESET_LAYOUT, self)
        self._reset_layout_action.triggered.connect(
            lambda checked=False: self.layout_reset_requested.emit()
        )
        view_menu.addAction(self._reset_layout_action)

        self._marker_config_action = QAction(ui.MENU_VIEW_CONTENT_UNIT_MARKER, self)
        self._marker_config_action.triggered.connect(
            lambda checked=False: self.marker_config_requested.emit()
        )
        view_menu.addAction(self._marker_config_action)

        # 快捷键自定义：二期独立任务实现，占位保持禁用（AGENTS 待确认需求保留 TODO）
        self._shortcuts_action = QAction(ui.MENU_VIEW_SHORTCUTS, self)
        self._shortcuts_action.setEnabled(False)
        self._shortcuts_action.setToolTip(ui.MENU_VIEW_SHORTCUTS_TODO)
        # TODO(UI合理性3 二期)：实现快捷键自定义对话框，启用后连接 shortcuts_requested
        self._shortcuts_action.triggered.connect(
            lambda checked=False: self.shortcuts_requested.emit()
        )
        view_menu.addAction(self._shortcuts_action)

    def _build_tools_menu(self) -> None:
        tools_menu = self.addMenu(ui.MENU_BAR_TOOLS)

        self._tag_manager_action = QAction(ui.MENU_TOOLS_TAG_MANAGER, self)
        self._tag_manager_action.triggered.connect(
            lambda checked=False: self.tag_manager_requested.emit()
        )
        tools_menu.addAction(self._tag_manager_action)

        self._operation_history_action = QAction(ui.MENU_TOOLS_OPERATION_HISTORY, self)
        self._operation_history_action.triggered.connect(
            lambda checked=False: self.operation_history_requested.emit()
        )
        tools_menu.addAction(self._operation_history_action)

        # 操作便捷性8/9（2026-08-04）：网址与搜索设置（验收反馈：从「视图」移至「工具」）
        tools_menu.addSeparator()
        self._url_settings_action = QAction(ui.MENU_VIEW_URL_SETTINGS, self)
        self._url_settings_action.triggered.connect(
            lambda checked=False: self.url_settings_requested.emit()
        )
        tools_menu.addAction(self._url_settings_action)

    # --- MainWindow 接线辅助 ---

    def set_view(self, mode: str) -> None:
        """同步视图菜单选中态（'list' | 'card'）。"""
        if mode == "card":
            self._view_card_action.setChecked(True)
        else:
            self._view_list_action.setChecked(True)

    def set_tag_manager_visible(self, visible: bool) -> None:
        """按注入服务开关标签管理菜单项。"""
        self._tag_manager_action.setVisible(visible)

    def set_operation_history_visible(self, visible: bool) -> None:
        """按注入服务开关操作历史菜单项。"""
        self._operation_history_action.setVisible(visible)

    # --- 测试辅助 ---

    def view_list_action(self) -> QAction:
        return self._view_list_action

    def view_card_action(self) -> QAction:
        return self._view_card_action

    def reset_layout_action(self) -> QAction:
        return self._reset_layout_action

    def marker_config_action(self) -> QAction:
        return self._marker_config_action

    @property
    def url_settings_action(self) -> QAction:
        return self._url_settings_action

    def shortcuts_action(self) -> QAction:
        return self._shortcuts_action

    def tag_manager_action(self) -> QAction:
        return self._tag_manager_action

    def operation_history_action(self) -> QAction:
        return self._operation_history_action
