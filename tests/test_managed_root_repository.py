"""ManagedRootRepository 测试。

覆盖：
- 创建与读取；
- 中文路径；
- path_key 唯一约束；
- 重启/重新连接数据库后可读取。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from domain.models import ManagedRoot
from infrastructure.db import get_connection, init_db
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.errors import ConstraintViolationError
from infrastructure.repositories.managed_root import ManagedRootRepository


def _make_root(
    real_path: Path,
    *,
    root_id: str = "root-1",
    display_name: str | None = None,
    created_at: str = "2026-07-07T00:00:00Z",
    updated_at: str = "2026-07-07T00:00:00Z",
) -> ManagedRoot:
    return ManagedRoot(
        id=root_id,
        real_path=str(real_path),
        path_key=make_path_key(real_path),
        display_name=display_name if display_name is not None else real_path.name,
        created_at=created_at,
        updated_at=updated_at,
    )


def test_create_and_get_by_id(db_connection: sqlite3.Connection, tmp_path: Path) -> None:
    """创建后可按 id 查询。"""
    repo = ManagedRootRepository(db_connection)
    path = tmp_path / "Mods"
    path.mkdir()
    root = _make_root(path)

    created = repo.create(root)
    assert created.id == root.id
    assert created.real_path == str(path)
    assert created.path_key == make_path_key(path)
    assert created.display_name == "Mods"

    fetched = repo.get_by_id(root.id)
    assert fetched is not None
    assert fetched.id == root.id
    assert fetched.real_path == str(path)


def test_create_with_chinese_path(db_connection: sqlite3.Connection, tmp_path: Path) -> None:
    """中文路径可往返保存。"""
    repo = ManagedRootRepository(db_connection)
    path = tmp_path / "我的模组目录"
    path.mkdir()

    root = _make_root(path, root_id="cn-1")
    repo.create(root)

    fetched = repo.get_by_id("cn-1")
    assert fetched is not None
    assert fetched.real_path == str(path)
    assert "我的模组目录" in fetched.real_path
    assert fetched.display_name == "我的模组目录"


def test_get_by_path_key(db_connection: sqlite3.Connection, tmp_path: Path) -> None:
    """按 path_key 查询用于去重检查。"""
    repo = ManagedRootRepository(db_connection)
    path = tmp_path / "Mods"
    path.mkdir()
    repo.create(_make_root(path, root_id="a"))

    fetched = repo.get_by_path_key(make_path_key(path))
    assert fetched is not None
    assert fetched.id == "a"

    # 不存在的 path_key 返回 None
    other = repo.get_by_path_key(make_path_key(tmp_path / "Other"))
    assert other is None


def test_path_key_unique_constraint(db_connection: sqlite3.Connection, tmp_path: Path) -> None:
    """同一 path_key 重复插入应抛 ConstraintViolationError。"""
    repo = ManagedRootRepository(db_connection)
    path = tmp_path / "Mods"
    path.mkdir()

    repo.create(_make_root(path, root_id="first"))

    # 同路径不同 id 仍触发 path_key 唯一约束
    duplicate = _make_root(path, root_id="second")
    with pytest.raises(ConstraintViolationError):
        repo.create(duplicate)


def test_list_all_ordered_by_real_path(db_connection: sqlite3.Connection, tmp_path: Path) -> None:
    """list_all 按 real_path 排序返回全部条目。"""
    repo = ManagedRootRepository(db_connection)
    p1 = tmp_path / "alpha"
    p1.mkdir()
    p2 = tmp_path / "beta"
    p2.mkdir()
    p3 = tmp_path / "伽马"
    p3.mkdir()

    repo.create(_make_root(p2, root_id="b"))
    repo.create(_make_root(p1, root_id="a"))
    repo.create(_make_root(p3, root_id="c"))

    roots = repo.list_all()
    assert [r.id for r in roots] == ["a", "b", "c"]
    assert len(roots) == 3


def test_persisted_across_reconnect(db_path: Path, tmp_path: Path) -> None:
    """关闭并重新打开数据库后，已保存的根目录仍可读取。"""
    init_db(db_path)
    path = tmp_path / "Persisted"
    path.mkdir()

    # 第一次连接：写入
    conn1 = get_connection(db_path)
    conn1.row_factory = sqlite3.Row
    try:
        repo1 = ManagedRootRepository(conn1)
        repo1.create(_make_root(path, root_id="persist-1"))
        conn1.commit()
    finally:
        conn1.close()

    # 第二次连接：读取
    conn2 = get_connection(db_path)
    conn2.row_factory = sqlite3.Row
    try:
        repo2 = ManagedRootRepository(conn2)
        fetched = repo2.get_by_id("persist-1")
        assert fetched is not None
        assert fetched.real_path == str(path)
        assert fetched.display_name == "Persisted"
    finally:
        conn2.close()


def test_get_by_id_returns_none_for_missing(
    db_connection: sqlite3.Connection,
) -> None:
    """不存在 id 返回 None。"""
    repo = ManagedRootRepository(db_connection)
    assert repo.get_by_id("nonexistent") is None
