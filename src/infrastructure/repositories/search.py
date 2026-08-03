"""SearchRepository（Stage 5 Task 7；UI合理性13 搜索范围 title → 文件名）。

跨表搜索实现全局搜索（数据量小，匹配在 Python 侧完成）。

搜索范围（spec §8）：
- content_unit.path 的文件名（basename，UI合理性13 替代原 title 匹配）
- content_unit.notes（备注）
- tag.name（标签名，通过 content_unit_tag 关联）

设计决策：
- Q2=B（原决策）：仅搜索已标记的内容单元。v13（UX 重构 Task 6）移除 is_marked
  字段后该条件自然消失——content_unit 表中有记录即已标记，取消标记 = DELETE 记录，
  无需额外过滤。
- Q6=A：单关键词子串匹配（原 LIKE '%query%' 语义）。
- Q7=B：匹配字段优先级排序（name > tag > notes）。
- Q8=C：不限制结果数量。
- 大小写不敏感（ASCII），中文天然准确。

实现说明（UI合理性13）：
- 原实现用 SQL LIKE 匹配 content_unit.title；title 停用后改为匹配真实文件名。
  SQLite 无内置 basename / reverse（3.50 验证），且 title 列不再写入新值，
  故在 Python 侧计算 basename 并做子串匹配，行为与原 LIKE 转义后一致。
"""

from __future__ import annotations

import logging
import sqlite3

from domain.models import SearchResult
from infrastructure.repositories.errors import RepositoryError

logger = logging.getLogger(__name__)


def _basename(path: str) -> str:
    """返回路径的文件名部分（兼容 \\ 与 / 分隔符，无分隔符时返回原路径）。"""
    for sep in ("\\", "/"):
        pos = path.rfind(sep)
        if pos >= 0:
            return path[pos + 1 :]
    return path


class SearchRepository:
    """全局搜索仓储：文件名 + 备注 + 标签名匹配。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def search(self, query: str) -> list[SearchResult]:
        """执行搜索，返回匹配的内容单元列表。

        Args:
            query: 搜索关键词（非空，调用方负责空白过滤）。

        Returns:
            匹配的 SearchResult 列表，按 matched_field 优先级 + 文件名排序。

        Raises:
            RepositoryError: 数据库查询失败。
        """
        if not query:
            return []

        needle = query.casefold()

        # 1. 一次性读取全部内容单元（id/path/content_type/notes）与标签关联，
        #    在 Python 侧完成匹配与聚合（数据量小，避免 SQLite 无 basename 的兼容问题）。
        try:
            unit_rows = self._conn.execute(
                "SELECT id, path, content_type, notes FROM content_unit"
            ).fetchall()
            tag_rows = self._conn.execute(
                "SELECT cut.content_unit_id AS unit_id, t.name AS name "
                "FROM content_unit_tag cut JOIN tag t ON cut.tag_id = t.id "
                "ORDER BY t.name"
            ).fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"搜索查询失败：{e}") from e

        # 标签按内容单元聚合（保持原 GROUP_CONCAT 的按名排序语义）
        tags_by_unit: dict[str, list[str]] = {}
        for row in tag_rows:
            tags_by_unit.setdefault(row["unit_id"], []).append(row["name"])

        # 2. 匹配：文件名 / 标签 / 备注，优先级 name > tag > notes
        results: list[SearchResult] = []
        for row in unit_rows:
            unit_id = row["id"]
            path = row["path"]
            name = _basename(path)
            tags = tags_by_unit.get(unit_id, [])

            if needle in name.casefold():
                matched_field = "name"
            elif any(needle in tag.casefold() for tag in tags):
                matched_field = "tag"
            elif row["notes"] and needle in row["notes"].casefold():
                matched_field = "notes"
            else:
                continue

            results.append(
                SearchResult(
                    unit_id=unit_id,
                    name=name,
                    path=path,
                    content_type=row["content_type"],
                    matched_field=matched_field,
                    tags=tags,
                )
            )

        # 3. 排序：matched_field 优先级 + 文件名（与原 title 排序语义一致）
        field_priority = {"name": 0, "tag": 1, "notes": 2}
        results.sort(key=lambda r: (field_priority[r.matched_field], r.name.casefold(), r.name))
        return results
