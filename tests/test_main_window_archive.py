"""MainWindow 归档功能（功能增加1，2026-08-04）集成测试。

覆盖：
- 中栏/目录树右键菜单项（快速归档 / 归档到… / 标记/取消归档根 / 生成清单）
- 标记归档根目录：QSettings 写入 + 立即清除根内内容单元标记
- 取消归档根目录标记
- 快速归档 Ctrl+W：有上次归档位置直接移动 + 删除内容单元标记 + 记录历史
- 快速归档无上次归档位置 → 打开归档选择对话框
- 归档文件夹后其内部子项标记一并清除
- 生成归档内容清单
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QDialog  # noqa: E402

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
    """构造测试目录树：
    mods/
    ├── Stash/
    │   ├── file1.7z
    │   ├── file2.7z
    │   └── group/            # 普通文件夹，内含压缩包
    │       └── inner.7z
    ├── Target/               # 普通移动目标
    └── 99_归档/              # 归档根目录
        └── 批次/             # 手动子目录（批次粒度）
    """
    root = tmp_path / "mods"
    root.mkdir()
    stash = root / "Stash"
    stash.mkdir()
    (stash / "file1.7z").write_bytes(b"\x00" * 100)
    (stash / "file2.7z").write_bytes(b"\x00" * 80)
    group = stash / "group"
    group.mkdir()
    (group / "inner.7z").write_bytes(b"\x00" * 60)
    (root / "Target").mkdir()
    archive_root = root / "99_归档"
    archive_root.mkdir()
    (archive_root / "批次").mkdir()
    (archive_root / "旧包.7z").write_bytes(b"\x00" * 40)
    return root


@pytest.fixture
def archive_env(qapp, tmp_path: Path):
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
        now_provider=lambda: "2026-08-04T00:00:00Z",
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
        now_provider=lambda: "2026-08-04T00:00:00Z",
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
    yield window, conn, root_dir

    window.close()
    conn.close()


def _select_tree_node(qapp, window: MainWindow, name: str) -> None:
    """在目录树中选中指定名称的节点。"""
    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)
    for i in range(model.rowCount(root_idx)):
        child_idx = model.index(i, 0, root_idx)
        display = model.data(child_idx, Qt.DisplayRole)
        if display and name in display:
            window._tree_view.setCurrentIndex(child_idx)  # noqa: SLF001
            qapp.processEvents()
            return
    pytest.fail(f"未找到目录树节点：{name}")


def _select_root_node(qapp, window: MainWindow) -> None:
    """在目录树中选中受管理根目录节点。"""
    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    window._tree_view.setCurrentIndex(root_idx)  # noqa: SLF001
    qapp.processEvents()


def _find_tree_node_index(window: MainWindow, name: str):
    """返回目录树中名称匹配的节点 QModelIndex。"""
    model = window._tree_model  # noqa: SLF001
    root_idx = model.index(0, 0)
    model.fetchMore(root_idx)
    for i in range(model.rowCount(root_idx)):
        child_idx = model.index(i, 0, root_idx)
        display = model.data(child_idx, Qt.DisplayRole)
        if display and name in display:
            return child_idx
    pytest.fail(f"未找到目录树节点：{name}")


def _find_entry_by_name(window: MainWindow, name: str) -> FileEntry | None:
    """在中栏查找指定名称的条目。"""
    model = window._content_list_model  # noqa: SLF001
    for row in range(model.entry_count()):
        entry = model.entry_at(row)
        if entry is not None and entry.name == name:
            return entry
    return None


def _make_fake_move_to_dialog(target_path: Path, accepted: bool = True):
    """构造假的 MoveToDialog 类（同 test_main_window_move_to 模式）。"""

    class _FakeDialog:
        def __init__(self, *args, **kwargs) -> None:
            self._target = target_path
            self._accepted = accepted

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted if self._accepted else QDialog.DialogCode.Rejected

        def selected_target_path(self) -> Path | None:
            return self._target if self._accepted else None

    return _FakeDialog


def _content_unit_exists(conn: sqlite3.Connection, path: Path) -> bool:
    """按路径查询 content_unit 记录是否存在。"""
    row = conn.execute("SELECT id FROM content_unit WHERE path = ?", (str(path),)).fetchone()
    return row is not None


class TestArchiveMenu:
    def test_content_menu_shows_quick_and_archive_to(self, qapp, archive_env) -> None:
        """中栏任意选中项 → 显示「快速归档」「归档到…」。"""
        window, _, root_dir = archive_env
        _select_tree_node(qapp, window, "Stash")
        qapp.processEvents()
        entry = _find_entry_by_name(window, "file1.7z")
        assert entry is not None

        labels = [a[0] for a in window._build_content_menu_actions([entry])]  # noqa: SLF001
        assert ui.MENU_ARCHIVE_QUICK in labels
        assert ui.MENU_ARCHIVE_TO in labels

    def test_single_folder_shows_mark_archive_root(self, qapp, archive_env) -> None:
        """单选普通文件夹 → 显示「标记为归档根目录」。"""
        window, _, root_dir = archive_env
        _select_tree_node(qapp, window, "Stash")
        qapp.processEvents()
        entry = _find_entry_by_name(window, "group")
        assert entry is not None and entry.is_dir

        labels = [a[0] for a in window._build_content_menu_actions([entry])]  # noqa: SLF001
        assert ui.MENU_MARK_ARCHIVE_ROOT in labels
        assert ui.MENU_UNMARK_ARCHIVE_ROOT not in labels

    def test_archive_root_folder_shows_unmark_and_manifest(self, qapp, archive_env) -> None:
        """单选已标记归档根 → 显示「取消归档根目录标记」+「生成归档内容清单」。"""
        window, _, root_dir = archive_env
        archive_root = root_dir / "99_归档"
        window._archive_settings.set_root(archive_root)  # noqa: SLF001
        _select_root_node(qapp, window)
        qapp.processEvents()
        entry = _find_entry_by_name(window, "99_归档")
        assert entry is not None and entry.is_dir

        labels = [a[0] for a in window._build_content_menu_actions([entry])]  # noqa: SLF001
        assert ui.MENU_UNMARK_ARCHIVE_ROOT in labels
        assert ui.MENU_GENERATE_ARCHIVE_MANIFEST in labels
        assert ui.MENU_MARK_ARCHIVE_ROOT not in labels

    def test_tree_menu_has_archive_entries(self, qapp, archive_env, monkeypatch) -> None:
        """目录树节点右键 → 显示快速归档 / 归档到… / 标记归档根。"""
        window, _, root_dir = archive_env
        _select_tree_node(qapp, window, "Stash")
        qapp.processEvents()

        menu_items: list[str] = []

        class _FakeAction:
            def __init__(self, text: str) -> None:
                self._text = text

            def text(self) -> str:
                return self._text

            def setEnabled(self, enabled: bool) -> None:
                pass

        class _FakeMenu:
            def __init__(self, *args, **kwargs) -> None:
                self._actions = []
                self._title = args[0] if args else ""

            def addAction(self, label):
                act = _FakeAction(label)
                self._actions.append(act)
                return act

            def actions(self):
                return list(self._actions)

            def insertMenu(self, before_action, submenu) -> None:
                idx = self._actions.index(before_action)
                self._actions.insert(idx, _FakeAction(f"<submenu:{submenu._title}>"))

            def addMenu(self, submenu) -> None:
                self._actions.append(_FakeAction(f"<submenu:{submenu._title}>"))

            def addSeparator(self) -> None:
                self._actions.append(_FakeAction("<separator>"))

            def exec(self, *args, **kwargs):
                menu_items.extend(a.text() for a in self._actions)
                return None

        import app.main_window as mw_module

        original_menu = mw_module.QMenu
        mw_module.QMenu = _FakeMenu  # noqa: SLF001
        try:
            window._on_tree_context_menu(QPoint(5, 5))  # noqa: SLF001
        finally:
            mw_module.QMenu = original_menu  # noqa: SLF001

        assert ui.MENU_ARCHIVE_QUICK in menu_items
        assert ui.MENU_ARCHIVE_TO in menu_items
        assert ui.MENU_MARK_ARCHIVE_ROOT in menu_items


class TestInsideArchiveRootMenu:
    """归档根内部条目的右键菜单规则（功能增加1，2026-08-04）。"""

    def test_inside_subfolder_shows_manifest_only(self, qapp, archive_env) -> None:
        """归档根内子文件夹：仅「生成归档内容清单」，无归档移动/标记入口。"""
        window, _, root_dir = archive_env
        window._archive_settings.set_root(root_dir / "99_归档")  # noqa: SLF001
        _select_tree_node(qapp, window, "99_归档")
        qapp.processEvents()
        entry = _find_entry_by_name(window, "批次")
        assert entry is not None and entry.is_dir

        labels = [a[0] for a in window._build_content_menu_actions([entry])]  # noqa: SLF001
        assert ui.MENU_GENERATE_ARCHIVE_MANIFEST in labels
        assert ui.MENU_ARCHIVE_QUICK not in labels
        assert ui.MENU_ARCHIVE_TO not in labels
        assert ui.MENU_MARK_ARCHIVE_ROOT not in labels

    def test_inside_file_has_no_archive_entries(self, qapp, archive_env) -> None:
        """归档根内文件：不显示任何归档相关右键项。"""
        window, _, root_dir = archive_env
        window._archive_settings.set_root(root_dir / "99_归档")  # noqa: SLF001
        _select_tree_node(qapp, window, "99_归档")
        qapp.processEvents()
        entry = _find_entry_by_name(window, "旧包.7z")
        assert entry is not None and not entry.is_dir

        labels = [a[0] for a in window._build_content_menu_actions([entry])]  # noqa: SLF001
        assert ui.MENU_ARCHIVE_QUICK not in labels
        assert ui.MENU_ARCHIVE_TO not in labels
        assert ui.MENU_GENERATE_ARCHIVE_MANIFEST not in labels
        assert ui.MENU_MARK_ARCHIVE_ROOT not in labels

    def test_tree_node_inside_archive_root_shows_manifest_only(
        self, qapp, archive_env, monkeypatch
    ) -> None:
        """目录树归档根内节点：仅「生成归档内容清单」，无快速归档/归档到。"""
        window, _, root_dir = archive_env
        window._archive_settings.set_root(root_dir / "99_归档")  # noqa: SLF001
        _select_root_node(qapp, window)
        qapp.processEvents()
        # 树内选中「批次」子节点
        archive_idx = _find_tree_node_index(window, "99_归档")
        window._tree_model.fetchMore(archive_idx)  # noqa: SLF001
        idx = None
        for i in range(window._tree_model.rowCount(archive_idx)):  # noqa: SLF001
            child_idx = window._tree_model.index(i, 0, archive_idx)  # noqa: SLF001
            display = window._tree_model.data(child_idx, Qt.DisplayRole)  # noqa: SLF001
            if display and "批次" in display:
                idx = child_idx
                break
        assert idx is not None
        window._tree_view.setCurrentIndex(idx)  # noqa: SLF001
        window._tree_view.expand(window._tree_model.index(0, 0))  # noqa: SLF001
        window._tree_view.expand(archive_idx)  # noqa: SLF001
        qapp.processEvents()
        pos = window._tree_view.visualRect(idx).center()  # noqa: SLF001

        menu_items: list[str] = []

        class _FakeAction:
            def __init__(self, text: str) -> None:
                self._text = text

            def text(self) -> str:
                return self._text

            def setEnabled(self, enabled: bool) -> None:
                pass

        class _FakeMenu:
            def __init__(self, *args, **kwargs) -> None:
                self._actions = []
                self._title = args[0] if args else ""

            def addAction(self, label):
                act = _FakeAction(label)
                self._actions.append(act)
                return act

            def actions(self):
                return list(self._actions)

            def insertMenu(self, before_action, submenu) -> None:
                idx_ = self._actions.index(before_action)
                self._actions.insert(idx_, _FakeAction(f"<submenu:{submenu._title}>"))

            def addMenu(self, submenu) -> None:
                self._actions.append(_FakeAction(f"<submenu:{submenu._title}>"))

            def addSeparator(self) -> None:
                self._actions.append(_FakeAction("<separator>"))

            def exec(self, *args, **kwargs):
                menu_items.extend(a.text() for a in self._actions)
                return None

        import app.main_window as mw_module

        original_menu = mw_module.QMenu
        mw_module.QMenu = _FakeMenu  # noqa: SLF001
        try:
            window._on_tree_context_menu(pos)  # noqa: SLF001
        finally:
            mw_module.QMenu = original_menu  # noqa: SLF001

        assert ui.MENU_GENERATE_ARCHIVE_MANIFEST in menu_items
        assert ui.MENU_ARCHIVE_QUICK not in menu_items
        assert ui.MENU_ARCHIVE_TO not in menu_items


class TestTreeArchiveMarker:
    """目录树归档根标记（功能增加1，2026-08-04）。"""

    def test_archive_root_marked_in_tree(self, qapp, archive_env) -> None:
        """标记归档根后，目录树节点显示图标 + 〔归档〕后缀。"""
        window, _, root_dir = archive_env
        archive_root = root_dir / "99_归档"

        window._on_mark_archive_root(archive_root)  # noqa: SLF001
        qapp.processEvents()

        idx = _find_tree_node_index(window, "99_归档")
        display = window._tree_model.data(idx, Qt.DisplayRole)  # noqa: SLF001
        assert ui.TREE_ARCHIVE_ROOT_HINT in display
        # 归档标记仅文本（〔归档〕），不再附加压缩包图标
        assert window._tree_model.data(idx, Qt.DecorationRole) is None  # noqa: SLF001

    def test_unmark_removes_tree_marker(self, qapp, archive_env) -> None:
        """取消归档根标记后，目录树节点标记消失。"""
        window, _, root_dir = archive_env
        archive_root = root_dir / "99_归档"
        window._on_mark_archive_root(archive_root)  # noqa: SLF001
        qapp.processEvents()

        window._on_unmark_archive_root(archive_root)  # noqa: SLF001
        qapp.processEvents()

        idx = _find_tree_node_index(window, "99_归档")
        display = window._tree_model.data(idx, Qt.DisplayRole)  # noqa: SLF001
        assert ui.TREE_ARCHIVE_ROOT_HINT not in display


class TestMarkArchiveRoot:
    def test_mark_root_sets_settings_and_purges_marks(self, qapp, archive_env) -> None:
        """标记归档根：QSettings 写入 + 立即清除根内内容单元标记。"""
        window, conn, root_dir = archive_env
        archive_root = root_dir / "99_归档"
        # 手工在归档根内放一条内容单元记录（模拟历史残留）
        stale = archive_root / "历史残留.7z"
        window._content_service.create_content_unit(stale)  # noqa: SLF001
        conn.commit()
        assert _content_unit_exists(conn, stale)

        window._on_mark_archive_root(archive_root)  # noqa: SLF001
        qapp.processEvents()

        assert window._archive_settings.root_path() == str(archive_root)  # noqa: SLF001
        assert not _content_unit_exists(conn, stale)
        assert "已标记" in window.statusBar().currentMessage()

    def test_unmark_root_clears_settings(self, qapp, archive_env) -> None:
        """取消归档根：仅清 QSettings，不删根内记录。"""
        window, conn, root_dir = archive_env
        archive_root = root_dir / "99_归档"
        window._archive_settings.set_root(archive_root)  # noqa: SLF001

        window._on_unmark_archive_root(archive_root)  # noqa: SLF001

        assert window._archive_settings.root_path() is None  # noqa: SLF001
        assert "取消" in window.statusBar().currentMessage()


class TestQuickArchive:
    def test_ctrl_w_moves_to_last_target_and_unmarks(self, qapp, archive_env) -> None:
        """Ctrl+W：移到上次归档位置 + 删除内容单元标记 + 写入历史。"""
        window, conn, root_dir = archive_env
        _select_tree_node(qapp, window, "Stash")
        qapp.processEvents()
        _select_entry_and_focus(qapp, window, "file1.7z")

        target = root_dir / "99_归档" / "批次"
        window._archive_settings.record_target(target)  # noqa: SLF001
        src = root_dir / "Stash" / "file1.7z"
        assert _content_unit_exists(conn, src)

        window._on_shortcut_archive_quick()  # noqa: SLF001
        qapp.processEvents()

        assert (target / "file1.7z").is_file()
        assert not src.exists()
        assert not _content_unit_exists(conn, src)
        assert not _content_unit_exists(conn, target / "file1.7z")
        assert window._archive_settings.last_target() == str(target)  # noqa: SLF001
        # 归档不写入「最近移动目标」（Ctrl+Q 快速移动的记忆不被污染）
        assert window._recent_move_targets.latest() is None  # noqa: SLF001
        row = conn.execute(
            "SELECT operation_type, target_path FROM operation_history ORDER BY created_at"
        ).fetchall()
        assert any(
            r["operation_type"] == "move" and r["target_path"] == str(target / "file1.7z")
            for r in row
        )

    def test_ctrl_w_no_last_target_opens_dialog(self, qapp, archive_env, monkeypatch) -> None:
        """Ctrl+W 无上次归档位置 → 打开归档选择对话框并记录目标。"""
        window, conn, root_dir = archive_env
        _select_tree_node(qapp, window, "Stash")
        qapp.processEvents()
        _select_entry_and_focus(qapp, window, "file2.7z")

        chosen = root_dir / "99_归档" / "批次"
        monkeypatch.setattr(
            "app.move_to_dialog.MoveToDialog",
            _make_fake_move_to_dialog(chosen, accepted=True),
        )

        window._on_shortcut_archive_quick()  # noqa: SLF001
        qapp.processEvents()

        assert (chosen / "file2.7z").is_file()
        assert not (root_dir / "Stash" / "file2.7z").exists()
        assert window._archive_settings.last_target() == str(chosen)  # noqa: SLF001

    def test_archive_folder_unmarks_descendants(self, qapp, archive_env) -> None:
        """归档文件夹后，其内部子项内容单元标记一并清除。"""
        window, conn, root_dir = archive_env
        _select_tree_node(qapp, window, "Stash")
        qapp.processEvents()
        entry = _find_entry_by_name(window, "group")
        assert entry is not None and entry.is_dir
        inner = root_dir / "Stash" / "group" / "inner.7z"
        assert _content_unit_exists(conn, inner)

        target = root_dir / "99_归档" / "批次"
        window._archive_settings.record_target(target)  # noqa: SLF001
        window._on_archive_quick([entry])  # noqa: SLF001
        qapp.processEvents()

        moved_group = target / "group"
        assert moved_group.is_dir()
        assert not (root_dir / "Stash" / "group").exists()
        assert not _content_unit_exists(conn, moved_group / "inner.7z")

    def test_archive_to_dialog_rooted_at_archive_root(self, qapp, archive_env, monkeypatch) -> None:
        """归档到…的选择窗口以归档目录为根（root_path 注入归档根）。"""
        window, _, root_dir = archive_env
        archive_root = root_dir / "99_归档"
        window._archive_settings.set_root(archive_root)  # noqa: SLF001
        _select_tree_node(qapp, window, "Stash")
        qapp.processEvents()
        entry = _find_entry_by_name(window, "file1.7z")
        assert entry is not None

        captured: dict = {}

        class _CaptureDialog(_make_fake_move_to_dialog(archive_root, accepted=True)):
            def __init__(self, *args, **kwargs) -> None:
                captured.update(kwargs)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr("app.move_to_dialog.MoveToDialog", _CaptureDialog)

        window._on_archive_to([entry])  # noqa: SLF001
        qapp.processEvents()

        assert captured.get("root_path") == archive_root

    def test_quick_archive_does_not_contaminate_quick_move(self, qapp, archive_env) -> None:
        """归档目标与快速移动目标分开记忆（验收反馈 2026-08-04 回归）。"""
        window, _, root_dir = archive_env
        _select_tree_node(qapp, window, "Stash")
        qapp.processEvents()
        _select_entry_and_focus(qapp, window, "file1.7z")

        regular_target = root_dir / "Target"
        archive_target = root_dir / "99_归档" / "批次"
        window._recent_move_targets.record(str(regular_target))  # noqa: SLF001
        window._archive_settings.record_target(archive_target)  # noqa: SLF001

        # 快速归档：file1.7z 进入归档目录
        window._on_shortcut_archive_quick()  # noqa: SLF001
        qapp.processEvents()

        assert (archive_target / "file1.7z").is_file()
        assert window._recent_move_targets.latest() == str(regular_target)  # noqa: SLF001

        # 快速移动（Ctrl+Q）：file2.7z 应进入普通移动目标，而不是归档目录
        _select_tree_node(qapp, window, "Stash")
        qapp.processEvents()
        _select_entry_and_focus(qapp, window, "file2.7z")
        window._on_shortcut_move_to_latest()  # noqa: SLF001
        qapp.processEvents()

        assert (regular_target / "file2.7z").is_file()
        assert not (archive_target / "file2.7z").exists()


class TestArchiveManifest:
    def test_generate_manifest_writes_file(self, qapp, archive_env) -> None:
        """归档根右键「生成归档内容清单」→ 上级目录生成 UTF-8 清单。"""
        window, _, root_dir = archive_env
        archive_root = root_dir / "99_归档"
        window._archive_settings.set_root(archive_root)  # noqa: SLF001

        window._on_generate_archive_manifest(archive_root)  # noqa: SLF001

        output = root_dir / "99_归档归档内容.txt"
        assert output.is_file()
        assert output.read_text(encoding="utf-8").splitlines() == ["批次", "旧包.7z"]
        assert "已生成" in window.statusBar().currentMessage()

    def test_generate_manifest_for_inside_subfolder(self, qapp, archive_env) -> None:
        """归档根内子文件夹右键生成该子目录的清单（输出到其上级）。"""
        window, _, root_dir = archive_env
        archive_root = root_dir / "99_归档"
        sub = archive_root / "批次"
        (sub / "内容.7z").write_bytes(b"\x00")

        window._on_generate_archive_manifest(sub)  # noqa: SLF001

        output = archive_root / "批次归档内容.txt"
        assert output.is_file()
        assert output.read_text(encoding="utf-8").splitlines() == ["内容.7z"]
        assert "已生成" in window.statusBar().currentMessage()


def _select_entry_and_focus(qapp, window: MainWindow, name: str) -> None:
    """在中栏选中条目并确保中栏获得焦点（Ctrl+W 树/中栏优先级依赖焦点）。"""
    model = window._content_list_model  # noqa: SLF001
    for row in range(model.entry_count()):
        entry = model.entry_at(row)
        if entry is not None and entry.name == name:
            window._content_view.selectRow(row)  # noqa: SLF001
            window._content_view.setFocus()  # noqa: SLF001
            qapp.processEvents()
            return
    pytest.fail(f"未找到条目：{name}")
