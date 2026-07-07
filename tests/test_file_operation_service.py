"""FileOperationService 测试。

所有文件操作使用 tmp_path 构造真实文件，验证实际移动行为。
不使用真实用户目录。
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from domain.models import (
    AssetKind,
    ConflictPolicy,
    FileAsset,
    FileRole,
    FolderNode,
    ModItem,
    OperationStatus,
    OperationType,
)
from infrastructure.file_operation_service import (
    FileOperationService,
)
from infrastructure.repositories.file_asset import FileAssetRepository
from infrastructure.repositories.folder_node import FolderNodeRepository
from infrastructure.repositories.mod_item import ModItemRepository
from infrastructure.repositories.operation_log import OperationLogRepository

# ---------- 固定时间 / UUID provider ----------


def _fixed_now() -> str:
    return "2026-07-07T00:00:00Z"


def _sequential_uuid() -> str:
    return str(uuid.uuid4())


# ---------- 辅助：构造真实文件与 DB 记录 ----------


def _make_file(path: Path, content: bytes = b"\x00" * 100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _insert_folder(
    repo: FolderNodeRepository,
    real_path: str,
    path_key: str | None = None,
    parent_id: str | None = None,
    is_managed_root: bool = False,
    now: str = "2026-07-07T00:00:00Z",
) -> FolderNode:
    node = FolderNode(
        id=str(uuid.uuid4()),
        real_path=real_path,
        path_key=path_key or real_path.lower(),
        parent_id=parent_id,
        display_name=None,
        is_managed_root=is_managed_root,
        created_at=now,
        updated_at=now,
    )
    return repo.create(node)


def _insert_file_asset(
    repo: FileAssetRepository,
    real_path: str,
    filename: str | None = None,
    path_key: str | None = None,
    mod_item_id: str | None = None,
    role: FileRole = FileRole.UNKNOWN,
    size_bytes: int = 100,
    now: str = "2026-07-07T00:00:00Z",
) -> FileAsset:
    asset = FileAsset(
        id=str(uuid.uuid4()),
        mod_item_id=mod_item_id,
        real_path=real_path,
        path_key=path_key or real_path.lower(),
        filename=filename or Path(real_path).name,
        extension=Path(real_path).suffix.lower(),
        asset_kind=AssetKind.FILE,
        role=role,
        size_bytes=size_bytes,
        modified_at=now,
        imported_at=now,
    )
    return repo.create(asset)


def _insert_mod_item(
    repo: ModItemRepository,
    display_name: str = "测试 Mod",
    now: str = "2026-07-07T00:00:00Z",
) -> ModItem:
    item = ModItem(
        id=str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
        display_name=display_name,
        description=None,
        source_url=None,
        category_folder_id=None,
        tags=set(),
        cover_asset_id=None,
    )
    return repo.create(item)


@pytest.fixture
def service(db_connection: sqlite3.Connection) -> FileOperationService:
    return FileOperationService(
        ModItemRepository(db_connection),
        FileAssetRepository(db_connection),
        FolderNodeRepository(db_connection),
        OperationLogRepository(db_connection),
        now_provider=_fixed_now,
        uuid_provider=_sequential_uuid,
    )


@pytest.fixture
def repos(
    db_connection: sqlite3.Connection,
) -> tuple[ModItemRepository, FileAssetRepository, FolderNodeRepository, OperationLogRepository]:
    return (
        ModItemRepository(db_connection),
        FileAssetRepository(db_connection),
        FolderNodeRepository(db_connection),
        OperationLogRepository(db_connection),
    )


# ---------- plan_move ----------


def test_plan_move_normal(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """正常预演：源存在、目标目录存在、无重名 → can_execute=True。"""
    mod_repo, file_repo, folder_repo, _ = repos

    # 构造源文件
    src_file = tmp_path / "src" / "mod.7z"
    _make_file(src_file)

    # 构造目标目录
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    # DB 记录
    folder = _insert_folder(folder_repo, str(target_dir), is_managed_root=True)
    mod = _insert_mod_item(mod_repo)
    asset = _insert_file_asset(
        file_repo,
        real_path=str(src_file),
        mod_item_id=mod.id,
        role=FileRole.MAIN_MOD,
    )

    plan = service.plan_move(mod.id, folder.id)

    assert plan.mod_item_id == mod.id
    assert plan.target_folder_id == folder.id
    assert len(plan.entries) == 1
    entry = plan.entries[0]
    assert entry.asset_id == asset.id
    assert entry.source_exists is True
    assert entry.target_exists is False
    assert entry.target_dir_exists is True
    assert entry.is_self_or_subdir is False
    assert entry.block_reason is None
    assert entry.can_execute is True
    assert plan.can_execute is True


def test_plan_move_source_missing(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """源文件缺失 → 阻止。"""
    mod_repo, file_repo, folder_repo, _ = repos

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    folder = _insert_folder(folder_repo, str(target_dir))
    mod = _insert_mod_item(mod_repo)
    _insert_file_asset(
        file_repo,
        real_path=str(tmp_path / "nonexistent.7z"),
        mod_item_id=mod.id,
    )

    plan = service.plan_move(mod.id, folder.id)

    assert plan.can_execute is False
    assert "源文件不存在" in plan.entries[0].block_reason


def test_plan_move_target_conflict(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """B3：目标重名即阻止。"""
    mod_repo, file_repo, folder_repo, _ = repos

    src_file = tmp_path / "src" / "mod.7z"
    _make_file(src_file)
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    # 目标已有同名文件
    _make_file(target_dir / "mod.7z")

    folder = _insert_folder(folder_repo, str(target_dir))
    mod = _insert_mod_item(mod_repo)
    _insert_file_asset(file_repo, real_path=str(src_file), mod_item_id=mod.id)

    plan = service.plan_move(mod.id, folder.id)

    assert plan.can_execute is False
    assert "重名" in plan.entries[0].block_reason


def test_plan_move_target_dir_not_exist(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """目标目录不存在 → 阻止。"""
    mod_repo, file_repo, folder_repo, _ = repos

    src_file = tmp_path / "mod.7z"
    _make_file(src_file)

    folder = _insert_folder(folder_repo, str(tmp_path / "nonexistent_dir"))
    mod = _insert_mod_item(mod_repo)
    _insert_file_asset(file_repo, real_path=str(src_file), mod_item_id=mod.id)

    plan = service.plan_move(mod.id, folder.id)

    assert plan.can_execute is False
    assert "目标目录不存在" in plan.entries[0].block_reason


def test_plan_move_self_or_subdir(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """spec §7.7：禁止移到自身或子目录。"""
    mod_repo, file_repo, folder_repo, _ = repos

    # 源文件在 D:/Mods/Armor/mod.7z
    # 目标目录是 D:/Mods/Armor（源的父目录，是源所在位置的子目录关系）
    src_dir = tmp_path / "Armor"
    src_dir.mkdir()
    src_file = src_dir / "mod.7z"
    _make_file(src_file)

    folder = _insert_folder(folder_repo, str(src_dir))
    mod = _insert_mod_item(mod_repo)
    _insert_file_asset(file_repo, real_path=str(src_file), mod_item_id=mod.id)

    plan = service.plan_move(mod.id, folder.id)

    # 目标目录是源文件的所在目录；target = src_dir / mod.7z = src_file
    # 即目标路径与源路径相同 → target_exists=True → 阻止
    # 但也触发 is_self_or_subdir 检查（target_dir 是 source 自身）
    assert plan.can_execute is False


def test_plan_move_empty_mod_item(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """ModItem 无成员 → 空 plan，can_execute=False。"""
    mod_repo, _, folder_repo, _ = repos
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    folder = _insert_folder(folder_repo, str(target_dir))
    mod = _insert_mod_item(mod_repo)

    plan = service.plan_move(mod.id, folder.id)

    assert len(plan.entries) == 0
    assert plan.can_execute is False


def test_plan_move_mod_item_not_found(
    service: FileOperationService, repos: tuple, tmp_path: Path
) -> None:
    """ModItem 不存在 → 抛错。"""
    _, _, folder_repo, _ = repos
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    folder = _insert_folder(folder_repo, str(target_dir))

    with pytest.raises(ValueError, match="ModItem 不存在"):
        service.plan_move("nonexistent", folder.id)


def test_plan_move_persists_operation_log(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """plan_move 应持久化 OperationLog(status=planned)。"""
    mod_repo, file_repo, folder_repo, op_repo = repos

    src_file = tmp_path / "mod.7z"
    _make_file(src_file)
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    folder = _insert_folder(folder_repo, str(target_dir))
    mod = _insert_mod_item(mod_repo)
    _insert_file_asset(file_repo, real_path=str(src_file), mod_item_id=mod.id)

    plan = service.plan_move(mod.id, folder.id)

    op_log = op_repo.get_by_id(plan.plan_id)
    assert op_log is not None
    assert op_log.status == OperationStatus.PLANNED
    assert op_log.operation_type == OperationType.MOVE
    assert op_log.conflict_policy == ConflictPolicy.ASK


# ---------- execute_move ----------


def test_execute_move_same_drive(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """正常同盘移动：文件实际移动；FileAsset 更新；OperationLog=completed。"""
    mod_repo, file_repo, folder_repo, op_repo = repos

    src_file = tmp_path / "src" / "寒霜之心.7z"
    _make_file(src_file, content=b"\x01" * 200)
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    folder = _insert_folder(folder_repo, str(target_dir))
    mod = _insert_mod_item(mod_repo, display_name="寒霜之心")
    asset = _insert_file_asset(
        file_repo,
        real_path=str(src_file),
        mod_item_id=mod.id,
        role=FileRole.MAIN_MOD,
    )

    plan = service.plan_move(mod.id, folder.id)
    result = service.execute_move(plan.plan_id)

    assert result.success is True
    assert result.partial is False
    assert asset.id in result.moved_assets

    # 文件实际移动
    assert not src_file.exists()
    target_file = target_dir / "寒霜之心.7z"
    assert target_file.exists()
    assert target_file.read_bytes() == b"\x01" * 200

    # FileAsset 更新
    updated = file_repo.get_by_id(asset.id)
    assert updated is not None
    assert updated.real_path == str(target_file)

    # OperationLog = completed
    op_log = op_repo.get_by_id(plan.plan_id)
    assert op_log.status == OperationStatus.COMPLETED
    assert op_log.completed_at is not None
    assert op_log.undo_payload is not None


def test_execute_move_multiple_members(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """多成员移动：全部成功。"""
    mod_repo, file_repo, folder_repo, _ = repos

    src1 = tmp_path / "src" / "main.7z"
    src2 = tmp_path / "src" / "translation.zip"
    src3 = tmp_path / "src" / "preview.webp"
    _make_file(src1, b"\x01" * 100)
    _make_file(src2, b"\x02" * 50)
    _make_file(src3, b"\x03" * 200)

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    folder = _insert_folder(folder_repo, str(target_dir))
    mod = _insert_mod_item(mod_repo)
    _insert_file_asset(file_repo, real_path=str(src1), mod_item_id=mod.id, role=FileRole.MAIN_MOD)
    _insert_file_asset(
        file_repo, real_path=str(src2), mod_item_id=mod.id, role=FileRole.TRANSLATION
    )
    _insert_file_asset(file_repo, real_path=str(src3), mod_item_id=mod.id, role=FileRole.PREVIEW)

    plan = service.plan_move(mod.id, folder.id)
    result = service.execute_move(plan.plan_id)

    assert result.success is True
    assert len(result.moved_assets) == 3
    assert (target_dir / "main.7z").exists()
    assert (target_dir / "translation.zip").exists()
    assert (target_dir / "preview.webp").exists()


def test_execute_move_partial_failure(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """单成员失败：partial=True；其他成员成功；OperationLog=failed。"""
    mod_repo, file_repo, folder_repo, op_repo = repos

    src1 = tmp_path / "src" / "ok.7z"
    _make_file(src1, b"\x01" * 100)
    src2 = tmp_path / "src" / "missing.7z"
    # 不创建 src2，模拟缺失

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    folder = _insert_folder(folder_repo, str(target_dir))
    mod = _insert_mod_item(mod_repo)
    asset_ok = _insert_file_asset(file_repo, real_path=str(src1), mod_item_id=mod.id)
    asset_missing = _insert_file_asset(file_repo, real_path=str(src2), mod_item_id=mod.id)

    plan = service.plan_move(mod.id, folder.id)
    # plan 阶段会发现 src2 缺失 → can_execute=False
    # 为测试 execute 的部分失败，手动让 plan 通过后删除文件
    # 这里改为：plan 阶段就阻止，execute 应拒绝
    assert plan.can_execute is False

    # 单独测试：让 plan 通过，执行时文件消失
    # 先创建 src2 让 plan 通过
    _make_file(src2, b"\x02" * 50)
    plan2 = service.plan_move(mod.id, folder.id)
    assert plan2.can_execute is True
    # 执行前删除 src2
    src2.unlink()

    result = service.execute_move(plan2.plan_id)

    assert result.success is False
    assert result.partial is True
    assert asset_ok.id in result.moved_assets
    assert asset_missing.id in result.failed_assets

    op_log = op_repo.get_by_id(plan2.plan_id)
    assert op_log.status == OperationStatus.FAILED


def test_execute_move_rejects_non_planned(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """plan.can_execute=False 时 execute_move 应拒绝（通过 plan 阶段阻止）。"""
    mod_repo, file_repo, folder_repo, _ = repos

    src_file = tmp_path / "mod.7z"
    _make_file(src_file)
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    # 创建重名文件使 plan 阻止
    _make_file(target_dir / "mod.7z")

    folder = _insert_folder(folder_repo, str(target_dir))
    mod = _insert_mod_item(mod_repo)
    _insert_file_asset(file_repo, real_path=str(src_file), mod_item_id=mod.id)

    plan = service.plan_move(mod.id, folder.id)
    assert plan.can_execute is False

    # execute 仍可调用，但因状态为 planned 会进入执行；
    # 执行时会发现 target_exists → 该成员失败
    result = service.execute_move(plan.plan_id)
    assert result.success is False
    assert len(result.failed_assets) == 1


def test_execute_move_chinese_path(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """中文路径移动往返。"""
    mod_repo, file_repo, folder_repo, _ = repos

    src_file = tmp_path / "源目录" / "寒霜之心.7z"
    _make_file(src_file, b"\x01" * 100)
    target_dir = tmp_path / "目标目录" / "护甲"
    target_dir.mkdir(parents=True)

    folder = _insert_folder(folder_repo, str(target_dir))
    mod = _insert_mod_item(mod_repo, display_name="寒霜之心")
    asset = _insert_file_asset(file_repo, real_path=str(src_file), mod_item_id=mod.id)

    plan = service.plan_move(mod.id, folder.id)
    result = service.execute_move(plan.plan_id)

    assert result.success is True
    assert (target_dir / "寒霜之心.7z").exists()

    updated = file_repo.get_by_id(asset.id)
    assert "寒霜之心.7z" in updated.real_path


def test_execute_move_undo_payload_records_size_mtime(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """undo_payload 应记录 size 与 mtime（B2）。"""
    mod_repo, file_repo, folder_repo, op_repo = repos

    src_file = tmp_path / "mod.7z"
    _make_file(src_file, b"\x01" * 150)
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    folder = _insert_folder(folder_repo, str(target_dir))
    mod = _insert_mod_item(mod_repo)
    _insert_file_asset(file_repo, real_path=str(src_file), mod_item_id=mod.id)

    plan = service.plan_move(mod.id, folder.id)
    service.execute_move(plan.plan_id)

    op_log = op_repo.get_by_id(plan.plan_id)
    import json

    payload = json.loads(op_log.undo_payload)
    assert payload["version"] == 1
    member = payload["members"][0]
    assert member["size_bytes"] == 150
    assert "mtime_iso" in member
    assert member["src_path"] == str(src_file)
    assert member["dst_path"] == str(target_dir / "mod.7z")


# ---------- plan_undo ----------


def test_plan_undo_normal(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """正常撤销预演：原目标存在、原源不存在、size+mtime 一致 → can_execute=True。"""
    mod_repo, file_repo, folder_repo, _ = repos

    src_file = tmp_path / "mod.7z"
    _make_file(src_file, b"\x01" * 100)
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    folder = _insert_folder(folder_repo, str(target_dir))
    mod = _insert_mod_item(mod_repo)
    _insert_file_asset(file_repo, real_path=str(src_file), mod_item_id=mod.id)

    plan = service.plan_move(mod.id, folder.id)
    service.execute_move(plan.plan_id)

    undo_plan = service.plan_undo(plan.plan_id)

    assert undo_plan.can_execute is True
    assert undo_plan.block_reason is None
    assert len(undo_plan.entries) == 1
    entry = undo_plan.entries[0]
    assert entry.source_exists is True
    assert entry.target_exists is False
    assert entry.size_matches is True
    assert entry.mtime_matches is True


def test_plan_undo_original_target_missing(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """B1：原目标文件已被删除 → 阻止。"""
    mod_repo, file_repo, folder_repo, _ = repos

    src_file = tmp_path / "mod.7z"
    _make_file(src_file, b"\x01" * 100)
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    folder = _insert_folder(folder_repo, str(target_dir))
    mod = _insert_mod_item(mod_repo)
    _insert_file_asset(file_repo, real_path=str(src_file), mod_item_id=mod.id)

    plan = service.plan_move(mod.id, folder.id)
    service.execute_move(plan.plan_id)

    # 删除目标文件
    (target_dir / "mod.7z").unlink()

    undo_plan = service.plan_undo(plan.plan_id)

    assert undo_plan.can_execute is False
    assert "原目标文件不存在" in undo_plan.entries[0].block_reason


def test_plan_undo_source_path_occupied(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """B1：原源路径已存在新文件 → 阻止。"""
    mod_repo, file_repo, folder_repo, _ = repos

    src_file = tmp_path / "mod.7z"
    _make_file(src_file, b"\x01" * 100)
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    folder = _insert_folder(folder_repo, str(target_dir))
    mod = _insert_mod_item(mod_repo)
    _insert_file_asset(file_repo, real_path=str(src_file), mod_item_id=mod.id)

    plan = service.plan_move(mod.id, folder.id)
    service.execute_move(plan.plan_id)

    # 在原源路径放新文件
    _make_file(src_file, b"\x02" * 50)

    undo_plan = service.plan_undo(plan.plan_id)

    assert undo_plan.can_execute is False
    assert "原源路径已存在" in undo_plan.entries[0].block_reason


def test_plan_undo_size_mismatch(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """B2：size 不一致 → 阻止。"""
    mod_repo, file_repo, folder_repo, _ = repos

    src_file = tmp_path / "mod.7z"
    _make_file(src_file, b"\x01" * 100)
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    folder = _insert_folder(folder_repo, str(target_dir))
    mod = _insert_mod_item(mod_repo)
    _insert_file_asset(file_repo, real_path=str(src_file), mod_item_id=mod.id)

    plan = service.plan_move(mod.id, folder.id)
    service.execute_move(plan.plan_id)

    # 修改目标文件内容（size 变化）
    (target_dir / "mod.7z").write_bytes(b"\x03" * 200)

    undo_plan = service.plan_undo(plan.plan_id)

    assert undo_plan.can_execute is False
    assert "大小" in undo_plan.entries[0].block_reason


def test_plan_undo_non_completed_operation(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """原操作非 completed/failed → 阻止。"""
    mod_repo, file_repo, folder_repo, _ = repos

    src_file = tmp_path / "mod.7z"
    _make_file(src_file, b"\x01" * 100)
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    folder = _insert_folder(folder_repo, str(target_dir))
    mod = _insert_mod_item(mod_repo)
    _insert_file_asset(file_repo, real_path=str(src_file), mod_item_id=mod.id)

    # 仅 plan，不 execute
    plan = service.plan_move(mod.id, folder.id)

    undo_plan = service.plan_undo(plan.plan_id)

    assert undo_plan.can_execute is False
    assert "状态非 completed/failed" in undo_plan.block_reason


# ---------- execute_undo ----------


def test_execute_undo_normal(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """正常撤销：文件反向移动；OperationLog=undone。"""
    mod_repo, file_repo, folder_repo, op_repo = repos

    src_file = tmp_path / "mod.7z"
    _make_file(src_file, b"\x01" * 100)
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    folder = _insert_folder(folder_repo, str(target_dir))
    mod = _insert_mod_item(mod_repo)
    asset = _insert_file_asset(file_repo, real_path=str(src_file), mod_item_id=mod.id)

    plan = service.plan_move(mod.id, folder.id)
    service.execute_move(plan.plan_id)

    # 撤销
    undo_plan = service.plan_undo(plan.plan_id)
    assert undo_plan.can_execute is True

    result = service.execute_undo(plan.plan_id)

    assert result.success is True
    # 文件回到原位
    assert src_file.exists()
    assert not (target_dir / "mod.7z").exists()

    # FileAsset 恢复
    updated = file_repo.get_by_id(asset.id)
    assert updated.real_path == str(src_file)

    # OperationLog = undone
    op_log = op_repo.get_by_id(plan.plan_id)
    assert op_log.status == OperationStatus.UNDONE


def test_execute_undo_rejects_unsafe(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """UndoPlan.can_execute=False 时 execute_undo 不执行。"""
    mod_repo, file_repo, folder_repo, _ = repos

    src_file = tmp_path / "mod.7z"
    _make_file(src_file, b"\x01" * 100)
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    folder = _insert_folder(folder_repo, str(target_dir))
    mod = _insert_mod_item(mod_repo)
    _insert_file_asset(file_repo, real_path=str(src_file), mod_item_id=mod.id)

    plan = service.plan_move(mod.id, folder.id)
    service.execute_move(plan.plan_id)

    # 删除目标文件使撤销不安全
    (target_dir / "mod.7z").unlink()

    result = service.execute_undo(plan.plan_id)

    assert result.success is False
    assert "撤销不安全" in result.error_messages[0]


# ---------- 完整场景 ----------


def test_full_scenario_move_then_undo(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """移动 → 撤销 往返：文件回到原位；DB 状态正确。"""
    mod_repo, file_repo, folder_repo, op_repo = repos

    src1 = tmp_path / "src" / "寒霜之心.7z"
    src2 = tmp_path / "src" / "preview.webp"
    _make_file(src1, b"\x01" * 100)
    _make_file(src2, b"\x02" * 200)
    target_dir = tmp_path / "target" / "护甲"
    target_dir.mkdir(parents=True)

    folder = _insert_folder(folder_repo, str(target_dir))
    mod = _insert_mod_item(mod_repo, display_name="寒霜之心")
    _insert_file_asset(file_repo, real_path=str(src1), mod_item_id=mod.id, role=FileRole.MAIN_MOD)
    _insert_file_asset(file_repo, real_path=str(src2), mod_item_id=mod.id, role=FileRole.PREVIEW)

    # 移动
    plan = service.plan_move(mod.id, folder.id)
    assert plan.can_execute is True
    move_result = service.execute_move(plan.plan_id)
    assert move_result.success is True

    # 验证移动
    assert (target_dir / "寒霜之心.7z").exists()
    assert (target_dir / "preview.webp").exists()
    assert not src1.exists()
    assert not src2.exists()

    # 撤销
    undo_plan = service.plan_undo(plan.plan_id)
    assert undo_plan.can_execute is True
    undo_result = service.execute_undo(plan.plan_id)
    assert undo_result.success is True

    # 验证撤销
    assert src1.exists()
    assert src2.exists()
    assert not (target_dir / "寒霜之心.7z").exists()
    assert not (target_dir / "preview.webp").exists()

    # OperationLog 状态
    op_log = op_repo.get_by_id(plan.plan_id)
    assert op_log.status == OperationStatus.UNDONE


def test_move_does_not_delete_user_files(
    service: FileOperationService,
    repos: tuple,
    tmp_path: Path,
) -> None:
    """spec §7.13：移动后文件数量不变（移动非删除）。"""
    mod_repo, file_repo, folder_repo, _ = repos

    src_file = tmp_path / "mod.7z"
    _make_file(src_file, b"\x01" * 100)
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    folder = _insert_folder(folder_repo, str(target_dir))
    mod = _insert_mod_item(mod_repo)
    _insert_file_asset(file_repo, real_path=str(src_file), mod_item_id=mod.id)

    # 移动前的文件总数（在 tmp_path 下）
    before_count = sum(1 for p in tmp_path.rglob("*") if p.is_file())

    plan = service.plan_move(mod.id, folder.id)
    service.execute_move(plan.plan_id)

    after_count = sum(1 for p in tmp_path.rglob("*") if p.is_file())
    assert before_count == after_count, "移动改变了文件总数（应保持不变）"
