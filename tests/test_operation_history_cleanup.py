"""操作历史自动清理测试（Stage 5 Task 3b 问题2 修复）。

覆盖：
- OperationHistoryRepository.count()
- OperationHistoryRepository.delete_oldest_exceeding(limit, preserve_can_undo)
  - 超过上限时删除最旧记录
  - 未超过上限时不删除
  - preserve_can_undo=True 时保留可撤销记录
  - preserve_can_undo=False 时不区分删除
- FileOperationService._create_history 自动触发清理
  - 超过 max_history_records 时自动清理
  - max_history_records=0 时关闭清理
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from domain.models import OperationHistory
from infrastructure.db import init_db
from infrastructure.file_operation_service import FileOperationService
from infrastructure.repositories.operation_history import OperationHistoryRepository


@pytest.fixture
def history_repo(tmp_path: Path) -> tuple[OperationHistoryRepository, sqlite3.Connection]:
    """构造内存仓储 + 已初始化的数据库。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    repo = OperationHistoryRepository(conn)
    return repo, conn


def _make_history(
    idx: int,
    *,
    can_undo: bool = False,
    undone_at: str | None = None,
    operation_type: str = "move",
) -> OperationHistory:
    """构造测试用 OperationHistory 记录。"""
    return OperationHistory(
        id=f"hist-{idx:04d}",
        operation_type=operation_type,
        source_path=f"D:/src{idx}.txt",
        target_path=f"D:/dst{idx}.txt",
        created_at=f"2026-07-{idx:02d}T00:00:00Z",
        can_undo=can_undo,
        undone_at=undone_at,
    )


class TestCount:
    def test_count_empty(self, history_repo) -> None:
        """空表 count 返回 0。"""
        repo, _ = history_repo
        assert repo.count() == 0

    def test_count_after_inserts(self, history_repo) -> None:
        """插入 5 条后 count 返回 5。"""
        repo, _ = history_repo
        for i in range(5):
            repo.create(_make_history(i))
        assert repo.count() == 5


class TestDeleteOldestExceeding:
    def test_no_delete_when_below_limit(self, history_repo) -> None:
        """记录数未超过上限时不删除。"""
        repo, _ = history_repo
        for i in range(5):
            repo.create(_make_history(i))

        deleted = repo.delete_oldest_exceeding(10)
        assert deleted == 0
        assert repo.count() == 5

    def test_no_delete_when_at_limit(self, history_repo) -> None:
        """记录数恰好等于上限时不删除。"""
        repo, _ = history_repo
        for i in range(5):
            repo.create(_make_history(i))

        deleted = repo.delete_oldest_exceeding(5)
        assert deleted == 0
        assert repo.count() == 5

    def test_delete_oldest_when_exceeding(self, history_repo) -> None:
        """超过上限时删除最旧的记录。"""
        repo, _ = history_repo
        for i in range(1, 11):  # 10 条，created_at = 07-01 ~ 07-10
            repo.create(_make_history(i))

        deleted = repo.delete_oldest_exceeding(7)  # 删除 3 条最旧的
        assert deleted == 3
        assert repo.count() == 7
        # 最旧的 3 条（07-01, 07-02, 07-03）被删除
        assert repo.get_by_id("hist-0001") is None
        assert repo.get_by_id("hist-0002") is None
        assert repo.get_by_id("hist-0003") is None
        assert repo.get_by_id("hist-0004") is not None

    def test_preserve_can_undo_true_keeps_undoable(self, history_repo) -> None:
        """preserve_can_undo=True 时保留可撤销记录。"""
        repo, _ = history_repo
        # 插入 5 条不可撤销 + 3 条可撤销（最旧）
        for i in range(1, 6):
            repo.create(_make_history(i, can_undo=False))
        for i in range(6, 9):
            repo.create(_make_history(i, can_undo=True))
        # 总共 8 条，上限 5，需删除 3 条
        # preserve_can_undo=True → 仅删除 can_undo=0 的最旧 3 条

        deleted = repo.delete_oldest_exceeding(5, preserve_can_undo=True)
        assert deleted == 3
        assert repo.count() == 5
        # 可撤销记录全保留
        assert repo.get_by_id("hist-0006") is not None
        assert repo.get_by_id("hist-0007") is not None
        assert repo.get_by_id("hist-0008") is not None
        # 最旧的 3 条不可撤销被删除
        assert repo.get_by_id("hist-0001") is None
        assert repo.get_by_id("hist-0002") is None
        assert repo.get_by_id("hist-0003") is None

    def test_preserve_can_undo_false_deletes_all_types(self, history_repo) -> None:
        """preserve_can_undo=False 时不区分，直接按最旧删除。"""
        repo, _ = history_repo
        for i in range(1, 6):
            repo.create(_make_history(i, can_undo=False))
        for i in range(6, 9):
            repo.create(_make_history(i, can_undo=True))

        deleted = repo.delete_oldest_exceeding(5, preserve_can_undo=False)
        assert deleted == 3
        # 最旧的 3 条（不分类型）被删除
        assert repo.get_by_id("hist-0001") is None
        assert repo.get_by_id("hist-0002") is None
        assert repo.get_by_id("hist-0003") is None

    def test_preserve_can_undo_skips_undone_records_too(self, history_repo) -> None:
        """已撤销记录（undone_at 非空）可被清理。"""
        repo, _ = history_repo
        # 5 条不可撤销 + 3 条已撤销（最旧，undone_at 非空）
        for i in range(1, 6):
            repo.create(_make_history(i, can_undo=True))  # 可撤销但未撤销 → 保留
        for i in range(6, 9):
            repo.create(
                _make_history(i, can_undo=True, undone_at="2026-07-30T00:00:00Z")
            )  # 已撤销 → 可清理

        deleted = repo.delete_oldest_exceeding(5, preserve_can_undo=True)
        assert deleted == 3
        # 已撤销的 3 条被清理
        assert repo.get_by_id("hist-0006") is None
        assert repo.get_by_id("hist-0007") is None
        assert repo.get_by_id("hist-0008") is None
        # 未撤销的可撤销记录全保留
        for i in range(1, 6):
            assert repo.get_by_id(f"hist-{i:04d}") is not None

    def test_zero_limit_disables_cleanup(self, history_repo) -> None:
        """limit=0 关闭清理。"""
        repo, _ = history_repo
        for i in range(5):
            repo.create(_make_history(i))

        deleted = repo.delete_oldest_exceeding(0)
        assert deleted == 0
        assert repo.count() == 5

    def test_negative_limit_disables_cleanup(self, history_repo) -> None:
        """负 limit 不清理。"""
        repo, _ = history_repo
        for i in range(5):
            repo.create(_make_history(i))

        deleted = repo.delete_oldest_exceeding(-1)
        assert deleted == 0


class TestFileOperationServiceAutoCleanup:
    """FileOperationService._create_history 自动清理。"""

    def test_auto_cleanup_on_exceed(self, tmp_path: Path) -> None:
        """写入不可撤销历史后总数超过上限时自动清理。"""
        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        repo = OperationHistoryRepository(conn)
        uuid_counter = [0]

        def uuid_provider() -> str:
            uuid_counter[0] += 1
            return f"uuid-{uuid_counter[0]:04d}"

        # max_history_records=3，写入第 4 条不可撤销记录时触发清理
        svc = FileOperationService(
            repo,
            now_provider=lambda: "2026-07-30T00:00:00Z",
            uuid_provider=uuid_provider,
            max_history_records=3,
        )

        # 写入 4 条不可撤销历史（copy 操作，can_undo=False）
        for i in range(4):
            s = tmp_path / f"src{i}.txt"
            s.write_text("x")
            d = tmp_path / f"dst{i}.txt"
            svc.copy(s, d)
            conn.commit()

        # 总数应 <= 3（不可撤销记录被清理）
        assert repo.count() <= 3

    def test_auto_cleanup_disabled_when_zero(self, tmp_path: Path) -> None:
        """max_history_records=0 关闭自动清理。"""
        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        repo = OperationHistoryRepository(conn)
        uuid_counter = [0]

        def uuid_provider() -> str:
            uuid_counter[0] += 1
            return f"uuid-{uuid_counter[0]:04d}"

        svc = FileOperationService(
            repo,
            now_provider=lambda: "2026-07-30T00:00:00Z",
            uuid_provider=uuid_provider,
            max_history_records=0,
        )

        for i in range(10):
            s = tmp_path / f"s{i}.txt"
            s.write_text("x")
            d = tmp_path / f"d{i}.txt"
            svc.move(s, d)
            conn.commit()

        # 0 = 关闭清理，全部保留
        assert repo.count() == 10

    def test_auto_cleanup_preserves_undoable(self, tmp_path: Path) -> None:
        """自动清理时保留可撤销记录。"""
        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        repo = OperationHistoryRepository(conn)
        uuid_counter = [0]
        time_counter = [0]

        def uuid_provider() -> str:
            uuid_counter[0] += 1
            return f"uuid-{uuid_counter[0]:04d}"

        def now_provider() -> str:
            time_counter[0] += 1
            return f"2026-07-{time_counter[0]:02d}T00:00:00Z"

        svc = FileOperationService(
            repo,
            now_provider=now_provider,
            uuid_provider=uuid_provider,
            max_history_records=5,
        )

        # 写入 5 条可撤销记录（new_folder，can_undo=True）
        for i in range(5):
            folder = tmp_path / f"folder{i}"
            svc.new_folder(folder)
            conn.commit()

        assert repo.count() == 5
        # 所有记录 can_undo=1（new_folder 可撤销）
        assert all(r["can_undo"] == 1 for r in conn.execute("SELECT * FROM operation_history"))

        # 写入第 6 条不可撤销记录（copy，can_undo=False，时间戳最新）
        src = tmp_path / "src.txt"
        src.write_text("src")
        dst = tmp_path / "dst.txt"
        svc.copy(src, dst)
        conn.commit()

        # copy 记录应保留（最新写入，不会被清理删除）
        copy_records = conn.execute(
            "SELECT * FROM operation_history WHERE operation_type = 'copy'"
        ).fetchall()
        assert len(copy_records) == 1
