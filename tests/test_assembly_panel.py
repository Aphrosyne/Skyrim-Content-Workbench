"""AssemblyPanel 单元测试（阶段 3 Task 4）。

覆盖：
- AssemblyListModel：refresh / entry_at / entry_count / data roles
- AssemblyPanel：bind_mod_group / refresh_current / current_unit / 关闭按钮回调
- 右键菜单 / 移除按钮回调路径（通过回调注入验证）

注（2026-07-17 调整）：拖拽方案已取消，相关测试已移除。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QModelIndex, Qt  # noqa: E402

from app.assembly_panel import AssemblyListModel, AssemblyPanel  # noqa: E402
from application.assembly_service import AssemblyService  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from domain.models import ContentUnit, FileEntry  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.file_operation_service import FileOperationService  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.folder_cache import FolderCacheRepository  # noqa: E402
from infrastructure.repositories.operation_history import (  # noqa: E402
    OperationHistoryRepository,
)

# === Fixture ===


@pytest.fixture
def assembly_service(tmp_path: Path) -> tuple[AssemblyService, sqlite3.Connection]:
    """构造 AssemblyService + 内存数据库连接。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    file_op = FileOperationService(OperationHistoryRepository(conn))
    folder_cache_repo = FolderCacheRepository(conn)
    service = AssemblyService(file_op, ContentUnitRepository(conn), folder_cache_repo)
    yield service, conn
    conn.close()


@pytest.fixture
def mod_group_env(
    assembly_service: tuple[AssemblyService, sqlite3.Connection], tmp_path: Path
) -> tuple[AssemblyService, ContentUnit, Path, Path, sqlite3.Connection]:
    """构造一个 Mod 组文件夹 + 已标记的 ContentUnit。

    结构：
        tmp_path/Stash/MyMod/  ← Mod 组文件夹（已标记 ContentUnit）
                /MyMod/source.7z  ← Mod 组内的文件
                /extra.jpg  ← 暂存区内的图片文件（用于拖入测试）
    """
    service, conn = assembly_service
    staging = tmp_path / "Stash"
    staging.mkdir()
    mod_folder = staging / "MyMod"
    mod_folder.mkdir()
    (mod_folder / "source.7z").write_bytes(b"\x00" * 100)
    (staging / "extra.jpg").write_bytes(b"\x00" * 50)

    # 标记 Mod 组文件夹为 ContentUnit
    content_service = ContentService(ContentUnitRepository(conn))
    unit = content_service.mark_as_content_unit(mod_folder)
    conn.commit()

    yield service, unit, mod_folder, staging, conn


# === AssemblyListModel ===


def test_list_model_initial_empty(qapp) -> None:
    """新建 model 应为空。"""
    model = AssemblyListModel()
    assert model.entry_count() == 0
    assert model.entry_at(0) is None


def test_list_model_refresh_sets_entries(qapp, mod_group_env) -> None:
    """refresh 后应填充 entries。"""
    service, unit, mod_folder, _, _ = mod_group_env
    entries = service.list_mod_group_files(unit.id)
    assert len(entries) == 1

    model = AssemblyListModel()
    model.refresh(entries)
    assert model.entry_count() == 1
    entry = model.entry_at(0)
    assert entry is not None
    assert entry.name == "source.7z"


def test_list_model_data_display_role(qapp, mod_group_env) -> None:
    """DisplayRole 返回文件名。"""
    service, unit, _, _, _ = mod_group_env
    entries = service.list_mod_group_files(unit.id)
    model = AssemblyListModel()
    model.refresh(entries)

    idx = model.index(0, 0)
    assert idx.isValid()
    assert model.data(idx, Qt.DisplayRole) == "source.7z"


def test_list_model_data_tooltip_role(qapp, mod_group_env) -> None:
    """ToolTipRole 返回完整路径。"""
    service, unit, mod_folder, _, _ = mod_group_env
    entries = service.list_mod_group_files(unit.id)
    model = AssemblyListModel()
    model.refresh(entries)

    idx = model.index(0, 0)
    tooltip = model.data(idx, Qt.ToolTipRole)
    assert tooltip is not None
    assert "source.7z" in tooltip


def test_list_model_data_user_role_returns_entry(qapp, mod_group_env) -> None:
    """UserRole 返回 FileEntry 对象。"""
    service, unit, _, _, _ = mod_group_env
    entries = service.list_mod_group_files(unit.id)
    model = AssemblyListModel()
    model.refresh(entries)

    idx = model.index(0, 0)
    entry = model.data(idx, Qt.UserRole)
    assert isinstance(entry, FileEntry)
    assert entry.name == "source.7z"


def test_list_model_refresh_clears_previous(qapp, mod_group_env) -> None:
    """再次 refresh 应清空旧条目。"""
    service, unit, _, _, _ = mod_group_env
    entries = service.list_mod_group_files(unit.id)
    model = AssemblyListModel()
    model.refresh(entries)
    assert model.entry_count() == 1

    model.refresh([])
    assert model.entry_count() == 0


# === AssemblyPanel ===


def test_panel_initial_state(qapp, assembly_service) -> None:
    """新建装配面板：无绑定 + 移除按钮禁用。"""
    service, _ = assembly_service
    panel = AssemblyPanel(service)
    assert panel.current_unit() is None
    assert panel.current_unit_id() is None
    assert panel.entry_count() == 0
    assert not panel._remove_button.isEnabled()  # noqa: SLF001


def test_panel_bind_mod_group_loads_files(qapp, mod_group_env) -> None:
    """bind_mod_group 后面板加载 Mod 组文件夹内容。"""
    service, unit, mod_folder, staging, _ = mod_group_env
    panel = AssemblyPanel(service)
    panel.bind_mod_group(unit, staging)

    assert panel.current_unit() is not None
    assert panel.current_unit_id() == unit.id
    assert panel.entry_count() == 1
    entry = panel.entry_at(0)
    assert entry is not None
    assert entry.name == "source.7z"
    assert panel._remove_button.isEnabled()  # noqa: SLF001


def test_panel_bind_none_clears(qapp, mod_group_env) -> None:
    """bind_mod_group(None) 清空面板。"""
    service, unit, _, staging, _ = mod_group_env
    panel = AssemblyPanel(service)
    panel.bind_mod_group(unit, staging)
    assert panel.entry_count() == 1

    panel.bind_mod_group(None, None)
    assert panel.current_unit() is None
    assert panel.entry_count() == 0
    assert not panel._remove_button.isEnabled()  # noqa: SLF001


def test_panel_refresh_current(qapp, mod_group_env) -> None:
    """refresh_current 重新加载文件列表。"""
    service, unit, mod_folder, staging, _ = mod_group_env
    panel = AssemblyPanel(service)
    panel.bind_mod_group(unit, staging)
    assert panel.entry_count() == 1

    # 在 Mod 组文件夹内新增文件
    (mod_folder / "new_file.txt").write_text("data", encoding="utf-8")
    panel.refresh_current()
    assert panel.entry_count() == 2


def test_panel_close_button_triggers_callback(qapp, assembly_service) -> None:
    """关闭按钮 → 触发 on_panel_closed 回调。"""
    service, _ = assembly_service
    closed_called = {"flag": False}

    def on_closed() -> None:
        closed_called["flag"] = True

    panel = AssemblyPanel(service, on_panel_closed=on_closed)
    panel._on_close_clicked()  # noqa: SLF001
    assert closed_called["flag"]


def test_panel_remove_button_invokes_callback(qapp, mod_group_env) -> None:
    """移除按钮 → 触发 on_file_removed 回调（参数为文件名）。"""
    service, unit, _, staging, _ = mod_group_env
    removed_filename: list[str] = []

    def on_removed(name: str) -> None:
        removed_filename.append(name)

    panel = AssemblyPanel(service, on_file_removed=on_removed)
    panel.bind_mod_group(unit, staging)

    # 选中第一项
    idx = panel._list_model.index(0, 0)  # noqa: SLF001
    panel._list_view.setCurrentIndex(idx)  # noqa: SLF001
    panel._on_remove_clicked()  # noqa: SLF001

    assert removed_filename == ["source.7z"]


def test_panel_remove_button_no_selection(qapp, mod_group_env, monkeypatch) -> None:
    """移除按钮但无选中 → 显示提示，不触发回调。"""
    service, unit, _, staging, _ = mod_group_env
    removed_called = {"flag": False}

    def on_removed(name: str) -> None:
        removed_called["flag"] = True

    panel = AssemblyPanel(service, on_file_removed=on_removed)
    panel.bind_mod_group(unit, staging)

    # 不选中任何项
    panel._list_view.setCurrentIndex(QModelIndex())  # noqa: SLF001

    # Mock QMessageBox.information 避免阻塞
    monkeypatch.setattr("app.assembly_panel.QMessageBox.information", lambda *a, **kw: None)
    panel._on_remove_clicked()  # noqa: SLF001
    assert not removed_called["flag"]


# === 拖拽方案已取消（2026-07-17 调整为右键菜单「加入装配」） ===


# === 右键菜单 ===


def test_panel_context_menu_rename_image(qapp, mod_group_env, monkeypatch) -> None:
    """右键图片 → 触发 on_cover_renamed 回调。"""
    service, unit, mod_folder, staging, _ = mod_group_env
    # 在 Mod 组内添加一张图片
    image_path = mod_folder / "preview.jpg"
    image_path.write_bytes(b"\x00" * 50)

    renamed_paths: list[Path] = []

    def on_rename(p: Path) -> None:
        renamed_paths.append(p)

    panel = AssemblyPanel(service, on_cover_renamed=on_rename)
    panel.bind_mod_group(unit, staging)
    panel.refresh_current()

    # 找到 preview.jpg 条目
    entry = None
    for i in range(panel.entry_count()):
        e = panel.entry_at(i)
        if e is not None and e.name == "preview.jpg":
            entry = e
            break
    assert entry is not None

    panel._on_rename_cover(entry)  # noqa: SLF001
    assert renamed_paths == [Path(entry.path)]


def test_panel_context_menu_remove_via_menu(qapp, mod_group_env, monkeypatch) -> None:
    """右键菜单"移除" → 触发 on_file_removed 回调。"""
    service, unit, _, staging, _ = mod_group_env
    removed: list[str] = []

    def on_removed(name: str) -> None:
        removed.append(name)

    panel = AssemblyPanel(service, on_file_removed=on_removed)
    panel.bind_mod_group(unit, staging)

    entry = panel.entry_at(0)
    assert entry is not None
    panel._on_remove_via_menu(entry)  # noqa: SLF001
    assert removed == [entry.name]
