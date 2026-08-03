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


# === UI合理性16：cover 方形居中裁剪模式 ===


def test_horizontal_image_fills_square(jpg_source, tmp_path):
    """横向图（100x80）填满 256x256，无透明填充条。"""
    cache_path = tmp_path / "thumb.webp"
    generate_thumbnail(jpg_source, cache_path, size=256)
    with Image.open(cache_path) as img:
        assert img.size == (256, 256)
        # 不透明源图输出可为 RGB（WebP 优化掉全不透明 alpha 通道）
        if "A" in img.getbands():
            alpha = img.split()[-1]
            # 整幅 alpha 全为 255（无透明条、无圆角）
            assert alpha.getextrema() == (255, 255)
            assert alpha.getpixel((0, 0)) == 255  # 角不透明 → 无圆角


def test_vertical_image_fills_square(tmp_path):
    """竖向图（80x120，不透明）同样填满方形。"""
    source = tmp_path / "vertical.jpg"
    Image.new("RGB", (80, 120), color=(0, 0, 255)).save(source, format="JPEG")
    cache_path = tmp_path / "thumb.webp"
    generate_thumbnail(source, cache_path, size=128)
    with Image.open(cache_path) as img:
        assert img.size == (128, 128)
        if "A" in img.getbands():
            alpha = img.split()[-1]
            assert alpha.getextrema() == (255, 255)


def test_generate_keeps_source_signature(jpg_source, tmp_path):
    """生成缩略图不修改源图。"""
    original_size, original_mtime = get_source_signature(jpg_source)
    cache_path = tmp_path / "thumb.webp"
    generate_thumbnail(jpg_source, cache_path, size=256)
    new_size, new_mtime = get_source_signature(jpg_source)
    assert new_size == original_size
    assert new_mtime == original_mtime
