"""应用模式管理器（spec §5.1/§5.2，roadmap 阶段 2 Task 5）。

封装当前应用模式（浏览/整理）的状态与切换逻辑，通过 Qt 信号通知订阅者。

设计要点：
- 纯 UI 层组件，不访问数据库或文件系统。
- 模式枚举 AppMode 定义在 domain.models，避免 UI 层持有业务语义。
- 相同模式重复设置不 emit 信号（避免无意义刷新）。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from domain.models import AppMode


class ModeManager(QObject):
    """应用模式状态管理器。

    使用方式：
        manager = ModeManager()
        manager.mode_changed.connect(self._on_mode_changed)
        manager.set_mode(AppMode.organize)
    """

    mode_changed = Signal(object)  # 发送 AppMode 枚举值

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._mode: AppMode = AppMode.browse

    @property
    def mode(self) -> AppMode:
        """当前模式。"""
        return self._mode

    def set_mode(self, mode: AppMode) -> None:
        """切换模式。相同模式不 emit 信号。"""
        if self._mode == mode:
            return
        self._mode = mode
        self.mode_changed.emit(mode)

    def is_browse(self) -> bool:
        """是否为浏览模式。"""
        return self._mode == AppMode.browse

    def is_organize(self) -> bool:
        """是否为整理模式。"""
        return self._mode == AppMode.organize
