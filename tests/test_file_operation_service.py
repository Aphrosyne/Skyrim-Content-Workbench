"""FileOperationService 测试。

覆盖：
- new_folder：创建成功 / 父目录不存在 / 目标已存在 / 写 operation_history / 中文路径
- move：移动文件 / 移动目录 / 源不存在 / 目标已存在 / 跨盘检测 / 自目录检测 /
        保留元数据 / 写 operation_history / 中文路径
- 写操作不自提交
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from application.errors import (
    ConflictError,
    CrossDriveError,
    SelfSubdirectoryError,
    SourceNotFoundError,
)
from domain.models import OperationHistory
from infrastructure.db import get_connection, init_db
from infrastructure.file_operation_service import FileOperationService
from infrastructure.repositories.operation_history import OperationHistoryRepository


@pytest.fixture
def service(tmp_path: Path) -> tuple[FileOperationService, sqlite3.Connection]:
    """构造 FileOperationService + 内存独立连接。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    repo = OperationHistoryRepository(conn)
    svc = FileOperationService(
        repo,
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=lambda: "uuid-test",
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
