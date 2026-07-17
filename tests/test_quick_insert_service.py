"""QuickInsertService 单元测试（阶段 3 Task 5）。

覆盖：
- 快速插入成功：Mod 组文件夹移入目标目录 + ContentUnit.path 同步 + operation_history 记录
- 跨盘移动检测（不同 st_dev 抛 CrossDriveError）
- 子目录阻止（目标在源子树内抛 SelfSubdirectoryError）
- 重名冲突（目标已存在抛 ConflictError）
- 中文路径支持
- folder_cache mtime 同步（与 ModGroupService 一致）
- ContentUnit 不存在（抛 ContentUnitNotFoundError）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from application.content_service import ContentService
from application.errors import (
    ConflictError,
    ContentUnitNotFoundError,
    CrossDriveError,
    SelfSubdirectoryError,
)
from application.quick_insert_service import QuickInsertService
from infrastructure.db import get_connection, init_db
from infrastructure.file_operation_service import FileOperationService
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.folder_cache import FolderCacheRepository
from infrastructure.repositories.operation_history import (
    OperationHistoryRepository,
)


@pytest.fixture
def db_env(tmp_path: Path):
    """构造测试环境：内存数据库 + ContentService + QuickInsertService。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row

    content_repo = ContentUnitRepository(conn)
    folder_cache_repo = FolderCacheRepository(conn)
    history_repo = OperationHistoryRepository(conn)
    file_op = FileOperationService(history_repo)
    content_service = ContentService(content_repo)

    service = QuickInsertService(file_op, content_repo, folder_cache_repo)
    yield service, content_service, conn, folder_cache_repo, history_repo
    conn.close()


@pytest.fixture
def mod_group_env(db_env, tmp_path: Path):
    """构造一个 Mod 组文件夹 + 已标记的 ContentUnit + 目标分类目录。

    结构：
        tmp_path/Stash/MyMod/         ← Mod 组文件夹（已标记 ContentUnit）
                /MyMod/source.7z      ← Mod 组内的文件
        tmp_path/Armor/               ← 目标分类目录
    """
    service, content_service, conn, folder_cache_repo, history_repo = db_env

    staging = tmp_path / "Stash"
    staging.mkdir()
    mod_folder = staging / "MyMod"
    mod_folder.mkdir()
    (mod_folder / "source.7z").write_bytes(b"\x00" * 100)

    target_dir = tmp_path / "Armor"
    target_dir.mkdir()

    # 标记 Mod 组文件夹为 ContentUnit
    unit = content_service.mark_as_content_unit(mod_folder)
    conn.commit()

    yield (
        service,
        content_service,
        conn,
        unit,
        mod_folder,
        target_dir,
        folder_cache_repo,
        history_repo,
    )  # noqa: E501


# === 快速插入成功 ===


def test_quick_insert_moves_mod_group_to_target(db_env, mod_group_env, tmp_path: Path) -> None:
    """快速插入成功：Mod 组文件夹整体移入目标目录。"""
    service, content_service, conn, unit, mod_folder, target_dir, _, history_repo = mod_group_env

    # 执行快速插入
    result_unit = service.quick_insert(unit.id, target_dir)
    conn.commit()

    # 源 Mod 组文件夹已移走
    assert not mod_folder.exists()
    # Mod 组文件夹已移入目标目录
    new_path = target_dir / mod_folder.name
    assert new_path.is_dir()
    assert (new_path / "source.7z").is_file()

    # 返回的 ContentUnit.path 已更新
    assert result_unit.path == str(new_path)
    assert result_unit.id == unit.id

    # 数据库中的 ContentUnit.path 已同步更新
    db_unit = content_service.get_by_id(unit.id)
    assert db_unit is not None
    assert db_unit.path == str(new_path)


def test_quick_insert_writes_operation_history(db_env, mod_group_env) -> None:
    """快速插入后应写入 operation_history 记录（operation_type='move'）。"""
    service, _, conn, unit, mod_folder, target_dir, _, history_repo = mod_group_env

    service.quick_insert(unit.id, target_dir)
    conn.commit()

    histories = history_repo.list_all()
    move_records = [h for h in histories if h.operation_type == "move"]
    assert len(move_records) >= 1
    last = move_records[-1]
    assert last.source_path == str(mod_folder)
    assert last.target_path == str(target_dir / mod_folder.name)
    assert last.can_undo is True


def test_quick_insert_syncs_folder_cache_complete(db_env, mod_group_env) -> None:
    """快速插入后应完整同步 folder_cache：删除旧节点 + 插入新节点 + 更新父目录 mtime。

    2026-07-17 用户验收修复：原实现只清理旧路径，导致目录树目标目录不刷新。
    现在与 ModGroupService 模式一致——服务层负责完整同步，UI 层只需 _refresh_tree。
    """
    service, _, conn, unit, mod_folder, target_dir, folder_cache_repo, _ = mod_group_env

    # 先为源 mod_folder 和 target_dir 写入 folder_cache 记录
    from domain.models import FolderCache

    source_fc = FolderCache(
        id="fc-source",
        path=str(mod_folder),
        parent_id=None,
        last_scanned_mtime=1000.0,
        created_at="2026-07-17T00:00:00Z",
    )
    target_fc = FolderCache(
        id="fc-target",
        path=str(target_dir),
        parent_id=None,
        last_scanned_mtime=2000.0,
        created_at="2026-07-17T00:00:00Z",
    )
    folder_cache_repo.create(source_fc)
    folder_cache_repo.create(target_fc)
    conn.commit()
    old_target_mtime = target_fc.last_scanned_mtime

    service.quick_insert(unit.id, target_dir)
    conn.commit()

    new_path = target_dir / mod_folder.name

    # 1. 旧路径的 folder_cache 记录已删除
    all_fcs = folder_cache_repo.list_all()
    old_path_keys = [make_path_key(fc.path) for fc in all_fcs]
    assert make_path_key(str(mod_folder)) not in old_path_keys

    # 2. 新路径的 folder_cache 记录已插入
    new_fc = None
    for fc in all_fcs:
        if make_path_key(fc.path) == make_path_key(str(new_path)):
            new_fc = fc
            break
    assert new_fc is not None, f"新路径 folder_cache 未插入：{new_path}"
    # parent_id 应指向目标目录的 folder_cache.id
    assert new_fc.parent_id == target_fc.id

    # 3. 目标目录的 last_scanned_mtime 已更新（应不等于旧值）
    updated_target_fc = folder_cache_repo.get_by_id(target_fc.id)
    assert updated_target_fc is not None
    assert updated_target_fc.last_scanned_mtime != old_target_mtime


# === 错误分支 ===


def test_quick_insert_conflict_target_exists(db_env, mod_group_env) -> None:
    """目标目录已存在同名文件夹 → ConflictError。"""
    service, _, conn, unit, mod_folder, target_dir, _, _ = mod_group_env

    # 在目标目录下预先创建同名文件夹
    (target_dir / mod_folder.name).mkdir()

    with pytest.raises(ConflictError):
        service.quick_insert(unit.id, target_dir)
    conn.rollback()

    # 源文件夹仍在原位
    assert mod_folder.is_dir()


def test_quick_insert_self_subdirectory(db_env, mod_group_env) -> None:
    """目标在 Mod 组子目录内 → SelfSubdirectoryError。"""
    service, _, conn, unit, mod_folder, _, _, _ = mod_group_env

    # 在 Mod 组内创建一个子目录，将其作为目标
    sub_dir = mod_folder / "SubDir"
    sub_dir.mkdir()

    with pytest.raises(SelfSubdirectoryError):
        service.quick_insert(unit.id, sub_dir)
    conn.rollback()

    # 源文件夹仍在原位
    assert mod_folder.is_dir()


def test_quick_insert_unit_not_found(db_env, tmp_path: Path) -> None:
    """ContentUnit 不存在 → ContentUnitNotFoundError。"""
    service, _, conn, _, _ = db_env
    target_dir = tmp_path / "Target"
    target_dir.mkdir()

    with pytest.raises(ContentUnitNotFoundError):
        service.quick_insert("non-existent-id", target_dir)


def test_quick_insert_cross_drive(db_env, mod_group_env, monkeypatch: pytest.MonkeyPatch) -> None:
    """跨盘移动 → CrossDriveError。

    通过 monkeypatch os.stat 让源和目标的 st_dev 不同来模拟跨盘。
    """
    service, _, conn, unit, mod_folder, target_dir, _, _ = mod_group_env

    real_stat = Path.stat

    class FakeStatResult:
        def __init__(self, st_dev: int, st_mtime: float = 0.0, st_size: int = 0) -> None:
            self.st_dev = st_dev
            self.st_mtime = st_mtime
            self.st_size = st_size

    def fake_stat(self: Path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        # 源目录树返回 dev=1，目标目录树返回 dev=2
        s = real_stat(self, *args, **kwargs)
        path_str = str(self)
        if path_str.startswith(str(target_dir)):
            return FakeStatResult(st_dev=2, st_mtime=s.st_mtime, st_size=s.st_size)
        return FakeStatResult(st_dev=1, st_mtime=s.st_mtime, st_size=s.st_size)

    monkeypatch.setattr(Path, "stat", fake_stat)

    with pytest.raises(CrossDriveError):
        service.quick_insert(unit.id, target_dir)
    conn.rollback()

    # 源文件夹仍在原位
    assert mod_folder.is_dir()


# === 中文路径 ===


def test_quick_insert_chinese_path(db_env, tmp_path: Path) -> None:
    """中文路径支持：Mod 组名和目标目录名均含中文。"""
    service, content_service, conn, _, _ = db_env

    staging = tmp_path / "暂存区"
    staging.mkdir()
    mod_folder = staging / "寒霜之心"
    mod_folder.mkdir()
    (mod_folder / "本体.7z").write_bytes(b"\x00" * 50)

    target_dir = tmp_path / "护甲分类"
    target_dir.mkdir()

    unit = content_service.mark_as_content_unit(mod_folder)
    conn.commit()

    result = service.quick_insert(unit.id, target_dir)
    conn.commit()

    new_path = target_dir / "寒霜之心"
    assert new_path.is_dir()
    assert (new_path / "本体.7z").is_file()
    assert result.path == str(new_path)

    db_unit = content_service.get_by_id(unit.id)
    assert db_unit is not None
    assert db_unit.path == str(new_path)


# === 目标路径旧 ContentUnit 清理（2026-07-17 修复 UNIQUE 约束冲突） ===


def test_quick_insert_cleans_stale_content_unit_at_target_path(db_env, tmp_path: Path) -> None:
    """目标路径已有旧 ContentUnit 记录时，快速插入应先清理旧记录再更新。

    场景：之前快速插入过同名 Mod 组到目标路径，用户删除了文件但数据库记录残留，
    再次快速插入时不应触发 UNIQUE 约束冲突。
    """
    service, content_service, conn, _, _ = db_env

    staging = tmp_path / "Stash"
    staging.mkdir()
    mod_folder = staging / "MyMod"
    mod_folder.mkdir()
    (mod_folder / "source.7z").write_bytes(b"\x00" * 100)

    target_dir = tmp_path / "Armor"
    target_dir.mkdir()

    # 标记 Mod 组文件夹为 ContentUnit
    unit = content_service.mark_as_content_unit(mod_folder)
    conn.commit()

    # 在目标路径下预先创建一条旧 ContentUnit 记录（模拟历史残留）
    stale_path = target_dir / "MyMod"
    from domain.models import ContentUnit

    stale_unit = ContentUnit(
        id="stale-unit-id",
        path=str(stale_path),
        title="旧残留记录",
        content_type="mod",
        status="unorganized",
        created_at="2026-07-17T00:00:00Z",
        updated_at="2026-07-17T00:00:00Z",
    )
    from infrastructure.repositories.content_unit import ContentUnitRepository

    ContentUnitRepository(conn).create(stale_unit)
    conn.commit()

    # 快速插入：应先清理旧记录，再更新当前 unit.path，不触发 UNIQUE 冲突
    result = service.quick_insert(unit.id, target_dir)
    conn.commit()

    # 当前 unit.path 已更新为新路径
    new_path = target_dir / "MyMod"
    assert result.path == str(new_path)

    # 旧残留记录已被删除
    from infrastructure.repositories.content_unit import ContentUnitRepository

    all_units = ContentUnitRepository(conn).list_all()
    stale_ids = [u.id for u in all_units]
    assert "stale-unit-id" not in stale_ids
    # 当前 unit 仍存在
    assert unit.id in stale_ids


def test_quick_insert_cleans_stale_child_content_units(db_env, tmp_path: Path) -> None:
    """目标路径子项有旧 ContentUnit 记录时也应清理。

    场景：目标路径下之前扫描过，有子项压缩包的 ContentUnit 记录。
    移动 Mod 组文件夹到目标路径后，这些子项记录已无效，应清理。
    """
    service, content_service, conn, _, _ = db_env

    staging = tmp_path / "Stash"
    staging.mkdir()
    mod_folder = staging / "MyMod"
    mod_folder.mkdir()
    (mod_folder / "source.7z").write_bytes(b"\x00" * 100)

    target_dir = tmp_path / "Armor"
    target_dir.mkdir()

    unit = content_service.mark_as_content_unit(mod_folder)
    conn.commit()

    # 在目标路径下预先创建子项旧 ContentUnit 记录
    stale_child_path = target_dir / "MyMod" / "old_archive.7z"
    from domain.models import ContentUnit

    stale_child = ContentUnit(
        id="stale-child-id",
        path=str(stale_child_path),
        title="旧子项记录",
        content_type="mod",
        status="unorganized",
        created_at="2026-07-17T00:00:00Z",
        updated_at="2026-07-17T00:00:00Z",
    )
    from infrastructure.repositories.content_unit import ContentUnitRepository

    ContentUnitRepository(conn).create(stale_child)
    conn.commit()

    # 快速插入：应清理子项旧记录
    service.quick_insert(unit.id, target_dir)
    conn.commit()

    # 子项旧记录已被删除
    from infrastructure.repositories.content_unit import ContentUnitRepository

    all_units = ContentUnitRepository(conn).list_all()
    unit_ids = [u.id for u in all_units]
    assert "stale-child-id" not in unit_ids
    assert unit.id in unit_ids


def test_quick_insert_cleans_stale_content_unit_with_path_normalization(
    db_env, tmp_path: Path
) -> None:
    """路径归一化场景：旧记录 path 与 dst_folder 原始字符串不同但 make_path_key 相同时也应清理。

    2026-07-17 根因修复验证：
    - 原实现用 list_by_path_prefix 的 SQL LIKE 匹配，Windows 反斜杠路径下 LIKE 转义 broken
    - 新实现用 list_all + make_path_key 归一化比较，符合 AGENTS 规则 9
    - 本测试构造尾随分隔符差异（normpath 可消除），验证归一化比较有效

    场景：旧记录 path = "D:\\Mods\\Armor\\MyMod\\"（尾随分隔符），
    dst_folder = "D:\\Mods\\Armor\\MyMod"（无尾随分隔符）。
    原始字符串不同，但 make_path_key 归一化后相同，应能清理。
    """
    service, content_service, conn, _, _ = db_env

    staging = tmp_path / "Stash"
    staging.mkdir()
    mod_folder = staging / "MyMod"
    mod_folder.mkdir()
    (mod_folder / "source.7z").write_bytes(b"\x00" * 100)

    target_dir = tmp_path / "Armor"
    target_dir.mkdir()

    unit = content_service.mark_as_content_unit(mod_folder)
    conn.commit()

    # 旧记录 path 与 dst_folder 原始字符串不同（尾随分隔符），但 make_path_key 相同
    import os

    stale_path_with_trailing_sep = str(target_dir / "MyMod") + os.sep
    from domain.models import ContentUnit
    from infrastructure.repositories.content_unit import ContentUnitRepository

    stale_unit = ContentUnit(
        id="stale-normalized-id",
        path=stale_path_with_trailing_sep,
        title="尾随分隔符旧记录",
        content_type="mod",
        status="unorganized",
        created_at="2026-07-17T00:00:00Z",
        updated_at="2026-07-17T00:00:00Z",
    )
    ContentUnitRepository(conn).create(stale_unit)
    conn.commit()

    # 验证归一化后路径相同（测试前提）
    assert make_path_key(stale_path_with_trailing_sep) == make_path_key(str(target_dir / "MyMod"))

    # 快速插入：应通过 make_path_key 归一化匹配清理旧记录，update 不触发 UNIQUE 冲突
    result = service.quick_insert(unit.id, target_dir)
    conn.commit()

    new_path = target_dir / "MyMod"
    assert result.path == str(new_path)

    # 旧记录已被删除
    all_units = ContentUnitRepository(conn).list_all()
    unit_ids = [u.id for u in all_units]
    assert "stale-normalized-id" not in unit_ids
    assert unit.id in unit_ids


def test_quick_insert_cleanup_before_move_allows_safe_rollback(db_env, tmp_path: Path) -> None:
    """验证新顺序 cleanup → move → update：cleanup 在 move 之前，若 move 失败可安全 rollback。

    2026-07-17 根因修复验证：
    - 旧顺序 move → cleanup → update：若 update 失败，rollback 回滚 cleanup，
      旧记录复活，下次重试 update 仍 UNIQUE 冲突 → 死循环
    - 新顺序 cleanup → move → update：cleanup 在 move 之前，若 move 失败，
      rollback 回滚 cleanup（旧记录复活），但文件未移动，下次重试可正常清理

    本测试验证：move 失败（ConflictError）后，旧记录被 rollback 恢复，
    但数据库无写锁残留，且下次 quick_insert 可正常执行。
    """
    service, content_service, conn, _, _ = db_env

    staging = tmp_path / "Stash"
    staging.mkdir()
    mod_folder = staging / "MyMod"
    mod_folder.mkdir()
    (mod_folder / "source.7z").write_bytes(b"\x00" * 100)

    target_dir = tmp_path / "Armor"
    target_dir.mkdir()

    unit = content_service.mark_as_content_unit(mod_folder)
    conn.commit()

    # 在目标路径下预先创建旧 ContentUnit 记录
    from domain.models import ContentUnit
    from infrastructure.repositories.content_unit import ContentUnitRepository

    stale_unit = ContentUnit(
        id="stale-before-move",
        path=str(target_dir / "MyMod"),
        title="旧记录",
        content_type="mod",
        status="unorganized",
        created_at="2026-07-17T00:00:00Z",
        updated_at="2026-07-17T00:00:00Z",
    )
    ContentUnitRepository(conn).create(stale_unit)
    conn.commit()

    # 在文件系统上创建同名文件夹，让 move 失败（ConflictError）
    (target_dir / "MyMod").mkdir()

    # 第一次快速插入：cleanup 清理旧记录（事务内），move 失败（ConflictError）
    with pytest.raises(ConflictError):
        service.quick_insert(unit.id, target_dir)
    conn.rollback()  # 模拟 main_window 的 rollback

    # rollback 后：旧记录复活（cleanup 被回滚），文件未移动
    all_units = ContentUnitRepository(conn).list_all()
    unit_ids = [u.id for u in all_units]
    assert "stale-before-move" in unit_ids  # 旧记录复活
    assert unit.id in unit_ids  # 当前 unit 仍在
    assert mod_folder.is_dir()  # 源文件夹未移动

    # 删除文件系统冲突，第二次快速插入应成功
    import shutil

    shutil.rmtree(target_dir / "MyMod")

    result = service.quick_insert(unit.id, target_dir)
    conn.commit()

    # 第二次成功：旧记录被清理，unit.path 更新
    new_path = target_dir / "MyMod"
    assert result.path == str(new_path)
    all_units = ContentUnitRepository(conn).list_all()
    unit_ids = [u.id for u in all_units]
    assert "stale-before-move" not in unit_ids  # 旧记录被清理
    assert unit.id in unit_ids
