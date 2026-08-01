"""装配面板控制器（UX 重构 Task 7 Step 3）。

封装装配面板的绑定 / 钉住 / 跟随中栏 / 受影响刷新逻辑（TD-M21），
MainWindow 通过回调与控制器交互，不再直接操作面板状态机。

设计约束（UX 重构 Phase 1 Task 3 A1/A2）：
- 钉住状态下 ``bind_*`` 调用被面板内部短路（本控制器只转发，不感知钉住）。
- 取消钉住后由 MainWindow 计算中栏当前选中并调用 ``follow_selection``。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject

from app.assembly_panel import AssemblyPanel
from domain.models import ContentUnit, FileEntry
from infrastructure.path_utils import make_path_key


class AssemblyController(QObject):
    """装配面板绑定 / 钉住 / 刷新控制器。"""

    def __init__(
        self,
        assembly_panel: AssemblyPanel | None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._panel = assembly_panel

    def has_panel(self) -> bool:
        """返回是否持有装配面板（未注入时所有操作均为空操作）。"""
        return self._panel is not None

    def bind_to_unit(self, unit: ContentUnit | None) -> None:
        """绑定/解绑装配面板到指定内容单元（钉住时面板内部短路）。"""
        if self._panel is not None:
            self._panel.bind_mod_group(unit)

    def bind_to_folder(self, folder_path: Path | None) -> None:
        """透视任意文件夹路径（不依赖 ContentUnit，钉住时面板内部短路）。"""
        if self._panel is not None:
            self._panel.bind_folder(folder_path)

    def is_pinned(self) -> bool:
        """返回装配面板当前是否处于钉住状态。"""
        return self._panel is not None and self._panel.is_pinned()

    def pin_folder(self, folder_path: Path) -> None:
        """钉住指定文件夹（替换已有钉住）。"""
        if self._panel is not None:
            self._panel.pin_folder(folder_path)

    def unpin(self) -> None:
        """取消钉住（仅清除钉住标志，不改变绑定）。"""
        if self._panel is not None and self._panel.is_pinned():
            self._panel.unpin()

    def follow_selection(self, entry: FileEntry | None) -> None:
        """按中栏当前选中条目绑定装配面板（B4 决策，取消钉住后调用）。

        - 选中文件夹内容单元 → 绑定该 Mod 组
        - 选中非内容单元文件夹 → 透视该文件夹
        - 选中文件或无选中 → 解绑显空状态
        """
        if self._panel is None:
            return
        if entry is None:
            self.bind_to_unit(None)
            return
        if entry.content_unit is not None:
            self.bind_to_unit(entry.content_unit if entry.is_dir else None)
        elif entry.is_dir:
            self.bind_to_folder(Path(entry.path))
        else:
            self.bind_to_unit(None)

    def refresh_if_affected(self, *affected_dirs: str | Path) -> None:
        """文件操作后，若受影响目录与装配面板当前透视文件夹相同则刷新。

        修复1（含用户补充）：双击进入被钉住的文件夹内进行任何操作
        （重命名、删除、新建文件夹、粘贴、移动等）都应当同步刷新装配面板。
        比较使用 make_path_key 归一化（AGENTS 规则 9）。

        Args:
            *affected_dirs: 文件操作受影响的目录路径列表（源/目标均可）。
        """
        if self._panel is None:
            return
        pinned_folder = self._panel.current_folder_path()
        if pinned_folder is None:
            return
        pinned_key = make_path_key(pinned_folder)
        for d in affected_dirs:
            if d is not None and make_path_key(d) == pinned_key:
                self._panel.refresh_current()
                return

    def refresh_current(self) -> None:
        """无条件刷新装配面板当前内容。"""
        if self._panel is not None:
            self._panel.refresh_current()

    def current_folder_path(self) -> Path | None:
        """返回装配面板当前透视/钉住的文件夹路径。"""
        if self._panel is None:
            return None
        return self._panel.current_folder_path()
