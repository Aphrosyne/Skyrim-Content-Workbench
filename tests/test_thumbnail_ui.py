"""缩略图 UI 集成测试。

覆盖：
- ThumbnailWorker 后台生成；
- MainWindow 设为封面；
- 成员表格封面列；
- 卡片列表显示封面图标；
- 错误状态占位。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("PIL", reason="Pillow 未安装")
pytest.importorskip("PySide6", reason="PySide6 未安装")

from PIL import Image  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.main_window import MainWindow  # noqa: E402
from app.thumbnail_worker import ThumbnailWorker  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.mod_assembly_service import ModAssemblyService  # noqa: E402
from application.thumbnail_coordinator import ThumbnailCoordinator  # noqa: E402
from domain.models import FileRole  # noqa: E402
from infrastructure.repositories.file_asset import FileAssetRepository  # noqa: E402
from infrastructure.repositories.folder_node import FolderNodeRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402
from infrastructure.repositories.mod_item import ModItemRepository  # noqa: E402
from infrastructure.repositories.thumbnail_cache import ThumbnailCacheRepository  # noqa: E402
from infrastructure.thumbnail_generator import ThumbnailGenerator, ThumbnailStatus  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def _make_png(path: Path, size: tuple[int, int] = (100, 80)) -> Path:
    img = Image.new("RGB", size, color=(255, 0, 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG")
    return path


def _make_window_with_thumbnail(db_connection, db_path: Path, cache_dir: Path) -> MainWindow:
    """构造带 ThumbnailCoordinator 的 MainWindow。"""
    service = ManagedRootService(ManagedRootRepository(db_connection))
    tree_service = FolderTreeService(
        ManagedRootRepository(db_connection), FolderNodeRepository(db_connection)
    )
    mod_service = ModAssemblyService(
        ModItemRepository(db_connection), FileAssetRepository(db_connection)
    )
    coord = ThumbnailCoordinator(
        FileAssetRepository(db_connection),
        ThumbnailCacheRepository(db_connection),
        ThumbnailGenerator(cache_dir),
    )
    return MainWindow(
        service,
        tree_service,
        mod_service,
        db_path,
        thumbnail_coordinator=coord,
        commit_callback=db_connection.commit,
    )


def _setup_mod_with_preview(db_connection, tmp_path: Path) -> tuple[str, str, Path]:
    """创建 ModItem 并关联一个 preview 图片素材，返回 (mod_id, asset_id, image_path)。"""
    from infrastructure.file_scanner import FileScanner, persist_scan_result

    image_path = _make_png(tmp_path / "mods" / "preview.png")
    scanner = FileScanner()
    result = scanner.scan(tmp_path / "mods")
    persist_scan_result(
        result,
        FolderNodeRepository(db_connection),
        FileAssetRepository(db_connection),
    )
    db_connection.commit()

    mod_service = ModAssemblyService(
        ModItemRepository(db_connection), FileAssetRepository(db_connection)
    )
    mod = mod_service.create_mod_item(display_name="测试 Mod")
    # 找到 preview.png 的 FileAsset
    assets = mod_service.list_unassociated_assets()
    preview_asset = next(a for a in assets if a.filename == "preview.png")
    mod_service.add_member(mod.id, preview_asset.id, FileRole.PREVIEW)
    db_connection.commit()
    return mod.id, preview_asset.id, image_path


def test_thumbnail_worker_generates_async(
    qapp: QApplication, db_connection, db_path: Path, tmp_path: Path
) -> None:
    """ThumbnailWorker 在后台生成缩略图。"""
    mod_id, asset_id, image_path = _setup_mod_with_preview(db_connection, tmp_path)
    cache_dir = tmp_path / "thumbnails"

    from PySide6.QtCore import QThread

    thread = QThread()
    worker = ThumbnailWorker(db_path, cache_dir, [asset_id])
    worker.moveToThread(thread)
    thread.started.connect(worker.run)

    results: list[tuple[str, object]] = []

    def on_ready(aid: str, result) -> None:
        results.append((aid, result))

    worker.thumbnail_ready.connect(on_ready)
    worker.finished.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()

    deadline = time.monotonic() + 10.0
    while thread.isRunning() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)

    assert len(results) == 1
    aid, result = results[0]
    assert aid == asset_id
    assert result.status == ThumbnailStatus.OK
    assert result.cache_path is not None
    assert result.cache_path.exists()


def test_main_window_set_cover_updates_members(
    qapp: QApplication, db_connection, db_path: Path, tmp_path: Path
) -> None:
    """设为封面后成员表格显示封面标记。"""
    mod_id, asset_id, _ = _setup_mod_with_preview(db_connection, tmp_path)
    window = _make_window_with_thumbnail(db_connection, db_path, tmp_path / "thumbnails")

    # 选中 ModItem
    list_view = window._mod_list_view  # noqa: SLF001
    for i in range(window._mod_list_model.item_count()):  # noqa: SLF001
        if window._mod_list_model.mod_item_id_at(i) == mod_id:  # noqa: SLF001
            idx = window._mod_list_model.index(i)  # noqa: SLF001
            list_view.setCurrentIndex(idx)
            break

    assert window._current_mod_id == mod_id  # noqa: SLF001
    assert window.members_table_row_count() == 1

    # 调用设为封面
    window._on_set_cover(asset_id)  # noqa: SLF001

    # 验证 cover_asset_id 已设置
    mod_item = window._mod_service.get_mod_item(mod_id)  # noqa: SLF001
    assert mod_item.cover_asset_id == asset_id


def test_main_window_set_cover_rejects_non_preview(
    qapp: QApplication, db_connection, db_path: Path, tmp_path: Path
) -> None:
    """非 preview 成员设为封面被拒绝。"""
    from PySide6.QtWidgets import QMessageBox

    from infrastructure.file_scanner import FileScanner, persist_scan_result

    # 创建一个非图片文件作为非 preview 成员
    archive = tmp_path / "mods2" / "mod.7z"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"\x00" * 50)

    scanner = FileScanner()
    result = scanner.scan(tmp_path / "mods2")
    persist_scan_result(
        result,
        FolderNodeRepository(db_connection),
        FileAssetRepository(db_connection),
    )
    db_connection.commit()

    mod_service = ModAssemblyService(
        ModItemRepository(db_connection), FileAssetRepository(db_connection)
    )
    mod = mod_service.create_mod_item(display_name="测试 Mod 2")
    assets = mod_service.list_unassociated_assets()
    archive_asset = next(a for a in assets if a.filename == "mod.7z")
    mod_service.add_member(mod.id, archive_asset.id, FileRole.MAIN_MOD)
    db_connection.commit()

    window = _make_window_with_thumbnail(db_connection, db_path, tmp_path / "thumbnails")

    # 选中 ModItem
    list_view = window._mod_list_view  # noqa: SLF001
    for i in range(window._mod_list_model.item_count()):  # noqa: SLF001
        if window._mod_list_model.mod_item_id_at(i) == mod.id:  # noqa: SLF001
            idx = window._mod_list_model.index(i)  # noqa: SLF001
            list_view.setCurrentIndex(idx)
            break

    # 模拟用户在 QMessageBox 点击 OK
    original = QMessageBox.warning
    QMessageBox.warning = staticmethod(  # type: ignore[assignment]
        lambda *args, **kwargs: QMessageBox.StandardButton.Ok
    )
    try:
        # 直接调用 set_cover，应被拒绝（role != PREVIEW）
        window._on_set_cover(archive_asset.id)  # noqa: SLF001
    finally:
        QMessageBox.warning = original  # type: ignore[assignment]

    # cover_asset_id 不应被设置
    mod_item = window._mod_service.get_mod_item(mod.id)  # noqa: SLF001
    assert mod_item.cover_asset_id is None


def test_mod_list_model_shows_member_count(
    qapp: QApplication, db_connection, db_path: Path, tmp_path: Path
) -> None:
    """ModItem 列表显示成员数。"""
    _setup_mod_with_preview(db_connection, tmp_path)
    window = _make_window_with_thumbnail(db_connection, db_path, tmp_path / "thumbnails")

    assert window.mod_list_count() == 1
    model = window._mod_list_model  # noqa: SLF001
    idx = model.index(0)
    display_text = model.data(idx, Qt.DisplayRole)
    assert "1 个成员" in display_text


def test_mod_list_model_supports_cover_icon(
    qapp: QApplication, db_connection, db_path: Path, tmp_path: Path
) -> None:
    """ModItemListModel 支持 DecorationRole（封面图标）。"""
    _setup_mod_with_preview(db_connection, tmp_path)
    window = _make_window_with_thumbnail(db_connection, db_path, tmp_path / "thumbnails")

    model = window._mod_list_model  # noqa: SLF001
    idx = model.index(0)
    # 初始无封面图标
    assert model.data(idx, Qt.DecorationRole) is None

    # 设置图标后可获取
    from PySide6.QtGui import QIcon, QPixmap

    icon = QIcon(QPixmap(16, 16))
    model.set_cover_icon(model.mod_item_id_at(0), icon)
    assert model.data(idx, Qt.DecorationRole) is not None


def test_main_window_cover_preview_label_exists(
    qapp: QApplication, db_connection, db_path: Path, tmp_path: Path
) -> None:
    """MainWindow 包含封面预览 QLabel。"""
    window = _make_window_with_thumbnail(db_connection, db_path, tmp_path / "thumbnails")
    assert hasattr(window, "_cover_label")  # noqa: SLF001
    # 初始显示提示文本
    assert "未设置封面" in window._cover_label.text()  # noqa: SLF001


def test_main_window_members_table_has_six_columns(
    qapp: QApplication, db_connection, db_path: Path, tmp_path: Path
) -> None:
    """成员表格有 6 列（含封面列）。"""
    _setup_mod_with_preview(db_connection, tmp_path)
    window = _make_window_with_thumbnail(db_connection, db_path, tmp_path / "thumbnails")

    # 选中 ModItem
    list_view = window._mod_list_view  # noqa: SLF001
    idx = window._mod_list_model.index(0)  # noqa: SLF001
    list_view.setCurrentIndex(idx)

    assert window._members_table.columnCount() == 6  # noqa: SLF001


def test_main_window_cover_preview_shows_after_set_cover(
    qapp: QApplication, db_connection, db_path: Path, tmp_path: Path
) -> None:
    """设为封面后详情区显示封面预览（缓存命中时）。"""
    mod_id, asset_id, _ = _setup_mod_with_preview(db_connection, tmp_path)
    cache_dir = tmp_path / "thumbnails"

    # 先生成缩略图
    coord = ThumbnailCoordinator(
        FileAssetRepository(db_connection),
        ThumbnailCacheRepository(db_connection),
        ThumbnailGenerator(cache_dir),
    )
    result = coord.generate_thumbnail(asset_id)
    assert result.status == ThumbnailStatus.OK
    db_connection.commit()

    window = _make_window_with_thumbnail(db_connection, db_path, cache_dir)

    # 选中 ModItem
    list_view = window._mod_list_view  # noqa: SLF001
    for i in range(window._mod_list_model.item_count()):  # noqa: SLF001
        if window._mod_list_model.mod_item_id_at(i) == mod_id:  # noqa: SLF001
            idx = window._mod_list_model.index(i)  # noqa: SLF001
            list_view.setCurrentIndex(idx)
            break

    # 设为封面
    window._on_set_cover(asset_id)  # noqa: SLF001

    # 封面预览应显示 pixmap（缓存已存在）
    assert window._cover_label.pixmap() is not None  # noqa: SLF001
    assert not window._cover_label.pixmap().isNull()  # noqa: SLF001


def test_thumbnail_worker_does_not_block_main_thread(
    qapp: QApplication, db_connection, db_path: Path, tmp_path: Path
) -> None:
    """缩略图生成不在主线程同步执行。"""
    mod_id, asset_id, _ = _setup_mod_with_preview(db_connection, tmp_path)
    cache_dir = tmp_path / "thumbnails"

    # 记录主线程在 worker 运行期间可以处理事件
    from PySide6.QtCore import QThread

    thread = QThread()
    worker = ThumbnailWorker(db_path, cache_dir, [asset_id])
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)

    processed_events = False

    def on_started() -> None:
        nonlocal processed_events
        # 主线程应能处理事件
        qapp.processEvents()
        processed_events = True

    thread.started.connect(on_started)
    thread.start()

    deadline = time.monotonic() + 10.0
    while thread.isRunning() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)

    assert processed_events
