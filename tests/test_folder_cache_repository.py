"""FolderCacheRepository 测试。

覆盖 CRUD、path 唯一约束、parent_id 自引用、upsert_mtime。
"""

from __future__ import annotations

import sqlite3

import pytest

from domain.models import FolderCache
from infrastructure.repositories.errors import (
    ConstraintViolationError,
    NotFoundError,
)
from infrastructure.repositories.folder_cache import FolderCacheRepository


@pytest.fixture
def repo(db_connection: sqlite3.Connection) -> FolderCacheRepository:
    return FolderCacheRepository(db_connection)


def _make_folder(
    folder_id: str = "f-1",
    path: str = "/mods",
    **kwargs,
) -> FolderCache:
    defaults = {
        "id": folder_id,
        "path": path,
        "created_at": "2026-07-12T00:00:00Z",
    }
    defaults.update(kwargs)
    return FolderCache(**defaults)


class TestCreateAndGet:
    def test_create_and_get_by_id(self, repo: FolderCacheRepository) -> None:
        folder = _make_folder()
        created = repo.create(folder)
        assert created.id == "f-1"

        fetched = repo.get_by_id("f-1")
        assert fetched is not None
        assert fetched.path == "/mods"

    def test_get_by_id_not_exist(self, repo: FolderCacheRepository) -> None:
        assert repo.get_by_id("nonexistent") is None

    def test_get_by_path(self, repo: FolderCacheRepository) -> None:
        repo.create(_make_folder(path="/mods/护甲"))
        fetched = repo.get_by_path("/mods/护甲")
        assert fetched is not None
        assert fetched.path == "/mods/护甲"

    def test_get_by_path_not_exist(self, repo: FolderCacheRepository) -> None:
        assert repo.get_by_path("/nonexistent") is None

    def test_chinese_path(self, repo: FolderCacheRepository) -> None:
        repo.create(_make_folder(path="D:/Mods/护甲"))
        fetched = repo.get_by_path("D:/Mods/护甲")
        assert fetched is not None


class TestPathUniqueConstraint:
    def test_duplicate_path_raises(self, repo: FolderCacheRepository) -> None:
        repo.create(_make_folder(folder_id="f-1", path="/a"))
        with pytest.raises(ConstraintViolationError):
            repo.create(_make_folder(folder_id="f-2", path="/a"))


class TestListByParent:
    def test_list_root_nodes(self, repo: FolderCacheRepository) -> None:
        repo.create(_make_folder(folder_id="f-1", path="/a"))
        repo.create(_make_folder(folder_id="f-2", path="/b"))
        repo.create(_make_folder(folder_id="f-3", path="/a/sub", parent_id="f-1"))

        roots = repo.list_by_parent(None)
        assert len(roots) == 2
        root_paths = {f.path for f in roots}
        assert "/a" in root_paths
        assert "/b" in root_paths

    def test_list_children(self, repo: FolderCacheRepository) -> None:
        repo.create(_make_folder(folder_id="f-1", path="/a"))
        repo.create(_make_folder(folder_id="f-2", path="/a/sub1", parent_id="f-1"))
        repo.create(_make_folder(folder_id="f-3", path="/a/sub2", parent_id="f-1"))

        children = repo.list_by_parent("f-1")
        assert len(children) == 2
        child_paths = {f.path for f in children}
        assert "/a/sub1" in child_paths
        assert "/a/sub2" in child_paths

    def test_list_children_empty(self, repo: FolderCacheRepository) -> None:
        repo.create(_make_folder(folder_id="f-1", path="/a"))
        children = repo.list_by_parent("f-1")
        assert children == []


class TestListAll:
    def test_list_all_ordered_by_path(self, repo: FolderCacheRepository) -> None:
        repo.create(_make_folder(folder_id="f-2", path="/b"))
        repo.create(_make_folder(folder_id="f-1", path="/a"))
        result = repo.list_all()
        assert len(result) == 2
        assert result[0].path == "/a"
        assert result[1].path == "/b"


class TestUpsertMtime:
    def test_upsert_mtime_updates_existing(self, repo: FolderCacheRepository) -> None:
        repo.create(_make_folder(folder_id="f-1", path="/a"))
        repo.upsert_mtime(path="/a", mtime=1000.5, folder_id="f-1")

        fetched = repo.get_by_id("f-1")
        assert fetched is not None
        assert fetched.last_scanned_mtime == 1000.5

    def test_upsert_mtime_overwrites(self, repo: FolderCacheRepository) -> None:
        repo.create(_make_folder(folder_id="f-1", path="/a", last_scanned_mtime=1000.0))
        repo.upsert_mtime(path="/a", mtime=2000.0, folder_id="f-1")

        fetched = repo.get_by_id("f-1")
        assert fetched is not None
        assert fetched.last_scanned_mtime == 2000.0

    def test_upsert_mtime_not_exist_raises(self, repo: FolderCacheRepository) -> None:
        with pytest.raises(NotFoundError):
            repo.upsert_mtime(path="/x", mtime=1.0, folder_id="nonexistent")


class TestParentSelfReference:
    def test_parent_id_self_reference_allowed(self, repo: FolderCacheRepository) -> None:
        """parent_id 自引用应允许（schema 未约束）。"""
        repo.create(_make_folder(folder_id="f-1", path="/a", parent_id="f-1"))
        fetched = repo.get_by_id("f-1")
        assert fetched is not None
        assert fetched.parent_id == "f-1"


class TestDelete:
    def test_delete_by_id(self, repo: FolderCacheRepository) -> None:
        repo.create(_make_folder())
        repo.delete("f-1")
        assert repo.get_by_id("f-1") is None

    def test_delete_by_id_not_exist_raises(self, repo: FolderCacheRepository) -> None:
        with pytest.raises(NotFoundError):
            repo.delete("nonexistent")

    def test_delete_by_path(self, repo: FolderCacheRepository) -> None:
        repo.create(_make_folder(path="/a"))
        repo.delete_by_path("/a")
        assert repo.get_by_path("/a") is None

    def test_delete_by_path_not_exist_raises(self, repo: FolderCacheRepository) -> None:
        with pytest.raises(NotFoundError):
            repo.delete_by_path("/nonexistent")
