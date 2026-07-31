"""事务边界管理器（Unit of Work）。

设计决策 D3（Stage 4.5）：Service 内部使用 UnitOfWork 管理多步写事务，
调用方不负责业务事务控制。

UnitOfWork 封装 SQLite 连接的 commit/rollback，提供 ``transaction()`` 上下文
管理器：

- 成功退出：提交事务
- 异常退出：回滚事务
- 支持嵌套：内层 ``transaction()`` 不实际提交/回滚，仅最外层生效

嵌套场景示例::

    # ContentUnitCreationService.create_content_unit_from_file 用 transaction() 包裹整个方法
    with self._uow.transaction():
        self._folder_cache_repo.create(folder)
        self._file_op.move(source, target)  # 文件操作不在事务范围
        # 内部调用 ContentService.mark_as_content_unit（也用 transaction()）
        # 内层 transaction() 不提交，仅最外层提交，保证 DB 写操作原子性
        unit = self._content.mark_as_content_unit(target_folder)

约束：
- 不访问文件系统（仅管理 DB 事务）
- 文件操作（move/delete/rename）不在事务范围内，无法回滚
- Repository 写操作不自提交（H5 修复），由 Service 通过 UnitOfWork 控制
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class UnitOfWork:
    """事务边界管理器。

    通过 ``transaction()`` 上下文管理器管理多步写操作的事务边界。
    支持嵌套：仅最外层 ``transaction()`` 实际执行 commit/rollback，
    内层仅增加/减少深度计数。

    用法::

        uow = UnitOfWork(conn)
        with uow.transaction():
            repo_a.write(...)
            repo_b.write(...)
        # 成功自动 commit，异常自动 rollback

    嵌套用法（Service 间调用共享同一 UoW 实例）::

        # 外层 Service
        with self._uow.transaction():          # depth 0 → 1
            self._repo.write(...)
            self._other_service.method()        # 内层 Service
            #   with self._uow.transaction():   # depth 1 → 2
            #       self._repo.write(...)
            #   # depth 2 → 1，不提交
        # depth 1 → 0，提交所有写操作
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._depth = 0

    @property
    def depth(self) -> int:
        """当前嵌套深度（供测试验证）。"""
        return self._depth

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """事务上下文管理器。

        - 成功退出且为最外层（depth 1→0）：``conn.commit()``
        - 异常退出且为最外层（depth 1→0）：``conn.rollback()`` + 重新抛出
        - 内层（depth > 1）：仅调整深度计数，不提交/回滚

        Raises:
            原始异常被重新抛出（不吞异常）。
        """
        self._depth += 1
        try:
            yield self._conn
        except BaseException:
            self._depth -= 1
            if self._depth == 0:
                try:
                    self._conn.rollback()
                except sqlite3.Error:
                    logger.exception("事务回滚失败")
            raise
        else:
            self._depth -= 1
            if self._depth == 0:
                try:
                    self._conn.commit()
                except sqlite3.Error:
                    logger.exception("事务提交失败")
                    raise
