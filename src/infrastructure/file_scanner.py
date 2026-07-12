"""文件系统扫描器。

只读递归扫描受管理根目录，识别内容单元候选（含压缩包的文件夹），
返回 ScannedFolderEntry 列表供 ScanService 持久化。

设计要点：
- 只读：不修改、不移动、不删除任何用户文件（AGENTS 规则 2、5）。
- 不读取文件内容（AGENTS 规则 6）：仅使用 Path.iterdir / is_dir / stat。
- 符号链接不跟随（避免循环）。
- 内容单元识别规则（spec §5.4）：文件夹内含压缩包 → 候选 ContentUnit。
  识别为内容单元后停止递归其子目录。
- 增量扫描：传入 folder_cache 的 last_scanned_mtime，未变更目录跳过。

错误处理：单个目录扫描失败不中断整体流程，记入 ScanResult.errors。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from infrastructure.file_classify import ARCHIVE_EXTENSIONS, get_extension

logger = logging.getLogger(__name__)


@dataclass
class ScanError:
    """扫描过程中的单个错误。"""

    path: str
    message: str


@dataclass
class ScannedFolderEntry:
    """扫描得到的单个目录条目。

    is_content_unit_candidate 为 True 表示该目录被识别为内容单元候选
    （含压缩包文件）。扫描器识别到候选后会停止递归其子目录。
    """

    path: str
    mtime: float
    is_content_unit_candidate: bool
    parent_path: str | None


@dataclass
class ScanResult:
    """扫描结果。"""

    scanned_dirs: list[ScannedFolderEntry] = field(default_factory=list)
    content_unit_candidates: list[ScannedFolderEntry] = field(default_factory=list)
    errors: list[ScanError] = field(default_factory=list)
    skipped_unchanged: int = 0

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

        folder_mtime_map: 已知目录路径 → last_scanned_mtime。
        路径键使用 str(Path)（在 Windows 上为反斜杠，调用方需保证一致性）。
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
          但仍读取目录内容以获取子目录列表，递归检查子目录
          （子目录的 mtime 可能独立变化）。
        - mtime 变化 → 重新扫描该目录，记录到 scanned_dirs。
        """
        try:
            dir_mtime = dir_path.stat().st_mtime
        except OSError as e:
            result.errors.append(ScanError(path=str(dir_path), message=f"无法读取目录 mtime：{e}"))
            return

        dir_path_str = str(dir_path)

        # 增量扫描：判断 mtime 是否未变
        is_unchanged = False
        if folder_mtime_map is not None:
            cached_mtime = folder_mtime_map.get(dir_path_str)
            if cached_mtime is not None and self._mtime_equal(cached_mtime, dir_mtime):
                is_unchanged = True

        # 读取目录内容（即使 mtime 未变也需要获取子目录列表）
        try:
            entries = list(dir_path.iterdir())
        except OSError as e:
            result.errors.append(ScanError(path=dir_path_str, message=f"无法读取目录内容：{e}"))
            return

        # 分离子目录与文件
        subdirs: list[Path] = []
        has_archive = False
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
                        has_archive = True
            except OSError as e:
                result.errors.append(ScanError(path=str(entry), message=f"无法读取条目：{e}"))
                continue

        if is_unchanged:
            # mtime 未变：跳过扫描结果记录，但仍递归子目录
            result.skipped_unchanged += 1
            # 内容单元候选不会递归子目录，所以未变的内容单元候选直接跳过
            if not has_archive:
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
            is_content_unit_candidate=has_archive,
            parent_path=parent_path,
        )
        result.scanned_dirs.append(entry)
        if has_archive:
            result.content_unit_candidates.append(entry)

        # 递归子目录
        # 内容单元候选：停止递归其子目录（spec §5.4）
        if not has_archive:
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
