"""扫描后台 worker。

依据 architecture §2 UI 分层规则、D4 决策：Qt 后台线程包裹同步扫描器。

线程边界：
- SQLite 连接不能跨线程共享。worker 在 run() 内创建并使用独立连接，
  与主线程的 UI 查询连接隔离。
- worker 仅调用 ScanService（同步），不访问 UI。
- worker 不写用户文件；仅通过 FileScanner 只读 API + Repository 写应用数据库。

使用方式（在 MainWindow 中）：
    thread = QThread()
    worker = ScanWorker(db_path, root_id, incremental=True)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.scan_finished.connect(...)
    worker.scan_failed.connect(...)
    worker.scan_finished.connect(thread.quit)
    worker.scan_failed.connect(thread.quit)
    thread.start()
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from application.scan_service import ScanService, ScanSummary
from infrastructure.db import get_connection
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.folder_cache import FolderCacheRepository
from infrastructure.repositories.managed_root import ManagedRootRepository
from infrastructure.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)


class ScanWorker(QObject):
    """在后台线程执行扫描的 worker。

    信号：
    - scan_started：扫描开始。
    - scan_progress(str)：进度文本（本任务仅发送"正在扫描…"）。
    - scan_finished(ScanSummary)：扫描成功完成（含错误摘要时也触发）。
    - scan_failed(str)：扫描过程中抛出未预期异常。
    """

    scan_started = Signal()
    scan_progress = Signal(str)
    scan_finished = Signal(object)  # ScanSummary
    scan_failed = Signal(str)  # 用户可读错误消息

    def __init__(
        self,
        db_path: Path,
        root_id: str,
        incremental: bool = True,
        archive_root: Path | None = None,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._root_id = root_id
        self._incremental = incremental
        self._archive_root = archive_root

    def run(self) -> None:
        """执行扫描。在 worker 所在线程内同步运行。

        本方法捕获所有异常并转为 scan_failed 信号，不向调用线程抛出。
        """
        conn: sqlite3.Connection | None = None
        try:
            # 在本线程内创建独立连接，避免跨线程共享
            # timeout=30.0：容忍主线程偶发的长事务（如元数据保存），
            # 避免短暂写锁冲突导致 "database is locked"（Stage 4.5 回归加固）
            conn = get_connection(self._db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row

            managed_root_repo = ManagedRootRepository(conn)
            folder_cache_repo = FolderCacheRepository(conn)
            content_unit_repo = ContentUnitRepository(conn)
            # Stage 4.5 D3：注入 UnitOfWork，Service 内部管理事务边界。
            # scan_worker（调用方）不再负责 commit/rollback，事务由 ScanService
            # 的 _persist_scan_result 在 transaction() 内自动提交/回滚。
            service = ScanService(
                managed_root_repo=managed_root_repo,
                folder_cache_repo=folder_cache_repo,
                content_unit_repo=content_unit_repo,
                uow=UnitOfWork(conn),
                archive_root=self._archive_root,
            )

            self.scan_started.emit()
            self.scan_progress.emit("正在扫描…")
            summary: ScanSummary = service.scan_root(self._root_id, incremental=self._incremental)
            self.scan_finished.emit(summary)
        except Exception as e:  # noqa: BLE001 - worker 边界需捕获所有异常
            logger.exception("后台扫描失败：root_id=%s", self._root_id)
            self.scan_failed.emit(f"扫描失败：{e}")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    logger.exception("关闭扫描 worker 连接失败")
