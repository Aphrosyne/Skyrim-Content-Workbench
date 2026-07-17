"""MainWindow 装配面板集成测试（阶段 3 Task 4）。

覆盖：
- 装配面板在浏览模式隐藏 / 整理模式按绑定显隐
- 创建 Mod 组后装配面板自动绑定并显示
- 整理模式下双击 Mod 组文件夹 → 装配面板绑定（单击不绑定）
- 装配面板回调：add_file / remove_file / rename_as_cover / closed
- 装配操作后暂存区列表与装配面板同步刷新
- 浏览模式下选中 Mod 组文件夹 → 装配面板保持隐藏
- 中栏右键菜单「加入装配」（2026-07-17 取消拖拽方案后新增）

注（2026-07-17 调整）：拖拽方案已取消，加入装配改由右键菜单触发；
整理模式下装配面板切换改由双击 Mod 组文件夹触发（单击仅选中显示元数据）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402

from app.main_window import MainWindow  # noqa: E402
from application.assembly_service import AssemblyService  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.mod_group_service import ModGroupService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from application.staging_service import StagingService  # noqa: E402
from domain.models import AppMode  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.file_operation_service import FileOperationService  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.folder_cache import FolderCacheRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402
from infrastructure.repositories.operation_history import (  # noqa: E402
    OperationHistoryRepository,
)
from infrastructure.repositories.staging_area import StagingAreaRepository  # noqa: E402


def _make_mod_tree(tmp_path: Path) -> Path:
    """构造测试目录树（含暂存区 + 零散文件）。"""
    root = tmp_path / "mods"
    root.mkdir()
    staging = root / "Stash"
    staging.mkdir()
    (staging / "BDOR Black Knight 1.0.7z").write_bytes(b"\x00" * 100)
    (staging / "preview.jpg").write_bytes(b"\x00" * 50)
    (staging / "extra_patch.zip").write_bytes(b"\x00" * 80)
    return root


@pytest.fixture
def main_window_env(qapp, tmp_path: Path):
    """构造完整 MainWindow 测试环境（含暂存区 + ModGroupService + AssemblyService 注入）。"""
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
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    staging_service = StagingService(
        StagingAreaRepository(conn),
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    tree_service = FolderTreeService(
        ManagedRootRepository(conn),
        FolderCacheRepository(conn),
        staging_service=staging_service,
    )
    content_service = ContentService(ContentUnitRepository(conn))
    scan_service = ScanService(
        managed_root_repo=ManagedRootRepository(conn),
        folder_cache_repo=FolderCacheRepository(conn),
        content_unit_repo=ContentUnitRepository(conn),
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    file_op_service = FileOperationService(OperationHistoryRepository(conn))
    folder_cache_repo = FolderCacheRepository(conn)
    mod_group_service = ModGroupService(file_op_service, content_service, folder_cache_repo)
    assembly_service = AssemblyService(
        file_op_service, ContentUnitRepository(conn), folder_cache_repo
    )

    root_dir = _make_mod_tree(tmp_path)
    root = managed_service.add_root(root_dir)
    scan_service.scan_root(root.id, incremental=False)
    staging_service.mark_staging(root_dir / "Stash")
    conn.commit()

    window = MainWindow(
        managed_service,
        tree_service,
        content_service,
        db_path,
        commit_callback=conn.commit,
        staging_service=staging_service,
        mod_group_service=mod_group_service,
        assembly_service=assembly_service,
    )
    yield window, conn, root_dir, root

    window.close()
    conn.close()


def _select_staging(qapp, window: MainWindow) -> None:
    """在目录树中选中暂存区 [S] 节点。"""
    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)
    for i in range(model.rowCount(root_idx)):
        child_idx = model.index(i, 0, root_idx)
        name = model.data(child_idx, Qt.DisplayRole)
        if name and "Stash" in name:
            window._tree_view.setCurrentIndex(child_idx)  # noqa: SLF001
            qapp.processEvents()
            return
    pytest.fail("未找到 Stash 节点")


def _select_entry_by_name(qapp, window: MainWindow, name: str) -> int:
    """在中栏选中指定名称的条目，返回其 row。"""
    model = window._content_list_model  # noqa: SLF001
    for row in range(model.entry_count()):
        entry = model.entry_at(row)
        if entry is not None and entry.name == name:
            idx = model.index(row, 0)
            window._content_view.setCurrentIndex(idx)  # noqa: SLF001
            qapp.processEvents()
            return row
    pytest.fail(f"未找到条目：{name}")


def _find_entry_by_name(window: MainWindow, name: str):
    """在中栏查找指定名称的条目。"""
    model = window._content_list_model  # noqa: SLF001
    for row in range(model.entry_count()):
        entry = model.entry_at(row)
        if entry is not None and entry.name == name:
            return entry
    return None


def _double_click_entry(qapp, window: MainWindow, name: str) -> None:
    """在中栏双击指定名称的条目（触发 _on_entry_activated）。"""
    model = window._content_list_model  # noqa: SLF001
    for row in range(model.entry_count()):
        entry = model.entry_at(row)
        if entry is not None and entry.name == name:
            idx = model.index(row, 0)
            window._on_entry_activated(idx)  # noqa: SLF001
            qapp.processEvents()
            return
    pytest.fail(f"未找到条目：{name}")


def _create_mod_group(qapp, window: MainWindow, source_name: str, chosen_name: str | None = None):
    """创建 Mod 组并返回新 ContentUnit。

    Args:
        source_name: 暂存区中源文件名。
        chosen_name: 对话框返回的名称；None 时用 extract_mod_name 提取的纯名。
    """
    _select_entry_by_name(qapp, window, source_name)
    entry = window._content_list_model.entry_at(  # noqa: SLF001
        window._content_view.currentIndex().row()  # noqa: SLF001
    )
    assert entry is not None

    if chosen_name is None:
        from application.mod_group_service import extract_mod_name

        chosen_name = extract_mod_name(entry.name)

    original_dialog = window._show_create_mod_group_dialog  # noqa: SLF001
    window._show_create_mod_group_dialog = lambda pure, full: chosen_name  # noqa: SLF001
    try:
        window._on_create_mod_group(entry)  # noqa: SLF001
        qapp.processEvents()
    finally:
        window._show_create_mod_group_dialog = original_dialog  # noqa: SLF001

    # 查询新创建的 ContentUnit
    staging_path = window._organize_workarea_path  # noqa: SLF001
    assert staging_path is not None
    mod_folder = Path(staging_path) / chosen_name
    unit = window._content_service.get_by_path(str(mod_folder))  # noqa: SLF001
    assert unit is not None, f"Mod 组 ContentUnit 未创建：{mod_folder}"
    return unit, mod_folder


# === 装配面板显隐 ===


def test_assembly_panel_hidden_in_browse_mode(qapp, main_window_env) -> None:
    """默认浏览模式：装配面板隐藏。"""
    window, _, _, _ = main_window_env
    assert window.current_mode() == AppMode.browse
    assert not window.assembly_panel_visible()


def test_assembly_panel_hidden_after_switching_to_organize_without_mod_group(
    qapp, main_window_env
) -> None:
    """整理模式下未选中 Mod 组：装配面板隐藏。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    # 未创建/选中 Mod 组 → 面板隐藏
    assert not window.assembly_panel_visible()
    assert window.assembly_panel_current_unit_id() is None


def test_assembly_panel_hidden_when_switching_back_to_browse(qapp, main_window_env) -> None:
    """整理模式下绑定 Mod 组后切回浏览模式：装配面板隐藏。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    # 创建 Mod 组 → 面板显示
    unit, _ = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z")
    assert window.assembly_panel_visible()
    assert window.assembly_panel_current_unit_id() == unit.id

    # 切回浏览模式 → 面板隐藏
    window._set_mode(AppMode.browse)  # noqa: SLF001
    qapp.processEvents()
    assert not window.assembly_panel_visible()


# === 创建 Mod 组后自动绑定 ===


def test_assembly_panel_shown_after_create_mod_group(qapp, main_window_env) -> None:
    """整理模式下创建 Mod 组 → 装配面板自动绑定并显示，列表含源文件。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    unit, _ = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z")

    # 装配面板显示并绑定到新 Mod 组
    assert window.assembly_panel_visible()
    assert window.assembly_panel_current_unit_id() == unit.id
    # 列表包含源压缩包文件
    assert window.assembly_panel_entry_count() == 1
    entry = window._assembly_panel.entry_at(0)  # noqa: SLF001
    assert entry is not None
    assert entry.name == "BDOR Black Knight 1.0.7z"


def test_assembly_panel_bind_switches_between_mod_groups(qapp, main_window_env) -> None:
    """整理模式下创建/选中不同 Mod 组 → 装配面板切换绑定。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    # 创建第一个 Mod 组
    unit1, mod_folder1 = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    assert window.assembly_panel_current_unit_id() == unit1.id

    # 创建第二个 Mod 组
    unit2, mod_folder2 = _create_mod_group(qapp, window, "extra_patch.zip", "ModB")
    assert window.assembly_panel_current_unit_id() == unit2.id
    assert window.assembly_panel_visible()
    # 第二个 Mod 组应包含 extra_patch.zip
    assert window.assembly_panel_entry_count() == 1
    entry = window._assembly_panel.entry_at(0)  # noqa: SLF001
    assert entry is not None
    assert entry.name == "extra_patch.zip"


# === 装配面板回调：add_file ===


def test_on_assembly_add_file_moves_file_to_mod_group(qapp, main_window_env) -> None:
    """_on_assembly_add_file：暂存区文件移入 Mod 组文件夹。"""
    window, _, root_dir, _ = main_window_env
    staging = root_dir / "Stash"
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")

    # 暂存区中应还有 preview.jpg（未移入）
    src_path = staging / "preview.jpg"
    assert src_path.is_file()

    # 触发 add_file 回调
    window._on_assembly_add_file(src_path)  # noqa: SLF001
    qapp.processEvents()

    # 源文件已移入 Mod 组文件夹
    assert not src_path.exists()
    assert (mod_folder / "preview.jpg").is_file()
    # 装配面板刷新后包含 2 个文件
    assert window.assembly_panel_entry_count() == 2
    # 暂存区列表已刷新（preview.jpg 不再出现）
    assert _find_entry_by_name(window, "preview.jpg") is None


def test_on_assembly_add_file_conflict(qapp, main_window_env, monkeypatch) -> None:
    """_on_assembly_add_file：目标已存在同名文件 → ConflictError 提示。"""
    window, _, root_dir, _ = main_window_env
    staging = root_dir / "Stash"
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")

    # 在 Mod 组内手动放置同名文件，制造冲突
    (mod_folder / "preview.jpg").write_bytes(b"\x00" * 10)

    # 暂存区也有 preview.jpg
    src_path = staging / "preview.jpg"
    assert src_path.is_file()

    # Mock QMessageBox 避免阻塞
    monkeypatch.setattr("app.main_window.QMessageBox.warning", lambda *a, **kw: None)
    window._on_assembly_add_file(src_path)  # noqa: SLF001
    qapp.processEvents()

    # 源文件未被移动（冲突）
    assert src_path.is_file()


# === 装配面板回调：remove_file ===


def test_on_assembly_remove_file_moves_back_to_staging(qapp, main_window_env) -> None:
    """_on_assembly_remove_file：Mod 组内文件移回暂存区根目录。"""
    window, _, root_dir, _ = main_window_env
    staging = root_dir / "Stash"
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    # 把 preview.jpg 移入 Mod 组
    window._on_assembly_add_file(staging / "preview.jpg")  # noqa: SLF001
    qapp.processEvents()
    assert (mod_folder / "preview.jpg").is_file()
    assert window.assembly_panel_entry_count() == 2

    # 移除 preview.jpg
    window._on_assembly_remove_file("preview.jpg")  # noqa: SLF001
    qapp.processEvents()

    # 文件已移回暂存区根目录（不保留原子目录结构）
    assert (staging / "preview.jpg").is_file()
    assert not (mod_folder / "preview.jpg").exists()
    # 装配面板刷新后只剩 1 个文件
    assert window.assembly_panel_entry_count() == 1


def test_on_assembly_remove_file_conflict(qapp, main_window_env, monkeypatch) -> None:
    """_on_assembly_remove_file：暂存区已存在同名文件 → ConflictError 提示。"""
    window, _, root_dir, _ = main_window_env
    staging = root_dir / "Stash"
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    # 把 preview.jpg 移入 Mod 组
    window._on_assembly_add_file(staging / "preview.jpg")  # noqa: SLF001
    qapp.processEvents()

    # 在暂存区手动放置同名文件，制造冲突
    (staging / "preview.jpg").write_bytes(b"\x00" * 10)

    monkeypatch.setattr("app.main_window.QMessageBox.warning", lambda *a, **kw: None)
    # 移除 preview.jpg（目标暂存区已存在）
    window._on_assembly_remove_file("preview.jpg")  # noqa: SLF001
    qapp.processEvents()

    # Mod 组内文件仍在（移动失败）
    assert (mod_folder / "preview.jpg").is_file()


# === 装配面板回调：rename_as_cover ===


def test_on_assembly_rename_cover_single_image(qapp, main_window_env) -> None:
    """_on_assembly_rename_cover：单张图片重命名为 {Mod组名}.{扩展名}。"""
    window, _, root_dir, _ = main_window_env
    staging = root_dir / "Stash"
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    # 把 preview.jpg 移入 Mod 组
    window._on_assembly_add_file(staging / "preview.jpg")  # noqa: SLF001
    qapp.processEvents()

    # 重命名 preview.jpg → MyMod.jpg
    image_path = mod_folder / "preview.jpg"
    window._on_assembly_rename_cover(image_path)  # noqa: SLF001
    qapp.processEvents()

    # 已重命名
    assert (mod_folder / "MyMod.jpg").is_file()
    assert not (mod_folder / "preview.jpg").exists()
    # 装配面板刷新后文件名变化
    assert window.assembly_panel_entry_count() == 2
    names = [
        window._assembly_panel.entry_at(i).name  # noqa: SLF001
        for i in range(window.assembly_panel_entry_count())
    ]
    assert "MyMod.jpg" in names


def test_on_assembly_rename_cover_multiple_images(qapp, main_window_env) -> None:
    """_on_assembly_rename_cover：多张图片采用 _2、_3 后缀。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    # 在 Mod 组内手动放置两张图片
    (mod_folder / "preview1.jpg").write_bytes(b"\x00" * 50)
    (mod_folder / "preview2.jpg").write_bytes(b"\x00" * 50)

    # 先重命名 preview1.jpg → MyMod.jpg
    window._on_assembly_rename_cover(mod_folder / "preview1.jpg")  # noqa: SLF001
    qapp.processEvents()
    assert (mod_folder / "MyMod.jpg").is_file()

    # 再重命名 preview2.jpg → MyMod_2.jpg
    window._on_assembly_rename_cover(mod_folder / "preview2.jpg")  # noqa: SLF001
    qapp.processEvents()
    assert (mod_folder / "MyMod_2.jpg").is_file()
    assert not (mod_folder / "preview1.jpg").exists()
    assert not (mod_folder / "preview2.jpg").exists()


def test_on_assembly_rename_cover_not_image(qapp, main_window_env, monkeypatch) -> None:
    """_on_assembly_rename_cover：非图片文件 → InvalidContentUnitPathError 提示。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")

    # 重命名 7z 文件（非图片）→ 应失败
    seven_z = mod_folder / "BDOR Black Knight 1.0.7z"
    monkeypatch.setattr("app.main_window.QMessageBox.warning", lambda *a, **kw: None)
    window._on_assembly_rename_cover(seven_z)  # noqa: SLF001
    qapp.processEvents()

    # 文件未被重命名
    assert seven_z.is_file()
    assert not (mod_folder / "MyMod.7z").exists()


# === 装配面板回调：closed ===


def test_on_assembly_closed_hides_panel(qapp, main_window_env) -> None:
    """_on_assembly_closed：隐藏装配面板（不解绑）。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    unit, _ = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    assert window.assembly_panel_visible()

    window._on_assembly_closed()  # noqa: SLF001
    qapp.processEvents()
    assert not window.assembly_panel_visible()
    # 解绑前 ContentUnit 仍保留（便于再次打开）
    assert window.assembly_panel_current_unit_id() == unit.id


# === 整理模式下双击 Mod 组文件夹 → 装配面板绑定 ===


def test_assembly_panel_binds_when_double_clicking_mod_group_in_content_list(
    qapp, main_window_env
) -> None:
    """整理模式下在中栏双击 Mod 组文件夹 → 装配面板绑定（2026-07-17 调整）。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    unit, _ = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    # 关闭面板模拟用户取消选中
    window._on_assembly_closed()  # noqa: SLF001
    qapp.processEvents()
    assert not window.assembly_panel_visible()

    # 在中栏双击 MyMod 文件夹
    _double_click_entry(qapp, window, "MyMod")

    # 装配面板自动绑定并显示
    assert window.assembly_panel_visible()
    assert window.assembly_panel_current_unit_id() == unit.id


def test_assembly_panel_no_bind_on_single_click_mod_group_in_content_list(
    qapp, main_window_env
) -> None:
    """整理模式下在中栏单击 Mod 组文件夹 → 装配面板不绑定（仅显示元数据）。

    2026-07-17 调整：单击不再切换装配面板，避免误触。
    """
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    unit, _ = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    # 关闭面板模拟用户取消选中
    window._on_assembly_closed()  # noqa: SLF001
    qapp.processEvents()
    assert not window.assembly_panel_visible()
    assert window.assembly_panel_current_unit_id() == unit.id  # 解绑前 ContentUnit 仍保留

    # 在中栏单击 MyMod 文件夹（不双击）
    _select_entry_by_name(qapp, window, "MyMod")
    qapp.processEvents()

    # 装配面板保持隐藏（单击不触发绑定）
    assert not window.assembly_panel_visible()
    # 但元数据已显示（单击选中显示元数据）
    # 检查元数据面板文本包含 Mod 组标题
    metadata_text = window._metadata_label.text()  # noqa: SLF001
    assert "MyMod" in metadata_text or "BDOR" in metadata_text


def test_assembly_panel_binds_when_selecting_mod_group_in_tree(qapp, main_window_env) -> None:
    """整理模式下在目录树选中 Mod 组文件夹 → 装配面板绑定（目录树行为不变）。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    unit, _ = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    window._on_assembly_closed()  # noqa: SLF001
    qapp.processEvents()
    assert not window.assembly_panel_visible()

    # 在目录树中找到 MyMod 节点并选中
    tree_model = window._tree_model  # noqa: SLF001
    root_idx = tree_model.index(0, 0)
    tree_model.fetchMore(root_idx)
    stash_idx = None
    for i in range(tree_model.rowCount(root_idx)):
        child_idx = tree_model.index(i, 0, root_idx)
        if "Stash" in (tree_model.data(child_idx, Qt.DisplayRole) or ""):
            stash_idx = child_idx
            break
    assert stash_idx is not None
    tree_model.fetchMore(stash_idx)
    mod_idx = None
    for j in range(tree_model.rowCount(stash_idx)):
        child_idx = tree_model.index(j, 0, stash_idx)
        if "MyMod" in (tree_model.data(child_idx, Qt.DisplayRole) or ""):
            mod_idx = child_idx
            break
    assert mod_idx is not None
    window._tree_view.setCurrentIndex(mod_idx)  # noqa: SLF001
    qapp.processEvents()

    # 装配面板自动绑定并显示
    assert window.assembly_panel_visible()
    assert window.assembly_panel_current_unit_id() == unit.id


def test_assembly_panel_no_bind_in_browse_mode_on_mod_group_selection(
    qapp, main_window_env
) -> None:
    """浏览模式下选中 Mod 组文件夹 → 装配面板保持隐藏（spec §7.4）。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    unit, _ = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    assert window.assembly_panel_visible()

    # 切回浏览模式
    window._set_mode(AppMode.browse)  # noqa: SLF001
    qapp.processEvents()
    assert not window.assembly_panel_visible()

    # 在中栏选中 MyMod 文件夹（浏览模式）
    # 先导航到 Stash 目录
    _select_staging(qapp, window)
    qapp.processEvents()
    # 选中 MyMod
    _select_entry_by_name(qapp, window, "MyMod")
    qapp.processEvents()

    # 装配面板保持隐藏
    assert not window.assembly_panel_visible()


# === 中栏右键菜单「加入装配」（2026-07-17 取消拖拽方案后新增） ===


class _FakeMenuAction:
    """模拟 QAction：仅保留 text 用于菜单项识别。"""

    def __init__(self, text: str) -> None:
        self._text = text

    def text(self) -> str:  # noqa: D401 (Qt 命名)
        return self._text


class _FakeMenu:
    """模拟 QMenu：捕获 addAction 调用，exec 返回匹配目标标签的 action。

    PySide6 的 QMenu.exec 为 C++ 实现，无法通过 monkeypatch.setattr(QMenu, "exec", ...)
    在实例方法层级替换；改为在模块命名空间替换 QMenu 类本身。
    """

    def __init__(self, parent=None) -> None:  # noqa: ANN001 (Qt 签名)
        self._actions: list[_FakeMenuAction] = []
        self._captured: list[str] = []
        self._target_label: str | None = None

    def addAction(self, label):  # noqa: ANN001 (Qt 签名)
        action = _FakeMenuAction(label)
        self._actions.append(action)
        return action

    def actions(self) -> list[_FakeMenuAction]:
        return self._actions

    def exec(self, pos, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, A003 (Qt 命名)
        for action in self._actions:
            self._captured.append(action.text())
            if self._target_label is not None and action.text() == self._target_label:
                return action
        return None


def _patch_qmenu(monkeypatch, target_label: str | None = None) -> list[str]:
    """Patch app.main_window.QMenu，返回捕获到的 action 文本列表容器。

    Args:
        target_label: exec 时返回此标签对应的 action；None 表示始终返回 None（仅捕获）。
    """
    from app import main_window as mw_module

    captured: list[str] = []

    class _CapturingMenu(_FakeMenu):
        def __init__(self, parent=None) -> None:  # noqa: ANN001
            super().__init__(parent)
            self._captured = captured
            self._target_label = target_label

    monkeypatch.setattr(mw_module, "QMenu", _CapturingMenu)
    return captured


def test_add_to_assembly_menu_moves_file_to_mod_group(qapp, main_window_env, monkeypatch) -> None:
    """右键菜单「加入装配」：暂存区文件移入 Mod 组文件夹。

    取代原拖拽方案，底层调用 AssemblyService.add_file。
    """
    window, _, root_dir, _ = main_window_env
    staging = root_dir / "Stash"
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")

    # 暂存区中应还有 preview.jpg（未移入）
    src_path = staging / "preview.jpg"
    assert src_path.is_file()

    # 选中 preview.jpg
    _select_entry_by_name(qapp, window, "preview.jpg")

    # Patch QMenu：捕获菜单项并返回「加入装配」action
    captured_actions = _patch_qmenu(monkeypatch, target_label="加入装配")

    # 触发右键菜单
    viewport = window._content_view.viewport()  # noqa: SLF001
    window._on_content_context_menu(viewport.mapToGlobal(viewport.rect().center()))  # noqa: SLF001
    qapp.processEvents()

    # 菜单中应包含「加入装配」
    assert "加入装配" in captured_actions

    # 源文件已移入 Mod 组文件夹
    assert not src_path.exists()
    assert (mod_folder / "preview.jpg").is_file()
    # 装配面板刷新后包含 2 个文件
    assert window.assembly_panel_entry_count() == 2


def test_add_to_assembly_menu_not_shown_without_mod_group_binding(
    qapp, main_window_env, monkeypatch
) -> None:
    """未绑定 Mod 组时右键菜单不显示「加入装配」。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    # 未创建 Mod 组 → 装配面板无绑定
    assert window.assembly_panel_current_unit_id() is None

    # 选中 preview.jpg
    _select_entry_by_name(qapp, window, "preview.jpg")

    # Patch QMenu：仅捕获，不返回任何 action
    captured_actions = _patch_qmenu(monkeypatch, target_label=None)

    viewport = window._content_view.viewport()  # noqa: SLF001
    window._on_content_context_menu(viewport.mapToGlobal(viewport.rect().center()))  # noqa: SLF001
    qapp.processEvents()

    # 菜单中不应包含「加入装配」
    assert "加入装配" not in captured_actions


# === 中文路径支持 ===


def test_assembly_panel_chinese_mod_group(qapp, main_window_env) -> None:
    """中文 Mod 组名 + 中文文件名：装配面板正常工作。"""
    window, _, root_dir, _ = main_window_env
    staging = root_dir / "Stash"
    _select_staging(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    # 创建中文 Mod 组
    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "寒霜之心")
    assert window.assembly_panel_visible()
    assert mod_folder.name == "寒霜之心"

    # 创建一个中文文件名的图片并移入
    chinese_image = staging / "预览图.jpg"
    chinese_image.write_bytes(b"\x00" * 50)
    window._on_assembly_add_file(chinese_image)  # noqa: SLF001
    qapp.processEvents()
    assert (mod_folder / "预览图.jpg").is_file()

    # 重命名为 Mod 组同名
    window._on_assembly_rename_cover(mod_folder / "预览图.jpg")  # noqa: SLF001
    qapp.processEvents()
    assert (mod_folder / "寒霜之心.jpg").is_file()
