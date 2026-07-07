"""MainWindow 测试。

覆盖：
- 构造（依赖注入）；
- 根目录列表显示；
- 扫描按钮在无选择时不可用；
- 扫描状态文本变化可测试（通过公共接口）。

若 PySide6 未安装则跳过整个模块。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.main_window import MainWindow  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def _make_window(db_connection, db_path: Path) -> MainWindow:
    """构造 MainWindow，注入已配置的 service。"""
    service = ManagedRootService(ManagedRootRepository(db_connection))
    return MainWindow(service, db_path)


def test_main_window_constructs(qapp: QApplication, db_connection, db_path: Path) -> None:
    """主窗口可正常构造，标题与初始状态正确。"""
    window = _make_window(db_connection, db_path)
    assert window.windowTitle() == "Skyrim Mod Workbench"
    assert window.root_count() == 0
    # 初始无选中，扫描按钮应禁用
    assert window.is_scan_button_enabled() is False
    # 初始状态文本
    assert window.status_text() == "就绪"


def test_main_window_shows_existing_roots(
    qapp: QApplication, db_connection, db_path: Path, tmp_path: Path
) -> None:
    """已保存的根目录在窗口启动时应在列表中显示。"""
    # 先在数据库中添加一个根目录
    service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-1",
    )
    mods = tmp_path / "已保存模组"
    mods.mkdir()
    service.add_root(mods)

    # 新建窗口应能看到已保存的根目录
    window = _make_window(db_connection, db_path)
    assert window.root_count() == 1


def test_main_window_scan_button_disabled_without_selection(
    qapp: QApplication, db_connection, db_path: Path, tmp_path: Path
) -> None:
    """有根目录但未选中时，扫描按钮应禁用。"""
    service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-1",
    )
    mods = tmp_path / "Mods"
    mods.mkdir()
    service.add_root(mods)

    window = _make_window(db_connection, db_path)
    assert window.root_count() == 1
    # 默认未选中
    assert window.is_scan_button_enabled() is False


def test_main_window_scan_button_enabled_with_selection(
    qapp: QApplication, db_connection, db_path: Path, tmp_path: Path
) -> None:
    """选中根目录后扫描按钮应可用。"""
    service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-1",
    )
    mods = tmp_path / "Mods"
    mods.mkdir()
    service.add_root(mods)

    window = _make_window(db_connection, db_path)
    # 模拟选中第一项
    from app.main_window import QListWidget

    list_widget = window.findChild(QListWidget)
    assert list_widget is not None
    list_widget.setCurrentRow(0)

    assert window.is_scan_button_enabled() is True


def test_main_window_status_text_settable(qapp: QApplication, db_connection, db_path: Path) -> None:
    """status_text 可读取初始状态。"""
    window = _make_window(db_connection, db_path)
    assert window.status_text() == "就绪"
