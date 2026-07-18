"""内容单元服务：查询与元数据写入。

从 content_unit 表查询内容单元，并提供元数据写入方法
（create_content_unit / mark_as_content_unit / unmark_content_unit）。

写方法仅修改数据库记录，不触发任何文件操作（不创建、不移动、不删除、
不重命名真实文件）。文件操作由 FileOperationService 负责。

list_direct_children：只返回 path 直接属于该目录的内容单元
（即 Path(unit.path).parent == dir_path），不含深层子目录的内容单元。
通过在 service 层过滤 list_by_path_prefix_normalized 结果实现，保持 Repository 简单。

list_directory_entries：从文件系统读取目录下所有条目（roadmap Task 4 2026-07-13 设计修正），
并按 path 关联 content_unit 表中的内容单元。内容单元不是可见性门槛——
所有文件系统条目均返回。仅使用 Path.iterdir / is_dir / is_file / stat（只读）。

路径比较统一使用 make_path_key()（normcase + normpath）归一化，
不依赖 Path.resolve()（后者会访问文件系统解析符号链接，语义不一致）。
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from application.errors import ContentUnitNotFoundError, InvalidContentUnitPathError
from domain.models import ContentUnit, FileEntry
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.errors import (
    ConstraintViolationError,  # noqa: F401
    RepositoryError,
)

logger = logging.getLogger(__name__)


def _default_now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_uuid_provider() -> str:
    return str(uuid.uuid4())


class ContentService:
    """内容单元服务：查询与元数据写入。"""

    def __init__(
        self,
        content_unit_repo: ContentUnitRepository,
        now_provider: Callable[[], str] | None = None,
        uuid_provider: Callable[[], str] | None = None,
    ) -> None:
        self._repo = content_unit_repo
        self._now = now_provider or _default_now_utc
        self._new_uuid = uuid_provider or _default_uuid_provider

    def list_by_directory(self, dir_path: str) -> list[ContentUnit]:
        """返回 dir_path 及其所有子目录下的内容单元。

        委托 ContentUnitRepository.list_by_path_prefix_normalized（TD-H7 修复：
        原 list_by_path_prefix 已删除，统一使用 normalized 接口）。
        """
        return self._repo.list_by_path_prefix_normalized(dir_path)

    def list_direct_children(self, dir_path: str) -> list[ContentUnit]:
        """只返回 path 直接属于 dir_path 的内容单元。

        判断规则：Path(unit.path).parent 与 dir_path 指向同一目录。
        使用 make_path_key() 归一化后比较，避免大小写/分隔符差异。

        特别地，当 unit.path 本身就是 dir_path（内容单元路径等于目录路径）时，
        也视为直接子项返回。
        """
        all_units = self._repo.list_by_path_prefix_normalized(dir_path)
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

    def get_by_path(self, path: str) -> ContentUnit | None:
        """按路径精确查询内容单元；不存在返回 None。"""
        return self._repo.get_by_path(path)

    def create_content_unit(
        self,
        path: Path,
        title: str | None = None,
        content_type: str = "mod",
        status: str = "unorganized",
    ) -> ContentUnit:
        """创建新 ContentUnit。

        Args:
            path: 内容单元对应的真实路径（文件或文件夹）。
            title: 标题，默认 None（显示时回退到路径名）。
            content_type: 类型，默认 "mod"。
            status: 状态，默认 "unorganized"。

        Returns:
            新创建的 ContentUnit。

        Raises:
            ConstraintViolationError: path 已存在 ContentUnit。
        """
        now = self._now()
        unit = ContentUnit(
            id=self._new_uuid(),
            path=str(path),
            title=title,
            content_type=content_type,
            status=status,
            created_at=now,
            updated_at=now,
        )
        return self._repo.create(unit)

    def mark_as_content_unit(self, path: Path) -> ContentUnit:
        """标记路径为内容单元。

        spec §5.4 关键规则：手动标记文件夹为内容单元时，其内部的所有内容单元
        标记自动取消（避免父子同时标记）。

        行为：
        - 若 path 已是 ContentUnit 且 status != "unmarked"：返回现有 unit（不重复创建）。
        - 若 path 已是 ContentUnit 且 status == "unmarked"：恢复为 "unorganized"（重新标记）。
        - 若 path 是文件夹：先 list_by_path_prefix_normalized 查询子项 ContentUnit
          （不含自身），逐个 delete 非 "unmarked" 子项（ContentUnitRepository.delete
          已级联清理 content_unit_tag）；"unmarked" 子项保留（用户显式取消标记的偏好
          不应被覆盖）；然后创建或恢复 ContentUnit。
        - 若 path 是文件：直接创建（不查子项）。

        Args:
            path: 待标记的文件或文件夹路径。

        Returns:
            新创建或已存在的 ContentUnit。

        Raises:
            InvalidContentUnitPathError: 路径不存在或不可访问。
        """
        # 路径合法性校验（只读检查）
        try:
            if not path.exists():
                raise InvalidContentUnitPathError(f"路径不存在：{path}")
        except OSError as e:
            raise InvalidContentUnitPathError(f"无法访问路径：{e}") from e

        # 查询现有记录
        existing = self._repo.get_by_path(str(path))

        # 已标记且非 unmarked：返回现有（不重复创建）
        if existing is not None and existing.status != "unmarked":
            return existing

        # 文件夹：取消子项标记（保留 "unmarked" 子项）
        try:
            is_dir = path.is_dir()
        except OSError as e:
            raise InvalidContentUnitPathError(f"无法访问路径：{e}") from e

        if is_dir:
            children = self._repo.list_by_path_prefix_normalized(str(path))
            # 排除 path 自身（list_by_path_prefix_normalized 含 prefix 自身）
            for child in children:
                if make_path_key(child.path) != make_path_key(str(path)):
                    if child.status == "unmarked":
                        continue  # 保留用户显式取消标记的偏好
                    try:
                        self._repo.delete(child.id)
                    except (RepositoryError, sqlite3.Error):  # noqa: BLE001
                        logger.exception("取消子项标记失败：unit_id=%s", child.id)

        # 创建新记录或恢复 unmarked 记录
        if existing is not None:
            # existing.status == "unmarked" → 恢复为 unorganized
            updated = replace(existing, status="unorganized", updated_at=self._now())
            return self._repo.update(updated)

        # 默认 title=path.name（文件名或文件夹名），避免元数据面板显示"（无标题）"
        return self.create_content_unit(path, title=path.name)

    def unmark_content_unit(self, unit_id: str) -> None:
        """取消内容单元标记。

        将 ContentUnit 的 status 设为 "unmarked"（而非删除记录），使扫描不再
        重复创建该路径的内容单元（roadmap：扫描候选的纠错能力）。**不删除真实文件**。

        UI 层将 "unmarked" 状态视为无内容单元（不显示标记、不响应双击）。
        若用户再次 mark_as_content_unit，status 恢复为 "unorganized"。

        Args:
            unit_id: 待取消的 ContentUnit ID。

        Raises:
            ContentUnitNotFoundError: unit_id 不存在。
        """
        unit = self._repo.get_by_id(unit_id)
        if unit is None:
            raise ContentUnitNotFoundError(f"内容单元不存在：{unit_id}")
        if unit.status == "unmarked":
            return  # 已取消标记，幂等
        updated = replace(unit, status="unmarked", updated_at=self._now())
        self._repo.update(updated)

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
        - 批量预查 content_unit（一次 list_by_path_prefix_normalized 取回所有
          相关单元，构建 path_key → ContentUnit 映射），避免 N 次 DB 查询。

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
        # "unmarked" 状态的单元不纳入映射（视为无内容单元）
        # 使用 list_by_path_prefix_normalized（统一归一化接口，原 list_by_path_prefix
        # 已在 TD-L20 清理中删除）
        unit_map: dict[str, ContentUnit] = {}
        try:
            units = self._repo.list_by_path_prefix_normalized(staging_path)
            for unit in units:
                if unit.status == "unmarked":
                    continue
                unit_map[make_path_key(unit.path)] = unit
        except (RepositoryError, sqlite3.Error):  # 数据库查询失败不阻塞文件系统遍历
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

        # spec §7.3：暂存区文件列表显示"零散文件"。
        # 若某个文件夹已被标记为内容单元（即 Mod 组文件夹），
        # 其内部的子文件/子文件夹视为"已收纳"，不再显示在列表中。
        # 这与 spec §5.4（标记文件夹时取消子项标记）的语义一致。
        cu_folder_keys: set[str] = set()
        for entry in entries:
            if entry.is_dir and entry.content_unit is not None:
                cu_folder_keys.add(make_path_key(entry.path))

        if cu_folder_keys:
            filtered: list[FileEntry] = []
            for entry in entries:
                if self._has_ancestor_in_set(entry.path, cu_folder_keys):
                    continue
                filtered.append(entry)
            entries = filtered

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
            # "unmarked" 状态视为无内容单元（用户显式取消标记）
            if content_unit is not None and content_unit.status == "unmarked":
                content_unit = None
        except (RepositoryError, sqlite3.Error):  # 数据库查询失败不应中断遍历
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

    def _has_ancestor_in_set(self, path: str, ancestor_keys: set[str]) -> bool:
        """检查 path 的任一祖先（不含自身）是否在 ancestor_keys 集合中。

        基于 make_path_key 归一化后比较。
        从 path.parent 逐级向上直到根目录。
        """
        p = Path(path)
        parent = p.parent
        while parent != parent.parent:
            if make_path_key(parent) in ancestor_keys:
                return True
            parent = parent.parent
        return False


def _mtime_to_iso(mtime: float) -> str:
    """把 stat.st_mtime（epoch 秒）转为 ISO 8601 UTC 字符串。"""
    dt = datetime.fromtimestamp(mtime, tz=UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
