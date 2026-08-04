"""ArchiveSettings 单元测试（功能增加1 归档，2026-08-04）。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from app.archive_settings import ArchiveSettings


def _make_settings(tmp_path: Path) -> QSettings:
    """构造指向临时 ini 文件的 QSettings（避免写注册表）。"""
    ini = tmp_path / "test.ini"
    return QSettings(str(ini), QSettings.Format.IniFormat)


def test_root_default_none(tmp_path: Path) -> None:
    """未标记归档根目录时 root_path() 返回 None。"""
    settings = ArchiveSettings(_make_settings(tmp_path))

    assert settings.root_path() is None
    assert settings.last_target() is None


def test_set_and_read_root(tmp_path: Path) -> None:
    """set_root 后 root_path 可读、is_root 命中。"""
    settings = ArchiveSettings(_make_settings(tmp_path))
    root = tmp_path / "99_归档"
    root.mkdir()

    settings.set_root(root)

    assert settings.root_path() == str(root)
    assert settings.is_root(root)
    assert not settings.is_root(tmp_path / "其他")


def test_is_root_normalizes_case_and_separators(tmp_path: Path) -> None:
    """is_root 使用 make_path_key 归一化（大小写/分隔符差异视为同一路径）。"""
    settings = ArchiveSettings(_make_settings(tmp_path))
    settings.set_root("D:/Mods/99_归档")

    assert settings.is_root("d:\\mods\\99_归档")


def test_clear_root(tmp_path: Path) -> None:
    """clear_root 后恢复未标记状态。"""
    settings = ArchiveSettings(_make_settings(tmp_path))
    root = tmp_path / "归档"
    root.mkdir()
    settings.set_root(root)

    settings.clear_root()

    assert settings.root_path() is None
    assert not settings.is_root(root)


def test_record_and_read_last_target(tmp_path: Path) -> None:
    """record_target 后 last_target 可读，重复记录覆盖。"""
    settings = ArchiveSettings(_make_settings(tmp_path))
    first = tmp_path / "批次一"
    second = tmp_path / "批次二"

    settings.record_target(first)
    settings.record_target(second)

    assert settings.last_target() == str(second)


def test_clear_target(tmp_path: Path) -> None:
    """clear_target 后 last_target 恢复 None。"""
    settings = ArchiveSettings(_make_settings(tmp_path))
    settings.record_target(tmp_path / "批次")

    settings.clear_target()

    assert settings.last_target() is None


def test_persisted_across_instances(tmp_path: Path) -> None:
    """QSettings 持久化：新实例可读取旧归档设置。"""
    settings = _make_settings(tmp_path)
    root = tmp_path / "99_归档"
    target = tmp_path / "99_归档" / "2026-08"
    first = ArchiveSettings(settings)
    first.set_root(root)
    first.record_target(target)

    second = ArchiveSettings(settings)
    assert second.root_path() == str(root)
    assert second.last_target() == str(target)
    assert second.is_root(root)
