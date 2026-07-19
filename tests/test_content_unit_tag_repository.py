"""ContentUnitTagRepository 测试。

覆盖：
- attach / detach / detach_all_by_content_unit / detach_all_by_tag /
  detach_all_by_category / list_tag_ids_by_content_unit /
  list_content_unit_ids_by_tag / count_by_tag / count_by_category / is_attached；
- attach 幂等性（INSERT OR IGNORE）；
- detach_all_by_category 子查询级联清理；
- 中文关联支持。
"""

from __future__ import annotations

import sqlite3

from domain.models import Tag, TagCategory
from infrastructure.repositories.content_unit_tag import ContentUnitTagRepository
from infrastructure.repositories.tag import TagRepository
from infrastructure.repositories.tag_category import TagCategoryRepository


def _seed_category(
    conn: sqlite3.Connection,
    category_id: str = "c-1",
    name: str = "服装护甲",
) -> None:
    TagCategoryRepository(conn).create(TagCategory(id=category_id, name=name, color_hue=210))


def _seed_tag(
    conn: sqlite3.Connection,
    tag_id: str = "t-1",
    name: str = "重甲",
    category_id: str = "c-1",
) -> None:
    TagRepository(conn).create(Tag(id=tag_id, name=name, category_id=category_id))


def _seed_content_unit(
    conn: sqlite3.Connection, unit_id: str = "cu-1", path: str = "/mods/a"
) -> None:
    conn.execute(
        "INSERT INTO content_unit (id, path, created_at, updated_at) VALUES (?, ?, 't', 't')",
        (unit_id, path),
    )
    conn.commit()


class TestAttach:
    def test_attach_new_returns_true(self, db_connection: sqlite3.Connection) -> None:
        _seed_category(db_connection)
        _seed_tag(db_connection)
        _seed_content_unit(db_connection)
        repo = ContentUnitTagRepository(db_connection)
        assert repo.attach("cu-1", "t-1") is True

    def test_attach_duplicate_returns_false(self, db_connection: sqlite3.Connection) -> None:
        _seed_category(db_connection)
        _seed_tag(db_connection)
        _seed_content_unit(db_connection)
        repo = ContentUnitTagRepository(db_connection)
        repo.attach("cu-1", "t-1")
        # 重复 attach 不抛异常，返回 False
        assert repo.attach("cu-1", "t-1") is False

    def test_attach_chinese_paths(self, db_connection: sqlite3.Connection) -> None:
        _seed_category(db_connection)
        _seed_tag(db_connection, name="中文标签")
        _seed_content_unit(db_connection, path="D:/Mods/护甲/寒霜之心")
        repo = ContentUnitTagRepository(db_connection)
        assert repo.attach("cu-1", "t-1") is True


class TestDetach:
    def test_detach_existing_returns_true(self, db_connection: sqlite3.Connection) -> None:
        _seed_category(db_connection)
        _seed_tag(db_connection)
        _seed_content_unit(db_connection)
        repo = ContentUnitTagRepository(db_connection)
        repo.attach("cu-1", "t-1")
        assert repo.detach("cu-1", "t-1") is True
        assert repo.is_attached("cu-1", "t-1") is False

    def test_detach_nonexisting_returns_false(self, db_connection: sqlite3.Connection) -> None:
        repo = ContentUnitTagRepository(db_connection)
        assert repo.detach("cu-1", "t-1") is False


class TestDetachAllByContentUnit:
    def test_removes_all_tags_for_content_unit(self, db_connection: sqlite3.Connection) -> None:
        _seed_category(db_connection)
        _seed_tag(db_connection, tag_id="t-1", name="重甲")
        _seed_tag(db_connection, tag_id="t-2", name="轻甲", category_id="c-1")
        _seed_content_unit(db_connection)
        repo = ContentUnitTagRepository(db_connection)
        repo.attach("cu-1", "t-1")
        repo.attach("cu-1", "t-2")
        removed = repo.detach_all_by_content_unit("cu-1")
        assert removed == 2
        assert repo.list_tag_ids_by_content_unit("cu-1") == []


class TestDetachAllByTag:
    def test_removes_all_content_units_for_tag(self, db_connection: sqlite3.Connection) -> None:
        _seed_category(db_connection)
        _seed_tag(db_connection, tag_id="t-1", name="重甲")
        _seed_content_unit(db_connection, unit_id="cu-1")
        _seed_content_unit(db_connection, unit_id="cu-2", path="/mods/b")
        repo = ContentUnitTagRepository(db_connection)
        repo.attach("cu-1", "t-1")
        repo.attach("cu-2", "t-1")
        removed = repo.detach_all_by_tag("t-1")
        assert removed == 2
        assert repo.list_content_unit_ids_by_tag("t-1") == []


class TestDetachAllByCategory:
    def test_cascade_removes_all_links_for_tags_in_category(
        self, db_connection: sqlite3.Connection
    ) -> None:
        # 准备两个分类，每个分类下有 1 个标签
        _seed_category(db_connection, category_id="c-1", name="服装护甲")
        _seed_category(db_connection, category_id="c-2", name="武器")
        # 直接 INSERT tag 第二个分类
        from domain.models import Tag

        TagRepository(db_connection).create(Tag(id="t-c1", name="重甲", category_id="c-1"))
        TagRepository(db_connection).create(Tag(id="t-c2", name="单手剑", category_id="c-2"))
        _seed_content_unit(db_connection, unit_id="cu-1")
        _seed_content_unit(db_connection, unit_id="cu-2", path="/mods/b")

        repo = ContentUnitTagRepository(db_connection)
        repo.attach("cu-1", "t-c1")
        repo.attach("cu-2", "t-c1")
        repo.attach("cu-1", "t-c2")

        # 删除 c-1 分类下所有 tag 的关联（保留 c-2 的关联）
        removed = repo.detach_all_by_category("c-1")
        assert removed == 2
        # c-2 关联仍存在
        assert repo.is_attached("cu-1", "t-c2") is True
        # c-1 关联已清空
        assert repo.is_attached("cu-1", "t-c1") is False
        assert repo.is_attached("cu-2", "t-c1") is False


class TestList:
    def test_list_tag_ids_by_content_unit(self, db_connection: sqlite3.Connection) -> None:
        _seed_category(db_connection)
        _seed_tag(db_connection, tag_id="t-1", name="重甲")
        _seed_tag(db_connection, tag_id="t-2", name="轻甲")
        _seed_content_unit(db_connection)
        repo = ContentUnitTagRepository(db_connection)
        repo.attach("cu-1", "t-2")
        repo.attach("cu-1", "t-1")
        ids = repo.list_tag_ids_by_content_unit("cu-1")
        # 按 tag_id 排序
        assert ids == ["t-1", "t-2"]

    def test_list_content_unit_ids_by_tag(self, db_connection: sqlite3.Connection) -> None:
        _seed_category(db_connection)
        _seed_tag(db_connection, tag_id="t-1", name="重甲")
        _seed_content_unit(db_connection, unit_id="cu-2", path="/mods/b")
        _seed_content_unit(db_connection, unit_id="cu-1", path="/mods/a")
        repo = ContentUnitTagRepository(db_connection)
        repo.attach("cu-2", "t-1")
        repo.attach("cu-1", "t-1")
        ids = repo.list_content_unit_ids_by_tag("t-1")
        # 按 content_unit_id 排序
        assert ids == ["cu-1", "cu-2"]


class TestCount:
    def test_count_by_tag(self, db_connection: sqlite3.Connection) -> None:
        _seed_category(db_connection)
        _seed_tag(db_connection, tag_id="t-1", name="重甲")
        _seed_content_unit(db_connection, unit_id="cu-1")
        _seed_content_unit(db_connection, unit_id="cu-2", path="/mods/b")
        repo = ContentUnitTagRepository(db_connection)
        repo.attach("cu-1", "t-1")
        repo.attach("cu-2", "t-1")
        assert repo.count_by_tag("t-1") == 2

    def test_count_by_category(self, db_connection: sqlite3.Connection) -> None:
        _seed_category(db_connection, category_id="c-1", name="服装护甲")
        _seed_category(db_connection, category_id="c-2", name="武器")
        from domain.models import Tag

        TagRepository(db_connection).create(Tag(id="t-c1a", name="重甲", category_id="c-1"))
        TagRepository(db_connection).create(Tag(id="t-c1b", name="轻甲", category_id="c-1"))
        TagRepository(db_connection).create(Tag(id="t-c2a", name="单手剑", category_id="c-2"))
        _seed_content_unit(db_connection, unit_id="cu-1")
        _seed_content_unit(db_connection, unit_id="cu-2", path="/mods/b")

        repo = ContentUnitTagRepository(db_connection)
        repo.attach("cu-1", "t-c1a")
        repo.attach("cu-2", "t-c1a")
        repo.attach("cu-1", "t-c1b")
        repo.attach("cu-1", "t-c2a")
        assert repo.count_by_category("c-1") == 3
        assert repo.count_by_category("c-2") == 1


class TestIsAttached:
    def test_attached_returns_true(self, db_connection: sqlite3.Connection) -> None:
        _seed_category(db_connection)
        _seed_tag(db_connection)
        _seed_content_unit(db_connection)
        repo = ContentUnitTagRepository(db_connection)
        repo.attach("cu-1", "t-1")
        assert repo.is_attached("cu-1", "t-1") is True

    def test_not_attached_returns_false(self, db_connection: sqlite3.Connection) -> None:
        repo = ContentUnitTagRepository(db_connection)
        assert repo.is_attached("cu-1", "t-1") is False
