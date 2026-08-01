"""文件操作服务。

阶段 3 Task 3：实现 new_folder + move 两个最小方法，每次操作写 operation_history 表。
Stage 5 Task 3a：新增 rename + delete_to_recycle_bin，补齐基础文件 CRUD。

Stage 4.5 H4：可选注入 FolderCacheSyncHelper + ContentUnitRepository，
new_folder/move 自动同步 folder_cache + ContentUnit.path，消除调用方
（ContentUnitCreationService/AssemblyService）手动同步的隐式契约（TD-M22）。
注入后调用方无需再各自实现 _resolve_parent_id_by_path / _sync_folder_cache 等
重复逻辑；未注入（helper/repo 为 None）时保持原行为，向后兼容。

UX 重构 Task 7 Step 5（TD-H10）：本服务从 infrastructure 层迁移到 application 层——
其职责（文件操作编排 + folder_cache 同步 + ContentUnit.path 更新 + 操作历史写入）
属于应用层业务编排，且原位置存在 infrastructure → application 反向依赖（import
application.errors）。FolderCacheSyncHelper 仍位于 infrastructure（仅依赖
FolderCacheRepository），由本服务注入使用。

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
        max_history_records: int = 1000,
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
            max_history_records: operation_history 表保留上限（默认 1000）。
                每次写入新记录后自动清理超出上限的最旧记录（保留可撤销记录）。
                设为 0 关闭自动清理。
        """
        self._repo = history_repo
        self._now = now_provider or _default_now_utc
        self._new_uuid = uuid_provider or _default_uuid_provider
        # Stage 4.5 H4：folder_cache 同步 + ContentUnit.path 更新
        self._folder_cache_helper = folder_cache_helper
        self._content_unit_repo = content_unit_repo
        # Stage 5 Task 3b：操作历史自动清理上限
        self._max_history_records = max_history_records

    def _create_history(self, history: OperationHistory) -> OperationHistory:
        """写入操作历史并执行自动清理（上限保护）。

        Stage 5 Task 3b：写入前先检查 operation_history 总数是否已达到上限，
        若已达到则预先清理最旧的不可撤销/已撤销记录（保留可撤销记录供用户撤销），
        然后再写入新记录。这样新记录不会被误删。
        清理失败仅记日志，不阻塞主操作。
        """
        if self._max_history_records > 0:
            try:
                # 预清理到 limit-1，为新记录腾出空间
                deleted = self._repo.delete_oldest_exceeding(
                    self._max_history_records - 1, preserve_can_undo=True
                )
                if deleted > 0:
                    logger.debug("自动清理 %d 条旧操作历史", deleted)
            except Exception:  # noqa: BLE001
                logger.warning("操作历史自动清理失败（非致命）", exc_info=True)
        record = self._repo.create(history)
        return record

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
            return self._create_history(history)
        except Exception as e:  # noqa: BLE001
            # 文件操作已成功但写历史失败：记日志，不回滚（用户可手动清理空文件夹）
            logger.exception("写入 operation_history 失败（new_folder：%s）", folder_path)
            raise FileOperationError(f"写入操作历史失败：{e}") from e

    def move(
        self,
        src: Path,
        dst: Path,
        *,
        overwrite: bool = False,
        record_history: bool = True,
    ) -> OperationHistory:
        """移动文件或目录到目标路径。

        - 源必须存在。
        - 目标不能已存在（不覆盖，AGENTS 规则 2）。
        - overwrite=True 时：目标已存在则先删除目标（用户已确认覆盖），
          同步 folder_cache + ContentUnit 后直接删除（不进回收站，不写 delete 历史）。
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
        - record_history=False 时：执行文件操作 + 同步，但不写 operation_history。
          用于 UndoService 撤销操作时避免产生新的可撤销记录（防止撤销循环）。

        Args:
            src: 源文件/目录路径。
            dst: 目标完整路径（含文件名）。
            overwrite: 是否覆盖已存在的目标（默认 False）。
            record_history: 是否写入 operation_history（默认 True）。

        Returns:
            OperationHistory 记录（record_history=False 时返回未入库的临时对象）。

        Raises:
            SourceNotFoundError: 源不存在。
            ConflictError: 目标已存在且 overwrite=False。
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
                if not overwrite:
                    raise ConflictError(f"目标已存在：{dst}")
                # 覆盖模式：先删除目标 + 同步元数据
                self._remove_target_for_overwrite(dst)
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
        if not record_history:
            # UndoService 撤销时调用：不写历史，避免产生新的可撤销记录（防止撤销循环）
            return history
        try:
            return self._create_history(history)
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

    # === Stage 5 Task 3a：rename + delete_to_recycle_bin ===

    # Windows 文件名非法字符（AGENTS 规则 5：不假设文件名格式，但新建/重命名需校验）
    _INVALID_NAME_CHARS = set('<>:"/\\|?*')

    def rename(
        self, old_path: Path, new_name: str, *, record_history: bool = True
    ) -> OperationHistory:
        """重命名文件或目录。

        - 源必须存在。
        - new_name 非空、不含非法字符（<>:"/\\|?*）、不为 "." 或 ".."。
        - 目标不能已存在（不覆盖，AGENTS 规则 2）。
        - 跨盘检测：Path.rename 在 Windows 上跨盘会失败，本方法提前校验。
        - Stage 4.5 H4：注入 helper/repo 后自动同步 folder_cache + ContentUnit.path：
          * 目录重命名：on_folder_moved（删除旧 + 插入新 + 更新父 mtime）+ ContentUnit.path 前缀重写
          * 文件重命名：update_folder_mtime（父目录 mtime 更新，best-effort）
          同步失败抛 FileOperationError，由上层 UoW 回滚 DB 写操作。
          文件已重命名无法回滚，由调用方处理。
        - 成功后写 operation_history（operation_type='rename'，
          source_path=old_path，target_path=new_path）。
        - record_history=False 时：执行文件操作 + 同步，但不写 operation_history。
          用于 UndoService 撤销操作时避免产生新的可撤销记录（防止撤销循环）。

        Args:
            old_path: 源文件/目录路径。
            new_name: 新名称（仅文件名，不含父目录路径）。
            record_history: 是否写入 operation_history（默认 True）。

        Returns:
            OperationHistory 记录（record_history=False 时返回未入库的临时对象）。

        Raises:
            SourceNotFoundError: 源不存在。
            ConflictError: 目标已存在。
            FileOperationError: 名称非法、跨盘、或其他文件系统错误。
        """
        # 校验 new_name
        if not new_name or not new_name.strip():
            raise FileOperationError("新名称不能为空")
        # 先检查 "." / ".."（这些名称本身会被尾随空格/点校验拦截，需提前判断）
        if new_name.strip() in (".", ".."):
            raise FileOperationError(f"新名称不能为 '{new_name.strip()}'")
        # Windows 文件名尾随空格/点会被自动去除，提前校验避免静默不一致
        # 必须在 strip 之前检查，否则 strip 后尾随空格已被去除，校验失效
        if new_name != new_name.rstrip(" ."):
            raise FileOperationError("新名称不能以空格或点结尾")
        new_name = new_name.strip()
        if any(c in self._INVALID_NAME_CHARS for c in new_name):
            raise FileOperationError(f"新名称含非法字符 {self._INVALID_NAME_CHARS}：{new_name}")

        try:
            if not old_path.exists():
                raise SourceNotFoundError(f"源不存在：{old_path}")
        except OSError as e:
            raise FileOperationError(f"无法访问源路径：{e}") from e

        new_path = old_path.parent / new_name

        try:
            if new_path.exists():
                raise ConflictError(f"目标已存在：{new_path}")
        except OSError as e:
            raise FileOperationError(f"无法检查目标路径：{e}") from e

        # 跨盘检测（rename 不跨盘，Windows 下跨盘 rename 会退化为 copy+delete）
        # TD-M35：与 move 一致统一抛 CrossDriveError（FileOperationError 子类）
        try:
            old_dev = old_path.stat().st_dev
            parent_dev = old_path.parent.stat().st_dev
            if old_dev != parent_dev:
                raise CrossDriveError(
                    f"跨盘重命名不支持：{old_path}（dev={old_dev}）→ {new_path}（dev={parent_dev}）"
                )
        except OSError as e:
            raise FileOperationError(f"无法获取路径设备号：{e}") from e

        try:
            old_path.rename(new_path)
        except OSError as e:
            raise FileOperationError(f"无法重命名：{old_path} → {new_path}：{e}") from e

        # 同步 folder_cache + ContentUnit.path（复用 move 的同步逻辑）
        self._sync_on_rename(old_path, new_path)

        history = OperationHistory(
            id=self._new_uuid(),
            operation_type="rename",
            source_path=str(old_path),
            target_path=str(new_path),
            created_at=self._now(),
            can_undo=True,
        )
        if not record_history:
            # UndoService 撤销时调用：不写历史，避免产生新的可撤销记录（防止撤销循环）
            return history
        try:
            return self._create_history(history)
        except Exception as e:  # noqa: BLE001
            logger.exception("写入 operation_history 失败（rename：%s → %s）", old_path, new_path)
            raise FileOperationError(f"写入操作历史失败：{e}") from e

    def _sync_on_rename(self, src: Path, dst: Path) -> None:
        """重命名后同步 folder_cache + ContentUnit.path（复用 move 的同步逻辑）。

        - 目录重命名：on_folder_moved（删除旧 + 插入新 + 更新父 mtime）+ ContentUnit.path 前缀重写
        - 文件重命名：update_folder_mtime（父目录 mtime 更新，best-effort）

        与 _sync_on_move 的差异：父目录相同，无需更新源父目录 mtime。
        """
        if self._folder_cache_helper is None and self._content_unit_repo is None:
            return

        try:
            # rename 后 dst.exists() 为 True；dst.is_dir() 判断是否为目录
            is_dir = dst.is_dir()
        except OSError as e:
            logger.warning("无法判断重命名后目标类型 %s: %s", dst, e)
            return

        if is_dir:
            if self._folder_cache_helper is not None:
                # on_folder_moved 需要 target_dir 参数（new_path 的父目录）
                self._folder_cache_helper.on_folder_moved(src, dst, dst.parent)
            if self._content_unit_repo is not None:
                self._update_content_unit_paths_on_move(src, dst)
        else:
            # 文件重命名：仅更新父目录 mtime（folder_cache 只记录目录）
            if self._folder_cache_helper is not None:
                # rename 父目录相同，只更新一次
                self._folder_cache_helper.update_folder_mtime(dst.parent)

    def delete_to_recycle_bin(self, paths: list[Path]) -> tuple[list[OperationHistory], list[str]]:
        """将多个文件/目录移至 Windows 回收站。

        - 批量操作：循环内单条同步失败仅收集错误不中断，最终汇总返回。
        - 每个成功删除的路径写一条 operation_history（type='delete'，
          source_path=path，target_path=None，can_undo=False）。
        - Stage 4.5 H4：注入 helper/repo 后自动同步 folder_cache（删除目录及其子节点）
          + ContentUnit（删除关联记录）。
        - 同步失败不抛异常（文件已删除是既成事实，需保留 operation_history 与部分同步
          结果），而是通过返回值 sync_errors 上报，由调用方决定如何提示用户。

        设计决策（Q1=A）：返回 (histories, sync_errors) 元组而非在 sync 失败时抛异常。
        原因：调用方若在 except 中 rollback，会丢失已删除文件的 operation_history
        记录；返回元组让调用方先 commit（保留历史与已成功的同步）再展示错误。

        Args:
            paths: 待删除的路径列表。

        Returns:
            (histories, sync_errors) 二元组：
            - histories：成功删除并写入 operation_history 的记录列表（按删除顺序）。
            - sync_errors：同步过程中收集的错误消息列表（空列表表示无同步错误）。

        Raises:
            FileOperationError: SHFileOperation 失败（此时文件未删除，无历史写入）。
        """
        from infrastructure.windows_recycle_bin import (
            RecycleBinError,
            move_to_recycle_bin,
        )

        # 过滤不存在的路径（不报错，仅记日志）
        valid_paths: list[Path] = []
        for p in paths:
            try:
                if p.exists():
                    valid_paths.append(p)
                else:
                    logger.warning("删除跳过不存在的路径：%s", p)
            except OSError as e:
                logger.warning("删除跳过无法访问的路径 %s: %s", p, e)

        if not valid_paths:
            return [], []

        # 调用 SHFileOperation 批量移至回收站
        # 失败时抛 FileOperationError：文件未删除，调用方可 rollback（无副作用）
        try:
            move_to_recycle_bin(valid_paths)
        except RecycleBinError as e:
            raise FileOperationError(f"移至回收站失败：{e}") from e

        # 同步 folder_cache + ContentUnit（每个路径独立处理，单条失败不中断）
        histories: list[OperationHistory] = []
        sync_errors: list[str] = []
        for path in valid_paths:
            # 同步 folder_cache（删除该节点及子节点）
            if self._folder_cache_helper is not None:
                try:
                    self._sync_on_delete(path)
                except FileOperationError as e:
                    sync_errors.append(str(e))

            # 删除关联的 ContentUnit（路径已不存在，记录无意义）
            if self._content_unit_repo is not None:
                try:
                    self._delete_content_units_on_path(path)
                except (RepositoryError, sqlite3.Error, FileOperationError) as e:
                    sync_errors.append(str(e))

            # 写 operation_history（即使同步失败，文件已删除是事实）
            history = OperationHistory(
                id=self._new_uuid(),
                operation_type="delete",
                source_path=str(path),
                target_path=None,
                created_at=self._now(),
                can_undo=False,
            )
            try:
                histories.append(self._create_history(history))
            except Exception as e:  # noqa: BLE001
                logger.exception("写入 operation_history 失败（delete：%s）", path)
                sync_errors.append(f"写入历史失败：{e}")

        return histories, sync_errors

    def _sync_on_delete(self, path: Path) -> None:
        """删除后同步 folder_cache。

        - 目录：删除该节点及所有子节点（helper.delete_folder_subtree，先子后父）
        - 文件：无 folder_cache 记录 → 仅更新父目录 mtime
        - TD-L25：folder_cache 子树删除封装在 FolderCacheSyncHelper，
          不再直接访问 helper 私有 `_repo`

        Raises:
            FileOperationError: folder_cache 同步失败。
        """
        self._folder_cache_helper.delete_folder_subtree(path)
        # 更新父目录 mtime（best-effort，TD-L18 策略）
        self._folder_cache_helper.update_folder_mtime(path.parent)

    def _delete_content_units_on_path(self, path: Path) -> None:
        """删除关联的 ContentUnit 记录。

        包括：
        - ContentUnit.path == path → 直接删除
        - ContentUnit.path 以 path/ 开头 → 子节点，直接删除（路径已不存在）

        Raises:
            FileOperationError: ContentUnit 删除失败。
            RepositoryError: 仓储错误。
        """
        affected = self._content_unit_repo.list_by_path_prefix_normalized(str(path))
        for unit in affected:
            try:
                self._content_unit_repo.delete(unit.id)
            except (RepositoryError, sqlite3.Error) as e:
                raise FileOperationError(f"删除 ContentUnit 失败：unit_id={unit.id} err={e}") from e

    # === Stage 5 Task 3b：覆盖前删除目标 ===

    def _remove_target_for_overwrite(self, dst: Path) -> None:
        """覆盖前删除已存在的目标（用户已通过 ConflictResolutionDialog 确认覆盖）。

        直接删除（不进回收站，不写 delete 历史），同步 folder_cache + ContentUnit。
        同步失败记日志不中断（best-effort）：文件删除是用户明确授权的覆盖操作，
        DB 同步失败不应阻止覆盖执行；后续 copy/move 的 _sync_on_copy/move 会重建记录。

        Raises:
            FileOperationError: 文件删除失败（此时不执行后续 copy/move）。
        """
        # 先同步 folder_cache + ContentUnit（此时 DB 中还有旧记录，_sync_on_delete
        # 通过 folder_cache 判断是否为目录，不依赖文件系统）
        if self._folder_cache_helper is not None:
            try:
                self._sync_on_delete(dst)
            except FileOperationError:
                logger.warning(
                    "覆盖前同步 folder_cache 失败（best-effort）：%s",
                    dst,
                    exc_info=True,
                )

        if self._content_unit_repo is not None:
            try:
                self._delete_content_units_on_path(dst)
            except (RepositoryError, sqlite3.Error, FileOperationError):
                logger.warning(
                    "覆盖前删除 ContentUnit 失败（best-effort）：%s",
                    dst,
                    exc_info=True,
                )

        # 删除目标文件/目录
        try:
            if dst.is_dir():
                shutil.rmtree(str(dst))
            else:
                os.remove(str(dst))
        except OSError as e:
            raise FileOperationError(f"无法删除覆盖目标：{dst}：{e}") from e

    # === Stage 5 Task 3b：复制 ===

    def copy(
        self,
        src: Path,
        dst: Path,
        *,
        overwrite: bool = False,
    ) -> OperationHistory:
        """复制文件或目录到目标路径。

        - 源必须存在。
        - 目标不能已存在（不覆盖，AGENTS 规则 2；冲突处理在 UI 层由
          ConflictResolutionDialog 提前解决，调用方传入最终无冲突的 dst）。
        - overwrite=True 时：目标已存在则先删除目标（用户已确认覆盖），
          同步 folder_cache + ContentUnit 后直接删除（不进回收站，不写 delete 历史）。
        - 跨盘复制允许（copy 不退化，与 move 不同）。
        - 自目录检测：dst 在 src 子树内抛 SelfSubdirectoryError（避免无限递归复制）。
        - 文件用 shutil.copy2（保留元数据）；文件夹用 shutil.copytree。
        - Stage 4.5 H4：注入 helper/repo 后自动同步 folder_cache + ContentUnit：
          * 目录复制：on_folder_created（插入新顶层节点）+ 复制 ContentUnit（新 id + 新 path）
          * 文件复制：update_folder_mtime（父目录 mtime 更新）+ 复制 ContentUnit（如有）
          同步失败抛 FileOperationError，由上层 UoW 回滚 DB 写操作。
          文件已复制无法回滚，由调用方处理。
        - 成功后写 operation_history（operation_type='copy'，
          source_path=src，target_path=dst，can_undo=False，Q4=A）。

        Args:
            src: 源文件/目录路径。
            dst: 目标完整路径（含文件名）。
            overwrite: 是否覆盖已存在的目标（默认 False）。

        Returns:
            OperationHistory 记录。

        Raises:
            SourceNotFoundError: 源不存在。
            ConflictError: 目标已存在且 overwrite=False。
            SelfSubdirectoryError: 复制到自身子目录。
            FileOperationError: 其他文件系统错误或同步失败。
        """
        try:
            if not src.exists():
                raise SourceNotFoundError(f"源不存在：{src}")
        except OSError as e:
            raise FileOperationError(f"无法访问源路径：{e}") from e

        try:
            if dst.exists():
                if not overwrite:
                    raise ConflictError(f"目标已存在：{dst}")
                # 覆盖模式：先删除目标 + 同步元数据
                self._remove_target_for_overwrite(dst)
        except OSError as e:
            raise FileOperationError(f"无法检查目标路径：{e}") from e

        try:
            dst_parent = dst.parent
            if not dst_parent.exists():
                raise SourceNotFoundError(f"目标父目录不存在：{dst_parent}")
        except OSError as e:
            raise FileOperationError(f"无法访问目标父目录：{e}") from e

        # 自目录检测：dst 在 src 子树内（仅目录复制时有风险）
        sep = os.sep
        src_str = str(src).rstrip(sep) + sep
        dst_str = str(dst)
        if dst_str.startswith(src_str):
            raise SelfSubdirectoryError(f"不能复制到自身子目录：{src} → {dst}")

        # 执行复制
        try:
            if src.is_dir():
                shutil.copytree(str(src), str(dst))
            else:
                shutil.copy2(str(src), str(dst))
        except OSError as e:
            raise FileOperationError(f"无法复制：{src} → {dst}：{e}") from e

        # 同步 folder_cache + ContentUnit
        self._sync_on_copy(src, dst)

        history = OperationHistory(
            id=self._new_uuid(),
            operation_type="copy",
            source_path=str(src),
            target_path=str(dst),
            created_at=self._now(),
            can_undo=False,
        )
        try:
            return self._create_history(history)
        except Exception as e:  # noqa: BLE001
            logger.exception("写入 operation_history 失败（copy：%s → %s）", src, dst)
            raise FileOperationError(f"写入操作历史失败：{e}") from e

    def _sync_on_copy(self, src: Path, dst: Path) -> None:
        """复制后同步 folder_cache + ContentUnit（Q10=A 复制 ContentUnit）。

        - 目录复制：on_folder_created（插入新顶层 folder_cache 节点）
          + 复制所有路径前缀匹配的 ContentUnit（新 id + 新 path + 元数据保留）
        - 文件复制：update_folder_mtime（父目录 mtime 更新）
          + 复制 ContentUnit.path == src 的单个记录（如有）

        与 _sync_on_move 的差异：
        - 不删除旧 folder_cache（复制保留原文件）
        - 不更新 ContentUnit.path（复制创建新记录，原记录保留）
        - 子目录 folder_cache 节点不自动插入（由下次扫描补全，与 move 行为一致）

        同步失败抛 FileOperationError，由上层 UoW 回滚 DB 写操作。
        文件已复制无法回滚，由调用方处理。

        未注入 helper/repo 时为空操作（向后兼容）。
        """
        if self._folder_cache_helper is None and self._content_unit_repo is None:
            return

        try:
            is_dir = dst.is_dir()
        except OSError as e:
            logger.warning("无法判断复制后目标类型 %s: %s", dst, e)
            return

        if is_dir:
            # 目录复制：插入新 folder_cache 顶层节点
            if self._folder_cache_helper is not None:
                self._folder_cache_helper.on_folder_created(dst, dst.parent)
            # 复制 ContentUnit（新 id + 新 path + 元数据保留，Q10=A）
            if self._content_unit_repo is not None:
                self._duplicate_content_units_on_copy(src, dst)
        else:
            # 文件复制：仅更新父目录 mtime
            if self._folder_cache_helper is not None:
                self._folder_cache_helper.update_folder_mtime(dst.parent)
            # 复制单个 ContentUnit（如 src 对应一个内容单元）
            if self._content_unit_repo is not None:
                self._duplicate_content_units_on_copy(src, dst)

    def _duplicate_content_units_on_copy(self, src: Path, dst: Path) -> None:
        """复制目录/文件后，复制所有路径前缀匹配的 ContentUnit 记录。

        包括：
        - ContentUnit.path == src → 创建新记录（新 id，path=dst，元数据保留）
        - ContentUnit.path 以 src/ 开头 → 创建新记录（新 id，path=dst + 相对后缀）

        新记录的 id 重新生成，created_at/updated_at 重置为当前时间，
        原记录保留不变（复制不修改源）。

        Raises:
            FileOperationError: ContentUnit 复制失败。
        """
        affected = self._content_unit_repo.list_by_path_prefix_normalized(str(src))
        if not affected:
            return

        src_key = make_path_key(src)
        dst_str = str(dst)
        sep = os.sep
        src_prefix = src_key.rstrip(sep) + sep
        now = self._now()

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
                    suffix = unit_key[len(src_key) :]
                    new_path = dst_str + suffix
            else:
                continue

            new_unit = ContentUnit(
                id=self._new_uuid(),
                path=new_path,
                title=unit.title,
                content_type=unit.content_type,
                source_url=unit.source_url,
                cover_path=unit.cover_path,
                notes=unit.notes,
                created_at=now,
                updated_at=now,
            )
            try:
                self._content_unit_repo.create(new_unit)
            except (RepositoryError, sqlite3.Error) as e:
                raise FileOperationError(f"复制 ContentUnit 失败：src_id={unit.id} err={e}") from e
