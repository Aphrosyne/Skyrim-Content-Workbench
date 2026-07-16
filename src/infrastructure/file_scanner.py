"""文件系统扫描器。

只读递归扫描受管理根目录，识别压缩包文件作为内容单元候选（spec §5.4 2026-07-13 修正），
返回 ScannedFolderEntry 列表 + archive_candidates 压缩包文件路径列表供 ScanService 持久化。

设计要点：
- 只读：不修改、不移动、不删除任何用户文件（AGENTS 规则 2、5）。
- 不读取文件内容（AGENTS 规则 6）：仅使用 Path.iterdir / is_dir / stat。
- 符号链接不跟随（避免循环）。
- 内容单元识别规则（spec §5.4 2026-07-13 修正）：所有压缩包文件均自动标记为内容单元候选。
  压缩包文件本身作为 ContentUnit.path，不再以文件夹作为候选。
  文件夹不自动标记为内容单元（手动标记属阶段 3 Task 3）。
  递归所有子目录，不再因识别到压缩包而停止递归。
- 增量扫描：传入 folder_cache 的 last_scanned_mtime，未变更目录跳过。

错误处理：单个目录扫描失败不中断整体流程，记入 ScanResult.errors。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from infrastructure.file_classify import ARCHIVE_EXTENSIONS, get_extension
from infrastructure.path_utils import make_path_key

logger = logging.getLogger(__name__)


@dataclass
class ScanError:
    """扫描过程中的单个错误。"""

    path: str
    message: str


@dataclass
class ScannedFolderEntry:
    """扫描得到的单个目录条目。"""

    path: str
    mtime: float
    parent_path: str | None


@dataclass
class ScanResult:
    """扫描结果。

    scanned_dirs：mtime 发生变化的目录（增量扫描仅记录变更目录）。
    archive_candidates：扫描发现的所有压缩包文件完整路径列表
    （spec §5.4 2026-07-13 修正：压缩包文件本身作为内容单元候选）。
    all_visited_dirs：扫描过程中实际访问到的所有目录路径（无论 mtime 是否变化、
    是否跳过）。用于 ScanService 对比 folder_cache 清理已删除目录的残留记录。
    """

    scanned_dirs: list[ScannedFolderEntry] = field(default_factory=list)
    archive_candidates: list[str] = field(default_factory=list)
    errors: list[ScanError] = field(default_factory=list)
    skipped_unchanged: int = 0
    all_visited_dirs: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


class FileScanner:
    """只读文件系统扫描器。"""

    def scan_full(self, root: Path) -> ScanResult:
        """全量扫描：无视 folder_cache，递归扫描所有子目录。"""
        return self._scan(root, folder_mtime_map=None)

    def scan_incremental(self, root: Path, folder_mtime_map: dict[str, float]) -> ScanResult:
        """增量扫描：mtime 未变的目录跳过其自身及子目录。

        folder_mtime_map: 已知目录 path_key → last_scanned_mtime。
        键使用 make_path_key() 归一化（normcase + normpath），调用方需保证一致性。
        """
        return self._scan(root, folder_mtime_map=folder_mtime_map)

    def _scan(
        self,
        root: Path,
        folder_mtime_map: dict[str, float] | None,
    ) -> ScanResult:
        result = ScanResult()

        if not root.exists():
            result.errors.append(ScanError(path=str(root), message="根目录不存在"))
            return result

        if not root.is_dir():
            result.errors.append(ScanError(path=str(root), message="根路径不是目录"))
            return result

        self._scan_dir(root, parent_path=None, folder_mtime_map=folder_mtime_map, result=result)
        return result

    def _scan_dir(
        self,
        dir_path: Path,
        parent_path: str | None,
        folder_mtime_map: dict[str, float] | None,
        result: ScanResult,
    ) -> None:
        """递归扫描单个目录。

        增量扫描逻辑：
        - mtime 未变 → 跳过该目录的扫描结果记录（skipped_unchanged），
          但仍读取目录内容以获取子目录列表和压缩包文件列表，递归检查子目录
          （子目录的 mtime 可能独立变化）。
        - mtime 变化 → 重新扫描该目录，记录到 scanned_dirs。

        新扫描规则（spec §5.4 2026-07-13 修正）：
        - 递归所有子目录，不再因发现压缩包而停止递归。
        - 压缩包文件路径记入 result.archive_candidates。
        """
        try:
            dir_mtime = dir_path.stat().st_mtime
        except OSError as e:
            result.errors.append(ScanError(path=str(dir_path), message=f"无法读取目录 mtime：{e}"))
            return

        dir_path_str = str(dir_path)

        # 增量扫描：判断 mtime 是否未变
        # folder_mtime_map 的键使用 make_path_key() 归一化（由 ScanService 构造）
        is_unchanged = False
        if folder_mtime_map is not None:
            cached_mtime = folder_mtime_map.get(make_path_key(dir_path))
            if cached_mtime is not None and self._mtime_equal(cached_mtime, dir_mtime):
                is_unchanged = True

        # 读取目录内容（即使 mtime 未变也需要获取子目录列表 + 压缩包文件）
        try:
            entries = list(dir_path.iterdir())
        except OSError as e:
            result.errors.append(ScanError(path=dir_path_str, message=f"无法读取目录内容：{e}"))
            return

        # 记录所有实际访问到的目录（无论 mtime 是否变化），供 ScanService
        # 对比 folder_cache 清理已删除目录的残留记录。
        result.all_visited_dirs.append(dir_path_str)

        # 分离子目录与压缩包文件
        subdirs: list[Path] = []
        for entry in entries:
            try:
                # 符号链接不跟随（避免循环）
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    subdirs.append(entry)
                elif entry.is_file():
                    ext = get_extension(entry.name)
                    if ext in ARCHIVE_EXTENSIONS:
                        # 压缩包文件作为内容单元候选（spec §5.4 2026-07-13 修正）
                        result.archive_candidates.append(str(entry))
            except OSError as e:
                result.errors.append(ScanError(path=str(entry), message=f"无法读取条目：{e}"))
                continue

        if is_unchanged:
            # mtime 未变：跳过扫描结果记录，但仍递归子目录
            result.skipped_unchanged += 1
            for subdir in subdirs:
                self._scan_dir(
                    subdir,
                    parent_path=dir_path_str,
                    folder_mtime_map=folder_mtime_map,
                    result=result,
                )
            return

        # 记录当前目录（mtime 已变化）
        entry = ScannedFolderEntry(
            path=dir_path_str,
            mtime=dir_mtime,
            parent_path=parent_path,
        )
        result.scanned_dirs.append(entry)

        # 递归所有子目录（新规则：不再因压缩包而停止递归）
        for subdir in subdirs:
            self._scan_dir(
                subdir,
                parent_path=dir_path_str,
                folder_mtime_map=folder_mtime_map,
                result=result,
            )

    @staticmethod
    def _mtime_equal(cached: float, current: float) -> bool:
        """判断 mtime 是否相等（考虑浮点精度）。

        Windows NTFS mtime 精度约 100ns，直接 == 比较风险高。
        使用差值绝对值 < 0.001 秒判定相等。
        """
        return abs(cached - current) < 0.001
