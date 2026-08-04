"""MainWindow 设置接线测试（设计合理性1 + 快捷键配置，2026-08-04）。

覆盖：工具菜单「设置…」信号接线；确认后保存 QSettings 并立即重注册快捷键
（中栏/目录树/文件夹预览），禁用键不再注册。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QKeySequence  # noqa: E402

from app.feature_toggle_config import FeatureToggleConfig  # noqa: E402
from app.main_window import MainWindow  # noqa: E402
from app.shortcut_config import ShortcutConfig  # noqa: E402
from application.clipboard_service import ClipboardService  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.file_operation_service import FileOperationService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from application.scan_service import ScanService  # noqa: E402
from application.undo_service import UndoService  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.folder_cache_sync_helper import FolderCacheSyncHelper  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.folder_cache import FolderCacheRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402
from infrastructure.repositories.operation_history import (  # noqa: E402
    OperationHistoryRepository,
)


def _make_tree(tmp_path: Path) -> Path:
    root = tmp_path / "mods"
    root.mkdir()
    stash = root / "Stash"
    stash.mkdir()
    (stash / "file1.7z").write_bytes(b"\x00" * 100)
    return root


@pytest.fixture
def settings_env(qapp, tmp_path: Path):
    """构造注入文件操作/撤销/剪贴板服务的 MainWindow。"""
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
    tree_service = FolderTreeService(ManagedRootRepository(conn), FolderCacheRepository(conn))
    content_service = ContentService(ContentUnitRepository(conn))
    scan_service = ScanService(
        managed_root_repo=ManagedRootRepository(conn),
        folder_cache_repo=FolderCacheRepository(conn),
        content_unit_repo=ContentUnitRepository(conn),
        now_provider=lambda: "2026-08-04T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    folder_cache_repo = FolderCacheRepository(conn)
    content_unit_repo = ContentUnitRepository(conn)
    helper = FolderCacheSyncHelper(folder_cache_repo)
    file_op_service = FileOperationService(
        OperationHistoryRepository(conn),
        folder_cache_helper=helper,
        content_unit_repo=content_unit_repo,
        now_provider=lambda: "2026-08-04T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    undo_service = UndoService(
        history_repo=OperationHistoryRepository(conn),
        file_operation_service=file_op_service,
        folder_cache_helper=helper,
        content_unit_repo=content_unit_repo,
        now_provider=lambda: "2026-08-04T00:00:00Z",
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
        clipboard_service=ClipboardService(),
    )
    yield window, conn

    window.close()
    conn.close()


class TestMainWindowSettings:
    def test_settings_menu_wired(self, qapp, settings_env, monkeypatch) -> None:
        """工具菜单「设置…」触发 _on_settings_clicked。"""
        window, _ = settings_env
        called: list[bool] = []

        class _FakeDialog:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def exec(self) -> int:
                return 0  # 取消

        monkeypatch.setattr("app.main_window.SettingsDialog", _FakeDialog)
        monkeypatch.setattr(
            window,
            "_on_settings_clicked",
            lambda: called.append(True),
        )
        window._menu_bar.settings_action().trigger()  # noqa: SLF001
        assert called == [True]

    def test_settings_clicked_saves_and_reapplies(self, qapp, settings_env, monkeypatch) -> None:
        """确认后保存 QSettings，快捷键立即重注册（含禁用与重映射）。"""
        window, conn = settings_env

        new_features = FeatureToggleConfig.defaults()
        new_features.toggle("browser_search", False)
        new_shortcuts = ShortcutConfig.defaults()
        new_shortcuts.set_key("rename", "Ctrl+E")
        new_shortcuts.set_key("delete", "")

        class _FakeDialog:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def exec(self) -> int:
                return 1  # Accepted

            def resulting_feature_config(self) -> FeatureToggleConfig:
                return new_features

            def resulting_shortcut_config(self) -> ShortcutConfig:
                return new_shortcuts

        monkeypatch.setattr("app.main_window.SettingsDialog", _FakeDialog)

        window._on_settings_clicked()  # noqa: SLF001

        # 配置已保存
        assert window._feature_toggle_config == new_features  # noqa: SLF001
        assert window._shortcut_config == new_shortcuts  # noqa: SLF001
        assert FeatureToggleConfig.load(window._qsettings) == new_features  # noqa: SLF001
        assert ShortcutConfig.load(window._qsettings) == new_shortcuts  # noqa: SLF001
        # 快捷键立即生效：重映射 + 禁用
        assert window._shortcut_rename.key() == QKeySequence("Ctrl+E")  # noqa: SLF001
        assert window._shortcut_rename_tree.key() == QKeySequence("Ctrl+E")  # noqa: SLF001
        assert not hasattr(window, "_shortcut_delete")
        assert not hasattr(window, "_shortcut_delete_tree")
        # 状态栏提示
        from app import ui_constants as ui  # noqa: PLC0415

        assert ui.SETTINGS_APPLIED in window.statusBar().currentMessage()
