"""扫描工作流服务。

依据 docs/phase-2-plan.md 任务 2、docs/architecture.md §3。
依据 D4 决策：阶段 2 使用同步扫描器；并发由 Qt worker 包裹，本服务本身保持同步、无 UI 依赖。

职责：
- 读取 ManagedRoot 配置。
- 调用现有 FileScanner.scan（同步、只读）。
- 调用 persist_scan_result 写入 DB。
- 返回结构化 ScanSummary，不访问 UI。

约束：
- 不修改 FileScanner 的同步接口。
- 仅调用现有只读扫描 API；不写用户文件。
- 持久化仅写应用数据库。
- 单个根目录扫描失败不阻止调用方处理其他根目录（由调用方循环处理）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from application.errors import ManagedRootNotFoundError
from domain.models import ManagedRoot
from infrastructure.file_scanner import FileScanner, ScanError, persist_scan_result
from infrastructure.repositories.file_asset import FileAssetRepository
from infrastructure.repositories.folder_node import FolderNodeRepository
from infrastructure.repositories.managed_root import ManagedRootRepository

logger = logging.getLogger(__name__)


@dataclass
class ScanSummary:
    """单次扫描的结构化摘要。供 UI 展示。"""

    root_id: str
    root_path: Path
    scanned_folders: int
    scanned_files: int
    persisted_folders: int
    persisted_files: int
    skipped_folders: int
    skipped_files: int
    error_count: int
    errors: list[ScanError] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        """扫描是否成功完成（无致命错误）。

        注意：存在 ScanError 仍视为成功完成（错误已记入摘要），
        仅当根目录无法扫描且无任何条目时视为失败。
        """
        return self.scanned_folders > 0 or self.scanned_files > 0 or self.error_count == 0


class ScanWorkflowService:
    """扫描工作流编排。

    使用方式：
        service = ScanWorkflowService(scanner, managed_root_repo, folder_repo, file_repo)
        summary = service.scan_root(root_id)
    """

    def __init__(
        self,
        scanner: FileScanner,
        managed_root_repo: ManagedRootRepository,
        folder_repo: FolderNodeRepository,
        file_repo: FileAssetRepository,
        now_provider: Callable[[], str] | None = None,
        uuid_provider: Callable[[], str] | None = None,
    ) -> None:
        self._scanner = scanner
        self._managed_root_repo = managed_root_repo
        self._folder_repo = folder_repo
        self._file_repo = file_repo
        self._now_provider = now_provider
        self._uuid_provider = uuid_provider

    def scan_root(self, root_id: str) -> ScanSummary:
        """扫描指定受管理根目录并持久化结果。

        - root_id 不存在抛 ManagedRootNotFoundError。
        - 根目录不存在/非目录时，FileScanner 返回仅含错误的 ScanResult，
          本方法仍返回 ScanSummary（error_count > 0），不抛异常。
        """
        root = self._managed_root_repo.get_by_id(root_id)
        if root is None:
            raise ManagedRootNotFoundError(f"受管理根目录不存在：{root_id}")
        return self._scan_managed_root(root)

    def scan_root_by_path(self, real_path: Path) -> ScanSummary:
        """按路径扫描（路径需已配置为受管理根目录）。

        用于扫描尚未持久化但调用方已知的根目录场景。
        本方法不创建 ManagedRoot 记录。
        """
        from infrastructure.path_utils import make_path_key

        path_key = make_path_key(real_path)
        root = self._managed_root_repo.get_by_path_key(path_key)
        if root is None:
            raise ManagedRootNotFoundError(f"该路径未配置为受管理根目录：{real_path}")
        return self._scan_managed_root(root)

    def _scan_managed_root(self, root: ManagedRoot) -> ScanSummary:
        """执行实际扫描与持久化。"""
        root_path = Path(root.real_path)
        logger.info("开始扫描受管理根目录：%s", root_path)

        scan_result = self._scanner.scan(root_path)
        outcome = persist_scan_result(
            scan_result,
            self._folder_repo,
            self._file_repo,
            now_provider=self._now_provider,
            uuid_provider=self._uuid_provider,
        )

        summary = ScanSummary(
            root_id=root.id,
            root_path=root_path,
            scanned_folders=len(scan_result.folders),
            scanned_files=len(scan_result.files),
            persisted_folders=len(outcome.inserted_folders),
            persisted_files=len(outcome.inserted_files),
            skipped_folders=len(outcome.skipped_folders),
            skipped_files=len(outcome.skipped_files),
            error_count=len(scan_result.errors),
            errors=list(scan_result.errors),
        )
        logger.info(
            "扫描完成：%s（目录 %d，文件 %d，错误 %d）",
            root_path,
            summary.scanned_folders,
            summary.scanned_files,
            summary.error_count,
        )
        return summary
