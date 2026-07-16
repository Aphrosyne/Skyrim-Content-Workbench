"""OperationHistoryRepository。

负责 OperationHistory dataclass 与 operation_history 表之间的转换。
不访问文件系统；source_path / target_path 仅作为字符串存储。
schema v4 引入（见 migrations.py migrate_v3_to_v4）。
"""

from __future__ import annotations

import logging
import sqlite3

from domain.models import OperationHistory
from infrastructure.repositories.errors import (
    ConstraintViolationError,
    NotFoundError,
    RepositoryError,
)

logger = logging.getLogger(__name__)


class OperationHistoryRepository:
    """OperationHistory 的 CRUD。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, history: OperationHistory) -> OperationHistory:
        """插入 OperationHistory。写操作不自提交，由 application 层控制事务边界。"""
        try:
            self._conn.execute(
                """
                INSERT INTO operation_history (
                    id, operation_type, source_path, target_path, created_at, can_undo
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    history.id,
                    history.operation_type,
                    history.source_path,
                    history.target_path,
                    history.created_at,
                    int(history.can_undo),
                ),
            )
        except sqlite3.IntegrityError as e:
            raise ConstraintViolationError(f"无法创建 OperationHistory：{e}") from e
        except sqlite3.Error as e:
            raise RepositoryError(f"无法创建 OperationHistory：{e}") from e
        return self.get_by_id(history.id)  # type: ignore[return-value]

    def get_by_id(self, history_id: str) -> OperationHistory | None:
        """按 ID 查询；不存在返回 None。"""
        try:
            row = self._conn.execute(
                "SELECT * FROM operation_history WHERE id = ?",
                (history_id,),
            ).fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法查询 OperationHistory：{e}") from e
        if row is None:
            return None
        return self._row_to_model(row)

    def list_all(self) -> list[OperationHistory]:
        """返回全部 OperationHistory，按 created_at 升序排序。"""
        try:
            rows = self._conn.execute(
                "SELECT * FROM operation_history ORDER BY created_at ASC"
            ).fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法列出 OperationHistory：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def delete(self, history_id: str) -> None:
        """按 ID 删除。不存在抛 NotFoundError。"""
        try:
            cur = self._conn.execute(
                "DELETE FROM operation_history WHERE id = ?",
                (history_id,),
            )
        except sqlite3.Error as e:
            raise RepositoryError(f"无法删除 OperationHistory：{e}") from e
        if cur.rowcount == 0:
            raise NotFoundError(f"OperationHistory 不存在：{history_id}")

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> OperationHistory:
        return OperationHistory(
            id=row["id"],
            operation_type=row["operation_type"],
            source_path=row["source_path"],
            target_path=row["target_path"],
            created_at=row["created_at"],
            can_undo=bool(row["can_undo"]),
        )
