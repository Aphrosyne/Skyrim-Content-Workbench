"""MainWindow 暂存区右键菜单集成测试（阶段 3 Task 1）。

覆盖：
- 标记暂存区 → 目录树节点显示 [S] 前缀；
- 取消暂存区标记 → [S] 前缀消失；
- 未注入 StagingService 时 _on_tree_context_menu 直接 return；
- 嵌套拒绝：祖先已标记时，标记子目录弹 QMessageBox.warning；
- 重启后保留：重新构造 MainWindow + StagingService，标记仍生效；
- 中文路径正确标记。

测试不模拟 QMenu 弹窗（模态），直接调用 _mark_staging_from_node /
_unmark_staging_from_node 验证业务联动。嵌套拒绝场景用 monkeypatch
替换 QMessageBox.warning 防止阻塞。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app.main_window import MainWindow  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from application.staging_service import StagingService  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.folder_cache import FolderCacheRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402
from infrastructure.repositories.staging_area import StagingAreaRepository  # noqa: E402


def _make_mod_tree(tmp_path: Path) -> Path:
    """构造测试目录树（含中文目录 + 子目录便于嵌套测试）。

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


def _build_services(conn: sqlite3.Connection, db_path: Path):
    """构造一套服务（managed/tree/content/scan/staging），共享同一 conn。"""
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
    return managed_service, tree_service, content_service, scan_service, staging_service


@pytest.fixture
def staging_window_env(qapp, tmp_path: Path):
    """构造注入了 StagingService 的 MainWindow 测试环境（已扫描）。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row

    managed_service, tree_service, content_service, scan_service, staging_service = _build_services(
        conn, db_path
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
        staging_service=staging_service,
    )
    yield window, conn, root_dir, db_path, staging_service

    window.close()
    conn.close()


def _select_root(qapp: QApplication, window: MainWindow) -> None:
    """选中目录树根节点并处理事件。"""
    model = window._tree_model  # noqa: SLF001
    idx = model.index(0, 0)
    window._tree_view.setCurrentIndex(idx)  # noqa: SLF001
    qapp.processEvents()


def _expand_root_and_get_child(qapp: QApplication, window: MainWindow, child_name_substr: str):
    """展开根节点并返回匹配名称的子节点 TreeNode。"""
    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)
    qapp.processEvents()
    for i in range(model.rowCount(root_idx)):
        child_idx = model.index(i, 0, root_idx)
        node = model.node_at(child_idx)
        if node is not None and child_name_substr in node.display_name:
            return node, child_idx
    pytest.fail(f"未找到包含 {child_name_substr!r} 的子节点")


# === 测试 ===


def test_mark_staging_shows_prefix(qapp: QApplication, staging_window_env) -> None:
    """标记暂存区 → 目录树根节点 display 含 [S] 前缀。"""
    window, _, _, _, staging_service = staging_window_env
    _select_root(qapp, window)

    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    root_node = model.node_at(root_idx)
    assert root_node is not None
    assert root_node.is_staging is False  # 初始未标记

    # 直接调用标记方法（绕过 QMenu 弹窗）
    window._mark_staging_from_node(root_node)  # noqa: SLF001
    qapp.processEvents()

    # 服务层已记录
    assert staging_service.is_staging(Path(root_node.real_path)) is True

    # refresh 后旧 QModelIndex 失效，必须重新获取 index 再读取 data
    fresh_root_idx = model.index(0, 0)
    display = model.data(fresh_root_idx, Qt.DisplayRole)
    assert display is not None
    assert display.startswith("[S] ")


def test_unmark_staging_removes_prefix(qapp: QApplication, staging_window_env) -> None:
    """取消暂存区标记 → [S] 前缀消失。"""
    window, _, _, _, _ = staging_window_env
    _select_root(qapp, window)

    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    root_node = model.node_at(root_idx)
    assert root_node is not None

    # 先标记
    window._mark_staging_from_node(root_node)  # noqa: SLF001
    qapp.processEvents()
    # refresh 后旧 index 失效，重新获取
    assert model.data(model.index(0, 0), Qt.DisplayRole).startswith("[S] ")  # type: ignore[union-attr]

    # 重新读取根节点（refresh 后 TreeNode 已替换为新对象）
    root_node_after = model.node_at(model.index(0, 0))
    assert root_node_after is not None
    assert root_node_after.is_staging is True

    # 取消标记
    window._unmark_staging_from_node(root_node_after)  # noqa: SLF001
    qapp.processEvents()

    # display 不再含 [S] 前缀（refresh 后再次重新获取 index）
    display = model.data(model.index(0, 0), Qt.DisplayRole)
    assert display is not None
    assert not display.startswith("[S] ")


def test_context_menu_noop_without_staging_service(qapp: QApplication, tmp_path: Path) -> None:
    """未注入 StagingService 时 _on_tree_context_menu 直接 return，不崩溃。"""
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
        # 不注入 staging_service
    )
    content_service = ContentService(ContentUnitRepository(conn))

    window = MainWindow(
        managed_service,
        tree_service,
        content_service,
        db_path,
        commit_callback=conn.commit,
        # 不传 staging_service
    )

    # 直接调用 _on_tree_context_menu 不应抛异常（早 return）
    from PySide6.QtCore import QPoint

    window._on_tree_context_menu(QPoint(0, 0))  # noqa: SLF001
    qapp.processEvents()

    window.close()
    conn.close()


def test_nested_staging_rejected(qapp: QApplication, staging_window_env, monkeypatch) -> None:
    """祖先已标记时，标记子目录弹 QMessageBox.warning（嵌套拒绝）。"""
    window, _, _, _, _ = staging_window_env
    _select_root(qapp, window)

    # 先标记根节点 mods
    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    root_node = model.node_at(root_idx)
    assert root_node is not None
    window._mark_staging_from_node(root_node)  # noqa: SLF001
    qapp.processEvents()

    # 找到子节点 "护甲"
    child_node, _ = _expand_root_and_get_child(qapp, window, "护甲")
    assert child_node is not None

    # monkeypatch QMessageBox.warning 记录调用，防止模态阻塞
    warnings: list[tuple] = []

    def fake_warning(parent, title, text, *args, **kwargs):
        warnings.append((title, text))
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)

    # 标记子节点应被拒绝（祖先 mods 已是暂存区）
    window._mark_staging_from_node(child_node)  # noqa: SLF001
    qapp.processEvents()

    assert len(warnings) == 1, "嵌套拒绝应弹一次 QMessageBox.warning"
    title, text = warnings[0]
    assert "无法标记" in title
    assert "嵌套" in text or "祖先" in text


def test_staging_persists_after_restart(
    qapp: QApplication, staging_window_env, tmp_path: Path
) -> None:
    """标记暂存区后重启 MainWindow（重新构造服务），标记仍生效。"""
    window, _, root_dir, db_path, _ = staging_window_env
    _select_root(qapp, window)

    # 标记根节点
    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    root_node = model.node_at(root_idx)
    assert root_node is not None
    window._mark_staging_from_node(root_node)  # noqa: SLF001
    qapp.processEvents()
    # refresh 后旧 index 失效，重新获取
    assert model.data(model.index(0, 0), Qt.DisplayRole).startswith("[S] ")  # type: ignore[union-attr]

    # 关闭旧窗口与连接
    window.close()

    # 重新打开同一数据库，构造新服务（模拟应用重启）
    conn2 = get_connection(db_path)
    conn2.row_factory = sqlite3.Row
    managed2, tree2, content2, _, staging2 = _build_services(conn2, db_path)

    window2 = MainWindow(
        managed2,
        tree2,
        content2,
        db_path,
        commit_callback=conn2.commit,
        staging_service=staging2,
    )
    qapp.processEvents()

    # 新窗口目录树根节点应仍显示 [S] 前缀
    model2 = window2._tree_model  # noqa: SLF001
    root_idx2 = model2.index(0, 0)
    display2 = model2.data(root_idx2, Qt.DisplayRole)
    assert display2 is not None
    assert display2.startswith("[S] ")

    # 服务层也确认标记仍在
    assert staging2.is_staging(root_dir) is True

    window2.close()
    conn2.close()


def test_mark_chinese_path(qapp: QApplication, staging_window_env) -> None:
    """中文路径目录可正确标记为暂存区。"""
    window, _, _, _, staging_service = staging_window_env
    _select_root(qapp, window)

    # 展开根节点找到 "护甲" 子目录（中文路径）
    child_node, _ = _expand_root_and_get_child(qapp, window, "护甲")
    assert child_node is not None
    assert "护甲" in child_node.real_path

    window._mark_staging_from_node(child_node)  # noqa: SLF001
    qapp.processEvents()

    assert staging_service.is_staging(Path(child_node.real_path)) is True


def test_unmark_nonexistent_staging_shows_warning(
    qapp: QApplication, staging_window_env, monkeypatch
) -> None:
    """取消未标记的节点 → 弹"未找到该目录的暂存区标记"提示。"""
    window, _, _, _, _ = staging_window_env
    _select_root(qapp, window)

    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    root_node = model.node_at(root_idx)
    assert root_node is not None
    assert root_node.is_staging is False  # 未标记

    warnings: list[tuple] = []

    def fake_warning(parent, title, text, *args, **kwargs):
        warnings.append((title, text))
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)

    # 直接调用取消方法（节点未标记）
    window._unmark_staging_from_node(root_node)  # noqa: SLF001
    qapp.processEvents()

    assert len(warnings) == 1
    title, text = warnings[0]
    assert "未找到" in text


def test_mark_staging_persists_in_db(qapp: QApplication, staging_window_env) -> None:
    """标记后数据库 staging_area 表有对应记录。"""
    window, conn, _, _, staging_service = staging_window_env
    _select_root(qapp, window)

    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    root_node = model.node_at(root_idx)
    assert root_node is not None

    window._mark_staging_from_node(root_node)  # noqa: SLF001
    qapp.processEvents()

    # 直接查询数据库确认记录存在
    rows = conn.execute("SELECT COUNT(*) AS n FROM staging_area").fetchone()
    assert rows["n"] == 1

    # list_staging 返回 1 条
    stagings = staging_service.list_staging()
    assert len(stagings) == 1
    assert Path(stagings[0].real_path) == Path(root_node.real_path)
