"""缩略图后台生成 worker。spec §9 / architecture.md §9。

在 QThread 中执行 ThumbnailService.generate，独立 SQLite 连接。
不冻结 UI；通过信号回调通知完成。

Task 1a：支持多档缓存（256/512），信号新增 size 参数。

线程边界：
- SQLite 连接不能跨线程共享。worker 在 run() 内创建并使用独立连接。
- worker 仅调用 ThumbnailService.generate（同步），不访问 UI。

使用方式（由 ThumbnailCoordinator 调度）：
    thread = QThread()
    worker = ThumbnailWorker(db_path, thumbnails_dir, unit_id, source_path, size=256)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.thumbnail_ready.connect(coordinator._on_worker_ready, Qt.QueuedConnection)
    worker.thumbnail_failed.connect(coordinator._on_worker_failed, Qt.QueuedConnection)
    worker.thumbnail_ready.connect(thread.quit)
    worker.thumbnail_failed.connect(thread.quit)
    thread.start()
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from application.thumbnail_service import ThumbnailService
from infrastructure.db import get_connection
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.thumbnail_cache import ThumbnailCacheRepository

logger = logging.getLogger(__name__)


class ThumbnailWorker(QObject):
    """在后台线程生成缩略图的 worker。

    信号：
    - thumbnail_ready(str, int, str)：生成完成。(unit_id, size, status)
      status 取值与 ThumbnailCache.status 一致（'ok' / 'missing' / 'corrupt' /
      'unsupported' / 'error'）。status='ok' 表示缓存命中可用，其他表示失败。
    - thumbnail_failed(str, int, str)：生成过程抛出未预期异常。(unit_id, size, error_message)
    """

    thumbnail_ready = Signal(str, int, str)  # unit_id, size, status
    thumbnail_failed = Signal(str, int, str)  # unit_id, size, error_message

    def __init__(
        self,
        db_path: Path,
        thumbnails_dir: Path,
        unit_id: str,
        source_path: Path,
        size: int = 256,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._thumbnails_dir = thumbnails_dir
        self._unit_id = unit_id
        self._source_path = source_path
        self._size = size

    def run(self) -> None:
        """执行生成。捕获所有异常并转为信号。"""
        conn: sqlite3.Connection | None = None
        try:
            # timeout=30.0：容忍主线程偶发的长事务（Stage 4.5 回归加固）
            conn = get_connection(self._db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            service = ThumbnailService(
                cache_repo=ThumbnailCacheRepository(conn),
                content_unit_repo=ContentUnitRepository(conn),
                thumbnails_dir=self._thumbnails_dir,
                size=self._size,
            )
            status = service.generate(self._unit_id, self._source_path, size=self._size)
            conn.commit()
            self.thumbnail_ready.emit(self._unit_id, self._size, status)
        except Exception as e:  # noqa: BLE001
            logger.exception("缩略图 worker 异常：unit_id=%s size=%d", self._unit_id, self._size)
            self.thumbnail_failed.emit(self._unit_id, self._size, str(e))
        finally:
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    logger.exception("关闭缩略图 worker 连接失败")

    @property
    def unit_id(self) -> str:
        """返回 worker 处理的 unit_id（供 coordinator 去重判断）。"""
        return self._unit_id

    @property
    def size(self) -> int:
        """返回 worker 处理的 size（供 coordinator 去重判断）。"""
        return self._size
