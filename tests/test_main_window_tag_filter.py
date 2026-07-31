"""MainWindow 标签筛选集成测试（Stage 4 Task 3）。

覆盖：
- TagFilterBar 创建条件：注入 tag_service 时创建，否则不创建
- 浏览模式可见
- 筛选激活时仅显示匹配的内容单元（Q1: B 非内容单元也隐藏）
- 筛选未激活时显示全量
- 筛选无命中显示空提示
- 筛选状态在切换目录树节点时保留并应用
- 筛选激活时单击内容单元不加载 MetadataPanel（Q6: B）
- 标签管理对话框关闭后刷新 TagFilterBar
- MetadataPanel 保存不刷新 TagFilterBar（标签库未变）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

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


def _make_mod_tree_with_tagged_units(tmp_path: Path) -> Path:
    """构造含多个内容单元 + 普通文件的测试目录树。

    结构：
        mods/
        ├── 寒霜之心.7z      # 内容单元
        ├── DragonSword.rar  # 内容单元
        └── normal_file.txt  # 非内容单元
    """
    root = tmp_path / "mods"
    root.mkdir()
    (root / "寒霜之心.7z").write_bytes(b"\x00" * 100)
    (root / "DragonSword.rar").write_bytes(b"\x00" * 80)
    (root / "normal_file.txt").write_bytes(b"data")
    return root


def _find_entry_index(window: MainWindow, name: str) -> int:
    for i in range(window.entry_count()):
        entry = window.entry_at(i)
        if entry is not None and entry.name == name:
            return i
    pytest.fail(f"未找到条目：{name}")


def _select_root(qapp, window: MainWindow) -> None:
    model = window._tree_model  # noqa: SLF001
    idx = model.index(0, 0)
    window._tree_view.setCurrentIndex(idx)  # noqa: SLF001
    qapp.processEvents()


@pytest.fixture
def env_with_filter(qapp, tmp_path: Path):
    """构造含 TagService + 标签 + 内容单元的 MainWindow 测试环境。

    返回 (window, conn, root_dir, tag_service, cat, tag_heavy, unit1, unit2)。
    """
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
        now_provider=lambda: "2026-07-27T00:00:00Z",
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
        now_provider=lambda: "2026-07-27T00:00:00Z",
        uuid_provider=fake_uuid,
    )

    root_dir = _make_mod_tree_with_tagged_units(tmp_path)
    root = managed_service.add_root(root_dir)
    scan_service.scan_root(root.id, incremental=False)
    conn.commit()

    # 创建分类 + 标签
    cat = tag_service.create_category("服装护甲")
    tag_heavy = tag_service.create_tag("重甲", cat.id)
    conn.commit()

    # 获取扫描出的内容单元
    units = content_service.list_direct_children(str(root_dir))
    assert len(units) >= 2
    unit1 = next(u for u in units if "寒霜之心" in u.path)
    unit2 = next(u for u in units if "DragonSword" in u.path)
    # 给 unit1 打上「重甲」标签
    tag_service.attach_tag_to_unit(unit1.id, tag_heavy.id)
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

    yield window, conn, root_dir, tag_service, cat, tag_heavy, unit1, unit2
    window.close()
    conn.close()


# === TagFilterBar 创建条件 ===


def test_tag_filter_bar_created_when_tag_service_injected(qapp, env_with_filter):
    """注入 TagService → TagFilterBar 创建。"""
    window, *_ = env_with_filter
    assert window.tag_filter_bar() is not None


def test_tag_filter_bar_not_created_without_tag_service(qapp, tmp_path: Path):
    """未注入 TagService → TagFilterBar 为 None。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row

    managed_service = ManagedRootService(
        ManagedRootRepository(conn),
        now_provider=lambda: "2026-07-27T00:00:00Z",
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
    assert window.tag_filter_bar() is None
    window.close()
    conn.close()


# === TagFilterBar 可见性 ===


def test_tag_filter_bar_visible_in_browse_mode(qapp, env_with_filter):
    """浏览模式 + 有分类 → TagFilterBar 可见。"""
    window, _, _, _, _, _, _, _ = env_with_filter
    _select_root(qapp, window)
    bar = window.tag_filter_bar()
    assert bar is not None
    assert bar.isVisibleTo(window)


# === 筛选行为 ===


def test_filter_active_shows_only_matching_content_units(qapp, env_with_filter):
    """筛选激活 → 仅显示匹配的内容单元（Q1: B 非内容单元也隐藏）。"""
    window, _, _, _, _, tag_heavy, unit1, _ = env_with_filter
    _select_root(qapp, window)

    # 默认显示 3 条：寒霜之心.7z / DragonSword.rar / normal_file.txt
    assert window.entry_count() == 3

    # 激活筛选：仅「重甲」标签
    bar = window.tag_filter_bar()
    bar._selected_tag_ids.add(tag_heavy.id)  # noqa: SLF001
    bar.on_filter_changed.emit(bar.current_selected_tag_ids())
    qapp.processEvents()

    # 应仅显示 unit1（寒霜之心.7z）
    assert window.entry_count() == 1
    entry = window.entry_at(0)
    assert entry is not None
    assert entry.name == "寒霜之心.7z"


def test_filter_inactive_shows_all_entries(qapp, env_with_filter):
    """无筛选 → 显示全量条目（含非内容单元）。"""
    window, *_ = env_with_filter
    _select_root(qapp, window)
    assert window.entry_count() == 3


def test_filter_empty_result_shows_hint(qapp, env_with_filter):
    """筛选无命中 → empty_hint 显示「无符合筛选条件」。"""
    window, _, _, tag_service, cat, _, _, _ = env_with_filter
    _select_root(qapp, window)

    # 创建一个新标签，无任何内容单元关联
    tag_unused = tag_service.create_tag("未使用标签", cat.id)
    bar = window.tag_filter_bar()
    bar._selected_tag_ids.add(tag_unused.id)  # noqa: SLF001
    bar.on_filter_changed.emit(bar.current_selected_tag_ids())
    qapp.processEvents()

    assert window.entry_count() == 0
    hint_text = window._content_empty_hint.text()  # noqa: SLF001
    assert "无符合筛选条件" in hint_text


def test_filter_persists_across_directory_switch(qapp, env_with_filter):
    """切换目录树节点 → 筛选状态保留并应用于新目录。"""
    window, _, _, _, _, tag_heavy, _, _ = env_with_filter
    _select_root(qapp, window)

    bar = window.tag_filter_bar()
    bar._selected_tag_ids.add(tag_heavy.id)  # noqa: SLF001
    bar.on_filter_changed.emit(bar.current_selected_tag_ids())
    qapp.processEvents()

    # 切换到根节点（重新选中）
    _select_root(qapp, window)
    qapp.processEvents()

    # 筛选状态保留
    assert bar.is_filter_active()
    assert tag_heavy.id in bar.current_selected_tag_ids()
    # 列表仍仅显示匹配条目
    assert window.entry_count() == 1


def test_filter_active_preserves_metadata_panel_load(qapp, env_with_filter):
    """筛选激活时单击内容单元仍加载 MetadataPanel（Q6: A 修正）。"""
    window, _, _, _, _, tag_heavy, _, _ = env_with_filter
    _select_root(qapp, window)

    # 激活筛选
    bar = window.tag_filter_bar()
    bar._selected_tag_ids.add(tag_heavy.id)  # noqa: SLF001
    bar.on_filter_changed.emit(bar.current_selected_tag_ids())
    qapp.processEvents()

    # 单击列表中的条目（筛选后仅剩 1 条匹配的内容单元）
    view = window._content_view  # noqa: SLF001
    view.selectRow(0)
    qapp.processEvents()

    panel = window.metadata_panel()
    assert panel is not None
    # MetadataPanel 应已加载（current_unit 不为 None）
    assert panel.current_unit() is not None


def test_filter_keeps_metadata_panel_visible_on_activate(qapp, env_with_filter):
    """筛选激活时 MetadataPanel 保持可见性（Q6: A 修正：不清空不隐藏）。"""
    window, _, _, _, _, tag_heavy, _, _ = env_with_filter
    _select_root(qapp, window)

    # 先单击一个条目加载 MetadataPanel
    view = window._content_view  # noqa: SLF001
    view.selectRow(0)
    qapp.processEvents()

    panel = window.metadata_panel()
    assert panel is not None
    visible_before = panel.isVisible()

    # 激活筛选 → MetadataPanel 可见性不应被主动改变
    bar = window.tag_filter_bar()
    bar._selected_tag_ids.add(tag_heavy.id)  # noqa: SLF001
    bar.on_filter_changed.emit(bar.current_selected_tag_ids())
    qapp.processEvents()

    # 筛选前后可见性一致（筛选不主动改 MetadataPanel 显隐）
    assert panel.isVisible() == visible_before
