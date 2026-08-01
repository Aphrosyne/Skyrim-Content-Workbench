"""数据库事务边界封装（UX 重构 Task 7 Step 1，TD-M31）。

将 MainWindow 的 ``_commit`` / ``_rollback`` / ``_handle_service_error`` 中的
事务逻辑（commit/rollback 回调 + 失败提示 + 异常分类映射）抽取为独立组件，
UI 层不再直接持有裸 connection 回调。

设计约束：
- 不访问文件系统；仅封装数据库事务回调。
- 已注入 UnitOfWork 的 Service 内部已管理事务（成功 commit、失败 rollback），
  调用方应传 ``rollback=False``；未注入 UoW 的 Service 由调用方在此 rollback。
- 所有异常转换为用户可理解的 QMessageBox 提示，技术细节记录日志（TD-M11）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtWidgets import QMessageBox, QWidget

from app import ui_constants as ui
from application.errors import ApplicationError, ConflictError, FileOperationError

logger = logging.getLogger(__name__)


class TransactionScope:
    """数据库事务边界（commit/rollback 回调 + 用户错误提示）。"""

    def __init__(
        self,
        commit_callback: Callable[[], None] | None = None,
        rollback_callback: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """初始化事务边界。

        Args:
            commit_callback: 数据库 commit 回调（通常为 conn.commit）。
            rollback_callback: 数据库 rollback 回调（通常为 conn.rollback）。
            parent: 弹窗父窗口。
        """
        self._commit_callback = commit_callback
        self._rollback_callback = rollback_callback
        self._parent = parent

    def commit(self) -> None:
        """提交当前数据库事务；失败时通过 QMessageBox 提示用户（TD-M11）。"""
        if self._commit_callback is None:
            return
        try:
            self._commit_callback()
        except Exception:  # noqa: BLE001 - UI 边界需捕获所有异常
            logger.exception("数据库提交失败")
            QMessageBox.critical(
                self._parent,
                ui.DB_COMMIT_FAILED_TITLE,
                ui.DB_COMMIT_FAILED_MESSAGE,
            )

    def rollback(self) -> None:
        """回滚当前数据库事务（释放 SQLite 写锁，避免 database is locked）。"""
        if self._rollback_callback is None:
            return
        try:
            self._rollback_callback()
        except Exception:  # noqa: BLE001 - UI 边界需捕获所有异常
            logger.exception("数据库回滚失败")

    def handle_service_error(self, e: Exception, title: str, *, rollback: bool = True) -> None:
        """统一处理 Service 调用异常（H7 修复 + TD-M11）。

        将异常分类转换为用户可读的 QMessageBox 提示，技术细节通过 logger 记录。
        ``rollback=True``（默认）时先回滚数据库事务（未注入 UoW 的 Service）；
        D3 决策下已注入 UoW 的 Service 内部已管理事务，调用方应传 ``rollback=False``。

        Args:
            e: Service 抛出的异常。
            title: QMessageBox 标题（通常为 ui_constants 中的 *_FAILED 常量）。
            rollback: 是否先调用 rollback()。
        """
        if rollback:
            self.rollback()
        if isinstance(e, ConflictError):
            QMessageBox.information(self._parent, title, f"目标已存在：\n{e}")
        elif isinstance(e, FileOperationError):
            QMessageBox.information(self._parent, title, f"文件操作失败：\n{e}")
        elif isinstance(e, ApplicationError):
            QMessageBox.information(self._parent, title, str(e))
        else:
            logger.exception(title)
            QMessageBox.critical(self._parent, title, "操作失败，请查看日志。")
