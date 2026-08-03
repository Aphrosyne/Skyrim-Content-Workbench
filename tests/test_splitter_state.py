"""SplitterStateHelper 单元测试（UI合理性2，2026-08-03）。

覆盖：QSplitter 尺寸与 QHeaderView 列宽的 保存/恢复/重置，
以及非法存档（长度不匹配 / 非正数 / 类型错误）回退默认值。
测试使用 tmp_path 的 ini 隔离 QSettings，不写注册表。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QStandardItemModel  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QHeaderView,
    QSplitter,
    QTableView,
    QWidget,
)

from app.splitter_state import SplitterStateHelper  # noqa: E402


def _make_settings(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "state.ini"), QSettings.Format.IniFormat)


def _make_splitter(count: int = 3) -> QSplitter:
    splitter = QSplitter()
    for _ in range(count):
        splitter.addWidget(QWidget())
    return splitter


def _proportions(sizes: list[int]) -> list[float]:
    total = sum(sizes)
    return [s / total for s in sizes] if total else sizes


def _assert_same_proportions(actual: list[int], expected: list[int], tol: float = 0.03) -> None:
    """QSplitter 未显示时会按自身宽度等比缩放 setSizes 值，按比例比较。"""
    assert len(actual) == len(expected)
    for a, e in zip(_proportions(actual), _proportions(expected), strict=True):
        assert abs(a - e) <= tol, f"比例不一致：{actual} vs {expected}"


def test_save_and_restore_splitter_sizes(qapp, tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    helper = SplitterStateHelper(settings)
    splitter = _make_splitter()
    splitter.setSizes([100, 300, 200])

    helper.save(splitter, "layout/main")

    restored = _make_splitter()
    SplitterStateHelper(settings).restore(restored, "layout/main", default_sizes=(10, 10, 10))
    _assert_same_proportions(restored.sizes(), [100, 300, 200])


def test_restore_applies_defaults_when_no_save(qapp, tmp_path: Path) -> None:
    helper = SplitterStateHelper(_make_settings(tmp_path))
    splitter = _make_splitter()

    helper.restore(splitter, "layout/main", default_sizes=(220, 480, 324))

    _assert_same_proportions(splitter.sizes(), [220, 480, 324])


def test_restore_ignores_invalid_saved_values(qapp, tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    helper = SplitterStateHelper(settings)
    splitter = _make_splitter()
    splitter.setSizes([100, 200, 300])
    helper.save(splitter, "layout/main")

    for bad in ("oops", [1, 2], [100, 0, 300], [100, -5, 300]):
        settings.setValue("layout/main", bad)
        restored = _make_splitter()
        SplitterStateHelper(settings).restore(restored, "layout/main", default_sizes=(9, 9, 9))
        assert len(set(restored.sizes())) == 1, f"存档 {bad!r} 应回退默认值"


def test_restore_accepts_numeric_strings_from_registry(qapp, tmp_path: Path) -> None:
    """Windows 注册表以字符串列表读回尺寸，应兼容（固化修复，2026-08-03）。"""
    settings = _make_settings(tmp_path)
    settings.setValue("layout/main", ["300", "420", "300"])
    splitter = _make_splitter()

    SplitterStateHelper(settings).restore(splitter, "layout/main", default_sizes=(9, 9, 9))
    _assert_same_proportions(splitter.sizes(), [300, 420, 300])

    # 非法字符串仍回退默认
    settings.setValue("layout/main", ["abc", "420", "300"])
    fresh = _make_splitter()
    SplitterStateHelper(settings).restore(fresh, "layout/main", default_sizes=(7, 7, 7))
    assert len(set(fresh.sizes())) == 1


def test_reset_removes_key_and_applies_defaults(qapp, tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    helper = SplitterStateHelper(settings)
    splitter = _make_splitter()
    splitter.setSizes([100, 100, 100])
    helper.save(splitter, "layout/main")

    helper.reset(splitter, "layout/main", (220, 480, 324))

    _assert_same_proportions(splitter.sizes(), [220, 480, 324])
    fresh = _make_splitter()
    SplitterStateHelper(settings).restore(fresh, "layout/main", default_sizes=(7, 7, 7))
    assert len(set(fresh.sizes())) == 1  # 存档键已删除 → 回退默认


def test_restore_skips_defaults_on_count_mismatch(qapp, tmp_path: Path) -> None:
    """默认尺寸长度与分割线子控件数不匹配时跳过 setSizes（Qt 忽略无效列表）。"""
    helper = SplitterStateHelper(_make_settings(tmp_path))
    splitter = _make_splitter(count=1)

    helper.restore(splitter, "layout/main", default_sizes=(625, 125))
    # 不抛异常且尺寸保持 Qt 默认分配
    assert len(splitter.sizes()) == 1


def _make_header(count: int = 3) -> tuple[QTableView, QHeaderView]:
    view = QTableView()
    view.setModel(QStandardItemModel(0, count))
    header = view.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    return view, header


def test_header_save_restore_and_reset(qapp, tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    helper = SplitterStateHelper(settings)
    _, header = _make_header()
    header.resizeSection(0, 180)
    header.resizeSection(1, 340)
    header.resizeSection(2, 90)

    helper.save_header(header, "layout/header/op_history")

    _, restored = _make_header()
    SplitterStateHelper(settings).restore_header(
        restored, "layout/header/op_history", default_widths=(100, 100, 100)
    )
    assert [restored.sectionSize(i) for i in range(3)] == [180, 340, 90]

    SplitterStateHelper(settings).reset_header(
        restored, "layout/header/op_history", default_widths=(100, 200, 100)
    )
    assert [restored.sectionSize(i) for i in range(3)] == [100, 200, 100]

    # 重置后键已删除：新实例恢复回默认值
    _, fresh = _make_header()
    SplitterStateHelper(settings).restore_header(
        fresh, "layout/header/op_history", default_widths=(50, 50, 50)
    )
    assert [fresh.sectionSize(i) for i in range(3)] == [50, 50, 50]


def test_restore_header_makes_columns_interactive(qapp, tmp_path: Path) -> None:
    helper = SplitterStateHelper(_make_settings(tmp_path))
    _, header = _make_header()

    helper.restore_header(header, "layout/header/op_history", default_widths=(180, 340, 90))

    assert all(header.sectionResizeMode(i) == QHeaderView.ResizeMode.Interactive for i in range(3))


def test_remove_key(qapp, tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    helper = SplitterStateHelper(settings)
    splitter = _make_splitter()
    splitter.setSizes([100, 200, 300])
    helper.save(splitter, "layout/main")
    assert settings.contains("layout/main")

    helper.remove_key("layout/main")

    assert not settings.contains("layout/main")
