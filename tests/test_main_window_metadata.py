"""MainWindow 元数据集成测试（Stage 4 Task 2）。

覆盖：
- MetadataPanel 创建条件：注入 tag_service 时创建，否则不创建
- 单击内容单元 → MetadataPanel 加载（spec §7.2 主要交互入口）
- 双击内容单元 → 同样加载（兼容行为，不应破坏）
- 单击非内容单元 → 清空元数据面板
- 保存元数据 → on_saved 信号 → 事务提交 + 状态栏提示
- 设置封面 → CoverPickerDialog 弹出 + 选定后更新表单
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

from PySide6.QtCore import Qt  # noqa: E402

from app.main_window import MainWindow  # noqa: E402
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


class _FakeAction:
    """模拟 QAction：仅提供 setEnabled no-op，供 FakeMenu.addAction 返回。"""

    def setEnabled(self, enabled: bool) -> None:  # noqa: ANN001 (Qt 签名)
        pass


def _make_mod_tree_with_units(tmp_path: Path) -> Path:
    """构造含多个内容单元文件的测试目录树。

    结构：
        mods/
        ├── 护甲/
        │   ├── 寒霜之心.7z   # 内容单元
        │   ├── preview1.jpg  # 非内容单元
        │   └── preview2.png   # 非内容单元
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
    assert panel.current_unit().title == "寒霜之心.7z"
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
    assert panel.current_unit().title == "寒霜之心.7z"
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

    # 再单击 preview1.jpg（非内容单元）
    idx_preview = _find_entry_index(window, "preview1.jpg")
    view.selectRow(idx_preview)
    qapp.processEvents()

    assert panel.current_unit() is None
    assert not panel.is_form_enabled()


# === 保存元数据 ===


def test_save_metadata_commits_and_shows_status(qapp, main_window_with_tags):
    """编辑标题 + 保存 → 事务提交 + 状态栏显示「元数据已保存」。"""
    window, conn, _, _ = main_window_with_tags
    _select_root(qapp, window)
    _navigate_to_armor(qapp, window)

    # 双击寒霜之心.7z
    idx = _find_entry_index(window, "寒霜之心.7z")
    window._on_entry_activated(window._content_list_model.index(idx, 0))  # noqa: SLF001
    qapp.processEvents()

    panel = window.metadata_panel()
    assert panel is not None

    # 修改标题
    panel._title_edit.setText("新标题")  # noqa: SLF001
    panel.click_save_button()
    qapp.processEvents()

    # 状态栏应有提示
    assert "已保存" in window.statusBar().currentMessage()

    # 数据库中的标题应已更新
    unit_id = panel.current_unit().id
    row = conn.execute("SELECT title FROM content_unit WHERE id = ?", (unit_id,)).fetchone()
    assert row["title"] == "新标题"


# === 设置封面 ===


def test_pick_cover_button_launches_dialog(qapp, main_window_with_tags, monkeypatch):
    """点击设置封面按钮 → 弹出 CoverPickerDialog（目录类型内容单元 + 含图片）。"""
    window, conn, root_dir, _ = main_window_with_tags

    # 标记"护甲"目录为内容单元（目录类型，包含图片候选 preview1.jpg / preview2.png）
    armor_dir = root_dir / "护甲"
    content_service = window._content_service  # noqa: SLF001
    unit = content_service.mark_as_content_unit(armor_dir)
    conn.commit()

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

    panel.click_pick_cover_button()
    qapp.processEvents()

    # 应该弹出了 dialog
    assert len(dialog_instances) == 1


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

        def addAction(self, label):
            self._actions.append(label)
            return _FakeAction()

        def exec(self, *args, **kwargs):
            menu_items.extend(self._actions)
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

        def addAction(self, label):
            self._actions.append(label)
            return _FakeAction()

        def exec(self, *args, **kwargs):
            menu_items.extend(self._actions)
            return None

    import app.main_window as mw_module

    original_menu = mw_module.QMenu
    mw_module.QMenu = FakeMenu  # noqa: SLF001
    try:
        window._on_content_context_menu(view.viewport().rect().center())  # noqa: SLF001
    finally:
        mw_module.QMenu = original_menu  # noqa: SLF001

    assert "批量打标签" not in menu_items


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
    assert "标题" in text
    assert "寒霜之心.7z" in text
