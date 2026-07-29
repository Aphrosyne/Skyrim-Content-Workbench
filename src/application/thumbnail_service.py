"""缩略图服务。spec §9。

封装 ThumbnailCacheRepository + ThumbnailGenerator：
- 同步路径：缓存命中 → 直接返回缓存文件路径
- 异步路径：缓存未命中 → 由 UI 层 ThumbnailWorker 调用 generate()
- 有效性判断：source_size + source_modified_at + 缓存文件存在性
- GC：启动时清理无对应 content_unit 的缓存（Q8: B）

Task 1a：支持多档缓存（256/512）。get_cache / generate 接收 size 参数，
invalidate 清理指定 unit 的所有档位文件与记录。

不访问文件系统的写操作（仅读源图 + 写应用数据目录的缓存 WebP）。
不修改用户原图。

约束：
- 写数据库操作不自提交，由 application 层调用方控制事务边界。
- 缓存文件目录由调用方注入（通常为 app_paths.get_thumbnails_dir()）。
- 缓存文件命名：{content_unit_id}_{size}.webp（Task 1a：多档缓存）。
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from domain.models import ThumbnailCache
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.errors import RepositoryError
from infrastructure.repositories.thumbnail_cache import ThumbnailCacheRepository
from infrastructure.thumbnail_generator import (
    ThumbnailSourceCorruptError,
    ThumbnailSourceNotFoundError,
    ThumbnailSourceUnsupportedError,
    generate_thumbnail,
    get_source_signature,
)

logger = logging.getLogger(__name__)


def _default_now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mtime_to_iso(mtime: float) -> str:
    """将 mtime（秒，浮点）转为 ISO 8601 UTC 字符串。

    用于 source_modified_at 字段。精度为秒（与 stat.st_mtime 一致）。
    """
    return datetime.fromtimestamp(mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class ThumbnailService:
    """缩略图缓存查询与生成调度。"""

    def __init__(
        self,
        cache_repo: ThumbnailCacheRepository,
        content_unit_repo: ContentUnitRepository,
        thumbnails_dir: Path,
        size: int = 256,
        now_provider: Callable[[], str] | None = None,
    ) -> None:
        self._cache_repo = cache_repo
        self._unit_repo = content_unit_repo
        self._thumbnails_dir = thumbnails_dir
        self._size = size  # 默认档位（256，Task 1a）
        self._now = now_provider or _default_now_utc

    # --- 同步路径：缓存查询 ---

    def get_cache(
        self,
        content_unit_id: str,
        source_path: Path,
        size: int = 256,
    ) -> Path | None:
        """查询缓存：若命中且有效，返回缓存 WebP 文件路径；否则返回 None。

        有效性判断（spec §9）：
        - cache.status == 'ok'
        - cache.source_size_bytes == 当前源图 size
        - cache.source_modified_at == 当前源图 mtime（ISO 字符串比较）
        - cache_filename 对应文件存在

        若源图被删除（无法 stat），视为缓存失效（返回 None），
        让调用方决定是否重新生成（重新生成时会写入 'missing' 状态）。

        不抛错；查询失败记日志返回 None。
        """
        try:
            cache = self._cache_repo.get_by_id_and_size(content_unit_id, size)
        except RepositoryError:
            logger.exception("查询缩略图缓存失败：unit_id=%s size=%d", content_unit_id, size)
            return None
        if cache is None:
            return None
        if not cache.is_ok():
            return None

        # 校验源图当前签名
        try:
            current_size, current_mtime = get_source_signature(source_path)
        except OSError:
            # 源图不可访问（可能被删除）→ 缓存失效
            return None
        if cache.source_size_bytes != current_size:
            return None
        if cache.source_modified_at != _mtime_to_iso(current_mtime):
            return None

        # 校验缓存文件存在
        cache_path = self._thumbnails_dir / cache.cache_filename
        if not cache_path.exists():
            return None
        return cache_path

    # --- 异步路径：生成 ---

    def generate(
        self,
        content_unit_id: str,
        source_path: Path,
        size: int = 256,
    ) -> str:
        """生成缩略图并写入缓存目录 + 更新数据库记录。

        - 成功：写入 WebP + upsert status='ok' 记录
        - 源图不存在：upsert status='missing'
        - 源图损坏：upsert status='corrupt'
        - 不支持格式：upsert status='unsupported'
        - 其他异常：upsert status='error' + error_message

        Returns:
            缓存状态：'ok' / 'missing' / 'corrupt' / 'unsupported' / 'error'

        Raises:
            RepositoryError: 数据库写入失败（文件已生成但记录未写入）。
        """
        # 先尝试获取源图签名（可能抛 OSError）
        try:
            source_size, source_mtime = get_source_signature(source_path)
        except OSError:
            # 源图不存在或不可访问
            self._record_failure(
                content_unit_id,
                size=size,
                source_size=0,
                source_modified_at=_default_now_utc(),
                status="missing",
                error_message=f"源图不可访问：{source_path}",
            )
            return "missing"

        cache_filename = f"{content_unit_id}_{size}.webp"
        cache_path = self._thumbnails_dir / cache_filename
        source_modified_at = _mtime_to_iso(source_mtime)

        try:
            generate_thumbnail(source_path, cache_path, size)
        except ThumbnailSourceNotFoundError:
            self._record_failure(
                content_unit_id,
                size=size,
                source_size=source_size,
                source_modified_at=source_modified_at,
                status="missing",
                error_message="源图不存在",
            )
            return "missing"
        except ThumbnailSourceUnsupportedError as e:
            self._record_failure(
                content_unit_id,
                size=size,
                source_size=source_size,
                source_modified_at=source_modified_at,
                status="unsupported",
                error_message=str(e),
            )
            return "unsupported"
        except ThumbnailSourceCorruptError as e:
            self._record_failure(
                content_unit_id,
                size=size,
                source_size=source_size,
                source_modified_at=source_modified_at,
                status="corrupt",
                error_message=str(e),
            )
            return "corrupt"
        except Exception as e:  # noqa: BLE001
            logger.exception("生成缩略图失败：unit_id=%s size=%d", content_unit_id, size)
            self._record_failure(
                content_unit_id,
                size=size,
                source_size=source_size,
                source_modified_at=source_modified_at,
                status="error",
                error_message=str(e),
            )
            return "error"

        # 成功
        self._record_success(
            content_unit_id=content_unit_id,
            size=size,
            source_size=source_size,
            source_modified_at=source_modified_at,
            cache_filename=cache_filename,
        )
        return "ok"

    # --- 失效与删除 ---

    def invalidate(self, content_unit_id: str) -> None:
        """删除指定内容单元的所有档位缓存记录与文件。

        用于封面清除 / 封面更换场景。文件不存在不报错。
        Task 1a：遍历该 unit 的所有档位（64/256/512），逐个删除缓存文件，
        然后删除数据库记录。
        """
        # 查询该 unit 的所有档位缓存记录
        try:
            caches = self._cache_repo.list_by_unit(content_unit_id)
        except RepositoryError:
            caches = []

        # 先删文件
        for cache in caches:
            cache_path = self._thumbnails_dir / cache.cache_filename
            try:
                if cache_path.exists():
                    cache_path.unlink()
            except OSError:
                logger.warning("删除缩略图文件失败：%s", cache_path, exc_info=True)

        # 兼容旧 v6 命名 {unit_id}.png（无 size 后缀）
        legacy_path = self._thumbnails_dir / f"{content_unit_id}.png"
        try:
            if legacy_path.exists():
                legacy_path.unlink()
        except OSError:
            logger.warning("删除旧缩略图文件失败：%s", legacy_path, exc_info=True)

        # 再删记录
        try:
            self._cache_repo.delete(content_unit_id)
        except RepositoryError:
            logger.exception("删除缩略图缓存记录失败：unit_id=%s", content_unit_id)

    # --- GC（Q8: B 启动时清理无对应 content_unit 的缓存） ---

    def cleanup_orphans(self) -> int:
        """清理无对应 content_unit 记录的缓存。

        用于启动时执行（Q8: B）。返回清理的条数。

        同时清理：
        - thumbnail_cache 表中无对应 content_unit 的记录
        - thumbnails 目录中无对应记录的 PNG / WebP 文件
        """
        cleaned = 0

        # 1. 清理 DB 中孤立的缓存记录
        try:
            all_caches = self._cache_repo.list_all()
        except RepositoryError:
            logger.exception("列出缩略图缓存失败，跳过 GC")
            return 0

        for cache in all_caches:
            unit = self._unit_repo.get_by_id(cache.content_unit_id)
            if unit is None:
                # 孤立记录 → 删除
                self.invalidate(cache.content_unit_id)
                cleaned += 1

        # 2. 清理目录中孤立的缓存文件
        if self._thumbnails_dir.exists():
            for entry in self._thumbnails_dir.iterdir():
                if not entry.is_file():
                    continue
                suffix = entry.suffix.lower()
                if suffix not in (".png", ".webp"):
                    continue

                # 文件名格式：{unit_id}_{size}.webp 或旧 {unit_id}.png
                stem = entry.stem
                # 新命名含 "_"，旧命名不含
                unit_id = stem.rsplit("_", 1)[0] if "_" in stem else stem

                # 检查是否有对应的 DB 记录
                with contextlib.suppress(RepositoryError):
                    caches = self._cache_repo.list_by_unit(unit_id)
                    if not caches:
                        try:
                            entry.unlink()
                            cleaned += 1
                        except OSError:
                            logger.warning("删除孤立缓存文件失败：%s", entry, exc_info=True)

        logger.info("缩略图 GC 完成：清理 %d 条", cleaned)
        return cleaned

    # --- 内部 ---

    def _record_success(
        self,
        content_unit_id: str,
        size: int,
        source_size: int,
        source_modified_at: str,
        cache_filename: str,
    ) -> None:
        cache = ThumbnailCache(
            content_unit_id=content_unit_id,
            size=size,
            source_size_bytes=source_size,
            source_modified_at=source_modified_at,
            cache_filename=cache_filename,
            status="ok",
            error_message=None,
            generated_at=self._now(),
        )
        try:
            self._cache_repo.upsert(cache)
        except RepositoryError:
            logger.exception("写入缩略图缓存记录失败：unit_id=%s size=%d", content_unit_id, size)

    def _record_failure(
        self,
        content_unit_id: str,
        size: int,
        source_size: int,
        source_modified_at: str,
        status: str,
        error_message: str,
    ) -> None:
        cache = ThumbnailCache(
            content_unit_id=content_unit_id,
            size=size,
            source_size_bytes=source_size,
            source_modified_at=source_modified_at,
            cache_filename=f"{content_unit_id}_{size}.webp",
            status=status,
            error_message=error_message,
            generated_at=self._now(),
        )
        try:
            self._cache_repo.upsert(cache)
        except (RepositoryError, sqlite3.Error):
            logger.exception("写入缩略图失败记录失败：unit_id=%s size=%d", content_unit_id, size)

    def get_size(self) -> int:
        """返回默认档位尺寸（供测试）。"""
        return self._size

    def get_thumbnails_dir(self) -> Path:
        """返回缓存目录路径（供测试）。"""
        return self._thumbnails_dir
