"""OperationHistoryRepository。

负责 OperationHistory dataclass 与 operation_history 表之间的转换。
不访问文件系统；source_path / target_path 仅作为字符串存储。
schema v4 引入（见 migrations.py migrate_v3_to_v4）。
schema v8 扩展 undone_at 列 + operation_type='undo'（Task 6 撤销框架）。
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
        """插入 OperationHistory。写操作不自提交，由 application 层控制事务边界。

        Stage 5 Task 6：支持 undone_at 字段写入（undo 记录本身 undone_at 必为 None，
        原记录通过 mark_undone 单独更新）。
        """
        try:
            self._conn.execute(
                """
                INSERT INTO operation_history (
                    id, operation_type, source_path, target_path,
                    created_at, can_undo, undone_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    history.id,
                    history.operation_type,
                    history.source_path,
                    history.target_path,
                    history.created_at,
                    int(history.can_undo),
                    history.undone_at,
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

    def list_recent(self, limit: int = 100) -> list[OperationHistory]:
        """返回最近的 OperationHistory，按 created_at 降序（最新在上）。

        Stage 5 Task 6：操作历史对话框使用，限制查询条数避免全表加载。
        含 undo 记录本身（用户可看到完整审计链）。
        已撤销的原记录也返回（通过 undone_at 字段判断，UI 层决定是否过滤）。
        """
        if limit <= 0:
            return []
        try:
            rows = self._conn.execute(
                "SELECT * FROM operation_history ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法查询最近 OperationHistory：{e}") from e
        return [self._row_to_model(r) for r in rows]

    def count(self) -> int:
        """返回 operation_history 总记录数。"""
        try:
            row = self._conn.execute("SELECT COUNT(*) FROM operation_history").fetchone()
        except sqlite3.Error as e:
            raise RepositoryError(f"无法统计 OperationHistory：{e}") from e
        return int(row[0]) if row else 0

    def delete_oldest_exceeding(
        self,
        limit: int,
        *,
        preserve_can_undo: bool = True,
    ) -> int:
        """删除超出上限的最旧记录，返回删除条数。

        策略（preserve_can_undo=True）：
        - 仅删除 can_undo=0 或 undone_at IS NOT NULL 的记录
          （不可撤销 / 已撤销的记录无审计价值，可安全清理）
        - 保留 can_undo=1 且 undone_at IS NULL 的记录（可撤销，用户可能需要撤销）
        - 按 created_at 升序删除最旧的，直到总数 <= limit 或无可删记录

        preserve_can_undo=False 时不区分，直接按最旧删除到 limit。

        Args:
            limit: 保留的最大记录数。
            preserve_can_undo: 是否保留可撤销记录（默认 True）。

        Returns:
            实际删除的记录数。
        """
        if limit <= 0:
            return 0  # 0 或负数关闭清理
        total = self.count()
        if total <= limit:
            return 0

        to_delete = total - limit
        deleted = 0
        try:
            if preserve_can_undo:
                # 仅删除不可撤销/已撤销的记录，按 created_at 升序
                rows = self._conn.execute(
                    """
                    SELECT id FROM operation_history
                    WHERE can_undo = 0 OR undone_at IS NOT NULL
                    ORDER BY created_at ASC LIMIT ?
                    """,
                    (to_delete,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id FROM operation_history ORDER BY created_at ASC LIMIT ?",
                    (to_delete,),
                ).fetchall()

            for row in rows:
                self._conn.execute("DELETE FROM operation_history WHERE id = ?", (row["id"],))
                deleted += 1
        except sqlite3.Error as e:
            raise RepositoryError(f"无法清理旧 OperationHistory：{e}") from e

        return deleted

    def mark_undone(self, history_id: str, undone_at: str) -> None:
        """标记原操作为已撤销，写入 undone_at 时间戳。

        Stage 5 Task 6：撤销成功后调用，原记录保留但标记为已撤销，
        避免被再次撤销。配合 operation_type='undo' 的新记录形成审计链。

        不存在抛 NotFoundError；已撤销（undone_at 非空）抛 ConstraintViolationError。
        """
        existing = self.get_by_id(history_id)
        if existing is None:
            raise NotFoundError(f"OperationHistory 不存在：{history_id}")
        if existing.undone_at is not None:
            raise ConstraintViolationError(
                f"OperationHistory 已被撤销：{history_id}（undone_at={existing.undone_at}）"
            )
        try:
            self._conn.execute(
                "UPDATE operation_history SET undone_at = ? WHERE id = ?",
                (undone_at, history_id),
            )
        except sqlite3.Error as e:
            raise RepositoryError(f"无法标记 OperationHistory 为已撤销：{e}") from e

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
        # Stage 5 Task 6：undone_at 可能为 NULL
        # 兼容旧 schema（v7）无 undone_at 列的情况，迁移完成后不应触发
        row_keys = row.keys()
        undone_at = row["undone_at"] if "undone_at" in row_keys else None
        return OperationHistory(
            id=row["id"],
            operation_type=row["operation_type"],
            source_path=row["source_path"],
            target_path=row["target_path"],
            created_at=row["created_at"],
            can_undo=bool(row["can_undo"]),
            undone_at=undone_at,
        )
