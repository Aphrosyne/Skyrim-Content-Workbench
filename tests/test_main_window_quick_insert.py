"""MainWindow 快速插入集成测试（阶段 3 Task 5）。

覆盖：
- 快速插入按钮显隐：浏览模式隐藏 / 整理模式可见
- 按钮可用性：无绑定/无目标/目标与源相同 → 禁用
- 快速插入成功：Mod 组移入目标目录 + UI 刷新（装配面板解绑 + 目录树刷新 + 状态栏提示）
- 冲突提示 / 子目录阻止提示
- 取消确认对话框 → 不执行移动

注：跨盘测试在单元测试层已覆盖（test_quick_insert_service.py），
此处的 UI 集成测试不重复跨盘场景（需 monkeypatch os.stat，与 UI 层耦合过深）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from app.main_window import MainWindow  # noqa: E402
from application.assembly_service import AssemblyService  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.mod_group_service import ModGroupService  # noqa: E402
from application.quick_insert_service import QuickInsertService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from application.staging_service import StagingService  # noqa: E402
from domain.models import AppMode  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.file_operation_service import FileOperationService  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.folder_cache import FolderCacheRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402
from infrastructure.repositories.operation_history import (  # noqa: E402
    OperationHistoryRepository,
)
from infrastructure.repositories.staging_area import StagingAreaRepository  # noqa: E402


def _make_mod_tree(tmp_path: Path) -> Path:
    """构造测试目录树（含暂存区 + 零散文件 + 目标分类目录）。"""
    root = tmp_path / "mods"
    root.mkdir()
    staging = root / "Stash"
    staging.mkdir()
    (staging / "BDOR Black Knight 1.0.7z").write_bytes(b"\x00" * 100)
    (staging / "preview.jpg").write_bytes(b"\x00" * 50)
    # 目标分类目录（受管理根目录下，预先创建以便扫描时进入 folder_cache）
    (root / "Armor").mkdir()
    (root / "护甲分类").mkdir()
    return root


@pytest.fixture
def main_window_env(qapp, tmp_path: Path):
    """构造完整 MainWindow 测试环境（含暂存区 + 目标分类目录 + QuickInsertService 注入）。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row

    counter = {"n": 0}

    def fake_uuid() -> str:
        counter["n"] += 1
        return f"id-{counter['n']}"

    managed_service = ManagedRootService(
        ManagedRootRepository(conn),
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    staging_service = StagingService(
        StagingAreaRepository(conn),
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    tree_service = FolderTreeService(
        ManagedRootRepository(conn),
        FolderCacheRepository(conn),
        staging_service=staging_service,
    )
    content_service = ContentService(ContentUnitRepository(conn))
    scan_service = ScanService(
        managed_root_repo=ManagedRootRepository(conn),
        folder_cache_repo=FolderCacheRepository(conn),
        content_unit_repo=ContentUnitRepository(conn),
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    file_op_service = FileOperationService(OperationHistoryRepository(conn))
    folder_cache_repo = FolderCacheRepository(conn)
    mod_group_service = ModGroupService(file_op_service, content_service, folder_cache_repo)
    assembly_service = AssemblyService(
        file_op_service, ContentUnitRepository(conn), folder_cache_repo
    )
    quick_insert_service = QuickInsertService(
        file_op_service, ContentUnitRepository(conn), folder_cache_repo
    )

    root_dir = _make_mod_tree(tmp_path)
    root = managed_service.add_root(root_dir)
    scan_service.scan_root(root.id, incremental=False)
    staging_service.mark_staging(root_dir / "Stash")
    conn.commit()

    window = MainWindow(
        managed_service,
        tree_service,
        content_service,
        db_path,
        commit_callback=conn.commit,
        rollback_callback=conn.rollback,
        staging_service=staging_service,
        mod_group_service=mod_group_service,
        assembly_service=assembly_service,
        quick_insert_service=quick_insert_service,
    )
    yield window, conn, root_dir, root

    window.close()
    conn.close()


def _select_staging(qapp, window: MainWindow) -> None:
    """在目录树中选中暂存区 [S] 节点。"""
    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)
    for i in range(model.rowCount(root_idx)):
        child_idx = model.index(i, 0, root_idx)
        name = model.data(child_idx, Qt.DisplayRole)
        if name and "Stash" in name:
            window._tree_view.setCurrentIndex(child_idx)  # noqa: SLF001
            qapp.processEvents()
            return
    pytest.fail("未找到 Stash 节点")


def _select_tree_node_by_name(qapp, window: MainWindow, name: str) -> None:
    """在目录树根节点下选中指定名称的子节点。"""
    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)
    for i in range(model.rowCount(root_idx)):
        child_idx = model.index(i, 0, root_idx)
        node_name = model.data(child_idx, Qt.DisplayRole)
        if node_name and name in node_name:
            window._tree_view.setCurrentIndex(child_idx)  # noqa: SLF001
            qapp.processEvents()
            return
    pytest.fail(f"未找到目录树节点：{name}")


def _tree_contains_child(qapp, window: MainWindow, parent_name: str, child_name: str) -> bool:
    """检查目录树中指定父节点下是否包含名为 child_name 的子节点。

    用于验证文件夹移动后目录树是否立即刷新（无需重新扫描）。
    """
    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)
    for i in range(model.rowCount(root_idx)):
        parent_idx = model.index(i, 0, root_idx)
        parent_node_name = model.data(parent_idx, Qt.DisplayRole)
        if parent_node_name and parent_name in parent_node_name:
            # 找到父节点，遍历其子节点
            model.fetchMore(parent_idx)
            for j in range(model.rowCount(parent_idx)):
                child_idx = model.index(j, 0, parent_idx)
                child_node_name = model.data(child_idx, Qt.DisplayRole)
                if child_node_name and child_name in child_node_name:
                    return True
            return False
    return False


def _select_entry_by_name(qapp, window: MainWindow, name: str) -> int:
    """在中栏选中指定名称的条目，返回其 row。"""
    model = window._content_list_model  # noqa: SLF001
    for row in range(model.entry_count()):
        entry = model.entry_at(row)
        if entry is not None and entry.name == name:
            idx = model.index(row, 0)
            window._content_view.setCurrentIndex(idx)  # noqa: SLF001
            qapp.processEvents()
            return row
    pytest.fail(f"未找到条目：{name}")


def _create_mod_group(qapp, window: MainWindow, source_name: str, chosen_name: str | None = None):
    """创建 Mod 组并返回新 ContentUnit + Mod 文件夹路径。"""
    _select_entry_by_name(qapp, window, source_name)
    entry = window._content_list_model.entry_at(  # noqa: SLF001
        window._content_view.currentIndex().row()  # noqa: SLF001
    )
    assert entry is not None

    if chosen_name is None:
        from application.mod_group_service import extract_mod_name

        chosen_name = extract_mod_name(entry.name)

    original_dialog = window._show_create_mod_group_dialog  # noqa: SLF001
    window._show_create_mod_group_dialog = lambda pure, full: chosen_name  # noqa: SLF001
    try:
        window._on_create_mod_group(entry)  # noqa: SLF001
        qapp.processEvents()
    finally:
        window._show_create_mod_group_dialog = original_dialog  # noqa: SLF001

    staging_path = window._organize_workarea_path  # noqa: SLF001
    assert staging_path is not None
    mod_folder = Path(staging_path) / chosen_name
    unit = window._content_service.get_by_path(str(mod_folder))  # noqa: SLF001
    assert unit is not None, f"Mod 组 ContentUnit 未创建：{mod_folder}"
    return unit, mod_folder


# === 按钮显隐 ===


def test_quick_insert_button_hidden_in_browse_mode(qapp, main_window_env) -> None:
    """浏览模式：快速插入按钮隐藏。"""
    window, _, _, _ = main_window_env
    assert window.current_mode() == AppMode.browse
    # 窗口未 show() 时 isVisible() 不可靠，用 isHidden() 反向断言
    assert window._quick_insert_button.isHidden()  # noqa: SLF001


def test_quick_insert_button_visible_in_organize_mode(qapp, main_window_env) -> None:
    """整理模式：快速插入按钮可见（即使无绑定）。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    # 窗口未 show() 时 isVisible() 返回 False，用 isHidden() 反向断言
    assert not window._quick_insert_button.isHidden()  # noqa: SLF001
    # 未绑定 Mod 组 → 禁用
    assert not window._quick_insert_button.isEnabled()  # noqa: SLF001


def test_quick_insert_button_disabled_without_mod_group_binding(qapp, main_window_env) -> None:
    """整理模式但未绑定 Mod 组：按钮禁用。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    assert not window._quick_insert_button.isEnabled()  # noqa: SLF001


def test_quick_insert_button_enabled_with_binding_and_target(qapp, main_window_env) -> None:
    """整理模式 + 装配面板已绑定 + 目录树选中目标目录：按钮启用。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    # 创建 Mod 组 → 装配面板绑定
    _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")

    # 选中目标分类目录 Armor
    _select_tree_node_by_name(qapp, window, "Armor")
    qapp.processEvents()

    # 按钮应启用
    assert window._quick_insert_button.isEnabled()  # noqa: SLF001


def test_quick_insert_button_disabled_when_target_is_source_parent(qapp, main_window_env) -> None:
    """目标目录 == 源 Mod 组父目录（暂存区）：按钮禁用（无需移动）。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    # 创建 Mod 组 → Mod 组位于暂存区下
    _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")

    # 选中暂存区（即源 Mod 组的父目录）作为目标
    _select_staging(qapp, window)
    qapp.processEvents()

    # 按钮应禁用（目标 == 源父目录，无需移动）
    assert not window._quick_insert_button.isEnabled()  # noqa: SLF001


# === 快速插入成功 ===


def test_quick_insert_moves_mod_group_to_target(qapp, main_window_env, monkeypatch) -> None:
    """快速插入成功：Mod 组移入目标目录 + UI 刷新（含目录树立即刷新）。"""
    window, _, root_dir, _ = main_window_env
    target_dir = root_dir / "Armor"

    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    assert mod_folder.is_dir()

    # 选中目标分类目录 Armor
    _select_tree_node_by_name(qapp, window, "Armor")
    qapp.processEvents()

    # Mock QMessageBox.question 返回 Yes
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)

    # 点击快速插入
    window._on_quick_insert_clicked()  # noqa: SLF001
    qapp.processEvents()

    # 源 Mod 组文件夹已移走
    assert not mod_folder.exists()
    # Mod 组文件夹已移入目标目录
    new_path = target_dir / "MyMod"
    assert new_path.is_dir()

    # 装配面板已解绑（Mod 组已移走）
    assert not window.assembly_panel_visible()
    assert window.assembly_panel_current_unit_id() is None

    # ContentUnit.path 已更新
    updated_unit = window._content_service.get_by_id(unit.id)  # noqa: SLF001
    assert updated_unit is not None
    assert updated_unit.path == str(new_path)

    # 目录树立即刷新：目标目录 Armor 下应出现 MyMod 节点（无需重新扫描）
    assert _tree_contains_child(qapp, window, "Armor", "MyMod"), (
        "快速插入后目录树目标目录未立即显示新节点（folder_cache 同步可能遗漏）"
    )
    # 源暂存区下不应再有 MyMod 节点
    assert not _tree_contains_child(qapp, window, "Stash", "MyMod")


def test_quick_insert_cancel_does_not_move(qapp, main_window_env, monkeypatch) -> None:
    """用户在确认对话框点击「否」→ 不执行移动。"""
    window, _, root_dir, _ = main_window_env
    target_dir = root_dir / "Armor"

    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")

    _select_tree_node_by_name(qapp, window, "Armor")
    qapp.processEvents()

    # Mock QMessageBox.question 返回 No
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.No)

    window._on_quick_insert_clicked()  # noqa: SLF001
    qapp.processEvents()

    # 源文件夹仍在原位
    assert mod_folder.is_dir()
    assert not (target_dir / "MyMod").exists()


# === 错误提示 ===


def test_quick_insert_conflict_shows_warning(qapp, main_window_env, monkeypatch) -> None:
    """目标目录已存在同名文件夹 → 弹窗提示冲突。"""
    window, _, root_dir, _ = main_window_env
    target_dir = root_dir / "Armor"

    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")

    # 在目标目录下预先创建同名文件夹
    (target_dir / "MyMod").mkdir()

    _select_tree_node_by_name(qapp, window, "Armor")
    qapp.processEvents()

    # Mock：question 返回 Yes，warning 记录调用
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    warning_calls: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *a, **kw: warning_calls.append(a[1] if len(a) > 1 else ""),
    )

    window._on_quick_insert_clicked()  # noqa: SLF001
    qapp.processEvents()

    # 应弹出警告
    assert len(warning_calls) > 0
    # 源文件夹仍在原位
    assert mod_folder.is_dir()


def test_quick_insert_self_subdirectory_shows_warning(qapp, main_window_env, monkeypatch) -> None:
    """目标在 Mod 组子目录内 → 弹窗提示 SelfSubdirectoryError。

    通过在 Mod 组内创建子目录并选中作为目标来触发。
    """
    window, _, root_dir, _ = main_window_env

    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")

    # 在 Mod 组内创建子目录
    sub_dir = mod_folder / "SubDir"
    sub_dir.mkdir()

    # 直接设置目标路径为 Mod 组子目录（绕过目录树选中，模拟边界情况）
    window._organize_target_path = str(sub_dir)  # noqa: SLF001
    qapp.processEvents()

    # 按钮状态：目标在源子树内 → 禁用（_update_quick_insert_button_state 会禁用）
    # 但用户可能强制点击（或按钮状态过时），所以 _on_quick_insert_clicked 内部不二次检查子目录
    # 实际由 QuickInsertService.move 抛 SelfSubdirectoryError
    # Mock：question 返回 Yes，warning 记录调用
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    warning_calls: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *a, **kw: warning_calls.append(a[1] if len(a) > 1 else ""),
    )

    # 手动调用（绕过按钮禁用）
    window._on_quick_insert_clicked()  # noqa: SLF001
    qapp.processEvents()

    # 应弹出警告
    assert len(warning_calls) > 0
    # 源文件夹仍在原位
    assert mod_folder.is_dir()


# === 中文路径 ===


def test_quick_insert_chinese_mod_group(qapp, main_window_env, monkeypatch) -> None:
    """中文 Mod 组名快速插入到中文目标目录。"""
    window, _, root_dir, _ = main_window_env
    # 中文目标目录已在 fixture 的 _make_mod_tree 中预先创建并扫描
    chinese_target = root_dir / "护甲分类"

    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "寒霜之心")

    # 选中中文目标目录
    _select_tree_node_by_name(qapp, window, "护甲分类")
    qapp.processEvents()

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)

    window._on_quick_insert_clicked()  # noqa: SLF001
    qapp.processEvents()

    new_path = chinese_target / "寒霜之心"
    assert new_path.is_dir()
    assert not mod_folder.exists()

    updated_unit = window._content_service.get_by_id(unit.id)  # noqa: SLF001
    assert updated_unit is not None
    assert updated_unit.path == str(new_path)
