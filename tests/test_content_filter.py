"""ContentFilter 纯函数测试（操作便捷性5 / UI合理性16，2026-08-03）。"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from app.content_filter import filter_entries  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.tag_service import TagService  # noqa: E402
from domain.models import FileEntry  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.repositories.content_unit import (  # noqa: E402
    ContentUnitRepository,
)
from infrastructure.repositories.content_unit_tag import (  # noqa: E402
    ContentUnitTagRepository,
)
from infrastructure.repositories.tag import TagRepository  # noqa: E402
from infrastructure.repositories.tag_category import (  # noqa: E402
    TagCategoryRepository,
)


def _entry(name: str, unit) -> FileEntry:
    return FileEntry(
        name=name,
        path=f"/mods/{name}",
        is_dir=False,
        modified_at="2026-07-13T00:00:00Z",
        content_unit=unit,
    )


@pytest.fixture
def tag_env(tmp_path: Path):
    """真实 TagService + 3 个内容单元（u1/u2/u3），供筛选查询。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    tag_service = TagService(
        TagCategoryRepository(conn),
        TagRepository(conn),
        ContentUnitTagRepository(conn),
    )
    content_service = ContentService(ContentUnitRepository(conn))
    units = []
    for name in ("u1", "u2", "u3"):
        folder = tmp_path / name
        folder.mkdir()
        units.append(content_service.mark_as_content_unit(folder))
    conn.commit()
    yield tag_service, units, conn
    conn.close()


def test_no_filter_returns_all(qapp, tag_env) -> None:
    tag_service, units, _ = tag_env
    entries = [_entry(n, u) for n, u in zip(("a", "b", "c"), units, strict=True)]

    result = filter_entries(
        entries,
        tag_service=tag_service,
        selected_tag_ids=set(),
        excluded_tag_ids=set(),
        cover_only=False,
    )
    assert [e.name for e in result] == ["a", "b", "c"]


def test_cover_only(qapp, tag_env) -> None:
    tag_service, units, _ = tag_env
    entries = [
        _entry("a", replace(units[0], cover_path="cover.jpg")),
        _entry("b", units[1]),
        _entry("c", units[2]),
    ]

    result = filter_entries(
        entries,
        tag_service=tag_service,
        selected_tag_ids=set(),
        excluded_tag_ids=set(),
        cover_only=True,
    )
    assert [e.name for e in result] == ["a"]


def test_tag_positive_filter(qapp, tag_env) -> None:
    tag_service, units, _ = tag_env
    cat = tag_service.create_category("分类")
    tag = tag_service.create_tag("t1", cat.id)
    tag_service.attach_tag_to_unit(units[0].id, tag.id)
    tag_service.attach_tag_to_unit(units[1].id, tag.id)
    entries = [_entry(n, u) for n, u in zip(("a", "b", "c"), units, strict=True)]

    result = filter_entries(
        entries,
        tag_service=tag_service,
        selected_tag_ids={tag.id},
        excluded_tag_ids=set(),
        cover_only=False,
    )
    assert [e.name for e in result] == ["a", "b"]


def test_excluded_tag_without_positive(qapp, tag_env) -> None:
    tag_service, units, _ = tag_env
    cat = tag_service.create_category("分类")
    tag = tag_service.create_tag("t1", cat.id)
    tag_service.attach_tag_to_unit(units[0].id, tag.id)
    tag_service.attach_tag_to_unit(units[1].id, tag.id)
    entries = [_entry(n, u) for n, u in zip(("a", "b", "c"), units, strict=True)]

    result = filter_entries(
        entries,
        tag_service=tag_service,
        selected_tag_ids=set(),
        excluded_tag_ids={tag.id},
        cover_only=False,
    )
    assert [e.name for e in result] == ["c"]


def test_positive_and_excluded_combo(qapp, tag_env) -> None:
    tag_service, units, _ = tag_env
    cat1 = tag_service.create_category("分类1")
    cat2 = tag_service.create_category("分类2")
    t1 = tag_service.create_tag("t1", cat1.id)
    t2 = tag_service.create_tag("t2", cat2.id)
    tag_service.attach_tag_to_unit(units[0].id, t1.id)
    tag_service.attach_tag_to_unit(units[1].id, t1.id)
    tag_service.attach_tag_to_unit(units[1].id, t2.id)
    tag_service.attach_tag_to_unit(units[2].id, t2.id)
    entries = [_entry(n, u) for n, u in zip(("a", "b", "c"), units, strict=True)]

    # 正选 t1（u1,u2）且排除 t2（u2,u3）→ 剩 u1
    result = filter_entries(
        entries,
        tag_service=tag_service,
        selected_tag_ids={t1.id},
        excluded_tag_ids={t2.id},
        cover_only=False,
    )
    assert [e.name for e in result] == ["a"]


def test_multiple_excluded_tags(qapp, tag_env) -> None:
    tag_service, units, _ = tag_env
    cat = tag_service.create_category("分类")
    t1 = tag_service.create_tag("t1", cat.id)
    t2 = tag_service.create_tag("t2", cat.id)
    tag_service.attach_tag_to_unit(units[0].id, t1.id)
    tag_service.attach_tag_to_unit(units[1].id, t2.id)
    tag_service.attach_tag_to_unit(units[2].id, t1.id)
    entries = [_entry(n, u) for n, u in zip(("a", "b", "c"), units, strict=True)]

    # 同时排除 t1 与 t2 → 全部被剔除
    result = filter_entries(
        entries,
        tag_service=tag_service,
        selected_tag_ids=set(),
        excluded_tag_ids={t1.id, t2.id},
        cover_only=False,
    )
    assert result == []
