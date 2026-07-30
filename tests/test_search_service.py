"""SearchService 测试（Stage 5 Task 7）。

覆盖：
- 空白查询返回空列表（不触发 Repository 调用）
- 正常查询 → 委托 Repository
- Repository 抛 RepositoryError → 转换为 SearchError
- 其他异常 → 转换为 SearchError
- strip 处理（前后空格）
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from application.errors import SearchError
from application.search_service import SearchService
from domain.models import SearchResult
from infrastructure.repositories.errors import RepositoryError


def _make_result(unit_id: str = "u1", title: str = "测试") -> SearchResult:
    """构造测试用 SearchResult。"""
    return SearchResult(
        unit_id=unit_id,
        title=title,
        path=f"D:/mod/{unit_id}.7z",
        content_type="mod",
        status="organized",
        matched_field="title",
        tags=["标签"],
    )


class TestEmptyQuery:
    """空白查询测试。"""

    def test_empty_string_returns_empty(self) -> None:
        """空字符串 → 空列表。"""
        repo = MagicMock()
        service = SearchService(repo)

        results = service.search("")

        assert results == []
        repo.search.assert_not_called()

    def test_whitespace_only_returns_empty(self) -> None:
        """纯空白字符串 → strip 后为空 → 空列表。"""
        repo = MagicMock()
        service = SearchService(repo)

        results = service.search("   ")

        assert results == []
        repo.search.assert_not_called()

    def test_none_returns_empty(self) -> None:
        """None → 空列表（防御性处理）。"""
        repo = MagicMock()
        service = SearchService(repo)

        results = service.search(None)  # type: ignore[arg-type]

        assert results == []
        repo.search.assert_not_called()


class TestNormalQuery:
    """正常查询测试。"""

    def test_delegates_to_repository(self) -> None:
        """正常查询 → 委托 Repository.search。"""
        expected = [_make_result("u1"), _make_result("u2")]
        repo = MagicMock()
        repo.search.return_value = expected
        service = SearchService(repo)

        results = service.search("测试")

        assert results == expected
        repo.search.assert_called_once_with("测试")

    def test_strips_query(self) -> None:
        """前后空格被 strip。"""
        repo = MagicMock()
        repo.search.return_value = []
        service = SearchService(repo)

        service.search("  测试  ")

        repo.search.assert_called_once_with("测试")


class TestErrorHandling:
    """异常处理测试。"""

    def test_repository_error_converted(self) -> None:
        """RepositoryError → SearchError。"""
        repo = MagicMock()
        repo.search.side_effect = RepositoryError("DB 错误")
        service = SearchService(repo)

        with pytest.raises(SearchError, match="搜索失败"):
            service.search("测试")

    def test_unexpected_error_converted(self) -> None:
        """其他异常 → SearchError。"""
        repo = MagicMock()
        repo.search.side_effect = RuntimeError("未预期错误")
        service = SearchService(repo)

        with pytest.raises(SearchError, match="未预期错误"):
            service.search("测试")

    def test_empty_query_does_not_raise(self) -> None:
        """空白查询不触发 Repository，即使 Repository 会抛异常也不报错。"""
        repo = MagicMock()
        repo.search.side_effect = RepositoryError("DB 错误")
        service = SearchService(repo)

        # 空白不触发 Repository，不抛异常
        results = service.search("")
        assert results == []
        repo.search.assert_not_called()
