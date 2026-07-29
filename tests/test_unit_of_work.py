"""UnitOfWork 单元测试（Stage 4.5 D3）。

覆盖：
- 基本事务：成功 commit，异常 rollback
- 嵌套事务：内层不提交/回滚，仅最外层生效
- 嵌套异常：内层异常导致外层回滚
- UoW 为 None 的兼容场景（由 Service 层处理）

测试使用专用 uow_test 表（仅 key/value，无 NOT NULL 约束），
使测试聚焦于事务行为而非具体业务表 schema。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from infrastructure.db import get_connection, init_db
from infrastructure.unit_of_work import UnitOfWork


@pytest.fixture
def conn(db_path: Path) -> sqlite3.Connection:
    """临时数据库连接 + 专用 uow_test 表。"""
    init_db(db_path)
    c = get_connection(db_path)
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS uow_test (key TEXT PRIMARY KEY, value TEXT)")
    c.commit()
    yield c
    c.close()


@pytest.fixture
def uow(conn: sqlite3.Connection) -> UnitOfWork:
    return UnitOfWork(conn)


def _insert(conn: sqlite3.Connection, key: str, value: str = "x") -> None:
    """向 uow_test 插入一行（避免重复长 SQL 字符串）。"""
    conn.execute("INSERT INTO uow_test (key, value) VALUES (?, ?)", (key, value))


def _exists(conn: sqlite3.Connection, key: str) -> bool:
    return conn.execute("SELECT key FROM uow_test WHERE key = ?", (key,)).fetchone() is not None


def test_transaction_success_commits(uow: UnitOfWork, conn: sqlite3.Connection) -> None:
    """成功退出 → commit。"""
    with uow.transaction():
        _insert(conn, "r1")
    # commit 后同连接内查询存在
    assert _exists(conn, "r1")


def test_transaction_exception_rolls_back(uow: UnitOfWork, conn: sqlite3.Connection) -> None:
    """异常退出 → rollback。"""
    with pytest.raises(RuntimeError, match="模拟失败"), uow.transaction():
        _insert(conn, "r2")
        raise RuntimeError("模拟失败")
    # rollback 后记录不存在
    assert not _exists(conn, "r2")


def test_nested_transaction_outer_commits(uow: UnitOfWork, conn: sqlite3.Connection) -> None:
    """嵌套事务：仅最外层 commit，内层不提交。"""
    with uow.transaction():  # depth 0→1
        _insert(conn, "r3")
        with uow.transaction():  # depth 1→2，内层不提交
            _insert(conn, "r4")
        # 内层退出后 depth 2→1，未提交
        assert uow.depth == 1
    # 外层退出后 depth 1→0，提交
    assert uow.depth == 0
    assert _exists(conn, "r3")
    assert _exists(conn, "r4")


def test_nested_transaction_inner_exception_rolls_back_outer(
    uow: UnitOfWork, conn: sqlite3.Connection
) -> None:
    """嵌套事务：内层异常 → 外层回滚所有写操作。"""
    with pytest.raises(ValueError, match="内层失败"), uow.transaction():  # depth 0→1
        _insert(conn, "r5")
        with uow.transaction():  # depth 1→2
            _insert(conn, "r6")
            raise ValueError("内层失败")
        # 内层异常，不会执行到这里
    # 外层回滚后两条记录都不存在
    assert not _exists(conn, "r5")
    assert not _exists(conn, "r6")


def test_nested_transaction_outer_exception_after_inner_success(
    uow: UnitOfWork, conn: sqlite3.Connection
) -> None:
    """嵌套事务：内层成功但外层后续异常 → 外层回滚（含内层的写操作）。"""
    with pytest.raises(RuntimeError, match="外层后续失败"), uow.transaction():  # depth 0→1
        _insert(conn, "r7")
        with uow.transaction():  # depth 1→2
            _insert(conn, "r8")
        # 内层成功退出，depth 2→1
        assert uow.depth == 1
        raise RuntimeError("外层后续失败")
    # 外层回滚，两条记录都不存在
    assert not _exists(conn, "r7")
    assert not _exists(conn, "r8")


def test_depth_tracking(uow: UnitOfWork) -> None:
    """深度计数正确跟踪嵌套层级。"""
    assert uow.depth == 0
    with uow.transaction():
        assert uow.depth == 1
        with uow.transaction():
            assert uow.depth == 2
            with uow.transaction():
                assert uow.depth == 3
            assert uow.depth == 2
        assert uow.depth == 1
    assert uow.depth == 0


def test_depth_resets_after_exception(uow: UnitOfWork) -> None:
    """异常后深度正确恢复为 0。"""
    with pytest.raises(ValueError), uow.transaction():
        assert uow.depth == 1
        with uow.transaction():
            assert uow.depth == 2
            raise ValueError("内层异常")
    assert uow.depth == 0
