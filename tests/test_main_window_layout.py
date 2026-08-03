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
from app.content_unit_delegate import ContentUnitStripeDelegate  # noqa: E402
from app.file_list_model import COL_MODIFIED, COL_NAME, COL_SIZE, COL_TYPE  # noqa: E402
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
    ui.QSETTINGS_KEY_HEADER_FILE_LIST,
    ui.QSETTINGS_KEY_HEADER_OPERATION_HISTORY,
    ui.QSETTINGS_KEY_VIEW_MODE,
    ui.QSETTINGS_KEY_ZOOM,
    ui.QSETTINGS_KEY_MARKER_ICON_ENABLED,
    ui.QSETTINGS_KEY_MARKER_ICON_GLYPH,
    ui.QSETTINGS_KEY_MARKER_STRIPE_ENABLED,
    ui.QSETTINGS_KEY_MARKER_STRIPE_COLOR,
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


def test_content_unit_stripe_delegate_installed(qapp, tmp_path: Path) -> None:
    window = _build_window(tmp_path)
    try:
        delegate = window._content_view.itemDelegateForColumn(COL_NAME)  # noqa: SLF001
        assert isinstance(delegate, ContentUnitStripeDelegate)
        # UI合理性21：默认配置 = 仅启用色条，🔗 预填但不启用
        assert delegate.config().icon_enabled is False
        assert delegate.config().stripe_enabled is True
        # 菜单入口存在且启用
        marker_action = window._menu_bar.marker_config_action()  # noqa: SLF001
        assert marker_action.text() == ui.MENU_VIEW_CONTENT_UNIT_MARKER
        assert marker_action.isEnabled()
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
        # 中栏列表/卡片按钮同步勾选（验收反馈：此前菜单切换不刷新按钮）
        assert window._view_card_button.isChecked()  # noqa: SLF001
        assert not window._view_list_button.isChecked()  # noqa: SLF001

        menu_bar.view_list_action().trigger()
        qapp.processEvents()
        assert window.current_view_index() == VIEW_INDEX_LIST
        assert menu_bar.view_list_action().isChecked()
        assert window._view_list_button.isChecked()  # noqa: SLF001
        assert not window._view_card_button.isChecked()  # noqa: SLF001
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
        settings.setValue(ui.QSETTINGS_KEY_HEADER_FILE_LIST, [111, 222, 333, 444])

        window._menu_bar.reset_layout_action().trigger()  # noqa: SLF001
        qapp.processEvents()

        # 所有布局存档键被清除（几何恢复由 helper 单测按比例覆盖）
        assert not settings.contains(ui.QSETTINGS_KEY_SPLITTER_MAIN)
        assert not settings.contains(ui.QSETTINGS_KEY_SPLITTER_RIGHT)
        assert not settings.contains(ui.QSETTINGS_KEY_HEADER_FILE_LIST)
        assert not settings.contains(ui.QSETTINGS_KEY_HEADER_OPERATION_HISTORY)
        assert window.statusBar().currentMessage() == ui.LAYOUT_RESET_STATUS
        # 中栏列宽实时恢复默认
        header = window._content_view.horizontalHeader()  # noqa: SLF001
        assert header.sectionSize(COL_NAME) == ui.FILE_LIST_COLUMN_WIDTHS[0]
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
    """验收反馈：四列 Interactive 固定默认宽度（Explorer 风格，右侧留白供框选）。"""
    window = _build_window(tmp_path)
    try:
        header = window._content_view.horizontalHeader()  # noqa: SLF001
        assert not header.stretchLastSection()
        for col in (COL_NAME, COL_TYPE, COL_SIZE, COL_MODIFIED):
            assert header.sectionResizeMode(col) == header.ResizeMode.Interactive
            assert header.sectionSize(col) == ui.FILE_LIST_COLUMN_WIDTHS[col]
    finally:
        window.close()


def test_file_list_column_widths_persist_across_restart(qapp, tmp_path: Path) -> None:
    """固化（2026-08-03 验收反馈）：中栏四列宽度跨重启保留。"""
    window1 = _build_window(tmp_path)
    window1.show()
    qapp.processEvents()
    try:
        header1 = window1._content_view.horizontalHeader()  # noqa: SLF001
        header1.resizeSection(COL_NAME, 400)  # sectionResized → 实时保存
        header1.resizeSection(COL_MODIFIED, 180)
        qapp.processEvents()
    finally:
        window1.close()

    window2 = _build_window(tmp_path)
    window2.show()
    qapp.processEvents()
    try:
        header2 = window2._content_view.horizontalHeader()  # noqa: SLF001
        assert header2.sectionSize(COL_NAME) == 400
        assert header2.sectionSize(COL_MODIFIED) == 180
    finally:
        window2.close()


def test_file_list_scrollbar_does_not_shift_columns(qapp, tmp_path: Path) -> None:
    """验收反馈：列宽固定 → 滚动条出现/消失只改变右侧留白，列位置不横移（中栏不跳）。"""
    window = _build_window(tmp_path)
    try:
        view = window._content_view  # noqa: SLF001
        header = view.horizontalHeader()  # noqa: SLF001
        # 无 Stretch 列，且首列从左侧固定起算
        assert all(header.sectionResizeMode(i) == header.ResizeMode.Interactive for i in range(4))
    finally:
        window.close()


def test_rubber_band_selects_when_bottom_edge_in_blank(qapp, tmp_path: Path) -> None:
    """操作合理性4：末行下方空白区起框（从下往上拉）也能选中到末行。"""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QStandardItemModel

    from app.main_window import _RubberBandTableView

    view = _RubberBandTableView()
    try:
        model = QStandardItemModel(5, 1)
        view.setModel(model)
        # 模拟：上边缘落在第 3 行，下边缘落在末行下方空白区（视口内）
        view.rowAt = lambda y: 3 if y == 90 else -1  # type: ignore[method-assign]

        view._select_rows_in_rect(QRect(10, 90, 100, 110))  # bottom=199（空白区）
        selected = [idx.row() for idx in view.selectionModel().selectedRows()]
        assert set(selected) == {3, 4}

        # 矩形整体落在空白区 → 不选中
        view.selectionModel().clear()
        view._select_rows_in_rect(QRect(10, 200, 100, 50))
        assert not view.selectionModel().hasSelection()
    finally:
        view.close()


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


def test_splitter_restores_registry_string_sizes(qapp, tmp_path: Path) -> None:
    """Windows 注册表字符串列表尺寸也能恢复（固化修复，2026-08-03）。"""
    settings = QSettings(ui.QSETTINGS_ORGANIZATION, ui.QSETTINGS_APPLICATION)
    settings.setValue(ui.QSETTINGS_KEY_SPLITTER_MAIN, ["300", "420", "300"])
    settings.sync()

    window = _build_window(tmp_path)
    window.show()
    qapp.processEvents()
    try:
        sizes = window._splitter.sizes()  # noqa: SLF001
        assert sizes[1] > sizes[0] and sizes[1] > sizes[2]  # 比例 300/420/300
    finally:
        window.close()


def test_splitter_drag_saves_immediately(qapp, tmp_path: Path) -> None:
    """UI合理性2 固化：拖动分隔线即时写入 QSettings（不依赖 closeEvent）。"""
    window = _build_window(tmp_path)
    window.show()
    qapp.processEvents()
    try:
        window._splitter.setSizes([200, 500, 300])  # noqa: SLF001
        window._splitter.splitterMoved.emit(1, 500)  # noqa: SLF001 模拟用户拖动

        settings = QSettings(ui.QSETTINGS_ORGANIZATION, ui.QSETTINGS_APPLICATION)
        assert settings.contains(ui.QSETTINGS_KEY_SPLITTER_MAIN)
    finally:
        window.close()


def test_cover_filter_toggle(qapp, tmp_path: Path) -> None:
    """操作便捷性5：封面筛选切换按钮（按下=只看有封面，不持久化）。"""
    window = _build_window(tmp_path)
    try:
        # 标记 armor 为内容单元（自动封面 preview.jpg）
        window._content_service.mark_as_content_unit(tmp_path / "mods" / "armor")  # noqa: SLF001
        window._commit()
        window._refresh_content_list(str(tmp_path / "mods"))  # noqa: SLF001
        qapp.processEvents()
        assert window.entry_count() == 2

        window._cover_filter_button.setChecked(True)  # noqa: SLF001
        qapp.processEvents()
        assert window.entry_count() == 1
        assert window.entry_at(0).name == "armor"

        window._cover_filter_button.setChecked(False)  # noqa: SLF001
        qapp.processEvents()
        assert window.entry_count() == 2
    finally:
        window.close()


def test_navigation_remembers_selection(qapp, tmp_path: Path) -> None:
    """操作便捷性7：双击进入目录，后退/前进恢复选中内容。"""
    window = _build_window(tmp_path)
    window.show()
    qapp.processEvents()
    try:
        window._refresh_content_list(str(tmp_path / "mods"))  # noqa: SLF001
        qapp.processEvents()
        row_armor = next(
            r for r in range(window.entry_count()) if window.entry_at(r).name == "armor"
        )
        window._content_view.selectRow(row_armor)  # noqa: SLF001
        qapp.processEvents()

        window._on_entry_activated(window._content_list_model.index(row_armor, 0))  # noqa: SLF001
        qapp.processEvents()
        row_pic = next(
            r for r in range(window.entry_count()) if window.entry_at(r).name == "preview.jpg"
        )
        window._content_view.selectRow(row_pic)  # noqa: SLF001
        qapp.processEvents()

        window._on_nav_back_clicked()  # noqa: SLF001
        qapp.processEvents()
        selected = [
            window.entry_at(r.row()).name
            for r in window._content_view.selectionModel().selectedRows()  # noqa: SLF001
        ]
        assert "armor" in selected

        window._on_nav_forward_clicked()  # noqa: SLF001
        qapp.processEvents()
        selected2 = [
            window.entry_at(r.row()).name
            for r in window._content_view.selectionModel().selectedRows()  # noqa: SLF001
        ]
        assert "preview.jpg" in selected2
    finally:
        window.close()
