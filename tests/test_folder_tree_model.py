"""FolderTreeModel 测试（重构版）。

覆盖：
- 节点层级正确；
- 父子关系正确；
- 展开/索引访问稳定；
- 无数据、错误数据不崩溃；
- 刷新后状态正确；
- 旧版缺陷回归测试：
  - fetchMore 连接真实 View 不递归崩溃；
  - 空子节点不发 rowsInserted 信号；
  - 无效 QModelIndex 不触发 TypeError；
  - 深层目录逐级展开不闪退（C++ persistent index 一致性）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QModelIndex, Qt  # noqa: E402
from PySide6.QtTest import QSignalSpy  # noqa: E402
from PySide6.QtWidgets import QApplication, QTreeView  # noqa: E402

from app.folder_tree_model import FolderTreeModel  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.folder_cache import FolderCacheRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def _make_managed_root_service(
    db_connection: sqlite3.Connection,
) -> ManagedRootService:
    counter = {"n": 0}

    def fake_uuid() -> str:
        counter["n"] += 1
        return f"root-{counter['n']}"

    return ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-12T00:00:00Z",
        uuid_provider=fake_uuid,
    )


def _make_scan_service(db_connection: sqlite3.Connection) -> ScanService:
    counter = {"n": 0}

    def fake_uuid() -> str:
        counter["n"] += 1
        return f"fc-{counter['n']}"

    return ScanService(
        managed_root_repo=ManagedRootRepository(db_connection),
        folder_cache_repo=FolderCacheRepository(db_connection),
        content_unit_repo=ContentUnitRepository(db_connection),
        now_provider=lambda: "2026-07-12T00:00:00Z",
        uuid_provider=fake_uuid,
    )


def _make_tree_service(db_connection: sqlite3.Connection) -> FolderTreeService:
    return FolderTreeService(
        ManagedRootRepository(db_connection),
        FolderCacheRepository(db_connection),
    )


@pytest.fixture
def mod_tree(tmp_path: Path) -> Path:
    """样本目录树：含两个内容单元候选 + 一个普通文件夹 + 空目录。"""
    root = tmp_path / "mods"
    root.mkdir()

    armor = root / "护甲"
    armor.mkdir()
    (armor / "寒霜之心.7z").write_bytes(b"\x00" * 100)

    weapons = root / "Weapons"
    weapons.mkdir()
    (weapons / "DragonSword.rar").write_bytes(b"\x00" * 80)

    normal = root / "普通文件夹"
    normal.mkdir()
    (normal / "readme.txt").write_bytes(b"data")

    empty = root / "空目录"
    empty.mkdir()

    return root


# --- 基础测试 ---


def test_empty_model(db_connection: sqlite3.Connection, qapp: QApplication) -> None:
    """无数据时 model 不崩溃，rowCount 为 0。"""
    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    assert model.root_node_count() == 0
    assert model.rowCount() == 0
    assert not model.index(0, 0).isValid()


def test_top_level_nodes_unscanned(
    db_connection: sqlite3.Connection, qapp: QApplication, tmp_path: Path
) -> None:
    """未扫描的顶层节点显示为「（未扫描）」。"""
    managed_service = _make_managed_root_service(db_connection)
    root_a = tmp_path / "Alpha"
    root_a.mkdir()
    root_b = tmp_path / "Beta"
    root_b.mkdir()
    managed_service.add_root(root_a)
    managed_service.add_root(root_b)

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    assert model.root_node_count() == 2

    idx_a = model.index(0, 0)
    idx_b = model.index(1, 0)
    assert idx_a.isValid()
    assert idx_b.isValid()
    assert model.data(idx_a, Qt.DisplayRole) == "Alpha（未扫描）"
    assert model.data(idx_b, Qt.DisplayRole) == "Beta（未扫描）"
    assert model.data(idx_a, Qt.ToolTipRole) == str(root_a)


def test_fetch_more_loads_children(
    db_connection: sqlite3.Connection, qapp: QApplication, mod_tree: Path
) -> None:
    """子节点在 fetchMore 时惰性加载。"""
    managed_service = _make_managed_root_service(db_connection)
    scan_service = _make_scan_service(db_connection)
    root = managed_service.add_root(mod_tree)
    scan_service.scan_root(root.id, incremental=False)
    db_connection.commit()

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    assert model.root_node_count() == 1

    root_idx = model.index(0, 0)
    assert root_idx.isValid()
    assert model.canFetchMore(root_idx) is True
    assert model.rowCount(root_idx) == 0
    model.fetchMore(root_idx)
    assert model.rowCount(root_idx) == 4
    assert model.canFetchMore(root_idx) is False

    names = []
    for i in range(model.rowCount(root_idx)):
        child_idx = model.index(i, 0, root_idx)
        names.append(model.data(child_idx, Qt.DisplayRole))
    assert "护甲" in names
    assert "Weapons" in names
    assert "普通文件夹" in names
    assert "空目录" in names


def test_parent_relationship(
    db_connection: sqlite3.Connection, qapp: QApplication, mod_tree: Path
) -> None:
    """父子关系：子节点的 parent() 返回根 index 的逻辑等价节点。"""
    managed_service = _make_managed_root_service(db_connection)
    scan_service = _make_scan_service(db_connection)
    root = managed_service.add_root(mod_tree)
    scan_service.scan_root(root.id, incremental=False)
    db_connection.commit()

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)

    child_idx = model.index(0, 0, root_idx)
    parent_idx = model.parent(child_idx)
    assert parent_idx.isValid()
    # QModelIndex 的 __eq__ 在 PySide6 中基于内部指针地址，
    # 通过 node_id 比较逻辑等价性。
    assert model.node_id_at(parent_idx) == model.node_id_at(root_idx)
    # 根节点的 parent 无效
    assert not model.parent(root_idx).isValid()


def test_deep_hierarchy_access(
    db_connection: sqlite3.Connection, qapp: QApplication, tmp_path: Path
) -> None:
    """深层目录可通过 index 链访问。"""
    managed_service = _make_managed_root_service(db_connection)
    scan_service = _make_scan_service(db_connection)
    deep = tmp_path / "Root" / "L1" / "L2"
    deep.mkdir(parents=True)
    root_dir = tmp_path / "Root"
    root = managed_service.add_root(root_dir)
    scan_service.scan_root(root.id, incremental=False)
    db_connection.commit()

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
    db_connection: sqlite3.Connection, qapp: QApplication, mod_tree: Path
) -> None:
    """node_at 返回 TreeNode 对象。"""
    managed_service = _make_managed_root_service(db_connection)
    scan_service = _make_scan_service(db_connection)
    root = managed_service.add_root(mod_tree)
    scan_service.scan_root(root.id, incremental=False)
    db_connection.commit()

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    root_idx = model.index(0, 0)
    node = model.node_at(root_idx)
    assert node is not None
    assert node.display_name == mod_tree.name
    assert node.category == "managed_root"
    assert node.is_managed_root is True


def test_node_id_at(db_connection: sqlite3.Connection, qapp: QApplication, tmp_path: Path) -> None:
    """node_id_at 返回 node_id 字符串。"""
    managed_service = _make_managed_root_service(db_connection)
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
    managed_service = _make_managed_root_service(db_connection)
    tree_service = _make_tree_service(db_connection)
    model = FolderTreeModel(tree_service)
    model.refresh()
    assert model.root_node_count() == 0

    mods = tmp_path / "Mods"
    mods.mkdir()
    managed_service.add_root(mods)
    model.refresh()
    assert model.root_node_count() == 1


def test_invalid_index_returns_none(db_connection: sqlite3.Connection, qapp: QApplication) -> None:
    """无效 index 的 data/node_at 返回 None。"""
    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    invalid = QModelIndex()
    assert model.data(invalid, Qt.DisplayRole) is None
    assert model.node_at(invalid) is None
    assert model.node_id_at(invalid) is None


def test_chinese_display_name(
    db_connection: sqlite3.Connection, qapp: QApplication, mod_tree: Path
) -> None:
    """中文目录名正确展示。"""
    managed_service = _make_managed_root_service(db_connection)
    scan_service = _make_scan_service(db_connection)
    root = managed_service.add_root(mod_tree)
    scan_service.scan_root(root.id, incremental=False)
    db_connection.commit()

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)

    names = []
    for i in range(model.rowCount(root_idx)):
        child_idx = model.index(i, 0, root_idx)
        names.append(model.data(child_idx, Qt.DisplayRole))
    assert "护甲" in names
    assert "空目录" in names


# --- hasChildren 测试 ---


def test_has_children_unscanned_root_returns_true(
    db_connection: sqlite3.Connection, qapp: QApplication, tmp_path: Path
) -> None:
    """hasChildren 对未扫描根节点返回 True，使 View 显示展开箭头。"""
    managed_service = _make_managed_root_service(db_connection)
    mods = tmp_path / "Mods"
    mods.mkdir()
    managed_service.add_root(mods)

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    root_idx = model.index(0, 0)
    assert root_idx.isValid()
    assert model.hasChildren(root_idx) is True


def test_has_children_scanned_root_returns_true_before_fetch(
    db_connection: sqlite3.Connection, qapp: QApplication, mod_tree: Path
) -> None:
    """hasChildren 对已扫描但未 fetchMore 的节点返回 True。"""
    managed_service = _make_managed_root_service(db_connection)
    scan_service = _make_scan_service(db_connection)
    root = managed_service.add_root(mod_tree)
    scan_service.scan_root(root.id, incremental=False)
    db_connection.commit()

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    root_idx = model.index(0, 0)
    assert root_idx.isValid()
    assert model.hasChildren(root_idx) is True


def test_has_children_leaf_node_returns_false_after_fetch(
    db_connection: sqlite3.Connection, qapp: QApplication, mod_tree: Path
) -> None:
    """hasChildren 对已加载且无子节点的叶子节点返回 False。"""
    managed_service = _make_managed_root_service(db_connection)
    scan_service = _make_scan_service(db_connection)
    root = managed_service.add_root(mod_tree)
    scan_service.scan_root(root.id, incremental=False)
    db_connection.commit()

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)

    # 找一个叶子节点（如护甲，含 .7z，扫描时不递归其子目录）
    for i in range(model.rowCount(root_idx)):
        child_idx = model.index(i, 0, root_idx)
        if model.data(child_idx, Qt.DisplayRole) == "护甲":
            model.fetchMore(child_idx)
            assert model.hasChildren(child_idx) is False
            return
    pytest.fail("未找到护甲节点")


def test_has_children_loaded_parent_with_children_returns_true(
    db_connection: sqlite3.Connection, qapp: QApplication, mod_tree: Path
) -> None:
    """hasChildren 对已加载且有子节点的节点返回 True。"""
    managed_service = _make_managed_root_service(db_connection)
    scan_service = _make_scan_service(db_connection)
    root = managed_service.add_root(mod_tree)
    scan_service.scan_root(root.id, incremental=False)
    db_connection.commit()

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)
    assert model.hasChildren(root_idx) is True


def test_has_children_empty_model_returns_false(
    db_connection: sqlite3.Connection, qapp: QApplication
) -> None:
    """hasChildren 对空 model 的根返回 False。"""
    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    assert model.hasChildren() is False


# --- 旧版缺陷回归测试 ---


def test_fetch_does_not_recurse_when_connected_to_view(
    db_connection: sqlite3.Connection, qapp: QApplication, mod_tree: Path
) -> None:
    """model 连接真实 QTreeView 后加载子节点不触发无限递归。"""
    managed_service = _make_managed_root_service(db_connection)
    scan_service = _make_scan_service(db_connection)
    root = managed_service.add_root(mod_tree)
    scan_service.scan_root(root.id, incremental=False)
    db_connection.commit()

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()

    view = QTreeView()
    view.setModel(model)

    root_idx = model.index(0, 0)
    assert root_idx.isValid()
    model.fetchMore(root_idx)
    qapp.processEvents()

    assert model.rowCount(root_idx) == 4
    view.deleteLater()
    qapp.processEvents()


def test_fetch_empty_children_does_not_emit_rows_inserted(
    db_connection: sqlite3.Connection, qapp: QApplication, tmp_path: Path
) -> None:
    """空子节点不发 rowsInserted 信号。"""
    managed_service = _make_managed_root_service(db_connection)
    scan_service = _make_scan_service(db_connection)
    empty_sub = tmp_path / "Root" / "EmptySub"
    empty_sub.mkdir(parents=True)
    root_dir = tmp_path / "Root"
    root = managed_service.add_root(root_dir)
    scan_service.scan_root(root.id, incremental=False)
    db_connection.commit()

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)
    assert model.rowCount(root_idx) == 1

    child_idx = model.index(0, 0, root_idx)
    assert child_idx.isValid()

    spy = QSignalSpy(model.rowsInserted)
    model.fetchMore(child_idx)
    qapp.processEvents()

    assert spy.count() == 0
    assert model.rowCount(child_idx) == 0


def test_row_count_handles_invalid_index_without_crash(
    db_connection: sqlite3.Connection, qapp: QApplication, mod_tree: Path
) -> None:
    """rowCount 对无效 QModelIndex 不崩溃，返回根节点数。"""
    managed_service = _make_managed_root_service(db_connection)
    scan_service = _make_scan_service(db_connection)
    root = managed_service.add_root(mod_tree)
    scan_service.scan_root(root.id, incremental=False)
    db_connection.commit()

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()

    invalid = QModelIndex()
    assert model.rowCount(invalid) == 1


def test_index_handles_invalid_parent_without_crash(
    db_connection: sqlite3.Connection, qapp: QApplication, mod_tree: Path
) -> None:
    """index 方法对无效 parent 不崩溃。"""
    managed_service = _make_managed_root_service(db_connection)
    scan_service = _make_scan_service(db_connection)
    root = managed_service.add_root(mod_tree)
    scan_service.scan_root(root.id, incremental=False)
    db_connection.commit()

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()

    invalid_parent = QModelIndex()
    result = model.index(0, 0, invalid_parent)
    assert result.isValid()
    assert model.data(result, Qt.DisplayRole) == mod_tree.name
    assert not model.index(99, 0, invalid_parent).isValid()


def test_has_children_handles_invalid_index_without_crash(
    db_connection: sqlite3.Connection, qapp: QApplication, mod_tree: Path
) -> None:
    """hasChildren 对无效 QModelIndex 不崩溃。"""
    managed_service = _make_managed_root_service(db_connection)
    scan_service = _make_scan_service(db_connection)
    root = managed_service.add_root(mod_tree)
    scan_service.scan_root(root.id, incremental=False)
    db_connection.commit()

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()

    invalid = QModelIndex()
    assert model.hasChildren(invalid) is True


def test_deep_expansion_does_not_crash(
    db_connection: sqlite3.Connection, qapp: QApplication, tmp_path: Path
) -> None:
    """深层目录逐级展开不闪退。

    核心回归测试：模拟用户逐级展开目录树，连接真实 QTreeView，验证
    Qt C++ 层 persistent index 机制在多层 fetchMore 下不崩溃。
    旧实现因 parent() 反查 + 线性扫描 + index 对象身份不一致导致 segfault。
    重构后通过 _Node 对象引用 + row_in_parent 缓存实现 O(1) parent()。
    """
    managed_service = _make_managed_root_service(db_connection)
    scan_service = _make_scan_service(db_connection)
    # 构造 Root/L1/L2/L3
    deep = tmp_path / "Root" / "L1" / "L2" / "L3"
    deep.mkdir(parents=True)
    root_dir = tmp_path / "Root"
    root = managed_service.add_root(root_dir)
    scan_service.scan_root(root.id, incremental=False)
    db_connection.commit()

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()

    view = QTreeView()
    view.setModel(model)

    # 逐级展开（连接真实 View，触发 persistent index 机制）
    root_idx = model.index(0, 0)
    assert root_idx.isValid()
    model.fetchMore(root_idx)
    qapp.processEvents()

    l1_idx = model.index(0, 0, root_idx)
    assert l1_idx.isValid()
    model.fetchMore(l1_idx)
    qapp.processEvents()

    l2_idx = model.index(0, 0, l1_idx)
    assert l2_idx.isValid()
    model.fetchMore(l2_idx)
    qapp.processEvents()

    l3_idx = model.index(0, 0, l2_idx)
    assert l3_idx.isValid()
    assert model.data(l3_idx, Qt.DisplayRole) == "L3"

    # 查询 L3 的 parent 链，验证 _Node.parent 引用一致性
    parent_of_l3 = model.parent(l3_idx)
    assert parent_of_l3.isValid()
    assert model.node_id_at(parent_of_l3) == model.node_id_at(l2_idx)

    parent_of_l2 = model.parent(l2_idx)
    assert parent_of_l2.isValid()
    assert model.node_id_at(parent_of_l2) == model.node_id_at(l1_idx)

    parent_of_l1 = model.parent(l1_idx)
    assert parent_of_l1.isValid()
    assert model.node_id_at(parent_of_l1) == model.node_id_at(root_idx)

    parent_of_root = model.parent(root_idx)
    assert not parent_of_root.isValid()

    view.deleteLater()
    qapp.processEvents()


def test_view_loads_root_children_without_crash(
    db_connection: sqlite3.Connection, qapp: QApplication, mod_tree: Path
) -> None:
    """连接真实 QTreeView 后通过 model 接口加载根的子节点不崩溃。

    端到端验证 model 与 view 的交互稳定性。setExpanded 不会自动触发
    fetchMore，需显式调用。深层逐级展开的正确性由
    test_deep_expansion_does_not_crash 覆盖。
    """
    managed_service = _make_managed_root_service(db_connection)
    scan_service = _make_scan_service(db_connection)
    root = managed_service.add_root(mod_tree)
    scan_service.scan_root(root.id, incremental=False)
    db_connection.commit()

    model = FolderTreeModel(_make_tree_service(db_connection))
    model.refresh()

    view = QTreeView()
    view.setModel(model)

    root_idx = model.index(0, 0)
    assert root_idx.isValid()
    # 显式触发 fetchMore（模拟用户点击展开按钮）
    model.fetchMore(root_idx)
    qapp.processEvents()

    # 根节点展开后子节点应能通过 model 访问
    assert model.rowCount(root_idx) == 4

    view.deleteLater()
    qapp.processEvents()
