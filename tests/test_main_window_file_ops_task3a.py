"""MainWindow 文件操作集成测试（Stage 5 Task 3a）。

覆盖：
- _build_content_menu_actions：菜单项显示规则（注入 FileOperationService）
- _on_new_folder_in_dir：新建文件夹完整流程
- _on_rename_entry：重命名完整流程
- _on_delete_entries：删除（移至回收站）完整流程
- _show_empty_area_context_menu：空白区域右键新建文件夹
- 未注入 FileOperationService 时菜单项不显示

对话框通过 monkeypatch QInputDialog.getText（新建文件夹）/
MainWindow._show_rename_dialog（重命名）/ QMessageBox.question 模拟。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QInputDialog, QMessageBox  # noqa: E402

from app import ui_constants as ui  # noqa: E402
from app.main_window import MainWindow  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.file_operation_service import FileOperationService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from domain.models import FileEntry  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.folder_cache_sync_helper import FolderCacheSyncHelper  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.folder_cache import FolderCacheRepository  # noqa: E402
from infrastructure.repositories.managed_root import (  # noqa: E402
    ManagedRootRepository,
)
from infrastructure.repositories.operation_history import (  # noqa: E402
    OperationHistoryRepository,
)


def _make_tree(tmp_path: Path) -> Path:
    """构造测试目录树。"""
    root = tmp_path / "mods"
    root.mkdir()
    stash = root / "Stash"
    stash.mkdir()
    (stash / "BDOR Black Knight 1.0.7z").write_bytes(b"\x00" * 100)
    (stash / "preview.jpg").write_bytes(b"\x00" * 50)
    return root


@pytest.fixture
def file_ops_env(qapp, tmp_path: Path):
    """构造注入 FileOperationService 的 MainWindow 测试环境。"""
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
        now_provider=lambda: "2026-07-30T00:00:00Z",
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
        now_provider=lambda: "2026-07-30T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    file_op_service = FileOperationService(
        OperationHistoryRepository(conn),
        folder_cache_helper=FolderCacheSyncHelper(FolderCacheRepository(conn)),
        content_unit_repo=ContentUnitRepository(conn),
    )

    root_dir = _make_tree(tmp_path)
    root = managed_service.add_root(root_dir)
    scan_service.scan_root(root.id, incremental=False)
    conn.commit()

    window = MainWindow(
        managed_service,
        tree_service,
        content_service,
        db_path,
        commit_callback=conn.commit,
        file_operation_service=file_op_service,
    )
    yield window, conn, root_dir, root

    window.close()
    conn.close()


@pytest.fixture
def no_file_ops_env(qapp, tmp_path: Path):
    """构造未注入 FileOperationService 的 MainWindow 测试环境。"""
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
        now_provider=lambda: "2026-07-30T00:00:00Z",
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
        now_provider=lambda: "2026-07-30T00:00:00Z",
        uuid_provider=fake_uuid,
    )

    root_dir = _make_tree(tmp_path)
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
    yield window, conn, root_dir, root

    window.close()
    conn.close()


def _select_stash(qapp, window: MainWindow) -> None:
    """在目录树中选中 Stash 节点。"""
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


def _select_entry(qapp, window: MainWindow, name: str) -> FileEntry:
    """选中指定名称的条目，返回 FileEntry。"""
    model = window._content_list_model  # noqa: SLF001
    for row in range(model.entry_count()):
        entry = model.entry_at(row)
        if entry is not None and entry.name == name:
            idx = model.index(row, 0)
            window._content_view.setCurrentIndex(idx)  # noqa: SLF001
            qapp.processEvents()
            return entry
    pytest.fail(f"未找到条目：{name}")


def _menu_labels(window: MainWindow, entries: list[FileEntry]) -> list[str]:
    """获取 _build_content_menu_actions 返回的菜单项标签列表。"""
    actions = window._build_content_menu_actions(entries)  # noqa: SLF001
    return [label for label, _, _ in actions]


# === 菜单项显示规则 ===


class TestMenuStructure:
    """菜单项显示规则。"""

    def test_menu_includes_new_folder_rename_delete(self, qapp, file_ops_env) -> None:
        """注入 FileOperationService 后，单选条目显示新建文件夹/重命名/删除。"""
        window, _, _, _ = file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()
        entry = _select_entry(qapp, window, "preview.jpg")

        labels = _menu_labels(window, [entry])

        assert ui.MENU_NEW_FOLDER in labels
        assert ui.MENU_RENAME in labels
        assert ui.MENU_DELETE in labels

    def test_menu_includes_delete_only_for_multi_select(self, qapp, file_ops_env) -> None:
        """多选条目只显示删除（不显示新建文件夹/重命名）。"""
        window, _, _, _ = file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()
        e1 = _select_entry(qapp, window, "preview.jpg")
        # 选中第二个（用 FileEntry 直接构造）
        model = window._content_list_model  # noqa: SLF001
        e2 = None
        for row in range(model.entry_count()):
            entry = model.entry_at(row)
            if entry is not None and entry.name == "BDOR Black Knight 1.0.7z":
                e2 = entry
                break
        assert e2 is not None

        labels = _menu_labels(window, [e1, e2])

        assert ui.MENU_DELETE in labels
        assert ui.MENU_NEW_FOLDER not in labels
        assert ui.MENU_RENAME not in labels

    def test_menu_excludes_file_ops_when_not_injected(self, qapp, no_file_ops_env) -> None:
        """未注入 FileOperationService 时，菜单不显示新建/重命名/删除。"""
        window, _, _, _ = no_file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()
        entry = _select_entry(qapp, window, "preview.jpg")

        labels = _menu_labels(window, [entry])

        assert ui.MENU_NEW_FOLDER not in labels
        assert ui.MENU_RENAME not in labels
        assert ui.MENU_DELETE not in labels


# === 新建文件夹 ===


class TestNewFolder:
    """新建文件夹流程。"""

    def test_new_folder_from_entry_menu(self, qapp, file_ops_env, monkeypatch) -> None:
        """右键条目 → 新建文件夹：在条目父目录下创建。"""
        window, conn, root_dir, _ = file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()
        entry = _select_entry(qapp, window, "preview.jpg")

        # Mock QInputDialog.getText 返回 ("MyNewFolder", True)
        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("MyNewFolder", True))

        window._on_new_folder_for_entry(entry)  # noqa: SLF001
        qapp.processEvents()

        # 文件夹已创建
        new_folder = root_dir / "Stash" / "MyNewFolder"
        assert new_folder.is_dir()
        # operation_history 写入
        rows = conn.execute("SELECT * FROM operation_history").fetchall()
        assert len(rows) == 1
        assert rows[0]["operation_type"] == "new_folder"
        assert rows[0]["target_path"] == str(new_folder)

    def test_new_folder_cancel_dialog(self, qapp, file_ops_env, monkeypatch) -> None:
        """取消对话框不创建文件夹。"""
        window, _, root_dir, _ = file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()
        entry = _select_entry(qapp, window, "preview.jpg")

        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("", False))

        window._on_new_folder_for_entry(entry)  # noqa: SLF001
        qapp.processEvents()

        # Stash 下仍只有 2 个文件（BDOR + preview.jpg），无新文件夹创建
        children = list((root_dir / "Stash").iterdir())
        assert len(children) == 2

    def test_new_folder_empty_name_skipped(self, qapp, file_ops_env, monkeypatch) -> None:
        """输入空白名称不创建（对话框层拦截）。"""
        window, _, root_dir, _ = file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()
        entry = _select_entry(qapp, window, "preview.jpg")

        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("   ", True))

        window._on_new_folder_for_entry(entry)  # noqa: SLF001
        qapp.processEvents()

        # 无新文件夹创建
        children = list((root_dir / "Stash").iterdir())
        assert len(children) == 2

    def test_new_folder_refreshes_tree(self, qapp, file_ops_env, monkeypatch) -> None:
        """新建文件夹后目录树刷新显示新节点。"""
        window, _, root_dir, _ = file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()
        entry = _select_entry(qapp, window, "preview.jpg")

        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("TreeRefresh", True))

        window._on_new_folder_for_entry(entry)  # noqa: SLF001
        qapp.processEvents()

        # 目录树 Stash 子节点应包含 TreeRefresh
        model = window._tree_model  # noqa: SLF001
        root_idx = model.index(0, 0)
        model.fetchMore(root_idx)
        found = False
        for i in range(model.rowCount(root_idx)):
            child_idx = model.index(i, 0, root_idx)
            name = model.data(child_idx, Qt.DisplayRole)
            if name and "Stash" in name:
                model.fetchMore(child_idx)
                for j in range(model.rowCount(child_idx)):
                    grandchild_idx = model.index(j, 0, child_idx)
                    gc_name = model.data(grandchild_idx, Qt.DisplayRole)
                    if gc_name and "TreeRefresh" in gc_name:
                        found = True
                        break
        assert found, "新建文件夹未在目录树中显示"

    def test_new_folder_in_dir_directly(self, qapp, file_ops_env, monkeypatch) -> None:
        """_on_new_folder_in_dir 直接调用：在指定目录下创建。"""
        window, conn, root_dir, _ = file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()

        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("DirectFolder", True))

        window._on_new_folder_in_dir(str(root_dir / "Stash"))  # noqa: SLF001
        qapp.processEvents()

        assert (root_dir / "Stash" / "DirectFolder").is_dir()

    def test_new_folder_from_tree_context_menu(self, qapp, file_ops_env, monkeypatch) -> None:
        """目录树节点右键 → 新建文件夹：在选中节点目录下创建子文件夹。

        回归测试：Stage 5 Task 3a 验收发现目录树右键菜单缺少「新建文件夹」项，
        仅显示暂存区标记/资源管理器打开。修复后在 _on_tree_context_menu 中
        注入 FileOperationService 时显示「新建文件夹」。
        """
        window, conn, root_dir, _ = file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()

        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("TreeNewSub", True))

        # 模拟目录树右键菜单流程：选中 Stash 节点后通过 _on_tree_context_menu 触发
        # 直接调用 _on_new_folder_in_dir(node.real_path) 验证链路通畅
        model = window._tree_model  # noqa: SLF001
        root_idx = model.index(0, 0)
        model.fetchMore(root_idx)
        stash_node = None
        for i in range(model.rowCount(root_idx)):
            child_idx = model.index(i, 0, root_idx)
            name = model.data(child_idx, Qt.DisplayRole)
            if name and "Stash" in name:
                stash_node = model.node_at(child_idx)
                break
        assert stash_node is not None

        window._on_new_folder_in_dir(stash_node.real_path)  # noqa: SLF001
        qapp.processEvents()

        new_folder = root_dir / "Stash" / "TreeNewSub"
        assert new_folder.is_dir()
        # operation_history 写入 new_folder
        rows = conn.execute("SELECT * FROM operation_history").fetchall()
        assert len(rows) == 1
        assert rows[0]["operation_type"] == "new_folder"
        assert rows[0]["target_path"] == str(new_folder)


# === 重命名 ===


class TestRename:
    """重命名流程。"""

    def test_rename_file_success(self, qapp, file_ops_env, monkeypatch) -> None:
        """重命名文件：旧文件消失，新文件出现。"""
        window, conn, root_dir, _ = file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()
        entry = _select_entry(qapp, window, "preview.jpg")

        monkeypatch.setattr(window, "_show_rename_dialog", lambda old_name: ("renamed.jpg", True))

        window._on_rename_entry(entry)  # noqa: SLF001
        qapp.processEvents()

        old_path = root_dir / "Stash" / "preview.jpg"
        new_path = root_dir / "Stash" / "renamed.jpg"
        assert not old_path.exists()
        assert new_path.is_file()
        # operation_history 写入
        rows = conn.execute("SELECT * FROM operation_history").fetchall()
        assert len(rows) == 1
        assert rows[0]["operation_type"] == "rename"
        assert rows[0]["source_path"] == str(old_path)
        assert rows[0]["target_path"] == str(new_path)

    def test_rename_cancel_dialog(self, qapp, file_ops_env, monkeypatch) -> None:
        """取消对话框不重命名。"""
        window, _, root_dir, _ = file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()
        entry = _select_entry(qapp, window, "preview.jpg")

        monkeypatch.setattr(window, "_show_rename_dialog", lambda old_name: ("", False))

        window._on_rename_entry(entry)  # noqa: SLF001
        qapp.processEvents()

        # 原文件仍在
        assert (root_dir / "Stash" / "preview.jpg").is_file()

    def test_rename_same_name_skipped(self, qapp, file_ops_env, monkeypatch) -> None:
        """输入相同名称跳过（handler 层比较后 return）。"""
        window, conn, _, _ = file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()
        entry = _select_entry(qapp, window, "preview.jpg")

        monkeypatch.setattr(window, "_show_rename_dialog", lambda old_name: ("preview.jpg", True))

        window._on_rename_entry(entry)  # noqa: SLF001
        qapp.processEvents()

        # 无 operation_history 写入
        rows = conn.execute("SELECT * FROM operation_history").fetchall()
        assert len(rows) == 0

    def test_rename_conflict_shows_warning(self, qapp, file_ops_env, monkeypatch) -> None:
        """目标已存在 → 弹出 warning（不抛异常）。"""
        window, conn, root_dir, _ = file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()
        entry = _select_entry(qapp, window, "preview.jpg")

        # 预创建冲突文件
        (root_dir / "Stash" / "exists.jpg").write_bytes(b"existing")

        monkeypatch.setattr(window, "_show_rename_dialog", lambda old_name: ("exists.jpg", True))
        # Mock QMessageBox.information 避免阻塞（UX 重构 Phase 2 Task 5 Q3=C：warning→information）
        info_calls = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: info_calls.append(a))

        window._on_rename_entry(entry)  # noqa: SLF001
        qapp.processEvents()

        # 弹了 information
        assert len(info_calls) > 0
        # 原文件未改名
        assert (root_dir / "Stash" / "preview.jpg").is_file()

    def test_rename_refreshes_list(self, qapp, file_ops_env, monkeypatch) -> None:
        """重命名后中栏列表刷新，显示新名称。"""
        window, _, _, _ = file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()
        entry = _select_entry(qapp, window, "preview.jpg")

        monkeypatch.setattr(
            window, "_show_rename_dialog", lambda old_name: ("list_refresh.jpg", True)
        )

        window._on_rename_entry(entry)  # noqa: SLF001
        qapp.processEvents()

        # 列表中应能找到新名称
        model = window._content_list_model  # noqa: SLF001
        found = False
        for row in range(model.entry_count()):
            e = model.entry_at(row)
            if e is not None and e.name == "list_refresh.jpg":
                found = True
                break
        assert found, "重命名后列表未刷新显示新名称"


# === 删除 ===


class TestDelete:
    """删除（移至回收站）流程。"""

    def test_delete_single_file_success(self, qapp, file_ops_env, monkeypatch) -> None:
        """删除单个文件：文件消失，写 operation_history。"""
        window, conn, root_dir, _ = file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()
        entry = _select_entry(qapp, window, "preview.jpg")

        # Mock QMessageBox.question 返回 Yes
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes
        )

        window._on_delete_entries([entry])  # noqa: SLF001
        qapp.processEvents()

        # 文件已删除
        assert not (root_dir / "Stash" / "preview.jpg").exists()
        # operation_history 写入
        rows = conn.execute("SELECT * FROM operation_history").fetchall()
        assert len(rows) == 1
        assert rows[0]["operation_type"] == "delete"
        assert rows[0]["source_path"] == str(root_dir / "Stash" / "preview.jpg")
        assert rows[0]["target_path"] is None
        assert rows[0]["can_undo"] == 0

    def test_delete_cancel_confirmation(self, qapp, file_ops_env, monkeypatch) -> None:
        """用户在确认对话框选择 No → 不删除。"""
        window, conn, root_dir, _ = file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()
        entry = _select_entry(qapp, window, "preview.jpg")

        monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.No)

        window._on_delete_entries([entry])  # noqa: SLF001
        qapp.processEvents()

        # 文件仍在
        assert (root_dir / "Stash" / "preview.jpg").is_file()
        # 无 operation_history 写入
        rows = conn.execute("SELECT * FROM operation_history").fetchall()
        assert len(rows) == 0

    def test_delete_multiple_files(self, qapp, file_ops_env, monkeypatch) -> None:
        """批量删除多个文件。"""
        window, conn, root_dir, _ = file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()

        e1 = _select_entry(qapp, window, "preview.jpg")
        model = window._content_list_model  # noqa: SLF001
        e2 = None
        for row in range(model.entry_count()):
            entry = model.entry_at(row)
            if entry is not None and entry.name == "BDOR Black Knight 1.0.7z":
                e2 = entry
                break
        assert e2 is not None

        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes
        )

        window._on_delete_entries([e1, e2])  # noqa: SLF001
        qapp.processEvents()

        # 两个文件都已删除
        assert not (root_dir / "Stash" / "preview.jpg").exists()
        assert not (root_dir / "Stash" / "BDOR Black Knight 1.0.7z").exists()
        # 2 条 operation_history
        rows = conn.execute("SELECT * FROM operation_history").fetchall()
        assert len(rows) == 2
        for row in rows:
            assert row["operation_type"] == "delete"
            assert row["can_undo"] == 0

    def test_delete_refreshes_list(self, qapp, file_ops_env, monkeypatch) -> None:
        """删除后列表刷新，被删除的条目不再显示。"""
        window, _, _, _ = file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()
        entry = _select_entry(qapp, window, "preview.jpg")

        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes
        )

        window._on_delete_entries([entry])  # noqa: SLF001
        qapp.processEvents()

        # 列表中不再有 preview.jpg
        model = window._content_list_model  # noqa: SLF001
        for row in range(model.entry_count()):
            e = model.entry_at(row)
            assert e is not None
            assert e.name != "preview.jpg"


# === 空白区域右键菜单 ===


class TestEmptyAreaContextMenu:
    """空白区域右键菜单（仅新建文件夹）。"""

    def test_empty_area_menu_shows_new_folder(self, qapp, file_ops_env, monkeypatch) -> None:
        """空白区域右键 → 仅显示新建文件夹。"""
        window, conn, root_dir, _ = file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()

        # Mock QInputDialog
        monkeypatch.setattr(
            QInputDialog, "getText", lambda *args, **kwargs: ("EmptyAreaFolder", True)
        )

        # 直接调用 _on_new_folder_in_dir（模拟空白区域触发）
        current_dir = window._current_displayed_dir()  # noqa: SLF001
        assert current_dir is not None
        window._on_new_folder_in_dir(current_dir)  # noqa: SLF001
        qapp.processEvents()

        # 文件夹已创建
        assert (root_dir / "Stash" / "EmptyAreaFolder").is_dir()

    def test_current_displayed_dir_browse_mode(self, qapp, file_ops_env) -> None:
        """浏览模式：_current_displayed_dir 返回目录树选中节点。"""
        window, _, _, _ = file_ops_env
        _select_stash(qapp, window)
        qapp.processEvents()

        current = window._current_displayed_dir()  # noqa: SLF001
        assert current is not None
        assert "Stash" in current

    def test_current_displayed_dir_no_selection(self, qapp, file_ops_env) -> None:
        """无选中节点：返回 None。"""
        window, _, _, _ = file_ops_env
        # 不选中任何节点
        sm = window._tree_view.selectionModel()  # noqa: SLF001
        if sm is not None:
            sm.clear()

        current = window._current_displayed_dir()  # noqa: SLF001
        assert current is None
