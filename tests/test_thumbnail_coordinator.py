"""ThumbnailCoordinator 测试。

覆盖：
- get_thumbnail_info 缓存命中/未命中/过期；
- generate_thumbnail 成功/失败/写入缓存记录；
- get_cover_thumbnail_info。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from application.thumbnail_coordinator import ThumbnailCoordinator
from domain.models import AssetKind, FileAsset, FileRole
from infrastructure.repositories.file_asset import FileAssetRepository
from infrastructure.repositories.thumbnail_cache import (
    ThumbnailCacheRecord,
    ThumbnailCacheRepository,
)
from infrastructure.thumbnail_generator import ThumbnailGenerator, ThumbnailStatus

pytest.importorskip("PIL", reason="Pillow 未安装")
from PIL import Image  # noqa: E402


def _make_asset(
    asset_id: str = "asset-1",
    real_path: str = "/test.png",
    size_bytes: int = 100,
    modified_at: str = "2026-07-07T00:00:00Z",
    filename: str = "test.png",
    extension: str = ".png",
) -> FileAsset:
    return FileAsset(
        id=asset_id,
        mod_item_id=None,
        real_path=real_path,
        path_key=real_path,
        filename=filename,
        extension=extension,
        asset_kind=AssetKind.FILE,
        role=FileRole.UNKNOWN,
        size_bytes=size_bytes,
        modified_at=modified_at,
        imported_at="2026-07-07T00:00:00Z",
    )


def _make_png(path: Path, size: tuple[int, int] = (100, 80)) -> Path:
    img = Image.new("RGB", size, color=(255, 0, 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG")
    return path


def _make_coordinator(
    db_connection: sqlite3.Connection,
    cache_dir: Path,
) -> tuple[ThumbnailCoordinator, FileAssetRepository, ThumbnailCacheRepository]:
    file_repo = FileAssetRepository(db_connection)
    cache_repo = ThumbnailCacheRepository(db_connection)
    gen = ThumbnailGenerator(cache_dir)
    coord = ThumbnailCoordinator(
        file_repo,
        cache_repo,
        gen,
        now_provider=lambda: "2026-07-07T00:00:00Z",
    )
    return coord, file_repo, cache_repo


def test_get_thumbnail_info_no_cache_record(
    db_connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """无缓存记录时返回 valid=False。"""
    asset = _make_asset()
    file_repo = FileAssetRepository(db_connection)
    file_repo.create(asset)

    coord, _, _ = _make_coordinator(db_connection, tmp_path / "thumbnails")
    info = coord.get_thumbnail_info(asset.id)

    assert info.status == ThumbnailStatus.OK
    assert info.valid is False
    assert info.cache_path is None


def test_get_thumbnail_info_asset_not_found(
    db_connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """FileAsset 不存在返回 MISSING。"""
    coord, _, _ = _make_coordinator(db_connection, tmp_path / "thumbnails")
    info = coord.get_thumbnail_info("nonexistent")

    assert info.status == ThumbnailStatus.MISSING
    assert info.valid is False


def test_get_thumbnail_info_valid_cache(db_connection: sqlite3.Connection, tmp_path: Path) -> None:
    """缓存有效时返回 valid=True 与 cache_path。"""
    source = _make_png(tmp_path / "src" / "test.png")
    stat = source.stat()
    asset = _make_asset(
        real_path=str(source),
        size_bytes=stat.st_size,
        modified_at="2026-07-07T00:00:00Z",
    )
    file_repo = FileAssetRepository(db_connection)
    file_repo.create(asset)

    coord, _, cache_repo = _make_coordinator(db_connection, tmp_path / "thumbnails")
    # 先生成
    result = coord.generate_thumbnail(asset.id)
    assert result.status == ThumbnailStatus.OK

    # 再次查询应命中
    info = coord.get_thumbnail_info(asset.id)
    assert info.status == ThumbnailStatus.OK
    assert info.valid is True
    assert info.cache_path is not None


def test_get_thumbnail_info_expired_by_size(
    db_connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """source_size 变化后缓存失效。"""
    source = _make_png(tmp_path / "src" / "test.png")
    asset = _make_asset(
        real_path=str(source),
        size_bytes=100,
        modified_at="2026-07-07T00:00:00Z",
    )
    file_repo = FileAssetRepository(db_connection)
    file_repo.create(asset)

    coord, _, cache_repo = _make_coordinator(db_connection, tmp_path / "thumbnails")
    coord.generate_thumbnail(asset.id)

    # 修改 source_size_bytes 模拟源文件变化
    record = cache_repo.get_by_asset_id(asset.id)
    assert record is not None
    cache_repo.upsert(
        ThumbnailCacheRecord(
            asset_id=asset.id,
            source_size_bytes=999,  # 不匹配
            source_modified_at=record.source_modified_at,
            cache_filename=record.cache_filename,
            status="ok",
            error_message=None,
            generated_at=record.generated_at,
        )
    )

    info = coord.get_thumbnail_info(asset.id)
    assert info.valid is False


def test_get_thumbnail_info_expired_by_mtime(
    db_connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """source_modified_at 变化后缓存失效。"""
    source = _make_png(tmp_path / "src" / "test.png")
    asset = _make_asset(
        real_path=str(source),
        size_bytes=100,
        modified_at="2026-07-07T00:00:00Z",
    )
    file_repo = FileAssetRepository(db_connection)
    file_repo.create(asset)

    coord, _, cache_repo = _make_coordinator(db_connection, tmp_path / "thumbnails")
    coord.generate_thumbnail(asset.id)

    record = cache_repo.get_by_asset_id(asset.id)
    assert record is not None
    cache_repo.upsert(
        ThumbnailCacheRecord(
            asset_id=asset.id,
            source_size_bytes=record.source_size_bytes,
            source_modified_at="2026-01-01T00:00:00Z",  # 不匹配
            cache_filename=record.cache_filename,
            status="ok",
            error_message=None,
            generated_at=record.generated_at,
        )
    )

    info = coord.get_thumbnail_info(asset.id)
    assert info.valid is False


def test_generate_thumbnail_success(db_connection: sqlite3.Connection, tmp_path: Path) -> None:
    """成功生成缩略图并写入缓存记录。"""
    source = _make_png(tmp_path / "src" / "test.png")
    stat = source.stat()
    asset = _make_asset(
        real_path=str(source),
        size_bytes=stat.st_size,
        modified_at="2026-07-07T00:00:00Z",
    )
    file_repo = FileAssetRepository(db_connection)
    file_repo.create(asset)

    coord, _, cache_repo = _make_coordinator(db_connection, tmp_path / "thumbnails")
    result = coord.generate_thumbnail(asset.id)

    assert result.status == ThumbnailStatus.OK
    assert result.cache_path is not None
    assert result.cache_path.exists()

    # 缓存记录已写入
    record = cache_repo.get_by_asset_id(asset.id)
    assert record is not None
    assert record.status == "ok"
    assert record.source_size_bytes == stat.st_size


def test_generate_thumbnail_missing_source(
    db_connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """源文件不存在生成失败，写入 MISSING 缓存记录。"""
    asset = _make_asset(real_path=str(tmp_path / "nonexistent.png"))
    file_repo = FileAssetRepository(db_connection)
    file_repo.create(asset)

    coord, _, cache_repo = _make_coordinator(db_connection, tmp_path / "thumbnails")
    result = coord.generate_thumbnail(asset.id)

    assert result.status == ThumbnailStatus.MISSING
    assert result.cache_path is None

    record = cache_repo.get_by_asset_id(asset.id)
    assert record is not None
    assert record.status == "missing"


def test_generate_thumbnail_corrupt(db_connection: sqlite3.Connection, tmp_path: Path) -> None:
    """损坏图片生成失败，写入 CORRUPT 缓存记录。"""
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not png")
    asset = _make_asset(real_path=str(corrupt))
    file_repo = FileAssetRepository(db_connection)
    file_repo.create(asset)

    coord, _, cache_repo = _make_coordinator(db_connection, tmp_path / "thumbnails")
    result = coord.generate_thumbnail(asset.id)

    assert result.status == ThumbnailStatus.CORRUPT
    record = cache_repo.get_by_asset_id(asset.id)
    assert record is not None
    assert record.status == "corrupt"


def test_generate_thumbnail_unsupported(db_connection: sqlite3.Connection, tmp_path: Path) -> None:
    """不支持格式写入 UNSUPPORTED 缓存记录。"""
    source = tmp_path / "test.txt"
    source.write_text("hello")
    asset = _make_asset(
        real_path=str(source),
        filename="test.txt",
        extension=".txt",
    )
    file_repo = FileAssetRepository(db_connection)
    file_repo.create(asset)

    coord, _, cache_repo = _make_coordinator(db_connection, tmp_path / "thumbnails")
    result = coord.generate_thumbnail(asset.id)

    assert result.status == ThumbnailStatus.UNSUPPORTED
    record = cache_repo.get_by_asset_id(asset.id)
    assert record is not None
    assert record.status == "unsupported"


def test_generate_thumbnail_asset_not_found(
    db_connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """FileAsset 不存在时不写缓存记录。"""
    coord, _, cache_repo = _make_coordinator(db_connection, tmp_path / "thumbnails")
    result = coord.generate_thumbnail("nonexistent")

    assert result.status == ThumbnailStatus.MISSING
    assert cache_repo.get_by_asset_id("nonexistent") is None


def test_generate_thumbnail_does_not_modify_source(
    db_connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """生成缩略图后源文件不变。"""
    source = _make_png(tmp_path / "src" / "test.png")
    content_before = source.read_bytes()
    stat_before = source.stat()

    asset = _make_asset(
        real_path=str(source),
        size_bytes=stat_before.st_size,
        modified_at="2026-07-07T00:00:00Z",
    )
    file_repo = FileAssetRepository(db_connection)
    file_repo.create(asset)

    coord, _, _ = _make_coordinator(db_connection, tmp_path / "thumbnails")
    coord.generate_thumbnail(asset.id)

    content_after = source.read_bytes()
    stat_after = source.stat()
    assert content_after == content_before
    assert stat_after.st_size == stat_before.st_size
    assert stat_after.st_mtime == stat_before.st_mtime


def test_generate_thumbnail_chinese_path(db_connection: sqlite3.Connection, tmp_path: Path) -> None:
    """中文路径图片可生成缩略图。"""
    source = _make_png(tmp_path / "中文目录" / "预览图.png")
    stat = source.stat()
    asset = _make_asset(
        real_path=str(source),
        size_bytes=stat.st_size,
        modified_at="2026-07-07T00:00:00Z",
        filename="预览图.png",
    )
    file_repo = FileAssetRepository(db_connection)
    file_repo.create(asset)

    coord, _, _ = _make_coordinator(db_connection, tmp_path / "thumbnails")
    result = coord.generate_thumbnail(asset.id)

    assert result.status == ThumbnailStatus.OK
    assert result.cache_path is not None


def test_get_cover_thumbnail_info_with_asset(
    db_connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """get_cover_thumbnail_info 直接使用 FileAsset 对象。"""
    source = _make_png(tmp_path / "src" / "test.png")
    stat = source.stat()
    asset = _make_asset(
        real_path=str(source),
        size_bytes=stat.st_size,
        modified_at="2026-07-07T00:00:00Z",
    )
    file_repo = FileAssetRepository(db_connection)
    file_repo.create(asset)

    coord, _, _ = _make_coordinator(db_connection, tmp_path / "thumbnails")
    coord.generate_thumbnail(asset.id)

    info = coord.get_cover_thumbnail_info(asset)
    assert info.valid is True
    assert info.cache_path is not None


def test_generate_then_cache_hit_on_second_query(
    db_connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """生成后第二次查询应缓存命中。"""
    source = _make_png(tmp_path / "src" / "test.png")
    stat = source.stat()
    asset = _make_asset(
        real_path=str(source),
        size_bytes=stat.st_size,
        modified_at="2026-07-07T00:00:00Z",
    )
    file_repo = FileAssetRepository(db_connection)
    file_repo.create(asset)

    coord, _, _ = _make_coordinator(db_connection, tmp_path / "thumbnails")
    coord.generate_thumbnail(asset.id)

    info = coord.get_thumbnail_info(asset.id)
    assert info.valid is True
    assert info.cache_path is not None
