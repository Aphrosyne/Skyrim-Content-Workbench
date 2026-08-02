"""FolderCacheSyncHelper 单元测试（Stage 4.5 TD-M22 + H4 + TD-L18）。

覆盖：
- on_folder_created：插入 folder_cache 记录 + parent_id 关联
- on_folder_moved：删除旧 + 插入新 + 更新父 mtime（多步原子性）
- on_folder_deleted：删除 folder_cache 记录
- update_folder_mtime：best-effort 单字段更新（TD-L18 策略）
- is_in_directory：模块级路径归属判断
- 错误处理：多步同步失败抛 FileOperationError
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from domain.models import FolderCache
from infrastructure.folder_cache_sync_helper import (
    FolderCacheSyncHelper,
    is_in_directory,
)
from infrastructure.repositories.folder_cache import FolderCacheRepository


@pytest.fixture
def helper(db_connection: sqlite3.Connection) -> FolderCacheSyncHelper:
    """构造 FolderCacheSyncHelper（使用真实 folder_cache 表）。"""
    repo = FolderCacheRepository(db_connection)
    return FolderCacheSyncHelper(
        repo,
        now_provider=lambda: "2026-07-28T00:00:00Z",
        uuid_provider=lambda: "fc-test-id",
    )


def _seed_folder_cache(
    conn: sqlite3.Connection, path: str, parent_id: str | None = None
) -> FolderCache:
    """插入一条 folder_cache 记录用于测试。"""
    repo = FolderCacheRepository(conn)
    folder = FolderCache(
        id=f"seed-{path}",
        path=path,
        parent_id=parent_id,
        last_scanned_mtime=1000.0,
        created_at="2026-07-28T00:00:00Z",
    )
    return repo.create(folder)


# === on_folder_created ===


def test_on_folder_created_inserts_record(helper, db_connection, tmp_path):
    """on_folder_created → folder_cache 表新增一条记录。"""
    parent = tmp_path / "Mods"
    parent.mkdir()
    new_folder = parent / "NewMod"
    new_folder.mkdir()

    helper.on_folder_created(new_folder, parent)

    repo = FolderCacheRepository(db_connection)
    fc = repo.get_by_path(str(new_folder))
    assert fc is not None
    assert fc.parent_id is None  # parent 不在 folder_cache 中 → None
    assert fc.path == str(new_folder)


def test_on_folder_created_resolves_parent_id(helper, db_connection, tmp_path):
    """on_folder_created → parent_id 关联到 folder_cache 中已有的父目录记录。"""
    parent = tmp_path / "Mods"
    parent.mkdir()
    _seed_folder_cache(db_connection, str(parent))

    new_folder = parent / "NewMod"
    new_folder.mkdir()
    helper.on_folder_created(new_folder, parent)

    repo = FolderCacheRepository(db_connection)
    fc = repo.get_by_path(str(new_folder))
    assert fc is not None
    assert fc.parent_id == f"seed-{parent}"


def test_on_folder_created_raises_on_repo_failure(helper, db_connection, tmp_path):
    """on_folder_created → folder_cache 写入失败抛 FileOperationError。"""
    from application.errors import FileOperationError

    parent = tmp_path / "Mods"
    parent.mkdir()
    new_folder = parent / "NewMod"
    new_folder.mkdir()

    # 注入相同的 path_key 导致唯一约束冲突
    _seed_folder_cache(db_connection, str(new_folder))

    with pytest.raises(FileOperationError, match="写入 folder_cache 失败"):
        helper.on_folder_created(new_folder, parent)


# === on_folder_moved ===


def test_on_folder_moved_deletes_old_inserts_new(helper, db_connection, tmp_path):
    """on_folder_moved → 删除旧记录 + 插入新记录 + 更新父 mtime。"""
    old_parent = tmp_path / "OldDir"
    old_parent.mkdir()
    new_parent = tmp_path / "NewDir"
    new_parent.mkdir()

    old_folder = old_parent / "MyMod"
    old_folder.mkdir()
    new_folder = new_parent / "MyMod"
    new_folder.mkdir()

    _seed_folder_cache(db_connection, str(old_parent))
    _seed_folder_cache(db_connection, str(new_parent))
    _seed_folder_cache(db_connection, str(old_folder), parent_id=f"seed-{old_parent}")

    helper.on_folder_moved(old_folder, new_folder, new_parent)

    repo = FolderCacheRepository(db_connection)
    # 旧记录已删除
    assert repo.get_by_path(str(old_folder)) is None
    # 新记录已插入
    new_fc = repo.get_by_path(str(new_folder))
    assert new_fc is not None
    assert new_fc.parent_id == f"seed-{new_parent}"
    # 父目录 mtime 已更新（不再是 1000.0）
    parent_fc = repo.get_by_path(str(new_parent))
    assert parent_fc is not None
    assert parent_fc.last_scanned_mtime != 1000.0


def test_on_folder_moved_no_old_record(helper, db_connection, tmp_path):
    """on_folder_moved → 旧记录不存在时仍正常插入新记录。"""
    new_parent = tmp_path / "NewDir"
    new_parent.mkdir()
    new_folder = new_parent / "MyMod"
    new_folder.mkdir()

    _seed_folder_cache(db_connection, str(new_parent))

    # 旧路径无 folder_cache 记录，不应报错
    helper.on_folder_moved(tmp_path / "NonExistent", new_folder, new_parent)

    repo = FolderCacheRepository(db_connection)
    assert repo.get_by_path(str(new_folder)) is not None


def test_on_folder_moved_migrates_subtree(db_connection, tmp_path):
    """on_folder_moved → 整棵子树迁移（Bug紧急修复2：带子目录不再 FK 失败）。"""
    counter = {"n": 0}

    def fake_uuid() -> str:
        counter["n"] += 1
        return f"fc-move-{counter['n']}"

    helper = FolderCacheSyncHelper(
        FolderCacheRepository(db_connection),
        now_provider=lambda: "2026-07-28T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    old_parent = tmp_path / "OldDir"
    old_parent.mkdir()
    new_parent = tmp_path / "NewDir"
    new_parent.mkdir()

    old_folder = old_parent / "MyMod"
    old_folder.mkdir()
    old_sub = old_folder / "sub"
    old_sub.mkdir()
    old_sub2 = old_sub / "deep"
    old_sub2.mkdir()
    new_folder = new_parent / "MyMod"
    new_folder.mkdir()
    new_sub = new_folder / "sub"
    new_sub.mkdir()
    new_sub2 = new_sub / "deep"
    new_sub2.mkdir()

    # 缓存：OldDir / NewDir / MyMod / sub / deep（三层）
    old_parent_fc = _seed_folder_cache(db_connection, str(old_parent))
    _seed_folder_cache(db_connection, str(new_parent))
    root_fc = _seed_folder_cache(db_connection, str(old_folder), parent_id=old_parent_fc.id)
    sub_fc = _seed_folder_cache(db_connection, str(old_sub), parent_id=root_fc.id)
    _seed_folder_cache(db_connection, str(old_sub2), parent_id=sub_fc.id)

    # 不应抛 FOREIGN KEY 异常
    helper.on_folder_moved(old_folder, new_folder, new_parent)

    repo = FolderCacheRepository(db_connection)
    # 旧子树已删除
    assert repo.get_by_path(str(old_folder)) is None
    assert repo.get_by_path(str(old_sub)) is None
    assert repo.get_by_path(str(old_sub2)) is None
    # 新子树完整且父链正确（根 → sub → deep）
    new_root = repo.get_by_path(str(new_folder))
    assert new_root is not None
    assert new_root.parent_id == f"seed-{new_parent}"
    new_sub_row = repo.get_by_path(str(new_sub))
    assert new_sub_row is not None
    assert new_sub_row.parent_id == new_root.id
    new_sub2_row = repo.get_by_path(str(new_sub2))
    assert new_sub2_row is not None
    assert new_sub2_row.parent_id == new_sub_row.id


# === on_folder_deleted ===


def test_on_folder_deleted_removes_record(helper, db_connection, tmp_path):
    """on_folder_deleted → 删除 folder_cache 记录。"""
    folder = tmp_path / "ToDelete"
    folder.mkdir()
    _seed_folder_cache(db_connection, str(folder))

    helper.on_folder_deleted(folder)

    repo = FolderCacheRepository(db_connection)
    assert repo.get_by_path(str(folder)) is None


def test_on_folder_deleted_no_record(helper, tmp_path):
    """on_folder_deleted → 记录不存在时静默返回（不抛异常）。"""
    helper.on_folder_deleted(tmp_path / "NonExistent")


# === update_folder_mtime (TD-L18: best-effort) ===


def test_update_folder_mtime_updates_existing(helper, db_connection, tmp_path):
    """update_folder_mtime → 更新已存在记录的 mtime。"""
    folder = tmp_path / "Mod"
    folder.mkdir()
    _seed_folder_cache(db_connection, str(folder))

    helper.update_folder_mtime(folder)

    repo = FolderCacheRepository(db_connection)
    fc = repo.get_by_path(str(folder))
    assert fc is not None
    assert fc.last_scanned_mtime != 1000.0  # 已更新为真实 mtime


def test_update_folder_mtime_no_record_is_silent(helper, tmp_path):
    """update_folder_mtime → 路径不在 folder_cache 中时不报错（best-effort）。"""
    folder = tmp_path / "NotInCache"
    folder.mkdir()
    # 不在 folder_cache 中，应静默返回
    helper.update_folder_mtime(folder)


def test_update_folder_mtime_nonexistent_path_is_silent(helper, tmp_path):
    """update_folder_mtime → 路径不存在时不报错（best-effort）。"""
    helper.update_folder_mtime(tmp_path / "DoesNotExist")


# === is_in_directory ===


def test_is_in_directory_child():
    """子路径返回 True。"""
    assert is_in_directory(Path("D:/Mods/Armor/mod.7z"), Path("D:/Mods"))


def test_is_in_directory_self():
    """路径自身返回 True。"""
    assert is_in_directory(Path("D:/Mods"), Path("D:/Mods"))


def test_is_in_directory_sibling():
    """兄弟目录返回 False。"""
    assert not is_in_directory(Path("D:/Mods2/file"), Path("D:/Mods"))


def test_is_in_directory_parent_prefix():
    """前缀相似但非子目录返回 False（如 Mods vs Mods2）。"""
    assert not is_in_directory(Path("D:/Mods2"), Path("D:/Mods"))
