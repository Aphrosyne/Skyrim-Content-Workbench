"""SearchRepository（Stage 5 Task 7）。

跨表 LIKE 查询实现全局搜索。

搜索范围（spec §8）：
- content_unit.title（标题）
- content_unit.notes（备注）
- tag.name（标签名，通过 content_unit_tag 关联）

设计决策：
- Q2=B：仅搜索 is_marked=True 的内容单元（v11 重构后，原 status='organized' → is_marked=1）。
  理由：is_marked=False 是用户显式取消标记（不再是内容单元），搜索这些记录对用户无意义。
- Q6=A：单关键词子串匹配（LIKE '%query%'）。
- Q7=B：匹配字段优先级排序（title > tag > notes）。
- Q8=C：不限制结果数量。
- LIKE 通配符（% _ \\）转义，作为字面量匹配。
- 大小写不敏感：LOWER() 双侧转换（ASCII），中文 UTF-8 字节比较天然准确。

SQL 结构：
- WHERE 子句：title / notes / 关联 tag.name 任一 LIKE 命中
- matched_field：CASE WHEN 按优先级取（title > tag > notes）
- tags：子查询 GROUP_CONCAT 聚合该内容单元的所有标签名
- ORDER BY：matched_field 优先级，其次 title
"""

from __future__ import annotations

import logging
import sqlite3

from domain.models import SearchResult
from infrastructure.repositories.errors import RepositoryError

logger = logging.getLogger(__name__)


def _like_escape(s: str) -> str:
    """转义 LIKE 模式中的特殊字符（\\ % _）。

    与 tag.py 的 _like_escape 保持一致，配合 ESCAPE '\\' 子句使用。
    """
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SearchRepository:
    """全局搜索仓储：跨表 LIKE 查询。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def search(self, query: str) -> list[SearchResult]:
        """执行搜索，返回匹配的内容单元列表。

        Args:
            query: 搜索关键词（非空，调用方负责空白过滤）。

        Returns:
            匹配的 SearchResult 列表，按 matched_field 优先级 + title 排序。

        Raises:
            RepositoryError: 数据库查询失败。
        """
        if not query:
            return []

        # 转义 LIKE 通配符，构建 %query% 子串模式
        escaped = _like_escape(query)
        pattern = f"%{escaped}%"

        # SQL：
        # - 主表 content_unit，LEFT JOIN 关联标签用于命中判断
        # - WHERE：title / notes / EXISTS(tag.name) 任一命中
        # - matched_field：CASE 按优先级 title > tag > notes
        # - tags：子查询 GROUP_CONCAT 聚合所有标签名（按 name 排序）
        # - ORDER BY：matched_field 优先级 + title
        sql = """
        SELECT
            cu.id AS unit_id,
            cu.title AS title,
            cu.path AS path,
            cu.content_type AS content_type,
            cu.is_marked AS is_marked,
            CASE
                WHEN LOWER(cu.title) LIKE LOWER(:pattern) ESCAPE '\\' THEN 'title'
                WHEN EXISTS (
                    SELECT 1 FROM content_unit_tag cut
                    JOIN tag t ON cut.tag_id = t.id
                    WHERE cut.content_unit_id = cu.id
                      AND LOWER(t.name) LIKE LOWER(:pattern) ESCAPE '\\'
                ) THEN 'tag'
                WHEN LOWER(cu.notes) LIKE LOWER(:pattern) ESCAPE '\\' THEN 'notes'
                ELSE 'title'
            END AS matched_field,
            COALESCE(
                (SELECT GROUP_CONCAT(t.name, ', ')
                 FROM content_unit_tag cut
                 JOIN tag t ON cut.tag_id = t.id
                 WHERE cut.content_unit_id = cu.id
                 ORDER BY t.name),
                ''
            ) AS tags_str
        FROM content_unit cu
        WHERE cu.is_marked = 1
          AND (
              LOWER(cu.title) LIKE LOWER(:pattern) ESCAPE '\\'
             OR LOWER(cu.notes) LIKE LOWER(:pattern) ESCAPE '\\'
             OR EXISTS (
                 SELECT 1 FROM content_unit_tag cut
                 JOIN tag t ON cut.tag_id = t.id
                 WHERE cut.content_unit_id = cu.id
                   AND LOWER(t.name) LIKE LOWER(:pattern) ESCAPE '\\'
             )
          )
        ORDER BY
            CASE matched_field
                WHEN 'title' THEN 0
                WHEN 'tag' THEN 1
                WHEN 'notes' THEN 2
            END,
            COALESCE(cu.title, cu.path)
        """

        try:
            rows = self._conn.execute(
                sql,
                {"pattern": pattern},
            ).fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"搜索查询失败：{e}") from e

        results: list[SearchResult] = []
        for row in rows:
            tags_str = row["tags_str"] or ""
            tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []
            results.append(
                SearchResult(
                    unit_id=row["unit_id"],
                    title=row["title"],
                    path=row["path"],
                    content_type=row["content_type"],
                    is_marked=bool(row["is_marked"]),
                    matched_field=row["matched_field"],
                    tags=tags,
                )
            )
        return results
