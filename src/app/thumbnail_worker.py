"""缩略图后台生成 worker。

依据 docs/architecture.md §8：缩略图生成不在 Qt 主线程同步批量执行。
本 worker 在后台线程逐个生成缩略图，通过信号回传结果。

线程边界：
- SQLite 连接不能跨线程共享。worker 在 run() 内创建并使用独立连接，
  与主线程的 UI 查询连接隔离（与 ScanWorker 模式一致）。
- 接收 asset_id 列表，在 run() 内创建 ThumbnailCoordinator 并逐个生成。
- 通过 signal 回传每个结果，UI 线程接收后更新界面。
- 不访问 UI 控件。

使用方式：
    thread = QThread()
    worker = ThumbnailWorker(db_path, cache_dir, asset_ids)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.thumbnail_ready.connect(on_thumbnail_ready)
    worker.finished.connect(thread.quit)
    thread.start()
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from infrastructure.db import get_connection
from infrastructure.thumbnail_generator import ThumbnailResult, ThumbnailStatus

logger = logging.getLogger(__name__)


class ThumbnailWorker(QObject):
    """在后台线程逐个生成缩略图的 worker。

    信号：
    - thumbnail_ready(str, object)：单个缩略图生成完成。
      参数为 (asset_id, ThumbnailResult)。
    - finished()：全部 asset_id 处理完成。
    """

    thumbnail_ready = Signal(str, object)  # (asset_id, ThumbnailResult)
    finished = Signal()

    def __init__(
        self,
        db_path: Path,
        cache_dir: Path,
        asset_ids: list[str],
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._cache_dir = cache_dir
        self._asset_ids = list(asset_ids)

    def run(self) -> None:
        """逐个生成缩略图。捕获所有异常，不向调用线程抛出。"""
        conn: sqlite3.Connection | None = None
        try:
            # 在本线程内创建独立连接，避免跨线程共享
            conn = get_connection(self._db_path)
            conn.row_factory = sqlite3.Row

            # 延迟导入，避免循环依赖
            from application.thumbnail_coordinator import ThumbnailCoordinator
            from infrastructure.repositories.file_asset import FileAssetRepository
            from infrastructure.repositories.thumbnail_cache import (
                ThumbnailCacheRepository,
            )
            from infrastructure.thumbnail_generator import ThumbnailGenerator

            coord = ThumbnailCoordinator(
                FileAssetRepository(conn),
                ThumbnailCacheRepository(conn),
                ThumbnailGenerator(self._cache_dir),
            )

            for asset_id in self._asset_ids:
                try:
                    result = coord.generate_thumbnail(asset_id)
                    self.thumbnail_ready.emit(asset_id, result)
                except Exception:  # noqa: BLE001 - worker 边界不崩溃
                    logger.exception("缩略图生成异常：asset_id=%s", asset_id)
                    error_result = ThumbnailResult(
                        asset_id=asset_id,
                        status=ThumbnailStatus.ERROR,
                        cache_path=None,
                        error_message="缩略图生成异常",
                    )
                    self.thumbnail_ready.emit(asset_id, error_result)

            # 提交缓存记录（Repository 不自提交）
            conn.commit()
        except Exception:  # noqa: BLE001 - worker 边界需捕获所有异常
            logger.exception("缩略图 worker 初始化或执行失败")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    logger.exception("关闭缩略图 worker 连接失败")
        self.finished.emit()
