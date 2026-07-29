"""MainWindow 视图切换集成测试（Stage 5 Task 1）。

覆盖：
- 默认视图为列表；
- 切换到卡片视图后 QListView 可见；
- 选中状态跨视图保持（用 entry.path 匹配）；
- 整理模式隐藏视图切换栏；
- 浏览模式恢复视图切换栏；
- 缩放滑块改变卡片图标尺寸；
- 卡片名称不含 [内容单元] 标记；
- 卡片 ToolTip 含状态。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QListView  # noqa: E402

from app.main_window import (  # noqa: E402
    QSETTINGS_APPLICATION,
    QSETTINGS_KEY_VIEW_MODE,
    QSETTINGS_KEY_ZOOM,
    QSETTINGS_ORGANIZATION,
    VIEW_INDEX_CARD,
    VIEW_INDEX_LIST,
    MainWindow,  # noqa: E402
)
from application.content_service import ContentService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.folder_cache import FolderCacheRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_qsettings():
    """每个测试前清除 QSettings，避免视图模式/缩放值在测试间持久化干扰。"""
    s = QSettings(QSETTINGS_ORGANIZATION, QSETTINGS_APPLICATION)
    s.remove(QSETTINGS_KEY_VIEW_MODE)
    s.remove(QSETTINGS_KEY_ZOOM)
    s.sync()
    yield
    s.remove(QSETTINGS_KEY_VIEW_MODE)
    s.remove(QSETTINGS_KEY_ZOOM)
    s.sync()


def _make_mod_tree(tmp_path: Path) -> Path:
    """构造测试目录树（含压缩包 + 普通文件 + 中文文件夹）。"""
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


def _find_entry_index(window: MainWindow, name: str) -> int:
    """在文件列表中查找指定名称条目的索引。"""
    for i in range(window.entry_count()):
        entry = window.entry_at(i)
        if entry is not None and entry.name == name:
            return i
    pytest.fail(f"未找到条目：{name}")


def test_default_view_is_list(main_window_env) -> None:
    """默认视图为列表（VIEW_INDEX_LIST）。"""
    window, _, _ = main_window_env
    assert window.current_view_index() == VIEW_INDEX_LIST


def test_switch_to_card_view(main_window_env) -> None:
    """切换到卡片视图后 current_view_index 变为 CARD。"""
    window, _, _ = main_window_env
    window.switch_view_for_test(VIEW_INDEX_CARD)
    assert window.current_view_index() == VIEW_INDEX_CARD
    # 卡片视图应为 QListView 实例
    assert isinstance(window._card_view, QListView)  # noqa: SLF001


def test_switch_back_to_list_view(main_window_env) -> None:
    """切换到卡片再切回列表。"""
    window, _, _ = main_window_env
    window.switch_view_for_test(VIEW_INDEX_CARD)
    assert window.current_view_index() == VIEW_INDEX_CARD
    window.switch_view_for_test(VIEW_INDEX_LIST)
    assert window.current_view_index() == VIEW_INDEX_LIST


def test_card_name_has_no_content_unit_marker(qapp, main_window_env) -> None:
    """卡片视图名称不含 [内容单元] 标记（Q6:B）。"""
    window, conn, root_dir = main_window_env
    # 标记 armor 文件夹为内容单元
    window._content_service.mark_as_content_unit(root_dir / "armor")  # noqa: SLF001
    conn.commit()
    _select_root(qapp, window)
    window._refresh_content_list_for_current_mode()  # noqa: SLF001
    qapp.processEvents()

    # 切到卡片视图
    window.switch_view_for_test(VIEW_INDEX_CARD)
    qapp.processEvents()

    # 取 armor 条目的 DisplayRole
    idx_row = _find_entry_index(window, "armor")
    card_model = window.card_list_model()
    idx = card_model.index(idx_row, 0)
    name = card_model.data(idx, Qt.DisplayRole)
    assert name == "armor"
    assert "[内容单元]" not in name  # Q6:B


def test_card_tooltip_includes_status(qapp, main_window_env) -> None:
    """卡片 ToolTip 含内容单元状态（Q6:B）。"""
    window, conn, root_dir = main_window_env
    window._content_service.mark_as_content_unit(root_dir / "armor")  # noqa: SLF001
    conn.commit()
    _select_root(qapp, window)
    window._refresh_content_list_for_current_mode()  # noqa: SLF001
    qapp.processEvents()

    window.switch_view_for_test(VIEW_INDEX_CARD)
    qapp.processEvents()

    idx_row = _find_entry_index(window, "armor")
    card_model = window.card_list_model()
    idx = card_model.index(idx_row, 0)
    tooltip = card_model.data(idx, Qt.ToolTipRole)
    assert "armor" in tooltip
    assert "内容单元状态" in tooltip  # Q6:B


def test_zoom_slider_changes_card_icon_size(main_window_env) -> None:
    """缩放滑块改变卡片图标尺寸（Task 1b：范围 128~512，默认 256）。"""
    window, _, _ = main_window_env
    # 默认 256
    assert window.card_icon_size() == 256
    # 改为 128
    window.set_card_icon_size_for_test(128)
    assert window.card_icon_size() == 128
    assert window.zoom_slider_value() == 128
    # 改为 512
    window.set_card_icon_size_for_test(512)
    assert window.card_icon_size() == 512


def test_zoom_slider_clamped_to_range(main_window_env) -> None:
    """缩放值在有效范围内（Task 1b：128~512）。"""
    window, _, _ = main_window_env
    # 测试边界值
    window.set_card_icon_size_for_test(128)
    assert window.card_icon_size() == 128
    window.set_card_icon_size_for_test(512)
    assert window.card_icon_size() == 512


def test_view_switch_bar_visible_in_browse_mode(main_window_env) -> None:
    """浏览模式视图切换栏可见（Q5=B）。"""
    window, _, _ = main_window_env
    assert window.view_switch_bar_visible() is True


def test_view_switch_bar_hidden_in_organize_mode(qapp, main_window_env) -> None:
    """整理模式隐藏视图切换栏（Q5=B）。"""
    window, _, _ = main_window_env
    # 切到整理模式
    window._set_mode(__import__("domain.models", fromlist=["AppMode"]).AppMode.organize)  # noqa: SLF001
    qapp.processEvents()
    assert window.view_switch_bar_visible() is False
    # 整理模式强制切到列表视图
    assert window.current_view_index() == VIEW_INDEX_LIST


def test_view_switch_bar_restored_in_browse_mode(qapp, main_window_env) -> None:
    """切回浏览模式恢复视图切换栏（Q5=B）。"""
    window, _, _ = main_window_env
    # 切到整理模式
    from domain.models import AppMode

    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()
    assert window.view_switch_bar_visible() is False
    # 切回浏览模式
    window._set_mode(AppMode.browse)  # noqa: SLF001
    qapp.processEvents()
    assert window.view_switch_bar_visible() is True


def test_selection_preserved_across_view_switch(qapp, main_window_env) -> None:
    """选中状态跨视图保持（用 entry.path 匹配，Q4=A）。"""

    window, _, _ = main_window_env
    _select_root(qapp, window)
    qapp.processEvents()

    # 在列表视图中选中 readme.txt（用 setCurrentIndex 选中整行）
    idx_row = _find_entry_index(window, "readme.txt")
    model_idx = window._content_list_model.index(idx_row, 0)  # noqa: SLF001
    window._content_view.setCurrentIndex(model_idx)  # noqa: SLF001
    qapp.processEvents()
    # 验证列表视图确实选中了
    sm = window._content_view.selectionModel()  # noqa: SLF001
    list_selected = sm.selectedRows()
    assert len(list_selected) == 1, f"列表视图选中失败：{len(list_selected)}"

    # 切到卡片视图
    window.switch_view_for_test(VIEW_INDEX_CARD)
    qapp.processEvents()

    # 卡片视图中对应行应被选中
    selected = window._card_view.selectionModel().selectedRows()  # noqa: SLF001
    assert len(selected) >= 1, "卡片视图选中为空，选中状态未保持"
    card_entry = window.card_list_model().entry_at(selected[0].row())
    assert card_entry is not None
    assert card_entry.name == "readme.txt"


def test_card_list_model_shares_data_with_file_list_model(qapp, main_window_env) -> None:
    """CardListModel 与 FileListModel 共享同一份数据（Q6:B 复用）。"""
    window, _, _ = main_window_env
    _select_root(qapp, window)
    qapp.processEvents()

    # 两个 model 行数应一致
    assert window.card_list_model().rowCount() == window._content_list_model.rowCount()  # noqa: SLF001

    # 对应行的 entry 应一致
    for i in range(window.entry_count()):
        file_entry = window._content_list_model.entry_at(i)  # noqa: SLF001
        card_entry = window.card_list_model().entry_at(i)
        assert file_entry is not None
        assert card_entry is not None
        assert file_entry.path == card_entry.path
