"""TagService 测试。

覆盖：
- TagCategory CRUD（create / get / list / rename / update_color / delete）；
- Tag CRUD（create / get / list / rename / move_to_category / delete）；
- delete_category 级联清理（标签 + content_unit_tag 关联）；
- delete_tag 级联清理（content_unit_tag 关联）；
- JSON 导入导出（schema_version=1，合并跳过策略）；
- 预置库加载（load_default_tags_if_empty）；
- 异常分层（ApplicationError 子类）；
- 中文标签支持。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from application.errors import (
    DuplicateTagCategoryNameError,
    DuplicateTagNameError,
    InvalidTagJsonError,
    TagCategoryNotFoundError,
    TagNotFoundError,
)
from application.tag_service import TAGS_JSON_SCHEMA_VERSION, TagService
from infrastructure.repositories.content_unit_tag import ContentUnitTagRepository
from infrastructure.repositories.tag import TagRepository
from infrastructure.repositories.tag_category import TagCategoryRepository


def _make_service(
    conn: sqlite3.Connection,
    now_provider=None,
    uuid_provider=None,
) -> TagService:
    """构造 TagService，注入固定 uuid_provider 便于测试断言。"""
    return TagService(
        TagCategoryRepository(conn),
        TagRepository(conn),
        ContentUnitTagRepository(conn),
        now_provider=now_provider or (lambda: "2026-07-18T00:00:00Z"),
        uuid_provider=uuid_provider,
    )


def _counter_uuid_provider():
    """返回一个计数器 uuid_provider，每次调用产生 uuid-1 / uuid-2 / ..."""
    counter = {"n": 0}

    def _gen() -> str:
        counter["n"] += 1
        return f"uuid-{counter['n']}"

    return _gen


# === TagCategory CRUD ===


class TestCreateCategory:
    def test_create_basic(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection, uuid_provider=lambda: "uuid-1")
        cat = service.create_category("服装护甲", color_hue=210)
        assert cat.id == "uuid-1"
        assert cat.name == "服装护甲"
        assert cat.color_hue == 210

    def test_create_duplicate_name_raises(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection)
        service.create_category("服装护甲")
        with pytest.raises(DuplicateTagCategoryNameError):
            service.create_category("服装护甲")

    def test_create_empty_name_raises(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection)
        with pytest.raises(InvalidTagJsonError):
            service.create_category("  ")

    def test_create_chinese_name(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection)
        cat = service.create_category("来源")
        assert cat.name == "来源"


class TestGetCategory:
    def test_get_existing(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection, uuid_provider=lambda: "c-1")
        service.create_category("服装护甲")
        cat = service.get_category("c-1")
        assert cat.name == "服装护甲"

    def test_get_missing_raises(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection)
        with pytest.raises(TagCategoryNotFoundError):
            service.get_category("nonexistent")


class TestListCategories:
    def test_list_empty(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection)
        assert service.list_categories() == []

    def test_list_sorted_by_name(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection, uuid_provider=_counter_uuid_provider())
        service.create_category("武器")
        service.create_category("服装护甲")
        service.create_category("来源")
        names = [c.name for c in service.list_categories()]
        # SQLite BINARY 排序（按 Unicode 码点）：服 < 来 < 武
        assert names == ["服装护甲", "来源", "武器"]


class TestRenameCategory:
    def test_rename(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection, uuid_provider=lambda: "c-1")
        service.create_category("旧名")
        cat = service.rename_category("c-1", "新名")
        assert cat.name == "新名"

    def test_rename_to_duplicate_raises(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection, uuid_provider=_counter_uuid_provider())
        cat1 = service.create_category("甲")  # id = uuid-1
        cat2 = service.create_category("乙")  # id = uuid-2
        with pytest.raises(DuplicateTagCategoryNameError):
            service.rename_category(cat2.id, "甲")  # 把"乙"重命名为"甲"
        assert cat1.id == "uuid-1"
        assert cat2.id == "uuid-2"

    def test_rename_missing_raises(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection)
        with pytest.raises(TagCategoryNotFoundError):
            service.rename_category("nonexistent", "新名")


class TestUpdateCategoryColor:
    def test_update_color(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection, uuid_provider=lambda: "c-1")
        service.create_category("服装护甲", color_hue=100)
        cat = service.update_category_color("c-1", 250)
        assert cat.color_hue == 250

    def test_update_missing_raises(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection)
        with pytest.raises(TagCategoryNotFoundError):
            service.update_category_color("nonexistent", 200)


class TestDeleteCategory:
    def test_delete_cascades_tags_and_links(self, db_connection: sqlite3.Connection) -> None:
        """delete_category 应级联清理：1) content_unit_tag 关联 2) tag 3) category。"""
        service = _make_service(db_connection)
        cat = service.create_category("服装护甲")
        tag1 = service.create_tag("重甲", cat.id)
        tag2 = service.create_tag("轻甲", cat.id)

        # 插入 content_unit + 关联
        db_connection.execute(
            "INSERT INTO content_unit (id, path, created_at, updated_at) "
            "VALUES ('cu-1', '/p', 't', 't')"
        )
        cut_repo = ContentUnitTagRepository(db_connection)
        cut_repo.attach("cu-1", tag1.id)
        cut_repo.attach("cu-1", tag2.id)

        service.delete_category(cat.id)

        # tag_category 已删除
        assert service.list_categories() == []
        # tag 已删除
        assert TagRepository(db_connection).list_all() == []
        # content_unit_tag 关联已清理
        assert cut_repo.list_tag_ids_by_content_unit("cu-1") == []
        # content_unit 本身不受影响
        count = db_connection.execute(
            "SELECT COUNT(*) FROM content_unit WHERE id = 'cu-1'"
        ).fetchone()[0]
        assert count == 1

    def test_delete_missing_raises(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection)
        with pytest.raises(TagCategoryNotFoundError):
            service.delete_category("nonexistent")


# === Tag CRUD ===


class TestCreateTag:
    def test_create_basic(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection)
        cat = service.create_category("服装护甲")
        tag = service.create_tag("重甲", cat.id)
        assert tag.name == "重甲"
        assert tag.category_id == cat.id

    def test_create_duplicate_in_same_category_raises(
        self, db_connection: sqlite3.Connection
    ) -> None:
        service = _make_service(db_connection)
        cat = service.create_category("服装护甲")
        service.create_tag("重甲", cat.id)
        with pytest.raises(DuplicateTagNameError):
            service.create_tag("重甲", cat.id)

    def test_create_same_name_in_different_category_ok(
        self, db_connection: sqlite3.Connection
    ) -> None:
        service = _make_service(db_connection)
        cat1 = service.create_category("服装护甲")
        cat2 = service.create_category("武器")
        service.create_tag("重甲", cat1.id)
        service.create_tag("重甲", cat2.id)  # 不同分类下同名允许

    def test_create_with_missing_category_raises(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection)
        with pytest.raises(TagCategoryNotFoundError):
            service.create_tag("重甲", "nonexistent")

    def test_create_empty_name_raises(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection)
        cat = service.create_category("服装护甲")
        with pytest.raises(InvalidTagJsonError):
            service.create_tag("  ", cat.id)


class TestRenameTag:
    def test_rename(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection)
        cat = service.create_category("服装护甲")
        tag = service.create_tag("旧名", cat.id)
        renamed = service.rename_tag(tag.id, "新名")
        assert renamed.name == "新名"

    def test_rename_to_duplicate_in_same_category_raises(
        self, db_connection: sqlite3.Connection
    ) -> None:
        service = _make_service(db_connection)
        cat = service.create_category("服装护甲")
        service.create_tag("重甲", cat.id)
        tag2 = service.create_tag("轻甲", cat.id)
        with pytest.raises(DuplicateTagNameError):
            service.rename_tag(tag2.id, "重甲")

    def test_rename_missing_raises(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection)
        with pytest.raises(TagNotFoundError):
            service.rename_tag("nonexistent", "新名")


class TestMoveTag:
    def test_move_to_other_category(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection)
        cat1 = service.create_category("服装护甲")
        cat2 = service.create_category("武器")
        tag = service.create_tag("重甲", cat1.id)
        moved = service.move_tag_to_category(tag.id, cat2.id)
        assert moved.category_id == cat2.id

    def test_move_to_same_category_is_noop(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection)
        cat = service.create_category("服装护甲")
        tag = service.create_tag("重甲", cat.id)
        moved = service.move_tag_to_category(tag.id, cat.id)
        assert moved.category_id == cat.id

    def test_move_to_target_with_duplicate_name_raises(
        self, db_connection: sqlite3.Connection
    ) -> None:
        service = _make_service(db_connection)
        cat1 = service.create_category("服装护甲")
        cat2 = service.create_category("武器")
        service.create_tag("重甲", cat2.id)
        tag = service.create_tag("重甲", cat1.id)
        with pytest.raises(DuplicateTagNameError):
            service.move_tag_to_category(tag.id, cat2.id)

    def test_move_to_missing_category_raises(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection)
        cat = service.create_category("服装护甲")
        tag = service.create_tag("重甲", cat.id)
        with pytest.raises(TagCategoryNotFoundError):
            service.move_tag_to_category(tag.id, "nonexistent")


class TestDeleteTag:
    def test_delete_cascades_content_unit_tag(self, db_connection: sqlite3.Connection) -> None:
        """delete_tag 应级联清理 content_unit_tag 关联，但不影响其他 tag。"""
        service = _make_service(db_connection)
        cat = service.create_category("服装护甲")
        tag1 = service.create_tag("重甲", cat.id)
        tag2 = service.create_tag("轻甲", cat.id)

        db_connection.execute(
            "INSERT INTO content_unit (id, path, created_at, updated_at) "
            "VALUES ('cu-1', '/p', 't', 't')"
        )
        cut_repo = ContentUnitTagRepository(db_connection)
        cut_repo.attach("cu-1", tag1.id)
        cut_repo.attach("cu-1", tag2.id)

        service.delete_tag(tag1.id)

        # tag1 已删除
        assert service.list_tags_by_category(cat.id) == [tag2]
        # tag1 的关联已清理，tag2 的关联保留
        assert cut_repo.is_attached("cu-1", tag1.id) is False
        assert cut_repo.is_attached("cu-1", tag2.id) is True

    def test_delete_missing_raises(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection)
        with pytest.raises(TagNotFoundError):
            service.delete_tag("nonexistent")


class TestListCategoriesWithTags:
    def test_returns_categories_with_their_tags(self, db_connection: sqlite3.Connection) -> None:
        service = _make_service(db_connection)
        cat1 = service.create_category("服装护甲")
        cat2 = service.create_category("武器")
        service.create_tag("重甲", cat1.id)
        service.create_tag("轻甲", cat1.id)
        service.create_tag("单手剑", cat2.id)

        result = service.list_categories_with_tags()
        # 分类按 BINARY 排序：服 < 武
        assert result[0][0].name == "服装护甲"
        # 标签按 BINARY 排序：轻 < 重
        assert [t.name for t in result[0][1]] == ["轻甲", "重甲"]
        assert result[1][0].name == "武器"
        assert [t.name for t in result[1][1]] == ["单手剑"]


# === JSON 导入导出 ===


class TestExportToJson:
    def test_export_basic(self, db_connection: sqlite3.Connection, tmp_path: Path) -> None:
        service = _make_service(db_connection)
        cat = service.create_category("服装护甲", color_hue=210)
        service.create_tag("重甲", cat.id)
        service.create_tag("轻甲", cat.id)

        out = tmp_path / "export.json"
        service.export_to_json(out)

        with out.open("r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["schema_version"] == TAGS_JSON_SCHEMA_VERSION
        assert len(data["categories"]) == 1
        assert data["categories"][0]["name"] == "服装护甲"
        assert data["categories"][0]["color_hue"] == 210
        assert sorted(data["categories"][0]["tags"]) == ["轻甲", "重甲"]

    def test_export_chinese(self, db_connection: sqlite3.Connection, tmp_path: Path) -> None:
        service = _make_service(db_connection)
        cat = service.create_category("来源")
        service.create_tag("N 网", cat.id)
        service.create_tag("韩网", cat.id)

        out = tmp_path / "cn.json"
        service.export_to_json(out)

        # 应保留中文字符（ensure_ascii=False）
        text = out.read_text(encoding="utf-8")
        assert "N 网" in text
        assert "韩网" in text


class TestImportFromJson:
    def test_import_basic(self, db_connection: sqlite3.Connection, tmp_path: Path) -> None:
        service = _make_service(db_connection)
        # 准备 JSON
        json_path = tmp_path / "input.json"
        json_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "categories": [
                        {
                            "name": "服装护甲",
                            "color_hue": 210,
                            "tags": ["重甲", "轻甲"],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = service.import_from_json(json_path)
        assert result["created_categories"] == 1
        assert result["skipped_categories"] == 0
        assert result["created_tags"] == 2
        assert result["skipped_tags"] == 0

        cats = service.list_categories()
        assert len(cats) == 1
        assert cats[0].name == "服装护甲"
        tags = service.list_tags_by_category(cats[0].id)
        assert {t.name for t in tags} == {"重甲", "轻甲"}

    def test_import_skips_existing_category(
        self, db_connection: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """合并跳过策略：同名分类整体跳过（不创建该分类）。"""
        service = _make_service(db_connection)
        # 数据库已有同名分类
        existing_cat = service.create_category("服装护甲")
        service.create_tag("已有标签", existing_cat.id)

        json_path = tmp_path / "input.json"
        json_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "categories": [
                        {
                            "name": "服装护甲",
                            "color_hue": 30,
                            "tags": ["重甲", "轻甲"],
                        },
                        {
                            "name": "武器",
                            "color_hue": 30,
                            "tags": ["单手剑"],
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = service.import_from_json(json_path)
        # 服装护甲 整体跳过（不创建其下标签）
        assert result["created_categories"] == 1
        assert result["skipped_categories"] == 1
        assert result["created_tags"] == 1
        assert result["skipped_tags"] == 0

        # 服装护甲 下的标签数量未变
        cat = service.get_category(existing_cat.id)
        tags = service.list_tags_by_category(cat.id)
        assert [t.name for t in tags] == ["已有标签"]

    def test_import_invalid_schema_version_raises(
        self, db_connection: sqlite3.Connection, tmp_path: Path
    ) -> None:
        service = _make_service(db_connection)
        json_path = tmp_path / "input.json"
        json_path.write_text(
            json.dumps({"schema_version": 999, "categories": []}),
            encoding="utf-8",
        )
        with pytest.raises(InvalidTagJsonError):
            service.import_from_json(json_path)

    def test_import_invalid_json_structure_raises(
        self, db_connection: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """非法 JSON 应被捕获并转换为 InvalidTagJsonError（不向上抛 JSONDecodeError）。"""
        service = _make_service(db_connection)
        json_path = tmp_path / "input.json"
        json_path.write_text("not a valid json {", encoding="utf-8")
        with pytest.raises(InvalidTagJsonError):
            service.import_from_json(json_path)

    def test_import_missing_categories_raises(
        self, db_connection: sqlite3.Connection, tmp_path: Path
    ) -> None:
        service = _make_service(db_connection)
        json_path = tmp_path / "input.json"
        json_path.write_text(
            json.dumps({"schema_version": 1}),
            encoding="utf-8",
        )
        with pytest.raises(InvalidTagJsonError):
            service.import_from_json(json_path)

    def test_import_missing_file_raises_oserror(
        self, db_connection: sqlite3.Connection, tmp_path: Path
    ) -> None:
        service = _make_service(db_connection)
        with pytest.raises(OSError):
            service.import_from_json(tmp_path / "nonexistent.json")


# === 清空与覆盖导入 ===


class TestClearAllTags:
    def test_clears_categories_tags_and_links(self, db_connection: sqlite3.Connection) -> None:
        """clear_all_tags 级联清理分类、标签、content_unit_tag 关联。"""
        service = _make_service(db_connection, uuid_provider=_counter_uuid_provider())
        cat = service.create_category("服装护甲", color_hue=210)
        service.create_tag("重甲", cat.id)
        service.create_tag("轻甲", cat.id)
        cat2 = service.create_category("武器", color_hue=30)
        service.create_tag("单手剑", cat2.id)
        db_connection.commit()

        result = service.clear_all_tags()

        assert result["deleted_categories"] == 2
        assert result["deleted_tags"] == 3
        # 关联无数据，deleted_links 应为 0
        assert result["deleted_links"] == 0
        assert service.list_categories() == []
        assert service.list_all_tags() == []

    def test_clear_all_tags_on_empty_db(self, db_connection: sqlite3.Connection) -> None:
        """空库调用 clear_all_tags 不报错，返回 0。"""
        service = _make_service(db_connection)
        result = service.clear_all_tags()
        assert result["deleted_categories"] == 0
        assert result["deleted_tags"] == 0
        assert result["deleted_links"] == 0


class TestOverwriteImportFromJson:
    def test_overwrite_clears_then_imports(
        self, db_connection: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """覆盖导入：先清空现有标签，再导入 JSON。"""
        service = _make_service(db_connection, uuid_provider=_counter_uuid_provider())
        # 数据库已有数据
        existing_cat = service.create_category("旧分类")
        service.create_tag("旧标签", existing_cat.id)
        db_connection.commit()

        json_path = tmp_path / "input.json"
        json_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "categories": [
                        {"name": "新分类A", "color_hue": 210, "tags": ["标签1", "标签2"]},
                        {"name": "新分类B", "color_hue": 30, "tags": ["标签3"]},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        result = service.overwrite_import_from_json(json_path)

        # 旧数据应被清空
        assert result["created_categories"] == 2
        assert result["created_tags"] == 3
        # 数据库中只应包含新数据
        cats = service.list_categories()
        assert {c.name for c in cats} == {"新分类A", "新分类B"}
        all_tags = service.list_all_tags()
        assert {t.name for t in all_tags} == {"标签1", "标签2", "标签3"}

    def test_overwrite_import_invalid_json_raises_no_partial_change(
        self, db_connection: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """覆盖导入非法 JSON：service 不 commit，调用方 rollback 后旧数据保留。"""
        service = _make_service(db_connection, uuid_provider=_counter_uuid_provider())
        existing_cat = service.create_category("旧分类")
        service.create_tag("旧标签", existing_cat.id)
        db_connection.commit()

        json_path = tmp_path / "input.json"
        json_path.write_text("not a valid json {", encoding="utf-8")

        with pytest.raises(InvalidTagJsonError):
            service.overwrite_import_from_json(json_path)

        # 调用方 rollback 后旧数据应保留（service 不自提交）
        db_connection.rollback()
        cats = service.list_categories()
        assert len(cats) == 1
        assert cats[0].name == "旧分类"
        tags = service.list_tags_by_category(cats[0].id)
        assert len(tags) == 1
        assert tags[0].name == "旧标签"


# === 预置库加载 ===


class TestLoadDefaultTagsIfEmpty:
    def test_loads_when_empty(self, db_connection: sqlite3.Connection, tmp_path: Path) -> None:
        service = _make_service(db_connection, uuid_provider=_counter_uuid_provider())
        json_path = tmp_path / "defaults.json"
        json_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "categories": [
                        {"name": "服装护甲", "color_hue": 210, "tags": ["重甲", "轻甲"]},
                        {"name": "武器", "color_hue": 30, "tags": ["单手剑"]},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        loaded = service.load_default_tags_if_empty(json_path)
        assert loaded is True
        cats = service.list_categories()
        assert {c.name for c in cats} == {"服装护甲", "武器"}

    def test_skips_when_not_empty(self, db_connection: sqlite3.Connection, tmp_path: Path) -> None:
        """D1：tag_category 表非空时不加载。"""
        service = _make_service(db_connection)
        service.create_category("已有分类")

        json_path = tmp_path / "defaults.json"
        json_path.write_text(
            json.dumps(
                {"schema_version": 1, "categories": [{"name": "新分类", "tags": []}]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        loaded = service.load_default_tags_if_empty(json_path)
        assert loaded is False
        cats = service.list_categories()
        assert {c.name for c in cats} == {"已有分类"}

    def test_missing_file_returns_false(
        self, db_connection: sqlite3.Connection, tmp_path: Path
    ) -> None:
        service = _make_service(db_connection)
        loaded = service.load_default_tags_if_empty(tmp_path / "nonexistent.json")
        assert loaded is False

    def test_invalid_json_returns_false_no_partial_load(
        self, db_connection: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """D3：加载失败时 service 不 commit，由调用方 rollback 保证原子性。"""
        service = _make_service(db_connection, uuid_provider=_counter_uuid_provider())
        json_path = tmp_path / "bad.json"
        json_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "categories": [
                        {"name": "服装护甲", "color_hue": 210, "tags": ["重甲"]},
                        # 第二个分类非法：name 缺失
                        {"color_hue": 30, "tags": ["单手剑"]},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        loaded = service.load_default_tags_if_empty(json_path)
        assert loaded is False
        # service 不 commit，调用方 rollback 后数据库保持空
        db_connection.rollback()
        assert service.list_categories() == []
