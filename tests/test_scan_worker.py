"""ScanWorker 测试。

覆盖：
- 后台扫描成功结果可通过 scan_finished 信号回传；
- ScanError 可通过 scan_finished 信号回传（错误计入摘要）；
- root_id 不存在时通过 scan_failed 信号回传；
- worker 在自身线程创建独立 SQLite 连接。

通过 _Harness 的 Python 属性捕获结果（harness 与 worker 通过信号/槽跨线程通信，
槽在主线程事件循环中处理）。
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, QThread, Signal  # noqa: E402

from app.scan_worker import ScanWorker  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402


class _Harness(QObject):
    """辅助对象：在独立线程中运行 worker，并通过信号将结果回传主线程。

    scan_finished/scan_failed 是 ScanWorker 的信号，从 worker 线程发射，
    Qt 自动跨线程投递到主线程事件循环，由 _on_finished/_on_failed 处理。
    """

    finished_with_summary = Signal(object)
    finished_with_error = Signal(str)

    def __init__(self, db_path: Path, root_id: str) -> None:
        super().__init__()
        self._db_path = db_path
        self._root_id = root_id
        self.thread: QThread | None = None
        self.worker: ScanWorker | None = None
        self.summary: object | None = None
        self.error: str | None = None

    def start(self) -> None:
        self.thread = QThread()
        self.worker = ScanWorker(self._db_path, self._root_id)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.scan_finished.connect(self._on_finished)
        self.worker.scan_failed.connect(self._on_failed)
        self.worker.scan_finished.connect(self.thread.quit)
        self.worker.scan_failed.connect(self.thread.quit)
        self.thread.start()

    def _on_finished(self, summary) -> None:
        self.summary = summary

    def _on_failed(self, message: str) -> None:
        self.error = message


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _run_worker(
    qapp, db_path: Path, root_id: str, timeout_ms: int = 30000
) -> tuple[object | None, str | None]:
    """运行 worker 至完成，返回 (summary, error_message)。"""
    harness = _Harness(db_path, root_id)
    harness.start()

    # 轮询等待结果到达主线程
    assert harness.thread is not None
    deadline = time.monotonic() + timeout_ms / 1000.0
    while harness.summary is None and harness.error is None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    # 等线程完全退出
    harness.thread.wait(5000)
    return harness.summary, harness.error


def test_scan_worker_emits_summary_on_success(qapp, db_path: Path, sample_mod_tree: Path) -> None:
    """成功扫描通过 scan_finished 信号回传 ScanSummary。"""
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        service = ManagedRootService(
            ManagedRootRepository(conn),
            now_provider=lambda: "2026-07-07T00:00:00Z",
            uuid_provider=lambda: "worker-root",
        )
        root = service.add_root(sample_mod_tree)
        conn.commit()
        root_id = root.id
    finally:
        conn.close()

    summary, error = _run_worker(qapp, db_path, root_id)
    assert error is None, f"预期 scan_finished 但收到 scan_failed：{error}"
    assert summary is not None
    assert summary.root_id == root_id
    assert summary.scanned_folders == 4
    assert summary.scanned_files == 7
    assert summary.error_count == 0


def test_scan_worker_emits_summary_with_errors_for_missing_dir(
    qapp, db_path: Path, tmp_path: Path
) -> None:
    """根目录在扫描前被删除，worker 仍通过 scan_finished 回传含错误的摘要。"""
    init_db(db_path)
    target = tmp_path / "deleted"
    target.mkdir()

    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        service = ManagedRootService(
            ManagedRootRepository(conn),
            now_provider=lambda: "2026-07-07T00:00:00Z",
            uuid_provider=lambda: "worker-missing",
        )
        root = service.add_root(target)
        conn.commit()
        root_id = root.id
    finally:
        conn.close()

    # 删除目录
    target.rmdir()

    summary, error = _run_worker(qapp, db_path, root_id)
    assert error is None, "缺失目录应通过 scan_finished 回传错误摘要，而非 scan_failed"
    assert summary is not None
    assert summary.error_count >= 1
    assert summary.scanned_folders == 0


def test_scan_worker_emits_failed_for_unknown_root(qapp, db_path: Path) -> None:
    """root_id 不存在时 worker 通过 scan_failed 信号回传错误。"""
    init_db(db_path)

    summary, error = _run_worker(qapp, db_path, "nonexistent-root-id")
    assert summary is None
    assert error is not None
    assert "不存在" in error or "失败" in error


def test_scan_worker_creates_independent_connection(
    qapp, db_path: Path, sample_mod_tree: Path
) -> None:
    """worker 在自身线程内创建独立 SQLite 连接，不依赖主线程连接。"""
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        service = ManagedRootService(
            ManagedRootRepository(conn),
            now_provider=lambda: "2026-07-07T00:00:00Z",
            uuid_provider=lambda: "worker-indep",
        )
        root = service.add_root(sample_mod_tree)
        conn.commit()
        root_id = root.id
    finally:
        # 主线程连接关闭——worker 必须使用自身连接
        conn.close()

    summary, error = _run_worker(qapp, db_path, root_id)
    assert error is None, f"worker 应独立连接 DB：{error}"
    assert summary is not None
    assert summary.scanned_files == 7


def test_scan_worker_persists_results_to_db(qapp, db_path: Path, sample_mod_tree: Path) -> None:
    """扫描完成后数据必须已提交到 DB，用独立连接可查到 folder_node 记录。

    回归测试：修复前 ScanWorker.run 在 conn.close() 前未调用 conn.commit()，
    persist_scan_result 与 Repository.create 均不自提交，导致未提交事务被
    回滚，扫描结果丢失，目录树始终显示"未扫描"。
    """
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        service = ManagedRootService(
            ManagedRootRepository(conn),
            now_provider=lambda: "2026-07-07T00:00:00Z",
            uuid_provider=lambda: "worker-persist",
        )
        root = service.add_root(sample_mod_tree)
        conn.commit()
        root_id = root.id
    finally:
        conn.close()

    summary, error = _run_worker(qapp, db_path, root_id)
    assert error is None, f"扫描不应失败：{error}"
    assert summary is not None
    assert summary.persisted_folders > 0, "应有持久化的目录节点"

    # 用全新独立连接查询——验证事务已提交，不依赖 worker 的连接
    verify_conn = get_connection(db_path)
    verify_conn.row_factory = sqlite3.Row
    try:
        rows = verify_conn.execute("SELECT COUNT(*) AS n FROM folder_node").fetchone()
        assert rows["n"] > 0, "扫描后 folder_node 表为空，事务未提交"

        # 验证根节点 is_managed_root=1
        root_rows = verify_conn.execute(
            "SELECT COUNT(*) AS n FROM folder_node WHERE is_managed_root = 1"
        ).fetchone()
        assert root_rows["n"] >= 1, "未找到 is_managed_root=1 的根节点"

        # 验证文件也持久化
        file_rows = verify_conn.execute("SELECT COUNT(*) AS n FROM file_asset").fetchone()
        assert file_rows["n"] > 0, "扫描后 file_asset 表为空，事务未提交"
    finally:
        verify_conn.close()
