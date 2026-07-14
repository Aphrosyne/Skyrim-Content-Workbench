"""StagingService 测试。

覆盖：
- 标记合法目录；
- 拒绝不存在路径；
- 拒绝非目录路径；
- 重复标记处理；
- 嵌套检查（祖先/子目录）；
- 取消标记；
- list_staging / get_staging / is_staging；
- 中文路径；
- 重启后保留。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from application.errors import (
    DuplicateStagingAreaError,
    StagingAreaNestingError,
    StagingAreaNotFoundError,
)
from application.staging_service import StagingService
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.staging_area import StagingAreaRepository


def test_mark_staging_legal_directory(db_connection, tmp_path: Path) -> None:
    """合法目录可标记为暂存区。"""
    repo = StagingAreaRepository(db_connection)
    service = StagingService(
        repo,
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=lambda: "uuid-1",
    )
    stash = tmp_path / "Stash"
    stash.mkdir()

    staging = service.mark_staging(stash)

    assert staging.id == "uuid-1"
    assert staging.real_path == str(stash)
    assert staging.path_key == make_path_key(stash)
    assert staging.display_name == "Stash"
    assert staging.created_at == "2026-07-14T00:00:00Z"


def test_mark_staging_chinese_path(db_connection, tmp_path: Path) -> None:
    """中文路径可正常标记。"""
    repo = StagingAreaRepository(db_connection)
    service = StagingService(
        repo,
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=lambda: "uuid-cn",
    )
    path = tmp_path / "暂存区"
    path.mkdir()

    staging = service.mark_staging(path)
    assert staging.real_path == str(path)
    assert staging.display_name == "暂存区"
    assert "暂存区" in staging.real_path


def test_mark_staging_rejects_nonexistent_path(db_connection, tmp_path: Path) -> None:
    """路径不存在应拒绝。"""
    repo = StagingAreaRepository(db_connection)
    service = StagingService(repo)
    nonexistent = tmp_path / "DoesNotExist"

    with pytest.raises(StagingAreaNotFoundError):
        service.mark_staging(nonexistent)


def test_mark_staging_rejects_non_directory_path(db_connection, tmp_path: Path) -> None:
    """非目录路径应拒绝。"""
    repo = StagingAreaRepository(db_connection)
    service = StagingService(repo)
    file_path = tmp_path / "file.txt"
    file_path.write_text("not a directory", encoding="utf-8")

    with pytest.raises(StagingAreaNotFoundError):
        service.mark_staging(file_path)


def test_mark_staging_rejects_duplicate(db_connection, tmp_path: Path) -> None:
    """同一路径不能重复标记。"""
    repo = StagingAreaRepository(db_connection)
    service = StagingService(
        repo,
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=lambda: "uuid-dup",
    )
    stash = tmp_path / "Stash"
    stash.mkdir()

    first = service.mark_staging(stash)
    assert first.id == "uuid-dup"

    with pytest.raises(DuplicateStagingAreaError):
        service.mark_staging(stash)


def test_mark_staging_rejects_descendant_of_existing(db_connection, tmp_path: Path) -> None:
    """子目录嵌套：祖先已是暂存区时拒绝标记后代。"""
    repo = StagingAreaRepository(db_connection)
    service = StagingService(
        repo,
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=lambda: "uuid-nest",
    )
    parent = tmp_path / "Parent"
    parent.mkdir()
    child = parent / "Child"
    child.mkdir()

    service.mark_staging(parent)

    with pytest.raises(StagingAreaNestingError) as exc:
        service.mark_staging(child)
    assert "祖先目录已是暂存区" in str(exc.value)


def test_mark_staging_rejects_ancestor_of_existing(db_connection, tmp_path: Path) -> None:
    """父目录嵌套：子目录已是暂存区时拒绝标记祖先。"""
    repo = StagingAreaRepository(db_connection)
    service = StagingService(
        repo,
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=lambda: "uuid-nest",
    )
    parent = tmp_path / "Parent"
    parent.mkdir()
    child = parent / "Child"
    child.mkdir()

    service.mark_staging(child)

    with pytest.raises(StagingAreaNestingError) as exc:
        service.mark_staging(parent)
    assert "子目录已是暂存区" in str(exc.value)


def test_mark_staging_does_not_modify_target_directory(db_connection, tmp_path: Path) -> None:
    """标记暂存区不应修改目标目录或其中文件。"""
    repo = StagingAreaRepository(db_connection)
    service = StagingService(repo)
    target = tmp_path / "Stash"
    target.mkdir()
    (target / "marker.txt").write_text("keep-me", encoding="utf-8")

    service.mark_staging(target)

    assert (target / "marker.txt").read_text(encoding="utf-8") == "keep-me"


def test_unmark_staging_deletes_record(db_connection, tmp_path: Path) -> None:
    """取消标记后该暂存区不再可查。"""
    repo = StagingAreaRepository(db_connection)
    service = StagingService(
        repo,
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=lambda: "uuid-unmark",
    )
    stash = tmp_path / "Stash"
    stash.mkdir()
    created = service.mark_staging(stash)

    service.unmark_staging(created.id)

    assert service.list_staging() == []


def test_unmark_staging_missing_raises(db_connection) -> None:
    """取消不存在的暂存区抛 StagingAreaNotFoundError。"""
    repo = StagingAreaRepository(db_connection)
    service = StagingService(repo)

    with pytest.raises(StagingAreaNotFoundError):
        service.unmark_staging("nonexistent-id")


def test_unmark_staging_preserves_real_directory(db_connection, tmp_path: Path) -> None:
    """取消暂存区标记后真实目录与文件不变。"""
    repo = StagingAreaRepository(db_connection)
    service = StagingService(
        repo,
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=lambda: "uuid-preserve",
    )
    target = tmp_path / "Stash"
    target.mkdir()
    marker = target / "marker.txt"
    marker.write_text("keep-me", encoding="utf-8")

    created = service.mark_staging(target)
    service.unmark_staging(created.id)

    assert marker.read_text(encoding="utf-8") == "keep-me"
    assert target.exists()
    assert target.is_dir()


def test_list_staging_empty(db_connection) -> None:
    """空库返回空列表。"""
    repo = StagingAreaRepository(db_connection)
    service = StagingService(repo)
    assert service.list_staging() == []


def test_list_staging_returns_all(db_connection, tmp_path: Path) -> None:
    """list_staging 返回全部暂存区。"""
    repo = StagingAreaRepository(db_connection)
    counter = {"n": 0}

    def uuid() -> str:
        counter["n"] += 1
        return f"u-{counter['n']}"

    service = StagingService(
        repo,
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=uuid,
    )
    p1 = tmp_path / "alpha"
    p1.mkdir()
    p2 = tmp_path / "beta"
    p2.mkdir()

    service.mark_staging(p1)
    service.mark_staging(p2)

    stgings = service.list_staging()
    assert len(stgings) == 2
    assert {s.real_path for s in stgings} == {str(p1), str(p2)}


def test_get_staging_existing(db_connection, tmp_path: Path) -> None:
    """get_staging 返回已存在的暂存区。"""
    repo = StagingAreaRepository(db_connection)
    service = StagingService(
        repo,
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=lambda: "uuid-get",
    )
    stash = tmp_path / "Stash"
    stash.mkdir()
    created = service.mark_staging(stash)

    fetched = service.get_staging(created.id)
    assert fetched.id == created.id
    assert fetched.real_path == str(stash)


def test_get_staging_missing_raises(db_connection) -> None:
    """get_staging 不存在时抛 StagingAreaNotFoundError。"""
    repo = StagingAreaRepository(db_connection)
    service = StagingService(repo)
    with pytest.raises(StagingAreaNotFoundError):
        service.get_staging("missing-id")


def test_is_staging_true_for_marked(db_connection, tmp_path: Path) -> None:
    """is_staging 对已标记路径返回 True。"""
    repo = StagingAreaRepository(db_connection)
    service = StagingService(
        repo,
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=lambda: "uuid-is",
    )
    stash = tmp_path / "Stash"
    stash.mkdir()
    service.mark_staging(stash)

    assert service.is_staging(stash) is True


def test_is_staging_false_for_unmarked(db_connection, tmp_path: Path) -> None:
    """is_staging 对未标记路径返回 False。"""
    repo = StagingAreaRepository(db_connection)
    service = StagingService(repo)
    stash = tmp_path / "Stash"
    stash.mkdir()

    assert service.is_staging(stash) is False


def test_get_staging_path_keys(db_connection, tmp_path: Path) -> None:
    """get_staging_path_keys 返回全部 path_key 集合。"""
    repo = StagingAreaRepository(db_connection)
    counter = {"n": 0}

    def uuid() -> str:
        counter["n"] += 1
        return f"u-{counter['n']}"

    service = StagingService(
        repo,
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=uuid,
    )
    p1 = tmp_path / "alpha"
    p1.mkdir()
    p2 = tmp_path / "beta"
    p2.mkdir()

    service.mark_staging(p1)
    service.mark_staging(p2)

    keys = service.get_staging_path_keys()
    assert keys == {make_path_key(p1), make_path_key(p2)}


def test_unmark_then_remark_succeeds(db_connection, tmp_path: Path) -> None:
    """取消标记后可重新标记同一路径。"""
    repo = StagingAreaRepository(db_connection)
    counter = {"n": 0}

    def uuid() -> str:
        counter["n"] += 1
        return f"u-{counter['n']}"

    service = StagingService(
        repo,
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=uuid,
    )
    stash = tmp_path / "Stash"
    stash.mkdir()

    first = service.mark_staging(stash)
    service.unmark_staging(first.id)

    # 重新标记应成功
    second = service.mark_staging(stash)
    assert second.id == "u-2"
    assert service.is_staging(stash) is True


def test_mark_staging_requires_explicit_commit(db_path: Path, tmp_path: Path) -> None:
    """mark_staging 不自提交，需调用方显式 commit 才能持久化。

    H5 一致性：Repository 不自提交，由 application 层控制事务边界。
    """
    from infrastructure.db import get_connection, init_db

    init_db(db_path)
    path = tmp_path / "PersistedStash"
    path.mkdir()

    # 第一次连接：通过 service 标记并显式 commit
    conn1 = get_connection(db_path)
    try:
        service = StagingService(
            StagingAreaRepository(conn1),
            now_provider=lambda: "2026-07-14T00:00:00Z",
            uuid_provider=lambda: "persist-uuid",
        )
        service.mark_staging(path)
        conn1.commit()
    finally:
        conn1.close()

    # 第二次连接：应能读到
    conn2 = get_connection(db_path)
    try:
        service2 = StagingService(StagingAreaRepository(conn2))
        stgings = service2.list_staging()
        assert len(stgings) == 1
        assert stgings[0].real_path == str(path)
        assert stgings[0].id == "persist-uuid"
    finally:
        conn2.close()
