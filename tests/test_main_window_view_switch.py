"""MainWindow 视图切换集成测试（Stage 5 Task 1）。

覆盖：
- 默认视图为列表；
- 切换到卡片视图后 QListView 可见；
- 选中状态跨视图保持（用 entry.path 匹配）；
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
    assert "内容单元" in tooltip  # Stage 5 Task 7：统一显示"内容单元"标记


def test_zoom_combo_changes_card_icon_size(main_window_env) -> None:
    """缩放下拉框改变卡片图标尺寸（Task 1b 修正：预选尺寸，默认 160）。"""
    window, _, _ = main_window_env
    # 默认 160
    assert window.card_icon_size() == 160
    assert window.zoom_combo_value() == 160
    # 改为 96
    window.set_card_icon_size_for_test(96)
    assert window.card_icon_size() == 96
    assert window.zoom_combo_value() == 96
    # 改为 256
    window.set_card_icon_size_for_test(256)
    assert window.card_icon_size() == 256


def test_zoom_combo_only_accepts_preset_sizes(main_window_env) -> None:
    """Task 1b 修正：下拉框仅接受预选尺寸，非预选值无效。"""
    window, _, _ = main_window_env
    # 非预选值（如 100）→ 无效，不改变
    window.set_card_icon_size_for_test(100)
    assert window.card_icon_size() == 160  # 保持默认
    # 边界值
    window.set_card_icon_size_for_test(96)
    assert window.card_icon_size() == 96
    window.set_card_icon_size_for_test(256)
    assert window.card_icon_size() == 256


def test_view_switch_bar_visible_in_browse_mode(main_window_env) -> None:
    """浏览模式视图切换栏可见（Q5=B）。"""
    window, _, _ = main_window_env
    assert window.view_switch_bar_visible() is True


def test_selection_preserved_across_view_switch(qapp, main_window_env) -> None:
    """选中状态跨视图保持：列表 → 卡片（用 entry.path 匹配，Q4=A）。"""

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


def test_selection_preserved_card_to_list(qapp, main_window_env) -> None:
    """选中状态跨视图保持：卡片 → 列表（Q4=A 回归）。

    回归场景：原实现从固定列表视图读取选中条目，导致卡片视图选中切回列表时
    选中丢失。修复后从当前活动视图读取选中 path，再在新视图按 path 重新选中。
    """
    window, _, _ = main_window_env
    _select_root(qapp, window)
    qapp.processEvents()

    # 先切到卡片视图
    window.switch_view_for_test(VIEW_INDEX_CARD)
    qapp.processEvents()

    # 在卡片视图中选中 readme.txt
    idx_row = _find_entry_index(window, "readme.txt")
    card_model = window.card_list_model()
    model_idx = card_model.index(idx_row, 0)
    window._card_view.setCurrentIndex(model_idx)  # noqa: SLF001
    qapp.processEvents()
    # 验证卡片视图确实选中了
    card_sm = window._card_view.selectionModel()  # noqa: SLF001
    card_selected = card_sm.selectedRows()
    assert len(card_selected) == 1, f"卡片视图选中失败：{len(card_selected)}"

    # 切回列表视图
    window.switch_view_for_test(VIEW_INDEX_LIST)
    qapp.processEvents()

    # 列表视图中对应条目应被选中
    list_sm = window._content_view.selectionModel()  # noqa: SLF001
    list_selected = list_sm.selectedRows()
    assert len(list_selected) >= 1, "列表视图选中为空，卡片→列表选中状态未保持"
    list_entry = window._content_list_model.entry_at(list_selected[0].row())  # noqa: SLF001
    assert list_entry is not None
    assert list_entry.name == "readme.txt"


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


# === Stage 5 Task 2：排序下拉框 + 列头方向指示 ===


def test_sort_field_combo_initial_state(main_window_env) -> None:
    """初始化时排序下拉框默认为名称，方向按钮显示 ▲。"""
    window, _, _ = main_window_env
    from app import ui_constants as ui
    from app.file_list_model import SORT_NAME

    assert window._sort_field_combo.currentData() == SORT_NAME  # noqa: SLF001
    assert window._sort_dir_button.text() == ui.SORT_ASC_SYMBOL  # noqa: SLF001


def test_sort_field_combo_changes_model_sort(qapp, main_window_env) -> None:
    """下拉框切换排序字段后 FileListModel 同步。

    Stage 5 Task 2 验收修复（最终版）：仅用 activated 信号，程序化 setCurrentIndex
    不触发 activated，需手动调 _on_sort_field_activated 模拟用户交互。
    """
    window, _, _ = main_window_env
    from app.file_list_model import SORT_SIZE

    _select_root(qapp, window)
    qapp.processEvents()

    # 程序化 setCurrentIndex 不触发 activated，需手动调 handler
    idx = window._sort_field_combo.findData(SORT_SIZE)  # noqa: SLF001
    window._sort_field_combo.setCurrentIndex(idx)  # noqa: SLF001
    window._on_sort_field_activated(idx)  # noqa: SLF001
    qapp.processEvents()

    assert window._content_list_model.current_sort_key() == SORT_SIZE  # noqa: SLF001


def test_sort_direction_button_toggles(qapp, main_window_env) -> None:
    """方向按钮点击后翻转方向，文本在 ▲/▼ 间切换。"""
    window, _, _ = main_window_env
    from app import ui_constants as ui

    _select_root(qapp, window)
    qapp.processEvents()

    # 默认升序 ▲
    assert window._sort_dir_button.text() == ui.SORT_ASC_SYMBOL  # noqa: SLF001
    assert window._content_list_model.is_sort_ascending() is True  # noqa: SLF001

    # 点击 → 降序 ▼
    window._sort_dir_button.click()  # noqa: SLF001
    qapp.processEvents()
    assert window._sort_dir_button.text() == ui.SORT_DESC_SYMBOL  # noqa: SLF001
    assert window._content_list_model.is_sort_ascending() is False  # noqa: SLF001

    # 再点击 → 升序 ▲
    window._sort_dir_button.click()  # noqa: SLF001
    qapp.processEvents()
    assert window._sort_dir_button.text() == ui.SORT_ASC_SYMBOL  # noqa: SLF001
    assert window._content_list_model.is_sort_ascending() is True  # noqa: SLF001


def test_header_click_syncs_sort_controls(qapp, main_window_env) -> None:
    """点击列头排序后下拉框与方向按钮同步。"""
    window, _, _ = main_window_env
    from app.file_list_model import SORT_SIZE

    _select_root(qapp, window)
    qapp.processEvents()

    # 点击大小列头（列索引 2）
    window._on_content_header_clicked(2)  # noqa: SLF001
    qapp.processEvents()

    # 下拉框同步到大小
    assert window._sort_field_combo.currentData() == SORT_SIZE  # noqa: SLF001
    # 方向按钮默认升序 ▲
    from app import ui_constants as ui

    assert window._sort_dir_button.text() == ui.SORT_ASC_SYMBOL  # noqa: SLF001

    # 再次点击同列 → 降序，方向按钮显示 ▼
    window._on_content_header_clicked(2)  # noqa: SLF001
    qapp.processEvents()
    assert window._sort_dir_button.text() == ui.SORT_DESC_SYMBOL  # noqa: SLF001


def test_sort_field_combo_activated_on_same_item(qapp, main_window_env) -> None:
    """Stage 5 Task 2 验收修复（最终版）：选当前项不会重新触发排序。

    单 activated 信号方案下，"选当前项"无产品意义且 Qt 不会触发 activated
    （currentIndex 不变），此测试验证 handler 在被手动调用时仍能正常执行
    （幂等：相同 sort_key 调用不报错，方向保持）。
    """
    window, _, _ = main_window_env
    from app.file_list_model import SORT_NAME

    _select_root(qapp, window)
    qapp.processEvents()

    # 默认是名称升序
    name_idx = window._sort_field_combo.findData(SORT_NAME)  # noqa: SLF001
    assert window._sort_field_combo.currentIndex() == name_idx  # noqa: SLF001

    # 手动调 handler（模拟 activated 触发，currentIndex 已是 name_idx）
    # 验证幂等：不抛异常，sort_key 仍为 SORT_NAME，方向不变
    window._on_sort_field_activated(name_idx)  # noqa: SLF001
    qapp.processEvents()

    assert window._content_list_model.current_sort_key() == SORT_NAME  # noqa: SLF001
    assert window._content_list_model.is_sort_ascending() is True  # noqa: SLF001


def test_sort_field_combo_switch_all_fields(qapp, main_window_env) -> None:
    """Stage 5 Task 2 验收修复（最终版）：验证所有字段切换均一次生效。

    回归测试：确保单 activated 信号方案下，名称→类型→大小→时间→名称
    每次切换都立即生效（无"需两次点击"问题）。
    """
    window, _, _ = main_window_env
    from app.file_list_model import SORT_MODIFIED, SORT_NAME, SORT_SIZE, SORT_TYPE

    _select_root(qapp, window)
    qapp.processEvents()

    # 依次切换所有字段
    for sort_key in [SORT_TYPE, SORT_SIZE, SORT_MODIFIED, SORT_NAME]:
        idx = window._sort_field_combo.findData(sort_key)  # noqa: SLF001
        window._sort_field_combo.setCurrentIndex(idx)  # noqa: SLF001
        window._on_sort_field_activated(idx)  # noqa: SLF001
        qapp.processEvents()
        # 立即验证生效
        assert window._content_list_model.current_sort_key() == sort_key  # noqa: SLF001


def test_sort_direction_button_not_checkable(main_window_env) -> None:
    """Task 2 验收修复：方向按钮不使用 checkable（避免蓝色高亮）。"""
    window, _, _ = main_window_env
    assert window._sort_dir_button.isCheckable() is False  # noqa: SLF001
    assert window._sort_dir_button.isChecked() is False  # noqa: SLF001


def test_card_grid_size_set(main_window_env) -> None:
    """Task 2 验收修复：卡片视图 gridSize 已设置（非空）。"""
    window, _, _ = main_window_env
    grid = window._card_view.gridSize()  # noqa: SLF001
    assert grid is not None
    assert grid.width() > 0
    assert grid.height() > 0


def test_list_view_is_rubber_band_table_view(main_window_env) -> None:
    """Stage 5 Task 2 验收修复（决策 3A）：列表视图使用 _RubberBandTableView 支持框选。"""
    from app.main_window import _RubberBandTableView

    window, _, _ = main_window_env
    assert isinstance(window._content_view, _RubberBandTableView)  # noqa: SLF001


def test_card_view_rubber_band_visible(main_window_env) -> None:
    """Stage 5 Task 2 验收修复（决策 3A）：卡片视图显式启用 rubber band。"""
    window, _, _ = main_window_env
    assert window._card_view.isSelectionRectVisible() is True  # noqa: SLF001


# === Stage 5 Task 2：前进/后退目录导航 ===


def test_nav_buttons_disabled_initially(main_window_env) -> None:
    """初始状态无历史，前进/后退按钮均禁用。"""
    window, _, _ = main_window_env
    assert window._nav_back_button.isEnabled() is False  # noqa: SLF001
    assert window._nav_forward_button.isEnabled() is False  # noqa: SLF001


def test_nav_back_forward_navigates_history(qapp, main_window_env) -> None:
    """浏览多个目录后后退/前进可在历史间切换。"""
    window, _, root_dir = main_window_env

    # 选中根节点 → 记录根路径
    _select_root(qapp, window)
    qapp.processEvents()
    root_path = str(root_dir)
    assert window._current_nav_path == root_path  # noqa: SLF001
    assert window._nav_back_button.isEnabled() is False  # noqa: SLF001

    # 双击 armor 子目录进入
    armor_path = str(root_dir / "armor")
    idx_row = _find_entry_index(window, "armor")
    model_idx = window._content_list_model.index(idx_row, 0)  # noqa: SLF001
    window._on_entry_activated(model_idx)  # noqa: SLF001
    qapp.processEvents()

    # 后退按钮启用，前进禁用
    assert window._nav_back_button.isEnabled() is True  # noqa: SLF001
    assert window._nav_forward_button.isEnabled() is False  # noqa: SLF001
    assert window._current_nav_path == armor_path  # noqa: SLF001

    # 点击后退 → 回到根目录
    window._on_nav_back_clicked()  # noqa: SLF001
    qapp.processEvents()
    assert window._current_nav_path == root_path  # noqa: SLF001
    # 后退禁用，前进启用
    assert window._nav_back_button.isEnabled() is False  # noqa: SLF001
    assert window._nav_forward_button.isEnabled() is True  # noqa: SLF001

    # 点击前进 → 回到 armor
    window._on_nav_forward_clicked()  # noqa: SLF001
    qapp.processEvents()
    assert window._current_nav_path == armor_path  # noqa: SLF001
    assert window._nav_back_button.isEnabled() is True  # noqa: SLF001
    assert window._nav_forward_button.isEnabled() is False  # noqa: SLF001


def test_nav_forward_stack_cleared_on_new_navigation(qapp, main_window_env) -> None:
    """后退后再进入新目录，前进栈应清空（标准浏览器行为）。"""
    window, _, root_dir = main_window_env

    _select_root(qapp, window)
    qapp.processEvents()

    # 进入 armor
    idx_row = _find_entry_index(window, "armor")
    model_idx = window._content_list_model.index(idx_row, 0)  # noqa: SLF001
    window._on_entry_activated(model_idx)  # noqa: SLF001
    qapp.processEvents()

    # 后退到根目录
    window._on_nav_back_clicked()  # noqa: SLF001
    qapp.processEvents()
    assert window._nav_forward_button.isEnabled() is True  # noqa: SLF001

    # 进入中文文件夹（新导航，应清空前进栈）
    idx_row = _find_entry_index(window, "中文文件夹")
    model_idx = window._content_list_model.index(idx_row, 0)  # noqa: SLF001
    window._on_entry_activated(model_idx)  # noqa: SLF001
    qapp.processEvents()
    # 前进栈应清空
    assert window._nav_forward_stack == []  # noqa: SLF001
    assert window._nav_forward_button.isEnabled() is False  # noqa: SLF001
