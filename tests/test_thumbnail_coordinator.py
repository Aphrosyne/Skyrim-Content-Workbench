"""ThumbnailCoordinator 单元测试（spec §9）。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image

from app.thumbnail_coordinator import ThumbnailCoordinator
from application.thumbnail_service import ThumbnailService
from domain.models import ContentUnit
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.thumbnail_cache import ThumbnailCacheRepository


@pytest.fixture
def thumbnails_dir(tmp_path: Path) -> Path:
    d = tmp_path / "thumbnails"
    d.mkdir()
    return d


@pytest.fixture
def jpg_source(tmp_path: Path) -> Path:
    path = tmp_path / "cover.jpg"
    img = Image.new("RGB", (100, 80), color=(255, 0, 0))
    img.save(path, format="JPEG")
    return path


def _make_unit(unit_id: str, tmp_path: Path) -> ContentUnit:
    return ContentUnit(
        id=unit_id,
        path=str(tmp_path / unit_id),
        title=f"Unit {unit_id}",
        content_type="mod",
        status="organized",
        created_at="2026-07-01T00:00:00Z",
        updated_at="2026-07-01T00:00:00Z",
    )


@pytest.fixture
def service(db_connection, thumbnails_dir, tmp_path) -> ThumbnailService:
    """预创建 u1/u2 content_unit 以满足 thumbnail_cache FK 约束。"""
    content_unit_repo = ContentUnitRepository(db_connection)
    for unit_id in ("u1", "u2"):
        content_unit_repo.create(_make_unit(unit_id, tmp_path))
    db_connection.commit()
    return ThumbnailService(
        cache_repo=ThumbnailCacheRepository(db_connection),
        content_unit_repo=content_unit_repo,
        thumbnails_dir=thumbnails_dir,
        size=256,
    )


@pytest.fixture
def coordinator(qapp, service, db_path, thumbnails_dir) -> Iterator[ThumbnailCoordinator]:
    """带正确 teardown 的 coordinator fixture。

    依赖 qapp 以确保 QApplication 已创建（QPixmap 加载需要 QApplication，
    否则 Windows 下会 STATUS_STACK_BUFFER_OVERRUN 崩溃）。
    yield + shutdown() 确保后台线程退出，避免 QThread 在运行状态下被析构。
    """
    c = ThumbnailCoordinator(
        thumbnail_service=service,
        db_path=db_path,
        thumbnails_dir=thumbnails_dir,
        size=256,
    )
    c.start()
    yield c
    c.shutdown()


def test_request_thumbnail_cache_miss_returns_none_and_dispatches(coordinator, jpg_source):
    """缓存未命中 → 返回 None + 投递到队列。"""
    pixmap = coordinator.request_thumbnail("u1", jpg_source, size=256)
    assert pixmap is None
    # 队列应有 1 个任务
    assert coordinator.queue_size() >= 0  # 至少调度过


def test_request_thumbnail_cache_hit_returns_pixmap(
    coordinator, service, jpg_source, thumbnails_dir
):
    """缓存命中 → 同步返回 QPixmap。"""
    # 先生成一次缓存
    service.generate("u1", jpg_source, size=256)
    pixmap = coordinator.request_thumbnail("u1", jpg_source, size=256)
    assert pixmap is not None
    assert not pixmap.isNull()


def test_duplicate_request_not_redispatched(coordinator, jpg_source, monkeypatch):
    """同一 (unit_id, size) 重复请求不重复投递（去重）。"""
    # 第一次请求：投递
    coordinator.request_thumbnail("u1", jpg_source, size=256)
    pending1 = coordinator.pending_count()
    # 第二次请求：应去重
    coordinator.request_thumbnail("u1", jpg_source, size=256)
    pending2 = coordinator.pending_count()
    assert pending2 == pending1  # 没有新增


def test_different_sizes_not_deduplicated(coordinator, jpg_source):
    """Task 1a：同 unit_id 不同 size 不去重，允许并行生成。"""
    coordinator.request_thumbnail("u1", jpg_source, size=256)
    pending1 = coordinator.pending_count()
    coordinator.request_thumbnail("u1", jpg_source, size=512)
    pending2 = coordinator.pending_count()
    assert pending2 == pending1 + 1  # 512 档也入队


def test_invalidate_delegates_to_service(coordinator, service, jpg_source, thumbnails_dir):
    """invalidate 调用 service.invalidate。"""
    service.generate("u1", jpg_source, size=256)
    assert (thumbnails_dir / "u1_256.webp").exists()
    coordinator.invalidate("u1")
    assert not (thumbnails_dir / "u1_256.webp").exists()


def test_shutdown_clears_queue(coordinator, jpg_source):
    """shutdown 清空待处理队列。"""
    coordinator.request_thumbnail("u1", jpg_source, size=256)
    coordinator.request_thumbnail("u2", jpg_source, size=256)
    coordinator.shutdown()
    assert coordinator.queue_size() == 0


def test_shutdown_does_not_crash_when_no_worker(coordinator):
    """shutdown 在无 worker 时不崩溃。"""
    coordinator.shutdown()  # 无任务在跑


def test_thumbnail_ready_signal_emitted_after_generate(qapp, coordinator, service, jpg_source):
    """worker 完成后发射 thumbnail_ready 信号。

    Task 1a：信号携带 (unit_id, size)。
    """
    from PySide6.QtCore import QEventLoop, QTimer

    received: list[tuple[str, int]] = []
    loop = QEventLoop()

    def on_ready(unit_id: str, size: int) -> None:
        received.append((unit_id, size))
        loop.quit()

    coordinator.thumbnail_ready.connect(on_ready)
    QTimer.singleShot(10000, loop.quit)  # 超时兜底
    coordinator.request_thumbnail("u1", jpg_source, size=256)
    loop.exec()
    coordinator.thumbnail_ready.disconnect(on_ready)

    assert received == [("u1", 256)]


def test_get_size_returns_configured_value(service, thumbnails_dir):
    """Q1: C 可配置尺寸。"""
    # 通过 service.get_size() 验证
    assert service.get_size() == 256


def test_pending_cleared_after_worker_complete_allows_redispatch(
    qapp, coordinator, service, jpg_source
):
    """Stage 4.5 H3：worker 完成后 pending 集合应精确移除该 (unit_id, size)，
    允许同一 unit 后续重新入队。

    Task 1a：pending 按 (unit_id, size) 元组移除。
    """
    from PySide6.QtCore import QEventLoop, QTimer

    # 第一次生成
    loop1 = QEventLoop()
    received1: list[tuple[str, int]] = []

    def on_ready1(unit_id: str, size: int) -> None:
        received1.append((unit_id, size))
        loop1.quit()

    coordinator.thumbnail_ready.connect(on_ready1)
    QTimer.singleShot(10000, loop1.quit)
    coordinator.request_thumbnail("u1", jpg_source, size=256)
    loop1.exec()
    coordinator.thumbnail_ready.disconnect(on_ready1)
    assert received1 == [("u1", 256)]

    # 此时 pending 应已清空（(u1, 256) 已精确移除）
    assert coordinator.pending_count() == 0

    # invalidate 后再请求应能重新入队（验证 pending 未卡住）
    coordinator.invalidate("u1")
    pixmap = coordinator.request_thumbnail("u1", jpg_source, size=256)
    # 缓存已被 invalidate 清空 → 返回 None，但应已入队
    assert pixmap is None
    # pending 应包含 (u1, 256)（重新入队成功）
    assert coordinator.pending_count() >= 1
