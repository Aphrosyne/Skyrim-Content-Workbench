"""MainWindow 装配面板集成测试（阶段 3 Task 4）。

覆盖：
- 创建 Mod 组后装配面板自动绑定并显示
- 装配面板始终可见，未绑定时显示空状态
- 装配面板回调：rename_as_cover
- 装配面板切换绑定（创建多个 Mod 组）

注（UX 重构 Phase 1 Task 1）：移除整理/浏览双模式，装配面板通过创建 Mod 组自动绑定。
注（UX 重构 Phase 1 Task 2）：装配面板迁至右栏下方；单击文件夹内容单元绑定装配面板（A1-1）；
关闭按钮移除（B1-1）；「加入装配」菜单项移除（B2-2），Task 4 由「添加到钉住文件夹」替代。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402

from app import ui_constants as ui  # noqa: E402
from app.main_window import MainWindow  # noqa: E402
from application.assembly_service import AssemblyService  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.content_unit_creation_service import ContentUnitCreationService  # noqa: E402
from application.file_operation_service import FileOperationService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.folder_cache_sync_helper import FolderCacheSyncHelper  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.folder_cache import FolderCacheRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402
from infrastructure.repositories.operation_history import (  # noqa: E402
    OperationHistoryRepository,
)


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
    """构造完整 MainWindow 测试环境（含暂存区 + ContentUnitCreationService 等服务注入）。"""
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
        now_provider=lambda: "2026-07-14T00:00:00Z",
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
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    file_op_service = FileOperationService(
        OperationHistoryRepository(conn),
        folder_cache_helper=FolderCacheSyncHelper(FolderCacheRepository(conn)),
        content_unit_repo=ContentUnitRepository(conn),
    )
    # Stage 4.5 H4：各 Service 不再需要 folder_cache_repo
    content_unit_creation_service = ContentUnitCreationService(file_op_service, content_service)
    assembly_service = AssemblyService(file_op_service, ContentUnitRepository(conn))
    # UX 重构 Phase 1 Task 2 Commit 2：注入 clipboard_service 用于装配面板文件操作
    from application.clipboard_service import ClipboardService

    clipboard_service = ClipboardService()

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
        rollback_callback=conn.rollback,
        content_unit_creation_service=content_unit_creation_service,
        assembly_service=assembly_service,
        file_operation_service=file_op_service,
        clipboard_service=clipboard_service,
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
        from application.content_unit_creation_service import extract_mod_name

        chosen_name = extract_mod_name(entry.name)

    original_dialog = window._show_create_mod_group_dialog  # noqa: SLF001
    window._show_create_mod_group_dialog = lambda pure, full: chosen_name  # noqa: SLF001
    try:
        window._on_create_mod_group([entry])  # noqa: SLF001
        qapp.processEvents()
    finally:
        window._show_create_mod_group_dialog = original_dialog  # noqa: SLF001

    # 查询新创建的 ContentUnit（UX 重构后通过装配面板绑定获取）
    unit_id = window.assembly_panel_current_unit_id()
    assert unit_id is not None, "Mod 组创建后装配面板未绑定"
    unit = window._content_service.get_by_id(unit_id)  # noqa: SLF001
    assert unit is not None, "Mod 组 ContentUnit 未创建"
    mod_folder = Path(unit.path)
    return unit, mod_folder


# === 装配面板显隐 ===


def test_assembly_panel_visible_by_default(qapp, main_window_env) -> None:
    """UX 重构 Phase 1 Task 1 Commit 3：装配面板始终可见，未绑定时显示空状态。"""
    window, _, _, _ = main_window_env
    assert window.assembly_panel_visible()
    assert window.assembly_panel_current_unit_id() is None


# === 创建 Mod 组后自动绑定 ===


def test_assembly_panel_shown_after_create_mod_group(qapp, main_window_env) -> None:
    """创建 Mod 组 → 装配面板自动绑定并显示，列表含源文件。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
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
    """创建/选中不同 Mod 组 → 装配面板切换绑定。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
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


# === 装配面板回调：add_file（UX 重构 Phase 1 Task 2 B2-2：加入装配功能已移除，测试一并删除） ===


# === 装配面板回调：rename_as_cover ===


def test_on_assembly_rename_cover_single_image(qapp, main_window_env) -> None:
    """_on_assembly_rename_cover：单张图片重命名为 {Mod组名}.{扩展名}。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    # UX 重构 Task 2：加入装配功能已移除，直接在 Mod 组内放置图片文件
    (mod_folder / "preview.jpg").write_bytes(b"\x00" * 50)

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
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")

    # 重命名 7z 文件（非图片）→ 应失败
    seven_z = mod_folder / "BDOR Black Knight 1.0.7z"
    monkeypatch.setattr("app.main_window.QMessageBox.information", lambda *a, **kw: None)
    window._on_assembly_rename_cover(seven_z)  # noqa: SLF001
    qapp.processEvents()

    # 文件未被重命名
    assert seven_z.is_file()
    assert not (mod_folder / "MyMod.7z").exists()


# === 装配面板回调：closed（UX 重构 Phase 1 Task 2：关闭按钮已移除，测试一并删除） ===


# === 中栏右键菜单「加入装配」（UX Task 2 B2-2：已移除，测试与辅助类一并删除） ===


# === 修复5：装配面板重命名后中栏保持显示 ===


def test_assembly_rename_preserves_middle_display(qapp, main_window_env, monkeypatch) -> None:
    """修复5：装配面板内重命名文件后，中栏保持原显示目录（不空白、不进入子文件夹）。

    场景：装配面板钉住 Mod 组文件夹，中栏显示暂存区。
    在装配面板内右键重命名 preview.jpg → renamed.jpg，
    中栏应仍显示暂存区内容（包含 BDOR 7z 等其他文件），不应空白。
    """
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    # 在 Mod 组内放置 preview.jpg
    (mod_folder / "preview.jpg").write_bytes(b"\x00" * 50)
    # 钉住装配面板，并刷新让其读取新增的 preview.jpg
    window._assembly_panel.pin()  # noqa: SLF001
    window._assembly_panel.refresh_current()  # noqa: SLF001
    qapp.processEvents()

    # 中栏切回暂存区（与装配面板钉住的文件夹不同）
    _select_staging(qapp, window)
    qapp.processEvents()
    staging = root_dir / "Stash"
    # 中栏应显示暂存区内容
    assert window._current_displayed_dir() == str(staging)  # noqa: SLF001
    middle_count_before = window._content_list_model.entry_count()  # noqa: SLF001
    assert middle_count_before > 0

    # 在装配面板内重命名 preview.jpg → renamed.jpg
    # 找到 preview.jpg 条目
    rename_entry = None
    for i in range(window._assembly_panel.entry_count()):  # noqa: SLF001
        e = window._assembly_panel.entry_at(i)  # noqa: SLF001
        if e is not None and e.name == "preview.jpg":
            rename_entry = e
            break
    assert rename_entry is not None, "装配面板未显示 preview.jpg"

    # mock 重命名对话框：返回 "renamed.jpg"
    monkeypatch.setattr(
        window,
        "_show_rename_dialog",
        lambda old_name: ("renamed.jpg", True),  # noqa: SLF001
    )

    # 调用 _on_assembly_file_op("rename", [entry])
    window._on_assembly_file_op("rename", [rename_entry])  # noqa: SLF001
    qapp.processEvents()

    # 修复5：中栏应保持显示暂存区，且内容不为空
    assert window._current_displayed_dir() == str(staging)  # noqa: SLF001
    middle_count_after = window._content_list_model.entry_count()  # noqa: SLF001
    assert middle_count_after > 0, "修复5：装配面板重命名后中栏内容不应消失"
    # 中栏条目数应保持不变（重命名发生在 mod_folder，不影响 staging）
    assert middle_count_after == middle_count_before

    # 装配面板刷新后显示新名称
    names = [
        window._assembly_panel.entry_at(i).name  # noqa: SLF001
        for i in range(window._assembly_panel.entry_count())  # noqa: SLF001
    ]
    assert "renamed.jpg" in names
    assert "preview.jpg" not in names


def test_assembly_rename_preserves_middle_display_when_pinned_same_folder(
    qapp, main_window_env, monkeypatch
) -> None:
    """修复5：钉住的就是中栏显示目录时，重命名后中栏仍保持显示且反映新名称。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    # 在 Mod 组内放置 preview.jpg
    (mod_folder / "preview.jpg").write_bytes(b"\x00" * 50)
    # 钉住装配面板，并刷新让其读取新增的 preview.jpg
    window._assembly_panel.pin()  # noqa: SLF001
    window._assembly_panel.refresh_current()  # noqa: SLF001
    qapp.processEvents()

    # 中栏导航到 mod_folder（与装配面板钉住的相同）
    # 通过目录树选中 mod_folder 节点，使 _current_displayed_dir 返回 mod_folder
    target_idx = window._tree_model.find_index_by_path(  # noqa: SLF001
        window._tree_view,
        str(mod_folder),  # noqa: SLF001
    )
    assert target_idx.isValid(), "未在目录树中找到 mod_folder 节点"
    window._tree_view.setCurrentIndex(target_idx)  # noqa: SLF001
    qapp.processEvents()
    assert window._current_displayed_dir() == str(mod_folder)  # noqa: SLF001

    # 装配面板找到 preview.jpg
    rename_entry = None
    for i in range(window._assembly_panel.entry_count()):  # noqa: SLF001
        e = window._assembly_panel.entry_at(i)  # noqa: SLF001
        if e is not None and e.name == "preview.jpg":
            rename_entry = e
            break
    assert rename_entry is not None

    monkeypatch.setattr(
        window,
        "_show_rename_dialog",
        lambda old_name: ("renamed.jpg", True),  # noqa: SLF001
    )
    window._on_assembly_file_op("rename", [rename_entry])  # noqa: SLF001
    qapp.processEvents()

    # 修复5：中栏仍显示 mod_folder，且内容不为空
    assert window._current_displayed_dir() == str(mod_folder)  # noqa: SLF001
    middle_count_after = window._content_list_model.entry_count()  # noqa: SLF001
    assert middle_count_after > 0, "修复5：中栏内容不应消失"
    # 中栏应反映新名称
    middle_names = [
        window._content_list_model.entry_at(i).name  # noqa: SLF001
        for i in range(window._content_list_model.entry_count())  # noqa: SLF001
    ]
    assert "renamed.jpg" in middle_names


# === 中文路径支持 ===


def test_assembly_panel_chinese_mod_group(qapp, main_window_env) -> None:
    """中文 Mod 组名 + 中文文件名：装配面板正常工作。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    # 创建中文 Mod 组
    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "寒霜之心")
    assert window.assembly_panel_visible()
    assert mod_folder.name == "寒霜之心"

    # UX 重构 Task 2：加入装配功能已移除，直接在 Mod 组内放置中文图片文件
    (mod_folder / "预览图.jpg").write_bytes(b"\x00" * 50)
    assert (mod_folder / "预览图.jpg").is_file()

    # 重命名为 Mod 组同名
    window._on_assembly_rename_cover(mod_folder / "预览图.jpg")  # noqa: SLF001
    qapp.processEvents()
    assert (mod_folder / "寒霜之心.jpg").is_file()


# === UX 重构 Phase 1 Task 2：单击绑定装配面板（A1-1） ===


def test_single_click_folder_content_unit_binds_assembly(qapp, main_window_env) -> None:
    """A1-1：单击文件夹内容单元 → 装配面板绑定并显示其内部文件。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    # 创建 Mod 组（装配面板自动绑定）
    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    assert window.assembly_panel_current_unit_id() == unit.id

    # 重新选中暂存区，单击其他文件 → 装配面板应解绑
    _select_staging(qapp, window)
    qapp.processEvents()
    _select_entry_by_name(qapp, window, "preview.jpg")
    qapp.processEvents()
    assert window.assembly_panel_current_unit_id() is None

    # 回到暂存区，单击 MyMod 文件夹内容单元 → 装配面板应绑定
    _select_entry_by_name(qapp, window, "MyMod")
    qapp.processEvents()
    assert window.assembly_panel_current_unit_id() == unit.id
    assert window.assembly_panel_entry_count() == 1


def test_single_click_non_content_unit_unbinds_assembly(qapp, main_window_env) -> None:
    """A1-1：单击非内容单元 → 装配面板解绑显空状态。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    # 创建 Mod 组（装配面板自动绑定）
    unit, _ = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    assert window.assembly_panel_current_unit_id() == unit.id

    # 重新选中暂存区，单击普通文件 preview.jpg → 装配面板解绑
    _select_staging(qapp, window)
    qapp.processEvents()
    _select_entry_by_name(qapp, window, "preview.jpg")
    qapp.processEvents()
    assert window.assembly_panel_current_unit_id() is None


def test_assembly_panel_in_right_splitter(qapp, main_window_env) -> None:
    """UX Task 2：装配面板位于右栏 _right_splitter（非中间区 _middle_splitter）。"""
    window, _, _, _ = main_window_env
    # _middle_splitter 已不存在
    assert not hasattr(window, "_middle_splitter")
    # _right_splitter 存在且包含元数据 + 装配面板
    assert hasattr(window, "_right_splitter")
    splitter = window._right_splitter  # noqa: SLF001
    assert splitter.count() == 2
    assert splitter.widget(0) is window._metadata_group  # noqa: SLF001
    assert splitter.widget(1) is window._assembly_panel  # noqa: SLF001


def test_single_click_non_content_unit_folder_inspects(qapp, main_window_env) -> None:
    """UX Task 2：单击非内容单元文件夹 → 装配面板透视其内部文件（文件夹透视器语义）。"""
    window, _, root_dir, _ = main_window_env
    staging = root_dir / "Stash"
    # 在暂存区创建一个非内容单元文件夹 + 内部文件
    plain_folder = staging / "PlainFolder"
    plain_folder.mkdir()
    (plain_folder / "readme.txt").write_text("hi", encoding="utf-8")

    _select_staging(qapp, window)
    qapp.processEvents()

    # 单击 PlainFolder 文件夹（非内容单元）
    _select_entry_by_name(qapp, window, "PlainFolder")
    qapp.processEvents()

    # 装配面板应透视显示其内部文件
    assert window.assembly_panel_current_unit_id() is None  # 无 ContentUnit 关联
    panel = window._assembly_panel  # noqa: SLF001
    assert panel.current_folder_path() == plain_folder
    assert panel.entry_count() == 1
    entry = panel.entry_at(0)
    assert entry is not None
    assert entry.name == "readme.txt"


# === UX 重构 Phase 1 Task 2 Commit 2：装配面板文件操作 ===


def test_assembly_file_op_delete(qapp, main_window_env, monkeypatch) -> None:
    """装配面板右键删除文件：文件被移至回收站 + 装配面板刷新。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    # 在 Mod 组内放置一个额外文件
    (mod_folder / "extra.txt").write_text("data", encoding="utf-8")
    window._assembly_panel.refresh_current()  # noqa: SLF001
    qapp.processEvents()
    assert window.assembly_panel_entry_count() == 2

    # 找到 extra.txt 条目
    panel = window._assembly_panel  # noqa: SLF001
    extra_entry = None
    for i in range(panel.entry_count()):
        e = panel.entry_at(i)
        if e is not None and e.name == "extra.txt":
            extra_entry = e
            break
    assert extra_entry is not None

    # Mock 确认对话框返回 Yes
    monkeypatch.setattr(
        "app.main_window.QMessageBox.question",
        lambda *a, **kw: __import__("PySide6").QtWidgets.QMessageBox.StandardButton.Yes,
    )
    # 直接调用 _on_assembly_file_op（绕过 QMenu.exec）
    window._on_assembly_file_op("delete", [extra_entry])  # noqa: SLF001
    qapp.processEvents()

    # 文件已删除
    assert not (mod_folder / "extra.txt").exists()
    # 装配面板刷新后只剩 1 个文件
    assert window.assembly_panel_entry_count() == 1


def test_pinned_assembly_delete_keeps_middle_directory(qapp, main_window_env, monkeypatch) -> None:
    """修复：钉住文件夹后，在装配面板删除文件 → 中栏不跳入被钉住的文件夹。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    (mod_folder / "extra.txt").write_text("data", encoding="utf-8")
    window._assembly_panel.pin()  # noqa: SLF001
    window._assembly_panel.refresh_current()  # noqa: SLF001
    qapp.processEvents()
    assert window._assembly_panel.entry_count() == 2

    # 中栏当前显示暂存区（Stash）内容
    def _middle_names() -> set[str]:
        model = window._content_list_model  # noqa: SLF001
        return {
            model.entry_at(i).name
            for i in range(model.entry_count())
            if model.entry_at(i) is not None
        }

    assert "preview.jpg" in _middle_names()
    assert "extra_patch.zip" in _middle_names()

    # 在装配面板中找到 extra.txt 并删除
    panel = window._assembly_panel  # noqa: SLF001
    extra_entry = None
    for i in range(panel.entry_count()):
        e = panel.entry_at(i)
        if e is not None and e.name == "extra.txt":
            extra_entry = e
            break
    assert extra_entry is not None

    monkeypatch.setattr(
        "app.main_window.QMessageBox.question",
        lambda *a, **kw: __import__("PySide6").QtWidgets.QMessageBox.StandardButton.Yes,
    )
    window._on_assembly_file_op("delete", [extra_entry])  # noqa: SLF001
    qapp.processEvents()

    # 文件已删除 + 装配面板刷新
    assert not (mod_folder / "extra.txt").exists()
    assert window._assembly_panel.entry_count() == 1
    # 中栏不跳入被钉住的 mod_folder，仍停留在 Stash：
    # 列表显示 Stash 剩余条目（preview.jpg / extra_patch.zip），不含 mod_folder 内的 7z
    names = _middle_names()
    assert "BDOR Black Knight 1.0.7z" not in names
    assert "preview.jpg" in names
    assert "extra_patch.zip" in names


def test_assembly_file_op_copy_path(qapp, main_window_env, monkeypatch) -> None:
    """装配面板右键复制路径：路径写入系统剪贴板。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    panel = window._assembly_panel  # noqa: SLF001
    entry = panel.entry_at(0)
    assert entry is not None

    # Mock 系统剪贴板
    captured = {"text": None}

    class FakeClip:
        def setText(self, text):
            captured["text"] = text

    monkeypatch.setattr("app.main_window.QApplication.clipboard", lambda: FakeClip())

    window._on_assembly_file_op("copy_path", [entry])  # noqa: SLF001
    qapp.processEvents()
    assert captured["text"] == entry.path


def test_assembly_rename_cover_non_content_unit_folder(qapp, main_window_env) -> None:
    """非内容单元文件夹内图片右键重命名封面：用文件夹名重命名（rename_as_cover_by_path）。"""
    window, _, root_dir, _ = main_window_env
    staging = root_dir / "Stash"
    # 创建非内容单元文件夹 + 图片
    plain_folder = staging / "PlainMod"
    plain_folder.mkdir()
    (plain_folder / "preview.jpg").write_bytes(b"\x00" * 50)

    _select_staging(qapp, window)
    qapp.processEvents()
    _select_entry_by_name(qapp, window, "PlainMod")
    qapp.processEvents()

    # 装配面板透视 PlainMod（非内容单元）
    panel = window._assembly_panel  # noqa: SLF001
    assert panel.current_unit_id() is None
    assert panel.current_folder_path() == plain_folder

    # 重命名 preview.jpg → PlainMod.jpg
    window._on_assembly_rename_cover(plain_folder / "preview.jpg")  # noqa: SLF001
    qapp.processEvents()

    assert (plain_folder / "PlainMod.jpg").is_file()
    assert not (plain_folder / "preview.jpg").exists()


def test_assembly_file_op_copy_and_paste(qapp, main_window_env) -> None:
    """装配面板右键复制+粘贴：文件复制到当前透视文件夹。"""
    window, _, root_dir, _ = main_window_env
    staging = root_dir / "Stash"
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")

    # 重新选中暂存区，复制 preview.jpg 到剪贴板
    _select_staging(qapp, window)
    qapp.processEvents()
    src_entry = _find_entry_by_name(window, "preview.jpg")
    assert src_entry is not None

    # 通过装配面板 file_op 复制 preview.jpg（用装配面板的 copy action）
    # 先构造一个 FileEntry 表示 preview.jpg
    from domain.models import FileEntry

    preview_entry = FileEntry(
        name="preview.jpg",
        path=str(staging / "preview.jpg"),
        is_dir=False,
        modified_at="2026-07-14T00:00:00Z",
        size=50,
        content_unit=None,
    )
    window._on_assembly_file_op("copy", [preview_entry])  # noqa: SLF001
    qapp.processEvents()

    # 装配面板仍绑定 MyMod，粘贴到 MyMod 文件夹
    assert window.assembly_panel_current_unit_id() == unit.id
    window._on_assembly_file_op("paste", [])  # noqa: SLF001
    qapp.processEvents()

    # preview.jpg 已复制到 Mod 组文件夹
    assert (mod_folder / "preview.jpg").is_file()
    # 源文件仍在（复制非移动）
    assert (staging / "preview.jpg").is_file()
    # 装配面板刷新后包含 2 个文件
    assert window.assembly_panel_entry_count() == 2


# === UX 重构 Phase 1 Task 3：📌 钉住功能 ===


def test_pin_button_disabled_when_unbound(qapp, main_window_env) -> None:
    """A5：未绑定时 📌 按钮禁用。"""
    window, _, _, _ = main_window_env
    # 初始未绑定
    assert window.assembly_panel_current_unit_id() is None
    assert not window.assembly_panel_pin_button_enabled()
    assert not window.assembly_panel_is_pinned()


def test_pin_button_enabled_after_bind(qapp, main_window_env) -> None:
    """绑定文件夹后 📌 按钮可点击。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, _ = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    assert window.assembly_panel_current_unit_id() == unit.id
    # 绑定后按钮可点击
    assert window.assembly_panel_pin_button_enabled()
    # 默认未钉住
    assert not window.assembly_panel_is_pinned()


def test_pin_blocks_middle_click_binding(qapp, main_window_env) -> None:
    """A1：钉住后中栏单击其他文件夹不改变装配面板绑定。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit_a, mod_folder_a = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    assert window.assembly_panel_current_unit_id() == unit_a.id

    # 钉住 ModA
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()
    assert window.assembly_panel_is_pinned()

    # 重新选中暂存区以创建 ModB
    _select_staging(qapp, window)
    qapp.processEvents()
    unit_b, mod_folder_b = _create_mod_group(qapp, window, "extra_patch.zip", "ModB")
    # B1：钉住状态下创建 Mod 组不自动绑定，装配面板仍绑定 ModA
    assert window.assembly_panel_current_unit_id() == unit_a.id
    assert window.assembly_panel_is_pinned()

    # 单击 ModB 文件夹（如果在中栏可见）
    _select_staging(qapp, window)
    qapp.processEvents()
    mod_b_entry = _find_entry_by_name(window, "ModB")
    if mod_b_entry is not None:
        _select_entry_by_name(qapp, window, "ModB")
        qapp.processEvents()
        # A1：钉住状态下装配面板仍显示 ModA
        assert window.assembly_panel_current_unit_id() == unit_a.id


def test_pin_blocks_double_click_navigation(qapp, main_window_env) -> None:
    """A2：钉住后中栏双击文件夹进入目录，装配面板保持钉住。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    assert window.assembly_panel_current_unit_id() == unit.id

    # 钉住
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()

    # 双击暂存区中的另一个文件夹（这里用 mod_folder 自身，验证双击不切换）
    # 切回暂存区
    _select_staging(qapp, window)
    qapp.processEvents()
    # 双击 MyMod 文件夹（进入目录）
    _double_click_entry(qapp, window, "MyMod")
    qapp.processEvents()
    # 装配面板仍绑定 MyMod（钉住状态下双击进入目录不切换）
    assert window.assembly_panel_current_unit_id() == unit.id
    assert window.assembly_panel_is_pinned()


def test_unpin_follows_middle_selection(qapp, main_window_env) -> None:
    """B4：取消钉住后立即跟随中栏当前选中。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    # 先创建 ModA 和 ModB（都不钉住，装配面板正常切换）
    unit_a, _ = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    unit_b, _ = _create_mod_group(qapp, window, "extra_patch.zip", "ModB")
    # 装配面板当前绑定 ModB（最后创建的）
    assert window.assembly_panel_current_unit_id() == unit_b.id

    # 中栏选中 ModA → 装配面板跟随绑定 ModA
    _select_staging(qapp, window)
    qapp.processEvents()
    _select_entry_by_name(qapp, window, "ModA")
    qapp.processEvents()
    assert window.assembly_panel_current_unit_id() == unit_a.id

    # 钉住 ModA
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()
    assert window.assembly_panel_is_pinned()

    # 中栏选中 ModB（钉住状态下装配面板仍显示 ModA）
    _select_entry_by_name(qapp, window, "ModB")
    qapp.processEvents()
    assert window.assembly_panel_current_unit_id() == unit_a.id

    # 取消钉住 → 立即跟随中栏选中 ModB
    window._assembly_panel.unpin()  # noqa: SLF001
    qapp.processEvents()
    window._on_assembly_pin_changed(False)  # noqa: SLF001
    qapp.processEvents()
    assert not window.assembly_panel_is_pinned()
    assert window.assembly_panel_current_unit_id() == unit_b.id


def test_unpin_no_selection_clears_panel(qapp, main_window_env) -> None:
    """B4 边界：钉住状态下中栏无选中 → 取消钉住后装配面板清空。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, _ = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()

    # 清空中栏选中
    sm = window._content_view.selectionModel()  # noqa: SLF001
    sm.clear()
    qapp.processEvents()

    # 取消钉住 → 无选中 → 清空
    window._assembly_panel.unpin()  # noqa: SLF001
    window._on_assembly_pin_changed(False)  # noqa: SLF001
    qapp.processEvents()
    assert not window.assembly_panel_is_pinned()
    assert window.assembly_panel_current_unit_id() is None


def test_pin_state_not_persisted(qapp, main_window_env) -> None:
    """A3：钉住状态不持久化（重新创建装配面板实例默认未钉住）。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    window._assembly_panel.pin()  # noqa: SLF001
    assert window.assembly_panel_is_pinned()

    # 重新创建装配面板（模拟"重启"）
    from app.assembly_panel import AssemblyPanel

    old_panel = window._assembly_panel  # noqa: SLF001
    new_panel = AssemblyPanel(
        old_panel._service,  # noqa: SLF001
        on_cover_renamed=old_panel._on_cover_renamed,  # noqa: SLF001
        on_file_op=old_panel._on_file_op,  # noqa: SLF001
        on_pin_changed=window._on_assembly_pin_changed,  # noqa: SLF001
    )
    assert not new_panel.is_pinned()


def test_pin_file_ops_still_work(qapp, main_window_env) -> None:
    """B2：钉住状态下装配面板内文件操作仍可用（删除测试）。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    # 在 Mod 组内放置额外文件
    (mod_folder / "extra.txt").write_bytes(b"data")

    # 钉住
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()

    # 刷新装配面板显示
    window._assembly_panel.refresh_current()  # noqa: SLF001
    qapp.processEvents()
    assert window.assembly_panel_entry_count() == 2

    # 删除 extra.txt
    from domain.models import FileEntry

    extra_entry = FileEntry(
        name="extra.txt",
        path=str(mod_folder / "extra.txt"),
        is_dir=False,
        modified_at="2026-07-14T00:00:00Z",
        size=4,
        content_unit=None,
    )
    # Mock 确认对话框
    import unittest.mock

    with unittest.mock.patch("app.main_window.QMessageBox.question", return_value=16384):  # Yes
        window._on_assembly_file_op("delete", [extra_entry])  # noqa: SLF001
        qapp.processEvents()

    # 文件已删除
    assert not (mod_folder / "extra.txt").exists()
    # 装配面板仍钉住
    assert window.assembly_panel_is_pinned()
    assert window.assembly_panel_current_unit_id() == unit.id


def test_pin_auto_unpin_when_folder_missing(qapp, main_window_env, tmp_path) -> None:
    """A4/B6：钉住的文件夹路径不存在时自动解除钉住并清空。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()
    assert window.assembly_panel_is_pinned()

    # 外部删除文件夹
    import shutil

    shutil.rmtree(mod_folder)
    qapp.processEvents()

    # 刷新装配面板 → 检测到路径不存在 → 自动解除钉住
    window._assembly_panel.refresh_current()  # noqa: SLF001
    qapp.processEvents()

    assert not window.assembly_panel_is_pinned()
    assert window.assembly_panel_current_unit_id() is None
    assert window.assembly_panel_entry_count() == 0


def test_pin_move_folder_unpins(qapp, main_window_env, monkeypatch) -> None:
    """A4：钉住状态下移动整个透视文件夹 → 强制解除钉住并清空。"""
    from PySide6.QtWidgets import QDialog

    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()
    assert window.assembly_panel_is_pinned()

    # 选目标路径
    target_dir = root_dir.parent / "moved_target"
    target_dir.mkdir(exist_ok=True)
    target_path = target_dir / "MyMod"

    # Mock MoveToDialog 返回 Accepted + target_dir
    def _make_fake_dialog(target: Path, accepted: bool = True):
        class _Fake:
            def __init__(self, *a, **kw) -> None:
                self._t = target
                self._ok = accepted

            def exec(self) -> int:
                return QDialog.DialogCode.Accepted if self._ok else QDialog.DialogCode.Rejected

            def selected_target_path(self) -> Path | None:
                return self._t if self._ok else None

        return _Fake

    monkeypatch.setattr(
        "app.move_to_dialog.MoveToDialog",
        _make_fake_dialog(target_dir, accepted=True),
    )
    # 防止移动后信息弹窗阻塞
    monkeypatch.setattr("app.main_window.QMessageBox.information", lambda *a, **kw: None)

    # 触发 move_to 操作（移动整个 Mod 文件夹）
    from domain.models import FileEntry

    folder_entry = FileEntry(
        name="MyMod",
        path=str(mod_folder),
        is_dir=True,
        modified_at="2026-07-14T00:00:00Z",
        size=None,
        content_unit=unit,
    )
    window._on_assembly_file_op("move_to", [folder_entry])  # noqa: SLF001
    qapp.processEvents()

    # 文件夹已移动到新位置
    assert target_path.is_dir()
    assert not mod_folder.exists()

    # 装配面板已强制解除钉住并清空
    assert not window.assembly_panel_is_pinned()
    assert window.assembly_panel_current_unit_id() is None


def test_pin_toggle_button_icon(qapp, main_window_env) -> None:
    """B3：钉住时按钮显示 📍，未钉住时显示 📌。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "MyMod")
    # 未钉住状态
    assert window._assembly_panel._pin_button.text() == "📌"  # noqa: SLF001

    # 点击钉住
    window._assembly_panel._on_pin_clicked()  # noqa: SLF001
    qapp.processEvents()
    assert window.assembly_panel_is_pinned()
    assert window._assembly_panel._pin_button.text() == "📍"  # noqa: SLF001

    # 再次点击取消钉住
    window._assembly_panel._on_pin_clicked()  # noqa: SLF001
    qapp.processEvents()
    assert not window.assembly_panel_is_pinned()
    assert window._assembly_panel._pin_button.text() == "📌"  # noqa: SLF001


# === 添加到钉住文件夹（UX 重构 Phase 1 Task 4）===


def _get_menu_labels(window: MainWindow, entries) -> list[str]:
    """构造右键菜单并返回标签列表。"""
    actions = window._build_content_menu_actions(entries)  # noqa: SLF001
    return [label for label, _, _ in actions]


def test_add_to_pinned_menu_hidden_when_not_pinned(qapp, main_window_env) -> None:
    """A1：未钉住时不显示「添加到钉住文件夹」菜单项。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    entry = _find_entry_by_name(window, "preview.jpg")
    assert entry is not None
    labels = _get_menu_labels(window, [entry])
    assert ui.MENU_ADD_TO_PINNED not in labels


def test_add_to_pinned_menu_shown_when_pinned(qapp, main_window_env) -> None:
    """A1：钉住后显示「添加到钉住文件夹」菜单项。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()

    # 切回暂存区选中文件
    _select_staging(qapp, window)
    qapp.processEvents()
    entry = _find_entry_by_name(window, "preview.jpg")
    assert entry is not None
    labels = _get_menu_labels(window, [entry])
    assert ui.MENU_ADD_TO_PINNED in labels


def test_add_to_pinned_menu_before_move_to(qapp, main_window_env) -> None:
    """B6：「添加到钉住文件夹」在「移动到...」之前。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()

    _select_staging(qapp, window)
    qapp.processEvents()
    entry = _find_entry_by_name(window, "preview.jpg")
    assert entry is not None
    labels = _get_menu_labels(window, [entry])
    assert ui.MENU_ADD_TO_PINNED in labels
    assert ui.MENU_MOVE_TO in labels
    assert labels.index(ui.MENU_ADD_TO_PINNED) < labels.index(ui.MENU_MOVE_TO)


def test_add_to_pinned_single_file(qapp, main_window_env) -> None:
    """单文件添加到钉住文件夹：文件移动 + 中栏刷新 + 装配面板刷新。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()

    _select_staging(qapp, window)
    qapp.processEvents()
    entry = _find_entry_by_name(window, "preview.jpg")
    assert entry is not None

    window._on_add_to_pinned_folder([entry])  # noqa: SLF001
    qapp.processEvents()

    # 文件已移入钉住文件夹
    assert (mod_folder / "preview.jpg").is_file()
    # 源文件已不存在
    assert not (Path(root_dir_of(main_window_env)) / "Stash" / "preview.jpg").exists()
    # 装配面板刷新后显示新文件
    assembly_entries = window._assembly_panel.entry_count()  # noqa: SLF001
    assert assembly_entries >= 1


def root_dir_of(main_window_env):
    """从 main_window_env 提取 root_dir。"""
    _, _, root_dir, _ = main_window_env
    return root_dir


def test_add_to_pinned_multiple_files(qapp, main_window_env) -> None:
    """B1：多选文件添加到钉住文件夹。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()

    _select_staging(qapp, window)
    qapp.processEvents()
    entries = []
    for name in ("preview.jpg", "extra_patch.zip"):
        e = _find_entry_by_name(window, name)
        assert e is not None
        entries.append(e)

    window._on_add_to_pinned_folder(entries)  # noqa: SLF001
    qapp.processEvents()

    assert (mod_folder / "preview.jpg").is_file()
    assert (mod_folder / "extra_patch.zip").is_file()


def test_add_to_pinned_conflict_opens_dialog(qapp, main_window_env, monkeypatch) -> None:
    """修复3：目标已存在同名文件时弹出 ConflictResolutionDialog 询问。

    用户选择「跳过」→ 原文件保留，目标文件不被覆盖。
    """
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    # 在 Mod 组文件夹内预放同名文件
    (mod_folder / "preview.jpg").write_bytes(b"existing")
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()

    _select_staging(qapp, window)
    qapp.processEvents()
    entry = _find_entry_by_name(window, "preview.jpg")
    assert entry is not None

    # mock ConflictResolutionDialog：模拟用户选择「跳过」
    from app import conflict_resolution_dialog as crd_mod
    from application.conflict_resolution_service import RESOLUTION_SKIP

    class _FakeDialog:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def exec(self) -> int:  # noqa: D401, ANN004
            return 1  # Accepted

        def decisions(self) -> list[str]:
            return [RESOLUTION_SKIP]

    monkeypatch.setattr(crd_mod, "ConflictResolutionDialog", _FakeDialog)
    # mock QMessageBox 避免部分失败弹窗
    monkeypatch.setattr("app.main_window.QMessageBox.information", lambda *a, **kw: None)

    window._on_add_to_pinned_folder([entry])  # noqa: SLF001
    qapp.processEvents()

    # 跳过：原目标文件未被覆盖，源文件保留
    assert (mod_folder / "preview.jpg").read_bytes() == b"existing"
    assert entry.path and Path(entry.path).is_file()


def test_add_to_pinned_conflict_overwrite(qapp, main_window_env, monkeypatch) -> None:
    """修复3：冲突时用户选择「覆盖」→ 目标文件被源文件覆盖。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    (mod_folder / "preview.jpg").write_bytes(b"existing")
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()

    _select_staging(qapp, window)
    qapp.processEvents()
    entry = _find_entry_by_name(window, "preview.jpg")
    assert entry is not None
    # 覆盖源文件内容（与 existing 不同）
    Path(entry.path).write_bytes(b"new content")

    from app import conflict_resolution_dialog as crd_mod
    from application.conflict_resolution_service import RESOLUTION_OVERWRITE

    class _FakeDialog:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def exec(self) -> int:  # noqa: ANN004
            return 1

        def decisions(self) -> list[str]:
            return [RESOLUTION_OVERWRITE]

    monkeypatch.setattr(crd_mod, "ConflictResolutionDialog", _FakeDialog)

    window._on_add_to_pinned_folder([entry])  # noqa: SLF001
    qapp.processEvents()

    # 覆盖：目标文件被源文件覆盖
    assert (mod_folder / "preview.jpg").read_bytes() == b"new content"
    assert not Path(entry.path).exists()


def test_add_to_pinned_chinese_filename(qapp, main_window_env) -> None:
    """中文文件名添加到钉住文件夹。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    # 在暂存区创建中文文件名文件
    staging = root_dir / "Stash"
    chinese_file = staging / "汉化补丁.zip"
    chinese_file.write_bytes(b"localization")

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()

    _select_staging(qapp, window)
    qapp.processEvents()
    entry = _find_entry_by_name(window, "汉化补丁.zip")
    assert entry is not None

    window._on_add_to_pinned_folder([entry])  # noqa: SLF001
    qapp.processEvents()

    assert (mod_folder / "汉化补丁.zip").is_file()
    assert not chinese_file.exists()


# === 修复1（用户补充）：双击进入被钉住的文件夹内进行操作后装配面板同步刷新 ===


def test_pinned_assembly_refreshes_on_middle_rename(qapp, main_window_env, monkeypatch) -> None:
    """修复1：钉住文件夹后，双击进入该文件夹，在中栏重命名文件 → 装配面板同步刷新。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    (mod_folder / "preview.jpg").write_bytes(b"\x00" * 50)
    # 钉住装配面板并刷新
    window._assembly_panel.pin()  # noqa: SLF001
    window._assembly_panel.refresh_current()  # noqa: SLF001
    qapp.processEvents()
    assert window._assembly_panel.entry_count() == 2  # 7z + preview.jpg

    # 双击进入 mod_folder（中栏导航到 mod_folder）
    _select_staging(qapp, window)
    qapp.processEvents()
    _double_click_entry(qapp, window, "ModA")
    qapp.processEvents()
    assert window._current_displayed_dir() == str(mod_folder)  # noqa: SLF001

    # 在中栏找到 preview.jpg 并重命名
    entry = _find_entry_by_name(window, "preview.jpg")
    assert entry is not None
    monkeypatch.setattr(window, "_show_rename_dialog", lambda old: ("renamed.jpg", True))  # noqa: SLF001
    window._on_rename_entry(entry)  # noqa: SLF001
    qapp.processEvents()

    # 装配面板应同步刷新，显示新名称
    names = [
        window._assembly_panel.entry_at(i).name  # noqa: SLF001
        for i in range(window._assembly_panel.entry_count())  # noqa: SLF001
    ]
    assert "renamed.jpg" in names
    assert "preview.jpg" not in names


def test_pinned_assembly_refreshes_on_middle_delete(qapp, main_window_env, monkeypatch) -> None:
    """修复1：钉住文件夹后，双击进入该文件夹，在中栏删除文件 → 装配面板同步刷新。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    (mod_folder / "extra.txt").write_text("data", encoding="utf-8")
    window._assembly_panel.pin()  # noqa: SLF001
    window._assembly_panel.refresh_current()  # noqa: SLF001
    qapp.processEvents()
    assert window._assembly_panel.entry_count() == 2

    # 双击进入 mod_folder
    _select_staging(qapp, window)
    qapp.processEvents()
    _double_click_entry(qapp, window, "ModA")
    qapp.processEvents()

    # 在中栏找到 extra.txt 并删除
    entry = _find_entry_by_name(window, "extra.txt")
    assert entry is not None
    monkeypatch.setattr(
        "app.main_window.QMessageBox.question",
        lambda *a, **kw: __import__("PySide6").QtWidgets.QMessageBox.StandardButton.Yes,
    )
    window._on_delete_entries([entry])  # noqa: SLF001
    qapp.processEvents()

    # 装配面板应同步刷新，只剩 7z
    assert window._assembly_panel.entry_count() == 1
    assert window._assembly_panel.entry_at(0).name == "BDOR Black Knight 1.0.7z"  # noqa: SLF001


def test_pinned_assembly_refreshes_on_middle_new_folder(qapp, main_window_env, monkeypatch) -> None:
    """修复1：钉住文件夹后，双击进入该文件夹，在中栏新建文件夹 → 装配面板同步刷新。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    window._assembly_panel.pin()  # noqa: SLF001
    window._assembly_panel.refresh_current()  # noqa: SLF001
    qapp.processEvents()
    assert window._assembly_panel.entry_count() == 1

    # 双击进入 mod_folder
    _select_staging(qapp, window)
    qapp.processEvents()
    _double_click_entry(qapp, window, "ModA")
    qapp.processEvents()

    # 在中栏新建文件夹
    monkeypatch.setattr(
        "app.main_window.QInputDialog.getText",
        lambda *a, **kw: ("NewSub", True),
    )
    window._on_new_folder_in_dir(str(mod_folder))  # noqa: SLF001
    qapp.processEvents()

    # 装配面板应同步刷新，显示新建的文件夹
    assert window._assembly_panel.entry_count() == 2  # noqa: SLF001
    names = [
        window._assembly_panel.entry_at(i).name  # noqa: SLF001
        for i in range(window._assembly_panel.entry_count())  # noqa: SLF001
    ]
    assert "NewSub" in names


def test_pinned_assembly_refreshes_on_middle_paste(qapp, main_window_env) -> None:
    """修复1（补充）：钉住文件夹后，双击进入该文件夹，粘贴文件 → 装配面板同步刷新。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    (mod_folder / "preview.jpg").write_bytes(b"\x00" * 50)
    window._assembly_panel.pin()  # noqa: SLF001
    window._assembly_panel.refresh_current()  # noqa: SLF001
    qapp.processEvents()
    assert window._assembly_panel.entry_count() == 2  # 7z + preview.jpg

    # 双击进入 mod_folder（中栏导航到 mod_folder）
    _select_staging(qapp, window)
    qapp.processEvents()
    _double_click_entry(qapp, window, "ModA")
    qapp.processEvents()
    assert window._current_displayed_dir() == str(mod_folder)  # noqa: SLF001

    # 准备一个外部文件作为复制源，设置剪贴板后粘贴到 mod_folder
    external = root_dir / "external.txt"
    external.write_text("external", encoding="utf-8")
    window._clipboard_service.set_copy([str(external)])  # noqa: SLF001
    window._perform_paste(mod_folder)  # noqa: SLF001
    qapp.processEvents()

    # 装配面板应同步刷新，包含 external.txt
    names = [
        window._assembly_panel.entry_at(i).name  # noqa: SLF001
        for i in range(window._assembly_panel.entry_count())  # noqa: SLF001
    ]
    assert "external.txt" in names


def test_pinned_assembly_refreshes_on_middle_move_to(qapp, main_window_env) -> None:
    """修复1（补充）：钉住文件夹后，双击进入该文件夹，移动文件到外部 → 装配面板同步刷新。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    (mod_folder / "preview.jpg").write_bytes(b"\x00" * 50)
    window._assembly_panel.pin()  # noqa: SLF001
    window._assembly_panel.refresh_current()  # noqa: SLF001
    qapp.processEvents()
    assert window._assembly_panel.entry_count() == 2  # 7z + preview.jpg

    # 双击进入 mod_folder
    _select_staging(qapp, window)
    qapp.processEvents()
    _double_click_entry(qapp, window, "ModA")
    qapp.processEvents()
    assert window._current_displayed_dir() == str(mod_folder)  # noqa: SLF001

    # 将 mod_folder 内的 preview.jpg 移动到独立目标目录（避免与暂存区同名文件冲突）
    dest_dir = root_dir / "dest"
    dest_dir.mkdir()
    window._perform_move_to([mod_folder / "preview.jpg"], dest_dir)  # noqa: SLF001
    qapp.processEvents()

    # 装配面板应同步刷新，只剩 7z
    assert window._assembly_panel.entry_count() == 1  # noqa: SLF001
    assert window._assembly_panel.entry_at(0).name == "BDOR Black Knight 1.0.7z"  # noqa: SLF001


# === 拖拽支持（UX 重构 Phase 1 Task 4）===


def _make_mime(paths: list[Path]):
    """构造含文件 URL 的 QMimeData。"""
    from PySide6.QtCore import QMimeData, QUrl

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


def _make_drop_event(mime, pos=(0, 0)):
    """构造 QDropEvent。"""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QDropEvent

    return QDropEvent(
        QPointF(pos[0], pos[1]),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def test_assembly_drop_rejected_when_not_pinned(qapp, main_window_env) -> None:
    """未钉住时装配面板拒绝拖入。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    staging = root_dir / "Stash"
    src = staging / "preview.jpg"
    mime = _make_mime([src])

    # 未钉住时应拒绝
    assert not window._assembly_panel._can_accept_drop(mime)  # noqa: SLF001


def test_assembly_drop_accepted_for_folder(qapp, main_window_env) -> None:
    """修复2：拖入文件夹时接受（与右键添加行为一致）。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()

    # 构造一个文件夹路径
    folder = root_dir / "Stash" / "SubFolder"
    folder.mkdir()
    mime = _make_mime([folder])
    assert window._assembly_panel._can_accept_drop(mime)  # noqa: SLF001


def test_assembly_drop_accepted_when_pinned_and_file(qapp, main_window_env) -> None:
    """钉住 + 文件时接受拖入。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()

    src = root_dir / "Stash" / "preview.jpg"
    mime = _make_mime([src])
    assert window._assembly_panel._can_accept_drop(mime)  # noqa: SLF001


def test_assembly_drop_moves_file(qapp, main_window_env) -> None:
    """拖拽文件到装配面板：文件移入钉住文件夹。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()

    src = root_dir / "Stash" / "preview.jpg"
    mime = _make_mime([src])
    event = _make_drop_event(mime)
    window._assembly_panel.dropEvent(event)  # noqa: SLF001
    qapp.processEvents()

    assert (mod_folder / "preview.jpg").is_file()
    assert not src.exists()


def test_assembly_drop_moves_folder(qapp, main_window_env) -> None:
    """修复2：拖拽文件夹到装配面板，文件夹移入钉住文件夹。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()

    # 在暂存区创建一个子文件夹（含一个文件）
    folder_src = root_dir / "Stash" / "SubFolder"
    folder_src.mkdir()
    (folder_src / "inner.txt").write_bytes(b"inner")

    mime = _make_mime([folder_src])
    event = _make_drop_event(mime)
    window._assembly_panel.dropEvent(event)  # noqa: SLF001
    qapp.processEvents()

    # 文件夹被移入钉住文件夹
    assert (mod_folder / "SubFolder").is_dir()
    assert (mod_folder / "SubFolder" / "inner.txt").is_file()
    assert not folder_src.exists()


def test_assembly_drop_mixed_files_and_folders(qapp, main_window_env) -> None:
    """修复2：拖入文件+文件夹混合时，两者都移入钉住文件夹。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()

    file_src = root_dir / "Stash" / "preview.jpg"
    folder_src = root_dir / "Stash" / "ExtraFolder"  # 文件夹
    folder_src.mkdir()
    mime = _make_mime([file_src, folder_src])
    event = _make_drop_event(mime)
    window._assembly_panel.dropEvent(event)  # noqa: SLF001
    qapp.processEvents()

    # 文件和文件夹都被移入
    assert (mod_folder / "preview.jpg").is_file()
    assert (mod_folder / "ExtraFolder").is_dir()


def test_assembly_drop_conflict_opens_dialog(qapp, main_window_env, monkeypatch) -> None:
    """修复3：拖拽到装配面板遇冲突时弹出 ConflictResolutionDialog 询问。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    # 预放同名文件
    (mod_folder / "preview.jpg").write_bytes(b"existing")
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()

    src = root_dir / "Stash" / "preview.jpg"
    # 改源文件内容，与 existing 区分
    src.write_bytes(b"new")

    # mock ConflictResolutionDialog：模拟用户选择「跳过」
    from app import conflict_resolution_dialog as crd_mod
    from application.conflict_resolution_service import RESOLUTION_SKIP

    class _FakeDialog:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def exec(self) -> int:  # noqa: ANN004
            return 1

        def decisions(self) -> list[str]:
            return [RESOLUTION_SKIP]

    monkeypatch.setattr(crd_mod, "ConflictResolutionDialog", _FakeDialog)

    mime = _make_mime([src])
    event = _make_drop_event(mime)
    window._assembly_panel.dropEvent(event)  # noqa: SLF001
    qapp.processEvents()

    # 跳过：目标保留 existing，源文件保留原位
    assert (mod_folder / "preview.jpg").read_bytes() == b"existing"
    assert src.is_file()


def test_drop_to_folder_internal(qapp, main_window_env) -> None:
    """中栏内部拖拽文件到同目录文件夹。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    # 在暂存区创建一个子文件夹
    staging = root_dir / "Stash"
    target_folder = staging / "分类"
    target_folder.mkdir()

    src = staging / "preview.jpg"
    assert src.is_file()

    window._on_drop_to_folder(target_folder, [src])  # noqa: SLF001
    qapp.processEvents()

    assert (target_folder / "preview.jpg").is_file()
    assert not src.exists()


def test_drop_to_folder_conflict_opens_dialog(qapp, main_window_env, monkeypatch) -> None:
    """修复3：中栏内部拖拽冲突时弹出 ConflictResolutionDialog 询问（与复制粘贴一致）。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    staging = root_dir / "Stash"
    target_folder = staging / "分类"
    target_folder.mkdir()
    (target_folder / "preview.jpg").write_bytes(b"existing")

    src = staging / "preview.jpg"
    src.write_bytes(b"new")

    # mock ConflictResolutionDialog：模拟用户选择「重命名」
    from app import conflict_resolution_dialog as crd_mod
    from application.conflict_resolution_service import RESOLUTION_RENAME

    class _FakeDialog:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def exec(self) -> int:  # noqa: ANN004
            return 1

        def decisions(self) -> list[str]:
            return [RESOLUTION_RENAME]

    monkeypatch.setattr(crd_mod, "ConflictResolutionDialog", _FakeDialog)

    window._on_drop_to_folder(target_folder, [src])  # noqa: SLF001
    qapp.processEvents()

    # 重命名：原目标保留 existing，源文件以 "preview (1).jpg" 重命名后移入
    assert (target_folder / "preview.jpg").read_bytes() == b"existing"
    assert (target_folder / "preview (1).jpg").is_file()
    assert (target_folder / "preview (1).jpg").read_bytes() == b"new"
    assert not src.exists()


def test_drop_to_folder_self_subdirectory_rejected(qapp, main_window_env, monkeypatch) -> None:
    """修复4：中栏内拖拽文件夹到自身子目录被拒绝（SelfSubdirectoryError）。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    staging = root_dir / "Stash"
    target_folder = staging / "TargetFolder"
    target_folder.mkdir()
    # 源 = 目标文件夹自身（拖到自身）
    src = target_folder

    # mock 部分失败弹窗（SelfSubdirectoryError 会被收集到 errors）
    monkeypatch.setattr("app.main_window.QMessageBox.information", lambda *a, **kw: None)

    window._on_drop_to_folder(target_folder, [src])  # noqa: SLF001
    qapp.processEvents()

    # 源文件夹未被移动（仍在原位）
    assert target_folder.is_dir()


def test_drop_to_folder_parent_into_child_rejected(qapp, main_window_env, monkeypatch) -> None:
    """修复4：父目录拖入子目录被拒绝。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    staging = root_dir / "Stash"
    parent_folder = staging / "Parent"
    parent_folder.mkdir()
    child_folder = parent_folder / "Child"
    child_folder.mkdir()

    # 源 = 父目录，目标 = 子目录（拖父进子）
    monkeypatch.setattr("app.main_window.QMessageBox.information", lambda *a, **kw: None)

    window._on_drop_to_folder(child_folder, [parent_folder])  # noqa: SLF001
    qapp.processEvents()

    # 父目录未被移动（仍在原位）
    assert parent_folder.is_dir()
    # 子目录中未出现父目录副本
    assert not (child_folder / "Parent").exists()


def test_drop_to_pinned_folder_refreshes_assembly(qapp, main_window_env) -> None:
    """修复1：拖拽到中栏被钉住文件夹后装配面板同步刷新。"""
    window, _, root_dir, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    # 创建 Mod 组并钉住（装配面板钉住 mod_folder）
    unit, mod_folder = _create_mod_group(qapp, window, "BDOR Black Knight 1.0.7z", "ModA")
    window._assembly_panel.pin()  # noqa: SLF001
    qapp.processEvents()

    # 中栏切回暂存区
    _select_staging(qapp, window)
    qapp.processEvents()

    # 装配面板当前透视 mod_folder，记录初始条目数
    initial_count = window._assembly_panel.entry_count()  # noqa: SLF001

    # 拖拽 preview.jpg 到中栏的 mod_folder（即装配面板钉住的文件夹）
    src = root_dir / "Stash" / "preview.jpg"
    window._on_drop_to_folder(mod_folder, [src])  # noqa: SLF001
    qapp.processEvents()

    # 修复1：装配面板应同步刷新，新文件出现在装配面板
    assert window._assembly_panel.entry_count() == initial_count + 1  # noqa: SLF001
    names = [
        window._assembly_panel.entry_at(i).name  # noqa: SLF001
        for i in range(window._assembly_panel.entry_count())  # noqa: SLF001
    ]
    assert "preview.jpg" in names


def test_file_list_model_mime_data(qapp, main_window_env) -> None:
    """FileListModel.mimeData 生成正确的 file URL。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    model = window._content_list_model  # noqa: SLF001
    entry = _find_entry_by_name(window, "preview.jpg")
    assert entry is not None
    idx = model.index(0, 0)
    mime = model.mimeData([idx])
    assert mime is not None
    urls = mime.urls()
    assert len(urls) >= 1
    assert all(url.scheme() == "file" for url in urls)


def test_card_list_model_mime_data(qapp, main_window_env) -> None:
    """CardListModel.mimeData 生成正确的 file URL。"""
    window, _, _, _ = main_window_env
    _select_staging(qapp, window)
    qapp.processEvents()

    # 切换到卡片视图
    window._content_stack.setCurrentIndex(1)  # noqa: SLF001
    qapp.processEvents()

    model = window._card_list_model  # noqa: SLF001
    idx = model.index(0, 0)
    mime = model.mimeData([idx])
    assert mime is not None
    urls = mime.urls()
    assert len(urls) >= 1
