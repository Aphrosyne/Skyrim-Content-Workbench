"""OperationLogRepository。

负责 OperationLog dataclass 与 operation_log 表之间的转换。
不访问文件系统；source_paths/target_paths/affected_asset_ids 序列化为 JSON 数组。
undo_payload 为 JSON 字符串，内部结构由 Task 5 定义（Q14）。
"""

from __future__ import annotations

import json
import logging
import sqlite3

from domain.models import ConflictPolicy, OperationLog, OperationStatus, OperationType
from infrastructure.repositories.errors import (
    ConstraintViolationError,
    NotFoundError,
    RepositoryError,
)

logger = logging.getLogger(__name__)


class OperationLogRepository:
    """OperationLog 的 CRUD。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, log: OperationLog) -> OperationLog:
        """插入 OperationLog。"""
        try:
            self._conn.execute(
                """
                INSERT INTO operation_log (
                    id, operation_type, status, affected_asset_ids,
                    source_paths, target_paths, conflict_policy,
                    created_at, completed_at, undo_payload, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log.id,
                    log.operation_type.value,
                    log.status.value,
                    json.dumps(log.affected_asset_ids, ensure_ascii=False),
                    json.dumps(log.source_paths, ensure_ascii=False),
                    json.dumps(log.target_paths, ensure_ascii=False),
                    log.conflict_policy.value,
                    log.created_at,
                    log.completed_at,
                    log.undo_payload,
                    log.error_message,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise ConstraintViolationError(f"无法创建 OperationLog：{e}") from e
        except sqlite3.Error as e:
            raise RepositoryError(f"无法创建 OperationLog：{e}") from e
        return self.get_by_id(log.id)  # type: ignore[return-value]

    def get_by_id(self, log_id: str) -> OperationLog | None:
        """按 ID 查询；不存在返回 None。"""
        try:
            row = self._conn.execute(
                "SELECT * FROM operation_log WHERE id = ?",
                (log_id,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法查询 OperationLog：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def list_by_status(self, status: OperationStatus) -> list[OperationLog]:
        """返回指定状态的全部日志。"""
        try:
            rows = self._conn.execute(
                "SELECT * FROM operation_log WHERE status = ? ORDER BY created_at",
                (status.value,),
            ).fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法列出 OperationLog：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def update(self, log: OperationLog) -> OperationLog:
        """全字段更新。实体不存在时抛 NotFoundError。"""
        try:
            cur = self._conn.execute(
                """
                UPDATE operation_log SET
                    operation_type = ?,
                    status = ?,
                    affected_asset_ids = ?,
                    source_paths = ?,
                    target_paths = ?,
                    conflict_policy = ?,
                    completed_at = ?,
                    undo_payload = ?,
                    error_message = ?
                WHERE id = ?
                """,
                (
                    log.operation_type.value,
                    log.status.value,
                    json.dumps(log.affected_asset_ids, ensure_ascii=False),
                    json.dumps(log.source_paths, ensure_ascii=False),
                    json.dumps(log.target_paths, ensure_ascii=False),
                    log.conflict_policy.value,
                    log.completed_at,
                    log.undo_payload,
                    log.error_message,
                    log.id,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise ConstraintViolationError(f"无法更新 OperationLog：{e}") from e
        except sqlite3.Error as e:
            raise RepositoryError(f"无法更新 OperationLog：{e}") from e
        if cur.rowcount == 0:
            raise NotFoundError(f"OperationLog 不存在：{log.id}")
        return self.get_by_id(log.id)  # type: ignore[return-value]

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> OperationLog:
        return OperationLog(
            id=row["id"],
            operation_type=OperationType(row["operation_type"]),
            status=OperationStatus(row["status"]),
            affected_asset_ids=json.loads(row["affected_asset_ids"]),
            source_paths=json.loads(row["source_paths"]),
            target_paths=json.loads(row["target_paths"]),
            conflict_policy=ConflictPolicy(row["conflict_policy"]),
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            undo_payload=row["undo_payload"],
            error_message=row["error_message"],
        )
