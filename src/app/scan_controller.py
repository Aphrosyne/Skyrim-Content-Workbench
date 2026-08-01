"""扫描控制器（UX 重构 Task 7 Step 2，TD-M21/M26 + TD-M13）。

封装 ScanWorker + QThread 生命周期（含 TD-H4/H5 sender 竞态校验），
通过 Qt 信号向 UI 转发扫描状态。MainWindow 只负责 UI 状态联动
（按钮禁用、状态栏、目录树/中栏刷新）。

线程边界：
- worker 在自身线程创建独立 SQLite 连接（见 ScanWorker.run）。
- 控制器只管理线程生命周期与信号转发，不访问 UI 控件。
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from app.scan_worker import ScanWorker

logger = logging.getLogger(__name__)


class ScanController(QObject):
    """扫描线程生命周期控制器。

    信号：
    - ``scan_started()``：扫描开始（UI 应禁用扫描入口）。
    - ``scan_progress(str)``：进度文本（TD-M13：转发 ScanWorker.scan_progress）。
    - ``scan_finished(object)``：ScanSummary。
    - ``scan_failed(str)``：用户可读错误消息。
    """

    scan_started = Signal()
    scan_progress = Signal(str)
    scan_finished = Signal(object)  # ScanSummary
    scan_failed = Signal(str)

    def __init__(self, db_path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None
        self._is_scanning = False

    def is_scanning(self) -> bool:
        """返回当前是否有扫描在进行。"""
        return self._is_scanning

    def start_scan(self, root_id: str, incremental: bool = True) -> None:
        """启动后台扫描；扫描进行中重复调用忽略。"""
        if self._is_scanning:
            return
        self._is_scanning = True
        self.scan_started.emit()

        self._thread = QThread()
        self._worker = ScanWorker(self._db_path, root_id, incremental=incremental)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        # TD-M13：转发进度文本（ScanWorker 目前仅发送"正在扫描…"）
        self._worker.scan_progress.connect(self.scan_progress)
        self._worker.scan_finished.connect(self._thread.quit)
        self._worker.scan_failed.connect(self._thread.quit)
        self._worker.scan_finished.connect(self._on_worker_finished)
        self._worker.scan_failed.connect(self._on_worker_failed)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def shutdown(self) -> None:
        """关闭窗口前等待扫描线程退出，避免 QThread Running 析构崩溃（TD-H5）。"""
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)

    # --- 内部：worker/线程回调 ---

    def _on_worker_finished(self, summary) -> None:
        """worker 扫描完成 → 恢复状态并转发摘要。"""
        self._is_scanning = False
        self.scan_finished.emit(summary)

    def _on_worker_failed(self, message: str) -> None:
        """worker 扫描失败 → 恢复状态并转发错误。"""
        self._is_scanning = False
        self.scan_failed.emit(message)

    def _on_thread_finished(self) -> None:
        """QThread 真正退出后清理 Python 引用（TD-H4/H5 竞态校验）。

        仅当退出的线程是当前扫描线程（self._thread）时才清除引用，
        避免旧线程退出时误清除新扫描线程的引用。
        """
        sender = self.sender()
        if sender is self._thread:
            self._worker = None
            self._thread = None
