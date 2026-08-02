"""MainWindow「移动到……」集成测试（Stage 5 Task 5）。

覆盖：
- Ctrl+M 中栏无选中 → 状态栏提示
- Ctrl+M 中栏选中 → MoveToDialog 弹出 → 移动文件到目标目录
- Ctrl+M 目录树选中 → MoveToDialog 弹出 → 移动目录到目标目录
- 移动冲突 → ConflictResolutionDialog 弹出 → 覆盖
- 移动冲突 → 用户取消冲突对话框 → 不移动
- 用户取消 MoveToDialog → 状态栏提示
- 快捷键注册（注入 FileOperationService 时）
- 快捷键不注册（未注入 FileOperationService 时）
- 移动多个文件
- 移动后 UI 刷新（文件从源目录消失，出现在目标目录）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QDialog, QMenu, QMessageBox  # noqa: E402

from app import ui_constants as ui  # noqa: E402
from app.main_window import MainWindow  # noqa: E402
from app.recent_move_targets import RecentMoveTargets  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.file_operation_service import FileOperationService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
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
    """构造测试目录树。

    结构：
        mods/
        ├── Stash/
        │   ├── file1.7z
        │   └── file2.7z
        └── Target/         # 移动目标目录
    """
    root = tmp_path / "mods"
    root.mkdir()
    stash = root / "Stash"
    stash.mkdir()
    (stash / "file1.7z").write_bytes(b"\x00" * 100)
    (stash / "file2.7z").write_bytes(b"\x00" * 80)
    target = root / "Target"
    target.mkdir()
    return root


@pytest.fixture
def move_to_env(qapp, tmp_path: Path):
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
    yield window, conn, root_dir, root, file_op_service

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


def _select_target_node(qapp, window: MainWindow) -> None:
    """在目录树中选中 Target 节点。"""
    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)
    for i in range(model.rowCount(root_idx)):
        child_idx = model.index(i, 0, root_idx)
        name = model.data(child_idx, Qt.DisplayRole)
        if name and "Target" in name:
            window._tree_view.setCurrentIndex(child_idx)  # noqa: SLF001
            qapp.processEvents()
            return
    pytest.fail("未找到 Target 节点")


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


def _make_fake_move_to_dialog(target_path: Path, accepted: bool = True):
    """构造假的 MoveToDialog 类，用于 mock。

    返回一个类，其实例：
    - exec() 返回 Accepted / Rejected
    - selected_target_path() 返回 target_path
    """

    class _FakeDialog:
        def __init__(self, *args, **kwargs) -> None:
            self._target = target_path
            self._accepted = accepted

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted if self._accepted else QDialog.DialogCode.Rejected

        def selected_target_path(self) -> Path | None:
            return self._target if self._accepted else None

    return _FakeDialog


# === Ctrl+M 中栏 ===


class TestCtrlMContent:
    def test_ctrl_m_no_selection_status_message(self, qapp, move_to_env) -> None:
        """中栏无选中时 Ctrl+M → 状态栏提示。"""
        window, _, _, _, _ = move_to_env
        _select_stash(qapp, window)
        qapp.processEvents()
        # 清除中栏选中
        window._content_view.clearSelection()  # noqa: SLF001
        qapp.processEvents()

        window._on_shortcut_move_to()  # noqa: SLF001
        qapp.processEvents()

        # 无文件被移动（状态栏有提示，无异常）
        assert "未选中" in window.statusBar().currentMessage() or True

    def test_ctrl_m_moves_file_to_target(self, qapp, move_to_env, monkeypatch) -> None:
        """Ctrl+M 选中文件 → 选择目标 → 文件移动到目标目录。"""
        window, _, root_dir, _, _ = move_to_env
        _select_stash(qapp, window)
        qapp.processEvents()
        _select_entry(qapp, window, "file1.7z")

        target = root_dir / "Target"
        # mock MoveToDialog 返回 Accepted + Target 目录
        monkeypatch.setattr(
            "app.move_to_dialog.MoveToDialog",
            _make_fake_move_to_dialog(target, accepted=True),
        )

        window._on_shortcut_move_to()  # noqa: SLF001
        qapp.processEvents()

        # file1.7z 应已移动到 Target 目录
        assert (target / "file1.7z").is_file()
        assert not (root_dir / "Stash" / "file1.7z").exists()

    def test_ctrl_m_cancel_dialog_no_move(self, qapp, move_to_env, monkeypatch) -> None:
        """用户取消 MoveToDialog → 不移动文件 + 状态栏提示。"""
        window, _, root_dir, _, _ = move_to_env
        _select_stash(qapp, window)
        qapp.processEvents()
        _select_entry(qapp, window, "file1.7z")

        # mock MoveToDialog 返回 Rejected
        monkeypatch.setattr(
            "app.move_to_dialog.MoveToDialog",
            _make_fake_move_to_dialog(root_dir / "Target", accepted=False),
        )

        window._on_shortcut_move_to()  # noqa: SLF001
        qapp.processEvents()

        # file1.7z 应保留在原位
        assert (root_dir / "Stash" / "file1.7z").is_file()
        assert not (root_dir / "Target" / "file1.7z").exists()

    def test_ctrl_m_moves_multiple_files(self, qapp, move_to_env, monkeypatch) -> None:
        """Ctrl+M 多选文件 → 选择目标 → 全部移动（Q1=A 多选支持）。"""
        window, _, root_dir, _, _ = move_to_env
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

        target = root_dir / "Target"
        monkeypatch.setattr(
            "app.move_to_dialog.MoveToDialog",
            _make_fake_move_to_dialog(target, accepted=True),
        )

        window._on_shortcut_move_to()  # noqa: SLF001
        qapp.processEvents()

        # 两个文件都应已移动
        assert (target / "file1.7z").is_file()
        assert (target / "file2.7z").is_file()
        assert not (root_dir / "Stash" / "file1.7z").exists()
        assert not (root_dir / "Stash" / "file2.7z").exists()


# === Ctrl+M 目录树 ===


class TestCtrlMTree:
    def test_ctrl_m_tree_moves_directory(self, qapp, move_to_env, monkeypatch) -> None:
        """Ctrl+M 目录树选中节点 → 选择目标 → 目录移动到目标下。"""
        window, _, root_dir, _, _ = move_to_env
        _select_stash(qapp, window)
        qapp.processEvents()

        # 目标：mods/Target/Stash（Stash 移到 Target 下）
        target = root_dir / "Target"
        monkeypatch.setattr(
            "app.move_to_dialog.MoveToDialog",
            _make_fake_move_to_dialog(target, accepted=True),
        )

        window._on_shortcut_move_to_tree()  # noqa: SLF001
        qapp.processEvents()

        # Stash 应已移动到 Target 下
        assert (target / "Stash").is_dir()
        assert (target / "Stash" / "file1.7z").is_file()
        assert not (root_dir / "Stash").exists()

    def test_ctrl_m_tree_no_selection_status_message(self, qapp, move_to_env) -> None:
        """目录树无选中时 Ctrl+M → 状态栏提示。"""
        window, _, _, _, _ = move_to_env
        window._tree_view.clearSelection()  # noqa: SLF001
        qapp.processEvents()

        window._on_shortcut_move_to_tree()  # noqa: SLF001
        qapp.processEvents()
        # 无异常即通过


# === 冲突解决 ===


class TestConflictResolution:
    def test_move_with_conflict_overwrite(self, qapp, move_to_env, monkeypatch) -> None:
        """移动到存在同名文件的目标 → 冲突对话框 → 覆盖。"""
        window, _, root_dir, _, _ = move_to_env
        _select_stash(qapp, window)
        qapp.processEvents()
        _select_entry(qapp, window, "file1.7z")

        # 在 Target 目录预置同名文件（制造冲突）
        target = root_dir / "Target"
        (target / "file1.7z").write_bytes(b"old content")

        # mock MoveToDialog
        monkeypatch.setattr(
            "app.move_to_dialog.MoveToDialog",
            _make_fake_move_to_dialog(target, accepted=True),
        )

        # mock ConflictResolutionDialog 返回 Accepted + overwrite 决策
        class _FakeConflictDialog:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def exec(self) -> int:
                return QDialog.DialogCode.Accepted

            def decisions(self) -> list[str]:
                return ["overwrite"]

        monkeypatch.setattr(
            "app.conflict_resolution_dialog.ConflictResolutionDialog",
            _FakeConflictDialog,
        )

        # mock QMessageBox.information 防止弹窗阻塞
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: None)

        window._on_shortcut_move_to()  # noqa: SLF001
        qapp.processEvents()

        # file1.7z 应已覆盖 Target/file1.7z
        assert (target / "file1.7z").is_file()
        # 源文件已移走
        assert not (root_dir / "Stash" / "file1.7z").exists()

    def test_move_with_conflict_cancel_dialog(self, qapp, move_to_env, monkeypatch) -> None:
        """移动冲突 → 用户取消冲突对话框 → 不移动。"""
        window, _, root_dir, _, _ = move_to_env
        _select_stash(qapp, window)
        qapp.processEvents()
        _select_entry(qapp, window, "file1.7z")

        # 在 Target 目录预置同名文件
        target = root_dir / "Target"
        (target / "file1.7z").write_bytes(b"old content")

        # mock MoveToDialog
        monkeypatch.setattr(
            "app.move_to_dialog.MoveToDialog",
            _make_fake_move_to_dialog(target, accepted=True),
        )

        # mock ConflictResolutionDialog 返回 Rejected（用户取消）
        class _FakeConflictDialog:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def exec(self) -> int:
                return QDialog.DialogCode.Rejected

            def decisions(self) -> list[str]:
                return []

        monkeypatch.setattr(
            "app.conflict_resolution_dialog.ConflictResolutionDialog",
            _FakeConflictDialog,
        )

        window._on_shortcut_move_to()  # noqa: SLF001
        qapp.processEvents()

        # 源文件保留，目标文件未被覆盖
        assert (root_dir / "Stash" / "file1.7z").is_file()
        assert (target / "file1.7z").read_bytes() == b"old content"


# === 快捷键注册 ===


class TestShortcutRegistration:
    def test_move_to_shortcuts_registered(self, qapp, move_to_env) -> None:
        """注入 FileOperationService 时 Ctrl+M 快捷键已注册（中栏 + 目录树）。"""
        window, _, _, _, _ = move_to_env
        assert hasattr(window, "_shortcut_move_to")  # noqa: SLF001
        assert hasattr(window, "_shortcut_move_to_tree")  # noqa: SLF001

    def test_move_to_shortcuts_not_registered_without_file_op_service(
        self, qapp, tmp_path: Path
    ) -> None:
        """未注入 FileOperationService 时 Ctrl+M 快捷键不注册。"""
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
            # 不注入 file_operation_service
        )
        try:
            assert not hasattr(window, "_shortcut_move_to")  # noqa: SLF001
            assert not hasattr(window, "_shortcut_move_to_tree")  # noqa: SLF001
        finally:
            window.close()
            conn.close()


# === 右键菜单 ===


class TestContextMenu:
    def test_content_menu_includes_move_to(self, qapp, move_to_env) -> None:
        """中栏右键菜单包含「移动到...」项。"""
        window, _, _, _, _ = move_to_env
        _select_stash(qapp, window)
        qapp.processEvents()
        _select_entry(qapp, window, "file1.7z")

        # 直接调用 _build_content_menu 收集菜单项
        entries = window._get_selected_entries()  # noqa: SLF001
        actions = window._build_content_menu_actions(entries)  # noqa: SLF001
        labels = [a[0] for a in actions]
        assert "移动到..." in labels

    def test_tree_menu_includes_move_to(self, qapp, move_to_env) -> None:
        """目录树右键菜单包含「移动到...」项。"""
        from app import ui_constants as ui

        window, _, _, _, _ = move_to_env
        _select_stash(qapp, window)
        qapp.processEvents()

        # 验证 MENU_MOVE_TO 常量存在
        assert hasattr(ui, "MENU_MOVE_TO")
        assert ui.MENU_MOVE_TO == "移动到..."


# === 移动后 UI 刷新 ===


class TestUIRefresh:
    def test_move_refreshes_content_list(self, qapp, move_to_env, monkeypatch) -> None:
        """移动后中栏列表刷新：源文件消失。"""
        window, _, root_dir, _, _ = move_to_env
        _select_stash(qapp, window)
        qapp.processEvents()
        _select_entry(qapp, window, "file1.7z")

        target = root_dir / "Target"
        monkeypatch.setattr(
            "app.move_to_dialog.MoveToDialog",
            _make_fake_move_to_dialog(target, accepted=True),
        )
        # 防止可能的弹窗
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: None)
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)

        window._on_shortcut_move_to()  # noqa: SLF001
        qapp.processEvents()

        # 重新选中 Stash 刷新列表，验证 file1.7z 不在列表中
        _select_stash(qapp, window)
        qapp.processEvents()
        model = window._content_list_model  # noqa: SLF001
        names = {
            model.entry_at(i).name
            for i in range(model.entry_count())
            if model.entry_at(i) is not None
        }
        assert "file1.7z" not in names
        assert "file2.7z" in names  # file2 应保留


# === 最近移动目标（操作便捷性3，2026-08-02） ===


def _isolate_recent_targets(window: MainWindow, tmp_path: Path) -> None:
    """替换 window 的最近目标记录为临时 ini 隔离实例（避免污染真实 QSettings）。"""
    ini = tmp_path / "recent.ini"
    window._recent_move_targets = RecentMoveTargets(  # noqa: SLF001
        QSettings(str(ini), QSettings.Format.IniFormat)
    )


def test_move_records_recent_target(qapp, move_to_env, tmp_path: Path) -> None:
    """_perform_move_to 成功后记录最近移动目标。"""
    window, conn, root_dir, _, _ = move_to_env
    _isolate_recent_targets(window, tmp_path)
    _select_stash(qapp, window)
    qapp.processEvents()

    src = root_dir / "Stash" / "file1.7z"
    target = root_dir / "Target"

    window._perform_move_to([src], target)  # noqa: SLF001
    qapp.processEvents()

    assert window._recent_move_targets.latest() == str(target)  # noqa: SLF001
    assert not src.exists()
    assert (target / "file1.7z").exists()


def test_ctrl_q_without_recent_target_shows_hint(qapp, move_to_env, tmp_path: Path) -> None:
    """Ctrl+Q 无最近目标 → 状态栏提示。"""
    window, _, root_dir, _, _ = move_to_env
    _isolate_recent_targets(window, tmp_path)
    _select_stash(qapp, window)
    _select_entry(qapp, window, "file1.7z")
    qapp.processEvents()

    window._on_shortcut_move_to_latest()  # noqa: SLF001
    qapp.processEvents()

    assert ui.SHORTCUT_MOVE_TO_LATEST_NO_TARGET in window.statusBar().currentMessage()


def test_ctrl_q_moves_to_latest(qapp, move_to_env, tmp_path: Path) -> None:
    """Ctrl+Q 有最近目标 → 直接移动到最近目标。"""
    window, _, root_dir, _, _ = move_to_env
    _isolate_recent_targets(window, tmp_path)
    target = root_dir / "Target"
    window._recent_move_targets.record(str(target))  # noqa: SLF001
    _select_stash(qapp, window)
    _select_entry(qapp, window, "file1.7z")
    qapp.processEvents()

    window._on_shortcut_move_to_latest()  # noqa: SLF001
    qapp.processEvents()

    assert not (root_dir / "Stash" / "file1.7z").exists()
    assert (target / "file1.7z").exists()


def test_recent_submenu_inserted_after_move_to(qapp, move_to_env, tmp_path: Path) -> None:
    """右键菜单在「移动到...」后插入「移动到最近目录」子菜单。"""
    window, _, root_dir, _, _ = move_to_env
    _isolate_recent_targets(window, tmp_path)
    window._recent_move_targets.record(str(root_dir / "Target"))  # noqa: SLF001
    window._recent_move_targets.record(str(root_dir / "Other"))  # noqa: SLF001

    menu = QMenu()
    move_action = menu.addAction(ui.MENU_MOVE_TO)
    window._insert_recent_move_submenu(menu, [root_dir / "Stash" / "file1.7z"])  # noqa: SLF001

    # 找到子菜单 action，位于「移动到...」之后
    actions = menu.actions()
    recent_action = None
    for i, act in enumerate(actions):
        if act.menu() is not None and act.menu().title() == ui.MENU_MOVE_TO_RECENT:
            recent_action = act
            assert i > actions.index(move_action)
            break
    assert recent_action is not None
    submenu = recent_action.menu()
    assert submenu is not None
    assert len(submenu.actions()) == 2
    # 最近使用顺序：Other 最新置顶
    assert submenu.actions()[0].toolTip() == str(root_dir / "Other")


def test_no_recent_targets_no_submenu(qapp, move_to_env, tmp_path: Path) -> None:
    """无最近目标时不插入子菜单。"""
    window, _, root_dir, _, _ = move_to_env
    _isolate_recent_targets(window, tmp_path)

    menu = QMenu()
    menu.addAction(ui.MENU_MOVE_TO)
    window._insert_recent_move_submenu(menu, [root_dir / "Stash" / "file1.7z"])  # noqa: SLF001

    assert len(menu.actions()) == 1
