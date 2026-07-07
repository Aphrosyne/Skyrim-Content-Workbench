"""FileAssetRepository 测试。"""

from __future__ import annotations

import sqlite3

import pytest

from domain.models import AssetKind, FileAsset, FileRole, ModItem
from infrastructure.repositories.errors import ConstraintViolationError, NotFoundError
from infrastructure.repositories.file_asset import FileAssetRepository
from infrastructure.repositories.mod_item import ModItemRepository


def _make_asset(
    asset_id: str = "asset-1",
    real_path: str = "D:/Mods/Armor/example.7z",
    path_key: str = "d:/mods/armor/example.7z",
    mod_item_id: str | None = None,
    role: FileRole = FileRole.MAIN_MOD,
) -> FileAsset:
    return FileAsset(
        id=asset_id,
        mod_item_id=mod_item_id,
        real_path=real_path,
        path_key=path_key,
        filename="example.7z",
        extension=".7z",
        asset_kind=AssetKind.FILE,
        role=role,
        size_bytes=1024,
        modified_at="2026-07-07T00:00:00Z",
        imported_at="2026-07-07T00:00:00Z",
    )


def test_create_and_get(db_connection: sqlite3.Connection) -> None:
    repo = FileAssetRepository(db_connection)
    asset = _make_asset()
    created = repo.create(asset)
    assert created.id == "asset-1"
    assert created.real_path == "D:/Mods/Armor/example.7z"
    assert created.path_key == "d:/mods/armor/example.7z"
    assert created.asset_kind == AssetKind.FILE
    assert created.role == FileRole.MAIN_MOD

    fetched = repo.get_by_id("asset-1")
    assert fetched is not None
    assert fetched.filename == "example.7z"
    assert fetched.extension == ".7z"
    assert fetched.size_bytes == 1024


def test_get_by_id_not_found(db_connection: sqlite3.Connection) -> None:
    repo = FileAssetRepository(db_connection)
    assert repo.get_by_id("nonexistent") is None


def test_path_key_unique(db_connection: sqlite3.Connection) -> None:
    repo = FileAssetRepository(db_connection)
    repo.create(_make_asset(asset_id="a1"))
    with pytest.raises(ConstraintViolationError):
        repo.create(_make_asset(asset_id="a2"))  # 同 path_key


def test_different_path_keys_allowed(db_connection: sqlite3.Connection) -> None:
    repo = FileAssetRepository(db_connection)
    repo.create(_make_asset(asset_id="a1", path_key="d:/mods/armor/a.7z"))
    repo.create(_make_asset(asset_id="a2", path_key="d:/mods/armor/b.7z"))
    assert len(repo.list_unassociated()) == 2


def test_list_by_mod_item(db_connection: sqlite3.Connection) -> None:
    # 先建一个 ModItem
    mod_repo = ModItemRepository(db_connection)
    mod_repo.create(
        ModItem(
            id="mod-1",
            created_at="2026-07-07T00:00:00Z",
            updated_at="2026-07-07T00:00:00Z",
        )
    )

    asset_repo = FileAssetRepository(db_connection)
    # 3 个成员：本体 + 汉化 + 预览
    asset_repo.create(
        _make_asset(
            asset_id="main",
            path_key="d:/mods/main.7z",
            real_path="D:/Mods/main.7z",
            mod_item_id="mod-1",
            role=FileRole.MAIN_MOD,
        )
    )
    asset_repo.create(
        _make_asset(
            asset_id="trans",
            path_key="d:/mods/trans.7z",
            real_path="D:/Mods/trans.7z",
            mod_item_id="mod-1",
            role=FileRole.TRANSLATION,
        )
    )
    asset_repo.create(
        _make_asset(
            asset_id="preview",
            path_key="d:/mods/preview.webp",
            real_path="D:/Mods/preview.webp",
            mod_item_id="mod-1",
            role=FileRole.PREVIEW,
        )
    )

    members = asset_repo.list_by_mod_item("mod-1")
    assert len(members) == 3
    roles = {m.role for m in members}
    assert roles == {FileRole.MAIN_MOD, FileRole.TRANSLATION, FileRole.PREVIEW}


def test_list_unassociated(db_connection: sqlite3.Connection) -> None:
    repo = FileAssetRepository(db_connection)
    repo.create(_make_asset(asset_id="a1", path_key="d:/a1.7z"))
    repo.create(_make_asset(asset_id="a2", path_key="d:/a2.7z"))
    assert len(repo.list_unassociated()) == 2


def test_associate_to_mod_item_via_update(
    db_connection: sqlite3.Connection,
) -> None:
    mod_repo = ModItemRepository(db_connection)
    mod_repo.create(
        ModItem(
            id="mod-1",
            created_at="2026-07-07T00:00:00Z",
            updated_at="2026-07-07T00:00:00Z",
        )
    )

    asset_repo = FileAssetRepository(db_connection)
    asset = _make_asset()
    asset_repo.create(asset)

    asset.mod_item_id = "mod-1"
    updated = asset_repo.update(asset)
    assert updated.mod_item_id == "mod-1"
    assert len(asset_repo.list_by_mod_item("mod-1")) == 1
    assert len(asset_repo.list_unassociated()) == 0


def test_update_not_found_raises(db_connection: sqlite3.Connection) -> None:
    repo = FileAssetRepository(db_connection)
    with pytest.raises(NotFoundError):
        repo.update(_make_asset(asset_id="nonexistent"))


def test_chinese_path_roundtrip(db_connection: sqlite3.Connection) -> None:
    repo = FileAssetRepository(db_connection)
    asset = _make_asset(
        asset_id="cn-1",
        real_path="D:/Mods/护甲/测试/example.7z",
        path_key="d:/mods/护甲/测试/example.7z",
    )
    repo.create(asset)
    fetched = repo.get_by_id("cn-1")
    assert fetched is not None
    assert fetched.real_path == "D:/Mods/护甲/测试/example.7z"
    assert fetched.path_key == "d:/mods/护甲/测试/example.7z"


def test_folder_asset_kind(db_connection: sqlite3.Connection) -> None:
    repo = FileAssetRepository(db_connection)
    asset = FileAsset(
        id="folder-1",
        real_path="D:/Mods/ArmorPack",
        path_key="d:/mods/armorpack",
        filename="ArmorPack",
        extension="",
        asset_kind=AssetKind.FOLDER,
        role=FileRole.MAIN_MOD,
        size_bytes=0,
        modified_at="2026-07-07T00:00:00Z",
        imported_at="2026-07-07T00:00:00Z",
    )
    repo.create(asset)
    fetched = repo.get_by_id("folder-1")
    assert fetched is not None
    assert fetched.asset_kind == AssetKind.FOLDER
    assert fetched.extension == ""


def test_empty_extension_roundtrip(db_connection: sqlite3.Connection) -> None:
    """无扩展名文件 extension 存为空字符串。"""
    repo = FileAssetRepository(db_connection)
    asset = FileAsset(
        id="noext",
        real_path="D:/README",
        path_key="d:/readme",
        filename="README",
        extension="",
        asset_kind=AssetKind.FILE,
        role=FileRole.README,
        size_bytes=10,
        modified_at="2026-07-07T00:00:00Z",
        imported_at="2026-07-07T00:00:00Z",
    )
    repo.create(asset)
    fetched = repo.get_by_id("noext")
    assert fetched is not None
    assert fetched.extension == ""
