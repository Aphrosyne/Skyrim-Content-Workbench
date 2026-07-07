"""path_utils 测试。"""

from __future__ import annotations

from pathlib import Path

from infrastructure.path_utils import make_path_key


def test_make_path_key_normalizes_separators() -> None:
    """冗余分隔符应被规范。"""
    key1 = make_path_key(Path("D:/Mods/Armor/test"))
    key2 = make_path_key(Path("D:/Mods/Armor//test"))
    assert key1 == key2


def test_make_path_key_normalizes_dot_segments() -> None:
    """相对段应被消除。"""
    key1 = make_path_key(Path("D:/Mods/Armor/test"))
    key2 = make_path_key(Path("D:/Mods/Armor/inner/../test"))
    assert key1 == key2


def test_make_path_key_chinese_path() -> None:
    """中文路径应被保留。"""
    key = make_path_key(Path("D:/Mods/护甲/测试/example.7z"))
    assert "护甲" in key
    assert "测试" in key


def test_make_path_key_accepts_string() -> None:
    """应接受字符串输入。"""
    key = make_path_key("D:/Mods/Armor/test")
    assert isinstance(key, str)


def test_make_path_key_idempotent() -> None:
    """对同一路径多次调用结果一致。"""
    p = Path("D:/Mods/护甲/测试/example.7z")
    assert make_path_key(p) == make_path_key(p)


def test_make_path_key_drives_consistent_casing() -> None:
    """同一驱动器不同大小写应产生相同 key（Windows normcase 行为）。

    注意：本测试反映 A2 决策在 Windows 下的行为。
    在非 Windows 平台 normcase 不改变大小写，测试仍应通过（两侧一致）。
    """
    key_upper = make_path_key(Path("D:/Mods/test"))
    key_lower = make_path_key(Path("d:/Mods/test"))
    assert key_upper == key_lower
