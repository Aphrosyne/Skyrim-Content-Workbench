"""FileOperationService 测试。

覆盖：
- new_folder：创建成功 / 父目录不存在 / 目标已存在 / 写 operation_history / 中文路径
- move：移动文件 / 移动目录 / 源不存在 / 目标已存在 / 跨盘检测 / 自目录检测 /
        保留元数据 / 写 operation_history / 中文路径
- 写操作不自提交
- Stage 4.5 H4：注入 FolderCacheSyncHelper + ContentUnitRepository 后自动同步
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from application.errors import (
    ConflictError,
    CrossDriveError,
    FileOperationError,
    SelfSubdirectoryError,
    SourceNotFoundError,
)
from domain.models import ContentUnit, OperationHistory
from infrastructure.db import get_connection, init_db
from infrastructure.file_operation_service import FileOperationService
from infrastructure.folder_cache_sync_helper import FolderCacheSyncHelper
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.folder_cache import FolderCacheRepository
from infrastructure.repositories.operation_history import OperationHistoryRepository


@pytest.fixture
def service(tmp_path: Path) -> tuple[FileOperationService, sqlite3.Connection]:
    """构造 FileOperationService + 内存独立连接。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    repo = OperationHistoryRepository(conn)
    # 批量操作（如 delete_to_recycle_bin）会多次调用 uuid_provider，
    # 使用计数器确保每次返回唯一 ID，避免 UNIQUE 约束冲突。
    counter = {"n": 0}

    def fake_uuid() -> str:
        counter["n"] += 1
        return f"uuid-test-{counter['n']}"

    svc = FileOperationService(
        repo,
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    yield svc, conn
    conn.close()


# === new_folder ===


class TestNewFolder:
    def test_creates_directory(self, service, tmp_path: Path) -> None:
        svc, _ = service
        parent = tmp_path / "parent"
        parent.mkdir()
        target = parent / "NewMod"

        history = svc.new_folder(target)

        assert target.is_dir()
        assert isinstance(history, OperationHistory)
        assert history.operation_type == "new_folder"
        assert history.source_path == str(parent)
        assert history.target_path == str(target)
        assert history.can_undo is True

    def test_rejects_missing_parent(self, service, tmp_path: Path) -> None:
        svc, _ = service
        target = tmp_path / "nonexistent" / "NewMod"

        with pytest.raises(SourceNotFoundError):
            svc.new_folder(target)

    def test_rejects_existing_target(self, service, tmp_path: Path) -> None:
        svc, _ = service
        target = tmp_path / "exists"
        target.mkdir()

        with pytest.raises(ConflictError):
            svc.new_folder(target)

    def test_writes_operation_history(self, service, tmp_path: Path) -> None:
        svc, conn = service
        parent = tmp_path / "parent"
        parent.mkdir()
        target = parent / "NewMod"

        svc.new_folder(target)
        conn.commit()

        rows = conn.execute("SELECT * FROM operation_history").fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["operation_type"] == "new_folder"
        assert row["source_path"] == str(parent)
        assert row["target_path"] == str(target)
        assert row["can_undo"] == 1

    def test_chinese_path(self, service, tmp_path: Path) -> None:
        svc, _ = service
        parent = tmp_path / "暂存区"
        parent.mkdir()
        target = parent / "新Mod组"

        history = svc.new_folder(target)

        assert target.is_dir()
        assert "新Mod组" in history.target_path


# === move ===


class TestMove:
    def test_move_file_to_directory(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "file.7z"
        src.write_bytes(b"content")
        dst_dir = tmp_path / "target_dir"
        dst_dir.mkdir()
        dst = dst_dir / "file.7z"

        history = svc.move(src, dst)

        assert not src.exists()
        assert dst.is_file()
        assert dst.read_bytes() == b"content"
        assert history.operation_type == "move"
        assert history.source_path == str(src)
        assert history.target_path == str(dst)

    def test_move_directory(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "src_dir"
        src.mkdir()
        (src / "inner.txt").write_text("data", encoding="utf-8")
        dst = tmp_path / "dst_dir"

        svc.move(src, dst)

        assert not src.exists()
        assert dst.is_dir()
        assert (dst / "inner.txt").read_text(encoding="utf-8") == "data"

    def test_rejects_missing_source(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "nonexistent.7z"
        dst = tmp_path / "dst.7z"

        with pytest.raises(SourceNotFoundError):
            svc.move(src, dst)

    def test_rejects_existing_target(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "src.7z"
        src.write_bytes(b"data")
        dst = tmp_path / "dst.7z"
        dst.write_bytes(b"existing")

        with pytest.raises(ConflictError):
            svc.move(src, dst)

    def test_rejects_self_subdirectory(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "src_dir"
        src.mkdir()
        # 试图把 src_dir 移到 src_dir/sub/ 下
        (src / "sub").mkdir()
        dst = src / "sub" / "src_dir"

        with pytest.raises(SelfSubdirectoryError):
            svc.move(src, dst)

    def test_rejects_missing_target_parent(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "src.7z"
        src.write_bytes(b"data")
        dst = tmp_path / "nonexistent" / "dst.7z"

        with pytest.raises(SourceNotFoundError):
            svc.move(src, dst)

    def test_preserves_file_content(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "file.7z"
        content = b"\x00" * 1024
        src.write_bytes(content)
        dst = tmp_path / "dst.7z"

        svc.move(src, dst)

        assert dst.read_bytes() == content

    def test_writes_operation_history(self, service, tmp_path: Path) -> None:
        svc, conn = service
        src = tmp_path / "file.7z"
        src.write_bytes(b"data")
        dst = tmp_path / "dst.7z"

        svc.move(src, dst)
        conn.commit()

        rows = conn.execute("SELECT * FROM operation_history").fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["operation_type"] == "move"
        assert row["source_path"] == str(src)
        assert row["target_path"] == str(dst)

    def test_chinese_path(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "汉化补丁.rar"
        src.write_bytes(b"data")
        dst = tmp_path / "目标" / "汉化补丁.rar"
        dst.parent.mkdir()

        svc.move(src, dst)

        assert not src.exists()
        assert dst.is_file()

    def test_does_not_modify_unrelated_files(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "src.7z"
        src.write_bytes(b"data")
        unrelated = tmp_path / "unrelated.txt"
        unrelated.write_text("keep-me", encoding="utf-8")
        dst = tmp_path / "dst.7z"

        svc.move(src, dst)

        assert unrelated.read_text(encoding="utf-8") == "keep-me"

    def test_move_overwrite_replaces_existing_file(self, service, tmp_path: Path) -> None:
        """overwrite=True 时覆盖已存在的目标文件。"""
        svc, _ = service
        src = tmp_path / "src.txt"
        src.write_text("new content")
        dst = tmp_path / "dst.txt"
        dst.write_text("old content")

        svc.move(src, dst, overwrite=True)

        # 目标被覆盖为新内容
        assert dst.read_text() == "new content"
        # 源已移动（不存在）
        assert not src.exists()

    def test_move_overwrite_false_still_raises_conflict(self, service, tmp_path: Path) -> None:
        """overwrite=False 时目标已存在仍抛 ConflictError（向后兼容）。"""
        svc, _ = service
        src = tmp_path / "src.txt"
        src.write_text("src")
        dst = tmp_path / "dst.txt"
        dst.write_text("existing")

        with pytest.raises(ConflictError):
            svc.move(src, dst, overwrite=False)

        with pytest.raises(ConflictError):
            svc.move(src, dst)  # 默认 overwrite=False


# === 跨盘检测（Windows 单盘环境跳过） ===


def test_cross_drive_detection_simulated(monkeypatch, tmp_path: Path) -> None:
    """模拟跨盘：通过 monkeypatch 替换 Path.stat 使 st_dev 不同。

    在单盘环境下，构造 src.st_dev == 1, dst_parent.st_dev == 2，
    验证抛 CrossDriveError。
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    svc = FileOperationService(
        OperationHistoryRepository(conn),
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=lambda: "uuid-cross",
    )

    src = tmp_path / "src.7z"
    src.write_bytes(b"data")
    dst_dir = tmp_path / "dst_dir"
    dst_dir.mkdir()
    dst = dst_dir / "src.7z"

    original_stat = Path.stat
    call_count = {"n": 0}

    def fake_stat(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        result = original_stat(self, *args, **kwargs)
        call_count["n"] += 1
        # 第 1 次（src）返回 dev=1，第 2 次（dst_parent）返回 dev=2
        if call_count["n"] == 1:
            return _fake_stat_result(result, st_dev=1)
        elif call_count["n"] == 2:
            return _fake_stat_result(result, st_dev=2)
        return result

    monkeypatch.setattr(Path, "stat", fake_stat)

    try:
        with pytest.raises(CrossDriveError):
            svc.move(src, dst)
    finally:
        conn.close()


class _fake_stat_result:
    """伪装 os.stat_result，仅替换 st_dev。"""

    def __init__(self, original, st_dev: int) -> None:
        self._original = original
        self._st_dev = st_dev

    def __getattr__(self, name):  # noqa: ANN001
        if name == "st_dev":
            return self._st_dev
        return getattr(self._original, name)


# === 不自提交 ===


def test_operation_does_not_auto_commit(tmp_path: Path) -> None:
    """文件操作写 history 后不自提交，需显式 commit 才能跨连接可见。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn1 = get_connection(db_path)
    conn1.row_factory = sqlite3.Row
    svc = FileOperationService(
        OperationHistoryRepository(conn1),
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=lambda: "uuid-nocommit",
    )

    parent = tmp_path / "parent"
    parent.mkdir()
    target = parent / "NewMod"
    svc.new_folder(target)
    # 不 commit，直接关闭

    conn2 = get_connection(db_path)
    conn2.row_factory = sqlite3.Row
    rows = conn2.execute("SELECT * FROM operation_history").fetchall()
    assert len(rows) == 0  # 未提交，跨连接不可见

    conn1.close()
    conn2.close()


# === Stage 4.5 H4：自动同步 folder_cache + ContentUnit.path ===


@pytest.fixture
def service_with_sync(
    tmp_path: Path,
) -> tuple[FileOperationService, sqlite3.Connection, FolderCacheRepository, ContentUnitRepository]:
    """构造注入了 helper + content_unit_repo 的 FileOperationService。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    history_repo = OperationHistoryRepository(conn)
    folder_cache_repo = FolderCacheRepository(conn)
    content_unit_repo = ContentUnitRepository(conn)
    helper = FolderCacheSyncHelper(
        folder_cache_repo,
        now_provider=lambda: "2026-07-28T00:00:00Z",
        uuid_provider=lambda: "fc-sync-id",
    )
    svc = FileOperationService(
        history_repo,
        now_provider=lambda: "2026-07-28T00:00:00Z",
        uuid_provider=lambda: "uuid-h4",
        folder_cache_helper=helper,
        content_unit_repo=content_unit_repo,
    )
    yield svc, conn, folder_cache_repo, content_unit_repo
    conn.close()


def _seed_content_unit(
    repo: ContentUnitRepository, unit_id: str, path: str, status: str = "organized"
) -> ContentUnit:
    """插入一条 ContentUnit 测试数据。"""
    unit = ContentUnit(
        id=unit_id,
        path=path,
        title=path.rsplit("/", 1)[-1],
        content_type="mod",
        status=status,
        created_at="2026-07-28T00:00:00Z",
        updated_at="2026-07-28T00:00:00Z",
    )
    return repo.create(unit)


class TestNewFolderAutoSync:
    """H4：new_folder 注入 helper 后自动同步 folder_cache。"""

    def test_new_folder_syncs_folder_cache(self, service_with_sync, tmp_path: Path) -> None:
        svc, conn, folder_cache_repo, _ = service_with_sync
        parent = tmp_path / "parent"
        parent.mkdir()
        target = parent / "NewMod"

        svc.new_folder(target)
        conn.commit()

        fc = folder_cache_repo.get_by_path(str(target))
        assert fc is not None
        assert fc.path == str(target)

    def test_new_folder_sync_failure_cleans_up(self, service_with_sync, tmp_path: Path) -> None:
        """folder_cache 写入失败时清理已创建的空文件夹 + 抛 FileOperationError。"""
        svc, conn, folder_cache_repo, _ = service_with_sync
        parent = tmp_path / "parent"
        parent.mkdir()
        target = parent / "NewMod"

        # 预插入相同 path 的 folder_cache → 触发唯一约束冲突
        from domain.models import FolderCache

        folder_cache_repo.create(
            FolderCache(
                id="dup",
                path=str(target),
                parent_id=None,
                last_scanned_mtime=0.0,
                created_at="2026-07-28T00:00:00Z",
            )
        )

        with pytest.raises(FileOperationError, match="写入 folder_cache 失败"):
            svc.new_folder(target)

        # 空文件夹已被清理
        assert not target.exists()


class TestMoveDirectoryAutoSync:
    """H4：move 目录注入 helper + repo 后自动同步 folder_cache + ContentUnit.path。"""

    def test_move_directory_syncs_folder_cache(self, service_with_sync, tmp_path: Path) -> None:
        svc, conn, folder_cache_repo, _ = service_with_sync
        # 构造：OldDir/MyMod（含子文件）→ NewDir/MyMod
        old_parent = tmp_path / "OldDir"
        old_parent.mkdir()
        new_parent = tmp_path / "NewDir"
        new_parent.mkdir()
        src = old_parent / "MyMod"
        src.mkdir()
        (src / "file.7z").write_bytes(b"data")
        dst = new_parent / "MyMod"

        # 预置 folder_cache：旧目录 + MyMod
        from domain.models import FolderCache

        old_parent_fc = folder_cache_repo.create(
            FolderCache(
                id="fc-old-parent",
                path=str(old_parent),
                parent_id=None,
                last_scanned_mtime=1000.0,
                created_at="2026-07-28T00:00:00Z",
            )
        )
        new_parent_fc = folder_cache_repo.create(
            FolderCache(
                id="fc-new-parent",
                path=str(new_parent),
                parent_id=None,
                last_scanned_mtime=1000.0,
                created_at="2026-07-28T00:00:00Z",
            )
        )
        folder_cache_repo.create(
            FolderCache(
                id="fc-src",
                path=str(src),
                parent_id=old_parent_fc.id,
                last_scanned_mtime=1000.0,
                created_at="2026-07-28T00:00:00Z",
            )
        )

        svc.move(src, dst)
        conn.commit()

        # 旧 folder_cache 已删除
        assert folder_cache_repo.get_by_path(str(src)) is None
        # 新 folder_cache 已插入
        new_fc = folder_cache_repo.get_by_path(str(dst))
        assert new_fc is not None
        assert new_fc.parent_id == new_parent_fc.id
        # 目标父目录 mtime 已更新
        new_parent_after = folder_cache_repo.get_by_path(str(new_parent))
        assert new_parent_after.last_scanned_mtime != 1000.0

    def test_move_directory_updates_content_unit_paths(
        self, service_with_sync, tmp_path: Path
    ) -> None:
        """move 目录时更新 ContentUnit.path：精确匹配 + 子路径前缀重写。"""
        svc, conn, _, content_unit_repo = service_with_sync
        old_root = tmp_path / "OldRoot"
        old_root.mkdir()
        new_root = tmp_path / "NewRoot"
        new_root.mkdir()
        src = old_root / "MyMod"
        src.mkdir()
        (src / "sub.7z").write_bytes(b"data")
        dst = new_root / "MyMod"

        # 预置 ContentUnit：
        # - unit-folder：path == src（精确匹配，移动后 → dst）
        # - unit-child：path == src/sub.7z（子路径，移动后 → dst/sub.7z）
        # - unit-unrelated：path == old_root/Other（不在 src 子树，不应更新）
        unit_folder = _seed_content_unit(content_unit_repo, "cu-folder", str(src))
        unit_child = _seed_content_unit(content_unit_repo, "cu-child", str(src / "sub.7z"))
        unit_unrelated = _seed_content_unit(
            content_unit_repo, "cu-unrelated", str(old_root / "Other")
        )

        svc.move(src, dst)
        conn.commit()

        # folder 的 path 已更新为 dst
        updated_folder = content_unit_repo.get_by_id(unit_folder.id)
        assert updated_folder is not None
        assert make_path_key(updated_folder.path) == make_path_key(str(dst))

        # child 的 path 已更新为 dst/sub.7z
        updated_child = content_unit_repo.get_by_id(unit_child.id)
        assert updated_child is not None
        assert make_path_key(updated_child.path) == make_path_key(str(dst / "sub.7z"))

        # unrelated 未变更
        updated_unrelated = content_unit_repo.get_by_id(unit_unrelated.id)
        assert updated_unrelated is not None
        assert updated_unrelated.path == str(old_root / "Other")


class TestMoveFileAutoSync:
    """H4：move 文件注入 helper 后更新父目录 mtime（best-effort）。"""

    def test_move_file_updates_parent_mtimes(self, service_with_sync, tmp_path: Path) -> None:
        svc, conn, folder_cache_repo, _ = service_with_sync
        src_dir = tmp_path / "SrcDir"
        src_dir.mkdir()
        dst_dir = tmp_path / "DstDir"
        dst_dir.mkdir()
        src = src_dir / "file.7z"
        src.write_bytes(b"data")
        dst = dst_dir / "file.7z"

        # 预置 folder_cache：两个父目录
        from domain.models import FolderCache

        folder_cache_repo.create(
            FolderCache(
                id="fc-src",
                path=str(src_dir),
                parent_id=None,
                last_scanned_mtime=1000.0,
                created_at="2026-07-28T00:00:00Z",
            )
        )
        folder_cache_repo.create(
            FolderCache(
                id="fc-dst",
                path=str(dst_dir),
                parent_id=None,
                last_scanned_mtime=1000.0,
                created_at="2026-07-28T00:00:00Z",
            )
        )

        svc.move(src, dst)
        conn.commit()

        # 两个父目录 mtime 都已更新（不再是 1000.0）
        src_after = folder_cache_repo.get_by_path(str(src_dir))
        assert src_after.last_scanned_mtime != 1000.0
        dst_after = folder_cache_repo.get_by_path(str(dst_dir))
        assert dst_after.last_scanned_mtime != 1000.0


class TestMoveWithoutSync:
    """H4：未注入 helper/repo 时 move 不同步（向后兼容）。"""

    def test_move_without_helper_no_sync(self, tmp_path: Path) -> None:
        """未注入 helper/repo → move 不写 folder_cache，保持原行为。"""
        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)
        conn.row_factory = sqlite3.Row
        svc = FileOperationService(
            OperationHistoryRepository(conn),
            now_provider=lambda: "2026-07-28T00:00:00Z",
            uuid_provider=lambda: "uuid-no-sync",
        )
        folder_cache_repo = FolderCacheRepository(conn)

        src = tmp_path / "src.7z"
        src.write_bytes(b"data")
        dst = tmp_path / "dst.7z"

        svc.move(src, dst)
        conn.commit()

        # folder_cache 表为空（无 helper 注入，不写）
        assert folder_cache_repo.list_all() == []

        conn.close()


# === Stage 5 Task 3a：rename ===


class TestRename:
    """rename：文件 / 目录 / 名称校验 / 冲突 / 历史写入 / 中文路径。"""

    def test_rename_file(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "old_name.txt"
        src.write_bytes(b"data")

        history = svc.rename(src, "new_name.txt")

        assert not src.exists()
        assert (tmp_path / "new_name.txt").is_file()
        assert history.operation_type == "rename"
        assert history.source_path == str(src)
        assert history.target_path == str(tmp_path / "new_name.txt")
        assert history.can_undo is True

    def test_rename_directory(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "old_dir"
        src.mkdir()
        (src / "inner.txt").write_text("data", encoding="utf-8")

        svc.rename(src, "new_dir")

        assert not src.exists()
        assert (tmp_path / "new_dir").is_dir()
        assert ((tmp_path / "new_dir") / "inner.txt").read_text(encoding="utf-8") == "data"

    def test_rejects_missing_source(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "nonexistent.txt"

        with pytest.raises(SourceNotFoundError):
            svc.rename(src, "new_name.txt")

    def test_rejects_existing_target(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "src.txt"
        src.write_bytes(b"data")
        (tmp_path / "dst.txt").write_bytes(b"existing")

        with pytest.raises(ConflictError):
            svc.rename(src, "dst.txt")

    def test_rejects_empty_name(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "src.txt"
        src.write_bytes(b"data")

        with pytest.raises(FileOperationError, match="新名称不能为空"):
            svc.rename(src, "")

    def test_rejects_whitespace_only_name(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "src.txt"
        src.write_bytes(b"data")

        with pytest.raises(FileOperationError, match="新名称不能为空"):
            svc.rename(src, "   ")

    def test_rejects_dot_name(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "src.txt"
        src.write_bytes(b"data")

        with pytest.raises(FileOperationError, match="新名称不能为"):
            svc.rename(src, ".")

    def test_rejects_double_dot_name(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "src.txt"
        src.write_bytes(b"data")

        with pytest.raises(FileOperationError, match="新名称不能为"):
            svc.rename(src, "..")

    def test_rejects_invalid_chars(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "src.txt"
        src.write_bytes(b"data")

        for c in '<>:"/\\|?*':
            with pytest.raises(FileOperationError, match="非法字符"):
                svc.rename(src, f"a{c}b")

    def test_rejects_trailing_space(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "src.txt"
        src.write_bytes(b"data")

        with pytest.raises(FileOperationError, match="不能以空格或点结尾"):
            svc.rename(src, "new_name ")

    def test_rejects_trailing_dot(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "src.txt"
        src.write_bytes(b"data")

        with pytest.raises(FileOperationError, match="不能以空格或点结尾"):
            svc.rename(src, "new_name.")

    def test_writes_operation_history(self, service, tmp_path: Path) -> None:
        svc, conn = service
        src = tmp_path / "old.txt"
        src.write_bytes(b"data")

        svc.rename(src, "new.txt")
        conn.commit()

        rows = conn.execute("SELECT * FROM operation_history").fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["operation_type"] == "rename"
        assert row["source_path"] == str(src)
        assert row["target_path"] == str(tmp_path / "new.txt")
        assert row["can_undo"] == 1

    def test_chinese_path(self, service, tmp_path: Path) -> None:
        svc, _ = service
        src = tmp_path / "旧名称.txt"
        src.write_bytes(b"data")

        history = svc.rename(src, "新名称.txt")

        assert not src.exists()
        assert (tmp_path / "新名称.txt").is_file()
        assert "新名称" in history.target_path

    def test_same_name_is_noop(self, service, tmp_path: Path) -> None:
        """同名重命名：当前 handler 层会跳过，但 service 层应抛 ConflictError
        （因为目标已存在 == 源）。

        handler 层（_on_rename_entry）在调用 service 前会比较新旧名称相同则提前 return。
        """
        svc, _ = service
        src = tmp_path / "same.txt"
        src.write_bytes(b"data")

        with pytest.raises(ConflictError):
            svc.rename(src, "same.txt")


# === Stage 5 Task 3a：rename 自动同步 ===


class TestRenameAutoSync:
    """rename 注入 helper + repo 后自动同步 folder_cache + ContentUnit.path。"""

    def test_rename_directory_syncs_folder_cache(self, service_with_sync, tmp_path: Path) -> None:
        """重命名目录：删除旧 folder_cache + 插入新 folder_cache + 更新父 mtime。"""
        svc, conn, folder_cache_repo, _ = service_with_sync
        parent = tmp_path / "parent"
        parent.mkdir()
        src = parent / "OldName"
        src.mkdir()

        from domain.models import FolderCache

        parent_fc = folder_cache_repo.create(
            FolderCache(
                id="fc-parent",
                path=str(parent),
                parent_id=None,
                last_scanned_mtime=1000.0,
                created_at="2026-07-28T00:00:00Z",
            )
        )
        folder_cache_repo.create(
            FolderCache(
                id="fc-src",
                path=str(src),
                parent_id=parent_fc.id,
                last_scanned_mtime=1000.0,
                created_at="2026-07-28T00:00:00Z",
            )
        )

        svc.rename(src, "NewName")
        conn.commit()

        # 旧 folder_cache 已删除
        assert folder_cache_repo.get_by_path(str(src)) is None
        # 新 folder_cache 已插入
        new_fc = folder_cache_repo.get_by_path(str(parent / "NewName"))
        assert new_fc is not None
        assert new_fc.parent_id == parent_fc.id

    def test_rename_directory_updates_content_unit_paths(
        self, service_with_sync, tmp_path: Path
    ) -> None:
        """重命名目录时更新 ContentUnit.path（精确匹配 + 子路径重写）。"""
        svc, conn, _, content_unit_repo = service_with_sync
        parent = tmp_path / "parent"
        parent.mkdir()
        src = parent / "OldMod"
        src.mkdir()
        (src / "sub.7z").write_bytes(b"data")

        # 预置 ContentUnit
        unit_folder = _seed_content_unit(content_unit_repo, "cu-folder", str(src))
        unit_child = _seed_content_unit(content_unit_repo, "cu-child", str(src / "sub.7z"))

        dst = parent / "NewMod"
        svc.rename(src, "NewMod")
        conn.commit()

        # folder 的 path 已更新
        updated_folder = content_unit_repo.get_by_id(unit_folder.id)
        assert updated_folder is not None
        assert make_path_key(updated_folder.path) == make_path_key(str(dst))

        # child 的 path 已更新
        updated_child = content_unit_repo.get_by_id(unit_child.id)
        assert updated_child is not None
        assert make_path_key(updated_child.path) == make_path_key(str(dst / "sub.7z"))

    def test_rename_file_updates_parent_mtime(self, service_with_sync, tmp_path: Path) -> None:
        """重命名文件：仅更新父目录 mtime（folder_cache 只记录目录）。"""
        svc, conn, folder_cache_repo, _ = service_with_sync
        parent = tmp_path / "parent"
        parent.mkdir()
        src = parent / "old.txt"
        src.write_bytes(b"data")

        from domain.models import FolderCache

        folder_cache_repo.create(
            FolderCache(
                id="fc-parent",
                path=str(parent),
                parent_id=None,
                last_scanned_mtime=1000.0,
                created_at="2026-07-28T00:00:00Z",
            )
        )

        svc.rename(src, "new.txt")
        conn.commit()

        parent_after = folder_cache_repo.get_by_path(str(parent))
        assert parent_after.last_scanned_mtime != 1000.0


class TestRenameWithoutSync:
    """未注入 helper/repo 时 rename 不同步（向后兼容）。"""

    def test_rename_without_helper_no_sync(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)
        conn.row_factory = sqlite3.Row
        svc = FileOperationService(
            OperationHistoryRepository(conn),
            now_provider=lambda: "2026-07-28T00:00:00Z",
            uuid_provider=lambda: "uuid-no-sync",
        )
        folder_cache_repo = FolderCacheRepository(conn)

        src = tmp_path / "old.txt"
        src.write_bytes(b"data")

        svc.rename(src, "new.txt")
        conn.commit()

        # folder_cache 表为空（无 helper 注入，不写）
        assert folder_cache_repo.list_all() == []

        conn.close()


# === Stage 5 Task 3a：delete_to_recycle_bin ===


@pytest.fixture
def service_with_sync_delete(
    tmp_path: Path,
) -> tuple[FileOperationService, sqlite3.Connection, FolderCacheRepository, ContentUnitRepository]:
    """构造注入了 helper + content_unit_repo 的 FileOperationService（用于 delete 测试）。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    history_repo = OperationHistoryRepository(conn)
    folder_cache_repo = FolderCacheRepository(conn)
    content_unit_repo = ContentUnitRepository(conn)
    helper = FolderCacheSyncHelper(
        folder_cache_repo,
        now_provider=lambda: "2026-07-28T00:00:00Z",
        uuid_provider=lambda: "fc-sync-id",
    )
    svc = FileOperationService(
        history_repo,
        now_provider=lambda: "2026-07-28T00:00:00Z",
        uuid_provider=lambda: "uuid-delete",
        folder_cache_helper=helper,
        content_unit_repo=content_unit_repo,
    )
    yield svc, conn, folder_cache_repo, content_unit_repo
    conn.close()


class TestDeleteToRecycleBin:
    """delete_to_recycle_bin：基本删除 / 历史写入 / 空列表 / 同步。"""

    def test_delete_single_file_returns_histories(self, service, tmp_path: Path) -> None:
        """删除单个文件：返回 (histories, sync_errors)，histories 含 1 条 delete 记录。"""
        svc, _ = service
        f = tmp_path / "to_delete.txt"
        f.write_bytes(b"data")

        histories, sync_errors = svc.delete_to_recycle_bin([f])

        assert not f.exists()
        assert len(histories) == 1
        assert histories[0].operation_type == "delete"
        assert histories[0].source_path == str(f)
        assert histories[0].target_path is None
        assert histories[0].can_undo is False
        assert sync_errors == []

    def test_delete_multiple_paths(self, service, tmp_path: Path) -> None:
        svc, _ = service
        f1 = tmp_path / "f1.txt"
        f1.write_bytes(b"1")
        f2 = tmp_path / "f2.txt"
        f2.write_bytes(b"2")
        d = tmp_path / "dir"
        d.mkdir()
        (d / "inner.txt").write_text("data", encoding="utf-8")

        histories, sync_errors = svc.delete_to_recycle_bin([f1, f2, d])

        assert not f1.exists()
        assert not f2.exists()
        assert not d.exists()
        assert len(histories) == 3
        assert sync_errors == []

    def test_delete_empty_list_returns_empty(self, service) -> None:
        """空列表返回 ([], [])。"""
        svc, _ = service
        histories, sync_errors = svc.delete_to_recycle_bin([])

        assert histories == []
        assert sync_errors == []

    def test_delete_skips_nonexistent_path(self, service, tmp_path: Path) -> None:
        """不存在的路径被过滤，不报错。"""
        svc, _ = service
        nonexistent = tmp_path / "does_not_exist.txt"
        # 同时包含一个存在的文件
        existing = tmp_path / "exists.txt"
        existing.write_bytes(b"data")

        histories, sync_errors = svc.delete_to_recycle_bin([nonexistent, existing])

        assert not existing.exists()
        assert len(histories) == 1
        assert histories[0].source_path == str(existing)
        assert sync_errors == []

    def test_delete_writes_operation_history(self, service, tmp_path: Path) -> None:
        """删除后写 operation_history（type='delete', can_undo=False）。"""
        svc, conn = service
        f = tmp_path / "to_delete.txt"
        f.write_bytes(b"data")

        svc.delete_to_recycle_bin([f])
        conn.commit()

        rows = conn.execute("SELECT * FROM operation_history").fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["operation_type"] == "delete"
        assert row["source_path"] == str(f)
        assert row["target_path"] is None
        assert row["can_undo"] == 0

    def test_delete_chinese_path(self, service, tmp_path: Path) -> None:
        svc, _ = service
        f = tmp_path / "中文文件.txt"
        f.write_bytes(b"data")

        histories, _ = svc.delete_to_recycle_bin([f])

        assert not f.exists()
        assert len(histories) == 1
        assert "中文文件" in histories[0].source_path


class TestDeleteAutoSync:
    """delete 注入 helper + repo 后自动同步 folder_cache + ContentUnit。"""

    def test_delete_directory_syncs_folder_cache(
        self, service_with_sync_delete, tmp_path: Path
    ) -> None:
        """删除目录：删除该节点及子节点的 folder_cache 记录。"""
        svc, conn, folder_cache_repo, _ = service_with_sync_delete
        parent = tmp_path / "parent"
        parent.mkdir()
        target = parent / "ToDelete"
        target.mkdir()
        (target / "sub_dir").mkdir()
        (target / "sub_dir" / "file.txt").write_text("data", encoding="utf-8")

        from domain.models import FolderCache

        folder_cache_repo.create(
            FolderCache(
                id="fc-parent",
                path=str(parent),
                parent_id=None,
                last_scanned_mtime=1000.0,
                created_at="2026-07-28T00:00:00Z",
            )
        )
        folder_cache_repo.create(
            FolderCache(
                id="fc-target",
                path=str(target),
                parent_id="fc-parent",
                last_scanned_mtime=1000.0,
                created_at="2026-07-28T00:00:00Z",
            )
        )
        folder_cache_repo.create(
            FolderCache(
                id="fc-sub",
                path=str(target / "sub_dir"),
                parent_id="fc-target",
                last_scanned_mtime=1000.0,
                created_at="2026-07-28T00:00:00Z",
            )
        )

        svc.delete_to_recycle_bin([target])
        conn.commit()

        # 目录及子节点的 folder_cache 已删除
        assert folder_cache_repo.get_by_path(str(target)) is None
        assert folder_cache_repo.get_by_path(str(target / "sub_dir")) is None
        # 父目录保留（仅更新 mtime）
        assert folder_cache_repo.get_by_path(str(parent)) is not None

    def test_delete_directory_removes_content_units(
        self, service_with_sync_delete, tmp_path: Path
    ) -> None:
        """删除目录：删除路径前缀匹配的 ContentUnit 记录（含子文件）。"""
        svc, conn, _, content_unit_repo = service_with_sync_delete
        parent = tmp_path / "parent"
        parent.mkdir()
        target = parent / "Mod"
        target.mkdir()
        (target / "sub.7z").write_bytes(b"data")

        # 预置 ContentUnit
        unit_folder = _seed_content_unit(content_unit_repo, "cu-folder", str(target))
        unit_child = _seed_content_unit(content_unit_repo, "cu-child", str(target / "sub.7z"))
        # 不在删除范围内的 ContentUnit（不应被删除）
        unit_unrelated = _seed_content_unit(
            content_unit_repo, "cu-other", str(parent / "Other.txt")
        )

        svc.delete_to_recycle_bin([target])
        conn.commit()

        # 关联的 ContentUnit 已删除
        assert content_unit_repo.get_by_id(unit_folder.id) is None
        assert content_unit_repo.get_by_id(unit_child.id) is None
        # 无关的 ContentUnit 保留
        assert content_unit_repo.get_by_id(unit_unrelated.id) is not None

    def test_delete_file_updates_parent_mtime(
        self, service_with_sync_delete, tmp_path: Path
    ) -> None:
        """删除文件：仅更新父目录 mtime（folder_cache 只记录目录）。"""
        svc, conn, folder_cache_repo, _ = service_with_sync_delete
        parent = tmp_path / "parent"
        parent.mkdir()
        f = parent / "to_delete.txt"
        f.write_bytes(b"data")

        from domain.models import FolderCache

        folder_cache_repo.create(
            FolderCache(
                id="fc-parent",
                path=str(parent),
                parent_id=None,
                last_scanned_mtime=1000.0,
                created_at="2026-07-28T00:00:00Z",
            )
        )

        svc.delete_to_recycle_bin([f])
        conn.commit()

        parent_after = folder_cache_repo.get_by_path(str(parent))
        assert parent_after.last_scanned_mtime != 1000.0

    def test_delete_returns_sync_errors_on_failure(
        self, service_with_sync_delete, tmp_path: Path
    ) -> None:
        """同步失败时返回 sync_errors（文件已删除，历史已写入）。"""
        svc, conn, folder_cache_repo, _ = service_with_sync_delete
        parent = tmp_path / "parent"
        parent.mkdir()
        target = parent / "ToDelete"
        target.mkdir()

        from domain.models import FolderCache

        folder_cache_repo.create(
            FolderCache(
                id="fc-parent",
                path=str(parent),
                parent_id=None,
                last_scanned_mtime=1000.0,
                created_at="2026-07-28T00:00:00Z",
            )
        )
        folder_cache_repo.create(
            FolderCache(
                id="fc-target",
                path=str(target),
                parent_id="fc-parent",
                last_scanned_mtime=1000.0,
                created_at="2026-07-28T00:00:00Z",
            )
        )

        # 让 _sync_on_delete 抛异常：替换 _sync_on_delete 方法
        original_sync = svc._sync_on_delete  # noqa: SLF001
        call_count = {"n": 0}

        def fake_sync(path):
            call_count["n"] += 1
            raise FileOperationError("模拟同步失败")

        svc._sync_on_delete = fake_sync  # noqa: SLF001

        try:
            histories, sync_errors = svc.delete_to_recycle_bin([target])
        finally:
            svc._sync_on_delete = original_sync  # noqa: SLF001

        # 文件已删除
        assert not target.exists()
        # 历史已写入（即使同步失败）
        assert len(histories) == 1
        # sync_errors 非空
        assert len(sync_errors) == 1
        assert "模拟同步失败" in sync_errors[0]


class TestDeleteWithoutSync:
    """未注入 helper/repo 时 delete 不同步（向后兼容）。"""

    def test_delete_without_helper_no_sync(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)
        conn.row_factory = sqlite3.Row
        svc = FileOperationService(
            OperationHistoryRepository(conn),
            now_provider=lambda: "2026-07-28T00:00:00Z",
            uuid_provider=lambda: "uuid-no-sync",
        )
        folder_cache_repo = FolderCacheRepository(conn)

        f = tmp_path / "to_delete.txt"
        f.write_bytes(b"data")

        svc.delete_to_recycle_bin([f])
        conn.commit()

        # folder_cache 表为空（无 helper 注入，不写）
        assert folder_cache_repo.list_all() == []

        conn.close()


# === Stage 5 Task 3b：copy ===


class TestCopy:
    """copy 基础测试（不注入 helper/repo）。"""

    def test_copy_file_success(self, service, tmp_path: Path) -> None:
        """复制文件成功，源保留，目标内容一致。"""
        svc, _ = service
        src = tmp_path / "file.7z"
        src.write_bytes(b"content")
        dst = tmp_path / "copy.7z"

        history = svc.copy(src, dst)

        # 源保留（copy 不删除源）
        assert src.is_file()
        # 目标内容一致
        assert dst.is_file()
        assert dst.read_bytes() == b"content"
        # 历史记录
        assert history.operation_type == "copy"
        assert history.source_path == str(src)
        assert history.target_path == str(dst)
        assert history.can_undo is False  # Q4=A 不可撤销

    def test_copy_directory_success(self, service, tmp_path: Path) -> None:
        """复制目录成功，递归复制子内容。"""
        svc, _ = service
        src = tmp_path / "src_dir"
        src.mkdir()
        (src / "inner.txt").write_text("data", encoding="utf-8")
        sub = src / "sub"
        sub.mkdir()
        (sub / "deep.txt").write_text("deep", encoding="utf-8")
        dst = tmp_path / "dst_dir"

        svc.copy(src, dst)

        assert src.is_dir()  # 源保留
        assert dst.is_dir()
        assert (dst / "inner.txt").read_text(encoding="utf-8") == "data"
        assert (dst / "sub" / "deep.txt").read_text(encoding="utf-8") == "deep"

    def test_rejects_missing_source(self, service, tmp_path: Path) -> None:
        """源不存在抛 SourceNotFoundError。"""
        svc, _ = service
        src = tmp_path / "nonexistent.7z"
        dst = tmp_path / "dst.7z"

        with pytest.raises(SourceNotFoundError):
            svc.copy(src, dst)

    def test_rejects_existing_target(self, service, tmp_path: Path) -> None:
        """目标已存在抛 ConflictError（不覆盖，AGENTS 规则 2）。"""
        svc, _ = service
        src = tmp_path / "src.txt"
        src.write_text("src")
        dst = tmp_path / "dst.txt"
        dst.write_text("existing")

        with pytest.raises(ConflictError):
            svc.copy(src, dst)

    def test_rejects_missing_parent(self, service, tmp_path: Path) -> None:
        """目标父目录不存在抛 SourceNotFoundError。"""
        svc, _ = service
        src = tmp_path / "src.txt"
        src.write_text("src")
        dst = tmp_path / "nonexistent" / "dst.txt"

        with pytest.raises(SourceNotFoundError):
            svc.copy(src, dst)

    def test_rejects_self_subdirectory(self, service, tmp_path: Path) -> None:
        """复制到自身子目录抛 SelfSubdirectoryError。"""
        svc, _ = service
        src = tmp_path / "src_dir"
        src.mkdir()
        (src / "inner.txt").write_text("data")
        # 目标在 src 子树内（创建父目录以通过 dst_parent.exists() 检查）
        (src / "sub").mkdir()
        dst = src / "sub" / "copy"

        with pytest.raises(SelfSubdirectoryError):
            svc.copy(src, dst)

    def test_writes_operation_history(self, service, tmp_path: Path) -> None:
        """成功复制后写 operation_history，can_undo=0。"""
        svc, conn = service
        src = tmp_path / "src.txt"
        src.write_text("src")
        dst = tmp_path / "dst.txt"

        svc.copy(src, dst)
        conn.commit()

        rows = conn.execute("SELECT * FROM operation_history").fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["operation_type"] == "copy"
        assert row["source_path"] == str(src)
        assert row["target_path"] == str(dst)
        assert row["can_undo"] == 0

    def test_chinese_path(self, service, tmp_path: Path) -> None:
        """中文路径复制成功。"""
        svc, _ = service
        src = tmp_path / "汉化包.7z"
        src.write_bytes(b"\x00" * 100)
        dst = tmp_path / "汉化包_副本.7z"

        history = svc.copy(src, dst)

        assert dst.is_file()
        assert "汉化包_副本" in history.target_path

    def test_copy_overwrite_replaces_existing_file(self, service, tmp_path: Path) -> None:
        """overwrite=True 时覆盖已存在的目标文件。"""
        svc, _ = service
        src = tmp_path / "src.txt"
        src.write_text("new content")
        dst = tmp_path / "dst.txt"
        dst.write_text("old content")

        svc.copy(src, dst, overwrite=True)

        # 目标被覆盖为新内容
        assert dst.read_text() == "new content"
        # 源保留
        assert src.read_text() == "new content"

    def test_copy_overwrite_replaces_existing_directory(self, service, tmp_path: Path) -> None:
        """overwrite=True 时覆盖已存在的目标目录。"""
        svc, _ = service
        src = tmp_path / "src_dir"
        src.mkdir()
        (src / "new.txt").write_text("new")
        dst = tmp_path / "dst_dir"
        dst.mkdir()
        (dst / "old.txt").write_text("old")

        svc.copy(src, dst, overwrite=True)

        # 旧文件被删除，新文件存在
        assert not (dst / "old.txt").exists()
        assert (dst / "new.txt").read_text() == "new"

    def test_copy_overwrite_false_still_raises_conflict(self, service, tmp_path: Path) -> None:
        """overwrite=False 时目标已存在仍抛 ConflictError（向后兼容）。"""
        svc, _ = service
        src = tmp_path / "src.txt"
        src.write_text("src")
        dst = tmp_path / "dst.txt"
        dst.write_text("existing")

        with pytest.raises(ConflictError):
            svc.copy(src, dst, overwrite=False)

        with pytest.raises(ConflictError):
            svc.copy(src, dst)  # 默认 overwrite=False


class TestCopyAutoSync:
    """copy 注入 helper + content_unit_repo 后自动同步（Stage 4.5 H4）。"""

    def test_copy_directory_syncs_folder_cache(self, service_with_sync, tmp_path: Path) -> None:
        """目录复制后 folder_cache 新增顶层节点。"""
        svc, conn, folder_cache_repo, _ = service_with_sync
        src = tmp_path / "src_dir"
        src.mkdir()
        (src / "inner.txt").write_text("data")
        dst = tmp_path / "dst_dir"

        svc.copy(src, dst)
        conn.commit()

        fc = folder_cache_repo.get_by_path(str(dst))
        assert fc is not None
        assert fc.path == str(dst)

    def test_copy_file_updates_folder_mtime(self, service_with_sync, tmp_path: Path) -> None:
        """文件复制后父目录 folder_cache mtime 更新。"""
        svc, conn, folder_cache_repo, _ = service_with_sync
        parent = tmp_path / "parent"
        parent.mkdir()
        # 预置 parent 的 folder_cache
        from infrastructure.folder_cache_sync_helper import FolderCacheSyncHelper

        helper = FolderCacheSyncHelper(
            folder_cache_repo,
            now_provider=lambda: "2026-07-30T00:00:00Z",
            uuid_provider=lambda: "fc-id",
        )
        helper.on_folder_created(parent, parent.parent)
        conn.commit()

        src = tmp_path / "src.txt"
        src.write_text("src")
        dst = parent / "dst.txt"

        svc.copy(src, dst)
        conn.commit()

        fc = folder_cache_repo.get_by_path(str(parent))
        assert fc is not None
        # mtime 应非空（被 update_folder_mtime 设置）
        assert fc.last_scanned_mtime is not None

    def test_copy_directory_duplicates_content_units(
        self, service_with_sync, tmp_path: Path
    ) -> None:
        """目录复制后复制 ContentUnit 记录（Q10=A，新 id + 新 path）。"""
        svc, conn, _, content_unit_repo = service_with_sync
        src = tmp_path / "src_dir"
        src.mkdir()
        (src / "inner.txt").write_text("data")
        dst = tmp_path / "dst_dir"

        # 预置源目录的 ContentUnit
        original_unit = _seed_content_unit(
            content_unit_repo,
            unit_id="unit-src",
            path=str(src),
            status="organized",
        )
        conn.commit()

        svc.copy(src, dst)
        conn.commit()

        # 原记录保留
        original = content_unit_repo.get_by_id(original_unit.id)
        assert original is not None
        assert original.path == str(src)

        # 新记录创建（路径 = dst）
        new_units = content_unit_repo.list_by_path_prefix_normalized(str(dst))
        assert len(new_units) == 1
        assert new_units[0].path == str(dst)
        assert new_units[0].id != original_unit.id  # 新 id
        assert new_units[0].status == "organized"  # 元数据保留

    def test_copy_file_duplicates_content_unit(self, service_with_sync, tmp_path: Path) -> None:
        """文件复制后复制对应 ContentUnit（如有）。"""
        svc, conn, _, content_unit_repo = service_with_sync
        src = tmp_path / "src.txt"
        src.write_text("src")
        dst = tmp_path / "dst.txt"

        original_unit = _seed_content_unit(
            content_unit_repo,
            unit_id="unit-file",
            path=str(src),
        )
        conn.commit()

        svc.copy(src, dst)
        conn.commit()

        # 原记录保留
        assert content_unit_repo.get_by_id(original_unit.id) is not None
        # 新记录创建
        new_units = content_unit_repo.list_by_path_prefix_normalized(str(dst))
        assert len(new_units) == 1
        assert new_units[0].path == str(dst)


class TestCopyWithoutSync:
    """未注入 helper/repo 时 copy 不同步（向后兼容）。"""

    def test_copy_without_helper_no_sync(self, tmp_path: Path) -> None:
        """无 helper/repo 注入时 copy 仅复制文件，不写 folder_cache。"""
        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = get_connection(db_path)
        conn.row_factory = sqlite3.Row
        svc = FileOperationService(
            OperationHistoryRepository(conn),
            now_provider=lambda: "2026-07-30T00:00:00Z",
            uuid_provider=lambda: "uuid-no-sync",
        )
        folder_cache_repo = FolderCacheRepository(conn)

        src = tmp_path / "src_dir"
        src.mkdir()
        (src / "inner.txt").write_text("data")
        dst = tmp_path / "dst_dir"

        svc.copy(src, dst)
        conn.commit()

        # folder_cache 表为空（无 helper 注入，不写）
        assert folder_cache_repo.list_all() == []

        # 文件已复制
        assert dst.is_dir()
        assert (dst / "inner.txt").read_text() == "data"

        conn.close()
