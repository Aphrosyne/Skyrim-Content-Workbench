"""内容单元查询服务。

从 content_unit 表查询内容单元，不写数据库。

list_direct_children：只返回 path 直接属于该目录的内容单元
（即 Path(unit.path).parent == dir_path），不含深层子目录的内容单元。
通过在 service 层过滤 list_by_path_prefix 结果实现，保持 Repository 简单。

list_directory_entries：从文件系统读取目录下所有条目（roadmap Task 4 2026-07-13 设计修正），
并按 path 关联 content_unit 表中的内容单元。内容单元不是可见性门槛——
所有文件系统条目均返回。仅使用 Path.iterdir / is_dir / is_file / stat（只读）。

路径比较统一使用 make_path_key()（normcase + normpath）归一化，
不依赖 Path.resolve()（后者会访问文件系统解析符号链接，语义不一致）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from domain.models import ContentUnit, FileEntry
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.content_unit import ContentUnitRepository

logger = logging.getLogger(__name__)


class ContentService:
    """内容单元查询服务。"""

    def __init__(self, content_unit_repo: ContentUnitRepository) -> None:
        self._repo = content_unit_repo

    def list_by_directory(self, dir_path: str) -> list[ContentUnit]:
        """返回 dir_path 及其所有子目录下的内容单元。

        委托 ContentUnitRepository.list_by_path_prefix。
        """
        return self._repo.list_by_path_prefix(dir_path)

    def list_direct_children(self, dir_path: str) -> list[ContentUnit]:
        """只返回 path 直接属于 dir_path 的内容单元。

        判断规则：Path(unit.path).parent 与 dir_path 指向同一目录。
        使用 make_path_key() 归一化后比较，避免大小写/分隔符差异。

        特别地，当 unit.path 本身就是 dir_path（内容单元路径等于目录路径）时，
        也视为直接子项返回。
        """
        all_units = self._repo.list_by_path_prefix(dir_path)
        if not all_units:
            return []

        target_key = make_path_key(dir_path)
        result: list[ContentUnit] = []
        for unit in all_units:
            unit_path_key = make_path_key(unit.path)
            parent_key = make_path_key(str(Path(unit.path).parent))
            # 内容单元路径等于目录本身 或 其父目录等于目录
            if unit_path_key == target_key or parent_key == target_key:
                result.append(unit)
        return result

    def get_by_id(self, unit_id: str) -> ContentUnit | None:
        """按 ID 查询内容单元；不存在返回 None。"""
        return self._repo.get_by_id(unit_id)

    def list_directory_entries(self, dir_path: str) -> list[FileEntry]:
        """返回 dir_path 下所有文件和文件夹条目，并关联 content_unit。

        数据源为文件系统（Path.iterdir），仅读取元数据（is_dir / is_file / stat）。
        对每个条目按 path 查询 content_unit 表，命中则填充 content_unit 字段。

        排序规则：文件夹在前（is_dir=True 优先），同类型按 name 升序（不区分大小写）。

        若 dir_path 不存在、不是目录或读取失败，返回空列表（记日志）。
        """
        root = Path(dir_path)
        try:
            if not root.is_dir():
                return []
        except OSError as e:
            logger.warning("list_directory_entries: 路径检查失败 %s: %s", dir_path, e)
            return []

        entries: list[FileEntry] = []
        try:
            for child in root.iterdir():
                entry = self._build_entry(child)
                if entry is not None:
                    entries.append(entry)
        except OSError as e:
            logger.warning("list_directory_entries: 读取目录失败 %s: %s", dir_path, e)
            return []

        # 文件夹在前，名称不区分大小写升序
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower(), e.name))
        return entries

    def list_staging_entries(self, staging_path: str) -> list[FileEntry]:
        """递归返回暂存区 staging_path 下所有文件和文件夹条目，并关联 content_unit。

        阶段 3 Task 2：暂存区文件列表。

        与 list_directory_entries 区别：
        - 递归遍历所有子目录（Path.rglob("*")），不只单层；
        - 批量预查 content_unit（一次 list_by_path_prefix 取回所有相关单元，
          构建 path_key → ContentUnit 映射），避免 N 次 DB 查询。

        数据源为文件系统，仅读取元数据（is_dir / is_file / stat），跳过符号链接。
        单条目读取失败不中断整体遍历（记日志后跳过）。

        排序规则：文件夹在前（is_dir=True 优先），同类型按 name 升序（不区分大小写）。
        排序为初始默认顺序；UI 层可通过 FileListModel.set_sort_key 切换排序键。

        若 staging_path 不存在、不是目录或读取失败，返回空列表（记日志）。
        """
        root = Path(staging_path)
        try:
            if not root.is_dir():
                return []
        except OSError as e:
            logger.warning("list_staging_entries: 路径检查失败 %s: %s", staging_path, e)
            return []

        # 批量预查 content_unit：一次 SQL 拿回所有相关单元，构建 path_key 映射
        unit_map: dict[str, ContentUnit] = {}
        try:
            units = self._repo.list_by_path_prefix(staging_path)
            for unit in units:
                unit_map[make_path_key(unit.path)] = unit
        except Exception:  # noqa: BLE001 - 数据库查询失败不阻塞文件系统遍历
            logger.exception("list_staging_entries: 预查 content_unit 失败：%s", staging_path)

        entries: list[FileEntry] = []
        try:
            for child in root.rglob("*"):
                entry = self._build_entry_with_map(child, unit_map)
                if entry is not None:
                    entries.append(entry)
        except OSError as e:
            logger.warning("list_staging_entries: 递归读取失败 %s: %s", staging_path, e)
            return []

        # 文件夹在前，名称不区分大小写升序
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower(), e.name))
        return entries

    def _build_entry(self, child: Path) -> FileEntry | None:
        """从单个 Path 构建 FileEntry（单次精确查询 content_unit）。跳过符号链接。"""
        try:
            if child.is_symlink():
                return None
            is_dir = child.is_dir()
            stat = child.stat()
            modified_at = _mtime_to_iso(stat.st_mtime)
            size: int | None = None if is_dir else stat.st_size
        except OSError as e:
            logger.warning("list_directory_entries: 读取条目失败 %s: %s", child, e)
            return None

        # 关联 content_unit（按 path 精确匹配）
        content_unit: ContentUnit | None = None
        try:
            content_unit = self._repo.get_by_path(str(child))
        except Exception:  # noqa: BLE001 - 数据库查询失败不应中断遍历
            logger.exception("查询 content_unit 失败：path=%s", child)

        return FileEntry(
            name=child.name,
            path=str(child),
            is_dir=is_dir,
            modified_at=modified_at,
            size=size,
            content_unit=content_unit,
        )

    def _build_entry_with_map(
        self, child: Path, unit_map: dict[str, ContentUnit]
    ) -> FileEntry | None:
        """从单个 Path 构建 FileEntry，content_unit 从预构建的 path_key 映射查询。

        用于 list_staging_entries 的批量关联场景，避免 N 次 DB 查询。
        """
        try:
            if child.is_symlink():
                return None
            is_dir = child.is_dir()
            stat = child.stat()
            modified_at = _mtime_to_iso(stat.st_mtime)
            size: int | None = None if is_dir else stat.st_size
        except OSError as e:
            logger.warning("list_staging_entries: 读取条目失败 %s: %s", child, e)
            return None

        content_unit = unit_map.get(make_path_key(str(child)))

        return FileEntry(
            name=child.name,
            path=str(child),
            is_dir=is_dir,
            modified_at=modified_at,
            size=size,
            content_unit=content_unit,
        )


def _mtime_to_iso(mtime: float) -> str:
    """把 stat.st_mtime（epoch 秒）转为 ISO 8601 UTC 字符串。"""
    dt = datetime.fromtimestamp(mtime, tz=UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
