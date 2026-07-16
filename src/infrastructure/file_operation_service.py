"""文件操作服务（简化版）。

阶段 3 Task 3：实现 new_folder + move 两个最小方法，每次操作写 operation_history 表。
rename / delete / undo 完整版留待阶段 5。

约束（AGENTS 规则 2/3）：
- 不覆盖已有文件/目录：目标存在抛 ConflictError。
- 跨盘移动检测：抛 CrossDriveError（Task 3 范围内 move 仅用于"创建 Mod 组"同盘移动，
  跨盘检测留作通用 move 的安全护栏）。
- 自目录移动检测：抛 SelfSubdirectoryError。
- 写 operation_history 在文件操作成功后；失败不写历史。
- 不自提交，由调用方控制事务边界。
"""

from __future__ import annotations

import logging
import shutil
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
from domain.models import OperationHistory
from infrastructure.repositories.operation_history import OperationHistoryRepository

logger = logging.getLogger(__name__)


def _default_now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_uuid_provider() -> str:
    return str(uuid.uuid4())


class FileOperationService:
    """文件操作服务（简化版）：new_folder + move。

    使用方式：
        service = FileOperationService(OperationHistoryRepository(conn))
        history = service.new_folder(Path("D:/Mods/Stash/NewMod"))
        history = service.move(Path("D:/Mods/Stash/file.7z"), Path("D:/Mods/Stash/NewMod/file.7z"))
    """

    def __init__(
        self,
        history_repo: OperationHistoryRepository,
        now_provider: Callable[[], str] | None = None,
        uuid_provider: Callable[[], str] | None = None,
    ) -> None:
        self._repo = history_repo
        self._now = now_provider or _default_now_utc
        self._new_uuid = uuid_provider or _default_uuid_provider

    def new_folder(self, folder_path: Path) -> OperationHistory:
        """创建新文件夹。

        - 父目录必须存在（只读检查）。
        - 目标不能已存在（不覆盖，AGENTS 规则 2）。
        - 成功后写 operation_history（operation_type='new_folder'，
          source_path=父目录路径，target_path=新文件夹路径）。

        Args:
            folder_path: 新文件夹的完整路径。

        Returns:
            OperationHistory 记录。

        Raises:
            SourceNotFoundError: 父目录不存在。
            ConflictError: 目标已存在。
            FileOperationError: 其他文件系统错误。
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
            FileOperationError: 其他文件系统错误。
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
        import os

        sep = os.sep
        src_str = str(src).rstrip(sep) + sep
        dst_str = str(dst)
        if dst_str.startswith(src_str):
            raise SelfSubdirectoryError(f"不能移动到自身子目录：{src} → {dst}")

        try:
            shutil.move(str(src), str(dst))
        except OSError as e:
            raise FileOperationError(f"无法移动：{src} → {dst}：{e}") from e

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
