"""中栏内容筛选（操作便捷性5 / UI合理性16，2026-08-03）。

把 MainWindow 的筛选组合逻辑（标签正选 + 反选排除 + 封面筛选）抽为纯函数，
MainWindow 只负责把 TagFilterBar / 封面按钮状态喂进来。

规则：
- 标签正选：跨分类 AND、同分类 OR（filter_unit_ids_by_category_and）
- 标签反选（排除）：在正选结果中剔除带有该标签的单元；无正选时以
  当前目录全部内容单元为基准剔除
- 封面筛选：仅保留有封面（cover_path 非空）的内容单元
"""

from __future__ import annotations

import logging

from application.tag_service import TagService
from domain.models import FileEntry

logger = logging.getLogger(__name__)


def filter_entries(
    entries: list[FileEntry],
    *,
    tag_service: TagService | None,
    selected_tag_ids: set[str],
    excluded_tag_ids: set[str],
    cover_only: bool,
) -> list[FileEntry]:
    """按标签（正选/反选）与封面筛选过滤条目。

    tag_service 仅在存在标签筛选（正选或反选）时使用；缺省时该部分跳过。
    """
    result = list(entries)

    # 标签筛选（正选 + 反选）
    if selected_tag_ids or excluded_tag_ids:
        if tag_service is None:
            logger.warning("标签筛选激活但未注入 TagService，跳过标签筛选")
            allowed: set[str] | None = None
        else:
            allowed = None
            try:
                if selected_tag_ids:
                    allowed = tag_service.filter_unit_ids_by_category_and(list(selected_tag_ids))
                if excluded_tag_ids:
                    excluded_ids = tag_service.list_content_unit_ids_by_tags(list(excluded_tag_ids))
                    all_unit_ids = {e.content_unit.id for e in result if e.content_unit}
                    base = allowed if allowed is not None else all_unit_ids
                    allowed = base - excluded_ids
            except Exception:  # noqa: BLE001
                logger.exception("标签筛选失败，回退到无筛选")
                allowed = None
        if allowed is not None:
            result = [
                e for e in result if e.content_unit is not None and e.content_unit.id in allowed
            ]

    # 封面筛选（只看有封面）
    if cover_only:
        result = [e for e in result if e.content_unit is not None and e.content_unit.cover_path]
    return result
