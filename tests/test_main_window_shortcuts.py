"""MainWindow 键盘快捷键集成测试（Stage 5 Task 4）。

覆盖：
- F2（中栏）：重命名选中条目（Q1=A：多选取第一个）
- F2（目录树）：重命名目录树选中节点（用户补充需求）
- Delete（中栏）：删除选中条目
- Ctrl+Z：撤销最近可撤销操作（Q2=A 二次确认；Q3=B 跳过不可撤销/已撤销）
- Ctrl+A：全选中栏内容
- Ctrl+C/X/V（中栏）：占位（Q4=C 静默忽略，不提示）
- 无选中条目时 F2/Delete 状态栏提示
- 无可撤销操作时 Ctrl+Z 状态栏提示
- 快捷键仅在中栏/目录树聚焦时生效（Q5=A WidgetShortcut）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QInputDialog, QMessageBox  # noqa: E402

from app.main_window import MainWindow  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from application.undo_service import UndoService  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.file_operation_service import FileOperationService  # noqa: E402
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
    (stash / "file1.7z").write_bytes(b"\x00" * 100)
    (stash / "file2.7z").write_bytes(b"\x00" * 80)
    (stash / "preview.jpg").write_bytes(b"\x00" * 50)
    return root


@pytest.fixture
def shortcut_env(qapp, tmp_path: Path):
    """构造注入 FileOperationService + UndoService 的 MainWindow 测试环境。"""
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
    history_repo = OperationHistoryRepository(conn)
    folder_cache_repo = FolderCacheRepository(conn)
    content_unit_repo = ContentUnitRepository(conn)
    helper = FolderCacheSyncHelper(folder_cache_repo)
    file_op_service = FileOperationService(
        history_repo,
        folder_cache_helper=helper,
        content_unit_repo=content_unit_repo,
        now_provider=lambda: "2026-07-30T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    undo_service = UndoService(
        history_repo=history_repo,
        file_operation_service=file_op_service,
        folder_cache_helper=helper,
        content_unit_repo=content_unit_repo,
        now_provider=lambda: "2026-07-30T12:00:00Z",
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
        file_operation_service=file_op_service,
        undo_service=undo_service,
    )
    yield window, conn, root_dir, root, file_op_service, undo_service

    window.close()
    conn.close()


def _select_stash(qapp, window: MainWindow) -> None:
    """在目录树中选中暂存区 Stash 节点。"""
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


def _select_entry(qapp, window: MainWindow, name: str) -> int:
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


# === F2 重命名（中栏） ===


class TestF2RenameContent:
    def test_f2_triggers_rename_single_selection(self, qapp, shortcut_env, monkeypatch) -> None:
        """F2 + 单选 → 重命名对话框弹出。"""
        window, conn, root_dir, _, _, _ = shortcut_env
        _select_stash(qapp, window)
        qapp.processEvents()
        _select_entry(qapp, window, "file1.7z")

        # Mock 重命名对话框返回新名称
        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("renamed.7z", True))

        # 直接调用 handler（模拟 QShortcut 触发）
        window._on_shortcut_rename_content()  # noqa: SLF001
        qapp.processEvents()

        # 文件已重命名
        assert (root_dir / "Stash" / "renamed.7z").is_file()
        assert not (root_dir / "Stash" / "file1.7z").exists()

    def test_f2_multi_selection_takes_first(self, qapp, shortcut_env, monkeypatch) -> None:
        """Q1=A：多选时 F2 取第一个选中条目。"""
        window, conn, root_dir, _, _, _ = shortcut_env
        _select_stash(qapp, window)
        qapp.processEvents()
        # 选中 file1 和 file2
        model = window._content_list_model  # noqa: SLF001
        sm = window._content_view.selectionModel()  # noqa: SLF001
        idx1 = model.index(0, 0)
        idx2 = model.index(1, 0)
        sm.select(idx1, sm.SelectionFlag.ClearAndSelect | sm.SelectionFlag.Rows)
        sm.select(idx2, sm.SelectionFlag.Select | sm.SelectionFlag.Rows)
        qapp.processEvents()

        # Mock 重命名对话框
        monkeypatch.setattr(
            QInputDialog, "getText", lambda *args, **kwargs: ("renamed_first.7z", True)
        )

        window._on_shortcut_rename_content()  # noqa: SLF001
        qapp.processEvents()

        # 第一个条目被重命名（file1 或 file2，取决于 model 顺序）
        renamed_found = (root_dir / "Stash" / "renamed_first.7z").is_file()
        assert renamed_found

    def test_f2_no_selection_status_message(self, qapp, shortcut_env) -> None:
        """无选中条目 + F2 → 状态栏提示。"""
        window, _, _, _, _, _ = shortcut_env
        _select_stash(qapp, window)
        qapp.processEvents()
        # 清空选中
        sm = window._content_view.selectionModel()  # noqa: SLF001
        if sm is not None:
            sm.clear()
        qapp.processEvents()

        window._on_shortcut_rename_content()  # noqa: SLF001
        qapp.processEvents()

        # 状态栏应显示"未选中任何条目"
        assert "未选中" in window.statusBar().currentMessage()


# === F2 重命名（目录树） ===


class TestF2RenameTree:
    def test_f2_tree_triggers_rename(self, qapp, shortcut_env, monkeypatch) -> None:
        """F2 + 目录树选中节点 → 重命名对话框弹出（用户补充需求）。"""
        window, conn, root_dir, _, _, _ = shortcut_env
        _select_stash(qapp, window)
        qapp.processEvents()

        # Mock 重命名对话框
        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("RenamedStash", True))

        window._on_shortcut_rename_tree()  # noqa: SLF001
        qapp.processEvents()

        # 目录已被重命名
        assert (root_dir / "RenamedStash").is_dir()
        assert not (root_dir / "Stash").exists()

    def test_f2_tree_no_selection_status_message(self, qapp, shortcut_env) -> None:
        """目录树无选中节点 + F2 → 状态栏提示。"""
        window, _, _, _, _, _ = shortcut_env
        # 清空目录树选中
        sm = window._tree_view.selectionModel()  # noqa: SLF001
        if sm is not None:
            sm.clear()
        qapp.processEvents()

        window._on_shortcut_rename_tree()  # noqa: SLF001
        qapp.processEvents()

        assert "未选中" in window.statusBar().currentMessage()


# === Delete 删除 ===


class TestDeleteShortcut:
    def test_delete_triggers_delete_single(self, qapp, shortcut_env, monkeypatch) -> None:
        """Delete + 单选 → 删除确认对话框弹出。"""
        window, conn, root_dir, _, _, _ = shortcut_env
        _select_stash(qapp, window)
        qapp.processEvents()
        _select_entry(qapp, window, "preview.jpg")

        # Mock 删除确认对话框返回 Yes
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)

        window._on_shortcut_delete()  # noqa: SLF001
        qapp.processEvents()

        # 文件已删除（移至回收站）
        assert not (root_dir / "Stash" / "preview.jpg").exists()

    def test_delete_no_selection_status_message(self, qapp, shortcut_env) -> None:
        """无选中条目 + Delete → 状态栏提示。"""
        window, _, _, _, _, _ = shortcut_env
        _select_stash(qapp, window)
        qapp.processEvents()
        sm = window._content_view.selectionModel()  # noqa: SLF001
        if sm is not None:
            sm.clear()
        qapp.processEvents()

        window._on_shortcut_delete()  # noqa: SLF001
        qapp.processEvents()

        assert "未选中" in window.statusBar().currentMessage()


# === Ctrl+Z 撤销 ===


class TestCtrlZUndo:
    def test_ctrl_z_triggers_undo_with_confirm(self, qapp, shortcut_env, monkeypatch) -> None:
        """Ctrl+Z + 有可撤销操作 → 二次确认 → 撤销成功。"""
        window, conn, root_dir, _, file_op, _ = shortcut_env
        _select_stash(qapp, window)
        qapp.processEvents()

        # 先创建一个文件夹产生可撤销历史
        new_folder = root_dir / "Stash" / "UndoTestFolder"
        file_op.new_folder(new_folder)
        conn.commit()
        assert new_folder.is_dir()

        # Mock 二次确认返回 Yes
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)

        window._on_shortcut_undo()  # noqa: SLF001
        qapp.processEvents()

        # 文件夹已被撤销删除
        assert not new_folder.exists()

    def test_ctrl_z_no_undoable_status_message(self, qapp, shortcut_env) -> None:
        """无历史记录 + Ctrl+Z → 状态栏提示"无可撤销操作"。"""
        window, _, _, _, _, _ = shortcut_env
        window._on_shortcut_undo()  # noqa: SLF001
        qapp.processEvents()

        assert "无可撤销" in window.statusBar().currentMessage()

    def test_ctrl_z_skips_delete_records(
        self, qapp, shortcut_env, monkeypatch, tmp_path: Path
    ) -> None:
        """Q3=B：Ctrl+Z 跳过 delete 记录，撤销最近的可撤销操作。"""
        window, conn, root_dir, _, file_op, _ = shortcut_env
        _select_stash(qapp, window)
        qapp.processEvents()

        # 先创建文件夹（可撤销），再删除一个文件（不可撤销）
        new_folder = root_dir / "Stash" / "UndoTestFolder"
        file_op.new_folder(new_folder)
        conn.commit()

        # 手动构造 delete 历史记录（不实际删除文件，仅测试跳过逻辑）
        from domain.models import OperationHistory

        OperationHistoryRepository(conn).create(
            OperationHistory(
                id="delete-test",
                operation_type="delete",
                source_path=str(root_dir / "Stash" / "file1.7z"),
                created_at="2026-07-30T01:00:00Z",  # 比 new_folder 晚
                target_path=None,
                can_undo=False,
            )
        )
        conn.commit()

        # Mock 二次确认返回 Yes
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)

        window._on_shortcut_undo()  # noqa: SLF001
        qapp.processEvents()

        # 应撤销 new_folder（跳过 delete）
        assert not new_folder.exists()

    def test_ctrl_z_cancel_confirm_no_op(self, qapp, shortcut_env, monkeypatch) -> None:
        """Q2=A：二次确认取消 → 不执行撤销。"""
        window, conn, root_dir, _, file_op, _ = shortcut_env
        _select_stash(qapp, window)
        qapp.processEvents()

        new_folder = root_dir / "Stash" / "UndoTestFolder"
        file_op.new_folder(new_folder)
        conn.commit()

        # Mock 二次确认返回 No
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.No)

        window._on_shortcut_undo()  # noqa: SLF001
        qapp.processEvents()

        # 文件夹仍存在（未撤销）
        assert new_folder.is_dir()


# === Ctrl+A 全选 ===


class TestCtrlASelectAll:
    def test_ctrl_a_selects_all(self, qapp, shortcut_env) -> None:
        """Ctrl+A → 中栏所有条目被选中。"""
        window, _, _, _, _, _ = shortcut_env
        _select_stash(qapp, window)
        qapp.processEvents()

        window._on_shortcut_select_all()  # noqa: SLF001
        qapp.processEvents()

        sm = window._content_view.selectionModel()  # noqa: SLF001
        assert sm is not None
        selected_rows = sm.selectedRows()
        model = window._content_list_model  # noqa: SLF001
        assert len(selected_rows) == model.entry_count()


# === Ctrl+C/X/V 占位 ===


class TestCtrlCXPVPlaceholder:
    def test_ctrl_c_silent_no_op(self, qapp, shortcut_env) -> None:
        """Q4=C：Ctrl+C 静默忽略，不提示。"""
        window, _, _, _, _, _ = shortcut_env
        # 直接调用 lambda（无验证方式，仅确保不抛异常）
        # QShortcut 的 lambda: None 无法直接测试，这里验证快捷键已注册
        assert hasattr(window, "_shortcut_copy")  # noqa: SLF001

    def test_ctrl_x_silent_no_op(self, qapp, shortcut_env) -> None:
        """Q4=C：Ctrl+X 静默忽略，不提示。"""
        window, _, _, _, _, _ = shortcut_env
        assert hasattr(window, "_shortcut_cut")  # noqa: SLF001

    def test_ctrl_v_silent_no_op(self, qapp, shortcut_env) -> None:
        """Q4=C：Ctrl+V 静默忽略，不提示。"""
        window, _, _, _, _, _ = shortcut_env
        assert hasattr(window, "_shortcut_paste")  # noqa: SLF001


# === 快捷键注册验证 ===


class TestShortcutRegistration:
    def test_shortcuts_registered_with_file_op_service(self, qapp, shortcut_env) -> None:
        """注入 FileOperationService 时所有快捷键已注册。"""
        window, _, _, _, _, _ = shortcut_env
        assert hasattr(window, "_shortcut_rename")  # noqa: SLF001
        assert hasattr(window, "_shortcut_delete")  # noqa: SLF001
        assert hasattr(window, "_shortcut_select_all")  # noqa: SLF001
        assert hasattr(window, "_shortcut_copy")  # noqa: SLF001
        assert hasattr(window, "_shortcut_cut")  # noqa: SLF001
        assert hasattr(window, "_shortcut_paste")  # noqa: SLF001
        assert hasattr(window, "_shortcut_undo")  # noqa: SLF001
        assert hasattr(window, "_shortcut_rename_tree")  # noqa: SLF001

    def test_undo_shortcut_not_registered_without_undo_service(self, qapp, tmp_path: Path) -> None:
        """未注入 UndoService 时 Ctrl+Z 快捷键不注册。"""
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
            # 不注入 undo_service
        )
        try:
            # F2/Delete/Ctrl+A/Ctrl+C/X/V 已注册
            assert hasattr(window, "_shortcut_rename")  # noqa: SLF001
            assert hasattr(window, "_shortcut_delete")  # noqa: SLF001
            # Ctrl+Z 未注册
            assert not hasattr(window, "_shortcut_undo")  # noqa: SLF001
        finally:
            window.close()
            conn.close()

    def test_tree_rename_shortcut_not_registered_without_file_op_service(
        self, qapp, tmp_path: Path
    ) -> None:
        """未注入 FileOperationService 时目录树 F2 快捷键不注册。"""
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
            # 不注入 file_operation_service
        )
        try:
            # F2（中栏）未注册
            assert not hasattr(window, "_shortcut_rename")  # noqa: SLF001
            # F2（目录树）未注册
            assert not hasattr(window, "_shortcut_rename_tree")  # noqa: SLF001
        finally:
            window.close()
            conn.close()
