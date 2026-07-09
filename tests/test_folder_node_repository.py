"""FolderNodeRepository 测试。"""

from __future__ import annotations

import sqlite3

import pytest

from domain.models import FolderNode
from infrastructure.repositories.errors import ConstraintViolationError, NotFoundError
from infrastructure.repositories.folder_node import FolderNodeRepository


def _make_node(
    node_id: str = "node-1",
    real_path: str = "D:/Mods",
    path_key: str = "d:/mods",
    parent_id: str | None = None,
    is_managed_root: bool = True,
) -> FolderNode:
    return FolderNode(
        id=node_id,
        real_path=real_path,
        path_key=path_key,
        parent_id=parent_id,
        is_managed_root=is_managed_root,
        created_at="2026-07-07T00:00:00Z",
        updated_at="2026-07-07T00:00:00Z",
    )


def test_create_and_get(db_connection: sqlite3.Connection) -> None:
    repo = FolderNodeRepository(db_connection)
    node = FolderNode(
        id="node-1",
        real_path="D:/Mods",
        path_key="d:/mods",
        display_name="Mod 库",
        is_managed_root=True,
        created_at="2026-07-07T00:00:00Z",
        updated_at="2026-07-07T00:00:00Z",
    )
    created = repo.create(node)
    assert created.id == "node-1"
    assert created.display_name == "Mod 库"
    assert created.is_managed_root is True

    fetched = repo.get_by_id("node-1")
    assert fetched is not None
    assert fetched.real_path == "D:/Mods"
    assert fetched.display_name == "Mod 库"


def test_get_by_id_not_found(db_connection: sqlite3.Connection) -> None:
    repo = FolderNodeRepository(db_connection)
    assert repo.get_by_id("nonexistent") is None


def test_path_key_unique(db_connection: sqlite3.Connection) -> None:
    repo = FolderNodeRepository(db_connection)
    repo.create(_make_node())
    with pytest.raises(ConstraintViolationError):
        repo.create(_make_node(node_id="dup"))


def test_parent_child_relationship(db_connection: sqlite3.Connection) -> None:
    repo = FolderNodeRepository(db_connection)
    root = _make_node(node_id="root", path_key="d:/mods")
    repo.create(root)

    child = _make_node(
        node_id="child",
        real_path="D:/Mods/Armor",
        path_key="d:/mods/armor",
        parent_id="root",
        is_managed_root=False,
    )
    repo.create(child)

    roots = repo.list_by_parent(None)
    assert len(roots) == 1
    assert roots[0].id == "root"

    children = repo.list_by_parent("root")
    assert len(children) == 1
    assert children[0].id == "child"
    assert children[0].parent_id == "root"
    assert children[0].is_managed_root is False


def test_list_managed_roots(db_connection: sqlite3.Connection) -> None:
    repo = FolderNodeRepository(db_connection)
    repo.create(_make_node(node_id="r1", path_key="d:/mods1", is_managed_root=True))
    repo.create(_make_node(node_id="r2", path_key="d:/mods2", is_managed_root=True))
    repo.create(
        _make_node(
            node_id="child",
            path_key="d:/mods1/armor",
            is_managed_root=False,
            parent_id="r1",
        )
    )

    roots = repo.list_managed_roots()
    assert len(roots) == 2
    assert {r.id for r in roots} == {"r1", "r2"}


def test_update(db_connection: sqlite3.Connection) -> None:
    repo = FolderNodeRepository(db_connection)
    node = _make_node()
    repo.create(node)

    node.display_name = "已整理"
    node.updated_at = "2026-07-08T00:00:00Z"
    updated = repo.update(node)
    assert updated.display_name == "已整理"
    assert updated.updated_at == "2026-07-08T00:00:00Z"


def test_update_not_found_raises(db_connection: sqlite3.Connection) -> None:
    repo = FolderNodeRepository(db_connection)
    with pytest.raises(NotFoundError):
        repo.update(_make_node(node_id="nonexistent"))


def test_list_all_returns_all_nodes(db_connection: sqlite3.Connection) -> None:
    """list_all 返回全部节点（根+子），按 real_path 排序。"""
    repo = FolderNodeRepository(db_connection)
    repo.create(_make_node(node_id="root2", real_path="D:/Beta", path_key="d:/beta"))
    repo.create(_make_node(node_id="root1", real_path="D:/Alpha", path_key="d:/alpha"))
    repo.create(
        _make_node(
            node_id="child",
            real_path="D:/Alpha/Sub",
            path_key="d:/alpha/sub",
            parent_id="root1",
            is_managed_root=False,
        )
    )

    all_nodes = repo.list_all()
    assert len(all_nodes) == 3
    # 按 real_path 排序：Alpha < Alpha/Sub < Beta
    assert [n.id for n in all_nodes] == ["root1", "child", "root2"]


def test_list_all_empty(db_connection: sqlite3.Connection) -> None:
    """空表返回空列表。"""
    repo = FolderNodeRepository(db_connection)
    assert repo.list_all() == []


def test_get_by_path_key(db_connection: sqlite3.Connection) -> None:
    """get_by_path_key 按 path_key 查询。"""
    repo = FolderNodeRepository(db_connection)
    repo.create(_make_node(node_id="root1", path_key="d:/alpha"))
    repo.create(
        _make_node(
            node_id="child",
            real_path="D:/Alpha/护甲",
            path_key="d:/alpha/护甲",
            parent_id="root1",
            is_managed_root=False,
        )
    )

    # 中文 path_key
    found = repo.get_by_path_key("d:/alpha/护甲")
    assert found is not None
    assert found.id == "child"
    assert found.real_path == "D:/Alpha/护甲"

    # 不存在
    assert repo.get_by_path_key("d:/nonexistent") is None


def test_count_children(db_connection: sqlite3.Connection) -> None:
    """count_children 返回直接子目录数量。"""
    repo = FolderNodeRepository(db_connection)
    root = _make_node(node_id="root", path_key="d:/mods")
    repo.create(root)
    repo.create(
        _make_node(
            node_id="c1",
            real_path="D:/Mods/A",
            path_key="d:/mods/a",
            parent_id="root",
            is_managed_root=False,
        )
    )
    repo.create(
        _make_node(
            node_id="c2",
            real_path="D:/Mods/B",
            path_key="d:/mods/b",
            parent_id="root",
            is_managed_root=False,
        )
    )
    # 孙子节点不计入 root 的子目录数
    repo.create(
        _make_node(
            node_id="g1",
            real_path="D:/Mods/A/Sub",
            path_key="d:/mods/a/sub",
            parent_id="c1",
            is_managed_root=False,
        )
    )

    assert repo.count_children("root") == 2
    assert repo.count_children("c1") == 1
    assert repo.count_children("c2") == 0
    assert repo.count_children("nonexistent") == 0


def test_chinese_real_path_roundtrip(db_connection: sqlite3.Connection) -> None:
    repo = FolderNodeRepository(db_connection)
    node = FolderNode(
        id="cn-node",
        real_path="D:/Mods/护甲",
        path_key="d:/mods/护甲",
        display_name="护甲目录",
        is_managed_root=True,
        created_at="2026-07-07T00:00:00Z",
        updated_at="2026-07-07T00:00:00Z",
    )
    repo.create(node)
    fetched = repo.get_by_id("cn-node")
    assert fetched is not None
    assert fetched.real_path == "D:/Mods/护甲"
    assert fetched.display_name == "护甲目录"
