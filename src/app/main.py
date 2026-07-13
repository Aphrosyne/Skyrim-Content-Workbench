"""应用入口。

启动顺序：创建应用数据目录 -> 初始化日志 -> 初始化数据库 -> 启动 Qt 事件循环。
任何步骤失败转为用户可读错误信息后退出（见 AGENTS.md 开发方式）。
"""

from __future__ import annotations

import logging
import sqlite3
import sys

from PySide6.QtWidgets import QApplication

from app.app_paths import ensure_app_directories, get_app_db_path
from app.logging_setup import setup_logging
from app.main_window import MainWindow
from application.folder_tree_service import FolderTreeService
from application.managed_root_service import ManagedRootService
from infrastructure.db import get_connection, init_db
from infrastructure.repositories.folder_cache import FolderCacheRepository
from infrastructure.repositories.managed_root import ManagedRootRepository

logger = logging.getLogger(__name__)


def main() -> int:
    """启动应用。返回退出码。"""
    try:
        ensure_app_directories()
    except OSError as e:
        print(f"无法创建应用数据目录：{e}", file=sys.stderr)
        return 1

    try:
        setup_logging()
    except OSError as e:
        print(f"无法初始化日志：{e}", file=sys.stderr)
        return 1

    logger.info("应用启动")

    db_path = get_app_db_path()
    try:
        init_db(db_path)
    except sqlite3.Error as e:
        logger.exception("数据库初始化失败")
        print(f"无法初始化数据库：{e}", file=sys.stderr)
        return 1

    logger.info("数据库路径：%s", db_path)

    # 主线程持有一个连接用于 UI 查询。
    # 后台扫描 worker 在自身线程内创建独立连接，不与本连接共享。
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    managed_root_service = ManagedRootService(ManagedRootRepository(conn))
    folder_tree_service = FolderTreeService(
        ManagedRootRepository(conn),
        FolderCacheRepository(conn),
    )

    app = QApplication(sys.argv)
    window = MainWindow(
        managed_root_service,
        folder_tree_service,
        db_path,
        commit_callback=conn.commit,
    )
    window.show()
    exit_code = app.exec()
    conn.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
