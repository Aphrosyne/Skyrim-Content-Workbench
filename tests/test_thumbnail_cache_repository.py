"""ThumbnailCacheRepository 单元测试。"""

from __future__ import annotations

import pytest

from domain.models import ContentUnit, ThumbnailCache
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.thumbnail_cache import ThumbnailCacheRepository


@pytest.fixture
def content_unit_repo(db_connection) -> ContentUnitRepository:
    return ContentUnitRepository(db_connection)


@pytest.fixture
def cache_repo(db_connection, content_unit_repo) -> ThumbnailCacheRepository:
    """预创建 u1/u2/u3 三个 content_unit 以满足 thumbnail_cache 的 FK 约束。"""
    for unit_id in ("u1", "u2", "u3"):
        content_unit_repo.create(_make_unit(unit_id))
    db_connection.commit()
    return ThumbnailCacheRepository(db_connection)


def _make_unit(unit_id: str = "u1") -> ContentUnit:
    return ContentUnit(
        id=unit_id,
        path=f"/test/{unit_id}",
        title=f"Unit {unit_id}",
        content_type="mod",
        status="unorganized",
        created_at="2026-07-01T00:00:00Z",
        updated_at="2026-07-01T00:00:00Z",
    )


def _make_cache(
    unit_id: str = "u1",
    status: str = "ok",
    error_message: str | None = None,
) -> ThumbnailCache:
    return ThumbnailCache(
        content_unit_id=unit_id,
        source_size_bytes=1024,
        source_modified_at="2026-07-01T00:00:00Z",
        cache_filename=f"{unit_id}.png",
        status=status,
        generated_at="2026-07-01T00:00:01Z",
        error_message=error_message,
    )


def test_get_by_id_empty_returns_none(cache_repo):
    assert cache_repo.get_by_id("nonexistent") is None


def test_upsert_and_get(cache_repo):
    cache = _make_cache(unit_id="u1", status="ok")
    cache_repo.upsert(cache)
    got = cache_repo.get_by_id("u1")
    assert got is not None
    assert got.content_unit_id == "u1"
    assert got.source_size_bytes == 1024
    assert got.status == "ok"
    assert got.cache_filename == "u1.png"
    assert got.error_message is None


def test_upsert_replaces_existing(cache_repo):
    cache_repo.upsert(_make_cache(unit_id="u1", status="ok"))
    cache_repo.upsert(_make_cache(unit_id="u1", status="corrupt", error_message="bad data"))
    got = cache_repo.get_by_id("u1")
    assert got is not None
    assert got.status == "corrupt"
    assert got.error_message == "bad data"


def test_delete_returns_true_when_exists(cache_repo):
    cache_repo.upsert(_make_cache(unit_id="u1"))
    assert cache_repo.delete("u1") is True


def test_delete_returns_false_when_absent(cache_repo):
    assert cache_repo.delete("nonexistent") is False


def test_list_all_returns_all(cache_repo):
    cache_repo.upsert(_make_cache(unit_id="u1"))
    cache_repo.upsert(_make_cache(unit_id="u2"))
    caches = cache_repo.list_all()
    assert len(caches) == 2
    assert {c.content_unit_id for c in caches} == {"u1", "u2"}


def test_list_by_unit_ids_batch_query(cache_repo):
    cache_repo.upsert(_make_cache(unit_id="u1"))
    cache_repo.upsert(_make_cache(unit_id="u2"))
    cache_repo.upsert(_make_cache(unit_id="u3"))
    result = cache_repo.list_by_unit_ids(["u1", "u3"])
    assert set(result.keys()) == {"u1", "u3"}


def test_list_by_unit_ids_empty_input(cache_repo):
    result = cache_repo.list_by_unit_ids([])
    assert result == {}


def test_list_by_unit_ids_unknown_id_omitted(cache_repo):
    cache_repo.upsert(_make_cache(unit_id="u1"))
    result = cache_repo.list_by_unit_ids(["u1", "unknown"])
    assert set(result.keys()) == {"u1"}
