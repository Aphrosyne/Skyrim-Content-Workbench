"""装配服务（阶段 3 Task 4）。

协调"装配面板"工作流：从暂存区拖入附加文件到 Mod 组文件夹，
或从 Mod 组移除文件回暂存区。

设计要点（2026-07-16 确认）：
- 不自动重命名图片。自动整理阶段不修改任何文件名，避免破坏用户已有命名。
- 移除文件时统一移回暂存区根目录（不保留原子目录结构）。
- 手动重命名预览图：`{Mod组名}.{扩展名}`，多张图片 `_2`、`_3` 后缀。
- 装配面板绑定"当前选中 Mod 组"，整理模式下切换不同 Mod 组时刷新内容。

约束（AGENTS 规则）：
- 不覆盖已有文件/目录（FileOperationService 已保证）。
- 文件操作通过 FileOperationService，本服务不直接调用 shutil / Path.rename。
- 不自提交，由调用方控制事务边界。
- folder_cache 同步：移动文件后更新 Mod 组文件夹的 last_scanned_mtime，
  避免下次增量扫描重复处理（与 ModGroupService 模式一致）。
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from application.errors import (
    ConflictError,
    ContentUnitNotFoundError,
    InvalidContentUnitPathError,
)
from domain.models import ContentUnit, FileEntry
from infrastructure.file_operation_service import FileOperationService
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.errors import RepositoryError
from infrastructure.repositories.folder_cache import FolderCacheRepository

logger = logging.getLogger(__name__)


# 支持的图片扩展名（spec §9）
_IMAGE_EXTENSIONS = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
        ".ico",
    }
)


def _default_now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_uuid_provider() -> str:
    return str(uuid.uuid4())


def is_image_file(path: Path) -> bool:
    """判断路径是否为支持的图片文件（按扩展名）。"""
    return path.suffix.lower() in _IMAGE_EXTENSIONS


class AssemblyService:
    """装配服务：Mod 组文件夹的文件增删 + 预览图手动重命名。

    使用方式：
        service = AssemblyService(
            file_op_service, content_unit_repo, folder_cache_repo
        )
        files = service.list_mod_group_files(unit_id)
        service.add_file(unit_id, Path("D:/Stash/汉化.zip"))
        service.remove_file(unit_id, "汉化.zip", Path("D:/Stash"))
        service.rename_as_cover(unit_id, Path("D:/Stash/Mod/preview.png"))
    """

    def __init__(
        self,
        file_op_service: FileOperationService,
        content_unit_repo: ContentUnitRepository,
        folder_cache_repo: FolderCacheRepository | None = None,
        now_provider: Callable[[], str] | None = None,
        uuid_provider: Callable[[], str] | None = None,
    ) -> None:
        self._file_op = file_op_service
        self._content_repo = content_unit_repo
        self._folder_cache_repo = folder_cache_repo
        self._now = now_provider or _default_now_utc
        self._new_uuid = uuid_provider or _default_uuid_provider

    # --- 查询 ---

    def list_mod_group_files(self, unit_id: str) -> list[FileEntry]:
        """列出 Mod 组文件夹内的所有文件和子文件夹条目。

        数据源为文件系统（Path.iterdir），与 ContentService.list_directory_entries
        一致的条目结构。若 unit_id 不存在或路径不可访问，返回空列表。

        Args:
            unit_id: ContentUnit ID（必须指向一个文件夹）。

        Returns:
            FileEntry 列表（文件夹在前，名称升序）。
        """
        unit = self._get_unit_or_raise(unit_id)
        folder_path = Path(unit.path)
        try:
            if not folder_path.is_dir():
                logger.warning("list_mod_group_files: ContentUnit 路径不是目录：%s", unit.path)
                return []
        except OSError as e:
            logger.warning("list_mod_group_files: 路径检查失败 %s: %s", unit.path, e)
            return []

        entries: list[FileEntry] = []
        try:
            for child in folder_path.iterdir():
                entry = self._build_entry(child)
                if entry is not None:
                    entries.append(entry)
        except OSError as e:
            logger.warning("list_mod_group_files: 读取目录失败 %s: %s", unit.path, e)
            return []

        # 文件夹在前，名称不区分大小写升序（与 ContentService 保持一致）
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower(), e.name))
        return entries

    # --- 装配操作 ---

    def add_file(self, unit_id: str, src_path: Path) -> FileEntry:
        """从暂存区拖入文件到 Mod 组文件夹（真实移动）。

        - 源文件必须存在。
        - 目标路径 = Mod 组文件夹 / src_path.name，不能已存在（AGENTS 规则 2）。
        - 移动后同步更新 folder_cache.last_scanned_mtime。
        - 不自动重命名（spec §7.4：自动整理阶段不修改任何文件名）。

        Args:
            unit_id: 目标 Mod 组 ContentUnit ID。
            src_path: 源文件路径（通常在暂存区内）。

        Returns:
            移动后的 FileEntry（指向 Mod 组文件夹内的新路径）。

        Raises:
            ContentUnitNotFoundError: unit_id 不存在。
            ConflictError: 目标路径已存在同名文件。
            FileOperationError: 其他文件操作失败。
        """
        unit = self._get_unit_or_raise(unit_id)
        folder_path = Path(unit.path)
        dst_path = folder_path / src_path.name

        self._file_op.move(src_path, dst_path)
        self._sync_folder_mtime(folder_path)

        # 返回新位置的 FileEntry（不关联 content_unit，装配面板不需要）
        return self._build_entry(dst_path) or FileEntry(
            name=dst_path.name,
            path=str(dst_path),
            is_dir=False,
            modified_at=self._now(),
            size=None,
            content_unit=None,
        )

    def remove_file(self, unit_id: str, filename: str, staging_path: Path) -> Path:
        """从 Mod 组移除文件，移回暂存区根目录。

        - 不保留原子目录结构（统一移到 staging_path 根目录）。
        - 目标路径 = staging_path / filename，不能已存在。
        - 移动后同步更新 Mod 组 folder_cache.last_scanned_mtime。

        Args:
            unit_id: Mod 组 ContentUnit ID。
            filename: 待移除的文件名（不含目录路径）。
            staging_path: 暂存区根目录路径。

        Returns:
            文件移回后的新路径。

        Raises:
            ContentUnitNotFoundError: unit_id 不存在。
            ConflictError: 暂存区根目录已存在同名文件。
            FileOperationError: 其他文件操作失败。
        """
        unit = self._get_unit_or_raise(unit_id)
        folder_path = Path(unit.path)
        src_path = folder_path / filename
        dst_path = staging_path / filename

        self._file_op.move(src_path, dst_path)
        self._sync_folder_mtime(folder_path)
        return dst_path

    # --- 手动重命名预览图 ---

    def rename_as_cover(self, unit_id: str, image_path: Path) -> Path:
        """将图片重命名为 Mod 组同名（手动操作，spec §7.4）。

        命名规则：
        - 单张：`{Mod组名}.{原扩展名}`
        - 多张：`{Mod组名}_2.{原扩展名}`、`{Mod组名}_3.{原扩展名}`……
        - 冲突走现有 ConflictError 流程（不覆盖，AGENTS 规则 2）。

        image_path 必须在 Mod 组文件夹内，且为支持的图片格式。

        Args:
            unit_id: Mod 组 ContentUnit ID。
            image_path: 待重命名的图片完整路径（必须在 Mod 组文件夹内）。

        Returns:
            重命名后的新路径。

        Raises:
            ContentUnitNotFoundError: unit_id 不存在。
            InvalidContentUnitPathError: image_path 不在 Mod 组文件夹内或非图片。
            ConflictError: 目标名称已存在。
            FileOperationError: 其他文件操作失败。
        """
        unit = self._get_unit_or_raise(unit_id)
        folder_path = Path(unit.path)

        # 校验 image_path 在 Mod 组文件夹内
        if not _is_in_directory(image_path, folder_path):
            raise InvalidContentUnitPathError(
                f"图片不在 Mod 组文件夹内：{image_path} 不在 {folder_path} 内"
            )

        # 校验为图片
        if not is_image_file(image_path):
            raise InvalidContentUnitPathError(f"文件不是支持的图片格式：{image_path}")

        # Mod 组名 = 文件夹名（与 ModGroupService 一致）
        mod_name = folder_path.name
        ext = image_path.suffix  # 保留原扩展名（含点）

        # 构造目标名称：先试 {mod_name}.ext，再试 {mod_name}_2.ext、_3.ext……
        # 注意：若 image_path 自身已经叫 {mod_name}.ext（即第一次重命名），直接返回
        first_name = f"{mod_name}{ext}"
        if image_path.name == first_name:
            return image_path  # 已是目标名称，幂等返回

        target_name = first_name
        suffix_n = 2
        while (folder_path / target_name).exists():
            # 目标已存在且不是自身 → 试下一个后缀
            target_name = f"{mod_name}_{suffix_n}{ext}"
            suffix_n += 1
            # 安全阈值：避免极端情况下死循环
            if suffix_n > 9999:
                raise ConflictError(f"无法生成唯一目标名称（已尝试到 _{suffix_n}）：{folder_path}")

        target_path = folder_path / target_name
        # 走 FileOperationService.move（含冲突检测 + operation_history）
        # 由于上面已预检查目标不存在，move 内部 ConflictError 一般不会触发
        self._file_op.move(image_path, target_path)
        self._sync_folder_mtime(folder_path)
        return target_path

    # --- 内部 ---

    def _get_unit_or_raise(self, unit_id: str) -> ContentUnit:
        """按 ID 查询 ContentUnit，不存在抛异常。"""
        unit = self._content_repo.get_by_id(unit_id)
        if unit is None:
            raise ContentUnitNotFoundError(f"内容单元不存在：{unit_id}")
        return unit

    def _build_entry(self, child: Path) -> FileEntry | None:
        """从单个 Path 构建 FileEntry（不关联 content_unit，装配面板不需要）。"""
        try:
            if child.is_symlink():
                return None
            is_dir = child.is_dir()
            stat = child.stat()
            modified_at = _mtime_to_iso(stat.st_mtime)
            size: int | None = None if is_dir else stat.st_size
        except OSError as e:
            logger.warning("装配面板构建条目失败 %s: %s", child, e)
            return None

        return FileEntry(
            name=child.name,
            path=str(child),
            is_dir=is_dir,
            modified_at=modified_at,
            size=size,
            content_unit=None,
        )

    def _sync_folder_mtime(self, folder_path: Path) -> None:
        """同步更新 folder_cache.last_scanned_mtime（避免下次扫描重复处理）。

        与 ModGroupService 模式一致：folder_cache 写入失败不阻塞主流程。
        """
        if self._folder_cache_repo is None:
            return
        try:
            target_key = make_path_key(str(folder_path))
            mtime = folder_path.stat().st_mtime
            for fc in self._folder_cache_repo.list_all():
                if make_path_key(fc.path) == target_key:
                    self._folder_cache_repo.upsert_mtime(fc.path, mtime, fc.id)
                    return
        except (RepositoryError, sqlite3.Error, OSError):  # folder_cache 更新失败不阻塞主流程
            logger.exception("更新 folder_cache mtime 失败：path=%s", folder_path)


def _is_in_directory(file_path: Path, dir_path: Path) -> bool:
    """判断 file_path 是否在 dir_path 之下（含 dir_path 自身）。

    使用 make_path_key 归一化后字符串前缀比较，避免大小写/分隔符差异。
    """
    import os

    sep = os.sep
    dir_key = make_path_key(dir_path).rstrip(sep) + sep
    file_key = make_path_key(file_path)
    return file_key.startswith(dir_key)


def _mtime_to_iso(mtime: float) -> str:
    """把 stat.st_mtime（epoch 秒）转为 ISO 8601 UTC 字符串。"""
    dt = datetime.fromtimestamp(mtime, tz=UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
