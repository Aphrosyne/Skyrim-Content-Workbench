"""分割线状态持久化（UI合理性2，2026-08-03）。

负责 QSplitter 尺寸与 QHeaderView 列宽的 保存 / 恢复 / 重置：
- 保存：写入 QSettings（键形如 ``layout/<name>``）
- 恢复：有合法存档 → 应用存档；否则应用调用方传入的默认尺寸
- 重置：删除存档键并立即应用默认尺寸

MainWindow 与 OperationHistoryDialog 均通过本 helper 管理分割线状态，
不重复实现 QSettings 读写逻辑。
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QHeaderView, QSplitter


def _valid_int_list(value: object, count: int) -> list[int] | None:
    """校验 QSettings 读回的尺寸列表：长度匹配且全部为正整数。

    兼容数字字符串：Windows 注册表（native 格式）把列表元素以字符串形式
    读回（如 ['300', '420', '300']），需转 int 后才可用于 setSizes。
    """
    if not isinstance(value, (list, tuple)):
        return None
    if len(value) != count:
        return None
    ints: list[int] = []
    for item in value:
        if isinstance(item, int):
            parsed = item
        elif isinstance(item, str):
            try:
                parsed = int(item.strip())
            except ValueError:
                return None
        else:
            return None
        if parsed <= 0:
            return None
        ints.append(parsed)
    return ints


class SplitterStateHelper:
    """分割线状态（QSplitter 尺寸 / QHeaderView 列宽）的保存与恢复。"""

    def __init__(self, settings: QSettings, key_prefix: str = "") -> None:
        self._settings = settings
        self._prefix = key_prefix

    def _key(self, name: str) -> str:
        return f"{self._prefix}/{name}" if self._prefix else name

    # --- QSplitter ---

    def save(self, splitter: QSplitter, name: str) -> None:
        """保存当前分割线像素尺寸。"""
        sizes = splitter.sizes()
        if sizes:
            self._settings.setValue(self._key(name), sizes)

    def restore(
        self,
        splitter: QSplitter,
        name: str,
        default_sizes: Sequence[int] | None = None,
    ) -> None:
        """恢复分割线尺寸：合法存档优先，否则应用默认尺寸。

        default_sizes 为 None 时（如主栏旧行为：无显式默认），
        仅在有存档时应用，否则保持 Qt 默认分配。
        """
        saved = _valid_int_list(self._settings.value(self._key(name)), splitter.count())
        if saved is not None:
            splitter.setSizes(saved)
            return
        if default_sizes is not None and len(default_sizes) == splitter.count():
            splitter.setSizes(list(default_sizes))

    def reset(
        self,
        splitter: QSplitter,
        name: str,
        default_sizes: Sequence[int],
    ) -> None:
        """重置为默认尺寸：删除存档键并立即应用。"""
        self._settings.remove(self._key(name))
        if len(default_sizes) == splitter.count():
            splitter.setSizes(list(default_sizes))

    # --- QHeaderView ---

    def save_header(
        self,
        header: QHeaderView,
        name: str,
    ) -> None:
        """保存当前各列像素宽度。"""
        widths = [header.sectionSize(i) for i in range(header.count())]
        if widths:
            self._settings.setValue(self._key(name), widths)

    def restore_header(
        self,
        header: QHeaderView,
        name: str,
        default_widths: Sequence[int],
    ) -> None:
        """恢复列宽：合法存档优先，否则应用默认宽度；所有列切为 Interactive（可拖动）。"""
        count = len(default_widths)
        widths = _valid_int_list(self._settings.value(self._key(name)), count)
        if widths is None:
            widths = list(default_widths)
        for i, width in enumerate(widths):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
            header.resizeSection(i, width)

    def reset_header(
        self,
        header: QHeaderView,
        name: str,
        default_widths: Sequence[int],
    ) -> None:
        """重置列宽为默认值：删除存档键并立即应用。"""
        self._settings.remove(self._key(name))
        self.restore_header(header, name, default_widths)

    # --- 通用 ---

    def remove_key(self, name: str) -> None:
        """删除指定键（供「重置布局」连带清理操作历史列宽存档）。"""
        self._settings.remove(self._key(name))
