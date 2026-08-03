"""数据库问题1 端到端回归测试（2026-08-02）。

场景（用户报告）：文件 AAA 重命名为 BAA 后，搜索 "AA" 仍能搜到两个文件；
移动后又多出一条搜索内容；重启多次依旧。

根因链路：
1. 压缩包在扫描时自动成为 content_unit（title = 文件名；UI合理性13 起不再写入）
2. FileOperationService 文件重命名/移动只更新父目录 mtime，不更新 content_unit 行
3. 下次扫描发现新路径 → 只插入新行、从不删除旧行 → 旧路径残留 + 新路径新增
4. 搜索匹配 title/notes/tags，两行都命中 → 重复结果；无任何逻辑清理旧行

修复：
- 文件重命名/移动原地更新 content_unit 行（path/path_key；UI合理性13 起 title 不再跟随）
- 扫描时清理 root 下文件已不存在的 content_unit 行（含级联）

本测试断言修复后的完整链路：扫描 → 重命名 → 扫描 → 搜索恰好 1 条、无失效路径。
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from application.file_operation_service import FileOperationService
from application.scan_service import ScanService
from application.search_service import SearchService
from domain.models import ManagedRoot
from infrastructure.db import get_connection, init_db
from infrastructure.folder_cache_sync_helper import FolderCacheSyncHelper
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.folder_cache import FolderCacheRepository
from infrastructure.repositories.managed_root import ManagedRootRepository
from infrastructure.repositories.operation_history import OperationHistoryRepository
from infrastructure.repositories.search import SearchRepository


def _build_services(
    db_path: Path,
) -> tuple[sqlite3.Connection, ScanService, FileOperationService, SearchService]:
    """构造真实服务链（与 main.py 相同的注入方式）。"""
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    managed_root_repo = ManagedRootRepository(conn)
    folder_cache_repo = FolderCacheRepository(conn)
    content_unit_repo = ContentUnitRepository(conn)

    scan = ScanService(managed_root_repo, folder_cache_repo, content_unit_repo)
    file_op = FileOperationService(
        OperationHistoryRepository(conn),
        folder_cache_helper=FolderCacheSyncHelper(folder_cache_repo),
        content_unit_repo=content_unit_repo,
    )
    search = SearchService(SearchRepository(conn))
    return conn, scan, file_op, search


def _register_root(conn: sqlite3.Connection, root: Path) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    root_rec = ManagedRoot(
        id=str(uuid.uuid4()),
        real_path=str(root),
        path_key=str(root).lower(),
        created_at=now,
        updated_at=now,
        display_name=root.name,
    )
    conn.execute(
        "INSERT INTO managed_root (id, real_path, path_key, display_name, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (root_rec.id, root_rec.real_path, root_rec.path_key, root_rec.display_name, now, now),
    )
    conn.commit()
    return root_rec.id


def test_rename_then_scan_search_returns_single_result(tmp_path: Path) -> None:
    """重命名后搜索旧关键词：恰好 1 条，且指向新路径。"""
    db_path = tmp_path / "app.db"
    conn, scan, file_op, search = _build_services(db_path)
    conn.row_factory = sqlite3.Row

    mods = tmp_path / "Mods"
    mods.mkdir()
    archive = mods / "AAA.7z"
    archive.write_bytes(b"x" * 10)
    root_id = _register_root(conn, mods)

    # 1. 首次扫描：AAA.7z 成为内容单元
    scan.scan_root(root_id, incremental=False)
    conn.commit()

    # 2. 重命名 AAA.7z → BAA.7z（应用内操作路径）
    file_op.rename(archive, "BAA.7z")
    conn.commit()

    # 3. 再次扫描（模拟重启后的扫描）
    scan.scan_root(root_id, incremental=False)
    conn.commit()

    # 4. 搜索 "AA"：应恰好 1 条，路径指向 BAA.7z
    results = search.search("AA")
    actual = [(r.name, r.path) for r in results]
    assert len(results) == 1, f"期望 1 条结果，实际 {len(results)}：{actual}"
    assert results[0].path.endswith("BAA.7z")

    # content_unit 表应只有一行，且无失效路径
    rows = conn.execute("SELECT path, title FROM content_unit").fetchall()
    assert len(rows) == 1
    assert rows[0]["path"].endswith("BAA.7z")
    assert rows[0]["title"] is None  # UI合理性13：title 不再写入/跟随
    conn.close()


def test_move_then_scan_search_returns_single_result(tmp_path: Path) -> None:
    """移动文件到其他目录后：恰好 1 条，指向新路径。"""
    db_path = tmp_path / "app.db"
    conn, scan, file_op, search = _build_services(db_path)
    conn.row_factory = sqlite3.Row

    mods = tmp_path / "Mods"
    mods.mkdir()
    sub_a = mods / "分类A"
    sub_a.mkdir()
    sub_b = mods / "分类B"
    sub_b.mkdir()
    archive = sub_a / "AAA.7z"
    archive.write_bytes(b"x" * 10)
    root_id = _register_root(conn, mods)

    scan.scan_root(root_id, incremental=False)
    conn.commit()
    file_op.move(archive, sub_b / "AAA.7z")
    conn.commit()
    scan.scan_root(root_id, incremental=False)
    conn.commit()

    results = search.search("AAA")
    assert len(results) == 1, f"期望 1 条结果，实际 {len(results)}"
    assert results[0].path.endswith("分类B\\AAA.7z") or results[0].path.endswith("分类B/AAA.7z")
    conn.close()
