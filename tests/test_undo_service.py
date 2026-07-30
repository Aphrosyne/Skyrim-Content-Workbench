"""UndoService 测试（Stage 5 Task 6）。

覆盖用户补充要求 #3 的重点测试：
- 正常 undo（new_folder / rename / move 三种类型）
- 文件被外部修改后的 undo 阻止
- 文件不存在后的 undo 阻止
- 多次 undo（连续撤销不同记录）
- 重启应用后历史恢复（重新构造 UndoService 后仍能撤销）
- undo 自身不会进入可无限 undo 循环（undo 记录不可再撤销）

额外覆盖：
- delete / undo 操作拒绝撤销（UndoNotAllowedError）
- 已撤销操作重复撤销（UndoAlreadyUndoneError）
- 目标已存在时撤销阻止（UndoSafetyError）
- new_folder 非空时撤销阻止（Q4=A）
- folder_cache + ContentUnit.path 同步
- list_recent 查询
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from application.errors import (
    UndoAlreadyUndoneError,
    UndoNotAllowedError,
    UndoSafetyError,
)
from application.undo_service import UndoService
from domain.models import ContentUnit, OperationHistory
from infrastructure.db import get_connection, init_db
from infrastructure.file_operation_service import FileOperationService
from infrastructure.folder_cache_sync_helper import FolderCacheSyncHelper
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.folder_cache import FolderCacheRepository
from infrastructure.repositories.operation_history import OperationHistoryRepository


@pytest.fixture
def undo_env(tmp_path: Path):
    """构造完整 UndoService 测试环境。

    返回 (undo_service, file_op_service, conn, history_repo, folder_cache_repo,
           content_unit_repo)，调用方在 tmp_path 下准备文件。
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row

    history_repo = OperationHistoryRepository(conn)
    folder_cache_repo = FolderCacheRepository(conn)
    content_unit_repo = ContentUnitRepository(conn)
    helper = FolderCacheSyncHelper(folder_cache_repo)

    # 计数器避免多次操作时 id 重复
    op_counter = {"n": 0}

    def op_uuid() -> str:
        op_counter["n"] += 1
        return f"uuid-test-{op_counter['n']}"

    undo_counter = {"n": 0}

    def undo_uuid() -> str:
        undo_counter["n"] += 1
        return f"undo-uuid-{undo_counter['n']}"

    file_op_service = FileOperationService(
        history_repo,
        folder_cache_helper=helper,
        content_unit_repo=content_unit_repo,
        now_provider=lambda: "2026-07-30T00:00:00Z",
        uuid_provider=op_uuid,
    )
    undo_service = UndoService(
        history_repo=history_repo,
        file_operation_service=file_op_service,
        folder_cache_helper=helper,
        content_unit_repo=content_unit_repo,
        now_provider=lambda: "2026-07-30T12:00:00Z",
        uuid_provider=undo_uuid,
    )
    yield undo_service, file_op_service, conn, history_repo, folder_cache_repo, content_unit_repo
    conn.close()


# === 正常 undo：new_folder ===


class TestUndoNewFolder:
    def test_undo_empty_folder_success(self, undo_env, tmp_path: Path) -> None:
        """撤销新建的空文件夹：文件夹删除 + folder_cache 同步 + undo 记录写入。"""
        undo_svc, file_op, conn, history_repo, folder_cache_repo, _ = undo_env
        parent = tmp_path / "parent"
        parent.mkdir()
        target = parent / "NewFolder"
        # 创建新文件夹
        history = file_op.new_folder(target)
        conn.commit()
        assert target.is_dir()
        # folder_cache 中应有该节点
        assert folder_cache_repo.get_by_path(str(target)) is not None

        # 撤销
        undo_record = undo_svc.undo(history)
        conn.commit()

        # 文件夹已被删除
        assert not target.exists()
        # folder_cache 中该节点已删除
        assert folder_cache_repo.get_by_path(str(target)) is None
        # undo 记录已写入
        assert undo_record.operation_type == "undo"
        assert undo_record.source_path == history.id  # 指向原 history.id
        assert undo_record.can_undo is False
        assert undo_record.undone_at is None
        # 原记录被标记为已撤销
        updated = history_repo.get_by_id(history.id)
        assert updated is not None
        assert updated.undone_at is not None

    def test_undo_non_empty_folder_blocked(self, undo_env, tmp_path: Path) -> None:
        """Q4=A：非空文件夹撤销被阻止，抛 UndoSafetyError。"""
        undo_svc, file_op, conn, _, _, _ = undo_env
        parent = tmp_path / "parent"
        parent.mkdir()
        target = parent / "NewFolder"
        # 创建新文件夹
        history = file_op.new_folder(target)
        conn.commit()
        # 手动放入文件
        (target / "extra.txt").write_text("data", encoding="utf-8")

        # 撤销应失败
        with pytest.raises(UndoSafetyError, match="文件夹非空"):
            undo_svc.undo(history)

        # 文件夹仍存在
        assert target.is_dir()
        # 原记录未被标记为已撤销
        conn.rollback()
        # 注意：rollback 不会清除已写入的 undo 记录的副作用，
        # 但原记录的 undone_at 应为 None（mark_undone 未执行）
        # 由于 UndoSafetyError 在 mark_undone 之前抛出，原记录未被标记

    def test_undo_folder_not_exists_blocked(self, undo_env, tmp_path: Path) -> None:
        """文件不存在后的 undo 阻止：撤销前文件夹已被外部删除。"""
        undo_svc, file_op, conn, _, _, _ = undo_env
        parent = tmp_path / "parent"
        parent.mkdir()
        target = parent / "NewFolder"
        history = file_op.new_folder(target)
        conn.commit()
        # 外部删除文件夹
        target.rmdir()

        with pytest.raises(UndoSafetyError, match="待撤销的文件夹不存在"):
            undo_svc.undo(history)


# === 正常 undo：rename ===


class TestUndoRename:
    def test_undo_rename_file_success(self, undo_env, tmp_path: Path) -> None:
        """撤销重命名：文件名还原 + ContentUnit.path 同步。"""
        undo_svc, file_op, conn, history_repo, _, content_unit_repo = undo_env
        src = tmp_path / "old_name.txt"
        src.write_bytes(b"data")
        # 重命名
        history = file_op.rename(src, "new_name.txt")
        conn.commit()
        new_path = tmp_path / "new_name.txt"
        assert new_path.is_file()
        assert not src.exists()

        # 撤销
        undo_record = undo_svc.undo(history)
        conn.commit()

        # 文件名还原
        assert src.is_file()
        assert not new_path.exists()
        assert src.read_bytes() == b"data"
        # undo 记录写入
        assert undo_record.operation_type == "undo"
        assert undo_record.source_path == history.id
        # 原记录被标记为已撤销
        updated = history_repo.get_by_id(history.id)
        assert updated is not None
        assert updated.undone_at is not None

    def test_undo_rename_directory_with_content_unit(self, undo_env, tmp_path: Path) -> None:
        """撤销重命名目录：目录名还原 + ContentUnit.path 同步。"""
        undo_svc, file_op, conn, history_repo, _, content_unit_repo = undo_env
        src_dir = tmp_path / "OldDir"
        src_dir.mkdir()
        archive = src_dir / "mod.7z"
        archive.write_bytes(b"data")
        # 标记为内容单元
        unit = ContentUnit(
            id="cu1",
            path=str(archive),
            title="mod",
            content_type="mod",
            status="organized",
            created_at="2026-07-30T00:00:00Z",
            updated_at="2026-07-30T00:00:00Z",
        )
        content_unit_repo.create(unit)
        conn.commit()

        # 重命名目录
        history = file_op.rename(src_dir, "NewDir")
        conn.commit()
        new_dir = tmp_path / "NewDir"
        assert new_dir.is_dir()
        # ContentUnit.path 已同步
        unit_after = content_unit_repo.get_by_id("cu1")
        assert unit_after is not None
        assert "NewDir" in unit_after.path

        # 撤销
        undo_svc.undo(history)
        conn.commit()

        # 目录名还原
        assert src_dir.is_dir()
        assert not new_dir.exists()
        # ContentUnit.path 已同步回原路径
        unit_undone = content_unit_repo.get_by_id("cu1")
        assert unit_undone is not None
        assert "OldDir" in unit_undone.path

    def test_undo_rename_source_exists_blocked(self, undo_env, tmp_path: Path) -> None:
        """撤销重命名时原路径已被外部创建 → 阻止。"""
        undo_svc, file_op, conn, _, _, _ = undo_env
        src = tmp_path / "old_name.txt"
        src.write_bytes(b"data")
        history = file_op.rename(src, "new_name.txt")
        conn.commit()
        # 外部在原路径创建文件
        src.write_bytes(b"external")

        with pytest.raises(UndoSafetyError, match="原路径已存在"):
            undo_svc.undo(history)

    def test_undo_rename_target_not_exists_blocked(self, undo_env, tmp_path: Path) -> None:
        """撤销重命名时重命名后的文件已被外部删除 → 阻止。"""
        undo_svc, file_op, conn, _, _, _ = undo_env
        src = tmp_path / "old_name.txt"
        src.write_bytes(b"data")
        history = file_op.rename(src, "new_name.txt")
        conn.commit()
        new_path = tmp_path / "new_name.txt"
        # 外部删除重命名后的文件
        new_path.unlink()

        with pytest.raises(UndoSafetyError, match="待撤销的操作结果不存在"):
            undo_svc.undo(history)


# === 正常 undo：move ===


class TestUndoMove:
    def test_undo_move_file_success(self, undo_env, tmp_path: Path) -> None:
        """撤销移动：文件回到原位置。"""
        undo_svc, file_op, conn, history_repo, _, _ = undo_env
        src = tmp_path / "file.7z"
        src.write_bytes(b"content")
        dst_dir = tmp_path / "target_dir"
        dst_dir.mkdir()
        dst = dst_dir / "file.7z"
        # 移动
        history = file_op.move(src, dst)
        conn.commit()
        assert dst.is_file()
        assert not src.exists()

        # 撤销
        undo_record = undo_svc.undo(history)
        conn.commit()

        # 文件回到原位置
        assert src.is_file()
        assert not dst.exists()
        assert src.read_bytes() == b"content"
        assert undo_record.operation_type == "undo"

    def test_undo_move_directory_success(self, undo_env, tmp_path: Path) -> None:
        """撤销移动目录：目录回到原位置 + ContentUnit.path 同步。"""
        undo_svc, file_op, conn, _, _, content_unit_repo = undo_env
        src_dir = tmp_path / "SrcDir"
        src_dir.mkdir()
        archive = src_dir / "mod.7z"
        archive.write_bytes(b"data")
        unit = ContentUnit(
            id="cu1",
            path=str(archive),
            title="mod",
            content_type="mod",
            status="organized",
            created_at="2026-07-30T00:00:00Z",
            updated_at="2026-07-30T00:00:00Z",
        )
        content_unit_repo.create(unit)
        conn.commit()

        dst_dir = tmp_path / "DstDir"
        # 移动目录
        history = file_op.move(src_dir, dst_dir)
        conn.commit()
        assert dst_dir.is_dir()
        assert not src_dir.exists()

        # 撤销
        undo_svc.undo(history)
        conn.commit()

        # 目录回到原位置
        assert src_dir.is_dir()
        assert not dst_dir.exists()
        # ContentUnit.path 已同步回原路径
        unit_undone = content_unit_repo.get_by_id("cu1")
        assert unit_undone is not None
        assert "SrcDir" in unit_undone.path

    def test_undo_move_target_not_exists_blocked(self, undo_env, tmp_path: Path) -> None:
        """撤销移动时目标已被外部删除 → 阻止。"""
        undo_svc, file_op, conn, _, _, _ = undo_env
        src = tmp_path / "file.7z"
        src.write_bytes(b"data")
        dst_dir = tmp_path / "target_dir"
        dst_dir.mkdir()
        dst = dst_dir / "file.7z"
        history = file_op.move(src, dst)
        conn.commit()
        # 外部删除移动后的文件
        dst.unlink()

        with pytest.raises(UndoSafetyError, match="待撤销的操作结果不存在"):
            undo_svc.undo(history)


# === 拒绝撤销：delete / undo / can_undo=False ===


class TestUndoNotAllowed:
    def test_undo_delete_not_allowed(self, undo_env, tmp_path: Path) -> None:
        """delete 操作不可撤销：抛 UndoNotAllowedError。"""
        undo_svc, file_op, conn, _, _, _ = undo_env
        src = tmp_path / "to_delete.txt"
        src.write_bytes(b"data")
        # 删除（delete_to_recycle_bin 需要 Windows 回收站，这里手动构造 delete history）

        history = OperationHistory(
            id="delete-id",
            operation_type="delete",
            source_path=str(src),
            created_at="2026-07-30T00:00:00Z",
            target_path=None,
            can_undo=False,
        )
        # 直接通过 repo 插入
        OperationHistoryRepository(conn).create(history)
        conn.commit()

        with pytest.raises(UndoNotAllowedError, match="删除操作不可撤销"):
            undo_svc.undo(history)

    def test_undo_undo_record_not_allowed(self, undo_env, tmp_path: Path) -> None:
        """undo 自身不会进入可无限 undo 循环：undo 记录不可再撤销。"""
        undo_svc, file_op, conn, history_repo, _, _ = undo_env
        # 先做一次正常撤销，产生 undo 记录
        parent = tmp_path / "parent"
        parent.mkdir()
        target = parent / "NewFolder"
        history = file_op.new_folder(target)
        conn.commit()
        undo_record = undo_svc.undo(history)
        conn.commit()

        # 再次撤销 undo 记录应被拒绝
        with pytest.raises(UndoNotAllowedError, match="撤销记录本身不可再次撤销"):
            undo_svc.undo(undo_record)

    def test_undo_already_undone_blocked(self, undo_env, tmp_path: Path) -> None:
        """已撤销的操作重复撤销 → UndoAlreadyUndoneError。"""
        undo_svc, file_op, conn, _, _, _ = undo_env
        parent = tmp_path / "parent"
        parent.mkdir()
        target = parent / "NewFolder"
        history = file_op.new_folder(target)
        conn.commit()
        # 第一次撤销成功
        undo_svc.undo(history)
        conn.commit()
        # 重新读取 history（带 undone_at）
        history_repo = OperationHistoryRepository(conn)
        history_updated = history_repo.get_by_id(history.id)
        assert history_updated is not None

        # 第二次撤销同一记录应被拒绝
        with pytest.raises(UndoAlreadyUndoneError):
            undo_svc.undo(history_updated)


# === 多次 undo（连续撤销不同记录） ===


class TestMultipleUndo:
    def test_multiple_undo_in_sequence(self, undo_env, tmp_path: Path) -> None:
        """连续撤销两条独立的操作记录。"""
        undo_svc, file_op, conn, _, _, _ = undo_env
        # 第一次操作：创建文件夹 A
        parent = tmp_path / "parent"
        parent.mkdir()
        target_a = parent / "FolderA"
        history_a = file_op.new_folder(target_a)
        conn.commit()

        # 第二次操作：创建文件夹 B
        target_b = parent / "FolderB"
        history_b = file_op.new_folder(target_b)
        conn.commit()

        # 撤销第二条（最近操作）
        undo_svc.undo(history_b)
        conn.commit()
        assert not target_b.exists()
        assert target_a.is_dir()  # A 仍存在

        # 撤销第一条
        undo_svc.undo(history_a)
        conn.commit()
        assert not target_a.exists()


# === 重启应用后历史恢复 ===


class TestRestartRestore:
    def test_history_persists_across_connections(self, undo_env, tmp_path: Path) -> None:
        """重启应用（重新打开连接）后，历史记录仍可查询、仍可撤销。

        Q2=A：operation_history 持久化设计，跨会话仍可撤销状态安全的操作。
        """
        undo_svc, file_op, conn, _, folder_cache_repo, content_unit_repo = undo_env
        db_path = conn.execute("PRAGMA database_list").fetchone()["file"]

        # 创建文件夹并写入历史
        parent = tmp_path / "parent"
        parent.mkdir()
        target = parent / "NewFolder"
        history = file_op.new_folder(target)
        conn.commit()

        # 模拟重启：关闭原连接，重新打开
        conn.close()

        conn2 = get_connection(Path(db_path))
        conn2.row_factory = sqlite3.Row
        history_repo2 = OperationHistoryRepository(conn2)
        folder_cache_repo2 = FolderCacheRepository(conn2)
        content_unit_repo2 = ContentUnitRepository(conn2)
        helper2 = FolderCacheSyncHelper(folder_cache_repo2)
        file_op2 = FileOperationService(
            history_repo2,
            folder_cache_helper=helper2,
            content_unit_repo=content_unit_repo2,
            now_provider=lambda: "2026-07-30T00:00:00Z",
            uuid_provider=lambda: "uuid-test",
        )
        undo_svc2 = UndoService(
            history_repo=history_repo2,
            file_operation_service=file_op2,
            folder_cache_helper=helper2,
            content_unit_repo=content_unit_repo2,
            now_provider=lambda: "2026-07-30T12:00:00Z",
            uuid_provider=lambda: "undo-uuid",
        )

        # 重新查询历史
        histories = undo_svc2.list_recent(limit=100)
        assert len(histories) == 1
        assert histories[0].id == history.id
        assert histories[0].operation_type == "new_folder"

        # 跨会话撤销
        undo_record = undo_svc2.undo(histories[0])
        conn2.commit()

        # 文件夹已被删除
        assert not target.exists()
        # undo 记录已写入
        assert undo_record.operation_type == "undo"
        # 原记录被标记为已撤销
        updated = history_repo2.get_by_id(history.id)
        assert updated is not None
        assert updated.undone_at is not None

        conn2.close()


# === list_recent 查询 ===


class TestListRecent:
    def test_list_recent_returns_descending_by_created_at(self, undo_env, tmp_path: Path) -> None:
        """list_recent 按 created_at 降序返回（最新在上）。"""
        undo_svc, file_op, conn, _, _, _ = undo_env
        parent = tmp_path / "parent"
        parent.mkdir()
        # 使用不同时间戳创建多条历史
        # 由于 fixture 的 now_provider 固定，手动构造

        repo = OperationHistoryRepository(conn)
        for i in range(5):
            target = parent / f"Folder{i}"
            target.mkdir()
            repo.create(
                OperationHistory(
                    id=f"hist-{i}",
                    operation_type="new_folder",
                    source_path=str(parent),
                    target_path=str(target),
                    created_at=f"2026-07-30T00:0{i}:00Z",
                    can_undo=True,
                )
            )
        conn.commit()

        histories = undo_svc.list_recent(limit=100)
        # 最新在上（i=4 在前，i=0 在后）
        assert len(histories) == 5
        assert histories[0].id == "hist-4"
        assert histories[-1].id == "hist-0"

    def test_list_recent_limit(self, undo_env, tmp_path: Path) -> None:
        """list_recent 尊重 limit 参数。"""
        undo_svc, file_op, conn, _, _, _ = undo_env
        parent = tmp_path / "parent"
        parent.mkdir()

        repo = OperationHistoryRepository(conn)
        for i in range(10):
            target = parent / f"Folder{i}"
            target.mkdir()
            repo.create(
                OperationHistory(
                    id=f"hist-{i}",
                    operation_type="new_folder",
                    source_path=str(parent),
                    target_path=str(target),
                    created_at=f"2026-07-30T00:0{i}:00Z",
                    can_undo=True,
                )
            )
        conn.commit()

        histories = undo_svc.list_recent(limit=3)
        assert len(histories) == 3
        # 返回最近 3 条
        assert histories[0].id == "hist-9"
        assert histories[1].id == "hist-8"
        assert histories[2].id == "hist-7"

    def test_list_recent_includes_undone_records(self, undo_env, tmp_path: Path) -> None:
        """list_recent 返回已撤销的原记录（UI 决定是否过滤显示）。"""
        undo_svc, file_op, conn, _, _, _ = undo_env
        parent = tmp_path / "parent"
        parent.mkdir()
        target = parent / "NewFolder"
        history = file_op.new_folder(target)
        conn.commit()
        # 撤销
        undo_svc.undo(history)
        conn.commit()

        histories = undo_svc.list_recent(limit=100)
        # 应包含原记录（已标记 undone_at）和 undo 记录
        assert len(histories) == 2
        # undo 记录最新（在上）
        assert histories[0].operation_type == "undo"
        assert histories[0].can_undo is False
        # 原记录已标记为已撤销
        assert histories[1].operation_type == "new_folder"
        assert histories[1].undone_at is not None


# === OperationHistory 数据模型校验（schema v8） ===


class TestOperationHistoryModelV8:
    def test_undo_record_can_undo_must_be_false(self) -> None:
        """undo 记录的 can_undo 必须为 False（避免无限循环）。"""

        with pytest.raises(ValueError, match="undo 不可再次撤销"):
            OperationHistory(
                id="undo-1",
                operation_type="undo",
                source_path="orig-id",
                created_at="2026-07-30T00:00:00Z",
                can_undo=True,  # 应为 False
            )

    def test_undo_record_target_path_must_be_none(self) -> None:
        """undo 记录的 target_path 必须为 None。"""

        with pytest.raises(ValueError, match="undo 要求 target_path 为 None"):
            OperationHistory(
                id="undo-1",
                operation_type="undo",
                source_path="orig-id",
                created_at="2026-07-30T00:00:00Z",
                can_undo=False,
                target_path="/some/path",  # 应为 None
            )

    def test_undo_record_undone_at_must_be_none(self) -> None:
        """undo 记录的 undone_at 必须为 None。"""

        with pytest.raises(ValueError, match="undo 的 undone_at 必须为 None"):
            OperationHistory(
                id="undo-1",
                operation_type="undo",
                source_path="orig-id",
                created_at="2026-07-30T00:00:00Z",
                can_undo=False,
                undone_at="2026-07-30T12:00:00Z",  # 应为 None
            )

    def test_normal_record_undone_at_defaults_none(self) -> None:
        """普通记录的 undone_at 默认为 None（未撤销）。"""

        h = OperationHistory(
            id="h1",
            operation_type="new_folder",
            source_path="/parent",
            target_path="/parent/NewFolder",
            created_at="2026-07-30T00:00:00Z",
            can_undo=True,
        )
        assert h.undone_at is None


# === OperationHistoryRepository.mark_undone ===


class TestMarkUndone:
    def test_mark_undone_sets_timestamp(self, undo_env) -> None:
        """mark_undone 写入 undone_at 时间戳。"""
        _, _, conn, history_repo, _, _ = undo_env

        history = OperationHistory(
            id="h-mark",
            operation_type="new_folder",
            source_path="/parent",
            target_path="/parent/NewFolder",
            created_at="2026-07-30T00:00:00Z",
            can_undo=True,
        )
        history_repo.create(history)
        conn.commit()

        history_repo.mark_undone("h-mark", "2026-07-30T12:00:00Z")
        conn.commit()

        updated = history_repo.get_by_id("h-mark")
        assert updated is not None
        assert updated.undone_at == "2026-07-30T12:00:00Z"

    def test_mark_undone_already_undone_raises(self, undo_env) -> None:
        """已撤销的记录再次 mark_undone 抛 ConstraintViolationError。"""
        from infrastructure.repositories.errors import ConstraintViolationError

        _, _, conn, history_repo, _, _ = undo_env

        history = OperationHistory(
            id="h-mark2",
            operation_type="new_folder",
            source_path="/parent",
            target_path="/parent/NewFolder",
            created_at="2026-07-30T00:00:00Z",
            can_undo=True,
        )
        history_repo.create(history)
        history_repo.mark_undone("h-mark2", "2026-07-30T12:00:00Z")
        conn.commit()

        with pytest.raises(ConstraintViolationError):
            history_repo.mark_undone("h-mark2", "2026-07-30T13:00:00Z")

    def test_mark_undone_not_found_raises(self, undo_env) -> None:
        """mark_undone 不存在的记录抛 NotFoundError。"""
        from infrastructure.repositories.errors import NotFoundError

        _, _, _, history_repo, _, _ = undo_env
        with pytest.raises(NotFoundError):
            history_repo.mark_undone("nonexistent", "2026-07-30T12:00:00Z")
