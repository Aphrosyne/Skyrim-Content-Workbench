"""Mod 组创建服务。

阶段 3 Task 3：从暂存区零散压缩包文件创建标准化 Mod 组文件夹。

工作流：
1. 从文件名提取主要名称（剔除版本号、扩展名）。
2. 在暂存区创建以该名称命名的新文件夹（FileOperationService.new_folder）。
3. 把源压缩包文件移入新文件夹（FileOperationService.move）。
4. 取消源文件旧路径的 ContentUnit 标记（若存在，设为 "unmarked" 避免悬挂标记）。
5. 为新文件夹标记 ContentUnit（mark_as_content_unit，spec §5.4 标记文件夹时
   取消子项标记；默认 title=path.name）。

失败回滚：若 move 失败，删除已创建的空文件夹（仅当为空时）。

约束（AGENTS 规则）：
- 不覆盖已有文件/目录（FileOperationService 已保证）。
- 文件操作通过 FileOperationService，本服务不直接调用 shutil / Path.rename。
- 不自提交，由调用方控制事务边界。
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

from application.content_service import ContentService
from application.errors import (
    ApplicationError,
    FileOperationError,
    InvalidModGroupNameError,
    ModGroupSourceNotInStagingError,
)
from domain.models import ContentUnit, FolderCache
from infrastructure.file_operation_service import FileOperationService
from infrastructure.repositories.errors import RepositoryError
from infrastructure.repositories.folder_cache import FolderCacheRepository

logger = logging.getLogger(__name__)


# Nexus Mods 下载文件名正则模式。
#
# Nexus 下载文件命名规律：`Mod名称-数字ID-版本号-时间戳`
# 例如：
#   "Alt-Tab Fix-148466-1-0-0-1745430887.zip"
#   "monster race crash fix-19899-1-2-1583905408.zip"
#   "Erin Suzu preset-173150-1-0-1771738716"
#
# 关键特征：第一个以 `-` 分隔的纯数字段是 Nexus Mod ID，
# ID 之后的所有内容（版本号、时间戳）都应剔除，
# ID 之前的内容是 Mod 名称（保留原样，包括名称内部的 `-`）。
#
# 模式解释：
#   ^(?P<name>.+?)       — 名称部分（非贪婪，包含名称内部的 `-`）
#   -                    — 名称与 ID 之间的分隔符
#   (?P<id>\d+)          — 纯数字 Mod ID
#   (?:-\d+)+            — 后续至少一个版本号段 / 时间戳段（每段以 - 开头）
#   $                    — 末尾
#
# 非贪婪 + 后续至少一个数字段，确保 name 不会吞掉 ID。
# 要求 ID 后至少有一个段，避免误匹配 "Mod-123" 这种短名。
_NEXUS_PATTERN = re.compile(r"^(?P<name>.+?)-(?P<id>\d+)(?:-\d+)+$")


# 通用版本号正则模式（回退策略，用于非 Nexus 命名）
# 匹配末尾的 " 1.0" / " v2.3" / " - 3.1" / " 1.0.0" / " 5.1 SE" 等形式
# 不匹配下划线分隔（避免误剔除 "ModName_1.0" 这种可能是名字本身的情况）
_VERSION_PATTERN = re.compile(
    r"""
    \s*              # 前导空白（可选）
    (?:-\s*)?        # 可选的 - 分隔符
    v?               # 可选的 v 前缀
    \d+              # 至少一位数字
    (?:\.\d+)+       # 至少一个 .数字 组合（如 .0 / .1.0 / .5.1）
    (?:\s*(?:SE|LE|SSE|AE))?  # 可选的 SE/LE/SSE/AE 后缀
    \s*$             # 末尾空白（可选）
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_mod_name(filename: str) -> str:
    """从文件名提取主要名称。

    支持两种命名规则：

    1. Nexus Mods 下载命名：`Mod名称-数字ID-版本号-时间戳`
       例如：
         "Alt-Tab Fix-148466-1-0-0-1745430887.zip" → "Alt-Tab Fix"
         "monster race crash fix-19899-1-2-1583905408.zip" → "monster race crash fix"
         "Erin Suzu preset-173150-1-0-1771738716" → "Erin Suzu preset"

    2. 通用命名（社区分享、汉化包等）：剔除末尾版本号
       例如：
         "BDOR Black Knight 1.0.7z" → "BDOR Black Knight"
         "SkyUI 5.1 SE.zip" → "SkyUI"
         "Armor Pack - 2.3.7z" → "Armor Pack"
         "RealisticWater.7z" → "RealisticWater"（无版本号，仅去扩展名）
         "寒霜之心 1.0.7z" → "寒霜之心"

    Args:
        filename: 文件名（含扩展名，不含目录路径）。

    Returns:
        提取的主要名称。若无版本号且非 Nexus 命名，返回去扩展名的部分。
    """
    # 先去扩展名（Path.stem 处理多扩展名场景，如 "file.1.0.7z" → "file.1.0"）
    stem = Path(filename).stem

    # 优先尝试 Nexus 命名规则
    # 要求：至少包含 ID + 一个后续段（版本号或时间戳），避免误匹配 "Mod-123" 这种短名
    nexus_match = _NEXUS_PATTERN.match(stem)
    if nexus_match:
        name = nexus_match.group("name").strip()
        if name:
            return name

    # 回退：通用版本号剔除（兼容社区分享、汉化包等命名）
    # rstrip(" .-") 剥离版本号前的分隔符（空格 / - / .）
    match = _VERSION_PATTERN.search(stem)
    if match:
        return stem[: match.start()].rstrip(" .-")
    return stem


class ModGroupService:
    """Mod 组创建服务。

    使用方式：
        service = ModGroupService(file_op_service, content_service, folder_cache_repo)
        unit = service.create_mod_group(Path("D:/Stash/file.7z"), Path("D:/Stash"), "NewMod")
    """

    def __init__(
        self,
        file_op_service: FileOperationService,
        content_service: ContentService,
        folder_cache_repo: FolderCacheRepository | None = None,
    ) -> None:
        self._file_op = file_op_service
        self._content = content_service
        self._folder_cache_repo = folder_cache_repo

    def create_mod_group(
        self,
        source_file: Path,
        staging_path: Path,
        name: str | None = None,
    ) -> ContentUnit:
        """创建 Mod 组：在暂存区建文件夹 + 移入源文件 + 标记 ContentUnit。

        Args:
            source_file: 源压缩包文件路径（必须在 staging_path 之下）。
            staging_path: 暂存区根目录路径。
            name: Mod 组名称。None 时从 source_file 文件名自动提取。

        Returns:
            新创建的 ContentUnit（path 指向新文件夹，title=文件夹名，status=unorganized）。

        Raises:
            ModGroupSourceNotInStagingError: source_file 不在 staging_path 下。
            InvalidModGroupNameError: name 为空或仅含空白。
            ConflictError: 目标文件夹已存在（FileOperationService 抛出）。
            FileOperationError: 其他文件操作失败。
        """
        # 校验 source_file 在 staging_path 下
        if not _is_in_directory(source_file, staging_path):
            raise ModGroupSourceNotInStagingError(
                f"源文件不在暂存区下：{source_file} 不在 {staging_path} 内"
            )

        # 解析名称
        if name is None:
            name = extract_mod_name(source_file.name)
        name = name.strip()
        if not name:
            raise InvalidModGroupNameError("Mod 组名称不能为空")

        target_folder = staging_path / name
        target_file = target_folder / source_file.name

        # 步骤 1：创建新文件夹
        # 若文件夹已存在，FileOperationService.new_folder 抛 ConflictError
        self._file_op.new_folder(target_folder)

        # 步骤 1b：同步写入 folder_cache（目录树数据源），使目录树立即可见
        # 父目录为 staging_path，需查找其 folder_cache.id 作为 parent_id。
        # 注意：不能用 get_by_path（精确字符串匹配），因为 staging_path 字符串
        # 与 folder_cache.path 存储的字符串可能存在大小写/分隔符差异。
        # 改用 make_path_key 归一化后比较，与 ScanService._resolve_parent_id 一致。
        #
        # H2 修复（2026-07-17 Code Review）：folder_cache 写入失败不再吞异常。
        # 原实现 ``except Exception: logger.exception(...)`` 让上层 _commit 把
        # 部分成功状态提交进数据库，导致目录树静默缺节点。新契约：写入失败立即抛出
        # FileOperationError，由上层 rollback 回滚 new_folder + move（move 尚未执行，
        # 可安全回滚）。回滚后 _try_cleanup_empty_folder 由调用方在 move 失败路径处理。
        if self._folder_cache_repo is not None:
            try:
                parent_id = self._resolve_parent_id_by_path(str(staging_path))
                # 用当前 mtime 作为 last_scanned_mtime（近似值，下次全量扫描会修正）
                mtime = target_folder.stat().st_mtime
                folder = FolderCache(
                    id=self._new_folder_cache_id(),
                    path=str(target_folder),
                    parent_id=parent_id,
                    last_scanned_mtime=mtime,
                    created_at=self._now_iso(),
                )
                self._folder_cache_repo.create(folder)
            except (RepositoryError, sqlite3.Error, OSError) as fc_err:
                logger.exception(
                    "写入 folder_cache 失败（将回滚 new_folder）：path=%s",
                    target_folder,
                )
                # 清理已创建的空文件夹，避免遗留
                _try_cleanup_empty_folder(target_folder)
                raise FileOperationError(f"写入 folder_cache 失败：{fc_err}") from fc_err

        # 步骤 2：移入源文件
        # 若 move 失败，回滚：删除刚创建的空文件夹（仅当为空时）
        try:
            self._file_op.move(source_file, target_file)
        except (FileOperationError, OSError) as move_err:
            _try_cleanup_empty_folder(target_folder)
            raise FileOperationError(f"移动源文件失败：{move_err}") from move_err

        # 步骤 3：取消源文件的旧 ContentUnit 标记（若存在）
        # 源文件已移动，旧路径的 ContentUnit 记录设为 "unmarked"（不可见，
        # 扫描不会重建），避免用户看到悬挂标记。
        old_unit = self._content.get_by_path(str(source_file))
        if old_unit is not None:
            try:
                self._content.unmark_content_unit(old_unit.id)
            except (ApplicationError, RepositoryError, sqlite3.Error):
                logger.exception("取消源文件旧 ContentUnit 标记失败：path=%s", source_file)

        # 步骤 4：为新文件夹标记 ContentUnit
        # 使用 mark_as_content_unit（spec §5.4：标记文件夹时取消子项标记），
        # 默认 title=path.name（即文件夹名 == name）。
        try:
            return self._content.mark_as_content_unit(target_folder)
        except (ApplicationError, RepositoryError, sqlite3.Error) as create_err:
            # ContentUnit 创建失败不回滚文件操作（文件已移动，无法自动复原）
            # 记日志，由用户手动处理
            logger.exception(
                "创建 ContentUnit 失败（文件已移动到 %s），请手动添加内容单元标记",
                target_folder,
            )
            raise FileOperationError(f"创建 ContentUnit 失败：{create_err}") from create_err

    def _resolve_parent_id_by_path(self, parent_path: str) -> str | None:
        """按路径查找 folder_cache.id（用于新建子文件夹时的 parent_id 关联）。

        使用 make_path_key 归一化后比较，避免大小写/分隔符差异导致匹配失败。
        与 ScanService._resolve_parent_id 保持一致的归一化策略。

        Args:
            parent_path: 父目录路径字符串。

        Returns:
            folder_cache.id；不存在返回 None。
        """
        from infrastructure.path_utils import make_path_key

        target_key = make_path_key(parent_path)
        for fc in self._folder_cache_repo.list_all():
            if make_path_key(fc.path) == target_key:
                return fc.id
        return None

    def _new_folder_cache_id(self) -> str:
        """生成 folder_cache 的 UUID。"""
        import uuid

        return str(uuid.uuid4())

    def _now_iso(self) -> str:
        """返回当前 UTC 时间的 ISO 8601 字符串。"""
        from datetime import UTC, datetime

        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_in_directory(file_path: Path, dir_path: Path) -> bool:
    """判断 file_path 是否在 dir_path 之下（含 dir_path 自身）。

    使用 make_path_key 归一化后字符串前缀比较，避免大小写/分隔符差异。
    不访问文件系统，仅基于路径字符串比较。
    """
    import os

    from infrastructure.path_utils import make_path_key

    sep = os.sep
    dir_key = make_path_key(dir_path).rstrip(sep) + sep
    file_key = make_path_key(file_path)
    return file_key.startswith(dir_key)


def _try_cleanup_empty_folder(folder: Path) -> None:
    """尝试删除空文件夹（仅当为空时）。失败静默记日志。"""
    try:
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    except OSError as e:
        logger.warning("清理空文件夹失败 %s: %s", folder, e)
