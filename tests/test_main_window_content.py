"""MainWindow 文件列表联动测试（roadmap Task 4 2026-07-13 设计修正 + spec §5.4 修正）。

覆盖：
- 初始状态：文件列表为空；
- 选中目录树节点 → 文件列表刷新（含非内容单元文件）；
- 压缩包文件作为内容单元候选（spec §5.4 修正），文件夹不作为候选；
- 双击内容单元 → 元数据面板显示详情；
- 双击非内容单元文件/文件夹 → 不响应（spec §5.1 L205）；
- 切换目录树节点 → 文件列表更新，元数据面板清空；
- 未扫描根目录选中时不崩溃；
- 右键复制路径写入剪贴板；
- 中文文件名正确显示。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.main_window import MainWindow  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.folder_cache import FolderCacheRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402


def _make_mod_tree(tmp_path: Path) -> Path:
    """构造含压缩包 + 普通文件的测试目录树。

    结构：
        mods/
        ├── 护甲/                # 含压缩包的文件夹（非内容单元）
        │   ├── 寒霜之心.7z       # 内容单元（压缩包文件本身）
        │   ├── readme.txt       # 非内容单元文件（同目录内测试用）
        │   └── 预览图/          # 非内容单元文件夹（同目录内测试用）
        ├── Weapons/             # 含压缩包的文件夹（非内容单元）
        │   └── DragonSword.rar  # 内容单元
        ├── 普通文件夹/          # 非内容单元（无压缩包）
        │   └── readme.txt
        └── 散落文件.txt         # 非内容单元
    """
    root = tmp_path / "mods"
    root.mkdir()

    armor = root / "护甲"
    armor.mkdir()
    (armor / "寒霜之心.7z").write_bytes(b"\x00" * 100)
    # 同目录内非内容单元文件 + 文件夹，用于双击不响应测试（避免切换目录清空元数据）
    (armor / "readme.txt").write_bytes(b"data")
    (armor / "预览图").mkdir()

    weapons = root / "Weapons"
    weapons.mkdir()
    (weapons / "DragonSword.rar").write_bytes(b"\x00" * 80)

    normal = root / "普通文件夹"
    normal.mkdir()
    (normal / "readme.txt").write_bytes(b"data")

    (root / "散落文件.txt").write_text("散落文件内容", encoding="utf-8")

    return root


def _find_entry_index(window: MainWindow, name: str) -> int:
    """在文件列表中查找指定名称条目的索引。"""
    for i in range(window.entry_count()):
        entry = window.entry_at(i)
        if entry is not None and entry.name == name:
            return i
    pytest.fail(f"未找到条目：{name}")


@pytest.fixture
def main_window_env(qapp, tmp_path: Path):
    """构造完整的 MainWindow 测试环境。"""
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
    """选中目录树根节点并等待事件处理。"""
    model = window._tree_model  # noqa: SLF001
    idx = model.index(0, 0)
    window._tree_view.setCurrentIndex(idx)  # noqa: SLF001
    qapp.processEvents()


# === 测试 ===


def test_initial_state_shows_no_selection_hint(qapp, tmp_path: Path) -> None:
    """初始状态：文件列表为空。"""
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

    window = MainWindow(
        managed_service,
        tree_service,
        content_service,
        db_path,
        commit_callback=conn.commit,
    )
    assert window.entry_count() == 0
    window.close()
    conn.close()


def test_selecting_tree_node_refreshes_file_list(qapp, main_window_env) -> None:
    """选中目录树节点 → 文件列表刷新，含所有文件和文件夹。"""
    window, _, _ = main_window_env
    _select_root(qapp, window)

    # 根目录下应有 4 个条目：护甲 / Weapons / 普通文件夹 / 散落文件.txt
    # 文件夹在前：护甲、Weapons、普通文件夹；文件在后：散落文件.txt
    assert window.entry_count() == 4


def test_file_list_includes_non_content_unit_files(qapp, main_window_env) -> None:
    """非内容单元文件也正常列出。"""
    window, _, _ = main_window_env
    _select_root(qapp, window)

    entries = [window.entry_at(i) for i in range(window.entry_count())]
    names = [e.name for e in entries]
    assert "散落文件.txt" in names
    assert "普通文件夹" in names


def test_archive_files_are_content_units(qapp, main_window_env) -> None:
    """新规则：压缩包文件本身是内容单元，含压缩包的文件夹不是。"""
    window, _, _ = main_window_env
    _select_root(qapp, window)

    # 根目录下的条目：护甲（文件夹，非内容单元）/ Weapons（文件夹，非内容单元）
    # / 普通文件夹（文件夹，非内容单元）/ 散落文件.txt（文件，非内容单元）
    # 压缩包文件在子目录中，需要进入子目录才能看到
    entries = [window.entry_at(i) for i in range(window.entry_count())]
    by_name = {e.name: e for e in entries}

    # 根目录下的文件夹都不是内容单元（spec §5.4 修正）
    assert by_name["护甲"].content_unit is None
    assert by_name["Weapons"].content_unit is None
    assert by_name["普通文件夹"].content_unit is None
    assert by_name["散落文件.txt"].content_unit is None


def test_archive_file_in_subdir_is_content_unit(qapp, main_window_env) -> None:
    """进入子目录后，压缩包文件显示为内容单元。"""
    window, _, _ = main_window_env
    _select_root(qapp, window)

    # 展开根节点，选中"护甲"子目录
    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)
    for i in range(model.rowCount(root_idx)):
        child_idx = model.index(i, 0, root_idx)
        name = model.data(child_idx, Qt.DisplayRole)
        if name and "护甲" in name:
            window._tree_view.setCurrentIndex(child_idx)  # noqa: SLF001
            qapp.processEvents()
            # 护甲目录下有 3 个条目：预览图/（文件夹，非内容单元）
            # + readme.txt（文件，非内容单元）+ 寒霜之心.7z（文件，内容单元）
            assert window.entry_count() == 3
            idx = _find_entry_index(window, "寒霜之心.7z")
            entry = window.entry_at(idx)
            assert entry.content_unit is not None  # 压缩包是内容单元
            # 其他两个条目不是内容单元
            idx_readme = _find_entry_index(window, "readme.txt")
            assert window.entry_at(idx_readme).content_unit is None
            idx_preview = _find_entry_index(window, "预览图")
            assert window.entry_at(idx_preview).content_unit is None
            return
    pytest.fail("未找到护甲节点")


def test_double_click_content_unit_shows_metadata(qapp, main_window_env) -> None:
    """双击内容单元 → 元数据面板显示详情。"""
    window, _, _ = main_window_env
    _select_root(qapp, window)

    # 进入护甲子目录
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

    # 双击寒霜之心.7z（内容单元）
    idx = _find_entry_index(window, "寒霜之心.7z")
    window._on_entry_activated(window._content_list_model.index(idx, 0))  # noqa: SLF001
    qapp.processEvents()

    metadata = window.metadata_full_text()
    assert "标题" in metadata
    assert "路径" in metadata
    assert "类型" in metadata
    assert "评分" in metadata
    assert "整理状态" in metadata
    # 标题应为压缩包文件名（含扩展名）
    assert "寒霜之心.7z" in metadata


def test_double_click_non_content_unit_file_no_response(qapp, main_window_env) -> None:
    """双击非内容单元文件 → 不响应，元数据面板保持现状（spec §5.1 L205）。"""
    window, _, _ = main_window_env
    _select_root(qapp, window)

    # 进入护甲子目录（同目录内同时存在内容单元和非内容单元文件）
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

    # 双击寒霜之心.7z 填充元数据
    idx_archive = _find_entry_index(window, "寒霜之心.7z")
    window._on_entry_activated(window._content_list_model.index(idx_archive, 0))  # noqa: SLF001
    qapp.processEvents()
    assert "标题" in window.metadata_full_text()

    # 同目录内双击 readme.txt（非内容单元文件），元数据面板应保持不变
    idx_readme = _find_entry_index(window, "readme.txt")
    window._on_entry_activated(window._content_list_model.index(idx_readme, 0))  # noqa: SLF001
    qapp.processEvents()
    # 元数据面板保持上一次状态（标题仍在，不响应）
    assert "标题" in window.metadata_full_text()
    assert "寒霜之心.7z" in window.metadata_full_text()


def test_double_click_non_content_unit_dir_no_response(qapp, main_window_env) -> None:
    """双击非内容单元文件夹 → 不响应（spec §5.1 L205）。"""
    window, _, _ = main_window_env
    _select_root(qapp, window)

    # 进入护甲子目录（同目录内同时存在内容单元和非内容单元文件夹）
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

    # 双击寒霜之心.7z 填充元数据
    idx_archive = _find_entry_index(window, "寒霜之心.7z")
    window._on_entry_activated(window._content_list_model.index(idx_archive, 0))  # noqa: SLF001
    qapp.processEvents()
    assert "标题" in window.metadata_full_text()

    # 同目录内双击 预览图（非内容单元文件夹），元数据面板应保持不变
    idx_preview = _find_entry_index(window, "预览图")
    window._on_entry_activated(window._content_list_model.index(idx_preview, 0))  # noqa: SLF001
    qapp.processEvents()
    # 元数据面板保持上一次状态（标题仍在，不响应）
    assert "标题" in window.metadata_full_text()
    assert "寒霜之心.7z" in window.metadata_full_text()


def test_switching_tree_node_clears_metadata(qapp, main_window_env) -> None:
    """切换目录树节点 → 文件列表更新，元数据面板清空。"""
    window, _, _ = main_window_env
    _select_root(qapp, window)
    assert window.entry_count() == 4

    # 展开根节点，选中一个子目录
    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)
    for i in range(model.rowCount(root_idx)):
        child_idx = model.index(i, 0, root_idx)
        name = model.data(child_idx, Qt.DisplayRole)
        if name and "普通文件夹" in name:
            window._tree_view.setCurrentIndex(child_idx)  # noqa: SLF001
            qapp.processEvents()
            # 普通文件夹下只有 readme.txt
            assert window.entry_count() == 1
            # 元数据面板应清空
            assert "双击" in window.metadata_full_text()
            return
    pytest.fail("未找到普通文件夹节点")


def test_unscanned_root_does_not_crash(qapp, tmp_path: Path) -> None:
    """未扫描根目录选中时不崩溃。"""
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

    root_dir = tmp_path / "unscanned"
    root_dir.mkdir()
    managed_service.add_root(root_dir)
    conn.commit()

    window = MainWindow(
        managed_service,
        tree_service,
        content_service,
        db_path,
        commit_callback=conn.commit,
    )
    # 选中未扫描根节点
    model = window._tree_model  # noqa: SLF001
    idx = model.index(0, 0)
    window._tree_view.setCurrentIndex(idx)  # noqa: SLF001
    qapp.processEvents()
    # 未扫描根目录的 real_path 存在但内部为空
    assert window.entry_count() == 0
    window.close()
    conn.close()


def test_chinese_filename_displayed(qapp, main_window_env) -> None:
    """中文文件名正确显示在文件列表中。"""
    window, _, _ = main_window_env
    _select_root(qapp, window)

    entries = [window.entry_at(i) for i in range(window.entry_count())]
    names = [e.name for e in entries]
    assert "护甲" in names
    assert "普通文件夹" in names
    assert "散落文件.txt" in names


def test_context_menu_copy_path(qapp, main_window_env) -> None:
    """右键复制路径 → 剪贴板包含路径。"""
    window, _, _ = main_window_env
    _select_root(qapp, window)

    # 找到第一个条目
    entry = window.entry_at(0)
    assert entry is not None

    # 直接调用复制方法
    window._copy_path_to_clipboard(entry.path)  # noqa: SLF001
    qapp.processEvents()

    clipboard = QApplication.clipboard()
    assert clipboard is not None
    assert clipboard.text() == entry.path


def test_elide_applies_to_long_path(qapp, main_window_env) -> None:
    """路径超长时 Elide 生效（显示文本与原文不同）。"""
    window, _, root_dir = main_window_env
    _select_root(qapp, window)

    # 进入护甲子目录双击内容单元填充元数据
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

    idx = _find_entry_index(window, "寒霜之心.7z")
    window._on_entry_activated(window._content_list_model.index(idx, 0))  # noqa: SLF001
    qapp.processEvents()

    # 调整窗口尺寸较小，触发 Elide
    window._metadata_label.resize(100, 30)  # noqa: SLF001
    window._apply_elide()  # noqa: SLF001

    full_text = window.metadata_full_text()
    displayed = window.metadata_text()

    # 路径字段应被 Elide（包含省略号 ...），原文不包含
    # 注意：仅路径行被 Elide，其他行保留
    full_lines = full_text.split("\n")
    displayed_lines = displayed.split("\n")
    assert len(full_lines) == len(displayed_lines)

    # 至少有一行（路径行）在显示中被 Elide
    # 注意：窗口很窄时确实会出现省略
    path_line_full = next((line for line in full_lines if "路径：" in line), None)
    path_line_display = next((line for line in displayed_lines if "路径：" in line), None)
    assert path_line_full is not None
    assert path_line_display is not None
    # 路径行被省略（与原文不同）
    assert (
        path_line_display != path_line_full
        or "..." in path_line_display
        or "…" in path_line_display
    )
