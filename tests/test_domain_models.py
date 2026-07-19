"""领域模型测试。

覆盖方向 C 的新实体：ContentUnit / TagCategory / Tag / OperationHistory /
FolderCache / ManagedRoot。重点测试 __post_init__ 校验逻辑。
"""

from __future__ import annotations

import pytest

from domain.models import (
    ContentUnit,
    FolderCache,
    ManagedRoot,
    OperationHistory,
    Tag,
    TagCategory,
)

# === ContentUnit ===


class TestContentUnit:
    def test_create_with_required_fields(self) -> None:
        unit = ContentUnit(
            id="u-1",
            path="/mods/armor",
            created_at="2026-07-12T00:00:00Z",
            updated_at="2026-07-12T00:00:00Z",
        )
        assert unit.id == "u-1"
        assert unit.path == "/mods/armor"
        assert unit.content_type == "mod"
        assert unit.status == "unorganized"
        assert unit.title is None

    def test_create_with_all_fields(self) -> None:
        unit = ContentUnit(
            id="u-2",
            path="/mods/weapon",
            created_at="2026-07-12T00:00:00Z",
            updated_at="2026-07-12T00:00:00Z",
            title="龙之剑",
            content_type="mod",
            source_url="https://example.com",
            cover_path="/mods/weapon/cover.png",
            status="organized",
            notes="测试备注",
        )
        assert unit.title == "龙之剑"
        assert unit.status == "organized"

    def test_empty_id_raises(self) -> None:
        with pytest.raises(ValueError, match="id"):
            ContentUnit(id="", path="/x", created_at="t", updated_at="t")

    def test_empty_path_raises(self) -> None:
        with pytest.raises(ValueError, match="path"):
            ContentUnit(id="u", path="", created_at="t", updated_at="t")

    def test_empty_created_at_raises(self) -> None:
        with pytest.raises(ValueError, match="created_at"):
            ContentUnit(id="u", path="/x", created_at="", updated_at="t")

    def test_empty_updated_at_raises(self) -> None:
        with pytest.raises(ValueError, match="updated_at"):
            ContentUnit(id="u", path="/x", created_at="t", updated_at="")

    def test_chinese_path(self) -> None:
        unit = ContentUnit(
            id="u",
            path="D:/Mods/护甲/寒霜之心",
            created_at="t",
            updated_at="t",
        )
        assert "护甲" in unit.path


# === TagCategory ===


class TestTagCategory:
    def test_create_with_defaults(self) -> None:
        cat = TagCategory(id="c-1", name="类型")
        assert cat.color_hue == 0

    def test_empty_id_raises(self) -> None:
        with pytest.raises(ValueError, match="id"):
            TagCategory(id="", name="x")

    def test_empty_name_raises(self) -> None:
        with pytest.raises(ValueError, match="name"):
            TagCategory(id="c", name="")

    def test_color_hue_below_range_raises(self) -> None:
        with pytest.raises(ValueError, match="color_hue"):
            TagCategory(id="c", name="x", color_hue=-1)

    def test_color_hue_above_range_raises(self) -> None:
        with pytest.raises(ValueError, match="color_hue"):
            TagCategory(id="c", name="x", color_hue=361)

    def test_color_hue_boundaries(self) -> None:
        TagCategory(id="c", name="x", color_hue=0)
        TagCategory(id="c", name="x", color_hue=360)


# === Tag ===


class TestTag:
    def test_create(self) -> None:
        tag = Tag(id="t-1", name="护甲", category_id="c-1")
        assert tag.name == "护甲"
        assert tag.category_id == "c-1"

    def test_empty_id_raises(self) -> None:
        with pytest.raises(ValueError, match="id"):
            Tag(id="", name="x", category_id="c")

    def test_empty_name_raises(self) -> None:
        with pytest.raises(ValueError, match="name"):
            Tag(id="t", name="", category_id="c")

    def test_empty_category_id_raises(self) -> None:
        with pytest.raises(ValueError, match="category_id"):
            Tag(id="t", name="x", category_id="")


# === OperationHistory ===


class TestOperationHistory:
    def test_create_move(self) -> None:
        op = OperationHistory(
            id="op-1",
            operation_type="move",
            source_path="/mods/a",
            target_path="/mods/b",
            created_at="t",
        )
        assert op.operation_type == "move"
        assert op.can_undo is True

    def test_create_delete_without_target(self) -> None:
        op = OperationHistory(
            id="op-2",
            operation_type="delete",
            source_path="/mods/a",
            created_at="t",
        )
        assert op.target_path is None

    def test_invalid_operation_type_raises(self) -> None:
        with pytest.raises(ValueError, match="operation_type"):
            OperationHistory(
                id="op",
                operation_type="invalid",
                source_path="/x",
                created_at="t",
            )

    def test_empty_source_path_raises(self) -> None:
        with pytest.raises(ValueError, match="source_path"):
            OperationHistory(
                id="op",
                operation_type="move",
                source_path="",
                created_at="t",
            )

    def test_can_undo_false(self) -> None:
        op = OperationHistory(
            id="op",
            operation_type="new_folder",
            source_path="/x",
            created_at="t",
            can_undo=False,
        )
        assert op.can_undo is False


# === FolderCache ===


class TestFolderCache:
    def test_create_with_parent(self) -> None:
        folder = FolderCache(
            id="f-1",
            path="/mods",
            created_at="t",
            parent_id="f-0",
            last_scanned_mtime=1000.0,
        )
        assert folder.parent_id == "f-0"
        assert folder.last_scanned_mtime == 1000.0

    def test_create_as_root(self) -> None:
        folder = FolderCache(id="f-1", path="/mods", created_at="t")
        assert folder.parent_id is None
        assert folder.last_scanned_mtime is None

    def test_empty_id_raises(self) -> None:
        with pytest.raises(ValueError, match="id"):
            FolderCache(id="", path="/x", created_at="t")

    def test_empty_path_raises(self) -> None:
        with pytest.raises(ValueError, match="path"):
            FolderCache(id="f", path="", created_at="t")


# === ManagedRoot ===


class TestManagedRoot:
    def test_create(self) -> None:
        root = ManagedRoot(
            id="r-1",
            real_path="D:/Mods",
            path_key="d:/mods",
            created_at="t",
            updated_at="t",
            display_name="Mods",
        )
        assert root.display_name == "Mods"

    def test_empty_id_raises(self) -> None:
        with pytest.raises(ValueError, match="id"):
            ManagedRoot(
                id="",
                real_path="D:/Mods",
                path_key="d:/mods",
                created_at="t",
                updated_at="t",
            )

    def test_empty_real_path_raises(self) -> None:
        with pytest.raises(ValueError, match="real_path"):
            ManagedRoot(
                id="r",
                real_path="",
                path_key="d:/mods",
                created_at="t",
                updated_at="t",
            )

    def test_empty_path_key_raises(self) -> None:
        with pytest.raises(ValueError, match="path_key"):
            ManagedRoot(
                id="r",
                real_path="D:/Mods",
                path_key="",
                created_at="t",
                updated_at="t",
            )
