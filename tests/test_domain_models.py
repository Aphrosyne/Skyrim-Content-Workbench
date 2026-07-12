"""领域模型验证测试。"""

from __future__ import annotations

import pytest

pytest.skip(
    "方向 C 重建（Task 1）：domain.models 将在 Task 2 重写为 ContentUnit 等新实体后重新启用",
    allow_module_level=True,
)

from domain.models import (
    AssetKind,
    ConflictPolicy,
    FileAsset,
    FileRole,
    FolderNode,
    ModItem,
    OperationLog,
    OperationStatus,
    OperationType,
)


def test_mod_item_requires_id() -> None:
    with pytest.raises(ValueError, match="id"):
        ModItem(id="", created_at="2026-07-07T00:00:00Z", updated_at="2026-07-07T00:00:00Z")


def test_mod_item_requires_timestamps() -> None:
    with pytest.raises(ValueError, match="created_at"):
        ModItem(id="x", created_at="", updated_at="2026-07-07T00:00:00Z")


def test_mod_item_default_tags_empty_set() -> None:
    item = ModItem(id="x", created_at="t", updated_at="t")
    assert item.tags == set()
    assert item.display_name is None


def test_mod_item_rejects_non_set_tags() -> None:
    with pytest.raises(TypeError, match="tags"):
        ModItem(  # type: ignore[arg-type]
            id="x", created_at="t", updated_at="t", tags=["a", "b"]
        )


def test_file_asset_requires_path_key() -> None:
    with pytest.raises(ValueError, match="path_key"):
        FileAsset(
            id="x",
            real_path="D:/test.7z",
            path_key="",
            filename="test.7z",
            asset_kind=AssetKind.FILE,
            role=FileRole.MAIN_MOD,
            size_bytes=100,
            modified_at="t",
            imported_at="t",
        )


def test_file_asset_rejects_negative_size() -> None:
    with pytest.raises(ValueError, match="size_bytes"):
        FileAsset(
            id="x",
            real_path="D:/test.7z",
            path_key="d:/test.7z",
            filename="test.7z",
            asset_kind=AssetKind.FILE,
            role=FileRole.MAIN_MOD,
            size_bytes=-1,
            modified_at="t",
            imported_at="t",
        )


def test_file_asset_rejects_non_enum_role() -> None:
    with pytest.raises(TypeError, match="role"):
        FileAsset(  # type: ignore[arg-type]
            id="x",
            real_path="D:/test.7z",
            path_key="d:/test.7z",
            filename="test.7z",
            asset_kind=AssetKind.FILE,
            role="main_mod",
            size_bytes=100,
            modified_at="t",
            imported_at="t",
        )


def test_file_asset_default_extension_empty() -> None:
    asset = FileAsset(
        id="x",
        real_path="D:/README",
        path_key="d:/readme",
        filename="README",
        asset_kind=AssetKind.FILE,
        role=FileRole.README,
        size_bytes=10,
        modified_at="t",
        imported_at="t",
    )
    assert asset.extension == ""
    assert asset.mod_item_id is None


def test_folder_node_default_is_managed_root_false() -> None:
    node = FolderNode(
        id="x",
        real_path="D:/Mods",
        path_key="d:/mods",
        created_at="t",
        updated_at="t",
    )
    assert node.is_managed_root is False
    assert node.parent_id is None


def test_folder_node_rejects_empty_real_path() -> None:
    with pytest.raises(ValueError, match="real_path"):
        FolderNode(
            id="x",
            real_path="",
            path_key="d:/mods",
            created_at="t",
            updated_at="t",
        )


def test_operation_log_defaults() -> None:
    log = OperationLog(
        id="x",
        operation_type=OperationType.MOVE,
        status=OperationStatus.PLANNED,
        conflict_policy=ConflictPolicy.ASK,
        created_at="t",
    )
    assert log.affected_asset_ids == []
    assert log.source_paths == []
    assert log.target_paths == []
    assert log.completed_at is None
    assert log.undo_payload is None
    assert log.error_message is None


def test_operation_log_rejects_non_enum_status() -> None:
    with pytest.raises(TypeError, match="status"):
        OperationLog(  # type: ignore[arg-type]
            id="x",
            operation_type=OperationType.MOVE,
            status="planned",
            conflict_policy=ConflictPolicy.ASK,
            created_at="t",
        )


def test_operation_log_rejects_non_list_asset_ids() -> None:
    with pytest.raises(TypeError, match="affected_asset_ids"):
        OperationLog(  # type: ignore[arg-type]
            id="x",
            operation_type=OperationType.MOVE,
            status=OperationStatus.PLANNED,
            conflict_policy=ConflictPolicy.ASK,
            created_at="t",
            affected_asset_ids="not-a-list",
        )


def test_enums_have_expected_values() -> None:
    assert AssetKind.FILE.value == "file"
    assert FileRole.MAIN_MOD.value == "main_mod"
    assert OperationStatus.PLANNED.value == "planned"
    assert ConflictPolicy.ASK.value == "ask"
    assert OperationType.MOVE.value == "move"
