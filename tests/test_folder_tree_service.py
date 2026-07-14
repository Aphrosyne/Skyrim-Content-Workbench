"""FolderTreeService 测试。

覆盖：
- list_root_nodes：空数据、未扫描根、已扫描根、中文目录名、多根目录、重复扫描不重复
- list_children：空根节点、多层层级、mr:/fc: 前缀分发、无效 node_id
- get_node：managed_root / folder / 无效 ID
- count_children：直接子目录数、孙节点不计入
- has_scan_data：已扫描/未扫描
- 持久化：重新连接数据库后树可加载
- TreeNode category 校验
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from application.folder_tree_service import FolderTreeService, TreeNode
from application.managed_root_service import ManagedRootService
from application.scan_service import ScanService
from application.staging_service import StagingService
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.folder_cache import FolderCacheRepository
from infrastructure.repositories.managed_root import ManagedRootRepository
from infrastructure.repositories.staging_area import StagingAreaRepository


@pytest.fixture
def managed_root_service(db_connection: sqlite3.Connection) -> ManagedRootService:
    counter = {"n": 0}

    def fake_uuid() -> str:
        counter["n"] += 1
        return f"root-{counter['n']}"

    return ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-12T00:00:00Z",
        uuid_provider=fake_uuid,
    )


@pytest.fixture
def scan_service(db_connection: sqlite3.Connection) -> ScanService:
    counter = {"n": 0}

    def fake_uuid() -> str:
        counter["n"] += 1
        return f"uuid-{counter['n']}"

    return ScanService(
        managed_root_repo=ManagedRootRepository(db_connection),
        folder_cache_repo=FolderCacheRepository(db_connection),
        content_unit_repo=ContentUnitRepository(db_connection),
        now_provider=lambda: "2026-07-12T00:00:00Z",
        uuid_provider=fake_uuid,
    )


@pytest.fixture
def staging_service(db_connection: sqlite3.Connection) -> StagingService:
    counter = {"n": 0}

    def fake_uuid() -> str:
        counter["n"] += 1
        return f"staging-{counter['n']}"

    return StagingService(
        StagingAreaRepository(db_connection),
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=fake_uuid,
    )


@pytest.fixture
def tree_service(
    db_connection: sqlite3.Connection, staging_service: StagingService
) -> FolderTreeService:
    return FolderTreeService(
        ManagedRootRepository(db_connection),
        FolderCacheRepository(db_connection),
        staging_service=staging_service,
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


# --- list_root_nodes ---


class TestListRootNodes:
    def test_empty_data_returns_empty(self, tree_service: FolderTreeService) -> None:
        """无任何配置时返回空列表。"""
        assert tree_service.list_root_nodes() == []

    def test_unscanned_root_shows_as_unscanned(
        self,
        tree_service: FolderTreeService,
        managed_root_service: ManagedRootService,
        tmp_path: Path,
    ) -> None:
        """已配置但未扫描的根目录标记为 unscanned_root。"""
        mods = tmp_path / "我的模组"
        mods.mkdir()
        managed_root_service.add_root(mods)

        nodes = tree_service.list_root_nodes()
        assert len(nodes) == 1
        assert nodes[0].category == "unscanned_root"
        assert nodes[0].is_managed_root is True
        assert nodes[0].folder_cache_id is None
        assert nodes[0].managed_root_id is not None
        assert nodes[0].display_name == "我的模组"
        assert nodes[0].real_path == str(mods)

    def test_scanned_root_shows_as_managed_root(
        self,
        tree_service: FolderTreeService,
        managed_root_service: ManagedRootService,
        scan_service: ScanService,
        mod_tree: Path,
    ) -> None:
        """已扫描的根目录标记为 managed_root，关联 folder_cache。"""
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)

        nodes = tree_service.list_root_nodes()
        assert len(nodes) == 1
        assert nodes[0].category == "managed_root"
        assert nodes[0].folder_cache_id is not None
        assert nodes[0].is_managed_root is True
        assert tree_service.has_scan_data(nodes[0].managed_root_id) is True

    def test_chinese_directory_names(
        self,
        tree_service: FolderTreeService,
        managed_root_service: ManagedRootService,
        scan_service: ScanService,
        mod_tree: Path,
    ) -> None:
        """中文目录名与路径正确展示。"""
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)

        root_node = tree_service.list_root_nodes()[0]
        children = tree_service.list_children(root_node.node_id)
        display_names = {c.display_name for c in children}
        assert "护甲" in display_names
        assert "Weapons" in display_names
        assert "普通文件夹" in display_names
        assert "空目录" in display_names

    def test_multiple_roots(
        self,
        tree_service: FolderTreeService,
        managed_root_service: ManagedRootService,
        scan_service: ScanService,
        tmp_path: Path,
    ) -> None:
        """多个根目录都作为顶层节点出现。"""
        root_a = tmp_path / "Alpha"
        root_a.mkdir()
        (root_a / "sub_a").mkdir()
        (root_a / "sub_a" / "mod.7z").write_bytes(b"\x00")
        root_b = tmp_path / "Beta"
        root_b.mkdir()
        (root_b / "sub_b").mkdir()
        (root_b / "sub_b" / "mod.zip").write_bytes(b"\x00")

        managed_root_service.add_root(root_a)
        managed_root_service.add_root(root_b)
        root_a_obj = managed_root_service.list_roots()[0]
        root_b_obj = managed_root_service.list_roots()[1]
        scan_service.scan_root(root_a_obj.id, incremental=False)
        scan_service.scan_root(root_b_obj.id, incremental=False)

        nodes = tree_service.list_root_nodes()
        assert len(nodes) == 2
        # 按 real_path 排序
        assert nodes[0].display_name == "Alpha"
        assert nodes[1].display_name == "Beta"

        children_a = tree_service.list_children(nodes[0].node_id)
        assert {c.display_name for c in children_a} == {"sub_a"}
        children_b = tree_service.list_children(nodes[1].node_id)
        assert {c.display_name for c in children_b} == {"sub_b"}

    def test_rescan_does_not_duplicate(
        self,
        tree_service: FolderTreeService,
        managed_root_service: ManagedRootService,
        scan_service: ScanService,
        mod_tree: Path,
    ) -> None:
        """重复扫描不产生重复树节点。"""
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)
        scan_service.scan_root(root.id, incremental=False)

        root_node = tree_service.list_root_nodes()[0]
        children = tree_service.list_children(root_node.node_id)
        assert len(children) == 4  # 护甲、Weapons、普通文件夹、空目录
        # 无重复 display_name
        names = [c.display_name for c in children]
        assert len(names) == len(set(names))


# --- list_children ---


class TestListChildren:
    def test_empty_root_has_no_children(
        self,
        tree_service: FolderTreeService,
        managed_root_service: ManagedRootService,
        scan_service: ScanService,
        tmp_path: Path,
    ) -> None:
        """已扫描但无子目录的根节点返回空列表。"""
        root_dir = tmp_path / "empty_root"
        root_dir.mkdir()
        root = managed_root_service.add_root(root_dir)
        scan_service.scan_root(root.id, incremental=False)

        nodes = tree_service.list_root_nodes()
        assert len(nodes) == 1
        assert tree_service.list_children(nodes[0].node_id) == []

    def test_multi_level_hierarchy(
        self,
        tree_service: FolderTreeService,
        managed_root_service: ManagedRootService,
        scan_service: ScanService,
        tmp_path: Path,
    ) -> None:
        """多级目录父子关系正确。"""
        deep = tmp_path / "Root" / "Level1" / "Level2" / "Level3"
        deep.mkdir(parents=True)
        root_dir = tmp_path / "Root"
        root = managed_root_service.add_root(root_dir)
        scan_service.scan_root(root.id, incremental=False)

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

    def test_mr_prefix_dispatches_to_managed_root(
        self,
        tree_service: FolderTreeService,
        managed_root_service: ManagedRootService,
        scan_service: ScanService,
        mod_tree: Path,
    ) -> None:
        """mr: 前缀查询 managed_root 的 folder_cache 子节点。"""
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)

        nodes = tree_service.list_root_nodes()
        children = tree_service.list_children(nodes[0].node_id)
        # 应返回 4 个子目录
        assert len(children) == 4
        # 所有子节点应为 folder 类型
        for child in children:
            assert child.category == "folder"
            assert child.is_managed_root is False

    def test_fc_prefix_dispatches_to_folder_cache(
        self,
        tree_service: FolderTreeService,
        managed_root_service: ManagedRootService,
        scan_service: ScanService,
        mod_tree: Path,
    ) -> None:
        """fc: 前缀查询 folder_cache 的子节点。"""
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)

        root_node = tree_service.list_root_nodes()[0]
        children = tree_service.list_children(root_node.node_id)
        # 取第一个子节点，查询其子节点
        first_child = children[0]
        grandchildren = tree_service.list_children(first_child.node_id)
        # 内容单元候选（护甲、Weapons）的子目录不扫描，普通文件夹和空目录无子目录
        assert grandchildren == []

    def test_invalid_node_id_returns_empty(self, tree_service: FolderTreeService) -> None:
        """非法 node_id 返回空列表。"""
        assert tree_service.list_children("invalid") == []
        assert tree_service.list_children("mr:nonexistent") == []
        assert tree_service.list_children("fc:nonexistent") == []
        assert tree_service.list_children("") == []

    def test_unscanned_root_returns_empty(
        self,
        tree_service: FolderTreeService,
        managed_root_service: ManagedRootService,
        tmp_path: Path,
    ) -> None:
        """未扫描的 managed_root 查询子节点返回空列表。"""
        mods = tmp_path / "mods"
        mods.mkdir()
        managed_root_service.add_root(mods)

        nodes = tree_service.list_root_nodes()
        assert nodes[0].category == "unscanned_root"
        assert tree_service.list_children(nodes[0].node_id) == []


# --- get_node ---


class TestGetNode:
    def test_get_node_managed_root(
        self,
        tree_service: FolderTreeService,
        managed_root_service: ManagedRootService,
        scan_service: ScanService,
        mod_tree: Path,
    ) -> None:
        """get_node 返回 managed_root 节点详情。"""
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)

        top = tree_service.list_root_nodes()[0]
        node = tree_service.get_node(top.node_id)
        assert node is not None
        assert node.category == "managed_root"
        assert node.display_name == mod_tree.name
        assert node.is_managed_root is True

    def test_get_node_folder(
        self,
        tree_service: FolderTreeService,
        managed_root_service: ManagedRootService,
        scan_service: ScanService,
        mod_tree: Path,
    ) -> None:
        """get_node 返回 folder 节点详情。"""
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)

        top = tree_service.list_root_nodes()[0]
        children = tree_service.list_children(top.node_id)
        armor = next(c for c in children if c.display_name == "护甲")

        node = tree_service.get_node(armor.node_id)
        assert node is not None
        assert node.category == "folder"
        assert node.display_name == "护甲"
        assert "护甲" in node.real_path
        assert node.parent_id == top.node_id

    def test_get_node_invalid_id_returns_none(self, tree_service: FolderTreeService) -> None:
        """非法 node_id 返回 None。"""
        assert tree_service.get_node("invalid") is None
        assert tree_service.get_node("mr:nonexistent") is None
        assert tree_service.get_node("fc:nonexistent") is None
        assert tree_service.get_node("") is None

    def test_get_node_unscanned_root(
        self,
        tree_service: FolderTreeService,
        managed_root_service: ManagedRootService,
        tmp_path: Path,
    ) -> None:
        """get_node 返回未扫描根目录节点。"""
        mods = tmp_path / "mods"
        mods.mkdir()
        managed_root_service.add_root(mods)

        nodes = tree_service.list_root_nodes()
        node = tree_service.get_node(nodes[0].node_id)
        assert node is not None
        assert node.category == "unscanned_root"
        assert node.folder_cache_id is None


# --- count_children ---


class TestCountChildren:
    def test_count_direct_children(
        self,
        tree_service: FolderTreeService,
        managed_root_service: ManagedRootService,
        scan_service: ScanService,
        mod_tree: Path,
    ) -> None:
        """count_children 返回直接子目录数。"""
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)

        top = tree_service.list_root_nodes()[0]
        # mod_tree 有 4 个子目录：护甲、Weapons、普通文件夹、空目录
        assert tree_service.count_children(top.node_id) == 4

    def test_grandchildren_not_counted(
        self,
        tree_service: FolderTreeService,
        managed_root_service: ManagedRootService,
        scan_service: ScanService,
        tmp_path: Path,
    ) -> None:
        """count_children 不计入孙节点。"""
        # Root/sub/subsub
        deep = tmp_path / "Root" / "sub" / "subsub"
        deep.mkdir(parents=True)
        root_dir = tmp_path / "Root"
        root = managed_root_service.add_root(root_dir)
        scan_service.scan_root(root.id, incremental=False)

        top = tree_service.list_root_nodes()[0]
        assert tree_service.count_children(top.node_id) == 1  # 只有 sub

        sub = tree_service.list_children(top.node_id)[0]
        assert tree_service.count_children(sub.node_id) == 1  # 只有 subsub

    def test_count_children_invalid_id_returns_zero(self, tree_service: FolderTreeService) -> None:
        """非法 node_id 返回 0。"""
        assert tree_service.count_children("invalid") == 0
        assert tree_service.count_children("mr:nonexistent") == 0
        assert tree_service.count_children("") == 0


# --- 持久化验证 ---


def test_persisted_tree_loadable_after_reconnect(db_path: Path, mod_tree: Path) -> None:
    """扫描结果持久化后，重新连接数据库仍能加载完整树。"""
    from infrastructure.db import get_connection, init_db

    init_db(db_path)
    conn1 = get_connection(db_path)
    conn1.row_factory = sqlite3.Row
    try:
        managed_service = ManagedRootService(
            ManagedRootRepository(conn1),
            now_provider=lambda: "2026-07-12T00:00:00Z",
            uuid_provider=lambda: "root-uuid",
        )
        scan_svc = ScanService(
            managed_root_repo=ManagedRootRepository(conn1),
            folder_cache_repo=FolderCacheRepository(conn1),
            content_unit_repo=ContentUnitRepository(conn1),
            now_provider=lambda: "2026-07-12T00:00:00Z",
            uuid_provider=lambda: f"fc-{uuid.uuid4()}",
        )
        root = managed_service.add_root(mod_tree)
        scan_svc.scan_root(root.id, incremental=False)
        conn1.commit()
    finally:
        conn1.close()

    # 重新连接
    conn2 = get_connection(db_path)
    conn2.row_factory = sqlite3.Row
    try:
        tree_svc = FolderTreeService(
            ManagedRootRepository(conn2),
            FolderCacheRepository(conn2),
        )
        nodes = tree_svc.list_root_nodes()
        assert len(nodes) == 1
        assert nodes[0].category == "managed_root"
        children = tree_svc.list_children(nodes[0].node_id)
        assert len(children) == 4
        assert {c.display_name for c in children} == {"护甲", "Weapons", "普通文件夹", "空目录"}
    finally:
        conn2.close()


# --- TreeNode 校验 ---


def test_treenode_validates_category() -> None:
    """TreeNode 拒绝非法 category。"""
    with pytest.raises(ValueError):
        TreeNode(
            node_id="x",
            display_name="x",
            real_path="x",
            category="invalid",
            is_managed_root=False,
            managed_root_id=None,
            folder_cache_id=None,
            parent_id=None,
        )


def test_treenode_accepts_valid_categories() -> None:
    """TreeNode 接受所有合法 category。"""
    for category in ("managed_root", "unscanned_root", "folder"):
        node = TreeNode(
            node_id=f"test:{category}",
            display_name="x",
            real_path="x",
            category=category,
            is_managed_root=False,
            managed_root_id=None,
            folder_cache_id=None,
            parent_id=None,
        )
        assert node.category == category


# --- 暂存区标记（阶段 3 Task 1） ---


class TestStagingMark:
    """FolderTreeService 的暂存区标记填充与缓存刷新。"""

    def test_root_node_is_staging_when_marked(
        self,
        db_connection: sqlite3.Connection,
        managed_root_service: ManagedRootService,
        scan_service: ScanService,
        staging_service: StagingService,
        tree_service: FolderTreeService,
        mod_tree: Path,
    ) -> None:
        """标记为暂存区的根节点 is_staging=True。"""
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)
        staging_service.mark_staging(mod_tree)
        tree_service.refresh_staging_cache()

        nodes = tree_service.list_root_nodes()
        assert len(nodes) == 1
        assert nodes[0].is_staging is True

    def test_root_node_not_staging_when_unmarked(
        self,
        db_connection: sqlite3.Connection,
        managed_root_service: ManagedRootService,
        scan_service: ScanService,
        staging_service: StagingService,
        tree_service: FolderTreeService,
        mod_tree: Path,
    ) -> None:
        """未标记的根节点 is_staging=False。"""
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)
        # 不标记暂存区
        tree_service.refresh_staging_cache()

        nodes = tree_service.list_root_nodes()
        assert len(nodes) == 1
        assert nodes[0].is_staging is False

    def test_child_node_is_staging_when_marked(
        self,
        db_connection: sqlite3.Connection,
        managed_root_service: ManagedRootService,
        scan_service: ScanService,
        staging_service: StagingService,
        tree_service: FolderTreeService,
        mod_tree: Path,
    ) -> None:
        """标记为暂存区的子节点 is_staging=True，其他兄弟节点为 False。"""
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)
        # 标记 "护甲" 子目录为暂存区
        staging_service.mark_staging(mod_tree / "护甲")
        tree_service.refresh_staging_cache()

        nodes = tree_service.list_root_nodes()
        children = tree_service.list_children(nodes[0].node_id)
        for child in children:
            if child.display_name == "护甲":
                assert child.is_staging is True
            else:
                assert child.is_staging is False

    def test_refresh_cache_reflects_unmark(
        self,
        db_connection: sqlite3.Connection,
        managed_root_service: ManagedRootService,
        scan_service: ScanService,
        staging_service: StagingService,
        tree_service: FolderTreeService,
        mod_tree: Path,
    ) -> None:
        """取消标记后刷新缓存，节点 is_staging 变为 False。"""
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)
        created = staging_service.mark_staging(mod_tree)
        tree_service.refresh_staging_cache()

        nodes = tree_service.list_root_nodes()
        assert nodes[0].is_staging is True

        staging_service.unmark_staging(created.id)
        tree_service.refresh_staging_cache()

        nodes = tree_service.list_root_nodes()
        assert nodes[0].is_staging is False

    def test_get_node_reflects_staging(
        self,
        db_connection: sqlite3.Connection,
        managed_root_service: ManagedRootService,
        scan_service: ScanService,
        staging_service: StagingService,
        tree_service: FolderTreeService,
        mod_tree: Path,
    ) -> None:
        """get_node 返回的节点 is_staging 正确。"""
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)
        staging_service.mark_staging(mod_tree / "Weapons")
        tree_service.refresh_staging_cache()

        nodes = tree_service.list_root_nodes()
        children = tree_service.list_children(nodes[0].node_id)
        weapons_node = next(c for c in children if c.display_name == "Weapons")

        fetched = tree_service.get_node(weapons_node.node_id)
        assert fetched is not None
        assert fetched.is_staging is True

    def test_no_staging_service_defaults_to_false(
        self,
        db_connection: sqlite3.Connection,
        managed_root_service: ManagedRootService,
        scan_service: ScanService,
        mod_tree: Path,
    ) -> None:
        """未注入 StagingService 时所有节点 is_staging=False。"""
        # 构造未注入 staging_service 的 FolderTreeService
        tree_svc = FolderTreeService(
            ManagedRootRepository(db_connection),
            FolderCacheRepository(db_connection),
            staging_service=None,
        )
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)

        nodes = tree_svc.list_root_nodes()
        assert len(nodes) == 1
        assert nodes[0].is_staging is False
