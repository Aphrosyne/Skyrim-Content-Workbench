"""MainWindow 暂存区文件列表集成测试（阶段 3 Task 2）。

覆盖：
- 整理模式下选中 [S] 节点 → 中栏显示递归文件列表（含子目录文件）
- 整理模式下选中非 [S] 节点 → 中栏不切换，只更新目标提示
- 整理模式切换时未选中 [S] 节点 → 显示"请选中暂存区节点"提示
- 切回浏览模式 → 中栏恢复为单层目录列表
- 列头排序切换
- 暂存区路径不存在 → 显示友好提示
- 扫描完成 → 整理模式暂存区列表刷新
- 中文路径正确加载
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from app.file_list_model import SORT_NAME, SORT_SIZE  # noqa: E402
from app.main_window import MainWindow  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from application.staging_service import StagingService  # noqa: E402
from domain.models import AppMode  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.folder_cache import FolderCacheRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402
from infrastructure.repositories.staging_area import StagingAreaRepository  # noqa: E402


def _make_staging_tree(tmp_path: Path) -> Path:
    """构造测试目录树（暂存区含子目录与多层文件）。

    结构：
        staging/
        ├── mod1.7z
        ├── readme.txt
        └── 汉化/
            ├── patch.zip
            └── deep/
                └── nested.7z
    """
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "mod1.7z").write_bytes(b"\x00" * 100)
    (staging / "readme.txt").write_text("hi", encoding="utf-8")
    (staging / "汉化").mkdir()
    (staging / "汉化" / "patch.zip").write_bytes(b"\x00" * 50)
    (staging / "汉化" / "deep").mkdir()
    (staging / "汉化" / "deep" / "nested.7z").write_bytes(b"\x00" * 20)
    return staging


@pytest.fixture
def staging_list_env(qapp, tmp_path: Path):
    """构造注入 StagingService 的 MainWindow 测试环境（已标记暂存区）。"""
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

    staging_dir = _make_staging_tree(tmp_path)
    root = managed_service.add_root(staging_dir)
    scan_service.scan_root(root.id, incremental=False)
    # 标记 staging_dir 为暂存区
    staging_service.mark_staging(staging_dir)
    conn.commit()

    window = MainWindow(
        managed_service,
        tree_service,
        content_service,
        db_path,
        commit_callback=conn.commit,
        staging_service=staging_service,
    )
    yield window, conn, staging_dir, scan_service, root

    window.close()
    conn.close()


def _select_root(qapp, window: MainWindow) -> None:
    """选中目录树根节点。"""
    model = window._tree_model  # noqa: SLF001
    idx = model.index(0, 0)
    window._tree_view.setCurrentIndex(idx)  # noqa: SLF001
    qapp.processEvents()


# === 测试 ===


def test_organize_mode_with_staging_node_shows_recursive_list(qapp, staging_list_env) -> None:
    """整理模式下选中 [S] 节点 → 中栏显示递归文件列表（含子目录文件）。"""
    window, _, staging_dir, _, _ = staging_list_env
    _select_root(qapp, window)

    # 切换到整理模式（根节点是 [S]）
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    # 应显示暂存区递归列表
    entry_names = {window.entry_at(i).name for i in range(window.entry_count())}
    assert "mod1.7z" in entry_names
    assert "readme.txt" in entry_names
    assert "汉化" in entry_names
    assert "patch.zip" in entry_names  # 一层子目录
    assert "deep" in entry_names
    assert "nested.7z" in entry_names  # 二层子目录


def test_organize_mode_without_staging_node_shows_hint(qapp, staging_list_env) -> None:
    """切到整理模式时未选中 [S] 节点 → 显示"请选中暂存区节点"提示。

    本测试场景：根节点是 [S]，所以构造一个没有选中 [S] 的场景——
    先取消选中，再切到整理模式（无选中节点）。
    """
    window, _, _, _, _ = staging_list_env
    # 不选中任何节点直接切到整理模式
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    # 中栏应为空，提示"请选中暂存区 [S] 节点"
    assert window.entry_count() == 0
    hint = window.mode_hint_full_text()
    assert "暂存区 [S]" in hint or "请选中" in hint


def test_organize_mode_non_staging_node_keeps_content(qapp, staging_list_env) -> None:
    """整理模式下点选非 [S] 节点 → 中栏不切换，只更新目标提示。

    本测试：先在 [S] 节点上切到整理模式加载暂存区列表，
    再点击目录树中另一个非 [S] 节点（无其他节点时仅验证目标提示更新）。
    """
    window, _, _, _, _ = staging_list_env
    _select_root(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()
    count_after_enter = window.entry_count()
    assert count_after_enter > 0

    # 由于目录树只有根节点（[S]），无法点击非 [S] 节点；
    # 改为验证：再次点击 [S] 节点时中栏内容不变
    _select_root(qapp, window)
    qapp.processEvents()
    assert window.entry_count() == count_after_enter


def test_switch_back_to_browse_shows_single_level(qapp, staging_list_env) -> None:
    """整理模式 → 切回浏览模式 → 中栏恢复为单层目录列表。"""
    window, _, _, _, _ = staging_list_env
    _select_root(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()
    # 整理模式：含递归子目录文件
    recursive_count = window.entry_count()
    assert recursive_count >= 6  # mod1.7z, readme.txt, 汉化, patch.zip, deep, nested.7z

    # 切回浏览模式
    window._set_mode(AppMode.browse)  # noqa: SLF001
    qapp.processEvents()
    # 浏览模式：单层（mod1.7z, readme.txt, 汉化）
    browse_names = {window.entry_at(i).name for i in range(window.entry_count())}
    assert "mod1.7z" in browse_names
    assert "readme.txt" in browse_names
    assert "汉化" in browse_names
    assert "patch.zip" not in browse_names  # 单层不含子目录文件
    assert "nested.7z" not in browse_names


def test_column_header_sort_toggle(qapp, staging_list_env) -> None:
    """列头点击切换排序键；同列再点切换升降序。"""
    window, _, _, _, _ = staging_list_env
    _select_root(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    model = window._content_list_model  # noqa: SLF001
    # 默认名称升序
    assert model.current_sort_key() == SORT_NAME
    assert model.is_sort_ascending() is True

    # 点击大小列（column=2）
    window._on_content_header_clicked(2)  # noqa: SLF001
    qapp.processEvents()
    assert model.current_sort_key() == SORT_SIZE
    assert model.is_sort_ascending() is True

    # 再次点击大小列 → 翻转为降序
    window._on_content_header_clicked(2)  # noqa: SLF001
    qapp.processEvents()
    assert model.current_sort_key() == SORT_SIZE
    assert model.is_sort_ascending() is False


def test_chinese_path_staging_loads(qapp, staging_list_env) -> None:
    """暂存区含中文路径与文件名，整理模式下正确加载。"""
    window, _, _, _, _ = staging_list_env
    _select_root(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    entry_names = {window.entry_at(i).name for i in range(window.entry_count())}
    assert "汉化" in entry_names


def test_scan_finished_refreshes_staging_list(qapp, staging_list_env) -> None:
    """整理模式下扫描完成 → 暂存区递归列表刷新，新文件出现。"""
    window, _, staging_dir, scan_service, root = staging_list_env
    _select_root(qapp, window)
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()
    count_before = window.entry_count()

    # 在暂存区子目录新增文件
    time.sleep(0.01)
    (staging_dir / "汉化" / "新增文件.zip").write_bytes(b"\x00" * 30)

    # 执行扫描
    scan_service.scan_root(root.id, incremental=True)
    qapp.processEvents()

    # 模拟扫描完成后的刷新
    window._refresh_content_list_after_scan()  # noqa: SLF001
    qapp.processEvents()

    # 列表应包含新文件
    found_new = False
    for i in range(window.entry_count()):
        entry = window.entry_at(i)
        if entry is not None and entry.name == "新增文件.zip":
            found_new = True
            break
    assert found_new, "整理模式下扫描完成应刷新暂存区递归列表，新文件应出现"
    assert window.entry_count() == count_before + 1


def test_staging_path_invalid_shows_hint(qapp, staging_list_env, tmp_path: Path) -> None:
    """暂存区目录被删除后选中 → 中栏显示"路径不存在"提示。

    本测试通过构造一个路径不存在的暂存区记录，验证 _refresh_staging_content_list
    的友好提示逻辑。
    """
    window, conn, _, _, _ = staging_list_env
    # 直接在数据库插入一条路径不存在的暂存区记录
    from infrastructure.repositories.staging_area import StagingAreaRepository

    repo = StagingAreaRepository(conn)
    from domain.models import StagingArea

    fake_path = str(tmp_path / "nonexistent_staging")
    repo.create(
        StagingArea(
            id="fake-staging",
            real_path=fake_path,
            path_key=fake_path.lower(),
            created_at="2026-07-14T00:00:00Z",
            updated_at="2026-07-14T00:00:00Z",
        )
    )
    conn.commit()

    # 直接调用 _refresh_staging_content_list
    window._refresh_staging_content_list(fake_path)  # noqa: SLF001
    qapp.processEvents()

    # 中栏应为空，提示路径不存在
    assert window.entry_count() == 0
    hint_text = window._content_empty_hint.text()  # noqa: SLF001
    assert "不存在" in hint_text or "为空" in hint_text


def test_organize_target_hint_updated_for_non_staging_node(
    qapp, staging_list_env, tmp_path: Path
) -> None:
    """整理模式下点选非 [S] 节点 → 目标提示更新。

    本测试添加第二个非 [S] 根目录，整理模式下点击它验证目标提示。
    """
    window, conn, _, _, _ = staging_list_env
    # 添加第二个根目录（非暂存区）
    other_dir = tmp_path / "other_root"
    other_dir.mkdir()
    (other_dir / "other.7z").write_bytes(b"\x00")
    from application.managed_root_service import ManagedRootService
    from infrastructure.repositories.managed_root import ManagedRootRepository

    managed2 = ManagedRootService(
        ManagedRootRepository(conn),
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=lambda: "other-root-id",
    )
    managed2.add_root(other_dir)
    conn.commit()

    # 刷新目录树以显示新根节点
    window._refresh_tree()  # noqa: SLF001
    qapp.processEvents()

    # 选中第一个根节点（[S]），切到整理模式
    model = window._tree_model  # noqa: SLF001
    # 按 real_path 排序，other_root 在 staging 之前（字母序）
    # 找到 staging 节点
    staging_idx = None
    other_idx = None
    for i in range(model.rowCount()):
        idx = model.index(i, 0)
        node = model.node_at(idx)
        if node is None:
            continue
        if "staging" in node.real_path:
            staging_idx = idx
        elif "other_root" in node.real_path:
            other_idx = idx

    assert staging_idx is not None, "未找到 staging 根节点"
    assert other_idx is not None, "未找到 other_root 根节点"

    # 选中 [S] 节点，切到整理模式
    window._tree_view.setCurrentIndex(staging_idx)  # noqa: SLF001
    qapp.processEvents()
    window._set_mode(AppMode.organize)  # noqa: SLF001
    qapp.processEvents()

    # 点击 other_root 节点（非 [S]）
    window._tree_view.setCurrentIndex(other_idx)  # noqa: SLF001
    qapp.processEvents()

    # 中栏内容应不变（仍为 staging 暂存区列表）
    entry_names = {window.entry_at(i).name for i in range(window.entry_count())}
    assert "mod1.7z" in entry_names  # 仍是 staging 列表

    # 提示应包含目标路径
    hint = window.mode_hint_full_text()
    assert "目标" in hint
    assert "other_root" in hint
