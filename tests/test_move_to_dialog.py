"""MoveToDialog 单元测试（Stage 5 Task 5）。

覆盖：
- 初始状态：确定按钮禁用、源条目数量正确
- 选中目标目录 → 路径回显 + 确定按钮启用
- 选中源自身 → 确定按钮禁用 + 无效提示
- 选中源子目录 → 确定按钮禁用 + 无效提示
- 选中合法目标 → 确定按钮启用
- 程序化选中目标 → selected_target_path 正确
- 确定/取消按钮 → accept / reject
- 默认展开源父目录（Q7=A）
- 独立 FolderTreeModel 实例（R2：不共享主窗口 model）
- 中文目录名支持
- 多选源条目数量提示（Q1=A）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from app.move_to_dialog import MoveToDialog  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.folder_cache import FolderCacheRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """临时数据库路径。"""
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def conn(db_path: Path) -> sqlite3.Connection:
    """数据库连接（Row 工厂）。"""
    c = get_connection(db_path)
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def mod_tree(tmp_path: Path) -> Path:
    """构造测试目录树：含子目录用于测试目标选择。

    结构：
        mods/
        ├── Armor/           # 源所在目录
        │   ├── 寒霜之心.7z  # 源文件
        │   └── preview.jpg
        ├── Weapons/         # 合法目标目录
        └── 空目录/          # 合法目标目录
    """
    root = tmp_path / "mods"
    root.mkdir()
    armor = root / "Armor"
    armor.mkdir()
    (armor / "寒霜之心.7z").write_bytes(b"\x00" * 100)
    (armor / "preview.jpg").write_bytes(b"\x00" * 50)
    weapons = root / "Weapons"
    weapons.mkdir()
    empty = root / "空目录"
    empty.mkdir()
    return root


@pytest.fixture
def tree_service(conn: sqlite3.Connection, mod_tree: Path) -> FolderTreeService:
    """构造已扫描的 FolderTreeService。"""
    counter = {"n": 0}

    def fake_uuid() -> str:
        counter["n"] += 1
        return f"id-{counter['n']}"

    managed_service = ManagedRootService(
        ManagedRootRepository(conn),
        now_provider=lambda: "2026-07-30T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    scan_service = ScanService(
        managed_root_repo=ManagedRootRepository(conn),
        folder_cache_repo=FolderCacheRepository(conn),
        content_unit_repo=ContentUnitRepository(conn),
        now_provider=lambda: "2026-07-30T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    svc = FolderTreeService(
        ManagedRootRepository(conn),
        FolderCacheRepository(conn),
    )
    root = managed_service.add_root(mod_tree)
    scan_service.scan_root(root.id, incremental=False)
    conn.commit()
    return svc


# === 初始状态 ===


class TestInitialState:
    def test_initial_ok_button_disabled(self, qapp, tree_service, mod_tree):
        """初始未选中目标 → 确定按钮禁用。"""
        src = mod_tree / "Armor" / "寒霜之心.7z"
        dialog = MoveToDialog(tree_service, [src])
        try:
            assert not dialog.is_ok_button_enabled()
            assert dialog.selected_target_path() is None
        finally:
            dialog.close()

    def test_src_count_single(self, qapp, tree_service, mod_tree):
        """单个源条目 → src_count=1。"""
        src = mod_tree / "Armor" / "寒霜之心.7z"
        dialog = MoveToDialog(tree_service, [src])
        try:
            assert dialog.src_count() == 1
        finally:
            dialog.close()

    def test_src_count_multiple(self, qapp, tree_service, mod_tree):
        """多个源条目 → src_count 正确（Q1=A 多选支持）。"""
        src1 = mod_tree / "Armor" / "寒霜之心.7z"
        src2 = mod_tree / "Armor" / "preview.jpg"
        dialog = MoveToDialog(tree_service, [src1, src2])
        try:
            assert dialog.src_count() == 2
        finally:
            dialog.close()


# === 选中目标目录 ===


class TestSelectTarget:
    def test_select_valid_target_enables_ok(self, qapp, tree_service, mod_tree):
        """选中合法目标目录 → 确定按钮启用 + 路径回显。"""
        src = mod_tree / "Armor" / "寒霜之心.7z"
        dialog = MoveToDialog(tree_service, [src])
        try:
            target_str = str(mod_tree / "Weapons")
            assert dialog.select_target_by_path(target_str)
            qapp.processEvents()
            assert dialog.is_ok_button_enabled()
            selected = dialog.selected_target_path()
            assert selected is not None
            assert selected.name == "Weapons"
        finally:
            dialog.close()

    def test_select_target_chinese_name(self, qapp, tree_service, mod_tree):
        """选中中文目录名目标 → 正确选中。"""
        src = mod_tree / "Armor" / "寒霜之心.7z"
        dialog = MoveToDialog(tree_service, [src])
        try:
            target_str = str(mod_tree / "空目录")
            assert dialog.select_target_by_path(target_str)
            qapp.processEvents()
            assert dialog.is_ok_button_enabled()
            selected = dialog.selected_target_path()
            assert selected is not None
            assert selected.name == "空目录"
        finally:
            dialog.close()

    def test_select_root_as_target(self, qapp, tree_service, mod_tree):
        """选中根目录作为目标 → 合法（根不是源的子目录）。"""
        src = mod_tree / "Armor" / "寒霜之心.7z"
        dialog = MoveToDialog(tree_service, [src])
        try:
            target_str = str(mod_tree)
            assert dialog.select_target_by_path(target_str)
            qapp.processEvents()
            assert dialog.is_ok_button_enabled()
        finally:
            dialog.close()

    def test_select_nonexistent_target_returns_false(self, qapp, tree_service, mod_tree):
        """程序化选中不存在的路径 → 返回 False。"""
        src = mod_tree / "Armor" / "寒霜之心.7z"
        dialog = MoveToDialog(tree_service, [src])
        try:
            result = dialog.select_target_by_path(str(mod_tree / "nonexistent"))
            assert not result
            assert not dialog.is_ok_button_enabled()
        finally:
            dialog.close()


# === 源自身/子目录校验（R1） ===


class TestSelfOrSubdirectory:
    def test_select_source_itself_disables_ok(self, qapp, tree_service, mod_tree):
        """选中源自身 → 确定按钮禁用（源为目录时）。"""
        # 源为 Armor 目录
        src = mod_tree / "Armor"
        dialog = MoveToDialog(tree_service, [src])
        try:
            target_str = str(src)
            assert dialog.select_target_by_path(target_str)
            qapp.processEvents()
            assert not dialog.is_ok_button_enabled()
        finally:
            dialog.close()

    def test_select_source_subdirectory_disables_ok(self, qapp, tree_service, mod_tree):
        """选中源的子目录 → 确定按钮禁用。"""
        # 源为 Armor 目录，目标选为 Armor 自身（已在上文测试），
        # 此处测试源为根目录 mods，目标选为其子目录 Armor
        src = mod_tree
        dialog = MoveToDialog(tree_service, [src])
        try:
            target_str = str(mod_tree / "Armor")
            assert dialog.select_target_by_path(target_str)
            qapp.processEvents()
            assert not dialog.is_ok_button_enabled()
        finally:
            dialog.close()

    def test_select_source_sibling_enables_ok(self, qapp, tree_service, mod_tree):
        """选中源的兄弟目录 → 确定按钮启用（非子目录）。"""
        # 源为 Armor，目标选为 Weapons（兄弟目录）
        src = mod_tree / "Armor"
        dialog = MoveToDialog(tree_service, [src])
        try:
            target_str = str(mod_tree / "Weapons")
            assert dialog.select_target_by_path(target_str)
            qapp.processEvents()
            assert dialog.is_ok_button_enabled()
        finally:
            dialog.close()

    def test_multi_source_subdirectory_check(self, qapp, tree_service, mod_tree):
        """多源场景：目标为任一源的子目录 → 禁用。"""
        src1 = mod_tree / "Armor"
        src2 = mod_tree / "Weapons"
        dialog = MoveToDialog(tree_service, [src1, src2])
        try:
            # 选中 Armor 自身（src1）
            target_str = str(mod_tree / "Armor")
            assert dialog.select_target_by_path(target_str)
            qapp.processEvents()
            assert not dialog.is_ok_button_enabled()
        finally:
            dialog.close()


# === 确定 / 取消按钮 ===


class TestOkCancelButtons:
    def test_ok_button_accepts(self, qapp, tree_service, mod_tree, monkeypatch):
        """确定按钮 → dialog.accept() 被调用。"""
        src = mod_tree / "Armor" / "寒霜之心.7z"
        dialog = MoveToDialog(tree_service, [src])
        target_str = str(mod_tree / "Weapons")
        dialog.select_target_by_path(target_str)
        qapp.processEvents()

        accepted = {"flag": False}
        monkeypatch.setattr(dialog, "accept", lambda: accepted.__setitem__("flag", True))
        dialog.click_ok_button()
        assert accepted["flag"]

    def test_cancel_button_rejects(self, qapp, tree_service, mod_tree, monkeypatch):
        """取消按钮 → dialog.reject() 被调用。"""
        src = mod_tree / "Armor" / "寒霜之心.7z"
        dialog = MoveToDialog(tree_service, [src])

        rejected = {"flag": False}
        monkeypatch.setattr(dialog, "reject", lambda: rejected.__setitem__("flag", True))
        dialog.click_cancel_button()
        assert rejected["flag"]

    def test_ok_button_no_selection_no_accept(self, qapp, tree_service, mod_tree, monkeypatch):
        """未选中目标时点击确定 → 不触发 accept。"""
        src = mod_tree / "Armor" / "寒霜之心.7z"
        dialog = MoveToDialog(tree_service, [src])

        accepted = {"flag": False}
        monkeypatch.setattr(dialog, "accept", lambda: accepted.__setitem__("flag", True))
        dialog.click_ok_button()
        assert not accepted["flag"]

    def test_ok_button_invalid_target_no_accept(self, qapp, tree_service, mod_tree, monkeypatch):
        """选中无效目标（源自身）时点击确定 → 不触发 accept。"""
        src = mod_tree / "Armor"
        dialog = MoveToDialog(tree_service, [src])
        dialog.select_target_by_path(str(src))
        qapp.processEvents()

        accepted = {"flag": False}
        monkeypatch.setattr(dialog, "accept", lambda: accepted.__setitem__("flag", True))
        dialog.click_ok_button()
        assert not accepted["flag"]


# === 默认展开（Q7=A） ===


class TestDefaultExpand:
    def test_default_expand_path_selects_node(self, qapp, tree_service, mod_tree):
        """提供 default_expand_path → 默认选中对应节点。"""
        src = mod_tree / "Armor" / "寒霜之心.7z"
        # 默认展开源所在父目录 Armor
        default_expand = mod_tree / "Armor"
        dialog = MoveToDialog(
            tree_service,
            [src],
            default_expand_path=default_expand,
        )
        try:
            qapp.processEvents()
            # 选中后确定按钮应启用（Armor 不是源的子目录，源是文件）
            assert dialog.is_ok_button_enabled()
            selected = dialog.selected_target_path()
            assert selected is not None
            assert selected.name == "Armor"
        finally:
            dialog.close()

    def test_no_default_expand_path(self, qapp, tree_service, mod_tree):
        """不提供 default_expand_path → 初始无选中。"""
        src = mod_tree / "Armor" / "寒霜之心.7z"
        dialog = MoveToDialog(tree_service, [src], default_expand_path=None)
        try:
            assert not dialog.is_ok_button_enabled()
            assert dialog.selected_target_path() is None
        finally:
            dialog.close()


# === 独立 model 实例（R2） ===


def test_dialog_uses_independent_model(qapp, tree_service, mod_tree):
    """对话框创建独立的 FolderTreeModel 实例（R2）。"""
    src = mod_tree / "Armor" / "寒霜之心.7z"
    dialog = MoveToDialog(tree_service, [src])
    try:
        # 对话框内部 model 应为 FolderTreeModel 实例
        model = dialog._tree_model  # noqa: SLF001
        assert model is not None
        # 已 refresh 加载根节点
        assert model.root_node_count() > 0
    finally:
        dialog.close()
