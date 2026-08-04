"""键盘快捷键注册（MainWindow 第二轮拆分，TD-M21 阶段 8；2026-08-04 支持自定义）。

将 MainWindow._setup_shortcuts 的 QShortcut 注册逻辑迁出；主窗口保留
``_shortcut_*`` 实例属性（防止 QShortcut 被 GC 且供测试检查注入开关）。

2026-08-04（设计合理性1 附带）：注册前读取 ShortcutConfig——
- 空键 = 禁用该快捷键（跳过注册并清理旧属性）；
- 重新调用 register() 会先卸载旧 QShortcut 再重建（设置对话框保存后立即生效）。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow, QWidget

from app import ui_constants as ui
from app.shortcut_config import ShortcutConfig

# 所有可能挂到宿主的快捷键属性名（重注册/卸载时按名清理）
_SHORTCUT_ATTR_NAMES: tuple[str, ...] = (
    "_shortcut_select_all",
    "_shortcut_undo",
    "_shortcut_rename",
    "_shortcut_rename_tree",
    "_shortcut_delete",
    "_shortcut_delete_tree",
    "_shortcut_move_to",
    "_shortcut_move_to_tree",
    "_shortcut_move_to_latest",
    "_shortcut_archive_quick",
    "_shortcut_copy",
    "_shortcut_cut",
    "_shortcut_paste",
    "_shortcut_copy_tree",
    "_shortcut_cut_tree",
    "_shortcut_paste_tree",
    "_shortcut_refresh",
    "_shortcut_toggle_pin",
)


class ShortcutRegistry:
    """按注入服务注册快捷键并挂到主窗口属性上。"""

    def __init__(self, host: QMainWindow, shortcut_config: ShortcutConfig | None = None) -> None:
        self._host = host
        self._config = shortcut_config

    def register(self) -> None:
        """注册键盘快捷键（先卸载旧注册，支持配置变更后重注册）。"""
        self._unregister_all()
        host = self._host

        # 中栏 Ctrl+A 始终注册
        self._register(
            "_shortcut_select_all",
            "select_all",
            host._content_view,  # noqa: SLF001
            Qt.ShortcutContext.WidgetShortcut,
            host._on_shortcut_select_all,  # noqa: SLF001
        )

        # Ctrl+Z：窗口级（任意位置聚焦均可触发，因为撤销是全局操作）
        # 仅在注入 UndoService 时注册
        if host._undo_service is not None:  # noqa: SLF001
            self._register(
                "_shortcut_undo",
                "undo",
                host,
                Qt.ShortcutContext.WindowShortcut,
                host._on_shortcut_undo,  # noqa: SLF001
            )

        # F2 / Delete / Ctrl+M 依赖 FileOperationService
        if host._file_operation_service is not None:  # noqa: SLF001
            # 中栏 F2 重命名（Q1=A：多选取第一个）
            self._register(
                "_shortcut_rename",
                "rename",
                host._content_view,  # noqa: SLF001
                Qt.ShortcutContext.WidgetShortcut,
                host._on_shortcut_rename_content,  # noqa: SLF001
            )
            self._register(
                "_shortcut_rename_tree",
                "rename",
                host._tree_view,  # noqa: SLF001
                Qt.ShortcutContext.WidgetShortcut,
                host._on_shortcut_rename_tree,  # noqa: SLF001
            )
            # 中栏 Delete 删除
            self._register(
                "_shortcut_delete",
                "delete",
                host._content_view,  # noqa: SLF001
                Qt.ShortcutContext.WidgetShortcut,
                host._on_shortcut_delete,  # noqa: SLF001
            )
            self._register(
                "_shortcut_delete_tree",
                "delete",
                host._tree_view,  # noqa: SLF001
                Qt.ShortcutContext.WidgetShortcut,
                host._on_shortcut_delete_tree,  # noqa: SLF001
            )
            # Stage 5 Task 5：Ctrl+M 移动到…（Q3=B 中栏 + 目录树 WidgetShortcut）
            self._register(
                "_shortcut_move_to",
                "move_to",
                host._content_view,  # noqa: SLF001
                Qt.ShortcutContext.WidgetShortcut,
                host._on_shortcut_move_to,  # noqa: SLF001
            )
            self._register(
                "_shortcut_move_to_tree",
                "move_to",
                host._tree_view,  # noqa: SLF001
                Qt.ShortcutContext.WidgetShortcut,
                host._on_shortcut_move_to_tree,  # noqa: SLF001
            )
            # 操作便捷性3：Ctrl+Q 移动到最近目标（窗口级，任意位置可触发）
            self._register(
                "_shortcut_move_to_latest",
                "move_to_latest",
                host,
                Qt.ShortcutContext.WindowShortcut,
                host._on_shortcut_move_to_latest,  # noqa: SLF001
            )
            # 功能增加1（2026-08-04）：Ctrl+W 快速归档（窗口级，与 Ctrl+Q 一致）
            self._register(
                "_shortcut_archive_quick",
                "archive_quick",
                host,
                Qt.ShortcutContext.WindowShortcut,
                host._on_shortcut_archive_quick,  # noqa: SLF001
            )

        # Ctrl+C / Ctrl+X / Ctrl+V 依赖 FileOperationService + ClipboardService
        if (
            host._file_operation_service is not None  # noqa: SLF001
            and host._clipboard_service is not None  # noqa: SLF001
        ):
            # 中栏 Ctrl+C / Ctrl+X / Ctrl+V（Task 3b 真实逻辑）
            self._register(
                "_shortcut_copy",
                "copy",
                host._content_view,  # noqa: SLF001
                Qt.ShortcutContext.WidgetShortcut,
                host._on_shortcut_copy,  # noqa: SLF001
            )
            self._register(
                "_shortcut_cut",
                "cut",
                host._content_view,  # noqa: SLF001
                Qt.ShortcutContext.WidgetShortcut,
                host._on_shortcut_cut,  # noqa: SLF001
            )
            self._register(
                "_shortcut_paste",
                "paste",
                host._content_view,  # noqa: SLF001
                Qt.ShortcutContext.WidgetShortcut,
                host._on_shortcut_paste,  # noqa: SLF001
            )
            # 目录树 Ctrl+C / Ctrl+X / Ctrl+V（Task 3b：目录树也支持）
            self._register(
                "_shortcut_copy_tree",
                "copy",
                host._tree_view,  # noqa: SLF001
                Qt.ShortcutContext.WidgetShortcut,
                host._on_shortcut_copy_tree,  # noqa: SLF001
            )
            self._register(
                "_shortcut_cut_tree",
                "cut",
                host._tree_view,  # noqa: SLF001
                Qt.ShortcutContext.WidgetShortcut,
                host._on_shortcut_cut_tree,  # noqa: SLF001
            )
            self._register(
                "_shortcut_paste_tree",
                "paste",
                host._tree_view,  # noqa: SLF001
                Qt.ShortcutContext.WidgetShortcut,
                host._on_shortcut_paste_tree,  # noqa: SLF001
            )

        # UX 重构 Phase 2 Task 5（Q5=B）：F5 刷新当前目录（窗口级，任意位置聚焦可触发）
        self._register(
            "_shortcut_refresh",
            "refresh",
            host,
            Qt.ShortcutContext.WindowShortcut,
            host._on_refresh_current,  # noqa: SLF001
        )

        # 操作便捷性10（2026-08-04）：Ctrl+P 钉住/取消钉住文件夹预览（窗口级）
        if host._assembly_panel is not None:  # noqa: SLF001
            self._register(
                "_shortcut_toggle_pin",
                "toggle_pin",
                host,
                Qt.ShortcutContext.WindowShortcut,
                host._on_shortcut_toggle_pin,  # noqa: SLF001
            )

    def _register(
        self,
        attr_name: str,
        shortcut_id: str,
        parent: QWidget | QMainWindow,
        context: Qt.ShortcutContext,
        handler: Callable[[], None],
    ) -> None:
        """注册单条快捷键；空键（禁用）跳过注册。"""
        key = (
            self._config.key_for(shortcut_id)
            if self._config is not None
            else ui.SHORTCUT_DEFAULT_KEYS[shortcut_id]
        )
        if not key:
            return
        shortcut = QShortcut(QKeySequence(key), parent)
        shortcut.setContext(context)
        shortcut.activated.connect(handler)
        setattr(self._host, attr_name, shortcut)
        self._host_shortcuts().append(shortcut)

    def _unregister_all(self) -> None:
        """卸载宿主上的全部已注册快捷键（禁用 + 待删），并清理宿主属性。

        快捷键列表挂在宿主上（``_scw_registered_shortcuts``），
        保证 MainWindow 每次新建 ShortcutRegistry 重注册时也能先卸载旧键。
        """
        for shortcut in self._host_shortcuts():
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._host_shortcuts().clear()
        for attr_name in _SHORTCUT_ATTR_NAMES:
            if hasattr(self._host, attr_name):
                delattr(self._host, attr_name)

    def _host_shortcuts(self) -> list[QShortcut]:
        """宿主上的已注册快捷键列表（跨 registry 实例共享）。"""
        if not hasattr(self._host, "_scw_registered_shortcuts"):
            self._host._scw_registered_shortcuts = []  # noqa: SLF001
        return self._host._scw_registered_shortcuts  # noqa: SLF001
