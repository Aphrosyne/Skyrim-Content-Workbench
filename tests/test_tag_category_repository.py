"""TagCategoryRepository 测试。

覆盖：
- create / get_by_id / get_by_name / list_all / update / delete；
- name UNIQUE 约束（schema v6 起生效）；
- NotFoundError / ConstraintViolationError 异常路径；
- 中文 name 支持。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from domain.models import TagCategory
from infrastructure.repositories.errors import (
    ConstraintViolationError,
    NotFoundError,
)
from infrastructure.repositories.tag_category import TagCategoryRepository


def _make_category(
    category_id: str = "c-1",
    name: str = "服装护甲",
    color_hue: int = 210,
) -> TagCategory:
    return TagCategory(id=category_id, name=name, color_hue=color_hue)


class TestCreate:
    def test_create_and_get_by_id(self, db_connection: sqlite3.Connection) -> None:
        repo = TagCategoryRepository(db_connection)
        created = repo.create(_make_category())
        assert created.id == "c-1"
        assert created.name == "服装护甲"
        assert created.color_hue == 210

        fetched = repo.get_by_id("c-1")
        assert fetched is not None
        assert fetched.name == "服装护甲"

    def test_create_duplicate_name_raises_constraint(
        self, db_connection: sqlite3.Connection
    ) -> None:
        repo = TagCategoryRepository(db_connection)
        repo.create(_make_category(name="服装护甲"))
        with pytest.raises(ConstraintViolationError):
            repo.create(_make_category(category_id="c-2", name="服装护甲"))

    def test_create_chinese_name(self, db_connection: sqlite3.Connection) -> None:
        repo = TagCategoryRepository(db_connection)
        created = repo.create(_make_category(name="来源"))
        assert created.name == "来源"

    def test_create_requires_explicit_commit(
        self,
        db_path: Path,
        tmp_path: Path,  # noqa: ARG001
    ) -> None:
        """create 不自提交，未 commit 关闭连接后数据丢失。"""
        from infrastructure.db import get_connection, init_db

        init_db(db_path)
        conn = get_connection(db_path)
        conn.row_factory = sqlite3.Row
        try:
            repo = TagCategoryRepository(conn)
            repo.create(_make_category())
            # 不 commit 直接关闭
        finally:
            conn.close()

        conn2 = get_connection(db_path)
        conn2.row_factory = sqlite3.Row
        try:
            assert TagCategoryRepository(conn2).get_by_id("c-1") is None
        finally:
            conn2.close()


class TestGetByName:
    def test_get_by_name_found(self, db_connection: sqlite3.Connection) -> None:
        repo = TagCategoryRepository(db_connection)
        repo.create(_make_category(name="武器"))
        found = repo.get_by_name("武器")
        assert found is not None
        assert found.name == "武器"

    def test_get_by_name_not_found(self, db_connection: sqlite3.Connection) -> None:
        repo = TagCategoryRepository(db_connection)
        assert repo.get_by_name("不存在") is None


class TestListAll:
    def test_list_all_empty(self, db_connection: sqlite3.Connection) -> None:
        repo = TagCategoryRepository(db_connection)
        assert repo.list_all() == []

    def test_list_all_sorted_by_name(self, db_connection: sqlite3.Connection) -> None:
        repo = TagCategoryRepository(db_connection)
        repo.create(_make_category(category_id="c-1", name="武器"))
        repo.create(_make_category(category_id="c-2", name="服装护甲"))
        repo.create(_make_category(category_id="c-3", name="来源"))

        result = repo.list_all()
        # SQLite BINARY 排序（按 Unicode 码点）：服 < 来 < 武
        assert [c.name for c in result] == ["服装护甲", "来源", "武器"]


class TestUpdate:
    def test_update_rename(self, db_connection: sqlite3.Connection) -> None:
        repo = TagCategoryRepository(db_connection)
        repo.create(_make_category(name="旧名"))
        cat = repo.get_by_id("c-1")
        assert cat is not None
        cat.name = "新名"
        updated = repo.update(cat)
        assert updated.name == "新名"

    def test_update_color_hue(self, db_connection: sqlite3.Connection) -> None:
        repo = TagCategoryRepository(db_connection)
        repo.create(_make_category(color_hue=100))
        cat = repo.get_by_id("c-1")
        assert cat is not None
        cat.color_hue = 200
        updated = repo.update(cat)
        assert updated.color_hue == 200

    def test_update_duplicate_name_raises_constraint(
        self, db_connection: sqlite3.Connection
    ) -> None:
        repo = TagCategoryRepository(db_connection)
        repo.create(_make_category(category_id="c-1", name="甲"))
        repo.create(_make_category(category_id="c-2", name="乙"))
        cat = repo.get_by_id("c-2")
        assert cat is not None
        cat.name = "甲"
        with pytest.raises(ConstraintViolationError):
            repo.update(cat)

    def test_update_not_exist_raises_not_found(self, db_connection: sqlite3.Connection) -> None:
        repo = TagCategoryRepository(db_connection)
        with pytest.raises(NotFoundError):
            repo.update(_make_category(category_id="nonexistent", name="ghost"))


class TestDelete:
    def test_delete(self, db_connection: sqlite3.Connection) -> None:
        repo = TagCategoryRepository(db_connection)
        repo.create(_make_category())
        repo.delete("c-1")
        assert repo.get_by_id("c-1") is None

    def test_delete_not_exist_raises_not_found(self, db_connection: sqlite3.Connection) -> None:
        repo = TagCategoryRepository(db_connection)
        with pytest.raises(NotFoundError):
            repo.delete("nonexistent")

    def test_delete_does_not_cascade_tags(self, db_connection: sqlite3.Connection) -> None:
        """delete 仅删除 tag_category 记录，不级联清理 tag。

        级联清理由 application 层（TagService.delete_category）负责，
        避免 Repository 越权。FK 违约时由 Repository 包装为 RepositoryError。
        """
        from infrastructure.repositories.errors import RepositoryError

        repo = TagCategoryRepository(db_connection)
        repo.create(_make_category())
        # 直接插入 tag（绕过 TagRepository 以隔离测试）
        db_connection.execute(
            "INSERT INTO tag (id, name, category_id) VALUES ('t-1', '重甲', 'c-1')"
        )
        db_connection.commit()

        # 直接 delete 会因 FK 违约失败，Repository 捕获并包装为 RepositoryError
        with pytest.raises(RepositoryError):
            repo.delete("c-1")
