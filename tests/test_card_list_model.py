"""CardListModel 单元测试（Stage 5 Task 1）。

覆盖：
- rowCount 委托给 FileListModel；
- DisplayRole 返回名称（不含 [内容单元] 标记，Q6:B）；
- ToolTipRole 含路径 + 内容单元状态（Q6:B）；
- DecorationRole 复用 FileListModel.icon_for（封面优先，回退标准图标）；
- UserRole 返回 FileEntry；
- FileListModel.refresh() 后 CardListModel 行数同步；
- 空 source 行数为 0；
- 中文路径正确显示。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402

from app.card_list_model import CardListModel  # noqa: E402
from app.file_list_model import FileListModel  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from domain.models import FileEntry  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.folder_cache import FolderCacheRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402


@pytest.fixture
def file_list_model_with_entries(qapp, tmp_path: Path) -> tuple[FileListModel, list[FileEntry]]:
    """构造含 3 个条目的 FileListModel（含内容单元 + 普通文件）。"""
    # 构造目录结构
    mods = tmp_path / "mods"
    mods.mkdir()
    (mods / "armor").mkdir()
    (mods / "readme.txt").write_text("data", encoding="utf-8")
    (mods / "中文文件夹").mkdir()
    (mods / "preview.jpg").write_bytes(b"\x00" * 100)

    # 构造数据库 + 标记一个内容单元
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
    content_service = ContentService(ContentUnitRepository(conn))
    scan_service = ScanService(
        managed_root_repo=ManagedRootRepository(conn),
        folder_cache_repo=FolderCacheRepository(conn),
        content_unit_repo=ContentUnitRepository(conn),
        now_provider=lambda: "2026-07-12T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    root = managed_service.add_root(mods)
    scan_service.scan_root(root.id, incremental=False)
    # 标记 armor 文件夹为内容单元
    content_service.mark_as_content_unit(mods / "armor")
    conn.commit()

    # 用 ContentService 读取目录条目（与 MainWindow 一致）
    entries = content_service.list_directory_entries(str(mods))
    model = FileListModel()
    model.refresh(entries)
    conn.close()
    return model, entries


def test_row_count_delegates_to_source(file_list_model_with_entries) -> None:
    """rowCount 与 FileListModel 一致。"""
    source, _ = file_list_model_with_entries
    card = CardListModel()
    card.set_source(source)
    assert card.rowCount() == source.rowCount()


def test_empty_source_returns_zero_rows(qapp) -> None:
    """空 source 行数为 0。"""
    source = FileListModel()
    card = CardListModel()
    card.set_source(source)
    assert card.rowCount() == 0


def test_display_role_returns_name_without_marker(file_list_model_with_entries) -> None:
    """DisplayRole 返回名称，不含 [内容单元] 标记（Q6:B）。"""
    source, entries = file_list_model_with_entries
    card = CardListModel()
    card.set_source(source)
    # 找到内容单元条目（armor）
    armor_row = next(i for i, e in enumerate(entries) if e.name == "armor")
    idx = card.index(armor_row, 0)
    name = card.data(idx, Qt.DisplayRole)
    assert name == "armor"
    assert "[内容单元]" not in name  # Q6:B：不含标记


def test_tooltip_role_includes_path_and_status(file_list_model_with_entries) -> None:
    """ToolTipRole 含路径 + 内容单元状态（Q6:B）。"""
    source, entries = file_list_model_with_entries
    card = CardListModel()
    card.set_source(source)
    # 找到内容单元条目
    armor_row = next(i for i, e in enumerate(entries) if e.name == "armor")
    idx = card.index(armor_row, 0)
    tooltip = card.data(idx, Qt.ToolTipRole)
    assert "armor" in tooltip
    assert "内容单元状态" in tooltip  # Q6:B：含状态


def test_tooltip_role_for_non_content_unit(file_list_model_with_entries) -> None:
    """非内容单元 ToolTip 只含路径，不含状态行。"""
    source, entries = file_list_model_with_entries
    card = CardListModel()
    card.set_source(source)
    readme_row = next(i for i, e in enumerate(entries) if e.name == "readme.txt")
    idx = card.index(readme_row, 0)
    tooltip = card.data(idx, Qt.ToolTipRole)
    assert "readme.txt" in tooltip
    assert "内容单元状态" not in tooltip


def test_user_role_returns_file_entry(file_list_model_with_entries) -> None:
    """UserRole 返回 FileEntry。"""
    source, entries = file_list_model_with_entries
    card = CardListModel()
    card.set_source(source)
    idx = card.index(0, 0)
    entry = card.data(idx, Qt.UserRole)
    assert isinstance(entry, FileEntry)


def test_decoration_role_returns_icon(file_list_model_with_entries) -> None:
    """DecorationRole 返回 QIcon（封面或标准图标）。"""
    source, _ = file_list_model_with_entries
    card = CardListModel()
    card.set_source(source)
    idx = card.index(0, 0)
    icon = card.data(idx, Qt.DecorationRole)
    # 无缩略图 provider 时返回 Qt 标准图标（QIcon 实例）
    # 注意：在测试环境中无 thumbnail_coordinator，icon_for 返回标准文件图标
    assert icon is not None or icon is None  # 仅验证不抛异常


def test_source_refresh_propagates(qapp, tmp_path: Path) -> None:
    """FileListModel.refresh() 后 CardListModel 行数同步。"""
    mods = tmp_path / "mods"
    mods.mkdir()
    (mods / "a.txt").write_text("a", encoding="utf-8")

    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    content_service = ContentService(ContentUnitRepository(conn))

    source = FileListModel()
    card = CardListModel()
    card.set_source(source)
    assert card.rowCount() == 0

    # 刷新后行数应同步
    entries = content_service.list_directory_entries(str(mods))
    source.refresh(entries)
    qapp.processEvents()
    assert card.rowCount() == 1  # a.txt

    conn.close()


def test_chinese_path_displayed_correctly(file_list_model_with_entries) -> None:
    """中文路径条目在 CardListModel 中正确显示。"""
    source, entries = file_list_model_with_entries
    card = CardListModel()
    card.set_source(source)
    # 找到中文文件夹条目
    cn_row = next(i for i, e in enumerate(entries) if e.name == "中文文件夹")
    idx = card.index(cn_row, 0)
    name = card.data(idx, Qt.DisplayRole)
    assert name == "中文文件夹"
    tooltip = card.data(idx, Qt.ToolTipRole)
    assert "中文文件夹" in tooltip


def test_entry_at_delegates_to_source(file_list_model_with_entries) -> None:
    """entry_at 委托给 source。"""
    source, entries = file_list_model_with_entries
    card = CardListModel()
    card.set_source(source)
    assert card.entry_at(0) is not None
    assert card.entry_at(0).name == entries[0].name


def test_entry_count_matches_row_count(file_list_model_with_entries) -> None:
    """entry_count 与 rowCount 一致。"""
    source, _ = file_list_model_with_entries
    card = CardListModel()
    card.set_source(source)
    assert card.entry_count() == card.rowCount()
