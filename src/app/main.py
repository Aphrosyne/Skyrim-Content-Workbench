"""应用入口。

启动顺序：创建应用数据目录 -> 初始化日志 -> 初始化数据库 -> 加载预置标签库
-> 启动 Qt 事件循环。
任何步骤失败转为用户可读错误信息后退出（见 AGENTS.md 开发方式）。
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.app_paths import ensure_app_directories, get_app_db_path, get_thumbnails_dir
from app.logging_setup import setup_logging
from app.main_window import MainWindow
from app.thumbnail_coordinator import ThumbnailCoordinator
from application.assembly_service import AssemblyService
from application.content_service import ContentService
from application.folder_tree_service import FolderTreeService
from application.managed_root_service import ManagedRootService
from application.mod_group_service import ModGroupService
from application.quick_insert_service import QuickInsertService
from application.staging_service import StagingService
from application.tag_service import TagService
from application.thumbnail_service import ThumbnailService
from infrastructure.db import get_connection, init_db
from infrastructure.file_operation_service import FileOperationService
from infrastructure.folder_cache_sync_helper import FolderCacheSyncHelper
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.content_unit_tag import ContentUnitTagRepository
from infrastructure.repositories.folder_cache import FolderCacheRepository
from infrastructure.repositories.managed_root import ManagedRootRepository
from infrastructure.repositories.operation_history import OperationHistoryRepository
from infrastructure.repositories.staging_area import StagingAreaRepository
from infrastructure.repositories.tag import TagRepository
from infrastructure.repositories.tag_category import TagCategoryRepository
from infrastructure.repositories.thumbnail_cache import ThumbnailCacheRepository
from infrastructure.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)

# 预置标签库资源文件路径（src/app/resources/default_tags.json）
# 通过 __file__ 定位，避免依赖 cwd
_DEFAULT_TAGS_JSON = Path(__file__).parent / "resources" / "default_tags.json"


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
    staging_service = StagingService(StagingAreaRepository(conn))
    folder_tree_service = FolderTreeService(
        ManagedRootRepository(conn),
        FolderCacheRepository(conn),
        staging_service=staging_service,
    )

    # Stage 4 Task 4：缩略图 service 先创建（Stage 4.5 M4：注入到 ContentService）
    # GC（Q8: B）：启动时清理无对应 content_unit 的缓存
    try:
        thumbnail_service = ThumbnailService(
            cache_repo=ThumbnailCacheRepository(conn),
            content_unit_repo=ContentUnitRepository(conn),
            thumbnails_dir=get_thumbnails_dir(),
            size=64,
        )
        cleaned = thumbnail_service.cleanup_orphans()
        if cleaned > 0:
            logger.info("启动 GC 清理 %d 条孤立缩略图缓存", cleaned)
        conn.commit()
    except Exception:  # noqa: BLE001 - 启动阶段任何异常都不能阻塞 UI
        logger.exception("缩略图 GC 失败（非致命，继续启动）")
        thumbnail_service = None

    # Stage 4.5 D3：UnitOfWork 管理多步写事务，Service 内部通过 transaction()
    # 保证原子性，调用方（MainWindow）不负责业务事务控制。
    # uow 绑定到主线程连接 conn，所有共享该连接的 Service 注入同一实例，
    # 支持跨 Service 嵌套事务（如 ModGroupService 调用 ContentService）。
    uow = UnitOfWork(conn)

    # Stage 4.5 M4：ContentService 注入 thumbnail_service，
    # 使 update_metadata 修改 cover_path 时主动 invalidate 缩略图缓存。
    content_service = ContentService(
        ContentUnitRepository(conn),
        thumbnail_service=thumbnail_service,
        uow=uow,
    )
    # Stage 4.5 H4：FileOperationService 注入 FolderCacheSyncHelper + ContentUnitRepository，
    # new_folder/move 自动同步 folder_cache + ContentUnit.path，消除调用方手动同步。
    # 各 Service（ModGroupService/AssemblyService/QuickInsertService）在 0.3c/d/e
    # 移除各自的重复同步逻辑后，统一由 FileOperationService 内部同步。
    folder_cache_repo = FolderCacheRepository(conn)
    content_unit_repo = ContentUnitRepository(conn)
    folder_cache_helper = FolderCacheSyncHelper(folder_cache_repo)
    file_operation_service = FileOperationService(
        OperationHistoryRepository(conn),
        folder_cache_helper=folder_cache_helper,
        content_unit_repo=content_unit_repo,
    )
    # Stage 4.5 H4：ModGroupService 不再需要 folder_cache_repo，
    # folder_cache 同步由 FileOperationService 内部的 helper 自动完成。
    mod_group_service = ModGroupService(file_operation_service, content_service, uow=uow)
    # 装配服务（阶段 3 Task 4）：使用同一个 file_operation_service 和 content_unit_repo
    # Stage 4.5 H4：folder_cache mtime 同步由 FileOperationService 内部 helper 自动完成，
    # AssemblyService 不再需要 folder_cache_repo。
    assembly_service = AssemblyService(
        file_operation_service,
        ContentUnitRepository(conn),
    )
    # 快速插入服务（阶段 3 Task 5）：复用 file_op / content_unit_repo
    # Stage 4.5 H4：folder_cache 同步由 FileOperationService 内部 helper 自动完成，
    # QuickInsertService 不再需要 folder_cache_repo。
    quick_insert_service = QuickInsertService(
        file_operation_service,
        ContentUnitRepository(conn),
        uow=uow,
    )
    # 标签服务（阶段 4 Task 1）：标签分类 / 标签 CRUD + JSON 导入导出 + 预置加载
    tag_service = TagService(
        TagCategoryRepository(conn),
        TagRepository(conn),
        ContentUnitTagRepository(conn),
    )

    # 加载预置标签库（D1-D4：仅当 tag_category 表为空时加载）
    # 加载失败不阻塞应用启动（service 内部捕获并记录 ERROR 日志）
    if _DEFAULT_TAGS_JSON.is_file():
        try:
            tag_service.load_default_tags_if_empty(_DEFAULT_TAGS_JSON)
            conn.commit()
        except Exception:  # noqa: BLE001 - 启动阶段任何异常都不能阻塞 UI
            logger.exception("加载预置标签库失败（非致命，继续启动）")
            conn.rollback()
    else:
        logger.warning("预置标签库文件不存在：%s", _DEFAULT_TAGS_JSON)

    thumbnail_coordinator = (
        ThumbnailCoordinator(
            thumbnail_service=thumbnail_service,
            db_path=db_path,
            thumbnails_dir=get_thumbnails_dir(),
            size=64,
        )
        if thumbnail_service is not None
        else None
    )

    app = QApplication(sys.argv)
    window = MainWindow(
        managed_root_service,
        folder_tree_service,
        content_service,
        db_path,
        commit_callback=conn.commit,
        staging_service=staging_service,
        mod_group_service=mod_group_service,
        assembly_service=assembly_service,
        quick_insert_service=quick_insert_service,
        rollback_callback=conn.rollback,
        tag_service=tag_service,
        thumbnail_coordinator=thumbnail_coordinator,
    )
    window.show()
    exit_code = app.exec()
    conn.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
