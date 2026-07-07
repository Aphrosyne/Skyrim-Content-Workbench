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
