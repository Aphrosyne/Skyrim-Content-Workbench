"""file_classify 扩展名分类测试。"""

from __future__ import annotations

from infrastructure.file_classify import (
    ARCHIVE_EXTENSIONS,
    IMAGE_EXTENSIONS,
    AssetHint,
    classify_by_extension,
    get_extension,
)


def test_get_extension_basic() -> None:
    assert get_extension("file.7z") == ".7z"
    assert get_extension("file.zip") == ".zip"


def test_get_extension_lowercase() -> None:
    """大写扩展名应转为小写。"""
    assert get_extension("IMAGE.PNG") == ".png"
    assert get_extension("ARCHIVE.7Z") == ".7z"


def test_get_extension_multiple_dots() -> None:
    """多扩展名仅返回最后一段。"""
    assert get_extension("archive.tar.gz") == ".gz"
    assert get_extension("name.with.many.dots.zip") == ".zip"


def test_get_extension_no_extension() -> None:
    assert get_extension("README") == ""
    assert get_extension("") == ""
    # 'noext.' 末尾点号视为空扩展名
    assert get_extension("noext.") == ""


def test_get_extension_only_dots() -> None:
    """仅含点号的文件名应返回空字符串。"""
    assert get_extension(".") == ""
    assert get_extension("..") == ""
    assert get_extension("...") == ""


def test_classify_image_extensions() -> None:
    for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"]:
        assert classify_by_extension(f"file{ext}") == AssetHint.IMAGE
        # 大写也应正确分类
        assert classify_by_extension(f"file{ext.upper()}") == AssetHint.IMAGE


def test_classify_archive_extensions() -> None:
    for ext in [".7z", ".zip", ".rar", ".001", ".r01", ".tar", ".gz"]:
        assert classify_by_extension(f"file{ext}") == AssetHint.ARCHIVE
        assert classify_by_extension(f"file{ext.upper()}") == AssetHint.ARCHIVE


def test_classify_other_extensions() -> None:
    for name in ["README.txt", "doc.pdf", "data.json", "noext", "config"]:
        assert classify_by_extension(name) == AssetHint.OTHER


def test_classify_chinese_filename_image() -> None:
    assert classify_by_extension("预览图.webp") == AssetHint.IMAGE
    assert classify_by_extension("截图.png") == AssetHint.IMAGE


def test_classify_chinese_filename_archive() -> None:
    assert classify_by_extension("寒霜之心.7z") == AssetHint.ARCHIVE
    assert classify_by_extension("汉化包.zip") == AssetHint.ARCHIVE


def test_image_extensions_are_lowercase() -> None:
    """集合内扩展名应为小写（约定）。"""
    for ext in IMAGE_EXTENSIONS:
        assert ext == ext.lower()
        assert ext.startswith(".")


def test_archive_extensions_are_lowercase() -> None:
    for ext in ARCHIVE_EXTENSIONS:
        assert ext == ext.lower()
        assert ext.startswith(".")
