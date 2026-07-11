"""缩略图协调服务（application 层）。

协调 FileAsset、ThumbnailGenerator、ThumbnailCacheRepository，提供 UI 层
查询与生成缩略图的统一入口。不访问 Qt；不直接操作用户原图。

依据 docs/spec.md §10、docs/architecture.md §8。
依据 Q5（已关闭）：缓存有效性基于 source_size + source_modified_at。
依据 Q13（已关闭）：缓存文件名 {asset_id}.png。

线程边界：本服务为纯同步，可由后台 worker 线程调用。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from domain.models import FileAsset
from infrastructure.repositories.file_asset import FileAssetRepository
from infrastructure.repositories.thumbnail_cache import (
    ThumbnailCacheRecord,
    ThumbnailCacheRepository,
)
from infrastructure.thumbnail_generator import (
    ThumbnailGenerator,
    ThumbnailResult,
    ThumbnailStatus,
)

logger = logging.getLogger(__name__)


def _default_now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class ThumbnailInfo:
    """UI 层消费的缩略图信息 DTO。

    - status=OK 且 valid=True 时，cache_path 指向可用缓存文件。
    - status=OK 但 valid=False 时，缓存已过期，需要重新生成。
    - 其他状态时 cache_path 为 None。
    """

    asset_id: str
    status: ThumbnailStatus
    cache_path: Path | None
    valid: bool
    error_message: str | None


class ThumbnailCoordinator:
    """缩略图协调服务。

    使用方式：
        coord = ThumbnailCoordinator(file_repo, cache_repo, generator)
        info = coord.get_thumbnail_info(asset_id)
        if not info.valid:
            result = coord.generate_thumbnail(asset_id)
    """

    def __init__(
        self,
        file_repo: FileAssetRepository,
        cache_repo: ThumbnailCacheRepository,
        generator: ThumbnailGenerator,
        now_provider: Callable[[], str] | None = None,
    ) -> None:
        self._file_repo = file_repo
        self._cache_repo = cache_repo
        self._generator = generator
        self._now = now_provider or _default_now_utc

    @property
    def cache_dir(self) -> Path:
        """返回缩略图缓存目录路径（供 ThumbnailWorker 创建独立连接时使用）。"""
        return self._generator.cache_dir

    def get_thumbnail_info(self, asset_id: str) -> ThumbnailInfo:
        """查询缩略图缓存状态。

        不生成缩略图；仅检查缓存是否存在且有效。
        - asset_id 不存在于 file_asset 表 → 返回 MISSING。
        - 缓存记录不存在 → status=OK, valid=False（需要生成）。
        - 缓存记录存在但 source_size/mtime 不匹配 → valid=False。
        - 缓存记录存在且匹配 → valid=True。
        - 缓存记录状态非 ok（missing/corrupt/unsupported/error）→ valid=False。
        """
        asset = self._file_repo.get_by_id(asset_id)
        if asset is None:
            return ThumbnailInfo(
                asset_id=asset_id,
                status=ThumbnailStatus.MISSING,
                cache_path=None,
                valid=False,
                error_message=f"FileAsset 不存在：{asset_id}",
            )

        record = self._cache_repo.get_by_asset_id(asset_id)
        if record is None:
            # 无缓存记录，需要生成
            return ThumbnailInfo(
                asset_id=asset_id,
                status=ThumbnailStatus.OK,
                cache_path=None,
                valid=False,
                error_message=None,
            )

        # 缓存记录存在，检查有效性
        if record.status != "ok":
            return ThumbnailInfo(
                asset_id=asset_id,
                status=ThumbnailStatus(record.status),
                cache_path=None,
                valid=False,
                error_message=record.error_message,
            )

        # 检查 source_size 和 source_modified_at 是否匹配
        size_match = record.source_size_bytes == asset.size_bytes
        mtime_match = record.source_modified_at == asset.modified_at
        if not size_match or not mtime_match:
            return ThumbnailInfo(
                asset_id=asset_id,
                status=ThumbnailStatus.OK,
                cache_path=None,
                valid=False,
                error_message=None,
            )

        # 缓存有效
        cache_path = self._generator.cache_path_for(asset_id)
        # 检查缓存文件是否实际存在（可能被用户手动删除）
        if not cache_path.exists():
            return ThumbnailInfo(
                asset_id=asset_id,
                status=ThumbnailStatus.OK,
                cache_path=None,
                valid=False,
                error_message=None,
            )

        return ThumbnailInfo(
            asset_id=asset_id,
            status=ThumbnailStatus.OK,
            cache_path=cache_path,
            valid=True,
            error_message=None,
        )

    def generate_thumbnail(self, asset_id: str) -> ThumbnailResult:
        """生成（或重新生成）缩略图。

        同步执行：读取源文件 → 生成缩略图 → 写入缓存目录 → 更新 thumbnail_cache 表。
        不修改用户原图。所有错误转为 ThumbnailResult 返回，不抛异常。

        若 FileAsset 不存在，返回 MISSING 结果（不写缓存记录）。
        """
        asset = self._file_repo.get_by_id(asset_id)
        if asset is None:
            return ThumbnailResult(
                asset_id=asset_id,
                status=ThumbnailStatus.MISSING,
                cache_path=None,
                error_message=f"FileAsset 不存在：{asset_id}",
            )

        source_path = Path(asset.real_path)
        result = self._generator.generate(asset_id, source_path)

        # 无论成功或失败，都写入缓存记录
        cache_filename = f"{asset_id}.png"
        record = ThumbnailCacheRecord(
            asset_id=asset_id,
            source_size_bytes=asset.size_bytes,
            source_modified_at=asset.modified_at,
            cache_filename=cache_filename,
            status=result.status.value,
            error_message=result.error_message,
            generated_at=self._now(),
        )
        try:
            self._cache_repo.upsert(record)
        except Exception:  # noqa: BLE001
            logger.exception("写入 thumbnail_cache 失败：asset_id=%s", asset_id)
            # 缓存记录写入失败不影响已生成的缩略图文件

        return result

    def get_cover_thumbnail_info(self, asset: FileAsset) -> ThumbnailInfo:
        """直接根据 FileAsset 对象查询缩略图信息（避免重复查询 file_repo）。

        供 UI 在已知 FileAsset 的情况下使用。
        """
        record = self._cache_repo.get_by_asset_id(asset.id)
        if record is None:
            return ThumbnailInfo(
                asset_id=asset.id,
                status=ThumbnailStatus.OK,
                cache_path=None,
                valid=False,
                error_message=None,
            )

        if record.status != "ok":
            return ThumbnailInfo(
                asset_id=asset.id,
                status=ThumbnailStatus(record.status),
                cache_path=None,
                valid=False,
                error_message=record.error_message,
            )

        size_match = record.source_size_bytes == asset.size_bytes
        mtime_match = record.source_modified_at == asset.modified_at
        if not size_match or not mtime_match:
            return ThumbnailInfo(
                asset_id=asset.id,
                status=ThumbnailStatus.OK,
                cache_path=None,
                valid=False,
                error_message=None,
            )

        cache_path = self._generator.cache_path_for(asset.id)
        if not cache_path.exists():
            return ThumbnailInfo(
                asset_id=asset.id,
                status=ThumbnailStatus.OK,
                cache_path=None,
                valid=False,
                error_message=None,
            )

        return ThumbnailInfo(
            asset_id=asset.id,
            status=ThumbnailStatus.OK,
            cache_path=cache_path,
            valid=True,
            error_message=None,
        )
