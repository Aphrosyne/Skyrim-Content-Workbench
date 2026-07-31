"""file_classify 扩展名分类测试。"""

from __future__ import annotations

from infrastructure.file_classify import (
    ARCHIVE_EXTENSIONS,
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


def test_archive_extensions_are_lowercase() -> None:
    for ext in ARCHIVE_EXTENSIONS:
        assert ext == ext.lower()
        assert ext.startswith(".")
