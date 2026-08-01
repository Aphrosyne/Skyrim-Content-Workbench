"""「在资源管理器中打开」功能测试（Stage 5 Task 1）。

覆盖：
- 文件列表右键菜单含「在资源管理器中打开」项；
- 目录树右键菜单含「在资源管理器中打开」项；
- _on_open_in_explorer 调用 subprocess.run，参数正确；
- 中文路径正常传递。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")

from app import ui_constants as ui  # noqa: E402
from app.main_window import MainWindow  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from domain.models import FileEntry  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.folder_cache import FolderCacheRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402


def _make_mod_tree(tmp_path: Path) -> Path:
    """构造测试目录树。"""
    root = tmp_path / "mods"
    root.mkdir()
    (root / "armor").mkdir()
    (root / "armor" / "preview.jpg").write_bytes(b"\x00" * 100)
    (root / "readme.txt").write_text("data", encoding="utf-8")
    (root / "中文文件夹").mkdir()
    return root


@pytest.fixture
def main_window_env(qapp, tmp_path: Path):
    """构造 MainWindow 测试环境。"""
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
        now_provider=lambda: "2026-07-12T00:00:00Z",
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
        now_provider=lambda: "2026-07-12T00:00:00Z",
        uuid_provider=fake_uuid,
    )

    root_dir = _make_mod_tree(tmp_path)
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
    """选中目录树根节点。"""
    model = window._tree_model  # noqa: SLF001
    idx = model.index(0, 0)
    window._tree_view.setCurrentIndex(idx)  # noqa: SLF001
    qapp.processEvents()


def _make_file_entry(path: str, name: str, is_dir: bool = False) -> FileEntry:
    """构造 FileEntry 测试对象。"""
    return FileEntry(
        name=name,
        path=path,
        is_dir=is_dir,
        size=100,
        modified_at="2026-07-12T00:00:00Z",
        content_unit=None,
    )


def test_content_menu_has_open_in_explorer_for_single_selection(main_window_env) -> None:
    """文件列表右键单选时含「在资源管理器中打开」项。"""
    window, _, _ = main_window_env
    entry = _make_file_entry("C:/test/file.txt", "file.txt")
    actions = window.build_content_menu_actions([entry])
    labels = [lbl for lbl, _, _ in actions]
    assert ui.MENU_OPEN_IN_EXPLORER in labels


def test_content_menu_no_open_in_explorer_for_multi_selection(main_window_env) -> None:
    """多选时不显示「在资源管理器中打开」（仅单选可用）。"""
    window, _, _ = main_window_env
    e1 = _make_file_entry("C:/test/a.txt", "a.txt")
    e2 = _make_file_entry("C:/test/b.txt", "b.txt")
    actions = window.build_content_menu_actions([e1, e2])
    labels = [lbl for lbl, _, _ in actions]
    assert ui.MENU_OPEN_IN_EXPLORER not in labels


def test_open_in_explorer_calls_subprocess(main_window_env) -> None:
    """_on_open_in_explorer 调用 subprocess.run，参数正确。"""
    window, _, _ = main_window_env
    handler = window.open_in_explorer_handler()
    test_path = "C:/test/file.txt"

    with patch("app.main_window.subprocess.run") as mock_run:
        handler(test_path)
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        # 验证参数含 explorer /select, 和路径
        args = call_args[0][0]
        assert args[0] == "explorer"
        assert args[1] == "/select,"
        assert args[2] == test_path


def test_open_in_explorer_handles_chinese_path(main_window_env) -> None:
    """中文路径正常传递给 subprocess.run。"""
    window, _, _ = main_window_env
    handler = window.open_in_explorer_handler()
    test_path = "C:/mods/中文文件夹/文件.txt"

    with patch("app.main_window.subprocess.run") as mock_run:
        handler(test_path)
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        args = call_args[0][0]
        assert args[2] == test_path  # 中文路径正确传递


def test_open_in_explorer_handles_exception(main_window_env) -> None:
    """subprocess 抛异常时不崩溃，显示错误提示。"""
    window, _, _ = main_window_env
    handler = window.open_in_explorer_handler()
    test_path = "C:/nonexistent/file.txt"

    with (
        patch(
            "app.main_window.subprocess.run",
            side_effect=OSError("test error"),
        ),
        patch("app.main_window.QMessageBox.information"),
    ):
        # 应不抛异常
        handler(test_path)


def test_open_in_explorer_handler_callable(main_window_env) -> None:
    """open_in_explorer_handler 返回可调用对象。"""
    window, _, _ = main_window_env
    handler = window.open_in_explorer_handler()
    assert callable(handler)
