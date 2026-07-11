"""ThumbnailGenerator 测试。

覆盖：
- 从测试图片生成缓存；
- 缓存写入指定目录，不写入源目录；
- 源图片内容、mtime、size 不被修改；
- 中文路径；
- 缓存命中；
- 不存在文件；
- 损坏图片；
- 不支持格式。

测试图片使用 Pillow 生成小型 PNG/WEBP/JPG。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from infrastructure.thumbnail_generator import (
    SUPPORTED_EXTENSIONS,
    ThumbnailGenerator,
    ThumbnailStatus,
)

pytest.importorskip("PIL", reason="Pillow 未安装")
from PIL import Image  # noqa: E402


def _make_png(path: Path, size: tuple[int, int] = (200, 150)) -> Path:
    """生成小型 PNG 测试图片。"""
    img = Image.new("RGB", size, color=(255, 0, 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG")
    return path


def _make_webp(path: Path, size: tuple[int, int] = (200, 150)) -> Path:
    """生成小型 WEBP 测试图片。"""
    img = Image.new("RGB", size, color=(0, 255, 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="WEBP")
    return path


def _make_jpg(path: Path, size: tuple[int, int] = (200, 150)) -> Path:
    """生成小型 JPEG 测试图片。"""
    img = Image.new("RGB", size, color=(0, 0, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="JPEG")
    return path


def test_generate_png_creates_cache(tmp_path: Path) -> None:
    """从 PNG 生成缩略图缓存。"""
    source = _make_png(tmp_path / "src" / "test.png")
    cache_dir = tmp_path / "thumbnails"

    gen = ThumbnailGenerator(cache_dir)
    result = gen.generate("asset-1", source)

    assert result.status == ThumbnailStatus.OK
    assert result.cache_path is not None
    assert result.cache_path.exists()
    # 缓存文件名格式 {asset_id}.png
    assert result.cache_path.name == "asset-1.png"


def test_generate_writes_to_cache_dir_not_source_dir(tmp_path: Path) -> None:
    """缩略图写入缓存目录，不写入源目录。"""
    source = _make_png(tmp_path / "src" / "test.png")
    cache_dir = tmp_path / "thumbnails"

    gen = ThumbnailGenerator(cache_dir)
    gen.generate("asset-2", source)

    # 源目录只有原始图片
    src_files = list((tmp_path / "src").iterdir())
    assert len(src_files) == 1
    assert src_files[0].name == "test.png"

    # 缓存目录有缩略图
    cache_files = list(cache_dir.iterdir())
    assert len(cache_files) == 1
    assert cache_files[0].name == "asset-2.png"


def test_generate_preserves_source_file(tmp_path: Path) -> None:
    """生成缩略图后源文件内容、size、mtime 不变。"""
    source = _make_png(tmp_path / "src" / "test.png")
    content_before = source.read_bytes()
    size_before = source.stat().st_size
    mtime_before = source.stat().st_mtime

    gen = ThumbnailGenerator(tmp_path / "thumbnails")
    gen.generate("asset-3", source)

    content_after = source.read_bytes()
    size_after = source.stat().st_size
    mtime_after = source.stat().st_mtime

    assert content_after == content_before
    assert size_after == size_before
    assert mtime_after == mtime_before


def test_generate_chinese_path(tmp_path: Path) -> None:
    """中文路径图片可生成缩略图。"""
    source = _make_png(tmp_path / "中文目录" / "预览图.png")
    gen = ThumbnailGenerator(tmp_path / "thumbnails")
    result = gen.generate("asset-cn", source)

    assert result.status == ThumbnailStatus.OK
    assert result.cache_path is not None
    assert result.cache_path.exists()


def test_generate_webp(tmp_path: Path) -> None:
    """WEBP 格式可生成缩略图。"""
    source = _make_webp(tmp_path / "src" / "test.webp")
    gen = ThumbnailGenerator(tmp_path / "thumbnails")
    result = gen.generate("asset-webp", source)

    assert result.status == ThumbnailStatus.OK
    assert result.cache_path is not None


def test_generate_jpg(tmp_path: Path) -> None:
    """JPEG 格式可生成缩略图。"""
    source = _make_jpg(tmp_path / "src" / "test.jpg")
    gen = ThumbnailGenerator(tmp_path / "thumbnails")
    result = gen.generate("asset-jpg", source)

    assert result.status == ThumbnailStatus.OK
    assert result.cache_path is not None


def test_generate_missing_file(tmp_path: Path) -> None:
    """源文件不存在返回 MISSING。"""
    gen = ThumbnailGenerator(tmp_path / "thumbnails")
    result = gen.generate("asset-missing", tmp_path / "nonexistent.png")

    assert result.status == ThumbnailStatus.MISSING
    assert result.cache_path is None
    assert "不存在" in (result.error_message or "")


def test_generate_corrupt_image(tmp_path: Path) -> None:
    """损坏图片返回 CORRUPT。"""
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not a real png image data")
    gen = ThumbnailGenerator(tmp_path / "thumbnails")
    result = gen.generate("asset-corrupt", corrupt)

    assert result.status == ThumbnailStatus.CORRUPT
    assert result.cache_path is None


def test_generate_unsupported_format(tmp_path: Path) -> None:
    """不支持格式返回 UNSUPPORTED。"""
    source = tmp_path / "test.txt"
    source.write_text("hello")
    gen = ThumbnailGenerator(tmp_path / "thumbnails")
    result = gen.generate("asset-txt", source)

    assert result.status == ThumbnailStatus.UNSUPPORTED
    assert result.cache_path is None


def test_generate_thumbnail_size(tmp_path: Path) -> None:
    """生成的缩略图尺寸不超过 max_size。"""
    source = _make_png(tmp_path / "src" / "big.png", size=(500, 400))
    gen = ThumbnailGenerator(tmp_path / "thumbnails", max_size=64)
    result = gen.generate("asset-size", source)

    assert result.status == ThumbnailStatus.OK
    assert result.cache_path is not None
    with Image.open(result.cache_path) as thumb:
        assert max(thumb.size) <= 64


def test_supported_extensions_contains_common_formats() -> None:
    """支持的扩展名包含常见格式。"""
    assert ".jpg" in SUPPORTED_EXTENSIONS
    assert ".jpeg" in SUPPORTED_EXTENSIONS
    assert ".png" in SUPPORTED_EXTENSIONS
    assert ".webp" in SUPPORTED_EXTENSIONS


def test_cache_path_for_returns_consistent_path(tmp_path: Path) -> None:
    """cache_path_for 返回一致的路径。"""
    cache_dir = tmp_path / "thumbnails"
    gen = ThumbnailGenerator(cache_dir)
    path1 = gen.cache_path_for("asset-x")
    path2 = gen.cache_path_for("asset-x")
    assert path1 == path2
    assert path1.name == "asset-x.png"
    assert path1.parent == cache_dir
