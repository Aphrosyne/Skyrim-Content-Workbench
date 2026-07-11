"""ManagedRootService 测试。

覆盖：
- 添加合法目录；
- 拒绝不存在路径；
- 拒绝非目录路径；
- 重复根目录处理；
- 中文路径；
- list_roots / get_root。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from application.errors import (
    DuplicateManagedRootError,
    InvalidRootPathError,
    ManagedRootNotFoundError,
)
from application.managed_root_service import ManagedRootService
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.managed_root import ManagedRootRepository


def _make_counter(prefix: str) -> tuple[Callable[[], str], list[str]]:
    """生成返回固定递增 id 的 provider，记录调用顺序。"""
    calls: list[str] = []

    def provider() -> str:
        calls.append(prefix)
        return f"{prefix}-{len(calls)}"

    return provider, calls


def test_add_root_legal_directory(db_connection, tmp_path: Path) -> None:
    """合法目录可添加，且 display_name 等于目录名。"""
    repo = ManagedRootRepository(db_connection)
    service = ManagedRootService(
        repo,
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-1",
    )
    mods = tmp_path / "Mods"
    mods.mkdir()

    root = service.add_root(mods)

    assert root.id == "uuid-1"
    assert root.real_path == str(mods)
    assert root.path_key == make_path_key(mods)
    assert root.display_name == "Mods"
    assert root.created_at == "2026-07-07T00:00:00Z"


def test_add_root_chinese_path(db_connection, tmp_path: Path) -> None:
    """中文路径可正常添加。"""
    repo = ManagedRootRepository(db_connection)
    service = ManagedRootService(
        repo,
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-cn",
    )
    path = tmp_path / " Skyrim 汉化模组 "
    path.mkdir()

    root = service.add_root(path)
    assert root.real_path == str(path)
    assert root.display_name == " Skyrim 汉化模组 "
    assert "汉化" in root.real_path


def test_add_root_rejects_nonexistent_path(db_connection, tmp_path: Path) -> None:
    """路径不存在应拒绝。"""
    repo = ManagedRootRepository(db_connection)
    service = ManagedRootService(repo)
    nonexistent = tmp_path / "DoesNotExist"

    with pytest.raises(InvalidRootPathError):
        service.add_root(nonexistent)


def test_add_root_rejects_non_directory_path(db_connection, tmp_path: Path) -> None:
    """非目录路径应拒绝。"""
    repo = ManagedRootRepository(db_connection)
    service = ManagedRootService(repo)
    file_path = tmp_path / "file.txt"
    file_path.write_text("not a directory", encoding="utf-8")

    with pytest.raises(InvalidRootPathError):
        service.add_root(file_path)


def test_add_root_rejects_duplicate(db_connection, tmp_path: Path) -> None:
    """同一路径不能重复添加。"""
    repo = ManagedRootRepository(db_connection)
    service = ManagedRootService(
        repo,
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-dup",
    )
    mods = tmp_path / "Mods"
    mods.mkdir()

    first = service.add_root(mods)
    assert first.id == "uuid-dup"

    with pytest.raises(DuplicateManagedRootError):
        service.add_root(mods)


def test_add_root_does_not_modify_target_directory(db_connection, tmp_path: Path) -> None:
    """添加根目录不应修改目标目录或其中文件。"""
    repo = ManagedRootRepository(db_connection)
    service = ManagedRootService(repo)
    target = tmp_path / "Mods"
    target.mkdir()
    (target / "marker.txt").write_text("keep-me", encoding="utf-8")

    service.add_root(target)

    # 文件内容、目录结构未变
    assert (target / "marker.txt").read_text(encoding="utf-8") == "keep-me"
    # 应用数据库未扫描用户文件（file_asset 表应为空）
    rows = db_connection.execute("SELECT COUNT(*) FROM file_asset").fetchone()
    assert rows[0] == 0


def test_list_roots_empty(db_connection) -> None:
    """空库返回空列表。"""
    repo = ManagedRootRepository(db_connection)
    service = ManagedRootService(repo)
    assert service.list_roots() == []


def test_list_roots_returns_all(db_connection, tmp_path: Path) -> None:
    """list_roots 返回全部已添加的根目录。"""
    repo = ManagedRootRepository(db_connection)
    uuid_provider, _ = _make_counter("u")
    service = ManagedRootService(
        repo,
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=uuid_provider,
    )
    p1 = tmp_path / "alpha"
    p1.mkdir()
    p2 = tmp_path / "beta"
    p2.mkdir()

    service.add_root(p1)
    service.add_root(p2)

    roots = service.list_roots()
    assert len(roots) == 2
    assert {r.real_path for r in roots} == {str(p1), str(p2)}


def test_get_root_existing(db_connection, tmp_path: Path) -> None:
    """get_root 返回已存在的根目录。"""
    repo = ManagedRootRepository(db_connection)
    service = ManagedRootService(
        repo,
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-get",
    )
    mods = tmp_path / "Mods"
    mods.mkdir()
    created = service.add_root(mods)

    fetched = service.get_root(created.id)
    assert fetched.id == created.id
    assert fetched.real_path == str(mods)


def test_get_root_missing_raises(db_connection) -> None:
    """get_root 不存在时抛 ManagedRootNotFoundError。"""
    repo = ManagedRootRepository(db_connection)
    service = ManagedRootService(repo)
    with pytest.raises(ManagedRootNotFoundError):
        service.get_root("missing-id")


def test_add_root_persists_without_explicit_commit(db_path: Path, tmp_path: Path) -> None:
    """add_root 应通过 Repository 自提交持久化，无需调用方显式 commit。

    回归测试：模拟生产路径——UI 调用 service.add_root() 后不显式 commit，
    关闭并重开数据库应仍能读到该根目录。
    """
    from infrastructure.db import get_connection, init_db

    init_db(db_path)
    path = tmp_path / "PersistedRoot"
    path.mkdir()

    # 第一次连接：通过 service 添加，不显式 commit
    conn1 = get_connection(db_path)
    conn1.row_factory = __import__("sqlite3").Row
    try:
        service = ManagedRootService(
            ManagedRootRepository(conn1),
            now_provider=lambda: "2026-07-07T00:00:00Z",
            uuid_provider=lambda: "persist-uuid",
        )
        service.add_root(path)
    finally:
        conn1.close()

    # 第二次连接：应能读到
    conn2 = get_connection(db_path)
    conn2.row_factory = __import__("sqlite3").Row
    try:
        service2 = ManagedRootService(ManagedRootRepository(conn2))
        roots = service2.list_roots()
        assert len(roots) == 1
        assert roots[0].real_path == str(path)
        assert roots[0].id == "persist-uuid"
    finally:
        conn2.close()


# --- remove_root 测试（Task 1 遗漏补完） ---


def test_remove_root_deletes_configuration(db_connection, tmp_path: Path) -> None:
    """remove_root 后该根目录配置不再可查。"""
    repo = ManagedRootRepository(db_connection)
    service = ManagedRootService(
        repo,
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-remove-1",
    )
    mods = tmp_path / "Mods"
    mods.mkdir()
    created = service.add_root(mods)

    service.remove_root(created.id)

    assert service.list_roots() == []


def test_remove_root_missing_raises(db_connection) -> None:
    """remove_root 不存在时抛 ManagedRootNotFoundError。"""
    repo = ManagedRootRepository(db_connection)
    service = ManagedRootService(repo)

    with pytest.raises(ManagedRootNotFoundError):
        service.remove_root("nonexistent-id")


def test_remove_root_preserves_real_directory_and_files(db_connection, tmp_path: Path) -> None:
    """移除根目录配置后真实目录与文件内容、mtime、size 不变。

    对应 docs/phase-2-plan.md 任务 1 测试要求：
    "移除根目录后真实目录与文件内容、mtime、size 不变的测试"。
    """
    repo = ManagedRootRepository(db_connection)
    service = ManagedRootService(
        repo,
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-remove-2",
    )
    target = tmp_path / "Mods"
    target.mkdir()
    marker = target / "marker.txt"
    marker.write_text("keep-me", encoding="utf-8")

    created = service.add_root(target)

    # 记录移除前的文件 stat
    stat_before = marker.stat()
    mtime_before = stat_before.st_mtime
    size_before = stat_before.st_size

    service.remove_root(created.id)

    # 文件内容、大小、mtime 不变
    assert marker.read_text(encoding="utf-8") == "keep-me"
    stat_after = marker.stat()
    assert stat_after.st_size == size_before
    # mtime 应保持不变（未对文件做任何写操作）
    assert stat_after.st_mtime == mtime_before
    # 目录仍存在
    assert target.exists()
    assert target.is_dir()
    # 目录下文件仍存在
    assert (target / "marker.txt").exists()


def test_remove_root_does_not_clean_scan_records(db_connection, tmp_path: Path) -> None:
    """移除根目录配置不清理 folder_node / file_asset 扫描记录。

    依据 docs/phase-2-plan.md 任务 1：
    "该任务不要求删除对应 FolderNode 扫描记录；其清理策略保持待确认。"
    """
    from infrastructure.path_utils import make_path_key

    repo = ManagedRootRepository(db_connection)
    service = ManagedRootService(
        repo,
        now_provider=lambda: "2026-07-07T00:00:00Z",
        uuid_provider=lambda: "uuid-remove-3",
    )
    target = tmp_path / "Mods"
    target.mkdir()
    created = service.add_root(target)

    # 模拟扫描结果
    db_connection.execute(
        "INSERT INTO folder_node (id, real_path, path_key, parent_id, display_name, "
        "is_managed_root, created_at, updated_at) VALUES "
        "('fn-1', ?, ?, NULL, 'Mods', 1, '2026-07-07T00:00:00Z', '2026-07-07T00:00:00Z')",
        (str(target), make_path_key(target)),
    )
    db_connection.execute(
        "INSERT INTO file_asset (id, mod_item_id, real_path, path_key, filename, extension, "
        "asset_kind, role, size_bytes, modified_at, imported_at) VALUES "
        "('fa-1', NULL, ?, ?, 'file.txt', '.txt', 'file', 'unknown', 10, "
        "'2026-07-07T00:00:00Z', '2026-07-07T00:00:00Z')",
        (str(target / "file.txt"), make_path_key(target / "file.txt")),
    )
    db_connection.commit()

    service.remove_root(created.id)

    # managed_root 已删除
    assert repo.get_by_id(created.id) is None
    # folder_node 仍存在
    fn_count = db_connection.execute(
        "SELECT COUNT(*) FROM folder_node WHERE id = 'fn-1'"
    ).fetchone()
    assert fn_count[0] == 1
    # file_asset 仍存在
    fa_count = db_connection.execute("SELECT COUNT(*) FROM file_asset WHERE id = 'fa-1'").fetchone()
    assert fa_count[0] == 1


def test_remove_root_persists_without_explicit_commit(db_path: Path, tmp_path: Path) -> None:
    """remove_root 应通过 Repository 自提交持久化，无需调用方显式 commit。

    回归测试：模拟生产路径——UI 调用 service.remove_root() 后不显式 commit，
    关闭并重开数据库应仍确认该根目录已删除。
    """
    from infrastructure.db import get_connection, init_db

    init_db(db_path)
    target = tmp_path / "PersistedRemove"
    target.mkdir()

    # 第一次连接：添加后移除，不显式 commit
    conn1 = get_connection(db_path)
    conn1.row_factory = __import__("sqlite3").Row
    try:
        service = ManagedRootService(
            ManagedRootRepository(conn1),
            now_provider=lambda: "2026-07-07T00:00:00Z",
            uuid_provider=lambda: "persist-remove-uuid",
        )
        created = service.add_root(target)
        service.remove_root(created.id)
    finally:
        conn1.close()

    # 第二次连接：应确认已删除
    conn2 = get_connection(db_path)
    conn2.row_factory = __import__("sqlite3").Row
    try:
        service2 = ManagedRootService(ManagedRootRepository(conn2))
        assert service2.list_roots() == []
    finally:
        conn2.close()
