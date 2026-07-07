"""ModItemRepository 测试。"""

from __future__ import annotations

import sqlite3

import pytest

from domain.models import ModItem
from infrastructure.repositories.errors import NotFoundError
from infrastructure.repositories.mod_item import ModItemRepository


def test_create_and_get(db_connection: sqlite3.Connection) -> None:
    repo = ModItemRepository(db_connection)
    item = ModItem(
        id="mod-1",
        created_at="2026-07-07T00:00:00Z",
        updated_at="2026-07-07T00:00:00Z",
        display_name="寒霜之心护甲",
        description="冰霜抗性重型护甲",
        source_url="https://example.com/mods/frost",
        tags={"护甲", "冰霜"},
    )
    created = repo.create(item)
    assert created.id == "mod-1"
    assert created.display_name == "寒霜之心护甲"
    assert created.tags == {"护甲", "冰霜"}

    fetched = repo.get_by_id("mod-1")
    assert fetched is not None
    assert fetched.display_name == "寒霜之心护甲"
    assert fetched.description == "冰霜抗性重型护甲"
    assert fetched.source_url == "https://example.com/mods/frost"
    assert fetched.tags == {"护甲", "冰霜"}


def test_get_by_id_not_found(db_connection: sqlite3.Connection) -> None:
    repo = ModItemRepository(db_connection)
    assert repo.get_by_id("nonexistent") is None


def test_create_with_all_none_fields(db_connection: sqlite3.Connection) -> None:
    repo = ModItemRepository(db_connection)
    item = ModItem(
        id="mod-empty",
        created_at="2026-07-07T00:00:00Z",
        updated_at="2026-07-07T00:00:00Z",
    )
    created = repo.create(item)
    assert created.display_name is None
    assert created.description is None
    assert created.source_url is None
    assert created.category_folder_id is None
    assert created.cover_asset_id is None
    assert created.tags == set()


def test_empty_tags_serialized_as_empty_array(db_connection: sqlite3.Connection) -> None:
    repo = ModItemRepository(db_connection)
    item = ModItem(
        id="mod-no-tags",
        created_at="2026-07-07T00:00:00Z",
        updated_at="2026-07-07T00:00:00Z",
    )
    repo.create(item)
    fetched = repo.get_by_id("mod-no-tags")
    assert fetched is not None
    assert fetched.tags == set()

    # 直接查表，确保存储为 '[]' 而非 'null'
    row = db_connection.execute(
        "SELECT tags FROM mod_item WHERE id = ?", ("mod-no-tags",)
    ).fetchone()
    assert row["tags"] == "[]"


def test_list_all(db_connection: sqlite3.Connection) -> None:
    repo = ModItemRepository(db_connection)
    for i in range(3):
        repo.create(
            ModItem(
                id=f"mod-{i}",
                created_at=f"2026-07-07T00:0{i}:00Z",
                updated_at=f"2026-07-07T00:0{i}:00Z",
                display_name=f"Mod {i}",
            )
        )
    items = repo.list_all()
    assert len(items) == 3
    assert {i.id for i in items} == {"mod-0", "mod-1", "mod-2"}


def test_update(db_connection: sqlite3.Connection) -> None:
    repo = ModItemRepository(db_connection)
    item = ModItem(
        id="mod-update",
        created_at="2026-07-07T00:00:00Z",
        updated_at="2026-07-07T00:00:00Z",
        display_name="旧名",
        tags={"a"},
    )
    repo.create(item)

    item.display_name = "新名"
    item.description = "新说明"
    item.tags = {"a", "b", "c"}
    item.updated_at = "2026-07-08T00:00:00Z"
    updated = repo.update(item)

    assert updated.display_name == "新名"
    assert updated.description == "新说明"
    assert updated.tags == {"a", "b", "c"}
    assert updated.updated_at == "2026-07-08T00:00:00Z"


def test_update_not_found_raises(db_connection: sqlite3.Connection) -> None:
    repo = ModItemRepository(db_connection)
    item = ModItem(
        id="nonexistent",
        created_at="2026-07-07T00:00:00Z",
        updated_at="2026-07-07T00:00:00Z",
    )
    with pytest.raises(NotFoundError):
        repo.update(item)


def test_chinese_tags_roundtrip(db_connection: sqlite3.Connection) -> None:
    repo = ModItemRepository(db_connection)
    tags = {"护甲", "冰霜", "重型"}
    item = ModItem(
        id="mod-cn-tags",
        created_at="2026-07-07T00:00:00Z",
        updated_at="2026-07-07T00:00:00Z",
        tags=tags,
    )
    repo.create(item)
    fetched = repo.get_by_id("mod-cn-tags")
    assert fetched is not None
    assert fetched.tags == tags
