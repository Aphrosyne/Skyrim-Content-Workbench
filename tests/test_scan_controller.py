"""ScanController 单元测试（UX 重构 Task 7 Step 2，TD-H4/H5 + TD-M13 接线）。"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QThread  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.scan_controller import ScanController  # noqa: E402


@pytest.fixture
def controller(qapp: QApplication, tmp_path: Path) -> ScanController:
    return ScanController(tmp_path / "test.db")


class TestOnThreadFinishedSenderCheck:
    """TD-H4 修复：_on_thread_finished 校验 sender 是否为当前扫描线程。"""

    def test_direct_call_does_not_clear_non_none_thread(self, controller: ScanController) -> None:
        """直接调用（sender 返回 None）不清除非 None 的 _thread。

        模拟竞态场景：旧线程退出触发 _on_thread_finished，但 self._thread
        已被新扫描线程覆盖。此时 sender（旧线程）!= self._thread（新线程），
        不应清除引用。
        """
        fake_new_thread = QThread()
        controller._thread = fake_new_thread  # noqa: SLF001

        controller._on_thread_finished()  # noqa: SLF001

        assert controller._thread is fake_new_thread  # noqa: SLF001
        fake_new_thread.deleteLater()

    def test_clears_reference_when_sender_matches(
        self, qapp: QApplication, controller: ScanController
    ) -> None:
        """正常流程：sender 匹配时清除引用。"""
        thread = QThread()
        controller._thread = thread  # noqa: SLF001
        thread.finished.connect(controller._on_thread_finished)  # noqa: SLF001

        thread.start()
        thread.quit()
        assert thread.wait(2000), "线程未在超时内退出"
        qapp.processEvents()

        assert controller._thread is None  # noqa: SLF001

    def test_old_thread_exit_does_not_clear_new_thread_reference(
        self, qapp: QApplication, controller: ScanController
    ) -> None:
        """旧线程退出时不误清除新线程引用（TD-H4 核心竞态场景）。"""
        thread_a = QThread()
        controller._thread = thread_a  # noqa: SLF001
        thread_a.finished.connect(controller._on_thread_finished)  # noqa: SLF001

        # 扫描 B 覆盖引用（模拟用户立即点击新扫描）
        thread_b = QThread()
        controller._thread = thread_b  # noqa: SLF001

        thread_a.start()
        thread_a.quit()
        assert thread_a.wait(2000), "线程 A 未在超时内退出"
        qapp.processEvents()

        assert controller._thread is thread_b  # noqa: SLF001
        thread_b.deleteLater()


class TestScanningState:
    """扫描状态与信号转发（TD-M13 接线）。"""

    def test_start_scan_sets_state_and_emits_started(
        self, controller: ScanController, tmp_path: Path
    ) -> None:
        """start_scan 置 is_scanning=True 并发射 scan_started。"""
        started: list[bool] = []
        controller.scan_started.connect(lambda: started.append(True))

        controller.start_scan("root-id", incremental=True)

        assert controller.is_scanning() is True
        assert len(started) == 1
        # 扫描进行中重复调用忽略
        controller.start_scan("root-id")
        assert len(started) == 1
        controller.shutdown()

    def test_worker_finished_resets_state_and_forwards_summary(
        self, controller: ScanController
    ) -> None:
        """worker 完成 → is_scanning 复位 + scan_finished 转发摘要。"""
        received: list[object] = []
        controller.scan_finished.connect(received.append)
        controller._is_scanning = True  # noqa: SLF001

        controller._on_worker_finished("summary")  # noqa: SLF001

        assert controller.is_scanning() is False
        assert received == ["summary"]

    def test_worker_failed_resets_state_and_forwards_error(
        self, controller: ScanController
    ) -> None:
        """worker 失败 → is_scanning 复位 + scan_failed 转发错误。"""
        received: list[str] = []
        controller.scan_failed.connect(received.append)
        controller._is_scanning = True  # noqa: SLF001

        controller._on_worker_failed("扫描失败：boom")  # noqa: SLF001

        assert controller.is_scanning() is False
        assert received == ["扫描失败：boom"]

    def test_scan_progress_signal_forwarded(self, controller: ScanController) -> None:
        """scan_progress 信号可被 UI 连接（TD-M13：MainWindow._on_scan_progress）。"""
        received: list[str] = []
        controller.scan_progress.connect(received.append)

        controller.scan_progress.emit("正在扫描…")

        assert received == ["正在扫描…"]


class TestCloseEventThreadSafety:
    """TD-H5 修复：shutdown() 能正确等待当前运行的线程。"""

    def test_shutdown_waits_for_running_thread(
        self, qapp: QApplication, controller: ScanController
    ) -> None:
        """shutdown() 在扫描线程运行时调用 quit + wait，不崩溃。"""
        thread = QThread()
        controller._thread = thread  # noqa: SLF001

        thread.start()
        qapp.processEvents()

        controller.shutdown()

        assert not thread.isRunning()
