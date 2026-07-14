"""ContentUnitRepository 测试。

覆盖 CRUD、path 唯一约束、中文路径、list_by_path_prefix。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from domain.models import ContentUnit
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.errors import (
    ConstraintViolationError,
    NotFoundError,
)


@pytest.fixture
def repo(db_connection: sqlite3.Connection) -> ContentUnitRepository:
    return ContentUnitRepository(db_connection)


def _make_unit(
    unit_id: str = "u-1",
    path: str = "/mods/armor",
    **kwargs,
) -> ContentUnit:
    defaults = {
        "id": unit_id,
        "path": path,
        "created_at": "2026-07-12T00:00:00Z",
        "updated_at": "2026-07-12T00:00:00Z",
    }
    defaults.update(kwargs)
    return ContentUnit(**defaults)


class TestCreateAndGet:
    def test_create_and_get_by_id(self, repo: ContentUnitRepository) -> None:
        unit = _make_unit()
        created = repo.create(unit)
        assert created.id == "u-1"

        fetched = repo.get_by_id("u-1")
        assert fetched is not None
        assert fetched.path == "/mods/armor"
        assert fetched.status == "unorganized"

    def test_get_by_id_not_exist(self, repo: ContentUnitRepository) -> None:
        assert repo.get_by_id("nonexistent") is None

    def test_get_by_path(self, repo: ContentUnitRepository) -> None:
        repo.create(_make_unit(path="/mods/护甲"))
        fetched = repo.get_by_path("/mods/护甲")
        assert fetched is not None
        assert fetched.path == "/mods/护甲"

    def test_get_by_path_not_exist(self, repo: ContentUnitRepository) -> None:
        assert repo.get_by_path("/nonexistent") is None

    def test_chinese_path(self, repo: ContentUnitRepository) -> None:
        repo.create(_make_unit(path="D:/Mods/护甲/寒霜之心"))
        fetched = repo.get_by_path("D:/Mods/护甲/寒霜之心")
        assert fetched is not None
        assert "护甲" in fetched.path


class TestPathUniqueConstraint:
    def test_duplicate_path_raises(self, repo: ContentUnitRepository) -> None:
        repo.create(_make_unit(unit_id="u-1", path="/mods/a"))
        with pytest.raises(ConstraintViolationError):
            repo.create(_make_unit(unit_id="u-2", path="/mods/a"))

    def test_same_id_raises(self, repo: ContentUnitRepository) -> None:
        repo.create(_make_unit(unit_id="u-1", path="/mods/a"))
        with pytest.raises(ConstraintViolationError):
            repo.create(_make_unit(unit_id="u-1", path="/mods/b"))


class TestListByPathPrefix:
    def test_list_by_path_prefix_includes_self_and_children(
        self, repo: ContentUnitRepository
    ) -> None:
        # 使用 str(Path(...)) 构造路径，适配 OS 分隔符
        mods = str(Path("/mods"))
        armor = str(Path("/mods/armor"))
        armor_sub = str(Path("/mods/armor/sub"))
        other = str(Path("/other"))
        repo.create(_make_unit(unit_id="u-1", path=mods))
        repo.create(_make_unit(unit_id="u-2", path=armor))
        repo.create(_make_unit(unit_id="u-3", path=armor_sub))
        repo.create(_make_unit(unit_id="u-4", path=other))

        result = repo.list_by_path_prefix(mods)
        paths = {u.path for u in result}
        assert mods in paths
        assert armor in paths
        assert armor_sub in paths
        assert other not in paths

    def test_list_by_path_prefix_empty(self, repo: ContentUnitRepository) -> None:
        result = repo.list_by_path_prefix(str(Path("/nonexistent")))
        assert result == []

    def test_list_by_path_prefix_underscore_not_treated_as_wildcard(
        self, repo: ContentUnitRepository
    ) -> None:
        """路径中的 _ 不应被 LIKE 解释为单字符通配符（TD-H6）。

        构造两个仅 _ 位置字符不同的目录：my_mods / myxmods。
        若未转义，查询 my_mods 会错误匹配 myxmods。
        """
        mods_with_underscore = str(Path("/mods/my_mods"))
        mods_with_x = str(Path("/mods/myxmods"))
        mods_parent = str(Path("/mods"))
        repo.create(_make_unit(unit_id="u-1", path=str(Path("/mods/my_mods/sub.7z"))))
        repo.create(_make_unit(unit_id="u-2", path=str(Path("/mods/myxmods/other.7z"))))

        result = repo.list_by_path_prefix(mods_with_underscore)
        paths = {u.path for u in result}
        assert str(Path("/mods/my_mods/sub.7z")) in paths
        assert str(Path("/mods/myxmods/other.7z")) not in paths

        # 反向验证：查询 myxmods 不应匹配 my_mods
        result_x = repo.list_by_path_prefix(mods_with_x)
        paths_x = {u.path for u in result_x}
        assert str(Path("/mods/myxmods/other.7z")) in paths_x
        assert str(Path("/mods/my_mods/sub.7z")) not in paths_x

        # 验证父目录查询仍能返回两者
        result_parent = repo.list_by_path_prefix(mods_parent)
        paths_parent = {u.path for u in result_parent}
        assert len(paths_parent) == 2

    def test_list_by_path_prefix_percent_not_treated_as_wildcard(
        self, repo: ContentUnitRepository
    ) -> None:
        """路径中的 % 不应被 LIKE 解释为任意字符串通配符（TD-H6）。"""
        mods_with_percent = str(Path("/mods/100%_pack"))
        repo.create(_make_unit(unit_id="u-1", path=str(Path("/mods/100%_pack/mod.7z"))))
        repo.create(_make_unit(unit_id="u-2", path=str(Path("/mods/other/mod.7z"))))

        result = repo.list_by_path_prefix(mods_with_percent)
        paths = {u.path for u in result}
        assert str(Path("/mods/100%_pack/mod.7z")) in paths
        assert str(Path("/mods/other/mod.7z")) not in paths


class TestListAll:
    def test_list_all_ordered_by_path(self, repo: ContentUnitRepository) -> None:
        repo.create(_make_unit(unit_id="u-2", path="/mods/b"))
        repo.create(_make_unit(unit_id="u-1", path="/mods/a"))
        result = repo.list_all()
        assert len(result) == 2
        assert result[0].path == "/mods/a"
        assert result[1].path == "/mods/b"

    def test_list_all_empty(self, repo: ContentUnitRepository) -> None:
        assert repo.list_all() == []


class TestUpdate:
    def test_update_fields(self, repo: ContentUnitRepository) -> None:
        repo.create(_make_unit())
        unit = repo.get_by_id("u-1")
        assert unit is not None

        unit.title = "新标题"
        unit.status = "organized"
        unit.rating = 5
        unit.updated_at = "2026-07-13T00:00:00Z"
        updated = repo.update(unit)

        assert updated.title == "新标题"
        assert updated.status == "organized"
        assert updated.rating == 5

    def test_update_not_exist_raises(self, repo: ContentUnitRepository) -> None:
        unit = _make_unit(unit_id="nonexistent")
        with pytest.raises(NotFoundError):
            repo.update(unit)


class TestDelete:
    def test_delete(self, repo: ContentUnitRepository) -> None:
        repo.create(_make_unit())
        repo.delete("u-1")
        assert repo.get_by_id("u-1") is None

    def test_delete_not_exist_raises(self, repo: ContentUnitRepository) -> None:
        with pytest.raises(NotFoundError):
            repo.delete("nonexistent")

    def test_delete_does_not_affect_others(self, repo: ContentUnitRepository) -> None:
        repo.create(_make_unit(unit_id="u-1", path="/a"))
        repo.create(_make_unit(unit_id="u-2", path="/b"))
        repo.delete("u-1")
        assert repo.get_by_id("u-2") is not None
