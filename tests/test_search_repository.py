"""SearchRepository 测试（Stage 5 Task 7；UI合理性13 标题 → 文件名）。

覆盖：
- 文件名匹配 / 备注匹配 / 标签匹配
- title 列已随 schema v15 删除，搜索仅按文件名/备注/标签
- 多字段同时匹配 → 单条记录，matched_field 取优先级（name > tag > notes, Q7=B）
- 大小写不敏感（ASCII）
- 中文搜索
- % / _ 作为字面量（Python 子串匹配，无 LIKE 通配符语义）
- 空查询返回空列表
- 无匹配返回空列表
- 标签聚合
- 搜索结果覆盖全部记录（v13 纯 DELETE 模式：记录存在即已标记）
- 结果按 matched_field 优先级 + 文件名排序
"""

from __future__ import annotations

import sqlite3

import pytest

from domain.models import SearchResult
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.search import SearchRepository


@pytest.fixture
def search_repo(db_connection) -> SearchRepository:
    return SearchRepository(db_connection)


def _create_unit(
    conn: sqlite3.Connection,
    unit_id: str,
    path: str,
    notes: str | None = None,
    content_type: str = "mod",
) -> None:
    """插入内容单元记录（v13 schema：纯 DELETE 模式，记录存在即已标记）。"""
    conn.execute(
        "INSERT INTO content_unit (id, path, path_key, notes, "
        "content_type, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            unit_id,
            path,
            make_path_key(path),
            notes,
            content_type,
            "2026-07-30T00:00:00Z",
            "2026-07-30T00:00:00Z",
        ),
    )
    conn.commit()


def _create_tag(
    conn: sqlite3.Connection,
    tag_id: str,
    name: str,
    category_id: str = "cat1",
) -> None:
    """插入标签（含分类）。"""
    conn.execute(
        "INSERT INTO tag_category (id, name, color_hex) VALUES (?, ?, '#D61A1A') "
        "ON CONFLICT(id) DO NOTHING",
        (category_id, category_id),
    )
    conn.execute(
        "INSERT INTO tag (id, name, category_id) VALUES (?, ?, ?)",
        (tag_id, name, category_id),
    )
    conn.commit()


def _attach_tag(conn: sqlite3.Connection, unit_id: str, tag_id: str) -> None:
    """关联内容单元与标签。"""
    conn.execute(
        "INSERT INTO content_unit_tag (content_unit_id, tag_id) VALUES (?, ?)",
        (unit_id, tag_id),
    )
    conn.commit()


class TestSearchByField:
    """按字段匹配测试。"""

    def test_match_name(self, search_repo, db_connection) -> None:
        """文件名含关键词 → 命中，matched_field='name'。"""
        _create_unit(db_connection, "u1", "D:/寒霜之心.7z")

        results = search_repo.search("寒霜")

        assert len(results) == 1
        assert results[0].unit_id == "u1"
        assert results[0].matched_field == "name"

    def test_match_notes(self, search_repo, db_connection) -> None:
        """备注含关键词 → 命中，matched_field='notes'。"""
        _create_unit(db_connection, "u1", "D:/mod1.7z", notes="这是一个测试备注")

        results = search_repo.search("测试")

        assert len(results) == 1
        assert results[0].matched_field == "notes"

    def test_match_tag(self, search_repo, db_connection) -> None:
        """标签名含关键词 → 命中，matched_field='tag'。"""
        _create_unit(db_connection, "u1", "D:/mod1.7z")
        _create_tag(db_connection, "t1", "重甲")
        _attach_tag(db_connection, "u1", "t1")

        results = search_repo.search("重甲")

        assert len(results) == 1
        assert results[0].unit_id == "u1"
        assert results[0].matched_field == "tag"
        assert "重甲" in results[0].tags


class TestMultiFieldMatch:
    """多字段匹配测试（Q7=B 优先级）。"""

    def test_name_takes_priority(self, search_repo, db_connection) -> None:
        """文件名 + 标签 + 备注都匹配 → matched_field='name'（最高优先级）。"""
        _create_unit(
            db_connection,
            "u1",
            "D:/测试名.7z",
            notes="测试备注",
        )
        _create_tag(db_connection, "t1", "测试标签")
        _attach_tag(db_connection, "u1", "t1")

        results = search_repo.search("测试")

        assert len(results) == 1
        assert results[0].matched_field == "name"

    def test_tag_takes_priority_over_notes(self, search_repo, db_connection) -> None:
        """标签 + 备注匹配（文件名不匹配）→ matched_field='tag'。"""
        _create_unit(
            db_connection,
            "u1",
            "D:/mod1.7z",
            notes="测试备注",
        )
        _create_tag(db_connection, "t1", "测试标签")
        _attach_tag(db_connection, "u1", "t1")

        results = search_repo.search("测试")

        assert len(results) == 1
        assert results[0].matched_field == "tag"


class TestCaseInsensitive:
    """大小写不敏感测试。"""

    def test_ascii_case_insensitive(self, search_repo, db_connection) -> None:
        """ASCII 大小写不敏感：文件名大写 → 搜小写可命中。"""
        _create_unit(db_connection, "u1", "D:/Frost Armor.7z")

        results_lower = search_repo.search("frost")
        results_upper = search_repo.search("FROST")

        assert len(results_lower) == 1
        assert len(results_upper) == 1


class TestChineseSearch:
    """中文搜索测试。"""

    def test_chinese_name(self, search_repo, db_connection) -> None:
        """中文文件名搜索正常。"""
        _create_unit(db_connection, "u1", "D:/中文/寒霜.7z")

        results = search_repo.search("寒霜")

        assert len(results) == 1
        assert results[0].name == "寒霜.7z"

    def test_chinese_notes(self, search_repo, db_connection) -> None:
        """中文备注搜索正常。"""
        _create_unit(db_connection, "u1", "D:/mod.7z", notes="这是中文备注内容")

        results = search_repo.search("中文")

        assert len(results) == 1
        assert results[0].matched_field == "notes"

    def test_chinese_tag(self, search_repo, db_connection) -> None:
        """中文标签搜索正常。"""
        _create_unit(db_connection, "u1", "D:/mod.7z")
        _create_tag(db_connection, "t1", "重甲")
        _attach_tag(db_connection, "u1", "t1")

        results = search_repo.search("重甲")

        assert len(results) == 1
        assert "重甲" in results[0].tags


class TestLiteralSubstring:
    """字面量子串匹配测试（无 LIKE 通配符语义）。"""

    def test_percent_literal(self, search_repo, db_connection) -> None:
        """关键词含 % → 作为字面量匹配。"""
        _create_unit(db_connection, "u1", "D:/100%完成.7z")

        results = search_repo.search("100%")

        assert len(results) == 1
        assert results[0].name == "100%完成.7z"

    def test_underscore_literal(self, search_repo, db_connection) -> None:
        """关键词含 _ → 作为字面量匹配。"""
        _create_unit(db_connection, "u1", "D:/test_001.7z")

        results = search_repo.search("test_0")

        assert len(results) == 1
        assert results[0].name == "test_001.7z"


class TestEmptyAndNoMatch:
    """空查询和无匹配测试。"""

    def test_empty_query_returns_empty(self, search_repo, db_connection) -> None:
        """空字符串查询返回空列表。"""
        _create_unit(db_connection, "u1", "D:/测试.7z")

        assert search_repo.search("") == []

    def test_no_match_returns_empty(self, search_repo, db_connection) -> None:
        """无匹配返回空列表。"""
        _create_unit(db_connection, "u1", "D:/mod1.7z")

        assert search_repo.search("不存在的关键词") == []


class TestTagAggregation:
    """标签聚合测试。"""

    def test_multiple_tags_aggregated(self, search_repo, db_connection) -> None:
        """多个标签聚合显示。"""
        _create_unit(db_connection, "u1", "D:/测试.7z")
        _create_tag(db_connection, "t1", "重甲")
        _create_tag(db_connection, "t2", "女性")
        _create_tag(db_connection, "t3", "HDT")
        _attach_tag(db_connection, "u1", "t1")
        _attach_tag(db_connection, "u1", "t2")
        _attach_tag(db_connection, "u1", "t3")

        results = search_repo.search("测试")

        assert len(results) == 1
        assert len(results[0].tags) == 3
        assert "重甲" in results[0].tags
        assert "女性" in results[0].tags
        assert "HDT" in results[0].tags

    def test_no_tags_returns_empty_list(self, search_repo, db_connection) -> None:
        """无标签的内容单元 → tags 为空列表。"""
        _create_unit(db_connection, "u1", "D:/测试.7z")

        results = search_repo.search("测试")

        assert len(results) == 1
        assert results[0].tags == []


class TestSorting:
    """结果排序测试（Q7=B matched_field 优先级 + 文件名）。"""

    def test_sorted_by_field_priority(self, search_repo, db_connection) -> None:
        """按 matched_field 优先级排序：name < tag < notes。"""
        # u3: 仅 notes 匹配（最低优先级）
        _create_unit(db_connection, "u3", "D:/mod3.7z", notes="测试备注")
        # u1: 文件名匹配（最高优先级）
        _create_unit(db_connection, "u1", "D:/测试名.7z")
        # u2: 仅 tag 匹配（中等优先级）
        _create_unit(db_connection, "u2", "D:/mod2.7z")
        _create_tag(db_connection, "t1", "测试标签")
        _attach_tag(db_connection, "u2", "t1")

        results = search_repo.search("测试")

        assert len(results) == 3
        assert results[0].unit_id == "u1"  # name 优先级最高
        assert results[0].matched_field == "name"
        assert results[1].unit_id == "u2"  # tag 次之
        assert results[1].matched_field == "tag"
        assert results[2].unit_id == "u3"  # notes 最低
        assert results[2].matched_field == "notes"

    def test_same_field_sorted_by_name(self, search_repo, db_connection) -> None:
        """相同 matched_field 内按文件名升序排序。"""
        _create_unit(db_connection, "u1", "D:/b.7z")
        _create_unit(db_connection, "u2", "D:/a.7z")

        results = search_repo.search("7z")

        assert len(results) == 2
        assert results[0].name == "a.7z"
        assert results[1].name == "b.7z"


class TestDuplicateHandling:
    """重复行处理测试。"""

    def test_multiple_tags_match_returns_single_row(self, search_repo, db_connection) -> None:
        """一个内容单元的多个标签都匹配关键词 → 只返回一行。"""
        _create_unit(db_connection, "u1", "D:/测试.7z")
        _create_tag(db_connection, "t1", "测试标签A")
        _create_tag(db_connection, "t2", "测试标签B")
        _attach_tag(db_connection, "u1", "t1")
        _attach_tag(db_connection, "u1", "t2")

        results = search_repo.search("测试")

        assert len(results) == 1
        assert results[0].unit_id == "u1"
        # 两个标签都被聚合
        assert "测试标签A" in results[0].tags
        assert "测试标签B" in results[0].tags


class TestResultModel:
    """SearchResult 模型字段验证测试。"""

    def test_invalid_matched_field_raises(self) -> None:
        """matched_field 非法值 → ValueError。"""
        with pytest.raises(ValueError, match="matched_field"):
            SearchResult(
                unit_id="u1",
                name="测试",
                path="D:/mod.7z",
                content_type="mod",
                matched_field="invalid",
                tags=[],
            )

    def test_empty_unit_id_raises(self) -> None:
        """unit_id 为空 → ValueError。"""
        with pytest.raises(ValueError, match="unit_id"):
            SearchResult(
                unit_id="",
                name="测试",
                path="D:/mod.7z",
                content_type="mod",
                matched_field="name",
                tags=[],
            )

    def test_empty_path_raises(self) -> None:
        """path 为空 → ValueError。"""
        with pytest.raises(ValueError, match="path"):
            SearchResult(
                unit_id="u1",
                name="测试",
                path="",
                content_type="mod",
                matched_field="name",
                tags=[],
            )
