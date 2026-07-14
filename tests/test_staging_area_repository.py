"""StagingAreaRepository 测试。

覆盖：
- 创建与读取；
- 中文路径；
- path_key 唯一约束；
- list_all 排序；
- delete 行为；
- 重启/重新连接数据库后可读取。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from domain.models import StagingArea
from infrastructure.db import get_connection, init_db
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.errors import ConstraintViolationError, NotFoundError
from infrastructure.repositories.staging_area import StagingAreaRepository


def _make_staging(
    real_path: Path,
    *,
    staging_id: str = "st-1",
    display_name: str | None = None,
    created_at: str = "2026-07-14T00:00:00Z",
    updated_at: str = "2026-07-14T00:00:00Z",
) -> StagingArea:
    return StagingArea(
        id=staging_id,
        real_path=str(real_path),
        path_key=make_path_key(real_path),
        display_name=display_name if display_name is not None else real_path.name,
        created_at=created_at,
        updated_at=updated_at,
    )


def test_create_and_get_by_id(db_connection: sqlite3.Connection, tmp_path: Path) -> None:
    """创建后可按 id 查询。"""
    repo = StagingAreaRepository(db_connection)
    path = tmp_path / "Stash"
    path.mkdir()
    staging = _make_staging(path)

    created = repo.create(staging)
    assert created.id == staging.id
    assert created.real_path == str(path)
    assert created.path_key == make_path_key(path)
    assert created.display_name == "Stash"

    fetched = repo.get_by_id(staging.id)
    assert fetched is not None
    assert fetched.id == staging.id
    assert fetched.real_path == str(path)


def test_create_with_chinese_path(db_connection: sqlite3.Connection, tmp_path: Path) -> None:
    """中文路径可往返保存。"""
    repo = StagingAreaRepository(db_connection)
    path = tmp_path / "暂存目录"
    path.mkdir()

    repo.create(_make_staging(path, staging_id="cn-1"))

    fetched = repo.get_by_id("cn-1")
    assert fetched is not None
    assert fetched.real_path == str(path)
    assert "暂存目录" in fetched.real_path
    assert fetched.display_name == "暂存目录"


def test_get_by_path_key(db_connection: sqlite3.Connection, tmp_path: Path) -> None:
    """按 path_key 查询用于去重检查。"""
    repo = StagingAreaRepository(db_connection)
    path = tmp_path / "Stash"
    path.mkdir()
    repo.create(_make_staging(path, staging_id="a"))

    fetched = repo.get_by_path_key(make_path_key(path))
    assert fetched is not None
    assert fetched.id == "a"

    # 不存在的 path_key 返回 None
    other = repo.get_by_path_key(make_path_key(tmp_path / "Other"))
    assert other is None


def test_path_key_unique_constraint(db_connection: sqlite3.Connection, tmp_path: Path) -> None:
    """同一 path_key 重复插入应抛 ConstraintViolationError。"""
    repo = StagingAreaRepository(db_connection)
    path = tmp_path / "Stash"
    path.mkdir()

    repo.create(_make_staging(path, staging_id="first"))

    # 同路径不同 id 仍触发 path_key 唯一约束
    duplicate = _make_staging(path, staging_id="second")
    with pytest.raises(ConstraintViolationError):
        repo.create(duplicate)


def test_list_all_ordered_by_real_path(db_connection: sqlite3.Connection, tmp_path: Path) -> None:
    """list_all 按 real_path 排序返回全部条目。"""
    repo = StagingAreaRepository(db_connection)
    p1 = tmp_path / "alpha"
    p1.mkdir()
    p2 = tmp_path / "beta"
    p2.mkdir()
    p3 = tmp_path / "伽马"
    p3.mkdir()

    repo.create(_make_staging(p2, staging_id="b"))
    repo.create(_make_staging(p1, staging_id="a"))
    repo.create(_make_staging(p3, staging_id="c"))

    stgings = repo.list_all()
    assert [s.id for s in stgings] == ["a", "b", "c"]
    assert len(stgings) == 3


def test_get_by_id_returns_none_for_missing(
    db_connection: sqlite3.Connection,
) -> None:
    """不存在 id 返回 None。"""
    repo = StagingAreaRepository(db_connection)
    assert repo.get_by_id("nonexistent") is None


def test_delete_removes_record(db_connection: sqlite3.Connection, tmp_path: Path) -> None:
    """delete 后记录不再可查。"""
    repo = StagingAreaRepository(db_connection)
    path = tmp_path / "Stash"
    path.mkdir()
    repo.create(_make_staging(path, staging_id="del-1"))

    repo.delete("del-1")

    assert repo.get_by_id("del-1") is None


def test_delete_missing_raises_not_found_error(
    db_connection: sqlite3.Connection,
) -> None:
    """删除不存在的 id 抛 NotFoundError。"""
    repo = StagingAreaRepository(db_connection)
    with pytest.raises(NotFoundError):
        repo.delete("nonexistent")


def test_delete_does_not_affect_other_staging_areas(
    db_connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """删除一个暂存区不影响其他暂存区。"""
    repo = StagingAreaRepository(db_connection)
    p1 = tmp_path / "alpha"
    p1.mkdir()
    p2 = tmp_path / "beta"
    p2.mkdir()

    repo.create(_make_staging(p1, staging_id="a"))
    repo.create(_make_staging(p2, staging_id="b"))

    repo.delete("a")

    assert repo.get_by_id("a") is None
    assert repo.get_by_id("b") is not None
    stgings = repo.list_all()
    assert [s.id for s in stgings] == ["b"]


def test_persisted_across_reconnect(db_path: Path, tmp_path: Path) -> None:
    """关闭并重新打开数据库后，已保存的暂存区标记仍可读取。"""
    init_db(db_path)
    path = tmp_path / "PersistedStash"
    path.mkdir()

    # 第一次连接：写入
    conn1 = get_connection(db_path)
    conn1.row_factory = sqlite3.Row
    try:
        repo1 = StagingAreaRepository(conn1)
        repo1.create(_make_staging(path, staging_id="persist-1"))
        conn1.commit()
    finally:
        conn1.close()

    # 第二次连接：读取
    conn2 = get_connection(db_path)
    conn2.row_factory = sqlite3.Row
    try:
        repo2 = StagingAreaRepository(conn2)
        fetched = repo2.get_by_id("persist-1")
        assert fetched is not None
        assert fetched.real_path == str(path)
        assert fetched.display_name == "PersistedStash"
    finally:
        conn2.close()


def test_create_requires_explicit_commit(db_path: Path, tmp_path: Path) -> None:
    """create 不自提交事务，需调用方显式 commit 才能跨连接可见。

    H5 一致性：Repository 不自提交，由 application 层控制事务边界。
    """
    init_db(db_path)
    path = tmp_path / "ExplicitCommit"
    path.mkdir()

    # 第一次连接：写入但不显式 commit
    conn1 = get_connection(db_path)
    try:
        repo1 = StagingAreaRepository(conn1)
        repo1.create(_make_staging(path, staging_id="no-commit-1"))
    finally:
        conn1.close()

    # 第二次连接：不应能读到（未提交）
    conn2 = get_connection(db_path)
    try:
        repo2 = StagingAreaRepository(conn2)
        fetched = repo2.get_by_id("no-commit-1")
        assert fetched is None, "create 不应自提交，未显式 commit 的数据不应跨连接可见"
    finally:
        conn2.close()

    # 第三次连接：显式 commit 后应能读到
    conn3 = get_connection(db_path)
    try:
        repo3 = StagingAreaRepository(conn3)
        repo3.create(_make_staging(path, staging_id="committed-1"))
        conn3.commit()
    finally:
        conn3.close()

    conn4 = get_connection(db_path)
    try:
        repo4 = StagingAreaRepository(conn4)
        fetched = repo4.get_by_id("committed-1")
        assert fetched is not None, "显式 commit 后数据应跨连接可见"
        assert fetched.real_path == str(path)
    finally:
        conn4.close()
