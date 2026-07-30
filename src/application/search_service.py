"""SearchService（Stage 5 Task 7）。

全局搜索服务：查询内容单元的标题 / 标签名 / 备注。

spec §8：搜索仅针对数据库中的内容单元元数据，不搜索文件系统。
Q1=A：回车触发（service 不关心触发方式，由 UI 层处理）。
Q2=A：搜索所有状态的内容单元（含 unmarked / missing）。
Q6=A：单关键词子串匹配。
Q7=B：匹配字段优先级排序（title > tag > notes），由 Repository 实现。
Q8=C：不限制结果数量。

职责：
- 预处理查询（strip / 空白过滤）
- 委托 SearchRepository 执行查询
- 异常转换：RepositoryError → SearchError（用户友好消息）
"""

from __future__ import annotations

import logging

from application.errors import SearchError
from domain.models import SearchResult
from infrastructure.repositories.errors import RepositoryError
from infrastructure.repositories.search import SearchRepository

logger = logging.getLogger(__name__)


class SearchService:
    """全局搜索服务。"""

    def __init__(self, search_repo: SearchRepository) -> None:
        """初始化 SearchService。

        Args:
            search_repo: SearchRepository 实例。
        """
        self._repo = search_repo

    def search(self, query: str) -> list[SearchResult]:
        """执行全局搜索。

        Args:
            query: 搜索关键词。空白字符串返回空列表（不触发查询）。

        Returns:
            匹配的 SearchResult 列表，按 matched_field 优先级 + title 排序。

        Raises:
            SearchError: 查询失败（数据库错误等）。
        """
        # 预处理：strip 后空字符串不查询
        normalized = query.strip() if query else ""
        if not normalized:
            return []

        try:
            return self._repo.search(normalized)
        except RepositoryError as e:
            logger.exception("搜索查询失败：query=%s", normalized)
            raise SearchError(f"搜索失败：{e}") from e
        except Exception as e:  # noqa: BLE001 - 兜底，确保 UI 收到友好错误
            logger.exception("搜索发生未预期异常：query=%s", normalized)
            raise SearchError(f"搜索发生未预期错误：{e}") from e
