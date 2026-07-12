"""扫描服务。

编排 ManagedRoot → FileScanner → folder_cache + content_unit 持久化的完整链路。

依据 spec §5.4：
- 内容单元识别规则：文件夹内含压缩包 → 候选 ContentUnit。
- 识别后停止递归其子目录。

依据 architecture §8.1：
- 增量扫描：对比 folder_cache.last_scanned_mtime，未变更目录跳过。
- 全量扫描：无视缓存全量扫描。

ScanService 不直接访问文件系统写操作；FileScanner 为只读。
ScanService 通过 Repository 写入应用数据库。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from application.errors import ManagedRootNotFoundError
from domain.models import ContentUnit, FolderCache, ManagedRoot
from infrastructure.file_scanner import FileScanner, ScanResult
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.folder_cache import FolderCacheRepository
from infrastructure.repositories.managed_root import ManagedRootRepository

logger = logging.getLogger(__name__)


@dataclass
class ScanSummary:
    """扫描结果的摘要，用于 UI 展示。"""

    root_id: str
    root_path: str
    scanned_dirs: int = 0
    content_units_found: int = 0
    errors: list[str] = field(default_factory=list)
    skipped_unchanged: int = 0

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def success(self) -> bool:
        """扫描成功：无整体性错误。单个目录的扫描错误计入 errors 但不影响 success 判定。"""
        # 当前实现：只要扫描流程完成即视为成功，errors 为单目录错误集合
        return True


def _default_now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_uuid_provider() -> str:
    return str(uuid.uuid4())


class ScanService:
    """扫描编排服务。

    使用方式：
        service = ScanService(managed_root_repo, folder_cache_repo, content_unit_repo)
        summary = service.scan_root(root_id, incremental=True)
    """

    def __init__(
        self,
        managed_root_repo: ManagedRootRepository,
        folder_cache_repo: FolderCacheRepository,
        content_unit_repo: ContentUnitRepository,
        scanner: FileScanner | None = None,
        now_provider: Callable[[], str] | None = None,
        uuid_provider: Callable[[], str] | None = None,
    ) -> None:
        self._managed_root_repo = managed_root_repo
        self._folder_cache_repo = folder_cache_repo
        self._content_unit_repo = content_unit_repo
        self._scanner = scanner or FileScanner()
        self._now = now_provider or _default_now_utc
        self._new_uuid = uuid_provider or _default_uuid_provider

    def scan_root(self, root_id: str, incremental: bool = True) -> ScanSummary:
        """扫描指定受管理根目录。

        incremental=True：使用 folder_cache 中的 mtime 做增量判断。
        incremental=False：全量重扫。
        """
        root = self._managed_root_repo.get_by_id(root_id)
        if root is None:
            raise ManagedRootNotFoundError(f"受管理根目录不存在：{root_id}")

        return self._do_scan(root, incremental=incremental)

    def scan_root_by_path(self, path: Path, incremental: bool = True) -> ScanSummary:
        """按路径扫描（不依赖 managed_root 表）。

        用于临时扫描未配置为受管理根目录的路径。
        """
        root = ManagedRoot(
            id="_adhoc",
            real_path=str(path),
            path_key=str(path),
            created_at=self._now(),
            updated_at=self._now(),
            display_name=path.name,
        )
        return self._do_scan(root, incremental=incremental)

    def _do_scan(self, root: ManagedRoot, incremental: bool) -> ScanSummary:
        root_path = Path(root.real_path)
        summary = ScanSummary(
            root_id=root.id,
            root_path=root.real_path,
        )

        # 增量扫描：构造 folder_mtime_map
        folder_mtime_map: dict[str, float] | None = None
        if incremental:
            folder_mtime_map = self._build_folder_mtime_map()

        # 执行扫描
        if folder_mtime_map is not None:
            result = self._scanner.scan_incremental(root_path, folder_mtime_map)
        else:
            result = self._scanner.scan_full(root_path)

        # 持久化 folder_cache + content_unit
        self._persist_scan_result(result, summary)

        summary.skipped_unchanged = result.skipped_unchanged
        summary.errors = [f"{e.path}: {e.message}" for e in result.errors]
        return summary

    def _build_folder_mtime_map(self) -> dict[str, float]:
        """从 folder_cache 表构造 path → mtime 映射。"""
        folders = self._folder_cache_repo.list_all()
        return {f.path: f.last_scanned_mtime for f in folders if f.last_scanned_mtime is not None}

    def _persist_scan_result(self, result: ScanResult, summary: ScanSummary) -> None:
        """将扫描结果持久化到 folder_cache 和 content_unit 表。

        - folder_cache：upsert（存在则更新 mtime，不存在则插入）
        - content_unit：仅插入新候选（已存在 path 跳过）
        """
        now = self._now()

        # 持久化 folder_cache
        existing_folder_map: dict[str, FolderCache] = {
            f.path: f for f in self._folder_cache_repo.list_all()
        }
        for entry in result.scanned_dirs:
            existing = existing_folder_map.get(entry.path)
            if existing is not None:
                # 更新 mtime
                if existing.last_scanned_mtime is None or not self._scanner._mtime_equal(
                    existing.last_scanned_mtime, entry.mtime
                ):
                    self._folder_cache_repo.upsert_mtime(
                        path=entry.path, mtime=entry.mtime, folder_id=existing.id
                    )
            else:
                # 新建
                parent_id = self._resolve_parent_id(entry.parent_path, existing_folder_map)
                folder = FolderCache(
                    id=self._new_uuid(),
                    path=entry.path,
                    parent_id=parent_id,
                    last_scanned_mtime=entry.mtime,
                    created_at=now,
                )
                created = self._folder_cache_repo.create(folder)
                existing_folder_map[created.path] = created

        summary.scanned_dirs = len(result.scanned_dirs)

        # 持久化 content_unit（仅插入新候选）
        existing_cu_paths: set[str] = {cu.path for cu in self._content_unit_repo.list_all()}
        new_units_count = 0
        for candidate in result.content_unit_candidates:
            if candidate.path in existing_cu_paths:
                continue
            unit = ContentUnit(
                id=self._new_uuid(),
                path=candidate.path,
                title=Path(candidate.path).name,
                content_type="mod",
                status="unorganized",
                created_at=now,
                updated_at=now,
            )
            try:
                self._content_unit_repo.create(unit)
                existing_cu_paths.add(unit.path)
                new_units_count += 1
            except Exception:
                # 单个内容单元创建失败不中断整体流程
                logger.exception("无法创建 ContentUnit: %s", unit.path)
                summary.errors.append(f"{unit.path}: 无法创建内容单元")

        summary.content_units_found = new_units_count

    def _resolve_parent_id(
        self,
        parent_path: str | None,
        existing_folder_map: dict[str, FolderCache],
    ) -> str | None:
        """根据 parent_path 解析 parent_id。

        parent_path 为 None 时返回 None（根节点）。
        parent_path 不在 existing_folder_map 中时返回 None（容忍乱序）。
        """
        if parent_path is None:
            return None
        parent = existing_folder_map.get(parent_path)
        return parent.id if parent is not None else None
