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

from PySide6.QtWidgets import QApplication, QListWidget  # noqa: E402

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


def test_main_window_scan_completes_without_crash(
    qapp: QApplication, db_path: Path, sample_mod_tree: Path
) -> None:
    """扫描完成后进程不应因 QThread 析构 CTD；按钮恢复、状态更新。

    回归测试：修复前 _end_scanning 清空 _thread 引用，QThread 在 Running
    状态被析构，扫描完成后进程崩溃（QThread: Destroyed while thread is still running）。
    """
    from infrastructure.db import get_connection, init_db
    from infrastructure.repositories.managed_root import ManagedRootRepository

    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = __import__("sqlite3").Row
    try:
        service = ManagedRootService(
            ManagedRootRepository(conn),
            now_provider=lambda: "2026-07-07T00:00:00Z",
            uuid_provider=lambda: "scan-crash-test",
        )
        service.add_root(sample_mod_tree)
        conn.commit()
    finally:
        conn.close()

    # 用独立 service 构造窗口（不依赖已关闭连接）
    conn2 = get_connection(db_path)
    conn2.row_factory = __import__("sqlite3").Row
    service2 = ManagedRootService(ManagedRootRepository(conn2))
    window = MainWindow(service2, db_path)
    assert window.root_count() == 1

    # 选中根目录并触发扫描
    list_widget = window.findChild(QListWidget)
    assert list_widget is not None
    list_widget.setCurrentRow(0)
    assert window.is_scan_button_enabled() is True

    window._on_scan()  # noqa: SLF001（直接触发，避免按钮事件封装）
    assert window._is_scanning is True  # noqa: SLF001
    assert window.is_scan_button_enabled() is False

    # 等待扫描线程退出（最长 30 秒）
    import time

    deadline = time.monotonic() + 30.0
    while window._thread is not None and time.monotonic() < deadline:  # noqa: SLF001
        qapp.processEvents()
        time.sleep(0.05)

    # 线程引用应已被 _on_thread_finished 清空（证明线程安全退出）
    assert window._thread is None, "扫描线程未在超时内退出"
    assert window._worker is None  # noqa: SLF001
    # 按钮恢复
    assert window.is_scan_button_enabled() is True
    # 状态文本应包含扫描完成摘要
    status = window.status_text()
    assert "扫描完成" in status or "扫描失败" in status, f"状态文本异常：{status}"

    conn2.close()


def test_main_window_close_event_safe_when_idle(
    qapp: QApplication, db_connection, db_path: Path
) -> None:
    """无扫描进行时 closeEvent 应正常执行，不抛异常。"""
    window = _make_window(db_connection, db_path)
    from PySide6.QtGui import QCloseEvent

    window.closeEvent(QCloseEvent())
    # 无异常即通过
