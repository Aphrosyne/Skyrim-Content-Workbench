"""ModAssemblyService 测试。

所有测试通过 Repository 直接在 DB 中构造 FileAsset，
不创建实际文件，不访问文件系统。
"""

from __future__ import annotations

import sqlite3
import uuid

import pytest

from application.errors import (
    DuplicateMemberError,
    FileAssetNotFoundError,
    MemberLimitError,
    ModItemNotFoundError,
)
from application.mod_assembly_service import ModAssemblyService
from domain.models import AssetKind, FileAsset, FileRole
from infrastructure.repositories.file_asset import FileAssetRepository
from infrastructure.repositories.mod_item import ModItemRepository

# ---------- 固定时间 / UUID provider ----------


def _fixed_now() -> str:
    return "2026-07-07T00:00:00Z"


def _sequential_uuid() -> str:
    return str(uuid.uuid4())


# ---------- 辅助：构造并插入 FileAsset ----------


def _insert_file_asset(
    repo: FileAssetRepository,
    asset_id: str | None = None,
    real_path: str = "D:/Mods/test.7z",
    path_key: str | None = None,
    filename: str = "test.7z",
    extension: str = ".7z",
    asset_kind: AssetKind = AssetKind.FILE,
    role: FileRole = FileRole.UNKNOWN,
    size_bytes: int = 100,
    mod_item_id: str | None = None,
) -> FileAsset:
    asset = FileAsset(
        id=asset_id or str(uuid.uuid4()),
        mod_item_id=mod_item_id,
        real_path=real_path,
        path_key=path_key or real_path.lower(),
        filename=filename,
        extension=extension,
        asset_kind=asset_kind,
        role=role,
        size_bytes=size_bytes,
        modified_at="2026-07-07T00:00:00Z",
        imported_at="2026-07-07T00:00:00Z",
    )
    return repo.create(asset)


@pytest.fixture
def service(db_connection: sqlite3.Connection) -> ModAssemblyService:
    mod_repo = ModItemRepository(db_connection)
    file_repo = FileAssetRepository(db_connection)
    return ModAssemblyService(
        mod_repo,
        file_repo,
        now_provider=_fixed_now,
        uuid_provider=_sequential_uuid,
    )


@pytest.fixture
def file_repo(db_connection: sqlite3.Connection) -> FileAssetRepository:
    return FileAssetRepository(db_connection)


@pytest.fixture
def mod_repo(db_connection: sqlite3.Connection) -> ModItemRepository:
    return ModItemRepository(db_connection)


# ---------- 创建 ModItem ----------


def test_create_mod_item_empty(service: ModAssemblyService) -> None:
    """创建空 ModItem，所有可选字段为 None。"""
    item = service.create_mod_item()

    assert item.id
    assert item.display_name is None
    assert item.description is None
    assert item.source_url is None
    assert item.category_folder_id is None
    assert item.tags == set()
    assert item.cover_asset_id is None
    assert item.created_at == "2026-07-07T00:00:00Z"


def test_create_mod_item_with_chinese_fields(
    service: ModAssemblyService,
) -> None:
    """创建带中文显示名、中文 description、中文 tags 的 ModItem。"""
    item = service.create_mod_item(
        display_name="寒霜之心",
        description="冰霜抗性重型护甲",
        source_url="https://example.com/mods/frost",
        tags={"护甲", "冰霜"},
    )

    assert item.display_name == "寒霜之心"
    assert item.description == "冰霜抗性重型护甲"
    assert item.tags == {"护甲", "冰霜"}

    # 通过 get 验证持久化
    fetched = service.get_mod_item(item.id)
    assert fetched.display_name == "寒霜之心"
    assert fetched.description == "冰霜抗性重型护甲"
    assert fetched.tags == {"护甲", "冰霜"}


# ---------- 成员关联 ----------


def test_add_single_member(service: ModAssemblyService, file_repo: FileAssetRepository) -> None:
    """关联 1 个成员（main_mod）。"""
    mod = service.create_mod_item(display_name="测试 Mod")
    asset = _insert_file_asset(file_repo, real_path="D:/main.7z")

    added = service.add_member(mod.id, asset.id, FileRole.MAIN_MOD)

    assert added.mod_item_id == mod.id
    assert added.role == FileRole.MAIN_MOD


def test_add_multiple_members_main_translation_preview(
    service: ModAssemblyService, file_repo: FileAssetRepository
) -> None:
    """roadmap 验收场景：本体 + 汉化包 + WEBP 预览图。"""
    mod = service.create_mod_item(display_name="寒霜之心")

    main = _insert_file_asset(file_repo, real_path="D:/寒霜之心.7z", filename="寒霜之心.7z")
    translation = _insert_file_asset(
        file_repo, real_path="D:/寒霜之心-汉化.zip", filename="寒霜之心-汉化.zip"
    )
    preview = _insert_file_asset(
        file_repo,
        real_path="D:/preview.webp",
        filename="preview.webp",
        extension=".webp",
    )

    service.add_member(mod.id, main.id, FileRole.MAIN_MOD)
    service.add_member(mod.id, translation.id, FileRole.TRANSLATION)
    service.add_member(mod.id, preview.id, FileRole.PREVIEW)

    members = service.get_members(mod.id)
    assert len(members) == 3

    roles = {m.role for m in members}
    assert roles == {FileRole.MAIN_MOD, FileRole.TRANSLATION, FileRole.PREVIEW}


def test_add_member_mod_item_not_found(
    service: ModAssemblyService, file_repo: FileAssetRepository
) -> None:
    """关联到不存在的 ModItem。"""
    asset = _insert_file_asset(file_repo)
    with pytest.raises(ModItemNotFoundError):
        service.add_member("nonexistent-mod", asset.id, FileRole.MAIN_MOD)


def test_add_member_file_asset_not_found(
    service: ModAssemblyService,
) -> None:
    """关联不存在的 FileAsset。"""
    mod = service.create_mod_item()
    with pytest.raises(FileAssetNotFoundError):
        service.add_member(mod.id, "nonexistent-asset", FileRole.MAIN_MOD)


def test_add_duplicate_member_raises(
    service: ModAssemblyService, file_repo: FileAssetRepository
) -> None:
    """同一 FileAsset 重复关联到同一 ModItem。"""
    mod = service.create_mod_item()
    asset = _insert_file_asset(file_repo)

    service.add_member(mod.id, asset.id, FileRole.MAIN_MOD)
    with pytest.raises(DuplicateMemberError):
        service.add_member(mod.id, asset.id, FileRole.TRANSLATION)


def test_add_second_main_mod_raises(
    service: ModAssemblyService, file_repo: FileAssetRepository
) -> None:
    """MAIN_MOD 已存在时再添加 MAIN_MOD。"""
    mod = service.create_mod_item()
    a1 = _insert_file_asset(file_repo, real_path="D:/a1.7z")
    a2 = _insert_file_asset(file_repo, real_path="D:/a2.7z")

    service.add_member(mod.id, a1.id, FileRole.MAIN_MOD)
    with pytest.raises(MemberLimitError, match="main_mod"):
        service.add_member(mod.id, a2.id, FileRole.MAIN_MOD)


def test_add_second_readme_raises(
    service: ModAssemblyService, file_repo: FileAssetRepository
) -> None:
    """README 已存在时再添加 README。"""
    mod = service.create_mod_item()
    a1 = _insert_file_asset(file_repo, real_path="D:/readme1.txt")
    a2 = _insert_file_asset(file_repo, real_path="D:/readme2.txt")

    service.add_member(mod.id, a1.id, FileRole.README)
    with pytest.raises(MemberLimitError, match="readme"):
        service.add_member(mod.id, a2.id, FileRole.README)


def test_add_multiple_translation_allowed(
    service: ModAssemblyService, file_repo: FileAssetRepository
) -> None:
    """TRANSLATION 不限制数量。"""
    mod = service.create_mod_item()
    a1 = _insert_file_asset(file_repo, real_path="D:/trans1.zip")
    a2 = _insert_file_asset(file_repo, real_path="D:/trans2.zip")

    service.add_member(mod.id, a1.id, FileRole.TRANSLATION)
    service.add_member(mod.id, a2.id, FileRole.TRANSLATION)

    members = service.get_members(mod.id)
    assert len(members) == 2


def test_add_multiple_preview_allowed(
    service: ModAssemblyService, file_repo: FileAssetRepository
) -> None:
    """PREVIEW 不限制数量。"""
    mod = service.create_mod_item()
    a1 = _insert_file_asset(file_repo, real_path="D:/p1.webp")
    a2 = _insert_file_asset(file_repo, real_path="D:/p2.webp")

    service.add_member(mod.id, a1.id, FileRole.PREVIEW)
    service.add_member(mod.id, a2.id, FileRole.PREVIEW)

    members = service.get_members(mod.id)
    assert len(members) == 2


# ---------- set_member_role ----------


def test_set_member_role(service: ModAssemblyService, file_repo: FileAssetRepository) -> None:
    """更新已关联成员的角色。"""
    mod = service.create_mod_item()
    asset = _insert_file_asset(file_repo)

    service.add_member(mod.id, asset.id, FileRole.UNKNOWN)
    updated = service.set_member_role(mod.id, asset.id, FileRole.OPTIONAL_FILE)

    assert updated.role == FileRole.OPTIONAL_FILE


def test_set_member_role_to_main_when_main_exists_raises(
    service: ModAssemblyService, file_repo: FileAssetRepository
) -> None:
    """已有 MAIN_MOD 时，将其他成员改为 MAIN_MOD 应被拒绝。"""
    mod = service.create_mod_item()
    main = _insert_file_asset(file_repo, real_path="D:/main.7z")
    other = _insert_file_asset(file_repo, real_path="D:/other.7z")

    service.add_member(mod.id, main.id, FileRole.MAIN_MOD)
    service.add_member(mod.id, other.id, FileRole.UNKNOWN)

    with pytest.raises(MemberLimitError, match="main_mod"):
        service.set_member_role(mod.id, other.id, FileRole.MAIN_MOD)


def test_set_member_role_same_role_noop(
    service: ModAssemblyService, file_repo: FileAssetRepository
) -> None:
    """角色未变时不报错。"""
    mod = service.create_mod_item()
    asset = _insert_file_asset(file_repo)

    service.add_member(mod.id, asset.id, FileRole.MAIN_MOD)
    result = service.set_member_role(mod.id, asset.id, FileRole.MAIN_MOD)
    assert result.role == FileRole.MAIN_MOD


# ---------- set_cover ----------


def test_set_cover(service: ModAssemblyService, file_repo: FileAssetRepository) -> None:
    """设置封面，要求成员为 PREVIEW 角色。"""
    mod = service.create_mod_item()
    preview = _insert_file_asset(file_repo, real_path="D:/preview.webp", filename="preview.webp")

    service.add_member(mod.id, preview.id, FileRole.PREVIEW)
    updated_mod = service.set_cover(mod.id, preview.id)

    assert updated_mod.cover_asset_id == preview.id


def test_set_cover_non_preview_raises(
    service: ModAssemblyService, file_repo: FileAssetRepository
) -> None:
    """非 PREVIEW 角色的成员设为 cover 应被拒绝。"""
    mod = service.create_mod_item()
    main = _insert_file_asset(file_repo, real_path="D:/main.7z")

    service.add_member(mod.id, main.id, FileRole.MAIN_MOD)
    with pytest.raises(ValueError, match="PREVIEW"):
        service.set_cover(mod.id, main.id)


def test_set_cover_unassociated_asset_raises(
    service: ModAssemblyService, file_repo: FileAssetRepository
) -> None:
    """未关联的 FileAsset 不能设为 cover。"""
    mod = service.create_mod_item()
    asset = _insert_file_asset(file_repo)

    with pytest.raises(FileAssetNotFoundError):
        service.set_cover(mod.id, asset.id)


# ---------- 查询 ----------


def test_get_mod_item_not_found(service: ModAssemblyService) -> None:
    with pytest.raises(ModItemNotFoundError):
        service.get_mod_item("nonexistent")


def test_get_members_mod_item_not_found(service: ModAssemblyService) -> None:
    with pytest.raises(ModItemNotFoundError):
        service.get_members("nonexistent")


def test_get_mod_item_with_members(
    service: ModAssemblyService, file_repo: FileAssetRepository
) -> None:
    """返回 ModItem 及其成员列表。"""
    mod = service.create_mod_item(display_name="测试")
    a1 = _insert_file_asset(file_repo, real_path="D:/a1.7z")
    a2 = _insert_file_asset(file_repo, real_path="D:/a2.7z")

    service.add_member(mod.id, a1.id, FileRole.MAIN_MOD)
    service.add_member(mod.id, a2.id, FileRole.TRANSLATION)

    item, members = service.get_mod_item_with_members(mod.id)

    assert item.id == mod.id
    assert item.display_name == "测试"
    assert len(members) == 2


def test_list_mod_items(
    service: ModAssemblyService,
) -> None:
    """返回全部 ModItem。"""
    service.create_mod_item(display_name="Mod 1")
    service.create_mod_item(display_name="Mod 2")

    items = service.list_mod_items()
    assert len(items) == 2


def test_list_unassociated_assets(
    service: ModAssemblyService,
    file_repo: FileAssetRepository,
) -> None:
    """list_unassociated_assets 只返回 mod_item_id 为 None 的素材。

    阶段 2 Task 3 回归测试：UI 素材池数据源。
    """
    mod = service.create_mod_item(display_name="测试")

    # 3 个未关联 + 2 个已关联
    _insert_file_asset(file_repo, asset_id="a1", real_path="D:/A.7z", filename="A.7z")
    _insert_file_asset(file_repo, asset_id="a2", real_path="D:/B.zip", filename="B.zip")
    _insert_file_asset(file_repo, asset_id="a3", real_path="D:/C.webp", filename="C.webp")
    _insert_file_asset(
        file_repo,
        asset_id="a4",
        real_path="D:/D.7z",
        filename="D.7z",
        mod_item_id=mod.id,
    )
    _insert_file_asset(
        file_repo,
        asset_id="a5",
        real_path="D:/E.txt",
        filename="E.txt",
        mod_item_id=mod.id,
    )

    unassociated = service.list_unassociated_assets()
    assert len(unassociated) == 3
    ids = {a.id for a in unassociated}
    assert ids == {"a1", "a2", "a3"}


def test_list_unassociated_assets_chinese(
    service: ModAssemblyService,
    file_repo: FileAssetRepository,
) -> None:
    """中文名素材正确返回。"""
    _insert_file_asset(
        file_repo,
        asset_id="cn1",
        real_path="D:/Mods/寒霜之心.7z",
        filename="寒霜之心.7z",
    )
    _insert_file_asset(
        file_repo,
        asset_id="cn2",
        real_path="D:/Mods/汉化包.zip",
        filename="汉化包.zip",
    )

    unassociated = service.list_unassociated_assets()
    assert len(unassociated) == 2
    names = {a.filename for a in unassociated}
    assert "寒霜之心.7z" in names
    assert "汉化包.zip" in names


def test_list_unassociated_assets_folder_kind(
    service: ModAssemblyService,
    file_repo: FileAssetRepository,
) -> None:
    """文件夹型素材正确返回。"""
    _insert_file_asset(
        file_repo,
        asset_id="folder1",
        real_path="D:/Mods/护甲包",
        filename="护甲包",
        extension="",
        asset_kind=AssetKind.FOLDER,
    )

    unassociated = service.list_unassociated_assets()
    assert len(unassociated) == 1
    assert unassociated[0].asset_kind == AssetKind.FOLDER


def test_get_members_empty(
    service: ModAssemblyService,
) -> None:
    """无成员的 ModItem 返回空列表。"""
    mod = service.create_mod_item()
    members = service.get_members(mod.id)
    assert members == []


# ---------- update_mod_item ----------


def test_update_mod_item_fields(
    service: ModAssemblyService,
) -> None:
    """更新各字段。"""
    mod = service.create_mod_item(display_name="旧名")

    updated = service.update_mod_item(
        mod.id,
        display_name="新名",
        description="新说明",
        source_url="https://example.com",
        tags={"a", "b"},
    )

    assert updated.display_name == "新名"
    assert updated.description == "新说明"
    assert updated.source_url == "https://example.com"
    assert updated.tags == {"a", "b"}


def test_update_mod_item_partial(
    service: ModAssemblyService,
) -> None:
    """仅更新部分字段。"""
    mod = service.create_mod_item(display_name="原名", description="原说明", tags={"x"})

    updated = service.update_mod_item(mod.id, display_name="新名")

    assert updated.display_name == "新名"
    assert updated.description == "原说明"
    assert updated.tags == {"x"}


def test_update_mod_item_chinese(
    service: ModAssemblyService,
) -> None:
    """更新中文显示名与用途说明。"""
    mod = service.create_mod_item()

    updated = service.update_mod_item(
        mod.id,
        display_name="寒霜之心",
        description="冰霜抗性重型护甲",
    )

    assert updated.display_name == "寒霜之心"
    assert updated.description == "冰霜抗性重型护甲"

    # 往返验证
    fetched = service.get_mod_item(mod.id)
    assert fetched.display_name == "寒霜之心"
    assert fetched.description == "冰霜抗性重型护甲"


def test_update_mod_item_not_found(
    service: ModAssemblyService,
) -> None:
    with pytest.raises(ModItemNotFoundError):
        service.update_mod_item("nonexistent", display_name="x")


def test_update_mod_item_tags_not_set_raises(
    service: ModAssemblyService,
) -> None:
    """tags 必须是 set。"""
    mod = service.create_mod_item()
    with pytest.raises(TypeError, match="tags"):
        service.update_mod_item(mod.id, tags=["a", "b"])  # type: ignore[arg-type]


# ---------- remove_member ----------


def test_remove_member(service: ModAssemblyService, file_repo: FileAssetRepository) -> None:
    """解除成员关联，mod_item_id=None，role=UNKNOWN。"""
    mod = service.create_mod_item()
    asset = _insert_file_asset(file_repo)

    service.add_member(mod.id, asset.id, FileRole.MAIN_MOD)
    removed = service.remove_member(mod.id, asset.id)

    assert removed.mod_item_id is None
    assert removed.role == FileRole.UNKNOWN

    # ModItem 不应有成员
    members = service.get_members(mod.id)
    assert len(members) == 0


def test_remove_member_clears_cover(
    service: ModAssemblyService, file_repo: FileAssetRepository
) -> None:
    """解除的是 cover 成员时，cover_asset_id 同步清除。"""
    mod = service.create_mod_item()
    preview = _insert_file_asset(file_repo, real_path="D:/preview.webp", filename="preview.webp")

    service.add_member(mod.id, preview.id, FileRole.PREVIEW)
    service.set_cover(mod.id, preview.id)

    # 确认 cover 已设置
    assert service.get_mod_item(mod.id).cover_asset_id == preview.id

    service.remove_member(mod.id, preview.id)

    # cover 应被清除
    updated_mod = service.get_mod_item(mod.id)
    assert updated_mod.cover_asset_id is None


def test_remove_member_not_a_member_raises(
    service: ModAssemblyService, file_repo: FileAssetRepository
) -> None:
    """不存在的成员（未关联）应抛错。"""
    mod = service.create_mod_item()
    asset = _insert_file_asset(file_repo)

    with pytest.raises(FileAssetNotFoundError):
        service.remove_member(mod.id, asset.id)


def test_remove_member_then_re_add_allowed(
    service: ModAssemblyService, file_repo: FileAssetRepository
) -> None:
    """解除后可重新关联。"""
    mod = service.create_mod_item()
    asset = _insert_file_asset(file_repo)

    service.add_member(mod.id, asset.id, FileRole.MAIN_MOD)
    service.remove_member(mod.id, asset.id)
    # 重新关联应成功
    re_added = service.add_member(mod.id, asset.id, FileRole.MAIN_MOD)
    assert re_added.mod_item_id == mod.id


# ---------- 完整场景：roadmap 验收 ----------


def test_full_scenario_main_translation_preview_with_cover(
    service: ModAssemblyService, file_repo: FileAssetRepository
) -> None:
    """完整场景：本体 + 汉化包 + WEBP 预览图 + 封面 + 中文显示名。"""
    # 创建 ModItem
    mod = service.create_mod_item(
        display_name="寒霜之心",
        description="冰霜抗性重型护甲",
        tags={"护甲", "冰霜"},
    )

    # 准备素材
    main = _insert_file_asset(file_repo, real_path="D:/寒霜之心.7z", filename="寒霜之心.7z")
    translation = _insert_file_asset(
        file_repo, real_path="D:/寒霜之心-汉化.zip", filename="寒霜之心-汉化.zip"
    )
    preview = _insert_file_asset(
        file_repo,
        real_path="D:/preview.webp",
        filename="preview.webp",
        extension=".webp",
    )

    # 关联成员
    service.add_member(mod.id, main.id, FileRole.MAIN_MOD)
    service.add_member(mod.id, translation.id, FileRole.TRANSLATION)
    service.add_member(mod.id, preview.id, FileRole.PREVIEW)

    # 设置封面
    service.set_cover(mod.id, preview.id)

    # 查询验证
    item, members = service.get_mod_item_with_members(mod.id)
    assert item.display_name == "寒霜之心"
    assert item.description == "冰霜抗性重型护甲"
    assert item.tags == {"护甲", "冰霜"}
    assert item.cover_asset_id == preview.id
    assert len(members) == 3

    roles = {m.role for m in members}
    assert roles == {FileRole.MAIN_MOD, FileRole.TRANSLATION, FileRole.PREVIEW}

    # 验证中文路径往返
    main_member = next(m for m in members if m.role == FileRole.MAIN_MOD)
    assert "寒霜之心.7z" in main_member.real_path
