"""MainWindow 剥离（提取内容，操作便捷性1）集成测试。

覆盖：
- 中栏右键菜单项显示/隐藏规则（普通文件夹/已标记文件夹/文件/多选）
- 完整剥离流程（确认 → 移动子项 → 删除空文件夹 → 历史记录）
- 取消确认不执行
- 空文件夹提示且不执行
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from app import ui_constants as ui  # noqa: E402
from app.main_window import MainWindow  # noqa: E402
from application.assembly_service import AssemblyService  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.file_operation_service import FileOperationService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from application.strip_service import StripService  # noqa: E402
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
    """构造测试目录树：普通文件夹 flat + 已标记文件夹 marked + 文件。"""
    root = tmp_path / "mods"
    root.mkdir()
    stash = root / "Stash"
    stash.mkdir()
    flat = stash / "flat"
    flat.mkdir()
    (flat / "a.txt").write_bytes(b"a")
    (flat / "子目录").mkdir()
    (flat / "子目录" / "c.txt").write_bytes(b"c")
    (stash / "marked").mkdir()
    (stash / "marked" / "m.txt").write_bytes(b"m")
    (stash / "empty").mkdir()
    (stash / "BDOR 1.0.7z").write_bytes(b"\x00" * 100)
    return root


@pytest.fixture
def strip_env(qapp, tmp_path: Path):
    """构造注入 FileOperationService + StripService 的 MainWindow 测试环境。"""
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
    strip_service = StripService(
        file_op_service,
        content_service,
        OperationHistoryRepository(conn),
    )
    assembly_service = AssemblyService(file_op_service, ContentUnitRepository(conn))

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
        assembly_service=assembly_service,
        file_operation_service=file_op_service,
        strip_service=strip_service,
    )
    # 选中暂存区节点，中栏文件列表才会填充
    _select_staging(qapp, window)
    yield window, conn, root_dir

    window.close()
    conn.close()


def _select_staging(qapp, window: MainWindow) -> None:
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


def _find_entry_by_name(window: MainWindow, name: str) -> FileEntry | None:
    """在中栏查找指定名称的条目。"""
    model = window._content_list_model  # noqa: SLF001
    for row in range(model.entry_count()):
        entry = model.entry_at(row)
        if entry is not None and entry.name == name:
            return entry
    return None


class TestStripMenu:
    def test_menu_shown_for_plain_folder(self, qapp, strip_env) -> None:
        """单选普通文件夹 → 显示「提取内容」。"""
        window, _, _ = strip_env
        entry = _find_entry_by_name(window, "flat")
        assert entry is not None and entry.is_dir and entry.content_unit is None

        labels = [a[0] for a in window._build_content_menu_actions([entry])]  # noqa: SLF001
        assert ui.MENU_STRIP_FOLDER in labels

    def test_menu_hidden_for_marked_folder(self, qapp, strip_env) -> None:
        """已标记内容单元的文件夹 → 不显示「提取内容」。"""
        window, conn, root_dir = strip_env
        marked_path = root_dir / "Stash" / "marked"
        window._content_service.mark_as_content_unit(marked_path)  # noqa: SLF001
        conn.commit()
        window._refresh_content_list_for_current_mode()  # noqa: SLF001
        qapp.processEvents()
        entry = _find_entry_by_name(window, "marked")
        assert entry is not None and entry.content_unit is not None

        labels = [a[0] for a in window._build_content_menu_actions([entry])]  # noqa: SLF001
        assert ui.MENU_STRIP_FOLDER not in labels

    def test_menu_hidden_for_file(self, qapp, strip_env) -> None:
        """单选文件 → 不显示「提取内容」。"""
        window, _, _ = strip_env
        entry = _find_entry_by_name(window, "BDOR 1.0.7z")
        assert entry is not None and not entry.is_dir

        labels = [a[0] for a in window._build_content_menu_actions([entry])]  # noqa: SLF001
        assert ui.MENU_STRIP_FOLDER not in labels

    def test_menu_hidden_for_multiselect(self, qapp, strip_env) -> None:
        """多选（含文件夹）→ 不显示「提取内容」。"""
        window, _, _ = strip_env
        flat = _find_entry_by_name(window, "flat")
        marked = _find_entry_by_name(window, "empty")
        assert flat is not None and marked is not None

        labels = [a[0] for a in window._build_content_menu_actions([flat, marked])]  # noqa: SLF001
        assert ui.MENU_STRIP_FOLDER not in labels


class TestStripFlow:
    def test_strip_full_flow(self, qapp, strip_env, monkeypatch: pytest.MonkeyPatch) -> None:
        """确认后执行剥离：子项到上级 + 文件夹进回收站 + strip/delete 历史。"""
        window, conn, root_dir = strip_env
        stash = root_dir / "Stash"
        flat = stash / "flat"
        entry = _find_entry_by_name(window, "flat")
        assert entry is not None

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
        )

        window._on_strip_folder(entry)  # noqa: SLF001
        conn.commit()

        assert not flat.exists()
        assert (stash / "a.txt").read_bytes() == b"a"
        assert (stash / "子目录" / "c.txt").read_bytes() == b"c"
        rows = conn.execute("SELECT * FROM operation_history").fetchall()
        types = [r["operation_type"] for r in rows]
        assert "strip" in types
        assert "delete" in types

    def test_strip_cancel_does_nothing(
        self, qapp, strip_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """取消确认 → 不执行任何操作。"""
        window, conn, root_dir = strip_env
        flat = root_dir / "Stash" / "flat"
        entry = _find_entry_by_name(window, "flat")
        assert entry is not None

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.No,
        )

        window._on_strip_folder(entry)  # noqa: SLF001
        conn.commit()

        assert flat.exists()
        assert (flat / "a.txt").exists()
        rows = conn.execute("SELECT * FROM operation_history").fetchall()
        assert all(r["operation_type"] != "strip" for r in rows)


class TestStripUnbindAssembly:
    """验收反馈（2026-08-04）：提取内容后解绑文件夹预览（含钉住）。"""

    def _confirm_and_strip(self, window, name: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
        )
        entry = _find_entry_by_name(window, name)
        assert entry is not None
        window._on_strip_folder(entry)  # noqa: SLF001

    def test_strip_unbinds_and_unpins_pinned_panel(
        self, qapp, strip_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """钉住被剥离文件夹：解绑并取消钉住。"""
        window, conn, root_dir = strip_env
        flat = root_dir / "Stash" / "flat"
        window._assembly_controller.pin_folder(flat)
        assert window._assembly_panel.is_pinned()
        assert window._assembly_panel.current_folder_path() == flat

        self._confirm_and_strip(window, "flat", monkeypatch)
        conn.commit()

        assert not flat.exists()
        assert not window._assembly_panel.is_pinned()
        assert window._assembly_panel.current_folder_path() is None

    def test_strip_unbinds_unpinned_panel(
        self, qapp, strip_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """未钉住但透视被剥离文件夹：解绑显空状态。"""
        window, conn, root_dir = strip_env
        flat = root_dir / "Stash" / "flat"
        window._bind_assembly_folder(flat)
        assert not window._assembly_panel.is_pinned()
        assert window._assembly_panel.current_folder_path() == flat

        self._confirm_and_strip(window, "flat", monkeypatch)
        conn.commit()

        assert not flat.exists()
        assert window._assembly_panel.current_folder_path() is None

    def test_strip_keeps_panel_bound_to_other_folder(
        self, qapp, strip_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """面板透视其他文件夹（未被剥离）→ 不受影响。"""
        window, conn, root_dir = strip_env
        marked = root_dir / "Stash" / "marked"
        window._bind_assembly_folder(marked)
        assert window._assembly_panel.current_folder_path() == marked

        self._confirm_and_strip(window, "flat", monkeypatch)
        conn.commit()

        assert not (root_dir / "Stash" / "flat").exists()
        assert window._assembly_panel.current_folder_path() == marked

    def test_strip_empty_folder_rejected(
        self, qapp, strip_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """空文件夹：提示且不执行。"""
        window, conn, root_dir = strip_env
        empty = root_dir / "Stash" / "empty"
        entry = _find_entry_by_name(window, "empty")
        assert entry is not None

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
        )

        window._on_strip_folder(entry)  # noqa: SLF001
        conn.commit()

        assert empty.exists()
        rows = conn.execute("SELECT * FROM operation_history").fetchall()
        assert all(r["operation_type"] != "strip" for r in rows)
