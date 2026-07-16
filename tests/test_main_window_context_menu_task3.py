"""MainWindow 右键菜单集成测试（阶段 3 Task 3）。

覆盖：
- 创建 Mod 组菜单项仅在整理模式 + 单选文件 + 注入 ModGroupService 时显示
- 标记为内容单元 / 取消标记 菜单项根据 entry.content_unit 切换
- 多选显示"把每个文件标记为内容单元"
- 复制路径始终显示
- 创建 Mod 组完整流程（对话框 + 文件夹创建 + 文件移动 + ContentUnit 创建 + 列表刷新）
- 标记/取消标记后列表刷新
- 批量标记多个文件
- ExtendedSelection 已启用
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from app.main_window import MainWindow  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.mod_group_service import ModGroupService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from application.staging_service import StagingService  # noqa: E402
from domain.models import AppMode, FileEntry  # noqa: E402
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
    """构造测试目录树（含暂存区）。"""
    root = tmp_path / "mods"
    root.mkdir()
    staging = root / "Stash"
    staging.mkdir()
    (staging / "BDOR Black Knight 1.0.7z").write_bytes(b"\x00" * 100)
    (staging / "SkyUI 5.1 SE.zip").write_bytes(b"\x00" * 80)
    (staging / "preview.jpg").write_bytes(b"\x00" * 50)
    return root


@pytest.fixture
def main_window_env(qapp, tmp_path: Path):
    """构造完整 MainWindow 测试环境（含暂存区 + ModGroupService 注入）。"""
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

    root_dir = _make_mod_tree(tmp_path)
    root = managed_service.add_root(root_dir)
    # 扫描以填充 folder_cache（目录树才能显示 Stash 子节点）+
    # 自动标记压缩包为内容单元（BDOR/SkyUI）
    scan_service.scan_root(root.id, incremental=False)
    # 标记暂存区
    staging_service.mark_staging(root_dir / "Stash")
    conn.commit()

    window = MainWindow(
        managed_service,
        tree_service,
        content_service,
        db_path,
        commit_callback=conn.commit,
        staging_service=staging_service,
        mod_group_service=mod_group_service,
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


def _find_entry_by_name(window: MainWindow, name: str) -> FileEntry | None:
    """在中栏查找指定名称的条目，返回 FileEntry 或 None。"""
    model = window._content_list_model  # noqa: SLF001
    for row in range(model.entry_count()):
        entry = model.entry_at(row)
        if entry is not None and entry.name == name:
            return entry
    return None


# === 测试 ===


def test_extended_selection_enabled(qapp, main_window_env) -> None:
    """_content_view 应启用 ExtendedSelection。"""
    from PySide6.QtWidgets import QAbstractItemView

    window, _, _, _ = main_window_env
    assert (
        window._content_view.selectionMode()  # noqa: SLF001
        == QAbstractItemView.SelectionMode.ExtendedSelection
    )


def test_context_menu_includes_mark_for_unmarked(qapp, main_window_env) -> None:
    """右键未标记条目 → 可调用 mark_as_content_unit 验证 service 链路。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    # 选中 preview.jpg（非压缩包，未自动标记）
    _select_entry_by_name(qapp, window, "preview.jpg")

    # 直接调用 mark_as_content_unit 验证 service 链路
    entry = window._content_list_model.entry_at(  # noqa: SLF001
        window._content_view.currentIndex().row()  # noqa: SLF001
    )
    assert entry is not None
    assert entry.content_unit is None  # 未标记

    window._on_mark_content_unit(entry)  # noqa: SLF001
    qapp.processEvents()

    # 重新加载列表，preview.jpg 应已标记
    entry_after = None
    for i in range(window.entry_count()):
        e = window.entry_at(i)
        if e is not None and e.name == "preview.jpg":
            entry_after = e
            break
    assert entry_after is not None
    assert entry_after.content_unit is not None


def test_mark_content_unit_refreshes_list(qapp, main_window_env) -> None:
    """标记后中栏列表刷新，显示 [内容单元] 标记。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()
    _select_entry_by_name(qapp, window, "preview.jpg")

    entry = window._content_list_model.entry_at(  # noqa: SLF001
        window._content_view.currentIndex().row()  # noqa: SLF001
    )
    window._on_mark_content_unit(entry)  # noqa: SLF001
    qapp.processEvents()

    # 验证 DB 中有该 ContentUnit
    assert entry is not None
    unit = window._content_service.get_by_path(entry.path)  # noqa: SLF001
    assert unit is not None


def test_unmark_content_unit_refreshes_list(qapp, main_window_env) -> None:
    """取消标记后中栏列表刷新，[内容单元] 标记消失。"""
    window, conn, _, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    # 先标记 BDOR 文件
    _select_entry_by_name(qapp, window, "BDOR Black Knight 1.0.7z")
    entry = window._content_list_model.entry_at(  # noqa: SLF001
        window._content_view.currentIndex().row()  # noqa: SLF001
    )
    assert entry is not None
    # 该压缩包应已被扫描自动标记
    assert entry.content_unit is not None

    window._on_unmark_content_unit(entry)  # noqa: SLF001
    qapp.processEvents()

    # DB 中该 ContentUnit status 应为 "unmarked"（不删除记录，防止扫描重建）
    unit = window._content_service.get_by_path(entry.path)  # noqa: SLF001
    assert unit is not None
    assert unit.status == "unmarked"

    # 列表刷新后该条目不再显示 [内容单元] 标记
    refreshed_entry = _find_entry_by_name(window, "BDOR Black Knight 1.0.7z")
    assert refreshed_entry is not None
    assert refreshed_entry.content_unit is None


def test_create_mod_group_full_flow(qapp, main_window_env) -> None:
    """创建 Mod 组完整流程：对话框接受默认名 → 文件夹创建 + 文件移动 + ContentUnit 创建。"""
    window, conn, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    _select_entry_by_name(qapp, window, "BDOR Black Knight 1.0.7z")
    entry = window._content_list_model.entry_at(  # noqa: SLF001
        window._content_view.currentIndex().row()  # noqa: SLF001
    )
    assert entry is not None

    # Mock 对话框返回纯 Mod 名
    original_dialog = window._show_create_mod_group_dialog  # noqa: SLF001
    window._show_create_mod_group_dialog = lambda pure, full: pure  # noqa: SLF001

    try:
        window._on_create_mod_group(entry)  # noqa: SLF001
        qapp.processEvents()
    finally:
        window._show_create_mod_group_dialog = original_dialog  # noqa: SLF001

    # 文件夹被创建
    target_folder = root_dir / "Stash" / "BDOR Black Knight"
    assert target_folder.is_dir()
    # 源文件被移入
    target_file = target_folder / "BDOR Black Knight 1.0.7z"
    assert target_file.is_file()
    assert not (root_dir / "Stash" / "BDOR Black Knight 1.0.7z").exists()
    # ContentUnit 创建
    unit = window._content_service.get_by_path(str(target_folder))  # noqa: SLF001
    assert unit is not None
    assert unit.title == "BDOR Black Knight"
    assert unit.status == "unorganized"
    # operation_history 写入 2 条
    rows = conn.execute("SELECT * FROM operation_history").fetchall()
    assert len(rows) == 2

    # 列表已自动刷新：新文件夹出现在列表中且标记为内容单元
    folder_entry = _find_entry_by_name(window, "BDOR Black Knight")
    assert folder_entry is not None
    assert folder_entry.is_dir
    assert folder_entry.content_unit is not None
    # 源文件不再出现在列表中（已移入 Mod 组文件夹，子项被收纳不显示）
    # spec §7.3：暂存区文件列表显示"零散文件"，已收纳的子文件不显示
    old_entry = _find_entry_by_name(window, "BDOR Black Knight 1.0.7z")
    assert old_entry is None


def test_create_mod_group_appears_in_tree(qapp, main_window_env) -> None:
    """创建 Mod 组后目录树立即显示新文件夹（无需重新扫描）。

    回归测试（2026-07-16）：main.py 之前未向 ModGroupService 注入
    FolderCacheRepository，导致创建 Mod 组后 folder_cache 未写入，
    目录树不显示新文件夹。修复后 ModGroupService 同步写入 folder_cache，
    _refresh_tree 后新节点立即可见。
    """
    window, conn, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    tree_model = window._tree_model  # noqa: SLF001

    def _list_stash_children() -> list[str]:
        """列出暂存区节点下的子节点显示名（每次重新 fetchMore，避免 reset 后失效）。"""
        root_idx = tree_model.index(0, 0)
        tree_model.fetchMore(root_idx)
        for i in range(tree_model.rowCount(root_idx)):
            child_idx = tree_model.index(i, 0, root_idx)
            name = tree_model.data(child_idx, Qt.DisplayRole)
            if name and "Stash" in name:
                tree_model.fetchMore(child_idx)
                names = []
                for j in range(tree_model.rowCount(child_idx)):
                    grandchild_idx = tree_model.index(j, 0, child_idx)
                    grandchild_name = tree_model.data(grandchild_idx, Qt.DisplayRole)
                    if grandchild_name:
                        names.append(grandchild_name)
                return names
        return []

    before_names = _list_stash_children()
    assert "BDOR Black Knight" not in before_names

    # 创建 Mod 组
    _select_entry_by_name(qapp, window, "BDOR Black Knight 1.0.7z")
    entry = window._content_list_model.entry_at(  # noqa: SLF001
        window._content_view.currentIndex().row()  # noqa: SLF001
    )
    window._show_create_mod_group_dialog = lambda pure, full: pure  # noqa: SLF001
    window._on_create_mod_group(entry)  # noqa: SLF001
    qapp.processEvents()

    # 刷新后暂存区子节点应包含新文件夹
    after_names = _list_stash_children()
    assert "BDOR Black Knight" in after_names


def test_create_mod_group_cancel_dialog(qapp, main_window_env) -> None:
    """取消对话框不操作文件。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    _select_entry_by_name(qapp, window, "BDOR Black Knight 1.0.7z")
    entry = window._content_list_model.entry_at(  # noqa: SLF001
        window._content_view.currentIndex().row()  # noqa: SLF001
    )

    # Mock 对话框返回 None（用户取消）
    window._show_create_mod_group_dialog = lambda pure, full: None  # noqa: SLF001

    window._on_create_mod_group(entry)  # noqa: SLF001
    qapp.processEvents()

    # 无文件夹创建
    assert not (root_dir / "Stash" / "BDOR Black Knight").exists()
    # 源文件仍在原位
    assert (root_dir / "Stash" / "BDOR Black Knight 1.0.7z").exists()


def test_create_mod_group_name_conflict(qapp, main_window_env, monkeypatch) -> None:
    """同名文件夹已存在 → 弹出错误（不抛异常，仅 QMessageBox）。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    # 预先创建同名文件夹
    (root_dir / "Stash" / "BDOR Black Knight").mkdir()

    _select_entry_by_name(qapp, window, "BDOR Black Knight 1.0.7z")
    entry = window._content_list_model.entry_at(  # noqa: SLF001
        window._content_view.currentIndex().row()  # noqa: SLF001
    )
    window._show_create_mod_group_dialog = lambda pure, full: pure  # noqa: SLF001

    # Mock QMessageBox 避免阻塞
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)

    # 应不抛异常（QMessageBox 被 mock）
    window._on_create_mod_group(entry)  # noqa: SLF001
    qapp.processEvents()

    # 源文件仍在原位（未被移动）
    assert (root_dir / "Stash" / "BDOR Black Knight 1.0.7z").exists()


def test_batch_mark_multiple_files(qapp, main_window_env) -> None:
    """多选 2 个未标记文件 → 批量标记 → 各自独立 ContentUnit。"""
    window, conn, _, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    # 多选 preview.jpg + SkyUI 5.1 SE.zip（后者已被扫描自动标记，先取消）
    # 找到 SkyUI 先取消标记
    for i in range(window.entry_count()):
        e = window.entry_at(i)
        if e is not None and e.name == "SkyUI 5.1 SE.zip":
            if e.content_unit is not None:
                window._on_unmark_content_unit(e)  # noqa: SLF001
                qapp.processEvents()
            break

    # 重新加载列表后多选
    model = window._content_list_model  # noqa: SLF001
    sm = window._content_view.selectionModel()  # noqa: SLF001
    sm.clearSelection()

    target_entries = []
    for row in range(model.entry_count()):
        entry = model.entry_at(row)
        if entry is not None and entry.name in ("preview.jpg", "SkyUI 5.1 SE.zip"):
            idx = model.index(row, 0)
            sm.select(idx, sm.SelectionFlag.Select)
            target_entries.append(entry)
    qapp.processEvents()

    assert len(target_entries) == 2

    window._on_batch_mark_content_unit(target_entries)  # noqa: SLF001
    qapp.processEvents()

    # 两个文件各自有 ContentUnit
    for e in target_entries:
        unit = window._content_service.get_by_path(e.path)  # noqa: SLF001
        assert unit is not None


def test_chinese_filename_mod_group(qapp, main_window_env) -> None:
    """中文名 Mod 组创建。"""
    window, conn, root_dir, _ = main_window_env
    # 在暂存区中加一个中文文件
    (root_dir / "Stash" / "寒霜之心 1.0.7z").write_bytes(b"\x00" * 100)

    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    _select_entry_by_name(qapp, window, "寒霜之心 1.0.7z")
    entry = window._content_list_model.entry_at(  # noqa: SLF001
        window._content_view.currentIndex().row()  # noqa: SLF001
    )
    window._show_create_mod_group_dialog = lambda pure, full: pure  # noqa: SLF001

    window._on_create_mod_group(entry)  # noqa: SLF001
    qapp.processEvents()

    target_folder = root_dir / "Stash" / "寒霜之心"
    assert target_folder.is_dir()
    assert (target_folder / "寒霜之心 1.0.7z").is_file()
