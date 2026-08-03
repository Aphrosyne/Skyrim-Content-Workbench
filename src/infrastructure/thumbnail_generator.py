"""缩略图生成器。spec §9。

使用 Pillow 只读加载源图，方形居中裁剪并写入应用缓存目录。
不修改、不压缩、不覆盖原始图片。

输出格式：WebP（Task 1a：相比 PNG 节省约 65% 磁盘占用，Qt6/Pillow 均原生支持）。
输出尺寸：调用方指定（默认 256x256，Task 1a 卡片视图基础档位）。
方形居中放大裁剪填满 size×size（UI合理性16 起卡片视图唯一渲染模式；
contain 圆角/透明填充模式已删除，见 CHANGELOG v0.50.7）。

异常分类（供 ThumbnailService 转换为 status）：
- FileNotFoundError → status='missing'
- UnidentifiedImageError / 解码错误 → status='corrupt'
- 其他异常 → status='error'

支持的图片格式（spec §9）：
JPG / JPEG / PNG / WEBP / GIF / BMP / TIF / TIFF / ICO

约束：
- 仅使用 PIL.Image 打开源图（只读）。
- 不读取压缩包内部内容。
- 输出文件命名：{content_unit_id}_{size}.webp（Task 1a：多档缓存）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

# 支持的源图扩展名（spec §9，与 ContentService._COVER_IMAGE_EXTENSIONS 一致）
SUPPORTED_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".ico"}
)

# WebP 编码质量（Task 1a：质量=90，体积/质量平衡）
_WEBP_QUALITY = 90


class ThumbnailSourceNotFoundError(FileNotFoundError):
    """源图文件不存在。"""


class ThumbnailSourceCorruptError(UnidentifiedImageError):
    """源图损坏或无法解码。"""


class ThumbnailSourceUnsupportedError(ValueError):
    """不支持的图片格式。"""


def _is_supported(source_path: Path) -> bool:
    """返回扩展名是否在支持列表内。"""
    return source_path.suffix.lower() in SUPPORTED_EXTENSIONS


def generate_thumbnail(
    source_path: Path,
    cache_path: Path,
    size: int = 256,
) -> None:
    """从源图生成缩略图并写入 cache_path。

    - 源图不存在 → 抛 ThumbnailSourceNotFoundError
    - 扩展名不支持 → 抛 ThumbnailSourceUnsupportedError
    - Pillow 无法解码 → 抛 ThumbnailSourceCorruptError
    - 其他异常向上传播

    输出 WebP 格式（quality=90），不修改源图（仅只读打开 + stat）。
    方形居中放大裁剪填满 size×size（无透明条、无圆角，
    UI合理性16：卡片视图 256 档缓存，与卡片方形居中裁剪视觉一致）。

    若 cache_path 已存在则覆盖。
    """
    if not source_path.exists():
        raise ThumbnailSourceNotFoundError(f"源图不存在：{source_path}")
    if not _is_supported(source_path):
        raise ThumbnailSourceUnsupportedError(f"不支持的图片格式：{source_path.suffix}")

    # 显式 convert("RGBA") 保证统一处理
    try:
        with Image.open(source_path) as img:
            img.load()  # 完整解码（避免懒加载在 with 块外失效）
            original = img.convert("RGBA")
    except UnidentifiedImageError as e:
        raise ThumbnailSourceCorruptError(f"无法识别图片：{source_path}") from e
    except OSError as e:
        # 损坏的图片文件
        raise ThumbnailSourceCorruptError(f"图片损坏或无法解码：{source_path}") from e

    # 居中放大裁剪填满方形（与卡片视图 _crop_to_square 一致的视觉）
    thumb = ImageOps.fit(
        original,
        (size, size),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )

    # 确保输出目录存在
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    # 保存为 WebP（保留透明通道，quality=90）
    thumb.save(cache_path, format="WEBP", quality=_WEBP_QUALITY)


def get_source_signature(source_path: Path) -> tuple[int, float]:
    """返回源图的 (size_bytes, mtime_seconds)。

    用于缓存有效性判断（spec §9）。失败抛 OSError（调用方决定如何处理）。
    """
    stat = source_path.stat()
    return (stat.st_size, stat.st_mtime)
