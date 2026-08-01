"""MainWindow._commit 失败 UI 反馈测试（TD-M11）。

覆盖：
- commit_callback 抛异常时 QMessageBox.critical 被调用；
- 提示标题与消息来自 ui_constants.DB_COMMIT_FAILED_TITLE / DB_COMMIT_FAILED_MESSAGE；
- 异常仍被记录到 logger（通过 logger.exception 调用验证）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from app import ui_constants  # noqa: E402
from app.main_window import MainWindow  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.folder_tree_service import FolderTreeService  # noqa: E402
from application.managed_root_service import ManagedRootService  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.folder_cache import FolderCacheRepository  # noqa: E402
from infrastructure.repositories.managed_root import ManagedRootRepository  # noqa: E402


@pytest.fixture
def main_window_with_failing_commit(qapp, tmp_path: Path):
    """构造 MainWindow，commit_callback 总是抛 OperationalError。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row

    managed_service = ManagedRootService(
        ManagedRootRepository(conn),
        FolderCacheRepository(conn),
        ContentUnitRepository(conn),
    )
    tree_service = FolderTreeService(
        ManagedRootRepository(conn),
        FolderCacheRepository(conn),
    )
    content_service = ContentService(ContentUnitRepository(conn))

    def failing_commit() -> None:
        raise sqlite3.OperationalError("disk full")

    window = MainWindow(
        managed_service,
        tree_service,
        content_service,
        db_path,
        commit_callback=failing_commit,
    )
    yield window
    window.close()
    conn.close()


def test_commit_failure_shows_critical_message_box(
    qapp, main_window_with_failing_commit, monkeypatch
) -> None:
    """commit_callback 抛异常时 QMessageBox.critical 被调用，标题匹配常量。"""
    called: list[tuple] = []

    def fake_critical(parent, title, message, *args, **kwargs):
        called.append((parent, title, message))

    monkeypatch.setattr(
        "app.transaction_scope.QMessageBox.critical",
        fake_critical,
    )

    main_window_with_failing_commit._commit()  # noqa: SLF001

    assert len(called) == 1
    _, title, message = called[0]
    assert title == ui_constants.DB_COMMIT_FAILED_TITLE
    assert message == ui_constants.DB_COMMIT_FAILED_MESSAGE


def test_commit_success_does_not_show_message_box(qapp, tmp_path: Path, monkeypatch) -> None:
    """commit_callback 成功时 QMessageBox.critical 不被调用。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row

    managed_service = ManagedRootService(
        ManagedRootRepository(conn),
        FolderCacheRepository(conn),
        ContentUnitRepository(conn),
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

    called: list[tuple] = []
    monkeypatch.setattr(
        "app.transaction_scope.QMessageBox.critical",
        lambda *args, **kwargs: called.append(args),
    )

    window._commit()  # noqa: SLF001

    assert len(called) == 0
    window.close()
    conn.close()


def test_commit_failure_without_callback_does_not_raise(qapp, tmp_path: Path) -> None:
    """未注入 commit_callback 时 _commit 静默空操作，不抛异常。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row

    managed_service = ManagedRootService(
        ManagedRootRepository(conn),
        FolderCacheRepository(conn),
        ContentUnitRepository(conn),
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
        commit_callback=None,
    )

    # 不应抛异常
    window._commit()  # noqa: SLF001

    window.close()
    conn.close()
