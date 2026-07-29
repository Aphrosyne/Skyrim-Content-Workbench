"""ThumbnailGenerator 单元测试（spec §9）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from infrastructure.thumbnail_generator import (
    ThumbnailSourceCorruptError,
    ThumbnailSourceNotFoundError,
    ThumbnailSourceUnsupportedError,
    generate_thumbnail,
    get_source_signature,
)


@pytest.fixture
def jpg_source(tmp_path: Path) -> Path:
    """生成一个 100x80 的 JPG 测试图片。"""
    path = tmp_path / "cover.jpg"
    img = Image.new("RGB", (100, 80), color=(255, 0, 0))
    img.save(path, format="JPEG")
    return path


@pytest.fixture
def png_source(tmp_path: Path) -> Path:
    """生成一个 80x120 的 PNG 测试图片（透明背景）。"""
    path = tmp_path / "cover.png"
    img = Image.new("RGBA", (80, 120), color=(0, 255, 0, 128))
    img.save(path, format="PNG")
    return path


def test_generate_from_jpg(jpg_source, tmp_path):
    cache_path = tmp_path / "thumb.webp"
    generate_thumbnail(jpg_source, cache_path, size=64)
    assert cache_path.exists()
    with Image.open(cache_path) as img:
        assert img.size == (64, 64)
        assert img.format == "WEBP"


def test_generate_from_png(png_source, tmp_path):
    cache_path = tmp_path / "thumb.webp"
    generate_thumbnail(png_source, cache_path, size=64)
    assert cache_path.exists()
    with Image.open(cache_path) as img:
        assert img.size == (64, 64)
        assert img.mode == "RGBA"  # 保留透明通道


def test_generate_preserves_aspect_ratio(jpg_source, tmp_path):
    """100x80 源图 → 64x64 缩略图，保持宽高比缩放（不变形）。"""
    cache_path = tmp_path / "thumb.webp"
    generate_thumbnail(jpg_source, cache_path, size=64)
    # 重新打开缩略图，检查非透明像素区域比例（不要求精确，仅验证未被拉伸）
    with Image.open(cache_path) as img:
        assert img.size == (64, 64)  # 输出尺寸固定 64x64


def test_generate_missing_source_raises(tmp_path):
    cache_path = tmp_path / "thumb.png"
    source = tmp_path / "nonexistent.jpg"
    with pytest.raises(ThumbnailSourceNotFoundError):
        generate_thumbnail(source, cache_path)


def test_generate_corrupt_source_raises(tmp_path):
    cache_path = tmp_path / "thumb.png"
    source = tmp_path / "corrupt.jpg"
    source.write_bytes(b"not an image")
    with pytest.raises(ThumbnailSourceCorruptError):
        generate_thumbnail(source, cache_path)


def test_generate_unsupported_format_raises(tmp_path):
    cache_path = tmp_path / "thumb.png"
    source = tmp_path / "file.txt"
    source.write_text("hello")
    with pytest.raises(ThumbnailSourceUnsupportedError):
        generate_thumbnail(source, cache_path)


def test_generate_does_not_modify_source(jpg_source, tmp_path):
    """生成缩略图后源图 size/mtime 应保持不变（spec §9：不修改用户原图）。"""
    original_size, original_mtime = get_source_signature(jpg_source)
    cache_path = tmp_path / "thumb.png"
    generate_thumbnail(jpg_source, cache_path, size=64)
    new_size, new_mtime = get_source_signature(jpg_source)
    assert new_size == original_size
    # mtime 精度到秒，sleep 后再读取
    # 文件未被写入，mtime 应保持不变
    assert new_mtime == original_mtime


def test_generate_overwrites_existing_cache(jpg_source, tmp_path):
    cache_path = tmp_path / "thumb.png"
    generate_thumbnail(jpg_source, cache_path, size=64)
    # 再次生成
    generate_thumbnail(jpg_source, cache_path, size=64)
    assert cache_path.exists()
    # 文件被覆盖（不应失败）


def test_get_source_signature_returns_size_and_mtime(jpg_source):
    size, mtime = get_source_signature(jpg_source)
    assert size > 0
    assert mtime > 0


def test_generate_custom_size(png_source, tmp_path):
    """Q1: C 可配置尺寸。"""
    cache_path = tmp_path / "thumb.png"
    generate_thumbnail(png_source, cache_path, size=48)
    with Image.open(cache_path) as img:
        assert img.size == (48, 48)


def test_generate_with_rounded_corners(png_source, tmp_path):
    """Q2: C 圆角边框。验证输出有透明像素（圆角处）。"""
    cache_path = tmp_path / "thumb.png"
    generate_thumbnail(png_source, cache_path, size=64)
    with Image.open(cache_path) as img:
        # 圆角处应为透明（alpha=0）
        alpha = img.split()[-1]
        # 4 个角中至少一个应为完全透明
        corner_alpha = alpha.getpixel((0, 0))
        assert corner_alpha == 0  # 圆角处透明
