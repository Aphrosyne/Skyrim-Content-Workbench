"""键盘快捷键注册（MainWindow 第二轮拆分，TD-M21 阶段 8）。

将 MainWindow._setup_shortcuts 的 QShortcut 注册逻辑迁出；宿主窗口保留
``_shortcut_*`` 实例属性（防止 QShortcut 被 GC 且供测试检查注入开关）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow


class ShortcutRegistry:
    """按注入服务注册快捷键并挂到宿主窗口属性上。"""

    def __init__(self, host: QMainWindow) -> None:
        self._host = host

    def register(self) -> None:
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
        host = self._host
        # 中栏 Ctrl+A 始终注册
        host._shortcut_select_all = QShortcut(QKeySequence("Ctrl+A"), host._content_view)
        host._shortcut_select_all.setContext(Qt.ShortcutContext.WidgetShortcut)
        host._shortcut_select_all.activated.connect(host._on_shortcut_select_all)

        # Ctrl+Z：窗口级（任意位置聚焦均可触发，因为撤销是全局操作）
        # 仅在注入 UndoService 时注册
        if host._undo_service is not None:
            host._shortcut_undo = QShortcut(QKeySequence("Ctrl+Z"), host)
            host._shortcut_undo.setContext(Qt.ShortcutContext.WindowShortcut)
            host._shortcut_undo.activated.connect(host._on_shortcut_undo)

        # F2 / Delete 依赖 FileOperationService
        if host._file_operation_service is not None:
            # 中栏 F2 重命名（Q1=A：多选取第一个）
            host._shortcut_rename = QShortcut(QKeySequence("F2"), host._content_view)
            host._shortcut_rename.setContext(Qt.ShortcutContext.WidgetShortcut)
            host._shortcut_rename.activated.connect(host._on_shortcut_rename_content)

            # 中栏 Delete 删除
            host._shortcut_delete = QShortcut(QKeySequence("Delete"), host._content_view)
            host._shortcut_delete.setContext(Qt.ShortcutContext.WidgetShortcut)
            host._shortcut_delete.activated.connect(host._on_shortcut_delete)

            # 目录树 F2 / Delete（用户补充：目录树也支持 F2/Delete）
            host._shortcut_rename_tree = QShortcut(QKeySequence("F2"), host._tree_view)
            host._shortcut_rename_tree.setContext(Qt.ShortcutContext.WidgetShortcut)
            host._shortcut_rename_tree.activated.connect(host._on_shortcut_rename_tree)

            host._shortcut_delete_tree = QShortcut(QKeySequence("Delete"), host._tree_view)
            host._shortcut_delete_tree.setContext(Qt.ShortcutContext.WidgetShortcut)
            host._shortcut_delete_tree.activated.connect(host._on_shortcut_delete_tree)

            # Stage 5 Task 5：Ctrl+M 移动到...（Q3=B 中栏 + 目录树 WidgetShortcut）
            host._shortcut_move_to = QShortcut(QKeySequence("Ctrl+M"), host._content_view)
            host._shortcut_move_to.setContext(Qt.ShortcutContext.WidgetShortcut)
            host._shortcut_move_to.activated.connect(host._on_shortcut_move_to)

            host._shortcut_move_to_tree = QShortcut(QKeySequence("Ctrl+M"), host._tree_view)
            host._shortcut_move_to_tree.setContext(Qt.ShortcutContext.WidgetShortcut)
            host._shortcut_move_to_tree.activated.connect(host._on_shortcut_move_to_tree)

            # 操作便捷性3：Ctrl+Q 移动到最近目标（窗口级，任意位置可触发）。
            # 默认快捷键暂定 Ctrl+Q，后续做自定义快捷键菜单时再开放配置。
            host._shortcut_move_to_latest = QShortcut(QKeySequence("Ctrl+Q"), host)
            host._shortcut_move_to_latest.setContext(Qt.ShortcutContext.WindowShortcut)
            host._shortcut_move_to_latest.activated.connect(host._on_shortcut_move_to_latest)

            # 功能增加1（2026-08-04）：Ctrl+W 快速归档（窗口级，与 Ctrl+Q 一致）。
            host._shortcut_archive_quick = QShortcut(QKeySequence("Ctrl+W"), host)
            host._shortcut_archive_quick.setContext(Qt.ShortcutContext.WindowShortcut)
            host._shortcut_archive_quick.activated.connect(host._on_shortcut_archive_quick)

        # Ctrl+C / Ctrl+X / Ctrl+V 依赖 FileOperationService + ClipboardService
        if host._file_operation_service is not None and host._clipboard_service is not None:
            # 中栏 Ctrl+C / Ctrl+X / Ctrl+V（Task 3b 真实逻辑）
            host._shortcut_copy = QShortcut(QKeySequence("Ctrl+C"), host._content_view)
            host._shortcut_copy.setContext(Qt.ShortcutContext.WidgetShortcut)
            host._shortcut_copy.activated.connect(host._on_shortcut_copy)

            host._shortcut_cut = QShortcut(QKeySequence("Ctrl+X"), host._content_view)
            host._shortcut_cut.setContext(Qt.ShortcutContext.WidgetShortcut)
            host._shortcut_cut.activated.connect(host._on_shortcut_cut)

            host._shortcut_paste = QShortcut(QKeySequence("Ctrl+V"), host._content_view)
            host._shortcut_paste.setContext(Qt.ShortcutContext.WidgetShortcut)
            host._shortcut_paste.activated.connect(host._on_shortcut_paste)

            # 目录树 Ctrl+C / Ctrl+X / Ctrl+V（用户补充：目录树也支持复制/剪切/粘贴）
            host._shortcut_copy_tree = QShortcut(QKeySequence("Ctrl+C"), host._tree_view)
            host._shortcut_copy_tree.setContext(Qt.ShortcutContext.WidgetShortcut)
            host._shortcut_copy_tree.activated.connect(host._on_shortcut_copy_tree)

            host._shortcut_cut_tree = QShortcut(QKeySequence("Ctrl+X"), host._tree_view)
            host._shortcut_cut_tree.setContext(Qt.ShortcutContext.WidgetShortcut)
            host._shortcut_cut_tree.activated.connect(host._on_shortcut_cut_tree)

            host._shortcut_paste_tree = QShortcut(QKeySequence("Ctrl+V"), host._tree_view)
            host._shortcut_paste_tree.setContext(Qt.ShortcutContext.WidgetShortcut)
            host._shortcut_paste_tree.activated.connect(host._on_shortcut_paste_tree)

        # UX 重构 Phase 2 Task 5（Q5=B）：F5 刷新当前目录（窗口级，任意位置聚焦可触发）
        host._shortcut_refresh = QShortcut(QKeySequence("F5"), host)
        host._shortcut_refresh.setContext(Qt.ShortcutContext.WindowShortcut)
        host._shortcut_refresh.activated.connect(host._on_refresh_current)

        # 操作便捷性10（2026-08-04）：Ctrl+P 钉住/取消钉住文件夹预览（窗口级）
        if host._assembly_panel is not None:
            host._shortcut_toggle_pin = QShortcut(QKeySequence("Ctrl+P"), host)
            host._shortcut_toggle_pin.setContext(Qt.ShortcutContext.WindowShortcut)
            host._shortcut_toggle_pin.activated.connect(host._on_shortcut_toggle_pin)
