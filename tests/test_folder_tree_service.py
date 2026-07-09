"""FolderTreeService 测试。

覆盖：
- 给定 ManagedRoot，获得对应 FolderNode 根与子树；
- 中文目录名/路径；
- 空目录；
- 多根目录；
- 已配置但未扫描的根目录；
- 重叠根目录去重后的可预期行为。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from application.folder_tree_service import FolderTreeService, TreeNode
from application.managed_root_service import ManagedRootService
from infrastructure.file_scanner import FileScanner, persist_scan_result
from infrastructure.repositories.file_asset import FileAssetRepository
from infrastructure.repositories.folder_node import FolderNodeRepository
from infrastructure.repositories.managed_root import ManagedRootRepository


def _make_services(
    db_connection: sqlite3.Connection,
) -> tuple[ManagedRootService, FolderTreeService]:
    """构造 ManagedRootService + FolderTreeService。"""
    managed_repo = ManagedRootRepository(db_connection)
    folder_repo = FolderNodeRepository(db_connection)
    return (
        ManagedRootService(managed_repo),
        FolderTreeService(managed_repo, folder_repo),
    )


def _scan_and_persist(db_connection: sqlite3.Connection, root_path: Path) -> None:
    """扫描并持久化（复用 FileScanner + persist_scan_result）。"""
    scanner = FileScanner()
    result = scanner.scan(root_path)
    persist_scan_result(
        result,
        FolderNodeRepository(db_connection),
        FileAssetRepository(db_connection),
    )
    db_connection.commit()


def test_list_root_nodes_empty(db_connection: sqlite3.Connection) -> None:
    """无任何配置时返回空列表。"""
    _, tree_service = _make_services(db_connection)
    assert tree_service.list_root_nodes() == []


def test_unscanned_root_shows_as_unscanned(
    db_connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """已配置但未扫描的根目录标记为 unscanned_root。"""
    managed_service, tree_service = _make_services(db_connection)
    mods = tmp_path / "我的模组"
    mods.mkdir()
    managed_service.add_root(mods)

    nodes = tree_service.list_root_nodes()
    assert len(nodes) == 1
    assert nodes[0].category == "unscanned_root"
    assert nodes[0].is_managed_root is True
    assert nodes[0].folder_node_id is None
    assert nodes[0].managed_root_id is not None
    assert nodes[0].display_name == "我的模组"
    assert nodes[0].real_path == str(mods)

    # unscanned_root 无子节点
    assert tree_service.list_children(nodes[0].node_id) == []
    assert tree_service.count_children(nodes[0].node_id) == 0
    assert tree_service.has_scan_data(nodes[0].managed_root_id) is False


def test_scanned_root_shows_as_managed_root(
    db_connection: sqlite3.Connection, sample_mod_tree: Path
) -> None:
    """已扫描的根目录标记为 managed_root，关联 FolderNode。"""
    managed_service, tree_service = _make_services(db_connection)
    managed_service.add_root(sample_mod_tree)
    _scan_and_persist(db_connection, sample_mod_tree)

    nodes = tree_service.list_root_nodes()
    assert len(nodes) == 1
    assert nodes[0].category == "managed_root"
    assert nodes[0].folder_node_id is not None
    assert nodes[0].is_managed_root is True
    assert tree_service.has_scan_data(nodes[0].managed_root_id) is True


def test_chinese_directory_names(db_connection: sqlite3.Connection, sample_mod_tree: Path) -> None:
    """中文目录名与路径正确展示。"""
    managed_service, tree_service = _make_services(db_connection)
    managed_service.add_root(sample_mod_tree)
    _scan_and_persist(db_connection, sample_mod_tree)

    root_node = tree_service.list_root_nodes()[0]
    children = tree_service.list_children(root_node.node_id)
    display_names = {c.display_name for c in children}
    # sample_mod_tree 含 "护甲"、"Weapons"、"空目录"
    assert "护甲" in display_names
    assert "Weapons" in display_names
    assert "空目录" in display_names


def test_empty_directory_appears_in_tree(
    db_connection: sqlite3.Connection, sample_mod_tree: Path
) -> None:
    """空目录作为子节点出现，且其子目录数为 0。"""
    managed_service, tree_service = _make_services(db_connection)
    managed_service.add_root(sample_mod_tree)
    _scan_and_persist(db_connection, sample_mod_tree)

    root_node = tree_service.list_root_nodes()[0]
    children = tree_service.list_children(root_node.node_id)
    empty_node = next(c for c in children if c.display_name == "空目录")
    assert empty_node is not None
    assert tree_service.list_children(empty_node.node_id) == []
    assert tree_service.count_children(empty_node.node_id) == 0


def test_multi_level_hierarchy(db_connection: sqlite3.Connection, tmp_path: Path) -> None:
    """多级目录父子关系正确。"""
    managed_service, tree_service = _make_services(db_connection)
    # 构造深层目录
    deep = tmp_path / "Root" / "Level1" / "Level2" / "Level3"
    deep.mkdir(parents=True)
    root = tmp_path / "Root"
    managed_service.add_root(root)
    _scan_and_persist(db_connection, root)

    top = tree_service.list_root_nodes()[0]
    assert top.display_name == "Root"

    level1 = tree_service.list_children(top.node_id)
    assert len(level1) == 1
    assert level1[0].display_name == "Level1"

    level2 = tree_service.list_children(level1[0].node_id)
    assert len(level2) == 1
    assert level2[0].display_name == "Level2"

    level3 = tree_service.list_children(level2[0].node_id)
    assert len(level3) == 1
    assert level3[0].display_name == "Level3"

    # parent_id 链正确
    assert level1[0].parent_id == top.node_id
    assert level2[0].parent_id == level1[0].node_id
    assert level3[0].parent_id == level2[0].node_id


def test_multiple_roots(db_connection: sqlite3.Connection, tmp_path: Path) -> None:
    """多个根目录都作为顶层节点出现。"""
    managed_service, tree_service = _make_services(db_connection)
    root_a = tmp_path / "Alpha"
    root_a.mkdir()
    (root_a / "sub_a").mkdir()
    root_b = tmp_path / "Beta"
    root_b.mkdir()
    (root_b / "sub_b").mkdir()

    managed_service.add_root(root_a)
    managed_service.add_root(root_b)
    _scan_and_persist(db_connection, root_a)
    _scan_and_persist(db_connection, root_b)

    nodes = tree_service.list_root_nodes()
    assert len(nodes) == 2
    # 按 real_path 排序
    assert nodes[0].display_name == "Alpha"
    assert nodes[1].display_name == "Beta"

    # 各自子节点正确
    children_a = tree_service.list_children(nodes[0].node_id)
    assert {c.display_name for c in children_a} == {"sub_a"}
    children_b = tree_service.list_children(nodes[1].node_id)
    assert {c.display_name for c in children_b} == {"sub_b"}


def test_rescan_does_not_duplicate_tree(
    db_connection: sqlite3.Connection, sample_mod_tree: Path
) -> None:
    """重复扫描不产生重复树节点（path_key 唯一约束 + skip 逻辑）。"""
    managed_service, tree_service = _make_services(db_connection)
    managed_service.add_root(sample_mod_tree)
    _scan_and_persist(db_connection, sample_mod_tree)
    _scan_and_persist(db_connection, sample_mod_tree)  # 再次扫描

    root_node = tree_service.list_root_nodes()[0]
    children = tree_service.list_children(root_node.node_id)
    # 仍为 3 个子目录，无重复
    assert len(children) == 3


def test_overlapping_roots_no_duplicate_children(
    db_connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """重叠根目录：父根已扫描后，子根作为独立顶层节点但不重复展示子目录。

    场景：root=/Parent（含 /Parent/Child），root2=/Parent/Child。
    两个 ManagedRoot 配置都作为顶层节点。
    /Parent/Child 在第一次扫描时已作为 Parent 的子节点持久化；
    第二次扫描 /Parent/Child 时，其 path_key 已存在，FolderNode 被跳过，
    但 is_managed_root 不会被设置（path_key 冲突跳过）。
    因此 root2 在树中显示为 unscanned_root（无关联 FolderNode）。
    这是当前可预期的行为：重叠根目录不强制提升为独立 managed_root FolderNode。
    """
    managed_service, tree_service = _make_services(db_connection)
    parent = tmp_path / "Parent"
    parent.mkdir()
    (parent / "Child").mkdir()
    child = parent / "Child"

    managed_service.add_root(parent)
    managed_service.add_root(child)
    _scan_and_persist(db_connection, parent)
    # 扫描 child：path_key 已存在（作为 Parent 子节点），跳过
    _scan_and_persist(db_connection, child)

    nodes = tree_service.list_root_nodes()
    assert len(nodes) == 2
    # parent 关联到 FolderNode（managed_root）
    parent_node = next(n for n in nodes if n.display_name == "Parent")
    assert parent_node.category == "managed_root"
    # child 因 path_key 冲突未持久化为 managed_root FolderNode，显示为 unscanned
    child_node = next(n for n in nodes if n.display_name == "Child")
    assert child_node.category == "unscanned_root"


def test_get_node_returns_none_for_invalid_id(
    db_connection: sqlite3.Connection,
) -> None:
    """非法 node_id 格式返回 None。"""
    _, tree_service = _make_services(db_connection)
    assert tree_service.get_node("invalid") is None
    assert tree_service.get_node("mr:nonexistent") is None
    assert tree_service.get_node("fn:nonexistent") is None


def test_get_node_for_managed_root(
    db_connection: sqlite3.Connection, sample_mod_tree: Path
) -> None:
    """get_node 返回 managed_root 节点详情。"""
    managed_service, tree_service = _make_services(db_connection)
    managed_service.add_root(sample_mod_tree)
    _scan_and_persist(db_connection, sample_mod_tree)

    top = tree_service.list_root_nodes()[0]
    node = tree_service.get_node(top.node_id)
    assert node is not None
    assert node.category == "managed_root"
    assert node.display_name == sample_mod_tree.name


def test_get_node_for_folder(db_connection: sqlite3.Connection, sample_mod_tree: Path) -> None:
    """get_node 返回 folder 节点详情。"""
    managed_service, tree_service = _make_services(db_connection)
    managed_service.add_root(sample_mod_tree)
    _scan_and_persist(db_connection, sample_mod_tree)

    top = tree_service.list_root_nodes()[0]
    children = tree_service.list_children(top.node_id)
    armor = next(c for c in children if c.display_name == "护甲")

    node = tree_service.get_node(armor.node_id)
    assert node is not None
    assert node.category == "folder"
    assert node.display_name == "护甲"
    assert "护甲" in node.real_path


def test_list_children_invalid_node_id_returns_empty(
    db_connection: sqlite3.Connection,
) -> None:
    """非法 node_id 返回空列表，不抛异常。"""
    _, tree_service = _make_services(db_connection)
    assert tree_service.list_children("invalid") == []
    assert tree_service.list_children("mr:nonexistent") == []
    assert tree_service.list_children("fn:nonexistent") == []


def test_count_children_invalid_node_id_returns_zero(
    db_connection: sqlite3.Connection,
) -> None:
    """非法 node_id 返回 0。"""
    _, tree_service = _make_services(db_connection)
    assert tree_service.count_children("invalid") == 0
    assert tree_service.count_children("mr:nonexistent") == 0


def test_treenode_validates_category() -> None:
    """TreeNode 拒绝非法 category。"""
    with pytest.raises(ValueError):
        TreeNode(
            node_id="x",
            display_name="x",
            real_path="x",
            category="invalid",
            is_managed_root=False,
        )


def test_persisted_tree_loadable_after_reconnect(db_path: Path, sample_mod_tree: Path) -> None:
    """扫描结果持久化后，重新连接数据库仍能加载完整树。"""
    from infrastructure.db import get_connection, init_db

    init_db(db_path)
    conn1 = get_connection(db_path)
    conn1.row_factory = sqlite3.Row
    try:
        managed_service, tree_service = _make_services(conn1)
        managed_service.add_root(sample_mod_tree)
        _scan_and_persist(conn1, sample_mod_tree)
    finally:
        conn1.close()

    # 重新连接
    conn2 = get_connection(db_path)
    conn2.row_factory = sqlite3.Row
    try:
        _, tree_service2 = _make_services(conn2)
        nodes = tree_service2.list_root_nodes()
        assert len(nodes) == 1
        assert nodes[0].category == "managed_root"
        children = tree_service2.list_children(nodes[0].node_id)
        assert len(children) == 3
        assert {c.display_name for c in children} == {"护甲", "Weapons", "空目录"}
    finally:
        conn2.close()
