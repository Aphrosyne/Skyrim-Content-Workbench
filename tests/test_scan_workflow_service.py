"""ScanWorkflowService 测试。

覆盖：
- scan_root 成功结果回传（含目录/文件/错误统计）；
- scan_root_by_path 成功；
- ScanError 可回传（根目录不存在场景）；
- root_id 不存在抛 ManagedRootNotFoundError。

不直接调用 UI；服务保持同步、无 Qt 依赖。
"""

from __future__ import annotations

import pytest

pytest.skip(
    "方向 C 重建（Task 1）：本模块依赖的旧 schema/服务将在 Task 2+ 重写后重新启用",
    allow_module_level=True,
)

from pathlib import Path

import pytest

from application.errors import ManagedRootNotFoundError
from application.managed_root_service import ManagedRootService
from application.scan_workflow_service import ScanSummary, ScanWorkflowService
from infrastructure.file_scanner import FileScanner
from infrastructure.repositories.file_asset import FileAssetRepository
from infrastructure.repositories.folder_node import FolderNodeRepository
from infrastructure.repositories.managed_root import ManagedRootRepository


def _make_service(db_connection) -> ScanWorkflowService:
    """构造 ScanWorkflowService 与配套的 ManagedRoot 记录支持。"""
    managed_root_repo = ManagedRootRepository(db_connection)
    folder_repo = FolderNodeRepository(db_connection)
    file_repo = FileAssetRepository(db_connection)
    scanner = FileScanner()
    return ScanWorkflowService(scanner, managed_root_repo, folder_repo, file_repo)


def test_scan_root_returns_summary_with_counts(db_connection, sample_mod_tree: Path) -> None:
    """成功扫描返回 ScanSummary，包含目录/文件/持久化统计。"""
    root_service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "root-1",
    )
    root = root_service.add_root(sample_mod_tree)

    service = _make_service(db_connection)
    summary = service.scan_root(root.id)

    assert isinstance(summary, ScanSummary)
    assert summary.root_id == root.id
    assert summary.root_path == sample_mod_tree
    # sample_mod_tree 结构：根 + 护甲 + Weapons + 空目录 = 4 个目录
    assert summary.scanned_folders == 4
    # 文件：寒霜之心.7z + 寒霜之心-汉化.zip + preview.webp + DragonSword.rar
    # + README.txt + normal_file.txt + no_extension = 7 个
    assert summary.scanned_files == 7
    assert summary.error_count == 0
    assert summary.is_success


def test_scan_root_persists_results(db_connection, sample_mod_tree: Path) -> None:
    """扫描结果应持久化到 file_asset 与 folder_node 表。"""
    root_service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "root-1",
    )
    root = root_service.add_root(sample_mod_tree)

    service = _make_service(db_connection)
    summary = service.scan_root(root.id)

    assert summary.persisted_folders > 0
    assert summary.persisted_files > 0

    rows = db_connection.execute("SELECT COUNT(*) FROM folder_node").fetchone()
    assert rows[0] >= summary.persisted_folders
    rows = db_connection.execute("SELECT COUNT(*) FROM file_asset").fetchone()
    assert rows[0] >= summary.persisted_files


def test_scan_root_by_path_success(db_connection, sample_mod_tree: Path) -> None:
    """scan_root_by_path 通过路径扫描已配置的根目录。"""
    root_service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "root-1",
    )
    root_service.add_root(sample_mod_tree)

    service = _make_service(db_connection)
    summary = service.scan_root_by_path(sample_mod_tree)

    assert summary.root_path == sample_mod_tree
    assert summary.scanned_files == 7


def test_scan_root_returns_errors_for_missing_directory(db_connection, tmp_path: Path) -> None:
    """已配置的根目录在扫描前被删除，扫描应返回错误摘要，不抛异常。"""
    # 先创建并配置一个目录
    target = tmp_path / "will_be_gone"
    target.mkdir()

    root_service = ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "root-missing",
    )
    root = root_service.add_root(target)

    # 删除目录（模拟用户在配置后删除了根目录）
    # 注意：service 只读校验在 add_root 时已通过；scan 时不再校验路径存在
    target.rmdir()

    service = _make_service(db_connection)
    summary = service.scan_root(root.id)

    assert summary.error_count >= 1
    assert summary.scanned_folders == 0
    assert summary.scanned_files == 0
    # 错误摘要中应包含路径信息
    assert any(str(tmp_path) in err.reason or "不存在" in err.reason for err in summary.errors)


def test_scan_root_unknown_id_raises(db_connection) -> None:
    """root_id 不存在时抛 ManagedRootNotFoundError。"""
    service = _make_service(db_connection)
    with pytest.raises(ManagedRootNotFoundError):
        service.scan_root("unknown-id")


def test_scan_root_by_path_unknown_path_raises(db_connection, tmp_path: Path) -> None:
    """scan_root_by_path 对未配置的路径抛 ManagedRootNotFoundError。"""
    service = _make_service(db_connection)
    with pytest.raises(ManagedRootNotFoundError):
        service.scan_root_by_path(tmp_path)


def test_scan_summary_is_success_logic() -> None:
    """ScanSummary.is_success 的边界条件。"""
    # 完全空扫描但有错误：失败
    s1 = ScanSummary(
        root_id="x",
        root_path=Path("/x"),
        scanned_folders=0,
        scanned_files=0,
        persisted_folders=0,
        persisted_files=0,
        skipped_folders=0,
        skipped_files=0,
        error_count=1,
    )
    assert s1.is_success is False

    # 有扫描结果 + 错误：成功（错误已记入摘要）
    s2 = ScanSummary(
        root_id="x",
        root_path=Path("/x"),
        scanned_folders=1,
        scanned_files=0,
        persisted_folders=0,
        persisted_files=0,
        skipped_folders=0,
        skipped_files=0,
        error_count=1,
    )
    assert s2.is_success is True

    # 完全空扫描且无错误：视为成功（空目录合法）
    s3 = ScanSummary(
        root_id="x",
        root_path=Path("/x"),
        scanned_folders=0,
        scanned_files=0,
        persisted_folders=0,
        persisted_files=0,
        skipped_folders=0,
        skipped_files=0,
        error_count=0,
    )
    assert s3.is_success is True
