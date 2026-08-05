"""MainWindow 缩略图集成测试（Stage 4 Task 4）。

覆盖：
- coordinator 未注入 → 文件列表退化为标准图标
- coordinator 已注入 → provider 注入到 CardListModel（UI合理性16）
- 卡片缩略图全链路：未命中占位 → 后台生成 → ready 刷新 → 二次命中缓存
- metadata_saved → 失效缓存
- closeEvent → 调用 coordinator.shutdown
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from PIL import Image

pytest.importorskip("PySide6")

from app.main_window import MainWindow  # noqa: E402
from app.thumbnail_coordinator import ThumbnailCoordinator  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from application.tag_service import TagService  # noqa: E402
from application.thumbnail_service import ThumbnailService  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.repositories.content_unit import (  # noqa: E402
    ContentUnitRepository,
)
from infrastructure.repositories.content_unit_tag import (  # noqa: E402
    ContentUnitTagRepository,
)
from infrastructure.repositories.folder_cache import (  # noqa: E402
    FolderCacheRepository,
)
from infrastructure.repositories.managed_root import (  # noqa: E402
    ManagedRootRepository,
)
from infrastructure.repositories.tag import TagRepository  # noqa: E402
from infrastructure.repositories.tag_category import (  # noqa: E402
    TagCategoryRepository,
)
from infrastructure.repositories.thumbnail_cache import (  # noqa: E402
    ThumbnailCacheRepository,
)


def _make_mod_tree(tmp_path: Path) -> Path:
    """构造含封面图片的测试目录树。"""
    root = tmp_path / "mods"
    root.mkdir()
    armor = root / "护甲"
    armor.mkdir()
    (armor / "寒霜之心.7z").write_bytes(b"\x00" * 100)
    # 创建封面图片
    cover_path = armor / "cover.jpg"
    img = Image.new("RGB", (100, 80), color=(255, 0, 0))
    img.save(cover_path, format="JPEG")
    return root


@pytest.fixture
def env_with_coordinator(qapp, tmp_path: Path):
    """构造含 thumbnail_coordinator 的 MainWindow 测试环境。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row

    thumbnails_dir = tmp_path / "thumbnails"
    thumbnails_dir.mkdir()

    counter = {"n": 0}

    def fake_uuid() -> str:
        counter["n"] += 1
        return f"id-{counter['n']}"

    managed_service = ManagedRootService(
        ManagedRootRepository(conn),
        FolderCacheRepository(conn),
        ContentUnitRepository(conn),
        now_provider=lambda: "2026-07-19T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    tree_service = FolderTreeService(
        ManagedRootRepository(conn),
        FolderCacheRepository(conn),
    )
    content_service = ContentService(ContentUnitRepository(conn))
    tag_service = TagService(
        TagCategoryRepository(conn),
        TagRepository(conn),
        ContentUnitTagRepository(conn),
    )
    thumbnail_service = ThumbnailService(
        cache_repo=ThumbnailCacheRepository(conn),
        content_unit_repo=ContentUnitRepository(conn),
        thumbnails_dir=thumbnails_dir,
        size=64,
    )
    coordinator = ThumbnailCoordinator(
        thumbnail_service=thumbnail_service,
        db_path=db_path,
        thumbnails_dir=thumbnails_dir,
        size=64,
    )
    scan_service = ScanService(
        managed_root_repo=ManagedRootRepository(conn),
        folder_cache_repo=FolderCacheRepository(conn),
        content_unit_repo=ContentUnitRepository(conn),
    )

    mods_root = _make_mod_tree(tmp_path)
    managed_service.add_root(mods_root)
    scan_service.scan_root(managed_service.list_roots()[0].id, incremental=False)
    conn.commit()

    window = MainWindow(
        managed_service,
        tree_service,
        content_service,
        db_path,
        commit_callback=conn.commit,
        tag_service=tag_service,
        thumbnail_coordinator=coordinator,
    )
    window.show()
    qapp.processEvents()
    yield window, coordinator, conn, mods_root
    window.close()


def test_coordinator_not_injected_degrades_to_standard_icons(qapp, tmp_path):
    """未注入 coordinator → FileListModel 无 provider，仍能正常显示。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    managed_service = ManagedRootService(
        ManagedRootRepository(conn),
        FolderCacheRepository(conn),
        ContentUnitRepository(conn),
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
    assert window._thumbnail_coordinator is None  # noqa: SLF001


def test_coordinator_injected_starts_without_error(env_with_coordinator):
    """UI合理性16：coordinator 注入 → 正常启动 + 卡片视图注入缩略图 provider。"""
    window, coordinator, _, _ = env_with_coordinator
    assert window._thumbnail_coordinator is not None  # noqa: SLF001
    # 卡片视图已接入 256 档缩略图缓存链路
    assert window._card_list_model._thumbnail_provider is not None  # noqa: SLF001


def test_close_event_calls_coordinator_shutdown(qapp, env_with_coordinator, monkeypatch):
    """closeEvent → 调用 coordinator.shutdown。"""
    window, coordinator, _, _ = env_with_coordinator
    called = {"flag": False}
    original_shutdown = coordinator.shutdown

    def mock_shutdown():
        called["flag"] = True
        original_shutdown()

    monkeypatch.setattr(coordinator, "shutdown", mock_shutdown)
    window.close()
    qapp.processEvents()
    assert called["flag"]


def test_metadata_saved_does_not_call_coordinator_invalidate(
    qapp, env_with_coordinator, monkeypatch
):
    """metadata_saved → 不再调用 coordinator.invalidate。

    Stage 4.5 M4 修复：缩略图缓存失效由 ContentService.update_metadata 在
    事务内条件性处理（仅 cover_path 变化时）。UI 层不再无条件 invalidate，
    避免未提交的 DELETE 事务阻塞后台 worker 写入。
    """
    window, coordinator, _, _ = env_with_coordinator
    called_unit_ids: list[str] = []

    def mock_invalidate(unit_id: str):
        called_unit_ids.append(unit_id)

    monkeypatch.setattr(coordinator, "invalidate", mock_invalidate)
    # 模拟 MetadataPanel 保存信号
    if window._metadata_panel is not None:  # noqa: SLF001
        from domain.models import ContentUnit

        unit = ContentUnit(
            id="test-unit-id",
            path="/test/path",
            content_type="mod",
            created_at="2026-07-01T00:00:00Z",
            updated_at="2026-07-01T00:00:00Z",
        )
        window._metadata_panel.on_saved.emit(unit)  # noqa: SLF001
        qapp.processEvents()
    # UI 层不应调用 invalidate（由 Service 层条件性处理）
    assert called_unit_ids == []


def test_card_thumbnail_generated_then_cache_hit(qapp, env_with_coordinator):
    """UI合理性16：卡片未命中 → 后台生成 → ready 刷新 → 二次请求命中缓存。"""
    from PySide6.QtCore import QEventLoop, Qt, QTimer
    from PySide6.QtGui import QPixmap

    from app import ui_constants as ui  # noqa: PLC0415

    window, coordinator, conn, mods_root = env_with_coordinator

    # 标记护甲文件夹为内容单元（自动设置封面）
    armor = mods_root / "护甲"
    unit = window._content_service.mark_as_content_unit(armor)  # noqa: SLF001
    conn.commit()
    assert unit.cover_path  # 自动封面已设置

    # 刷新中栏使 FileEntry 携带 content_unit
    window._refresh_content_list(str(mods_root))  # noqa: SLF001
    qapp.processEvents()

    card_model = window._card_list_model  # noqa: SLF001
    assert card_model._thumbnail_provider is not None  # noqa: SLF001
    source = window._content_list_model  # noqa: SLF001
    row = next(i for i in range(source.rowCount()) if source.entry_at(i).path == str(armor))
    idx = card_model.index(row, 0)

    # 首次：缓存未命中 → 占位 QPixmap（并已投递后台生成）
    first = card_model.data(idx, Qt.DecorationRole)
    assert isinstance(first, QPixmap)
    assert first.width() == ui.ZOOM_SLIDER_DEFAULT

    # 等待后台生成完成（thumbnail_ready 信号）
    loop = QEventLoop()
    coordinator.thumbnail_ready.connect(lambda unit_id, size: loop.quit())
    QTimer.singleShot(15000, loop.quit)  # 超时兜底
    loop.exec()
    qapp.processEvents()

    # 生成完成后：缓存清除 + 重新查询 → 返回缩略图（尺寸一致，占地不抖动）
    second = card_model.data(idx, Qt.DecorationRole)
    assert isinstance(second, QPixmap)
    assert second.width() == ui.ZOOM_SLIDER_DEFAULT
    assert second.height() == ui.ZOOM_SLIDER_DEFAULT

    # 再次请求命中磁盘缓存
    unit_id = unit.id
    cover_path = Path(armor) / unit.cover_path
    pixmap = coordinator.request_thumbnail(unit_id, cover_path, size=256)
    assert pixmap is not None
    assert not pixmap.isNull()
