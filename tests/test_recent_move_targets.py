"""RecentMoveTargets 单元测试（操作便捷性3，2026-08-02）。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from app.recent_move_targets import RecentMoveTargets


def _make_settings(tmp_path: Path) -> QSettings:
    """构造指向临时 ini 文件的 QSettings（避免写注册表）。"""
    ini = tmp_path / "test.ini"
    return QSettings(str(ini), QSettings.Format.IniFormat)


def test_record_latest_and_order(tmp_path: Path) -> None:
    """record 后 latest 为最新，list_recent 按新→旧。"""
    targets = RecentMoveTargets(_make_settings(tmp_path))

    targets.record("/m/a")
    targets.record("/m/b")
    targets.record("/m/c")

    assert targets.latest() == "/m/c"
    assert targets.list_recent() == ["/m/c", "/m/b", "/m/a"]


def test_record_dedup_reorders(tmp_path: Path) -> None:
    """重复记录同一目标（含路径归一化差异）→ 去重置顶。"""
    targets = RecentMoveTargets(_make_settings(tmp_path))

    targets.record("D:/Mods/Armor")
    targets.record("D:/Mods/Weapons")
    # 归一化差异（大小写/分隔符）视为同一目标
    targets.record("d:\\mods\\armor")

    # 去重生效：latest 为最后一次记录的原始字符串（保留新记录书写形式）
    assert targets.latest() == "d:\\mods\\armor"
    assert len(targets.list_recent()) == 2


def test_max_targets_evicts_oldest(tmp_path: Path) -> None:
    """超过上限时丢弃最旧目标。"""
    targets = RecentMoveTargets(_make_settings(tmp_path), max_targets=3)

    for i in range(5):
        targets.record(f"/m/{i}")

    assert targets.list_recent() == ["/m/4", "/m/3", "/m/2"]


def test_persisted_across_instances(tmp_path: Path) -> None:
    """QSettings 持久化：新实例可读取旧记录。"""
    settings = _make_settings(tmp_path)
    first = RecentMoveTargets(settings)
    first.record("/m/a")
    first.record("/m/b")

    second = RecentMoveTargets(_make_settings(tmp_path))

    assert second.list_recent() == ["/m/b", "/m/a"]
    assert second.latest() == "/m/b"


def test_empty_state(tmp_path: Path) -> None:
    """无记录时 latest 为 None，list_recent 为空。"""
    targets = RecentMoveTargets(_make_settings(tmp_path))

    assert targets.latest() is None
    assert targets.list_recent() == []
