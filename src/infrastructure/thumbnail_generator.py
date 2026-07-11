"""缩略图生成器（infrastructure 层）。

负责只读加载源图、生成缩略图并写入应用缓存目录。
不访问数据库；不修改用户原图；不联网。

依据 docs/spec.md §10、docs/architecture.md §8。
依据 Q5（已关闭）：缓存有效性基于 asset_id + source_size + source_modified_at。
依据 Q13（已关闭）：缓存文件名格式 {asset_id}.png。

线程边界：本模块为纯同步 IO，可由后台 worker 线程调用。
不在 Qt 主线程批量调用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)

# 缩略图最大边长（像素）。按比例缩放，保持宽高比。
THUMBNAIL_MAX_SIZE = 128

# Pillow 支持的图片格式扩展名（小写，含点）。
# 覆盖 scanner IMAGE_EXTENSIONS 中的常见可解码子集。
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
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


class ThumbnailStatus(StrEnum):
    """缩略图生成状态。"""

    OK = "ok"
    MISSING = "missing"
    CORRUPT = "corrupt"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


@dataclass(frozen=True)
class ThumbnailResult:
    """缩略图生成结果。

    - status=OK 时 cache_path 指向生成的缓存文件。
    - 其他状态时 cache_path 为 None，error_message 描述原因。
    """

    asset_id: str
    status: ThumbnailStatus
    cache_path: Path | None
    error_message: str | None


class ThumbnailGenerator:
    """缩略图生成器。

    使用 Pillow 只读加载源图，生成缩略图写入 cache_dir。
    不修改、不删除、不覆盖用户原图。
    """

    def __init__(self, cache_dir: Path, max_size: int = THUMBNAIL_MAX_SIZE) -> None:
        self._cache_dir = cache_dir
        self._max_size = max_size

    @property
    def cache_dir(self) -> Path:
        """返回缓存目录路径。"""
        return self._cache_dir

    def generate(self, asset_id: str, source_path: Path) -> ThumbnailResult:
        """为指定源图生成缩略图。

        返回 ThumbnailResult。不抛异常；所有错误转为错误状态返回。
        """
        # 检查扩展名是否支持
        ext = source_path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return ThumbnailResult(
                asset_id=asset_id,
                status=ThumbnailStatus.UNSUPPORTED,
                cache_path=None,
                error_message=f"不支持的图片格式：{ext}",
            )

        # 检查源文件是否存在
        if not source_path.exists():
            return ThumbnailResult(
                asset_id=asset_id,
                status=ThumbnailStatus.MISSING,
                cache_path=None,
                error_message=f"源文件不存在：{source_path}",
            )

        # 尝试用 Pillow 加载
        try:
            from PIL import Image  # 延迟导入，避免未安装时模块加载失败
        except ImportError as e:
            logger.error("Pillow 未安装：%s", e)
            return ThumbnailResult(
                asset_id=asset_id,
                status=ThumbnailStatus.ERROR,
                cache_path=None,
                error_message="Pillow 未安装，无法生成缩略图",
            )

        try:
            with Image.open(source_path) as img:
                # 验证图片可解码（load 触发实际解码）
                img.load()
                # 转换为 RGB 以统一输出格式（RGBA/CMYK/P 等需转换）
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                img.thumbnail((self._max_size, self._max_size))
                # 确保缓存目录存在
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                cache_filename = f"{asset_id}.png"
                cache_path = self._cache_dir / cache_filename
                img.save(cache_path, format="PNG")
        except FileNotFoundError:
            return ThumbnailResult(
                asset_id=asset_id,
                status=ThumbnailStatus.MISSING,
                cache_path=None,
                error_message=f"源文件不存在：{source_path}",
            )
        except OSError as e:
            # Pillow 对损坏图片抛 OSError 或其子类（UnidentifiedImageError）
            return ThumbnailResult(
                asset_id=asset_id,
                status=ThumbnailStatus.CORRUPT,
                cache_path=None,
                error_message=f"图片解码失败：{e}",
            )
        except Exception as e:  # noqa: BLE001 - 生成器边界不抛异常
            logger.exception("缩略图生成失败：asset_id=%s", asset_id)
            return ThumbnailResult(
                asset_id=asset_id,
                status=ThumbnailStatus.ERROR,
                cache_path=None,
                error_message=f"缩略图生成失败：{e}",
            )

        return ThumbnailResult(
            asset_id=asset_id,
            status=ThumbnailStatus.OK,
            cache_path=cache_path,
            error_message=None,
        )

    def cache_path_for(self, asset_id: str) -> Path:
        """返回指定 asset_id 的缓存文件路径（无论是否已生成）。"""
        return self._cache_dir / f"{asset_id}.png"
