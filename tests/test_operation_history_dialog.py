"""OperationHistoryDialog 列宽测试（UI合理性2，2026-08-03）。

覆盖：
- 三列均为 Interactive（可拖动）
- 默认列宽来自 LAYOUT_OPERATION_HISTORY_COLUMN_WIDTHS
- 拖动列宽后 QSettings 持久化，新实例恢复
- 「重置布局」清除存档键后，新实例回默认宽度
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QHeaderView  # noqa: E402

from app import ui_constants as ui  # noqa: E402
from app.operation_history_dialog import OperationHistoryDialog  # noqa: E402


class _FakeUndoService:
    """仅实现对话框加载历史所需接口。"""

    def list_recent(self, limit: int = 100) -> list:
        return []


def _make_settings(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "op_history.ini"), QSettings.Format.IniFormat)


def _make_dialog(settings: QSettings) -> OperationHistoryDialog:
    return OperationHistoryDialog(_FakeUndoService(), limit=100, settings=settings)


def test_columns_interactive_with_default_widths(qapp, tmp_path: Path) -> None:
    dialog = _make_dialog(_make_settings(tmp_path))
    try:
        header = dialog._table.horizontalHeader()  # noqa: SLF001
        assert all(
            header.sectionResizeMode(i) == QHeaderView.ResizeMode.Interactive for i in range(3)
        )
        for i, width in enumerate(ui.LAYOUT_OPERATION_HISTORY_COLUMN_WIDTHS):
            assert header.sectionSize(i) == width
    finally:
        dialog.close()


def test_column_widths_persist_across_instances(qapp, tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    dialog1 = _make_dialog(settings)
    try:
        header = dialog1._table.horizontalHeader()  # noqa: SLF001
        # resizeSection 触发 sectionResized → 自动保存
        header.resizeSection(1, 420)
    finally:
        dialog1.close()

    dialog2 = _make_dialog(settings)
    try:
        header2 = dialog2._table.horizontalHeader()  # noqa: SLF001
        assert header2.sectionSize(1) == 420
        # 未拖动的列保持默认
        assert header2.sectionSize(0) == ui.LAYOUT_OPERATION_HISTORY_COLUMN_WIDTHS[0]
    finally:
        dialog2.close()


def test_reset_clears_key_and_new_dialog_uses_defaults(qapp, tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    dialog1 = _make_dialog(settings)
    try:
        header = dialog1._table.horizontalHeader()  # noqa: SLF001
        header.resizeSection(1, 420)
    finally:
        dialog1.close()
    assert settings.contains(ui.QSETTINGS_KEY_HEADER_OPERATION_HISTORY)

    # 模拟菜单「重置布局」：删除存档键
    from app.splitter_state import SplitterStateHelper

    SplitterStateHelper(settings).remove_key(ui.QSETTINGS_KEY_HEADER_OPERATION_HISTORY)

    dialog2 = _make_dialog(settings)
    try:
        header2 = dialog2._table.horizontalHeader()  # noqa: SLF001
        for i, width in enumerate(ui.LAYOUT_OPERATION_HISTORY_COLUMN_WIDTHS):
            assert header2.sectionSize(i) == width
    finally:
        dialog2.close()
