"""RecentTags 单元测试（UI合理性8，2026-08-02）。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from app.recent_tags import RecentTags


def _make_settings(tmp_path: Path) -> QSettings:
    ini = tmp_path / "test.ini"
    return QSettings(str(ini), QSettings.Format.IniFormat)


def test_record_latest_and_order(tmp_path: Path) -> None:
    """record 后最近列表按新→旧排序。"""
    recent = RecentTags(_make_settings(tmp_path))

    recent.record("tag-a")
    recent.record("tag-b")
    recent.record("tag-c")

    assert recent.list_recent() == ["tag-c", "tag-b", "tag-a"]


def test_record_dedup_reorders(tmp_path: Path) -> None:
    """重复记录同一 tag → 去重置顶。"""
    recent = RecentTags(_make_settings(tmp_path))

    recent.record("tag-a")
    recent.record("tag-b")
    recent.record("tag-a")

    assert recent.list_recent() == ["tag-a", "tag-b"]


def test_max_tags_evicts_oldest(tmp_path: Path) -> None:
    """超过上限时丢弃最旧。"""
    recent = RecentTags(_make_settings(tmp_path), max_tags=3)

    for i in range(5):
        recent.record(f"tag-{i}")

    assert recent.list_recent() == ["tag-4", "tag-3", "tag-2"]


def test_persisted_across_instances(tmp_path: Path) -> None:
    """QSettings 持久化：新实例可读取旧记录。"""
    first = RecentTags(_make_settings(tmp_path))
    first.record("tag-a")
    first.record("tag-b")

    second = RecentTags(_make_settings(tmp_path))

    assert second.list_recent() == ["tag-b", "tag-a"]


def test_empty_and_blank_ignored(tmp_path: Path) -> None:
    """空状态返回空；空 id 不记录。"""
    recent = RecentTags(_make_settings(tmp_path))

    assert recent.list_recent() == []
    recent.record("")
    recent.record("tag-a")
    recent.record("")

    assert recent.list_recent() == ["tag-a"]
