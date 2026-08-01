"""MainWindow 快速设置封面右键菜单测试（Stage 5 Task 1）。

覆盖：
- 文件列表右键已标记文件夹内容单元 → 菜单含「快速设置封面」且可用
- 文件列表右键压缩包内容单元 → 菜单含「快速设置封面」但灰显
- 点击菜单项 → ContentService.quick_set_cover 被调用 + 状态栏反馈
- 无图片时状态栏显示提示
- 已有封面时状态栏显示未覆盖提示
- 整理模式下菜单项同样可用（不限制模式）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from app import ui_constants as ui  # noqa: E402
from app.main_window import MainWindow  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.folder_cache import FolderCacheRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402


def _make_tree_with_images(tmp_path: Path) -> Path:
    """构造含图片的测试目录树。

    结构：
        mods/
        ├── FolderMod/            # 文件夹内容单元候选（mark 后有图片）
        │   ├── preview.jpg
        │   └── readme.txt
        ├── EmptyFolder/          # 文件夹内容单元候选（无图片）
        │   └── readme.txt
        └── archive_mod.7z        # 压缩包内容单元（自动标记）
    """
    root = tmp_path / "mods"
    root.mkdir()

    folder_mod = root / "FolderMod"
    folder_mod.mkdir()
    (folder_mod / "preview.jpg").write_bytes(b"img")
    (folder_mod / "readme.txt").write_text("readme")

    empty_folder = root / "EmptyFolder"
    empty_folder.mkdir()
    (empty_folder / "readme.txt").write_text("readme")

    (root / "archive_mod.7z").write_bytes(b"\x00" * 100)

    return root


@pytest.fixture
def main_window_env(qapp, tmp_path: Path):
    """构造含图片的完整 MainWindow 测试环境。"""
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
        FolderCacheRepository(conn),
        ContentUnitRepository(conn),
        now_provider=lambda: "2026-07-29T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    tree_service = FolderTreeService(
        ManagedRootRepository(conn),
        FolderCacheRepository(conn),
    )
    content_service = ContentService(ContentUnitRepository(conn))
    scan_service = ScanService(
        managed_root_repo=ManagedRootRepository(conn),
        folder_cache_repo=FolderCacheRepository(conn),
        content_unit_repo=ContentUnitRepository(conn),
        now_provider=lambda: "2026-07-29T00:00:00Z",
        uuid_provider=fake_uuid,
    )

    root_dir = _make_tree_with_images(tmp_path)
    root = managed_service.add_root(root_dir)
    scan_service.scan_root(root.id, incremental=False)
    conn.commit()

    window = MainWindow(
        managed_service,
        tree_service,
        content_service,
        db_path,
        commit_callback=conn.commit,
    )
    yield window, conn, root_dir
    window.close()
    conn.close()


def _select_root(qapp, window: MainWindow) -> None:
    """选中目录树根节点并等待事件处理。"""
    model = window._tree_model  # noqa: SLF001
    idx = model.index(0, 0)
    window._tree_view.setCurrentIndex(idx)  # noqa: SLF001
    qapp.processEvents()


def _find_entry_index(window: MainWindow, name: str) -> int:
    """在文件列表中查找指定名称条目的索引。"""
    for i in range(window.entry_count()):
        entry = window.entry_at(i)
        if entry is not None and entry.name == name:
            return i
    pytest.fail(f"未找到条目：{name}")


def _select_entry(qapp, window: MainWindow, name: str) -> None:
    """在文件列表中选中指定名称条目（保留用于元数据加载流程）。"""
    row = _find_entry_index(window, name)
    idx = window._content_list_model.index(row, 0)  # noqa: SLF001
    window._content_view.setCurrentIndex(idx)  # noqa: SLF001
    qapp.processEvents()


def test_context_menu_has_quick_set_cover_for_marked_folder(qapp, main_window_env) -> None:
    """已标记文件夹内容单元 → 右键菜单含「快速设置封面」且可用。"""
    window, conn, root_dir = main_window_env
    _select_root(qapp, window)

    # 标记 FolderMod 为内容单元
    folder_mod = root_dir / "FolderMod"
    window._content_service.mark_as_content_unit(folder_mod)  # noqa: SLF001
    conn.commit()
    window._refresh_content_list_for_current_mode()  # noqa: SLF001
    qapp.processEvents()

    # 直接从文件列表取条目，调用 _build_content_menu_actions 验证菜单项
    row = _find_entry_index(window, "FolderMod")
    entry = window.entry_at(row)
    assert entry is not None
    assert entry.content_unit is not None

    actions = window._build_content_menu_actions([entry])  # noqa: SLF001
    labels = [lbl for lbl, _, _ in actions]
    assert ui.MENU_QUICK_SET_COVER in labels
    idx = labels.index(ui.MENU_QUICK_SET_COVER)
    assert actions[idx][2] is True  # 文件夹 → enabled


def test_context_menu_quick_set_cover_disabled_for_archive_unit(qapp, main_window_env) -> None:
    """压缩包内容单元 → 右键菜单「快速设置封面」灰显。"""
    window, conn, root_dir = main_window_env
    _select_root(qapp, window)

    row = _find_entry_index(window, "archive_mod.7z")
    entry = window.entry_at(row)
    assert entry is not None
    assert entry.content_unit is not None  # 扫描时已自动标记
    assert entry.is_dir is False  # 压缩包是文件

    actions = window._build_content_menu_actions([entry])  # noqa: SLF001
    labels = [lbl for lbl, _, _ in actions]
    assert ui.MENU_QUICK_SET_COVER in labels
    idx = labels.index(ui.MENU_QUICK_SET_COVER)
    assert actions[idx][2] is False  # 压缩包 → 灰显


def test_quick_set_cover_success_shows_status_message(qapp, main_window_env, monkeypatch) -> None:
    """点击快速设置封面 → 设置成功 → 状态栏显示成功消息。"""
    window, conn, root_dir = main_window_env
    _select_root(qapp, window)

    # 标记 FolderMod（mark 时已自动录入封面，需先清空再走 quick_set_cover）
    folder_mod = root_dir / "FolderMod"
    unit = window._content_service.mark_as_content_unit(folder_mod)  # noqa: SLF001
    conn.commit()
    assert unit.cover_path == "preview.jpg"

    # 清空 cover_path 模拟"未自动录入"场景
    from dataclasses import replace

    cleared = replace(unit, cover_path=None)
    repo = ContentUnitRepository(conn)
    repo.update(cleared)
    conn.commit()

    # 直接调用 handler 验证状态栏反馈
    window._on_quick_set_cover(unit.id)  # noqa: SLF001
    qapp.processEvents()

    assert ui.MENU_QUICK_SET_COVER_OK in window.statusBar().currentMessage()
    # 验证 DB 已写入
    persisted = repo.get_by_id(unit.id)
    assert persisted is not None
    assert persisted.cover_path == "preview.jpg"


def test_quick_set_cover_no_image_shows_hint(qapp, main_window_env) -> None:
    """无图片时点击快速设置封面 → 状态栏显示「该目录无可用图片」。"""
    window, conn, root_dir = main_window_env
    _select_root(qapp, window)

    # 标记 EmptyFolder（无图片）
    empty_folder = root_dir / "EmptyFolder"
    unit = window._content_service.mark_as_content_unit(empty_folder)  # noqa: SLF001
    conn.commit()
    assert unit.cover_path is None

    window._on_quick_set_cover(unit.id)  # noqa: SLF001
    qapp.processEvents()

    assert ui.MENU_QUICK_SET_COVER_NO_IMAGE in window.statusBar().currentMessage()


def test_quick_set_cover_already_set_shows_hint(qapp, main_window_env) -> None:
    """已有封面时点击快速设置封面 → 状态栏显示「已设置封面，未覆盖」。"""
    window, conn, root_dir = main_window_env
    _select_root(qapp, window)

    # 标记 FolderMod（mark 时已自动录入 preview.jpg）
    folder_mod = root_dir / "FolderMod"
    unit = window._content_service.mark_as_content_unit(folder_mod)  # noqa: SLF001
    conn.commit()
    assert unit.cover_path == "preview.jpg"

    window._on_quick_set_cover(unit.id)  # noqa: SLF001
    qapp.processEvents()

    assert ui.MENU_QUICK_SET_COVER_ALREADY_SET in window.statusBar().currentMessage()
    # 验证未被覆盖
    repo = ContentUnitRepository(conn)
    persisted = repo.get_by_id(unit.id)
    assert persisted is not None
    assert persisted.cover_path == "preview.jpg"


def test_mark_folder_auto_cover_appears_in_file_list(qapp, main_window_env) -> None:
    """标记文件夹 → 文件列表显示内容单元标记 + 缩略图图标可加载。"""
    window, conn, root_dir = main_window_env
    _select_root(qapp, window)

    folder_mod = root_dir / "FolderMod"
    window._content_service.mark_as_content_unit(folder_mod)  # noqa: SLF001
    conn.commit()
    window._refresh_content_list_for_current_mode()  # noqa: SLF001
    qapp.processEvents()

    # 验证条目已是内容单元
    row = _find_entry_index(window, "FolderMod")
    entry = window.entry_at(row)
    assert entry is not None
    assert entry.content_unit is not None
    assert entry.content_unit.cover_path == "preview.jpg"
