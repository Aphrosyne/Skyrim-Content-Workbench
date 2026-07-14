"""MainWindow 扫描线程生命周期测试（TD-H4 + TD-H5 修复）。

覆盖：
- _on_thread_finished 仅当 sender 是当前扫描线程时才清除引用；
- 旧线程退出时不误清除新扫描线程的引用（竞态修复）；
- 正常流程下 sender 匹配时引用被正确清除。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QThread  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.main_window import MainWindow  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.folder_cache import FolderCacheRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402


@pytest.fixture
def main_window(qapp: QApplication, tmp_path: Path) -> MainWindow:
    """构造一个最小化的 MainWindow（不添加根目录、不扫描）。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row

    counter = {"n": 0}

    def fake_uuid() -> str:
        counter["n"] += 1
        return f"id-{counter['n']}"

    managed_service = ManagedRootService(
        ManagedRootRepository(conn),
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    tree_service = FolderTreeService(
        ManagedRootRepository(conn),
        FolderCacheRepository(conn),
    )
    content_service = ContentService(ContentUnitRepository(conn))

    window = MainWindow(
        managed_service,
        tree_service,
        content_service,
        db_path,
        commit_callback=conn.commit,
    )
    yield window
    window.close()
    conn.close()


class TestOnThreadFinishedSenderCheck:
    """TD-H4 修复：_on_thread_finished 校验 sender 是否为当前扫描线程。"""

    def test_direct_call_does_not_clear_non_none_thread(self, main_window: MainWindow) -> None:
        """直接调用 _on_thread_finished（sender 返回 None）不清除非 None 的 _thread。

        模拟竞态场景：旧线程退出触发 _on_thread_finished，但 self._thread
        已被新扫描线程覆盖。此时 sender（旧线程）!= self._thread（新线程），
        不应清除引用。

        直接调用时 sender() 返回 None，等价于"sender 不匹配"。
        """
        # 模拟新扫描线程已覆盖 self._thread
        fake_new_thread = QThread()
        main_window._thread = fake_new_thread  # noqa: SLF001

        # 直接调用（sender() 返回 None，不匹配 self._thread）
        main_window._on_thread_finished()  # noqa: SLF001

        # 引用不应被清除（仍指向新线程）
        assert main_window._thread is fake_new_thread  # noqa: SLF001

    def test_clears_reference_when_sender_matches(
        self, qapp: QApplication, main_window: MainWindow
    ) -> None:
        """正常流程：sender 匹配时清除引用。

        创建真实 QThread，连接 finished 信号到 _on_thread_finished，
        线程退出后 sender == self._thread，引用应被清除。
        """
        thread = QThread()
        main_window._thread = thread  # noqa: SLF001
        thread.finished.connect(main_window._on_thread_finished)  # noqa: SLF001

        thread.start()
        thread.quit()
        assert thread.wait(2000), "线程未在超时内退出"
        qapp.processEvents()

        # sender 匹配，引用应被清除
        assert main_window._thread is None  # noqa: SLF001

    def test_old_thread_exit_does_not_clear_new_thread_reference(
        self, qapp: QApplication, main_window: MainWindow
    ) -> None:
        """旧线程退出时不误清除新线程引用（TD-H4 核心竞态场景）。

        场景：
        1. 启动扫描 A，self._thread = thread_a
        2. 扫描 A 完成，_on_scan_finished 恢复按钮（_is_scanning=False）
        3. 用户立即点击扫描 B，self._thread = thread_b（覆盖 thread_a）
        4. thread_a 退出，触发 _on_thread_finished（sender=thread_a）
        5. thread_a != self._thread(thread_b)，不应清除引用
        """
        # 步骤 1：启动扫描 A
        thread_a = QThread()
        main_window._thread = thread_a  # noqa: SLF001
        thread_a.finished.connect(main_window._on_thread_finished)  # noqa: SLF001

        # 步骤 3：扫描 B 覆盖引用（模拟用户立即点击新扫描）
        thread_b = QThread()
        main_window._thread = thread_b  # noqa: SLF001

        # 步骤 4：旧线程 A 退出
        thread_a.start()
        thread_a.quit()
        assert thread_a.wait(2000), "线程 A 未在超时内退出"
        qapp.processEvents()

        # 步骤 5：引用仍应指向新线程 B
        assert main_window._thread is thread_b  # noqa: SLF001

        # 清理
        thread_b.deleteLater()


class TestCloseEventThreadSafety:
    """TD-H5 修复：closeEvent 能正确等待当前运行的线程。"""

    def test_close_event_waits_for_running_thread(
        self, qapp: QApplication, main_window: MainWindow
    ) -> None:
        """closeEvent 在有线程运行时调用 quit + wait，不崩溃。

        修复 TD-H4 后，self._thread 始终指向当前运行的线程，
        closeEvent 能正确等待其退出。
        """
        thread = QThread()
        main_window._thread = thread  # noqa: SLF001

        thread.start()
        qapp.processEvents()

        # 模拟关闭窗口（closeEvent 会调用 thread.quit + wait）
        main_window.close()
        qapp.processEvents()

        # 线程应已退出
        assert not thread.isRunning()
