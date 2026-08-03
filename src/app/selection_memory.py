"""中栏选中记忆（操作便捷性7，2026-08-03）。

记录每个浏览目录最后一次选中（含多选），后退/前进导航时按路径恢复并
滚动到首个恢复行。MainWindow 只负责在选中变化时 record、历史导航时 restore。
"""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QAbstractItemView


class SelectionMemory:
    """目录路径 → 选中条目路径列表 的记忆与恢复。"""

    def __init__(self) -> None:
        self._memory: dict[str, list[str]] = {}

    def record(self, dir_path: str, paths: list[str]) -> None:
        """记录指定目录最后一次选中（含多选）。"""
        self._memory[dir_path] = list(paths)

    def remembered_paths(self, dir_path: str) -> list[str]:
        """返回指定目录的记忆路径（无记录返回空列表）。"""
        return list(self._memory.get(dir_path, []))

    def restore(self, dir_path: str, model, view: QAbstractItemView) -> bool:
        """按路径恢复选中并滚动到首个恢复行（缺失路径跳过）。

        model 需提供 rowCount / entry_at / index（FileListModel 即可）；
        view 需提供 selectionModel / scrollTo（QTableView / QListView）。
        返回是否实际恢复了选中。
        """
        remembered = set(self._memory.get(dir_path, []))
        if not remembered:
            return False
        rows = [
            row
            for row in range(model.rowCount())
            if (entry := model.entry_at(row)) is not None and entry.path in remembered
        ]
        if not rows:
            return False
        sm = view.selectionModel()
        if sm is None:
            return False
        sm.clearSelection()
        for row in rows:
            idx = model.index(row, 0)
            sm.select(
                idx,
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )
        view.scrollTo(model.index(rows[0], 0))
        return True

    # --- 测试辅助 ---

    def entries_count(self) -> int:
        """返回记忆的目录数（供测试）。"""
        return len(self._memory)
