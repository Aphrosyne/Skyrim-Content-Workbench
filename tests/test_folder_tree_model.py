"""FolderTreeModel 测试。

覆盖：
- 节点层级正确；
- 父子关系正确；
- 展开/索引访问稳定；
- 无数据、错误数据不崩溃；
- 刷新后状态正确。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.folder_tree_model import FolderTreeModel  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from infrastructure.file_scanner import FileScanner, persist_scan_result  # noqa: E402
from infrastructure.repositories.file_asset import FileAssetRepository  # noqa: E402
from infrastructure.repositories.folder_node import FolderNodeRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def _make_tree_service(db_connection: sqlite3.Connection) -> FolderTreeService:
    return FolderTreeService(
        ManagedRootRepository(db_connection), FolderNodeRepository(db_connection)
    )


def _scan(db_connection: sqlite3.Connection, root_path: Path) -> None:
    scanner = FileScanner()
    result = scanner.scan(root_path)
    persist_scan_result(
        result,
        FolderNodeRepository(db_connection),
        FileAssetRepository(db_connection),
    )
    db_connection.commit()


def test_empty_model(db_connection: sqlite3.Connection, qapp: QApplication) -> None:
    """无数据时 model 不崩溃，rowCount 为 0。"""
    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    assert model.root_node_count() == 0
    assert model.rowCount() == 0
    # 无效 index
    assert not model.index(0, 0).isValid()


def test_top_level_nodes(
    db_connection: sqlite3.Connection, qapp: QApplication, tmp_path: Path
) -> None:
    """顶层节点正确展示。"""
    managed_service = ManagedRootService(ManagedRootRepository(db_connection))
    root_a = tmp_path / "Alpha"
    root_a.mkdir()
    root_b = tmp_path / "Beta"
    root_b.mkdir()
    managed_service.add_root(root_a)
    managed_service.add_root(root_b)

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    assert model.root_node_count() == 2

    # 按 real_path 排序：Alpha < Beta
    idx_a = model.index(0, 0)
    idx_b = model.index(1, 0)
    assert idx_a.isValid()
    assert idx_b.isValid()
    assert model.data(idx_a, Qt.DisplayRole) == "Alpha（未扫描）"
    assert model.data(idx_b, Qt.DisplayRole) == "Beta（未扫描）"
    assert model.data(idx_a, Qt.ToolTipRole) == str(root_a)


def test_children_loaded_on_fetch(
    db_connection: sqlite3.Connection, qapp: QApplication, sample_mod_tree: Path
) -> None:
    """子节点在 rowCount/fetchMore 时惰性加载。"""
    managed_service = ManagedRootService(ManagedRootRepository(db_connection))
    managed_service.add_root(sample_mod_tree)
    _scan(db_connection, sample_mod_tree)

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    assert model.root_node_count() == 1

    root_idx = model.index(0, 0)
    assert root_idx.isValid()
    # 初始未加载，canFetchMore 为 True
    assert model.canFetchMore(root_idx) is True
    # 触发加载
    model.fetchMore(root_idx)
    assert model.rowCount(root_idx) == 3  # 护甲、Weapons、空目录

    # 第一个子节点（按 real_path 排序）
    child_idx = model.index(0, 0, root_idx)
    assert child_idx.isValid()
    # sample_mod_tree 子目录按 real_path 排序：Weapons < 护甲 < 空目录
    display = model.data(child_idx, Qt.DisplayRole)
    assert display in ("Weapons", "护甲", "空目录")


def test_parent_relationship(
    db_connection: sqlite3.Connection, qapp: QApplication, sample_mod_tree: Path
) -> None:
    """父子关系：子节点的 parent() 返回根 index。"""
    managed_service = ManagedRootService(ManagedRootRepository(db_connection))
    managed_service.add_root(sample_mod_tree)
    _scan(db_connection, sample_mod_tree)

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)

    child_idx = model.index(0, 0, root_idx)
    parent_idx = model.parent(child_idx)
    assert parent_idx.isValid()
    assert parent_idx == root_idx

    # 根节点的 parent 无效
    assert not model.parent(root_idx).isValid()


def test_deep_hierarchy_access(
    db_connection: sqlite3.Connection, qapp: QApplication, tmp_path: Path
) -> None:
    """深层目录可通过 index 链访问。"""
    managed_service = ManagedRootService(ManagedRootRepository(db_connection))
    deep = tmp_path / "Root" / "L1" / "L2"
    deep.mkdir(parents=True)
    root = tmp_path / "Root"
    managed_service.add_root(root)
    _scan(db_connection, root)

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)

    l1_idx = model.index(0, 0, root_idx)
    assert l1_idx.isValid()
    model.fetchMore(l1_idx)
    l2_idx = model.index(0, 0, l1_idx)
    assert l2_idx.isValid()
    assert model.data(l2_idx, Qt.DisplayRole) == "L2"


def test_node_at_returns_treenode(
    db_connection: sqlite3.Connection, qapp: QApplication, sample_mod_tree: Path
) -> None:
    """node_at 返回 TreeNode 对象。"""
    managed_service = ManagedRootService(ManagedRootRepository(db_connection))
    managed_service.add_root(sample_mod_tree)
    _scan(db_connection, sample_mod_tree)

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    root_idx = model.index(0, 0)
    node = model.node_at(root_idx)
    assert node is not None
    assert node.display_name == sample_mod_tree.name
    assert node.category == "managed_root"
    assert node.is_managed_root is True


def test_node_id_at(db_connection: sqlite3.Connection, qapp: QApplication, tmp_path: Path) -> None:
    """node_id_at 返回 node_id 字符串。"""
    managed_service = ManagedRootService(ManagedRootRepository(db_connection))
    mods = tmp_path / "Mods"
    mods.mkdir()
    managed_service.add_root(mods)

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    root_idx = model.index(0, 0)
    node_id = model.node_id_at(root_idx)
    assert node_id is not None
    assert node_id.startswith("mr:")


def test_refresh_resets_model(
    db_connection: sqlite3.Connection, qapp: QApplication, tmp_path: Path
) -> None:
    """refresh 后顶层节点重新加载。"""
    managed_service = ManagedRootService(ManagedRootRepository(db_connection))
    tree_service = _make_tree_service(db_connection)
    model = FolderTreeModel(tree_service)
    model.refresh()
    assert model.root_node_count() == 0

    # 添加根目录后 refresh
    mods = tmp_path / "Mods"
    mods.mkdir()
    managed_service.add_root(mods)
    model.refresh()
    assert model.root_node_count() == 1


def test_invalid_index_returns_none(db_connection: sqlite3.Connection, qapp: QApplication) -> None:
    """无效 index 的 data/node_at 返回 None。"""
    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    from PySide6.QtCore import QModelIndex

    invalid = QModelIndex()
    assert model.data(invalid, Qt.DisplayRole) is None
    assert model.node_at(invalid) is None
    assert model.node_id_at(invalid) is None


def test_chinese_display_name(
    db_connection: sqlite3.Connection, qapp: QApplication, sample_mod_tree: Path
) -> None:
    """中文目录名正确展示。"""
    managed_service = ManagedRootService(ManagedRootRepository(db_connection))
    managed_service.add_root(sample_mod_tree)
    _scan(db_connection, sample_mod_tree)

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)

    # 收集所有子节点 display name
    names = []
    for i in range(model.rowCount(root_idx)):
        child_idx = model.index(i, 0, root_idx)
        names.append(model.data(child_idx, Qt.DisplayRole))
    assert "护甲" in names
    assert "空目录" in names
