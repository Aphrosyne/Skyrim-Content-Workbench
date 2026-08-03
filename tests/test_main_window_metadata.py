"""MainWindow 元数据集成测试（Stage 4 Task 2）。

覆盖：
- MetadataPanel 创建条件：注入 tag_service 时创建，否则不创建
- 单击内容单元 → MetadataPanel 加载（spec §7.2 主要交互入口）
- 双击内容单元 → 同样加载（兼容行为，不应破坏）
- 单击非内容单元 → 清空元数据面板
- 保存元数据 → on_saved 信号 → 事务提交 + 状态栏提示
- 设置封面 → CoverPickerDialog 弹出 + 选定后立即保存（操作便捷性6）
- 批量打标签菜单：多选内容单元 → 右键显示菜单
- 批量打标签动作：弹 BatchTagDialog + 应用 → 提交

测试使用 tmp_path + init_db 构造真实 service。
QMessageBox / CoverPickerDialog / BatchTagDialog 通过 monkeypatch 替换 exec 避免阻塞。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QMenu  # noqa: E402

from app import ui_constants as ui  # noqa: E402
from app.main_window import MainWindow  # noqa: E402
from app.recent_tags import RecentTags  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.file_operation_service import FileOperationService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from application.tag_service import TagService  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.folder_cache_sync_helper import FolderCacheSyncHelper  # noqa: E402
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
from infrastructure.repositories.operation_history import (  # noqa: E402
    OperationHistoryRepository,
)
from infrastructure.repositories.tag import TagRepository  # noqa: E402
from infrastructure.repositories.tag_category import (  # noqa: E402
    TagCategoryRepository,
)


class _FakeAction:
    """模拟 QAction：提供菜单构建所需的属性/方法，供 FakeMenu.addAction 返回。"""

    def __init__(self, text: str = "") -> None:
        self._text = text
        self._tooltip: str | None = None

    def text(self) -> str:
        return self._text

    def setToolTip(self, tooltip: str) -> None:  # noqa: ANN001 (Qt 签名)
        self._tooltip = tooltip

    def setEnabled(self, enabled: bool) -> None:  # noqa: ANN001 (Qt 签名)
        pass

    def menu(self):
        """子菜单容器（本替身不支持，返回 None 即可）。"""
        return None

    @property
    def triggered(self):
        """信号对象（提供 connect no-op，供最近目标子菜单连接）。"""
        return _FakeSignal()


class _FakeSignal:
    """模拟 Qt Signal：connect no-op。"""

    def connect(self, slot) -> None:  # noqa: ANN001
        pass

    def setEnabled(self, enabled: bool) -> None:  # noqa: ANN001 (Qt 签名)
        pass


def _make_mod_tree_with_units(tmp_path: Path) -> Path:
    """构造含多个内容单元文件的测试目录树。

    结构：
        mods/
        ├── 护甲/
        │   ├── 寒霜之心.7z   # 内容单元
        │   ├── preview1.jpg  # 非内容单元
        │   ├── preview2.png   # 非内容单元
        │   └── notes.txt      # 非内容单元（非图片）
        └── Weapons/
            └── DragonSword.rar  # 内容单元
    """
    root = tmp_path / "mods"
    root.mkdir()

    armor = root / "护甲"
    armor.mkdir()
    (armor / "寒霜之心.7z").write_bytes(b"\x00" * 100)
    (armor / "preview1.jpg").write_bytes(b"\x00" * 50)
    (armor / "preview2.png").write_bytes(b"\x00" * 50)
    (armor / "notes.txt").write_bytes(b"hello")

    weapons = root / "Weapons"
    weapons.mkdir()
    (weapons / "DragonSword.rar").write_bytes(b"\x00" * 80)

    return root


def _find_entry_index(window: MainWindow, name: str) -> int:
    """在文件列表中查找指定名称条目的索引。"""
    for i in range(window.entry_count()):
        entry = window.entry_at(i)
        if entry is not None and entry.name == name:
            return i
    pytest.fail(f"未找到条目：{name}")


def _select_root(qapp, window: MainWindow) -> None:
    """选中目录树根节点并等待事件处理。"""
    model = window._tree_model  # noqa: SLF001
    idx = model.index(0, 0)
    window._tree_view.setCurrentIndex(idx)  # noqa: SLF001
    qapp.processEvents()


def _navigate_to_armor(qapp, window: MainWindow) -> None:
    """在目录树中选中"护甲"子目录。"""
    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)
    for i in range(model.rowCount(root_idx)):
        child_idx = model.index(i, 0, root_idx)
        name = model.data(child_idx, Qt.DisplayRole)
        if name and "护甲" in name:
            window._tree_view.setCurrentIndex(child_idx)  # noqa: SLF001
            qapp.processEvents()
            break


@pytest.fixture
def main_window_with_tags(qapp, tmp_path: Path):
    """构造含 TagService 注入的 MainWindow 测试环境。"""
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
        now_provider=lambda: "2026-07-19T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    tree_service = FolderTreeService(
        ManagedRootRepository(conn),
        FolderCacheRepository(conn),
    )
    content_service = ContentService(ContentUnitRepository(conn))
    tag_service = TagService(
        TagCategoryRepository(conn),
        TagRepository(conn),
        ContentUnitTagRepository(conn),
    )
    scan_service = ScanService(
        managed_root_repo=ManagedRootRepository(conn),
        folder_cache_repo=FolderCacheRepository(conn),
        content_unit_repo=ContentUnitRepository(conn),
        now_provider=lambda: "2026-07-19T00:00:00Z",
        uuid_provider=fake_uuid,
    )

    root_dir = _make_mod_tree_with_units(tmp_path)
    root = managed_service.add_root(root_dir)
    scan_service.scan_root(root.id, incremental=False)
    conn.commit()

    window = MainWindow(
        managed_service,
        tree_service,
        content_service,
        db_path,
        commit_callback=conn.commit,
        rollback_callback=conn.rollback,
        tag_service=tag_service,
    )
    yield window, conn, root_dir, tag_service
    window.close()
    conn.close()


# === MetadataPanel 创建条件 ===


def test_metadata_panel_created_when_tag_service_injected(qapp, main_window_with_tags):
    """注入 TagService → MetadataPanel 创建。"""
    window, _, _, _ = main_window_with_tags
    assert window.metadata_panel() is not None


def test_metadata_panel_not_created_without_tag_service(qapp, tmp_path: Path):
    """未注入 TagService → MetadataPanel 为 None。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row

    managed_service = ManagedRootService(
        ManagedRootRepository(conn),
        FolderCacheRepository(conn),
        ContentUnitRepository(conn),
        now_provider=lambda: "2026-07-19T00:00:00Z",
    )
    tree_service = FolderTreeService(
        ManagedRootRepository(conn),
        FolderCacheRepository(conn),
    )
    content_service = ContentService(ContentUnitRepository(conn))

    window = MainWindow(
        managed_service,
        tree_service,
        content_service,
        db_path,
        commit_callback=conn.commit,
    )
    assert window.metadata_panel() is None
    window.close()
    conn.close()


# === 初始状态：MetadataPanel 隐藏 ===


def test_metadata_panel_hidden_initially(qapp, main_window_with_tags):
    """初始状态：MetadataPanel 隐藏（无 unit 加载）。"""
    window, _, _, _ = main_window_with_tags
    panel = window.metadata_panel()
    assert panel is not None
    assert not panel.isVisible()


# === 加载内容单元 ===


def test_double_click_content_unit_loads_into_panel(qapp, main_window_with_tags):
    """双击内容单元 → MetadataPanel 加载 + 字段填充。"""
    window, _, _, _ = main_window_with_tags
    _select_root(qapp, window)
    _navigate_to_armor(qapp, window)

    # 双击寒霜之心.7z（内容单元）
    idx = _find_entry_index(window, "寒霜之心.7z")
    window._on_entry_activated(window._content_list_model.index(idx, 0))  # noqa: SLF001
    qapp.processEvents()

    panel = window.metadata_panel()
    assert panel is not None
    assert panel.current_unit() is not None
    assert panel.current_unit().title is None  # UI合理性13：扫描不再写 title
    assert panel.rename_text() == "寒霜之心.7z"  # 重命名栏显示真实文件名
    assert panel.is_form_enabled()


def test_double_click_non_content_unit_does_not_load(qapp, main_window_with_tags):
    """双击非内容单元 → MetadataPanel 不加载（保持初始状态）。"""
    window, _, _, _ = main_window_with_tags
    _select_root(qapp, window)
    _navigate_to_armor(qapp, window)

    # 双击 preview1.jpg（非内容单元）
    idx = _find_entry_index(window, "preview1.jpg")
    window._on_entry_activated(window._content_list_model.index(idx, 0))  # noqa: SLF001
    qapp.processEvents()

    panel = window.metadata_panel()
    assert panel is not None
    assert panel.current_unit() is None
    assert not panel.is_form_enabled()


def test_single_click_content_unit_loads_into_panel(qapp, main_window_with_tags):
    """单击内容单元 → MetadataPanel 加载（spec §7.2 主要交互入口）。

    2026-07-25 调整：用户反馈原双击为主要入口不符合产品交互，
    改为单击加载元数据；双击行为兼容保留。
    """
    window, _, _, _ = main_window_with_tags
    _select_root(qapp, window)
    _navigate_to_armor(qapp, window)

    # 单击寒霜之心.7z（内容单元）：通过 selectionModel 触发
    view = window._content_view  # noqa: SLF001
    idx = _find_entry_index(window, "寒霜之心.7z")
    view.selectRow(idx)
    qapp.processEvents()

    panel = window.metadata_panel()
    assert panel is not None
    assert panel.current_unit() is not None
    assert panel.current_unit().title is None  # UI合理性13：扫描不再写 title
    assert panel.rename_text() == "寒霜之心.7z"
    assert panel.is_form_enabled()


def test_single_click_non_content_unit_clears_panel(qapp, main_window_with_tags):
    """单击非内容单元 → MetadataPanel 清空（按设计清空避免误导）。"""
    window, _, _, _ = main_window_with_tags
    _select_root(qapp, window)
    _navigate_to_armor(qapp, window)

    # 先单击内容单元加载 panel
    view = window._content_view  # noqa: SLF001
    idx_unit = _find_entry_index(window, "寒霜之心.7z")
    view.selectRow(idx_unit)
    qapp.processEvents()
    panel = window.metadata_panel()
    assert panel is not None and panel.current_unit() is not None

    # 再单击 notes.txt（非内容单元、非图片）
    idx_txt = _find_entry_index(window, "notes.txt")
    view.selectRow(idx_txt)
    qapp.processEvents()

    assert panel.current_unit() is None
    assert not panel.is_form_enabled()


def test_single_click_image_file_shows_preview(qapp, main_window_with_tags):
    """操作合理性2：单击非内容单元图片文件 → 元数据面板进入图片预览模式。"""
    window, _, _, _ = main_window_with_tags
    _select_root(qapp, window)
    _navigate_to_armor(qapp, window)

    view = window._content_view  # noqa: SLF001
    idx = _find_entry_index(window, "preview1.jpg")
    view.selectRow(idx)
    qapp.processEvents()

    panel = window.metadata_panel()
    assert panel is not None
    assert panel.is_image_preview_visible()
    assert panel.current_unit() is None
    assert not panel.is_form_enabled()
    assert panel.preview_name_text() == "preview1.jpg"


def test_select_non_image_after_image_preview_resets(qapp, main_window_with_tags):
    """操作合理性2：图片预览后再选中非图片文件 → 退出预览并清空面板。"""
    window, _, _, _ = main_window_with_tags
    _select_root(qapp, window)
    _navigate_to_armor(qapp, window)

    view = window._content_view  # noqa: SLF001
    idx_img = _find_entry_index(window, "preview1.jpg")
    view.selectRow(idx_img)
    qapp.processEvents()
    panel = window.metadata_panel()
    assert panel.is_image_preview_visible()

    idx_txt = _find_entry_index(window, "notes.txt")
    view.selectRow(idx_txt)
    qapp.processEvents()

    assert not panel.is_image_preview_visible()
    assert panel.current_unit() is None


# === 保存元数据 ===


def test_save_metadata_commits_and_shows_status(qapp, main_window_with_tags):
    """编辑备注 + 保存 → 事务提交 + 状态栏显示「元数据已保存」（title 不再写）。"""
    window, conn, _, _ = main_window_with_tags
    _select_root(qapp, window)
    _navigate_to_armor(qapp, window)

    # 双击寒霜之心.7z
    idx = _find_entry_index(window, "寒霜之心.7z")
    window._on_entry_activated(window._content_list_model.index(idx, 0))  # noqa: SLF001
    qapp.processEvents()

    panel = window.metadata_panel()
    assert panel is not None

    # 修改备注
    panel._notes_edit.setPlainText("新备注")  # noqa: SLF001
    panel.click_save_button()
    qapp.processEvents()

    # 状态栏应有提示
    assert "已保存" in window.statusBar().currentMessage()

    # 数据库中的备注应已更新，title 保持 None
    unit_id = panel.current_unit().id
    row = conn.execute("SELECT title, notes FROM content_unit WHERE id = ?", (unit_id,)).fetchone()
    assert row["title"] is None
    assert row["notes"] == "新备注"


def test_metadata_rename_request_renames_file(qapp, main_window_with_tags):
    """UI合理性13：面板重命名栏回车 → 真实文件重命名 + DB 路径更新 + 面板刷新。"""
    window, conn, _, _ = main_window_with_tags
    _select_root(qapp, window)
    _navigate_to_armor(qapp, window)

    idx = _find_entry_index(window, "寒霜之心.7z")
    window._on_entry_activated(window._content_list_model.index(idx, 0))  # noqa: SLF001
    qapp.processEvents()

    panel = window.metadata_panel()
    assert panel is not None
    unit = panel.current_unit()
    assert unit is not None
    old_path = Path(unit.path)

    # 注入文件操作服务（fixture 未注入，重命名走 FileOperationService 链路）
    window._file_operation_service = FileOperationService(  # noqa: SLF001
        OperationHistoryRepository(conn),
        folder_cache_helper=FolderCacheSyncHelper(FolderCacheRepository(conn)),
        content_unit_repo=ContentUnitRepository(conn),
    )

    # 模拟重命名栏回车（信号链路：panel → MetadataView → MainWindow）
    window._metadata_view.rename_requested.emit(unit.id, "新名字.7z")  # noqa: SLF001
    qapp.processEvents()

    new_path = old_path.parent / "新名字.7z"
    assert new_path.is_file()
    assert not old_path.exists()
    updated = window._content_service.get_by_id(unit.id)  # noqa: SLF001
    assert updated is not None
    assert updated.path == str(new_path)
    assert panel.rename_text() == "新名字.7z"
    assert "已重命名" in window.statusBar().currentMessage()
    # 操作历史已记录（undo 可用）
    rows = conn.execute("SELECT operation_type FROM operation_history").fetchall()
    assert any(r["operation_type"] == "rename" for r in rows)


# === 设置封面 ===


def test_pick_cover_button_launches_dialog(qapp, main_window_with_tags, monkeypatch):
    """点击设置封面 → 弹出对话框；确定后立即保存到数据库（操作便捷性6）。"""
    window, conn, root_dir, _ = main_window_with_tags

    # 标记"护甲"目录为内容单元（目录类型，包含图片候选 preview1.jpg / preview2.png）
    armor_dir = root_dir / "护甲"
    content_service = window._content_service  # noqa: SLF001
    unit = content_service.mark_as_content_unit(armor_dir)
    conn.commit()
    assert unit.cover_path == "preview1.jpg"  # 标记时自动录入第一张

    # 直接加载到 MetadataPanel（避免复杂的 UI 导航）
    panel = window.metadata_panel()
    assert panel is not None
    panel.load_unit(unit)
    qapp.processEvents()

    # Mock CoverPickerDialog.exec 返回 Accepted
    dialog_instances: list = []

    def fake_exec(self):
        dialog_instances.append(self)
        return 1  # QDialog.Accepted

    monkeypatch.setattr("app.cover_picker_dialog.QDialog.exec", fake_exec)
    # 固定对话框选择 preview2.png（覆盖自动选中的第一张）
    monkeypatch.setattr(
        "app.cover_picker_dialog.CoverPickerDialog.selected_relative_path",
        lambda self: "preview2.png",
    )

    panel.click_pick_cover_button()
    qapp.processEvents()

    # 应该弹出了 dialog
    assert len(dialog_instances) == 1
    # 操作便捷性6：确定后立即落库，无需再点「保存」
    updated = content_service.get_by_id(unit.id)
    assert updated is not None
    assert updated.cover_path == "preview2.png"
    assert panel.cover_path_text() == "preview2.png"
    assert window.statusBar().currentMessage() == ui.METADATA_PANEL_COVER_SAVED


def test_pick_cover_no_images_shows_information(qapp, main_window_with_tags, monkeypatch):
    """内容单元目录下无图片 → 弹 QMessageBox.information 提示。"""
    window, conn, root_dir, _ = main_window_with_tags

    # 创建一个无图片的目录并标记为内容单元
    empty_dir = root_dir / "EmptyMod"
    empty_dir.mkdir()
    (empty_dir / "readme.txt").write_text("data", encoding="utf-8")
    content_service = window._content_service  # noqa: SLF001
    unit = content_service.mark_as_content_unit(empty_dir)
    conn.commit()

    panel = window.metadata_panel()
    assert panel is not None
    panel.load_unit(unit)
    qapp.processEvents()

    info_calls: list = []
    monkeypatch.setattr(
        "app.main_window.QMessageBox.information",
        lambda *a, **kw: info_calls.append(a),
    )
    panel.click_pick_cover_button()
    qapp.processEvents()

    assert len(info_calls) == 1


# === 批量打标签菜单 ===


def test_batch_tag_menu_appears_for_multi_selection(qapp, main_window_with_tags):
    """多选内容单元 → 右键菜单出现「批量打标签」。"""
    window, _, _, _ = main_window_with_tags
    _select_root(qapp, window)
    _navigate_to_armor(qapp, window)

    # 选中所有条目
    view = window._content_view  # noqa: SLF001
    view.selectAll()
    qapp.processEvents()

    # Mock menu exec 返回 None（不点击任何项，仅验证菜单内容）
    menu_items: list[str] = []

    class FakeMenu:
        def __init__(self, *args, **kwargs):
            self._actions = []
            self._title = args[0] if args else ""

        def addAction(self, label):
            act = _FakeAction(label)
            self._actions.append(act)
            return act

        def actions(self):
            return list(self._actions)

        def insertMenu(self, before_action, submenu):
            """在指定 action 前插入子菜单（记录到 actions，供最近目标测试）。"""
            idx = self._actions.index(before_action)
            self._actions.insert(idx, _FakeAction(f"<submenu:{submenu._title}>"))

        def addMenu(self, submenu):
            self._actions.append(_FakeAction(f"<submenu:{submenu._title}>"))

        def exec(self, *args, **kwargs):
            menu_items.extend(a.text() for a in self._actions)
            return None

    import app.main_window as mw_module

    monkeypatch_menu = FakeMenu
    original_menu = mw_module.QMenu
    mw_module.QMenu = monkeypatch_menu  # noqa: SLF001
    try:
        window._on_content_context_menu(view.viewport().rect().center())  # noqa: SLF001
    finally:
        mw_module.QMenu = original_menu  # noqa: SLF001

    assert "批量打标签" in menu_items


def test_batch_tag_menu_not_appears_for_single_selection(qapp, main_window_with_tags):
    """单选 → 右键菜单不出现「批量打标签」。"""
    window, _, _, _ = main_window_with_tags
    _select_root(qapp, window)
    _navigate_to_armor(qapp, window)

    # 选中一个条目
    view = window._content_view  # noqa: SLF001
    view.selectRow(0)
    qapp.processEvents()

    menu_items: list[str] = []

    class FakeMenu:
        def __init__(self, *args, **kwargs):
            self._actions = []
            self._title = args[0] if args else ""

        def addAction(self, label):
            act = _FakeAction(label)
            self._actions.append(act)
            return act

        def actions(self):
            return list(self._actions)

        def insertMenu(self, before_action, submenu):
            idx = self._actions.index(before_action)
            self._actions.insert(idx, _FakeAction(f"<submenu:{submenu._title}>"))

        def addMenu(self, submenu):
            self._actions.append(_FakeAction(f"<submenu:{submenu._title}>"))

        def exec(self, *args, **kwargs):
            menu_items.extend(a.text() for a in self._actions)
            return None

    import app.main_window as mw_module

    original_menu = mw_module.QMenu
    mw_module.QMenu = FakeMenu  # noqa: SLF001
    try:
        window._on_content_context_menu(view.viewport().rect().center())  # noqa: SLF001
    finally:
        mw_module.QMenu = original_menu  # noqa: SLF001

    assert "批量打标签" not in menu_items


def test_insert_recent_tag_submenu(qapp, main_window_with_tags, tmp_path):
    """UI合理性8：右键「添加最近标签 ▸」子菜单按最近顺序列出标签。"""
    window, _, _, tag_service = main_window_with_tags
    # 隔离最近标签（避免污染真实 QSettings）
    window._recent_tags = RecentTags(  # noqa: SLF001
        QSettings(str(tmp_path / "recent_tags.ini"), QSettings.Format.IniFormat)
    )
    cat = tag_service.create_category("分类A", color_hue=10)
    tag = tag_service.create_tag("测试标签A", cat.id)
    window._recent_tags.record(tag.id)  # noqa: SLF001

    menu = QMenu()
    window._insert_recent_tag_submenu(menu, "unit-id")  # noqa: SLF001

    actions = menu.actions()
    assert len(actions) == 1
    submenu = actions[0].menu()
    assert submenu is not None
    assert submenu.title() == ui.MENU_ADD_RECENT_TAG
    assert [a.text() for a in submenu.actions()] == ["测试标签A"]


def test_on_add_recent_tag_attaches_and_records(qapp, main_window_with_tags, tmp_path):
    """UI合理性8：右键「添加最近标签」点击 → 立即 attach + 提交 + 记录最近。"""
    window, conn, root_dir, tag_service = main_window_with_tags
    window._recent_tags = RecentTags(  # noqa: SLF001
        QSettings(str(tmp_path / "recent_tags.ini"), QSettings.Format.IniFormat)
    )
    cat = tag_service.create_category("分类B", color_hue=20)
    tag = tag_service.create_tag("测试标签B", cat.id)

    unit = window._content_service.get_by_path(  # noqa: SLF001
        str(root_dir / "护甲" / "寒霜之心.7z")
    )
    assert unit is not None

    window._on_add_recent_tag(unit.id, tag.id)  # noqa: SLF001

    rows = conn.execute(
        "SELECT COUNT(*) FROM content_unit_tag WHERE content_unit_id = ? AND tag_id = ?",
        (unit.id, tag.id),
    ).fetchone()
    assert rows[0] == 1
    assert window._recent_tags.list_recent() == [tag.id]  # noqa: SLF001


def test_batch_tag_action_commits_and_attaches(qapp, main_window_with_tags, monkeypatch):
    """点击批量打标签 → BatchTagDialog 弹出 → 添加标签 → 提交到数据库。"""
    window, conn, _, tag_service = main_window_with_tags
    # 创建一个标签用于测试
    cat = tag_service.create_category("服装护甲", color_hue=210)
    created_tag = tag_service.create_tag("重甲", cat.id)
    conn.commit()

    _select_root(qapp, window)
    _navigate_to_armor(qapp, window)

    # 收集所有内容单元条目
    entries = []
    for i in range(window.entry_count()):
        e = window.entry_at(i)
        if e is not None and e.content_unit is not None:
            entries.append(e)
    assert len(entries) > 0

    # 直接为每个内容单元预关联标签，验证 _on_batch_tag 能正确调用 service
    # Mock BatchTagDialog：构造时记录参数，exec 返回 Accepted
    dialog_calls: list = []

    class FakeDialog:
        def __init__(self, tag_service, content_unit_ids, parent=None):
            self._tag_service = tag_service
            self._content_unit_ids = content_unit_ids
            dialog_calls.append(content_unit_ids)
            # 真实地添加标签到所有内容单元（模拟用户操作）
            tag_service.batch_attach_tags(content_unit_ids, created_tag.id)

        def exec(self):
            return 1  # QDialog.Accepted

        def result_messages(self):
            return ["已为 N 个内容单元添加标签「重甲」"]

    monkeypatch.setattr("app.main_window.BatchTagDialog", FakeDialog)

    window._on_batch_tag(entries)  # noqa: SLF001
    qapp.processEvents()

    # 验证 dialog 被构造（含 content_unit_ids）
    assert len(dialog_calls) == 1
    assert len(dialog_calls[0]) == len(entries)

    # 验证所有内容单元都关联了标签「重甲」
    for entry in entries:
        tags = tag_service.list_tags_of_content_unit(entry.content_unit.id)
        flat = [t.name for _, tags_in_cat in tags for t in tags_in_cat]
        assert "重甲" in flat


# === 兼容性测试 ===


def test_metadata_full_text_backward_compat(qapp, main_window_with_tags):
    """加载内容单元后 metadata_full_text() 仍返回多行文本（兼容旧测试）。"""
    window, _, _, _ = main_window_with_tags
    _select_root(qapp, window)
    _navigate_to_armor(qapp, window)

    idx = _find_entry_index(window, "寒霜之心.7z")
    window._on_entry_activated(window._content_list_model.index(idx, 0))  # noqa: SLF001
    qapp.processEvents()

    text = window.metadata_full_text()
    assert "标题" not in text  # UI合理性13：多行文本不再含标题行
    assert "路径" in text
    assert "寒霜之心.7z" in text
