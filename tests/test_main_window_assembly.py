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

from app.main_window import MainWindow  # noqa: E402
from application.assembly_service import AssemblyService  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.content_unit_creation_service import ContentUnitCreationService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.file_operation_service import FileOperationService  # noqa: E402
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
    from application.quick_insert_service import QuickInsertService

    quick_insert_service = QuickInsertService(file_op_service, ContentUnitRepository(conn))
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
        quick_insert_service=quick_insert_service,
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
    monkeypatch.setattr("app.main_window.QMessageBox.warning", lambda *a, **kw: None)
    window._on_assembly_rename_cover(seven_z)  # noqa: SLF001
    qapp.processEvents()

    # 文件未被重命名
    assert seven_z.is_file()
    assert not (mod_folder / "MyMod.7z").exists()


# === 装配面板回调：closed（UX 重构 Phase 1 Task 2：关闭按钮已移除，测试一并删除） ===


# === 中栏右键菜单「加入装配」（UX Task 2 B2-2：已移除，测试与辅助类一并删除） ===


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
