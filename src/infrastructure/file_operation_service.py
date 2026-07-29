"""文件操作服务（简化版）。

阶段 3 Task 3：实现 new_folder + move 两个最小方法，每次操作写 operation_history 表。
rename / delete / undo 完整版留待阶段 5。

Stage 4.5 H4：可选注入 FolderCacheSyncHelper + ContentUnitRepository，
new_folder/move 自动同步 folder_cache + ContentUnit.path，消除调用方
（ModGroupService/QuickInsertService/AssemblyService）手动同步的隐式契约（TD-M22）。
注入后调用方无需再各自实现 _resolve_parent_id_by_path / _sync_folder_cache 等
重复逻辑；未注入（helper/repo 为 None）时保持原行为，向后兼容。

约束（AGENTS 规则 2/3）：
- 不覆盖已有文件/目录：目标存在抛 ConflictError。
- 跨盘移动检测：抛 CrossDriveError（Task 3 范围内 move 仅用于"创建 Mod 组"同盘移动，
  跨盘检测留作通用 move 的安全护栏）。
- 自目录移动检测：抛 SelfSubdirectoryError。
- 写 operation_history 在文件操作 + 同步成功后；失败不写历史。
- 不自提交，由调用方控制事务边界。
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from application.errors import (
    ConflictError,
    CrossDriveError,
    FileOperationError,
    SelfSubdirectoryError,
    SourceNotFoundError,
)
from domain.models import ContentUnit, OperationHistory
from infrastructure.folder_cache_sync_helper import FolderCacheSyncHelper
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.errors import RepositoryError
from infrastructure.repositories.operation_history import OperationHistoryRepository

logger = logging.getLogger(__name__)


def _default_now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_uuid_provider() -> str:
    return str(uuid.uuid4())


def _try_cleanup_empty_folder(folder: Path) -> None:
    """尝试删除空文件夹（仅当为空时）。失败静默记日志。"""
    try:
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    except OSError as e:
        logger.warning("清理空文件夹失败 %s: %s", folder, e)


class FileOperationService:
    """文件操作服务（简化版）：new_folder + move。

    Stage 4.5 H4：可选注入 FolderCacheSyncHelper + ContentUnitRepository，
    注入后 new_folder/move 自动同步 folder_cache + ContentUnit.path。

    使用方式：
        # 无注入（向后兼容，调用方手动同步 folder_cache）
        service = FileOperationService(OperationHistoryRepository(conn))

        # H4 注入（推荐，调用方无需手动同步）
        helper = FolderCacheSyncHelper(folder_cache_repo)
        service = FileOperationService(
            OperationHistoryRepository(conn),
            folder_cache_helper=helper,
            content_unit_repo=ContentUnitRepository(conn),
        )
        history = service.new_folder(Path("D:/Mods/Stash/NewMod"))
        history = service.move(Path("D:/Mods/OldMod"), Path("D:/Mods/NewMod"))
    """

    def __init__(
        self,
        history_repo: OperationHistoryRepository,
        now_provider: Callable[[], str] | None = None,
        uuid_provider: Callable[[], str] | None = None,
        folder_cache_helper: FolderCacheSyncHelper | None = None,
        content_unit_repo: ContentUnitRepository | None = None,
    ) -> None:
        """初始化 FileOperationService。

        Args:
            history_repo: 操作历史仓储。
            now_provider: 时间戳生成器（测试可注入）。
            uuid_provider: UUID 生成器（测试可注入）。
            folder_cache_helper: folder_cache 同步辅助（可选）。Stage 4.5 H4：
                注入后 new_folder/move 自动同步 folder_cache，消除调用方手动同步。
                None 时保持原行为。
            content_unit_repo: ContentUnit 仓储（可选）。Stage 4.5 H4：
                注入后 move 目录时自动重写 ContentUnit.path 前缀。
                None 时不更新 ContentUnit.path（调用方自行处理）。
        """
        self._repo = history_repo
        self._now = now_provider or _default_now_utc
        self._new_uuid = uuid_provider or _default_uuid_provider
        # Stage 4.5 H4：folder_cache 同步 + ContentUnit.path 更新
        self._folder_cache_helper = folder_cache_helper
        self._content_unit_repo = content_unit_repo

    def new_folder(self, folder_path: Path) -> OperationHistory:
        """创建新文件夹。

        - 父目录必须存在（只读检查）。
        - 目标不能已存在（不覆盖，AGENTS 规则 2）。
        - Stage 4.5 H4：注入 helper 后自动同步 folder_cache（插入新节点）。
          同步失败清理空文件夹并抛 FileOperationError。
        - 成功后写 operation_history（operation_type='new_folder'，
          source_path=父目录路径，target_path=新文件夹路径）。

        Args:
            folder_path: 新文件夹的完整路径。

        Returns:
            OperationHistory 记录。

        Raises:
            SourceNotFoundError: 父目录不存在。
            ConflictError: 目标已存在。
            FileOperationError: 其他文件系统错误或 folder_cache 同步失败。
        """
        parent = folder_path.parent
        try:
            if not parent.exists():
                raise SourceNotFoundError(f"父目录不存在：{parent}")
            if not parent.is_dir():
                raise SourceNotFoundError(f"父路径不是目录：{parent}")
        except OSError as e:
            raise FileOperationError(f"无法访问父目录：{e}") from e

        try:
            if folder_path.exists():
                raise ConflictError(f"目标已存在：{folder_path}")
        except OSError as e:
            raise FileOperationError(f"无法检查目标路径：{e}") from e

        try:
            folder_path.mkdir(parents=False, exist_ok=False)
        except FileExistsError as e:
            raise ConflictError(f"目标已存在：{folder_path}") from e
        except OSError as e:
            raise FileOperationError(f"无法创建文件夹：{e}") from e

        # Stage 4.5 H4：自动同步 folder_cache（注入 helper 时）
        if self._folder_cache_helper is not None:
            try:
                self._folder_cache_helper.on_folder_created(folder_path, parent)
            except FileOperationError:
                # folder_cache 写入失败：清理已创建的空文件夹 + re-raise
                _try_cleanup_empty_folder(folder_path)
                raise

        history = OperationHistory(
            id=self._new_uuid(),
            operation_type="new_folder",
            source_path=str(parent),
            target_path=str(folder_path),
            created_at=self._now(),
            can_undo=True,
        )
        try:
            return self._repo.create(history)
        except Exception as e:  # noqa: BLE001
            # 文件操作已成功但写历史失败：记日志，不回滚（用户可手动清理空文件夹）
            logger.exception("写入 operation_history 失败（new_folder：%s）", folder_path)
            raise FileOperationError(f"写入操作历史失败：{e}") from e

    def move(self, src: Path, dst: Path) -> OperationHistory:
        """移动文件或目录到目标路径。

        - 源必须存在。
        - 目标不能已存在（不覆盖，AGENTS 规则 2）。
        - 跨盘检测：src 与 dst.parent 的 st_dev 不同抛 CrossDriveError。
        - 自目录检测：dst 在 src 子树内抛 SelfSubdirectoryError。
        - 使用 shutil.move 保留元数据（copystat）。
        - Stage 4.5 H4：注入 helper/repo 后自动同步 folder_cache + ContentUnit.path：
          * 目录移动：on_folder_moved（删除旧 + 插入新 + 更新父 mtime）+ ContentUnit.path 前缀重写
          * 文件移动：update_folder_mtime（源/目标父目录 mtime 更新，best-effort）
          同步失败抛 FileOperationError，由上层 UoW 回滚 DB 写操作。
          文件已移动无法回滚，由调用方处理。
        - 成功后写 operation_history（operation_type='move'，
          source_path=src，target_path=dst）。

        Args:
            src: 源文件/目录路径。
            dst: 目标完整路径（含文件名）。

        Returns:
            OperationHistory 记录。

        Raises:
            SourceNotFoundError: 源不存在。
            ConflictError: 目标已存在。
            CrossDriveError: 跨盘移动。
            SelfSubdirectoryError: 移动到自身子目录。
            FileOperationError: 其他文件系统错误或同步失败。
        """
        try:
            if not src.exists():
                raise SourceNotFoundError(f"源不存在：{src}")
        except OSError as e:
            raise FileOperationError(f"无法访问源路径：{e}") from e

        try:
            if dst.exists():
                raise ConflictError(f"目标已存在：{dst}")
        except OSError as e:
            raise FileOperationError(f"无法检查目标路径：{e}") from e

        # 跨盘检测
        try:
            src_dev = src.stat().st_dev
            dst_parent = dst.parent
            if not dst_parent.exists():
                raise SourceNotFoundError(f"目标父目录不存在：{dst_parent}")
            dst_dev = dst_parent.stat().st_dev
            if src_dev != dst_dev:
                raise CrossDriveError(
                    f"跨盘移动不支持：{src}（dev={src_dev}）→ {dst}（dev={dst_dev}）"
                )
        except OSError as e:
            raise FileOperationError(f"无法获取路径设备号：{e}") from e

        # 自目录检测：dst 在 src 子树内
        # 用字符串前缀比较（src 是目录时，dst 以 src + sep 开头则违规）
        sep = os.sep
        src_str = str(src).rstrip(sep) + sep
        dst_str = str(dst)
        if dst_str.startswith(src_str):
            raise SelfSubdirectoryError(f"不能移动到自身子目录：{src} → {dst}")

        try:
            shutil.move(str(src), str(dst))
        except OSError as e:
            raise FileOperationError(f"无法移动：{src} → {dst}：{e}") from e

        # Stage 4.5 H4：自动同步 folder_cache + ContentUnit.path
        self._sync_on_move(src, dst)

        history = OperationHistory(
            id=self._new_uuid(),
            operation_type="move",
            source_path=str(src),
            target_path=str(dst),
            created_at=self._now(),
            can_undo=True,
        )
        try:
            return self._repo.create(history)
        except Exception as e:  # noqa: BLE001
            logger.exception("写入 operation_history 失败（move：%s → %s）", src, dst)
            raise FileOperationError(f"写入操作历史失败：{e}") from e

    def _sync_on_move(self, src: Path, dst: Path) -> None:
        """移动后同步 folder_cache + ContentUnit.path。

        - 目录移动：on_folder_moved（删除旧 + 插入新 + 更新父 mtime）+ ContentUnit.path 前缀重写
        - 文件移动：update_folder_mtime（源/目标父目录 mtime 更新，best-effort）

        同步失败抛 FileOperationError，由上层 UoW 回滚 DB 写操作。
        文件已移动无法回滚，由调用方处理。

        未注入 helper/repo 时为空操作（向后兼容）。
        """
        if self._folder_cache_helper is None and self._content_unit_repo is None:
            return

        try:
            is_dir = dst.is_dir()
        except OSError as e:
            logger.warning("无法判断移动后目标类型 %s: %s", dst, e)
            return

        if is_dir:
            # 目录移动：完整 folder_cache 同步 + ContentUnit.path 重写
            if self._folder_cache_helper is not None:
                self._folder_cache_helper.on_folder_moved(src, dst, dst.parent)
            if self._content_unit_repo is not None:
                self._update_content_unit_paths_on_move(src, dst)
        else:
            # 文件移动：仅更新父目录 mtime（folder_cache 只记录目录）
            # mtime 更新为 best-effort（TD-L18 策略），失败不阻塞主流程
            if self._folder_cache_helper is not None:
                self._folder_cache_helper.update_folder_mtime(dst.parent)
                if make_path_key(src.parent) != make_path_key(dst.parent):
                    self._folder_cache_helper.update_folder_mtime(src.parent)

    def _update_content_unit_paths_on_move(self, src: Path, dst: Path) -> None:
        """移动目录后，更新所有路径前缀匹配的 ContentUnit.path。

        包括：
        - ContentUnit.path == src → 更新为 dst
        - ContentUnit.path 以 src/ 开头 → 替换前缀为 dst/

        使用 list_by_path_prefix_normalized 查找（归一化匹配），
        路径重写尽量保留原始大小写（Path.relative_to），失败时回退到归一化后缀。

        Raises:
            FileOperationError: ContentUnit.path 更新失败。
        """
        affected = self._content_unit_repo.list_by_path_prefix_normalized(str(src))
        if not affected:
            return

        src_key = make_path_key(src)
        dst_str = str(dst)
        sep = os.sep
        src_prefix = src_key.rstrip(sep) + sep

        for unit in affected:
            unit_key = make_path_key(unit.path)
            if unit_key == src_key:
                new_path = dst_str
            elif unit_key.startswith(src_prefix):
                # 尝试保留原始大小写
                try:
                    relative = Path(unit.path).relative_to(src)
                    new_path = str(dst / relative)
                except ValueError:
                    # 大小写/分隔符差异：使用归一化后缀（Windows 大小写不敏感，路径仍有效）
                    suffix = unit_key[len(src_key) :]
                    new_path = dst_str + suffix
            else:
                continue

            updated = ContentUnit(
                id=unit.id,
                path=new_path,
                title=unit.title,
                content_type=unit.content_type,
                source_url=unit.source_url,
                cover_path=unit.cover_path,
                status=unit.status,
                notes=unit.notes,
                created_at=unit.created_at,
                updated_at=unit.updated_at,
            )
            try:
                self._content_unit_repo.update(updated)
            except (RepositoryError, sqlite3.Error) as e:
                raise FileOperationError(
                    f"更新 ContentUnit 路径失败：unit_id={unit.id} err={e}"
                ) from e
