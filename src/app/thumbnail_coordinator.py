"""缩略图调度器。spec §9 / architecture.md §9。

管理 ThumbnailWorker 的生命周期与任务队列（Q5: A：单 worker + FIFO 队列）。
不冻结 UI；通过 thumbnail_ready 信号通知 MainWindow 刷新对应行。

Task 1a：支持多档缓存（256/512）。
- request_thumbnail(unit_id, source_path, size)：按指定档位请求
- pending 集合改为 (unit_id, size) 元组，允许同一 unit 不同档位并行生成
- 信号 thumbnail_ready(unit_id, size)：通知 UI 刷新对应档位

职责：
- request_thumbnail(unit_id, source_path, size)：检查缓存命中 → 同步返回 QPixmap 或 None
- 缓存未命中 → 投递到 worker 队列异步生成
- 单 worker + FIFO 队列：避免并发问题与 SQLite 锁
- 任务去重：同一 (unit_id, size) 同时仅一个生成任务在跑
- closeEvent：等待当前 worker 退出（与 ScanWorker 模式一致）

约束：
- 不在主线程访问 SQLite（避免 UI 卡顿）
- worker 在独立线程内创建独立 SQLite 连接
- 缓存命中（同步）只读 WebP 文件 + 查询 DB，性能 O(1)
"""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path

from PySide6.QtCore import QMutex, QObject, QThread, Signal
from PySide6.QtGui import QPixmap

from app.thumbnail_worker import ThumbnailWorker
from application.thumbnail_service import ThumbnailService

logger = logging.getLogger(__name__)


class ThumbnailCoordinator(QObject):
    """缩略图加载调度器。

    信号：
    - thumbnail_ready(str, int)：缩略图已生成并可用于显示。参数为 (unit_id, size)。
      MainWindow 接收后调 FileListModel.notify_thumbnail_ready(unit_id)
      触发对应行 dataChanged 重绘。
    """

    thumbnail_ready = Signal(str, int)  # unit_id, size

    def __init__(
        self,
        thumbnail_service: ThumbnailService,
        db_path: Path,
        thumbnails_dir: Path,
        size: int = 256,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = thumbnail_service
        self._db_path = db_path
        self._thumbnails_dir = thumbnails_dir
        self._size = size  # 默认档位（256，Task 1a）

        # 任务队列（FIFO）：(unit_id, source_path, size)
        self._queue: deque[tuple[str, Path, int]] = deque()
        # 在途任务集合（按 (unit_id, size) 去重）
        self._pending: set[tuple[str, int]] = set()
        self._mutex = QMutex()

        self._thread: QThread | None = None
        self._worker: ThumbnailWorker | None = None
        self._is_running = False

    # --- 公开接口 ---

    def request_thumbnail(
        self,
        content_unit_id: str,
        source_path: Path,
        size: int = 256,
    ) -> QPixmap | None:
        """请求缩略图：缓存命中同步返回 QPixmap，未命中投递后台生成。

        - 命中：返回 QPixmap（由调用方缩放到目标尺寸）
        - 未命中：返回 None，并把任务加入队列（按 (unit_id, size) 去重）
        """
        cache_path = self._service.get_cache(content_unit_id, source_path, size=size)
        if cache_path is not None:
            return self._load_pixmap(cache_path)
        # 未命中 → 投递队列（去重）
        self._enqueue(content_unit_id, source_path, size)
        return None

    def invalidate(self, content_unit_id: str) -> None:
        """失效指定内容单元的所有档位缓存（封面清除/更换时调用）。"""
        self._service.invalidate(content_unit_id)

    def shutdown(self) -> None:
        """停止队列，等待当前 worker 退出。供 MainWindow.closeEvent 调用。"""
        self._is_running = False
        # 清空待处理队列
        self._mutex.lock()
        self._queue.clear()
        self._pending.clear()
        self._mutex.unlock()
        # 等待当前 worker
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)

    # --- 内部：队列管理 ---

    def _enqueue(self, content_unit_id: str, source_path: Path, size: int) -> None:
        """投递生成任务到队列（按 (unit_id, size) 去重）。"""
        key = (content_unit_id, size)
        self._mutex.lock()
        try:
            if key in self._pending:
                return  # 已在队列或处理中
            self._pending.add(key)
            self._queue.append((content_unit_id, source_path, size))
        finally:
            self._mutex.unlock()
        self._dispatch_next()

    def _dispatch_next(self) -> None:
        """派发下一个任务（若无在途 worker）。"""
        if not self._is_running:
            return
        self._mutex.lock()
        if self._thread is not None or not self._queue:
            self._mutex.unlock()
            return
        unit_id, source_path, size = self._queue.popleft()
        self._mutex.unlock()
        self._start_worker(unit_id, source_path, size)

    def _start_worker(self, unit_id: str, source_path: Path, size: int) -> None:
        """启动 worker 处理指定任务。"""
        self._thread = QThread()
        self._worker = ThumbnailWorker(
            db_path=self._db_path,
            thumbnails_dir=self._thumbnails_dir,
            unit_id=unit_id,
            source_path=source_path,
            size=size,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.thumbnail_ready.connect(self._on_worker_ready)
        self._worker.thumbnail_failed.connect(self._on_worker_failed)
        self._worker.thumbnail_ready.connect(self._thread.quit)
        self._worker.thumbnail_failed.connect(self._thread.quit)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _on_worker_ready(self, unit_id: str, size: int, status: str) -> None:
        """worker 完成。发射 thumbnail_ready 信号通知 UI 刷新。

        Stage 4.5 H3 修复：精确移除 pending 标记，允许同一 unit 后续重新入队
        （原实现只在队列空时整体清空，导致封面更换后无法重新生成）。
        Task 1a：pending 按 (unit_id, size) 元组移除。
        """
        logger.debug("缩略图生成完成：unit_id=%s size=%d status=%s", unit_id, size, status)
        key = (unit_id, size)
        self._mutex.lock()
        self._pending.discard(key)
        self._mutex.unlock()
        self.thumbnail_ready.emit(unit_id, size)

    def _on_worker_failed(self, unit_id: str, size: int, error_message: str) -> None:
        """worker 异常。仅日志，不发射信号（避免 UI 误刷新）。

        Stage 4.5 H3 修复：同样精确移除 pending 标记。
        Task 1a：pending 按 (unit_id, size) 元组移除。
        """
        logger.warning(
            "缩略图 worker 失败：unit_id=%s size=%d err=%s",
            unit_id,
            size,
            error_message,
        )
        key = (unit_id, size)
        self._mutex.lock()
        self._pending.discard(key)
        self._mutex.unlock()

    def _on_thread_finished(self) -> None:
        """worker 线程结束：清理引用并派发下一个。"""
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
        # pending 已在 _on_worker_ready/_on_worker_failed 中精确移除
        # 此处不再需要清空（原"队列空时清空 pending"逻辑已废弃）
        self._dispatch_next()

    def _load_pixmap(self, path: Path) -> QPixmap | None:
        """加载 WebP / PNG 文件为 QPixmap。"""
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            logger.warning("加载缩略图文件失败：%s", path)
            return None
        return pixmap

    def start(self) -> None:
        """启动 coordinator（设置 is_running=True）。"""
        self._is_running = True

    # --- 测试接口 ---

    def queue_size(self) -> int:
        """返回当前队列长度（供测试）。"""
        self._mutex.lock()
        try:
            return len(self._queue)
        finally:
            self._mutex.unlock()

    def pending_count(self) -> int:
        """返回当前在途任务数（供测试）。"""
        self._mutex.lock()
        try:
            return len(self._pending)
        finally:
            self._mutex.unlock()
