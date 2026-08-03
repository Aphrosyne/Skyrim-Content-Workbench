"""MainWindow 布局状态与菜单栏接线测试（UI合理性2/3，2026-08-03）。

覆盖：
- 顶部菜单栏创建与工具菜单可见性（按注入服务开关）
- 菜单视图切换 → _switch_view + 菜单选中态同步
- 菜单「重置布局」→ 分割线恢复默认比例 + 清除操作历史列宽存档
- 分割线状态跨重启持久化（closeEvent 保存 → 新窗口恢复）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402

from app import ui_constants as ui  # noqa: E402
from app.file_list_model import COL_MODIFIED, COL_SIZE, COL_TYPE  # noqa: E402
from app.main_menu_bar import MainMenuBar  # noqa: E402
from app.main_window import VIEW_INDEX_CARD, VIEW_INDEX_LIST, MainWindow  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from application.tag_service import TagService  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.repositories.content_unit import (  # noqa: E402
    ContentUnitRepository,
)
from infrastructure.repositories.content_unit_tag import (  # noqa: E402
    ContentUnitTagRepository,
)
from infrastructure.repositories.folder_cache import (  # noqa: E402
    FolderCacheRepository,
)
from infrastructure.repositories.managed_root import (  # noqa: E402
    ManagedRootRepository,
)
from infrastructure.repositories.tag import TagRepository  # noqa: E402
from infrastructure.repositories.tag_category import (  # noqa: E402
    TagCategoryRepository,
)

_ALL_KEYS = (
    ui.QSETTINGS_KEY_SPLITTER_MAIN,
    ui.QSETTINGS_KEY_SPLITTER_RIGHT,
    ui.QSETTINGS_KEY_HEADER_OPERATION_HISTORY,
    ui.QSETTINGS_KEY_VIEW_MODE,
    ui.QSETTINGS_KEY_ZOOM,
)

_DB_COUNTER = {"n": 0}


@pytest.fixture(autouse=True)
def _clear_layout_settings():
    """每个测试前后清除布局/视图 QSettings，避免测试间持久化干扰。"""
    s = QSettings(ui.QSETTINGS_ORGANIZATION, ui.QSETTINGS_APPLICATION)
    for key in _ALL_KEYS:
        s.remove(key)
    s.sync()
    yield
    for key in _ALL_KEYS:
        s.remove(key)
    s.sync()


def _make_mod_tree(tmp_path: Path) -> Path:
    root = tmp_path / "mods"
    root.mkdir(exist_ok=True)
    (root / "armor").mkdir(exist_ok=True)
    (root / "armor" / "preview.jpg").write_bytes(b"\x00" * 100)
    (root / "readme.txt").write_text("data", encoding="utf-8")
    return root


def _build_window(
    tmp_path: Path,
    *,
    tag_service: TagService | None = None,
) -> MainWindow:
    # 同一测试内可能构造多个窗口（如持久化跨重启用例），每个窗口用独立 db
    _DB_COUNTER["n"] += 1
    db_path = tmp_path / f"test-{_DB_COUNTER['n']}.db"
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
        tag_service=tag_service,
    )
    return window


def _make_tag_service(conn: sqlite3.Connection) -> TagService:
    return TagService(
        TagCategoryRepository(conn),
        TagRepository(conn),
        ContentUnitTagRepository(conn),
    )


def test_menu_bar_created(qapp, tmp_path: Path) -> None:
    window = _build_window(tmp_path)
    try:
        menu_bar = window._menu_bar  # noqa: SLF001
        assert isinstance(menu_bar, MainMenuBar)
        titles = [action.text() for action in menu_bar.actions()]
        assert ui.MENU_BAR_VIEW in titles
        assert ui.MENU_BAR_TOOLS in titles
    finally:
        window.close()


def test_menu_tools_actions_follow_injected_services(qapp, tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    window = _build_window(tmp_path, tag_service=_make_tag_service(conn))
    try:
        menu_bar = window._menu_bar  # noqa: SLF001
        assert menu_bar.tag_manager_action().isVisible()
        assert not menu_bar.operation_history_action().isVisible()  # 未注入 UndoService
    finally:
        window.close()
        conn.close()


def test_menu_view_switch_updates_window_and_menu(qapp, tmp_path: Path) -> None:
    window = _build_window(tmp_path)
    try:
        assert window.current_view_index() == VIEW_INDEX_LIST
        menu_bar = window._menu_bar  # noqa: SLF001

        menu_bar.view_card_action().trigger()
        qapp.processEvents()
        assert window.current_view_index() == VIEW_INDEX_CARD
        assert menu_bar.view_card_action().isChecked()
        assert not menu_bar.view_list_action().isChecked()

        menu_bar.view_list_action().trigger()
        qapp.processEvents()
        assert window.current_view_index() == VIEW_INDEX_LIST
        assert menu_bar.view_list_action().isChecked()
    finally:
        window.close()


def test_menu_reset_layout_restores_defaults(qapp, tmp_path: Path) -> None:
    window = _build_window(tmp_path)
    try:
        # 预置存档：主栏/右栏分割线 + 操作历史列宽
        settings = QSettings(ui.QSETTINGS_ORGANIZATION, ui.QSETTINGS_APPLICATION)
        window._splitter_state.save(window._splitter, ui.QSETTINGS_KEY_SPLITTER_MAIN)  # noqa: SLF001
        window._splitter_state.save(  # noqa: SLF001
            window._right_splitter,
            ui.QSETTINGS_KEY_SPLITTER_RIGHT,  # noqa: SLF001
        )
        settings.setValue(ui.QSETTINGS_KEY_HEADER_OPERATION_HISTORY, [1, 2, 3])
        assert settings.contains(ui.QSETTINGS_KEY_HEADER_OPERATION_HISTORY)

        window._menu_bar.reset_layout_action().trigger()  # noqa: SLF001
        qapp.processEvents()

        # 所有布局存档键被清除（几何恢复由 helper 单测按比例覆盖）
        assert not settings.contains(ui.QSETTINGS_KEY_SPLITTER_MAIN)
        assert not settings.contains(ui.QSETTINGS_KEY_SPLITTER_RIGHT)
        assert not settings.contains(ui.QSETTINGS_KEY_HEADER_OPERATION_HISTORY)
        assert window.statusBar().currentMessage() == ui.LAYOUT_RESET_STATUS
    finally:
        window.close()


def test_main_splitter_applies_defaults_on_first_show(qapp, tmp_path: Path) -> None:
    """UI合理性2：无存档时首次显示按默认比例 220/480/324 分配（中栏最大）。"""
    window = _build_window(tmp_path)
    try:
        window.show()
        qapp.processEvents()

        sizes = window._splitter.sizes()  # noqa: SLF001
        assert sizes[1] > sizes[0] and sizes[1] > sizes[2]
    finally:
        window.close()


def test_file_list_column_width_defaults_applied(qapp, tmp_path: Path) -> None:
    """UI合理性2：名称列 Stretch；类型/大小/修改日期按常量默认宽度。"""
    window = _build_window(tmp_path)
    try:
        header = window._content_view.horizontalHeader()  # noqa: SLF001
        assert header.sectionResizeMode(0) == header.ResizeMode.Stretch
        for col in (COL_TYPE, COL_SIZE, COL_MODIFIED):
            assert header.sectionSize(col) == ui.FILE_LIST_COLUMN_WIDTHS[col]
    finally:
        window.close()


def test_splitter_state_persists_across_restart(qapp, tmp_path: Path) -> None:
    window1 = _build_window(tmp_path)
    window1.show()  # showEvent 恢复 + 布局完成后再调整尺寸
    qapp.processEvents()
    window1._splitter.setSizes([300, 420, 300])  # noqa: SLF001
    qapp.processEvents()
    saved_sizes = window1._splitter.sizes()  # noqa: SLF001
    window1.close()  # closeEvent → 保存

    window2 = _build_window(tmp_path)
    window2.show()
    qapp.processEvents()
    try:
        assert window2._splitter.sizes() == saved_sizes  # noqa: SLF001
    finally:
        window2.close()
