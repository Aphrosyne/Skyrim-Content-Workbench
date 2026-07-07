"""OperationLogRepository 测试。"""

from __future__ import annotations

import json
import sqlite3

import pytest

from domain.models import ConflictPolicy, OperationLog, OperationStatus, OperationType
from infrastructure.repositories.errors import (
    ConstraintViolationError,
    NotFoundError,
)
from infrastructure.repositories.operation_log import OperationLogRepository


def _make_log(
    log_id: str = "log-1",
    status: OperationStatus = OperationStatus.PLANNED,
    operation_type: OperationType = OperationType.MOVE,
) -> OperationLog:
    return OperationLog(
        id=log_id,
        operation_type=operation_type,
        status=status,
        conflict_policy=ConflictPolicy.ASK,
        created_at="2026-07-07T00:00:00Z",
        affected_asset_ids=["a1", "a2"],
        source_paths=["D:/src/a.7z", "D:/src/b.7z"],
        target_paths=["D:/dst/a.7z", "D:/dst/b.7z"],
    )


def test_create_and_get(db_connection: sqlite3.Connection) -> None:
    repo = OperationLogRepository(db_connection)
    log = _make_log()
    created = repo.create(log)
    assert created.id == "log-1"
    assert created.status == OperationStatus.PLANNED
    assert created.operation_type == OperationType.MOVE
    assert created.affected_asset_ids == ["a1", "a2"]
    assert created.source_paths == ["D:/src/a.7z", "D:/src/b.7z"]
    assert created.target_paths == ["D:/dst/a.7z", "D:/dst/b.7z"]
    assert created.conflict_policy == ConflictPolicy.ASK
    assert created.completed_at is None
    assert created.undo_payload is None
    assert created.error_message is None

    fetched = repo.get_by_id("log-1")
    assert fetched is not None
    assert fetched.affected_asset_ids == ["a1", "a2"]


def test_get_by_id_not_found(db_connection: sqlite3.Connection) -> None:
    repo = OperationLogRepository(db_connection)
    assert repo.get_by_id("nonexistent") is None


def test_invalid_status_rejected(db_connection: sqlite3.Connection) -> None:
    """非法 status 值应被 CHECK 约束拒绝。"""
    with pytest.raises(ConstraintViolationError):
        # 直接 SQL 注入非法值
        try:
            db_connection.execute(
                "INSERT INTO operation_log (id, operation_type, status, conflict_policy, "
                "created_at) VALUES (?, ?, ?, ?, ?)",
                ("bad", "move", "invalid_status", "ask", "t"),
            )
        except sqlite3.IntegrityError as e:
            raise ConstraintViolationError(str(e)) from e


def test_invalid_conflict_policy_rejected(db_connection: sqlite3.Connection) -> None:
    """B3：仅 'ask' 合法。"""
    with pytest.raises(sqlite3.IntegrityError):
        db_connection.execute(
            "INSERT INTO operation_log (id, operation_type, status, conflict_policy, "
            "created_at) VALUES (?, ?, ?, ?, ?)",
            ("bad", "move", "planned", "overwrite", "t"),
        )


def test_list_by_status(db_connection: sqlite3.Connection) -> None:
    repo = OperationLogRepository(db_connection)
    repo.create(_make_log(log_id="p1", status=OperationStatus.PLANNED))
    repo.create(_make_log(log_id="p2", status=OperationStatus.PLANNED))
    repo.create(_make_log(log_id="c1", status=OperationStatus.COMPLETED))

    planned = repo.list_by_status(OperationStatus.PLANNED)
    assert len(planned) == 2
    assert {lg.id for lg in planned} == {"p1", "p2"}

    completed = repo.list_by_status(OperationStatus.COMPLETED)
    assert len(completed) == 1
    assert completed[0].id == "c1"


def test_update_status_and_completed_at(db_connection: sqlite3.Connection) -> None:
    repo = OperationLogRepository(db_connection)
    log = _make_log()
    repo.create(log)

    log.status = OperationStatus.COMPLETED
    log.completed_at = "2026-07-07T01:00:00Z"
    updated = repo.update(log)
    assert updated.status == OperationStatus.COMPLETED
    assert updated.completed_at == "2026-07-07T01:00:00Z"


def test_update_with_undo_payload(db_connection: sqlite3.Connection) -> None:
    """undo_payload 为 JSON 字符串；内部结构由 Task 5 定义（Q14）。"""
    repo = OperationLogRepository(db_connection)
    log = _make_log()
    repo.create(log)

    payload = json.dumps(
        {"members": [{"asset_id": "a1", "src": "D:/dst/a.7z", "dst": "D:/src/a.7z"}]}
    )
    log.undo_payload = payload
    updated = repo.update(log)
    assert updated.undo_payload == payload


def test_update_with_error_message(db_connection: sqlite3.Connection) -> None:
    repo = OperationLogRepository(db_connection)
    log = _make_log()
    repo.create(log)

    log.status = OperationStatus.FAILED
    log.error_message = "目标目录不可写"
    updated = repo.update(log)
    assert updated.status == OperationStatus.FAILED
    assert updated.error_message == "目标目录不可写"


def test_update_not_found_raises(db_connection: sqlite3.Connection) -> None:
    repo = OperationLogRepository(db_connection)
    with pytest.raises(NotFoundError):
        repo.update(_make_log(log_id="nonexistent"))


def test_chinese_error_message_roundtrip(db_connection: sqlite3.Connection) -> None:
    repo = OperationLogRepository(db_connection)
    log = _make_log()
    log.error_message = "跨盘移动失败：目标盘空间不足"
    repo.create(log)
    fetched = repo.get_by_id("log-1")
    assert fetched is not None
    assert fetched.error_message == "跨盘移动失败：目标盘空间不足"


def test_undo_operation_type(db_connection: sqlite3.Connection) -> None:
    """OperationType.UNDO 应能正确读写。"""
    repo = OperationLogRepository(db_connection)
    log = OperationLog(
        id="undo-1",
        operation_type=OperationType.UNDO,
        status=OperationStatus.PLANNED,
        conflict_policy=ConflictPolicy.ASK,
        created_at="2026-07-07T00:00:00Z",
    )
    repo.create(log)
    fetched = repo.get_by_id("undo-1")
    assert fetched is not None
    assert fetched.operation_type == OperationType.UNDO


def test_empty_list_fields_default(db_connection: sqlite3.Connection) -> None:
    """affected_asset_ids/source_paths/target_paths 默认空数组。"""
    repo = OperationLogRepository(db_connection)
    log = OperationLog(
        id="empty-1",
        operation_type=OperationType.MOVE,
        status=OperationStatus.PLANNED,
        conflict_policy=ConflictPolicy.ASK,
        created_at="2026-07-07T00:00:00Z",
    )
    created = repo.create(log)
    assert created.affected_asset_ids == []
    assert created.source_paths == []
    assert created.target_paths == []

    # 直接查表，确保存储为 '[]'
    row = db_connection.execute(
        "SELECT affected_asset_ids, source_paths, target_paths FROM operation_log WHERE id = ?",
        ("empty-1",),
    ).fetchone()
    assert row["affected_asset_ids"] == "[]"
    assert row["source_paths"] == "[]"
    assert row["target_paths"] == "[]"
