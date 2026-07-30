"""ThumbnailService 单元测试（spec §9 / Q8: B GC / Task 1a 多档缓存）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from application.thumbnail_service import ThumbnailService
from domain.models import ContentUnit, ThumbnailCache
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.thumbnail_cache import ThumbnailCacheRepository


@pytest.fixture
def thumbnails_dir(tmp_path: Path) -> Path:
    d = tmp_path / "thumbnails"
    d.mkdir()
    return d


@pytest.fixture
def content_unit_repo(db_connection) -> ContentUnitRepository:
    return ContentUnitRepository(db_connection)


@pytest.fixture
def cache_repo(db_connection) -> ThumbnailCacheRepository:
    return ThumbnailCacheRepository(db_connection)


@pytest.fixture
def unit_u1(db_connection, content_unit_repo, tmp_path) -> ContentUnit:
    """确保 content_unit 表中存在 id='u1' 记录（满足 thumbnail_cache FK 约束）。"""
    unit = ContentUnit(
        id="u1",
        path=str(tmp_path / "u1"),
        title="U1",
        content_type="mod",
        status="organized",
        created_at="2026-07-01T00:00:00Z",
        updated_at="2026-07-01T00:00:00Z",
    )
    content_unit_repo.create(unit)
    db_connection.commit()
    return unit


@pytest.fixture
def service(cache_repo, content_unit_repo, thumbnails_dir, unit_u1) -> ThumbnailService:
    return ThumbnailService(
        cache_repo=cache_repo,
        content_unit_repo=content_unit_repo,
        thumbnails_dir=thumbnails_dir,
        size=256,
    )


@pytest.fixture
def jpg_source(tmp_path: Path) -> Path:
    path = tmp_path / "cover.jpg"
    img = Image.new("RGB", (100, 80), color=(255, 0, 0))
    img.save(path, format="JPEG")
    return path


@pytest.fixture
def unit_with_cover(
    unit_u1, content_unit_repo, db_connection, tmp_path
) -> tuple[ContentUnit, Path]:
    """基于 unit_u1 添加封面：创建封面文件并更新 cover_path。"""
    unit_dir = Path(unit_u1.path)
    unit_dir.mkdir(parents=True, exist_ok=True)
    cover_path = unit_dir / "cover.jpg"
    img = Image.new("RGB", (100, 80), color=(0, 0, 255))
    img.save(cover_path, format="JPEG")
    updated = ContentUnit(
        id=unit_u1.id,
        path=unit_u1.path,
        title=unit_u1.title,
        content_type=unit_u1.content_type,
        source_url=unit_u1.source_url,
        cover_path="cover.jpg",
        status=unit_u1.status,
        notes=unit_u1.notes,
        created_at=unit_u1.created_at,
        updated_at=unit_u1.updated_at,
    )
    content_unit_repo.update(updated)
    db_connection.commit()
    return updated, cover_path


# --- get_cache（缓存命中/未命中）---


def test_get_cache_miss_when_no_record(service, jpg_source):
    """无缓存记录 → 返回 None。"""
    result = service.get_cache("u1", jpg_source, size=256)
    assert result is None


def _make_valid_cache_record(cache_repo, unit_id: str, source_path: Path, size: int = 256) -> None:
    """构造一个"有效"的缓存记录（size/mtime 匹配实际文件）。"""
    from datetime import UTC, datetime

    actual_mtime = source_path.stat().st_mtime
    source_modified_at = datetime.fromtimestamp(actual_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    cache_repo.upsert(
        ThumbnailCache(
            content_unit_id=unit_id,
            size=size,
            source_size_bytes=source_path.stat().st_size,
            source_modified_at=source_modified_at,
            cache_filename=f"{unit_id}_{size}.webp",
            status="ok",
            generated_at="2026-07-01T00:00:01Z",
        )
    )


def test_get_cache_hit_returns_path(service, jpg_source, cache_repo, thumbnails_dir):
    """缓存命中 → 返回 WebP 路径。"""
    _make_valid_cache_record(cache_repo, "u1", jpg_source, size=256)
    # 创建缓存文件
    cache_file = thumbnails_dir / "u1_256.webp"
    Image.new("RGBA", (256, 256)).save(cache_file, format="WEBP")

    result = service.get_cache("u1", jpg_source, size=256)
    assert result is not None
    assert result == cache_file


def test_get_cache_invalid_mtime_treats_as_miss(service, jpg_source, cache_repo, thumbnails_dir):
    """源图 mtime 变化 → 缓存失效。"""
    import os

    _make_valid_cache_record(cache_repo, "u1", jpg_source, size=256)
    cache_file = thumbnails_dir / "u1_256.webp"
    Image.new("RGBA", (256, 256)).save(cache_file, format="WEBP")

    # 修改源文件 mtime
    new_mtime = jpg_source.stat().st_mtime + 3600
    os.utime(jpg_source, (new_mtime, new_mtime))

    result = service.get_cache("u1", jpg_source, size=256)
    assert result is None


def test_get_cache_invalid_size_treats_as_miss(service, jpg_source, cache_repo, thumbnails_dir):
    """源图 size 变化 → 缓存失效。"""
    cache_repo.upsert(
        ThumbnailCache(
            content_unit_id="u1",
            size=256,
            source_size_bytes=99999,
            source_modified_at="2026-07-01T00:00:00Z",
            cache_filename="u1_256.webp",
            status="ok",
            generated_at="2026-07-01T00:00:01Z",
        )
    )
    cache_file = thumbnails_dir / "u1_256.webp"
    Image.new("RGBA", (256, 256)).save(cache_file, format="WEBP")
    result = service.get_cache("u1", jpg_source, size=256)
    assert result is None


def test_get_cache_status_not_ok_returns_none(service, jpg_source, cache_repo):
    """status != 'ok' → 缓存不可用。"""
    cache_repo.upsert(
        ThumbnailCache(
            content_unit_id="u1",
            size=256,
            source_size_bytes=jpg_source.stat().st_size,
            source_modified_at="2026-07-01T00:00:00Z",
            cache_filename="u1_256.webp",
            status="corrupt",
            generated_at="2026-07-01T00:00:01Z",
            error_message="bad",
        )
    )
    result = service.get_cache("u1", jpg_source, size=256)
    assert result is None


def test_get_cache_missing_file_treats_as_miss(service, jpg_source, cache_repo):
    """cache_filename 文件不存在 → 缓存失效。"""
    cache_repo.upsert(
        ThumbnailCache(
            content_unit_id="u1",
            size=256,
            source_size_bytes=jpg_source.stat().st_size,
            source_modified_at="2026-07-01T00:00:00Z",
            cache_filename="u1_256.webp",
            status="ok",
            generated_at="2026-07-01T00:00:01Z",
        )
    )
    # 不创建缓存文件
    result = service.get_cache("u1", jpg_source, size=256)
    assert result is None


# --- generate ---


def test_generate_success_writes_cache_and_file(service, jpg_source, cache_repo, thumbnails_dir):
    """生成成功 → 写入 WebP + upsert status='ok' 记录。"""
    status = service.generate("u1", jpg_source, size=256)
    assert status == "ok"
    cache_file = thumbnails_dir / "u1_256.webp"
    assert cache_file.exists()
    cache = cache_repo.get_by_id_and_size("u1", 256)
    assert cache is not None
    assert cache.status == "ok"
    assert cache.size == 256
    assert cache.source_size_bytes == jpg_source.stat().st_size


def test_generate_512_writes_separate_cache(service, jpg_source, cache_repo, thumbnails_dir):
    """Task 1a：512 档生成独立缓存，与 256 档共存。"""
    # 先生成 256 档
    service.generate("u1", jpg_source, size=256)
    # 再生成 512 档
    status = service.generate("u1", jpg_source, size=512)
    assert status == "ok"
    assert (thumbnails_dir / "u1_512.webp").exists()
    # 256 档仍在
    assert (thumbnails_dir / "u1_256.webp").exists()
    # DB 两条记录
    caches = cache_repo.list_by_unit("u1")
    assert {c.size for c in caches} == {256, 512}


def test_generate_missing_source_records_missing_status(service, tmp_path, cache_repo):
    """源图不存在 → status='missing'。"""
    source = tmp_path / "nonexistent.jpg"
    status = service.generate("u1", source, size=256)
    assert status == "missing"
    cache = cache_repo.get_by_id_and_size("u1", 256)
    assert cache is not None
    assert cache.status == "missing"


def test_generate_corrupt_records_corrupt_status(service, tmp_path, cache_repo):
    """源图损坏 → status='corrupt'。"""
    source = tmp_path / "corrupt.jpg"
    source.write_bytes(b"not an image")
    status = service.generate("u1", source, size=256)
    assert status == "corrupt"
    cache = cache_repo.get_by_id_and_size("u1", 256)
    assert cache is not None
    assert cache.status == "corrupt"


def test_generate_unsupported_records_unsupported_status(service, tmp_path, cache_repo):
    """不支持的格式 → status='unsupported'。"""
    source = tmp_path / "file.txt"
    source.write_text("hello")
    status = service.generate("u1", source, size=256)
    assert status == "unsupported"
    cache = cache_repo.get_by_id_and_size("u1", 256)
    assert cache is not None
    assert cache.status == "unsupported"


# --- invalidate（Task 1a：清理所有档位）---


def test_invalidate_deletes_all_sizes(service, jpg_source, cache_repo, thumbnails_dir):
    """Task 1a：invalidate 删除所有档位的记录和文件。"""
    service.generate("u1", jpg_source, size=256)
    service.generate("u1", jpg_source, size=512)
    assert cache_repo.get_by_id_and_size("u1", 256) is not None
    assert cache_repo.get_by_id_and_size("u1", 512) is not None
    assert (thumbnails_dir / "u1_256.webp").exists()
    assert (thumbnails_dir / "u1_512.webp").exists()

    service.invalidate("u1")

    assert cache_repo.get_by_id_and_size("u1", 256) is None
    assert cache_repo.get_by_id_and_size("u1", 512) is None
    assert not (thumbnails_dir / "u1_256.webp").exists()
    assert not (thumbnails_dir / "u1_512.webp").exists()


def test_invalidate_nonexistent_is_noop(service):
    """失效不存在的 unit → 不报错。"""
    service.invalidate("nonexistent")


def test_invalidate_cleans_legacy_png(service, jpg_source, cache_repo, thumbnails_dir):
    """Task 1a：invalidate 同时清理旧 v6 命名 {unit_id}.png。"""
    # 模拟旧 v6 缓存文件
    legacy_path = thumbnails_dir / "u1.png"
    Image.new("RGBA", (64, 64)).save(legacy_path, format="PNG")
    assert legacy_path.exists()

    service.invalidate("u1")
    assert not legacy_path.exists()


# --- GC（Q8: B） ---


def test_cleanup_orphans_removes_orphaned_records(
    service, cache_repo, content_unit_repo, db_connection, thumbnails_dir
):
    """GC 清理无对应 content_unit 的缓存记录。"""
    db_connection.commit()
    db_connection.execute("PRAGMA foreign_keys = OFF;")
    cache_repo.upsert(
        ThumbnailCache(
            content_unit_id="orphan",
            size=256,
            source_size_bytes=100,
            source_modified_at="2026-07-01T00:00:00Z",
            cache_filename="orphan_256.webp",
            status="ok",
            generated_at="2026-07-01T00:00:01Z",
        )
    )
    db_connection.commit()
    db_connection.execute("PRAGMA foreign_keys = ON;")
    (thumbnails_dir / "orphan_256.webp").write_bytes(b"fake webp")

    cleaned = service.cleanup_orphans()
    assert cleaned >= 1
    assert cache_repo.get_by_id_and_size("orphan", 256) is None
    assert not (thumbnails_dir / "orphan_256.webp").exists()


def test_cleanup_orphans_preserves_valid_caches(
    service,
    jpg_source,
    cache_repo,
    content_unit_repo,
    db_connection,
    thumbnails_dir,
    unit_with_cover,
):
    """GC 不清理有对应 content_unit 的缓存。"""
    unit, cover_path = unit_with_cover
    service.generate(unit.id, cover_path, size=256)
    db_connection.commit()

    cleaned = service.cleanup_orphans()
    assert cleaned == 0
    assert cache_repo.get_by_id_and_size(unit.id, 256) is not None
    assert (thumbnails_dir / f"{unit.id}_256.webp").exists()


def test_cleanup_orphans_removes_orphaned_files(
    service, cache_repo, content_unit_repo, db_connection, thumbnails_dir
):
    """GC 清理目录中无对应记录的 WebP 文件。"""
    (thumbnails_dir / "orphan_file_256.webp").write_bytes(b"fake webp")

    cleaned = service.cleanup_orphans()
    assert cleaned >= 1
    assert not (thumbnails_dir / "orphan_file_256.webp").exists()
