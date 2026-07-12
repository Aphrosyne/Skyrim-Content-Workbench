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
from infrastructure.repositories.errors import ConstraintViolationError, NotFoundError
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


def test_create_commits_transaction_without_explicit_commit(db_path: Path, tmp_path: Path) -> None:
    """create 应自提交事务，无需调用方显式 commit 即可跨连接可见。

    回归测试：修复前 create 未调用 conn.commit()，关闭连接后数据丢失。
    """
    init_db(db_path)
    path = tmp_path / "AutoCommit"
    path.mkdir()

    # 第一次连接：写入但不显式 commit
    conn1 = get_connection(db_path)
    conn1.row_factory = sqlite3.Row
    try:
        repo1 = ManagedRootRepository(conn1)
        repo1.create(_make_root(path, root_id="autocommit-1"))
    finally:
        conn1.close()

    # 第二次连接：应能读到（证明 create 已自提交）
    conn2 = get_connection(db_path)
    conn2.row_factory = sqlite3.Row
    try:
        repo2 = ManagedRootRepository(conn2)
        fetched = repo2.get_by_id("autocommit-1")
        assert fetched is not None, "create 未提交事务，数据丢失"
        assert fetched.real_path == str(path)
    finally:
        conn2.close()


# --- delete 测试（Task 1 遗漏补完） ---


def test_delete_removes_record(db_connection: sqlite3.Connection, tmp_path: Path) -> None:
    """delete 后记录不再可查。"""
    repo = ManagedRootRepository(db_connection)
    path = tmp_path / "Mods"
    path.mkdir()
    repo.create(_make_root(path, root_id="del-1"))

    repo.delete("del-1")

    assert repo.get_by_id("del-1") is None


def test_delete_commits_without_explicit_commit(db_path: Path, tmp_path: Path) -> None:
    """delete 应自提交事务，跨连接可见。

    回归测试：与 create 保持一致的事务策略。
    """
    init_db(db_path)
    path = tmp_path / "AutoCommitDelete"
    path.mkdir()

    # 第一次连接：写入并删除，但不显式 commit
    conn1 = get_connection(db_path)
    conn1.row_factory = sqlite3.Row
    try:
        repo1 = ManagedRootRepository(conn1)
        repo1.create(_make_root(path, root_id="del-autocommit"))
        repo1.delete("del-autocommit")
    finally:
        conn1.close()

    # 第二次连接：应已删除（证明 delete 自提交）
    conn2 = get_connection(db_path)
    conn2.row_factory = sqlite3.Row
    try:
        repo2 = ManagedRootRepository(conn2)
        assert repo2.get_by_id("del-autocommit") is None
    finally:
        conn2.close()


def test_delete_missing_raises_not_found_error(db_connection: sqlite3.Connection) -> None:
    """删除不存在的 id 抛 NotFoundError。"""
    repo = ManagedRootRepository(db_connection)
    with pytest.raises(NotFoundError):
        repo.delete("nonexistent")


def test_delete_does_not_affect_other_roots(
    db_connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """删除一个根目录不影响其他根目录。"""
    repo = ManagedRootRepository(db_connection)
    p1 = tmp_path / "alpha"
    p1.mkdir()
    p2 = tmp_path / "beta"
    p2.mkdir()

    repo.create(_make_root(p1, root_id="a"))
    repo.create(_make_root(p2, root_id="b"))

    repo.delete("a")

    assert repo.get_by_id("a") is None
    assert repo.get_by_id("b") is not None
    roots = repo.list_all()
    assert [r.id for r in roots] == ["b"]


def test_delete_preserves_content_unit_and_folder_cache(
    db_connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """删除 managed_root 记录不清理 content_unit / folder_cache 扫描记录。

    方向 C 重建后（v4），扫描记录存储于 content_unit 与 folder_cache 表。
    ManagedRootRepository.delete 仅删除 managed_root 记录，不触碰其他表。
    """
    repo = ManagedRootRepository(db_connection)
    path = tmp_path / "Mods"
    path.mkdir()
    repo.create(_make_root(path, root_id="del-2"))

    # 模拟扫描结果存在（直接插入 content_unit 与 folder_cache）
    db_connection.execute(
        "INSERT INTO content_unit (id, path, title, content_type, status, "
        "created_at, updated_at) VALUES "
        "('cu-1', ?, 'Mods', 'mod', 'unorganized', '2026-07-07T00:00:00Z', '2026-07-07T00:00:00Z')",
        (str(path),),
    )
    db_connection.execute(
        "INSERT INTO folder_cache (id, path, created_at) VALUES "
        "('fc-1', ?, '2026-07-07T00:00:00Z')",
        (str(path),),
    )
    db_connection.commit()

    repo.delete("del-2")

    # managed_root 已删除
    assert repo.get_by_id("del-2") is None
    # content_unit 仍存在
    cu_row = db_connection.execute("SELECT id FROM content_unit WHERE id = 'cu-1'").fetchone()
    assert cu_row is not None
    # folder_cache 仍存在
    fc_row = db_connection.execute("SELECT id FROM folder_cache WHERE id = 'fc-1'").fetchone()
    assert fc_row is not None
