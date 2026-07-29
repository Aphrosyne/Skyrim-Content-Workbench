"""ThumbnailService 单元测试（spec §9 / Q8: B GC）。"""

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
        status="unorganized",
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
        size=64,
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
    """基于 unit_u1 添加封面：创建封面文件并更新 cover_path。

    使用 unit_u1 作为基础以避免主键冲突（unit_u1 已创建 id='u1'）。
    """
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
    result = service.get_cache("u1", jpg_source)
    assert result is None


def test_get_cache_hit_returns_path(service, jpg_source, cache_repo):
    """缓存命中 → 返回 PNG 路径。

    Stage 4.5 M19 修正：原测试无 assert 且 mtime 硬编码与实际文件不匹配，
    导致永远"通过"但未验证任何东西。现使用动态 mtime + 明确 assert。
    """
    from datetime import UTC, datetime

    # 用实际文件 mtime 构造缓存记录（避免硬编码 mtime 不匹配）
    actual_mtime = jpg_source.stat().st_mtime
    source_modified_at = datetime.fromtimestamp(actual_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    cache_repo.upsert(
        ThumbnailCache(
            content_unit_id="u1",
            source_size_bytes=jpg_source.stat().st_size,
            source_modified_at=source_modified_at,
            cache_filename="u1.png",
            status="ok",
            generated_at="2026-07-01T00:00:01Z",
        )
    )
    # 同时创建缓存文件
    cache_png = service.get_thumbnails_dir() / "u1.png"
    Image.new("RGBA", (64, 64)).save(cache_png)

    result = service.get_cache("u1", jpg_source)
    assert result is not None
    assert result == cache_png


def test_get_cache_invalid_mtime_treats_as_miss(service, jpg_source, cache_repo):
    """源图 mtime 变化 → 缓存失效（spec §9 核心条款）。

    Stage 4.5 M19 新增：原测试套件无 mtime 失效路径覆盖，导致
    若未来误删 mtime 检查无法被测试发现。
    """
    import os

    # 先构造一个"有效"的缓存记录
    actual_mtime = jpg_source.stat().st_mtime
    from datetime import UTC, datetime

    source_modified_at = datetime.fromtimestamp(actual_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    cache_repo.upsert(
        ThumbnailCache(
            content_unit_id="u1",
            source_size_bytes=jpg_source.stat().st_size,
            source_modified_at=source_modified_at,
            cache_filename="u1.png",
            status="ok",
            generated_at="2026-07-01T00:00:01Z",
        )
    )
    cache_png = service.get_thumbnails_dir() / "u1.png"
    Image.new("RGBA", (64, 64)).save(cache_png)

    # 修改源文件 mtime（模拟外部工具覆盖）
    new_mtime = actual_mtime + 3600  # +1 小时
    os.utime(jpg_source, (new_mtime, new_mtime))

    result = service.get_cache("u1", jpg_source)
    assert result is None  # mtime 不匹配 → 缓存失效


def test_get_cache_invalid_size_treats_as_miss(service, jpg_source, cache_repo):
    """源图 size 变化 → 缓存失效。"""
    cache_repo.upsert(
        ThumbnailCache(
            content_unit_id="u1",
            source_size_bytes=99999,  # 与实际不符
            source_modified_at="2026-07-01T00:00:00Z",
            cache_filename="u1.png",
            status="ok",
            generated_at="2026-07-01T00:00:01Z",
        )
    )
    cache_png = service.get_thumbnails_dir() / "u1.png"
    Image.new("RGBA", (64, 64)).save(cache_png)
    result = service.get_cache("u1", jpg_source)
    assert result is None


def test_get_cache_status_not_ok_returns_none(service, jpg_source, cache_repo):
    """status != 'ok' → 缓存不可用。"""
    cache_repo.upsert(
        ThumbnailCache(
            content_unit_id="u1",
            source_size_bytes=jpg_source.stat().st_size,
            source_modified_at="2026-07-01T00:00:00Z",
            cache_filename="u1.png",
            status="corrupt",
            generated_at="2026-07-01T00:00:01Z",
            error_message="bad",
        )
    )
    result = service.get_cache("u1", jpg_source)
    assert result is None


def test_get_cache_missing_file_treats_as_miss(service, jpg_source, cache_repo):
    """cache_filename 文件不存在 → 缓存失效。"""
    cache_repo.upsert(
        ThumbnailCache(
            content_unit_id="u1",
            source_size_bytes=jpg_source.stat().st_size,
            source_modified_at="2026-07-01T00:00:00Z",
            cache_filename="u1.png",
            status="ok",
            generated_at="2026-07-01T00:00:01Z",
        )
    )
    # 不创建缓存文件
    result = service.get_cache("u1", jpg_source)
    assert result is None


# --- generate ---


def test_generate_success_writes_cache_and_file(service, jpg_source, cache_repo, thumbnails_dir):
    """生成成功 → 写入 PNG + upsert status='ok' 记录。"""
    status = service.generate("u1", jpg_source)
    assert status == "ok"
    # 缓存文件存在
    cache_png = thumbnails_dir / "u1.png"
    assert cache_png.exists()
    # 数据库记录
    cache = cache_repo.get_by_id("u1")
    assert cache is not None
    assert cache.status == "ok"
    assert cache.source_size_bytes == jpg_source.stat().st_size


def test_generate_missing_source_records_missing_status(service, tmp_path, cache_repo):
    """源图不存在 → status='missing'。"""
    source = tmp_path / "nonexistent.jpg"
    status = service.generate("u1", source)
    assert status == "missing"
    cache = cache_repo.get_by_id("u1")
    assert cache is not None
    assert cache.status == "missing"


def test_generate_corrupt_records_corrupt_status(service, tmp_path, cache_repo):
    """源图损坏 → status='corrupt'。"""
    source = tmp_path / "corrupt.jpg"
    source.write_bytes(b"not an image")
    status = service.generate("u1", source)
    assert status == "corrupt"
    cache = cache_repo.get_by_id("u1")
    assert cache is not None
    assert cache.status == "corrupt"


def test_generate_unsupported_records_unsupported_status(service, tmp_path, cache_repo):
    """不支持的格式 → status='unsupported'。"""
    source = tmp_path / "file.txt"
    source.write_text("hello")
    status = service.generate("u1", source)
    assert status == "unsupported"
    cache = cache_repo.get_by_id("u1")
    assert cache is not None
    assert cache.status == "unsupported"


# --- invalidate ---


def test_invalidate_deletes_cache_and_file(service, jpg_source, cache_repo, thumbnails_dir):
    """失效：删除记录 + 文件。"""
    service.generate("u1", jpg_source)
    assert cache_repo.get_by_id("u1") is not None
    assert (thumbnails_dir / "u1.png").exists()
    service.invalidate("u1")
    assert cache_repo.get_by_id("u1") is None
    assert not (thumbnails_dir / "u1.png").exists()


def test_invalidate_nonexistent_is_noop(service):
    """失效不存在的 unit → 不报错。"""
    service.invalidate("nonexistent")


# --- GC（Q8: B） ---


def test_cleanup_orphans_removes_orphaned_records(
    service, cache_repo, content_unit_repo, db_connection, thumbnails_dir
):
    """GC 清理无对应 content_unit 的缓存记录。"""
    # 临时关闭 FK 约束以插入孤儿记录（无对应 content_unit）
    db_connection.commit()
    db_connection.execute("PRAGMA foreign_keys = OFF;")
    cache_repo.upsert(
        ThumbnailCache(
            content_unit_id="orphan",
            source_size_bytes=100,
            source_modified_at="2026-07-01T00:00:00Z",
            cache_filename="orphan.png",
            status="ok",
            generated_at="2026-07-01T00:00:01Z",
        )
    )
    db_connection.commit()
    db_connection.execute("PRAGMA foreign_keys = ON;")
    # 创建对应的缓存文件
    (thumbnails_dir / "orphan.png").write_bytes(b"fake png")

    cleaned = service.cleanup_orphans()
    assert cleaned >= 1
    assert cache_repo.get_by_id("orphan") is None
    assert not (thumbnails_dir / "orphan.png").exists()


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
    service.generate(unit.id, cover_path)
    db_connection.commit()

    cleaned = service.cleanup_orphans()
    assert cleaned == 0
    assert cache_repo.get_by_id(unit.id) is not None
    assert (thumbnails_dir / f"{unit.id}.png").exists()


def test_cleanup_orphans_removes_orphaned_files(
    service, cache_repo, content_unit_repo, db_connection, thumbnails_dir
):
    """GC 清理目录中无对应记录的 PNG 文件。"""
    # 创建一个无 DB 记录的 PNG 文件
    (thumbnails_dir / "orphan_file.png").write_bytes(b"fake png")

    cleaned = service.cleanup_orphans()
    assert cleaned >= 1
    assert not (thumbnails_dir / "orphan_file.png").exists()
