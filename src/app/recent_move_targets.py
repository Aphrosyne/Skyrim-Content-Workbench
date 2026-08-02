"""最近移动目标记录（操作便捷性3 方案1，2026-08-02）。

记录最近 N 次成功移动的目标目录，通过 QSettings 持久化（跨会话保留），
供右键「移动到最近目录」子菜单 / MoveToDialog 快捷区 / Ctrl+Q 快捷键使用。

语义：
- 每次成功移动（至少移动成功 1 项）后 record(target)。
- 同目录去重置顶（make_path_key 归一化比较，AGENTS 规则 9）。
- 上限由 max_targets 控制（默认 5，用户确认），超出丢弃最旧。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from infrastructure.path_utils import make_path_key


class RecentMoveTargets:
    """最近移动目标列表（QSettings 持久化）。"""

    DEFAULT_MAX_TARGETS = 5
    _SETTINGS_KEY = "recent_move_targets"

    def __init__(self, settings: QSettings, max_targets: int = DEFAULT_MAX_TARGETS) -> None:
        """初始化最近目标记录。

        Args:
            settings: QSettings 实例（由 MainWindow 注入，与缩放/视图持久化共用）。
            max_targets: 保留的最大条目数。
        """
        self._settings = settings
        self._max_targets = max(1, max_targets)

    def record(self, target: str | Path) -> None:
        """记录一次成功移动的目标目录（去重置顶，超限丢弃最旧）。"""
        target_str = str(target)
        target_key = make_path_key(target_str)
        targets = self._read()
        # 去重（归一化比较，保留原始字符串用于显示）
        kept = [t for t in targets if make_path_key(t) != target_key]
        kept.insert(0, target_str)
        self._write(kept[: self._max_targets])

    def list_recent(self) -> list[str]:
        """按最近使用顺序返回目标目录路径列表（新→旧）。"""
        return self._read()

    def latest(self) -> str | None:
        """返回最近一次成功移动的目标目录；无记录返回 None。"""
        targets = self._read()
        return targets[0] if targets else None

    # --- 内部：QSettings 读写 ---

    def _read(self) -> list[str]:
        value = self._settings.value(self._SETTINGS_KEY, [])
        if not value:
            return []
        if isinstance(value, str):
            # 兼容单元素存储（QSettings 对单元素 list 可能存为标量）
            return [value]
        return [str(v) for v in value]

    def _write(self, targets: list[str]) -> None:
        self._settings.setValue(self._SETTINGS_KEY, targets)
        self._settings.sync()
