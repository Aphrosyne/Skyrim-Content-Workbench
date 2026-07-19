"""TagRepository 测试。

覆盖：
- create / get_by_id / get_by_name_in_category / list_all / list_by_category /
  list_by_ids / update / delete；
- (name, category_id) UNIQUE 约束（schema v6 起生效，同分类下不重名，不同分类可重名）；
- NotFoundError / ConstraintViolationError 异常路径；
- 中文 name 支持。
"""

from __future__ import annotations

import sqlite3

import pytest

from domain.models import Tag, TagCategory
from infrastructure.repositories.errors import (
    ConstraintViolationError,
    NotFoundError,
)
from infrastructure.repositories.tag import TagRepository
from infrastructure.repositories.tag_category import TagCategoryRepository


def _seed_cat(conn: sqlite3.Connection, category_id: str = "c-1", name: str = "服装护甲") -> None:
    """插入一个 TagCategory 供 Tag 引用。"""
    TagCategoryRepository(conn).create(TagCategory(id=category_id, name=name, color_hue=210))


def _make_tag(
    tag_id: str = "t-1",
    name: str = "重甲",
    category_id: str = "c-1",
) -> Tag:
    return Tag(id=tag_id, name=name, category_id=category_id)


class TestCreate:
    def test_create_and_get_by_id(self, db_connection: sqlite3.Connection) -> None:
        _seed_cat(db_connection)
        repo = TagRepository(db_connection)
        created = repo.create(_make_tag())
        assert created.id == "t-1"
        assert created.name == "重甲"
        assert created.category_id == "c-1"

        fetched = repo.get_by_id("t-1")
        assert fetched is not None
        assert fetched.name == "重甲"

    def test_create_duplicate_name_in_same_category_raises(
        self, db_connection: sqlite3.Connection
    ) -> None:
        _seed_cat(db_connection)
        repo = TagRepository(db_connection)
        repo.create(_make_tag(name="重甲"))
        with pytest.raises(ConstraintViolationError):
            repo.create(_make_tag(tag_id="t-2", name="重甲"))

    def test_create_same_name_in_different_category_ok(
        self, db_connection: sqlite3.Connection
    ) -> None:
        _seed_cat(db_connection, category_id="c-1", name="服装护甲")
        _seed_cat(db_connection, category_id="c-2", name="武器")
        repo = TagRepository(db_connection)
        repo.create(_make_tag(tag_id="t-1", name="重甲", category_id="c-1"))
        # 不同分类下同名标签应允许
        repo.create(_make_tag(tag_id="t-2", name="重甲", category_id="c-2"))

    def test_create_chinese_name(self, db_connection: sqlite3.Connection) -> None:
        _seed_cat(db_connection)
        repo = TagRepository(db_connection)
        created = repo.create(_make_tag(name="单手剑"))
        assert created.name == "单手剑"


class TestGetByNameInCategory:
    def test_found(self, db_connection: sqlite3.Connection) -> None:
        _seed_cat(db_connection)
        repo = TagRepository(db_connection)
        repo.create(_make_tag(name="重甲"))
        found = repo.get_by_name_in_category("重甲", "c-1")
        assert found is not None
        assert found.name == "重甲"

    def test_not_found(self, db_connection: sqlite3.Connection) -> None:
        _seed_cat(db_connection)
        repo = TagRepository(db_connection)
        assert repo.get_by_name_in_category("不存在", "c-1") is None


class TestListAll:
    def test_empty(self, db_connection: sqlite3.Connection) -> None:
        repo = TagRepository(db_connection)
        assert repo.list_all() == []

    def test_sorted_by_name(self, db_connection: sqlite3.Connection) -> None:
        _seed_cat(db_connection)
        repo = TagRepository(db_connection)
        repo.create(_make_tag(tag_id="t-1", name="重甲"))
        repo.create(_make_tag(tag_id="t-2", name="轻甲"))
        repo.create(_make_tag(tag_id="t-3", name="法袍"))
        result = repo.list_all()
        assert [t.name for t in result] == ["法袍", "轻甲", "重甲"]


class TestListByCategory:
    def test_returns_tags_in_category(self, db_connection: sqlite3.Connection) -> None:
        _seed_cat(db_connection, category_id="c-1", name="服装护甲")
        _seed_cat(db_connection, category_id="c-2", name="武器")
        repo = TagRepository(db_connection)
        repo.create(_make_tag(tag_id="t-1", name="重甲", category_id="c-1"))
        repo.create(_make_tag(tag_id="t-2", name="轻甲", category_id="c-1"))
        repo.create(_make_tag(tag_id="t-3", name="单手剑", category_id="c-2"))

        result = repo.list_by_category("c-1")
        assert {t.id for t in result} == {"t-1", "t-2"}

    def test_empty_for_category_without_tags(self, db_connection: sqlite3.Connection) -> None:
        _seed_cat(db_connection)
        repo = TagRepository(db_connection)
        assert repo.list_by_category("c-1") == []


class TestListByIds:
    def test_empty_input(self, db_connection: sqlite3.Connection) -> None:
        repo = TagRepository(db_connection)
        assert repo.list_by_ids([]) == []

    def test_returns_matching(self, db_connection: sqlite3.Connection) -> None:
        _seed_cat(db_connection)
        repo = TagRepository(db_connection)
        repo.create(_make_tag(tag_id="t-1", name="重甲"))
        repo.create(_make_tag(tag_id="t-2", name="轻甲"))
        repo.create(_make_tag(tag_id="t-3", name="法袍"))

        result = repo.list_by_ids(["t-1", "t-3"])
        assert {t.id for t in result} == {"t-1", "t-3"}

    def test_ignores_nonexistent(self, db_connection: sqlite3.Connection) -> None:
        _seed_cat(db_connection)
        repo = TagRepository(db_connection)
        repo.create(_make_tag(tag_id="t-1", name="重甲"))
        result = repo.list_by_ids(["t-1", "ghost"])
        assert [t.id for t in result] == ["t-1"]


class TestUpdate:
    def test_rename(self, db_connection: sqlite3.Connection) -> None:
        _seed_cat(db_connection)
        repo = TagRepository(db_connection)
        repo.create(_make_tag(name="旧名"))
        tag = repo.get_by_id("t-1")
        assert tag is not None
        tag.name = "新名"
        updated = repo.update(tag)
        assert updated.name == "新名"

    def test_move_category(self, db_connection: sqlite3.Connection) -> None:
        _seed_cat(db_connection, category_id="c-1", name="服装护甲")
        _seed_cat(db_connection, category_id="c-2", name="武器")
        repo = TagRepository(db_connection)
        repo.create(_make_tag(tag_id="t-1", name="重甲", category_id="c-1"))
        tag = repo.get_by_id("t-1")
        assert tag is not None
        tag.category_id = "c-2"
        updated = repo.update(tag)
        assert updated.category_id == "c-2"

    def test_update_duplicate_name_in_same_category_raises(
        self, db_connection: sqlite3.Connection
    ) -> None:
        _seed_cat(db_connection)
        repo = TagRepository(db_connection)
        repo.create(_make_tag(tag_id="t-1", name="重甲"))
        repo.create(_make_tag(tag_id="t-2", name="轻甲"))
        tag = repo.get_by_id("t-2")
        assert tag is not None
        tag.name = "重甲"
        with pytest.raises(ConstraintViolationError):
            repo.update(tag)

    def test_update_not_exist_raises_not_found(self, db_connection: sqlite3.Connection) -> None:
        repo = TagRepository(db_connection)
        with pytest.raises(NotFoundError):
            repo.update(_make_tag(tag_id="ghost", name="ghost"))


class TestDelete:
    def test_delete(self, db_connection: sqlite3.Connection) -> None:
        _seed_cat(db_connection)
        repo = TagRepository(db_connection)
        repo.create(_make_tag())
        repo.delete("t-1")
        assert repo.get_by_id("t-1") is None

    def test_delete_not_exist_raises_not_found(self, db_connection: sqlite3.Connection) -> None:
        repo = TagRepository(db_connection)
        with pytest.raises(NotFoundError):
            repo.delete("nonexistent")

    def test_delete_does_not_cascade_content_unit_tag(
        self, db_connection: sqlite3.Connection
    ) -> None:
        """delete 仅删除 tag 记录，不级联清理 content_unit_tag。

        级联清理由 application 层（TagService.delete_tag）负责。
        FK 违约时由 Repository 包装为 RepositoryError。
        """
        from infrastructure.repositories.errors import RepositoryError

        _seed_cat(db_connection)
        # 直接插入 content_unit 与 content_unit_tag（绕过 Repository）
        db_connection.execute(
            "INSERT INTO content_unit (id, path, created_at, updated_at) "
            "VALUES ('cu-1', '/p', 't', 't')"
        )
        db_connection.execute(
            "INSERT INTO tag (id, name, category_id) VALUES ('t-1', '重甲', 'c-1')"
        )
        db_connection.execute(
            "INSERT INTO content_unit_tag (content_unit_id, tag_id) VALUES ('cu-1', 't-1')"
        )
        db_connection.commit()

        repo = TagRepository(db_connection)
        # 直接 delete 会因 FK 违约失败，Repository 捕获并包装为 RepositoryError
        with pytest.raises(RepositoryError):
            repo.delete("t-1")
