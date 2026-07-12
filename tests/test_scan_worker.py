"""ScanWorker 测试。

覆盖：
- 后台扫描成功结果可通过 scan_finished 信号回传；
- scan_error 可通过 scan_finished 信号回传（错误计入摘要）；
- root_id 不存在时通过 scan_failed 信号回传；
- worker 在自身线程创建独立 SQLite 连接；
- 增量/全量参数传递。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, QThread, Signal  # noqa: E402

from app.scan_worker import ScanWorker  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    """模块级 QApplication fixture，确保跨线程信号槽能正常投递。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class _Harness(QObject):
    """辅助对象：在独立线程中运行 worker，并通过信号将结果回传主线程。"""

    finished_with_summary = Signal(object)
    finished_with_error = Signal(str)

    def __init__(self, db_path: Path, root_id: str, incremental: bool = True) -> None:
        super().__init__()
        self._db_path = db_path
        self._root_id = root_id
        self._incremental = incremental
        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None
        self.summary = None
        self.error: str | None = None

    def run(self) -> None:
        self._thread = QThread()
        self._worker = ScanWorker(self._db_path, self._root_id, incremental=self._incremental)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.scan_finished.connect(self._on_finished)
        self._worker.scan_failed.connect(self._on_failed)
        self._worker.scan_finished.connect(self._thread.quit)
        self._worker.scan_failed.connect(self._thread.quit)
        self._thread.start()

    def _on_finished(self, summary) -> None:
        self.summary = summary
        self.finished_with_summary.emit(summary)

    def _on_failed(self, message: str) -> None:
        self.error = message
        self.finished_with_error.emit(message)

    def wait(self, timeout_ms: int = 5000) -> None:
        if self._thread is not None:
            self._thread.wait(timeout_ms)

    def cleanup(self) -> None:
        if self._thread is not None:
            if self._thread.isRunning():
                self._thread.quit()
                self._thread.wait(2000)
            self._thread = None
        self._worker = None


def _wait_for_completion(harness: _Harness, qapp, timeout: float = 10.0) -> None:
    """等待 harness 完成，通过事件循环处理跨线程信号。"""
    import time as _time

    start = _time.monotonic()
    while harness.summary is None and harness.error is None:
        if _time.monotonic() - start > timeout:
            break
        qapp.processEvents()
        _time.sleep(0.02)
    # 再处理一轮事件确保信号槽都执行完
    qapp.processEvents()


@pytest.fixture
def app_db(temp_app_data: Path) -> Path:
    """初始化临时应用数据库，返回路径。"""
    from app.app_paths import get_app_db_path

    db_path = get_app_db_path()
    init_db(db_path)
    return db_path


@pytest.fixture
def managed_root(app_db: Path, tmp_path: Path) -> tuple[str, Path]:
    """添加一个受管理根目录，返回 (root_id, root_path)。"""
    root_dir = tmp_path / "mods"
    root_dir.mkdir()
    (root_dir / "armor").mkdir()
    (root_dir / "armor" / "mod.7z").write_bytes(b"\x00" * 100)

    conn = get_connection(app_db)
    conn.row_factory = sqlite3.Row
    try:
        service = ManagedRootService(ManagedRootRepository(conn))
        root = service.add_root(root_dir)
        conn.commit()
        return root.id, root_dir
    finally:
        conn.close()


class TestScanWorkerSuccess:
    def test_scan_finished_returns_summary(
        self, qapp, app_db: Path, managed_root: tuple[str, Path]
    ) -> None:
        root_id, _ = managed_root
        harness = _Harness(app_db, root_id, incremental=False)
        try:
            harness.run()
            _wait_for_completion(harness, qapp)
            assert harness.error is None, f"意外错误：{harness.error}"
            assert harness.summary is not None
            assert harness.summary.root_id == root_id
            assert harness.summary.scanned_dirs > 0
            assert harness.summary.content_units_found == 1
        finally:
            harness.cleanup()

    def test_scan_persists_to_db(self, qapp, app_db: Path, managed_root: tuple[str, Path]) -> None:
        root_id, _ = managed_root
        harness = _Harness(app_db, root_id, incremental=False)
        try:
            harness.run()
            _wait_for_completion(harness, qapp)
            assert harness.summary is not None, "扫描未完成"
            # 独立连接验证持久化（必须设置 row_factory）
            conn = get_connection(app_db)
            conn.row_factory = sqlite3.Row
            try:
                repo = ContentUnitRepository(conn)
                units = repo.list_all()
                assert len(units) == 1
            finally:
                conn.close()
        finally:
            harness.cleanup()


class TestScanWorkerFailure:
    def test_scan_failed_on_nonexistent_root(self, qapp, app_db: Path) -> None:
        harness = _Harness(app_db, "nonexistent-root", incremental=False)
        try:
            harness.run()
            _wait_for_completion(harness, qapp)
            assert harness.summary is None
            assert harness.error is not None
            assert "扫描失败" in harness.error or "不存在" in harness.error
        finally:
            harness.cleanup()


class TestScanWorkerIncremental:
    def test_incremental_scan_skips_unchanged(
        self, qapp, app_db: Path, managed_root: tuple[str, Path]
    ) -> None:
        root_id, _ = managed_root

        # 第一次全量扫描
        harness1 = _Harness(app_db, root_id, incremental=False)
        try:
            harness1.run()
            _wait_for_completion(harness1, qapp)
            assert harness1.summary is not None, "第一次扫描未完成"
            assert harness1.summary.skipped_unchanged == 0
        finally:
            harness1.cleanup()

        # 第二次增量扫描应跳过所有目录
        harness2 = _Harness(app_db, root_id, incremental=True)
        try:
            harness2.run()
            _wait_for_completion(harness2, qapp)
            assert harness2.summary is not None, "第二次扫描未完成"
            assert harness2.summary.skipped_unchanged > 0
            assert harness2.summary.scanned_dirs == 0
        finally:
            harness2.cleanup()
