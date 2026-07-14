"""MainWindow 模式切换集成测试（roadmap 阶段 2 Task 5）。

覆盖：
- 初始模式为 browse，模式按钮"浏览"选中
- 切换到整理模式 → 中栏冻结当前工作区内容
- 整理模式下点击目录树节点 → 中栏内容不变，显示目标提示
- 切回浏览模式 → 中栏恢复跟随目录树刷新
- 扫描完成（浏览模式）→ 当前文件列表刷新，新压缩包显示标记
- 扫描完成（整理模式）→ 冻结的工作区文件列表刷新
- 扫描完成 → 目录树刷新（回归）
- 整理模式工作区提示文本正确
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402

from app.main_window import MainWindow  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from domain.models import AppMode  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.folder_cache import FolderCacheRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402


def _make_mod_tree(tmp_path: Path) -> Path:
    """构造测试目录树。

    结构：
        mods/
        ├── 护甲/
        │   └── 寒霜之心.7z
        └── Weapons/
            └── DragonSword.rar
    """
    root = tmp_path / "mods"
    root.mkdir()

    armor = root / "护甲"
    armor.mkdir()
    (armor / "寒霜之心.7z").write_bytes(b"\x00" * 100)

    weapons = root / "Weapons"
    weapons.mkdir()
    (weapons / "DragonSword.rar").write_bytes(b"\x00" * 80)

    return root


@pytest.fixture
def main_window_env(qapp, tmp_path: Path):
    """构造完整的 MainWindow 测试环境（已扫描）。"""
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
    yield window, conn, root_dir, scan_service, root

    window.close()
    conn.close()


def _select_root(qapp, window: MainWindow) -> None:
    """选中目录树根节点。"""
    model = window._tree_model  # noqa: SLF001
    idx = model.index(0, 0)
    window._tree_view.setCurrentIndex(idx)  # noqa: SLF001
    qapp.processEvents()


def _select_child(qapp, window: MainWindow, name_contains: str) -> None:
    """展开根节点并选中包含指定名称的子节点。"""
    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)
    for i in range(model.rowCount(root_idx)):
        child_idx = model.index(i, 0, root_idx)
        name = model.data(child_idx, Qt.DisplayRole)
        if name and name_contains in name:
            window._tree_view.setCurrentIndex(child_idx)  # noqa: SLF001
            qapp.processEvents()
            return
    pytest.fail(f"未找到包含 '{name_contains}' 的节点")


# === 测试 ===


def test_initial_mode_is_browse(qapp, main_window_env) -> None:
    """启动后默认浏览模式，模式提示为浏览模式。"""
    window, _, _, _, _ = main_window_env
    assert window.current_mode() == AppMode.browse
    assert "浏览" in window.mode_hint_full_text()


def test_switch_to_organize_freezes_content(qapp, main_window_env) -> None:
    """浏览模式选中目录A → 切换到整理模式 → 中栏清空（A 不是 [S] 节点）。

    阶段 3 Task 2 新行为：整理模式只加载 [S] 节点的递归列表。
    非 [S] 节点 → 中栏清空，显示"请选中暂存区 [S] 节点"提示。
    """
    window, _, _, _, _ = main_window_env
    _select_root(qapp, window)
    # 选中护甲子目录
    _select_child(qapp, window, "护甲")
    entry_count_before = window.entry_count()
    assert entry_count_before > 0  # 护甲目录下有文件

    # 切换到整理模式
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    assert window.current_mode() == AppMode.organize
    # 护甲不是 [S] 节点 → 中栏清空
    assert window.entry_count() == 0
    # 工作区为 None（非 [S] 节点）
    assert window.organize_workarea_path() is None


def test_organize_mode_tree_click_does_not_refresh_content(qapp, main_window_env) -> None:
    """整理模式下点击目录树其他节点 → 中栏仍为空（无 [S] 节点被选中）。"""
    window, _, _, _, _ = main_window_env
    _select_root(qapp, window)
    _select_child(qapp, window, "护甲")

    # 切换到整理模式
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()
    assert window.entry_count() == 0  # 非 [S] 节点，中栏清空

    # 点击 Weapons 节点
    _select_child(qapp, window, "Weapons")
    # 中栏仍为空（Weapons 也不是 [S] 节点）
    assert window.entry_count() == 0


def test_organize_mode_shows_target_hint(qapp, main_window_env) -> None:
    """整理模式下点击目录树节点 → 中栏顶部显示"目标：xxx"。"""
    window, _, _, _, _ = main_window_env
    _select_root(qapp, window)
    _select_child(qapp, window, "护甲")
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    # 点击 Weapons 节点
    _select_child(qapp, window, "Weapons")
    hint = window.mode_hint_full_text()
    # 新行为：提示"请选中 [S] 节点" + 目标路径（Weapons）
    assert "目标" in hint
    assert "Weapons" in hint


def test_switch_back_to_browse_refreshes_content(qapp, main_window_env) -> None:
    """整理模式 → 切回浏览模式 → 中栏刷新为目录树当前选中节点内容。"""
    window, _, _, _, _ = main_window_env
    _select_root(qapp, window)
    _select_child(qapp, window, "护甲")

    # 切换到整理模式
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()
    # 点击 Weapons
    _select_child(qapp, window, "Weapons")
    # 中栏为空（非 [S] 节点）
    assert window.entry_count() == 0

    # 切回浏览模式
    window._set_mode(AppMode.browse)  # noqa: SLF001
    qapp.processEvents()
    assert window.current_mode() == AppMode.browse
    # 中栏应刷新为当前选中的 Weapons 节点内容
    found_dragon = False
    for i in range(window.entry_count()):
        entry = window.entry_at(i)
        if entry is not None and entry.name == "DragonSword.rar":
            found_dragon = True
            break
    assert found_dragon, "切回浏览模式后应显示 Weapons 目录的 DragonSword.rar"


def test_scan_finished_refreshes_content_list(qapp, main_window_env, tmp_path: Path) -> None:
    """浏览模式下扫描完成 → 当前文件列表刷新，新压缩包显示标记。"""
    window, _, root_dir, scan_service, root = main_window_env
    _select_root(qapp, window)
    _select_child(qapp, window, "护甲")

    # 在护甲目录下新增一个压缩包文件
    time.sleep(0.01)
    (root_dir / "护甲" / "新增武器.zip").write_bytes(b"\x00" * 50)

    # 执行扫描（直接调用 scan_service，模拟 ScanWorker 完成后的刷新逻辑）
    scan_service.scan_root(root.id, incremental=True)
    qapp.processEvents()

    # 模拟扫描完成后的刷新（测试 _refresh_content_list_after_scan）
    window._refresh_content_list_after_scan()  # noqa: SLF001
    qapp.processEvents()

    # 文件列表应包含新压缩包
    found_new = False
    for i in range(window.entry_count()):
        entry = window.entry_at(i)
        if entry is not None and entry.name == "新增武器.zip":
            found_new = True
            assert entry.content_unit is not None  # 新压缩包应被识别为内容单元
            break
    assert found_new, "新压缩包应出现在文件列表中"


def test_scan_finished_refreshes_content_list_in_organize(qapp, main_window_env) -> None:
    """整理模式下扫描完成 → 无 [S] 工作区时不刷新（中栏保持空）。"""
    window, _, _, _, _ = main_window_env
    _select_root(qapp, window)
    _select_child(qapp, window, "护甲")

    # 切换到整理模式（护甲非 [S] 节点，工作区为 None）
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()
    # 无 [S] 工作区
    assert window.organize_workarea_path() is None

    # 模拟扫描完成后的刷新
    window._refresh_content_list_after_scan()  # noqa: SLF001
    qapp.processEvents()

    # 无工作区 → 中栏仍为空
    assert window.entry_count() == 0


def test_organize_no_workarea_hint(qapp, main_window_env) -> None:
    """未选中任何目录树节点就切换到整理模式 → 显示"请选中 [S] 节点"提示。"""
    window, _, _, _, _ = main_window_env
    # 不选中任何节点直接切换到整理模式
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    assert window.current_mode() == AppMode.organize
    assert window.organize_workarea_path() is None
    hint = window.mode_hint_full_text()
    # 新行为：提示"请选中暂存区 [S] 节点"
    assert "暂存区 [S]" in hint or "请选中" in hint


def test_mode_hint_elide_applies_to_long_target_path(qapp, main_window_env) -> None:
    """整理模式下长目标路径应用 Elide，不撑大布局（Task 5 UI 一致性修复）。"""
    window, _, _, _, _ = main_window_env
    _select_root(qapp, window)
    _select_child(qapp, window, "护甲")
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    # 构造一个超长目标路径提示
    long_path = "C:\\" + "very_long_subdir_name\\" * 20 + "target_dir"
    window._organize_target_path = long_path  # noqa: SLF001
    window._update_organize_hint()
    qapp.processEvents()

    # 原始文本包含完整路径
    full_text = window.mode_hint_full_text()
    assert long_path in full_text

    # 模拟较小宽度触发 Elide
    window._mode_hint_label.resize(100, 30)  # noqa: SLF001
    window._apply_elide()  # noqa: SLF001
    elided_text = window.mode_hint_text()
    # Elide 后文本应比原始短（含省略号 …）
    assert len(elided_text) < len(full_text)
    assert "…" in elided_text
    # Tooltip 应包含完整文本
    assert window._mode_hint_label.toolTip() == full_text  # noqa: SLF001
