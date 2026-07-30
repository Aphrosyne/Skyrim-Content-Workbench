"""操作历史对话框（Stage 5 Task 6）。

spec §7.7：顶部工具栏「操作历史」按钮 → 弹出对话框。

UI：
- QTableWidget 展示历史记录（时间 / 操作 / 源 → 目标 / 状态）
- can_undo=False 的行整行灰色，撤销按钮禁用
- 已撤销的行（undone_at 非空）显示「已撤销」标记，撤销按钮禁用
- 底部按钮：刷新 / 撤销选中 / 关闭

数据流：
- MainWindow 构造 UndoService → 打开 OperationHistoryDialog
- 对话框调用 undo_service.list_recent(limit=100) 加载历史
- 用户选中行 + 点击「撤销选中」→ 二次确认对话框
- 确认后调用 undo_service.undo(history) → 刷新列表
- 撤销成功后通过 callback 通知 MainWindow 刷新中栏/目录树

事务边界：
- 对话框调用 undo_service.undo 完成所有写入（反向文件操作 + 同步 + undo 记录 + mark_undone）。
- 对话框不自提交，由 MainWindow 在 dialog.exec() 返回后 commit。
- 失败时由 MainWindow rollback。

约束：
- Q7=A：撤销需要二次确认弹窗
- Q3=A：已撤销操作在列表中显示「已撤销」标记，不可重复撤销
- Q6=A：默认加载最近 100 条
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from application.errors import (
    UndoAlreadyUndoneError,
    UndoError,
    UndoNotAllowedError,
    UndoSafetyError,
)
from application.undo_service import UndoService
from domain.models import OperationHistory

logger = logging.getLogger(__name__)


def _format_history_description(history: OperationHistory) -> str:
    """格式化历史记录为用户可读描述。"""
    op = history.operation_type
    if op == "new_folder":
        return ui.HISTORY_DESC_NEW_FOLDER.format(target=history.target_path or "")
    if op == "rename":
        return ui.HISTORY_DESC_RENAME.format(
            source=history.source_path, target=history.target_path or ""
        )
    if op == "move":
        return ui.HISTORY_DESC_MOVE.format(
            source=history.source_path, target=history.target_path or ""
        )
    if op == "delete":
        return ui.HISTORY_DESC_DELETE.format(source=history.source_path)
    if op == "undo":
        return ui.HISTORY_DESC_UNDO.format(source=history.source_path)
    return ui.HISTORY_DESC_UNKNOWN.format(op=op)


def _format_status(history: OperationHistory) -> str:
    """格式化状态文本。"""
    if history.undone_at is not None:
        return ui.HISTORY_STATUS_UNDONE
    if not history.can_undo:
        return ui.HISTORY_STATUS_CANNOT_UNDO
    return ui.HISTORY_STATUS_CAN_UNDO


class OperationHistoryDialog(QDialog):
    """操作历史对话框。

    使用方式：
        dialog = OperationHistoryDialog(undo_service, parent=window)
        dialog.set_on_undone_callback(lambda: window._refresh_after_undo())
        if dialog.exec() == QDialog.Accepted:
            # MainWindow 在此 commit
            ...
    """

    def __init__(
        self,
        undo_service: UndoService,
        parent: QWidget | None = None,
        limit: int = 100,
    ) -> None:
        super().__init__(parent)
        self._undo_service = undo_service
        self._limit = limit
        self._on_undone_callback: Callable[[], None] | None = None

        self.setWindowTitle(ui.OPERATION_HISTORY_DIALOG_TITLE)
        self.resize(800, 500)

        self._setup_ui()
        self._load_history()

    def set_on_undone_callback(self, callback: Callable[[], None]) -> None:
        """设置撤销成功后的回调（用于刷新 MainWindow 的中栏/目录树）。"""
        self._on_undone_callback = callback

    # === UI 构建 ===

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # 历史记录表格
        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(["时间", "操作", "描述", "状态"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        # 列宽
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._table)

        # 底部按钮
        btn_layout = QHBoxLayout()

        self._refresh_btn = QPushButton(ui.OPERATION_HISTORY_REFRESH, self)
        self._refresh_btn.clicked.connect(self._on_refresh)
        btn_layout.addWidget(self._refresh_btn)

        btn_layout.addStretch()

        self._undo_btn = QPushButton(ui.OPERATION_HISTORY_UNDO, self)
        self._undo_btn.clicked.connect(self._on_undo)
        btn_layout.addWidget(self._undo_btn)

        self._close_btn = QPushButton(ui.OPERATION_HISTORY_CLOSE, self)
        self._close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self._close_btn)

        layout.addLayout(btn_layout)

    # === 数据加载 ===

    def _load_history(self) -> None:
        """从 UndoService 加载最近的历史记录。"""
        try:
            histories = self._undo_service.list_recent(limit=self._limit)
        except Exception as e:  # noqa: BLE001
            logger.exception("加载操作历史失败")
            QMessageBox.critical(
                self,
                ui.OPERATION_HISTORY_DIALOG_TITLE,
                ui.MENU_OPERATION_FAILED.format(error=str(e)),
            )
            return

        self._table.setRowCount(0)
        for history in histories:
            self._add_history_row(history)

    def _add_history_row(self, history: OperationHistory) -> None:
        """添加一行历史记录。"""
        row = self._table.rowCount()
        self._table.insertRow(row)

        # 时间
        time_item = QTableWidgetItem(history.created_at)
        time_item.setFlags(time_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, 0, time_item)

        # 操作
        op_item = QTableWidgetItem(history.operation_type)
        op_item.setFlags(op_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, 1, op_item)

        # 描述
        desc_item = QTableWidgetItem(_format_history_description(history))
        desc_item.setFlags(desc_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, 2, desc_item)

        # 状态
        status_item = QTableWidgetItem(_format_status(history))
        status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, 3, status_item)

        # 不可撤销 / 已撤销的行整行灰色
        if history.undone_at is not None or not history.can_undo:
            for col in range(4):
                item = self._table.item(row, col)
                if item is not None:
                    item.setForeground(Qt.GlobalColor.gray)

        # 存储 OperationHistory 引用（UserRole）
        time_item.setData(Qt.ItemDataRole.UserRole, history)

    # === 事件处理 ===

    def _on_refresh(self) -> None:
        """刷新历史记录列表。"""
        self._load_history()

    def _on_undo(self) -> None:
        """撤销选中的历史记录。"""
        history = self._get_selected_history()
        if history is None:
            return

        # Q7=A：二次确认弹窗
        desc = _format_history_description(history)
        reply = QMessageBox.question(
            self,
            ui.OPERATION_HISTORY_UNDO_CONFIRM_TITLE,
            ui.OPERATION_HISTORY_UNDO_CONFIRM_TEXT.format(desc=desc),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # 执行撤销
        try:
            self._undo_service.undo(history)
        except UndoNotAllowedError as e:
            # delete / undo / can_undo=False
            msg = str(e)
            if history.operation_type == "delete":
                msg = ui.UNDO_DELETE_NOT_ALLOWED
            QMessageBox.information(self, ui.OPERATION_HISTORY_UNDO_CONFIRM_TITLE, msg)
            return
        except UndoAlreadyUndoneError:
            QMessageBox.information(
                self,
                ui.OPERATION_HISTORY_UNDO_CONFIRM_TITLE,
                ui.UNDO_ALREADY_UNDONE,
            )
            return
        except UndoSafetyError as e:
            QMessageBox.warning(
                self,
                ui.OPERATION_HISTORY_UNDO_CONFIRM_TITLE,
                ui.UNDO_SAFETY_FAILED.format(reason=e.reason),
            )
            return
        except UndoError as e:
            QMessageBox.critical(
                self,
                ui.OPERATION_HISTORY_UNDO_CONFIRM_TITLE,
                ui.UNDO_FAILED.format(error=str(e)),
            )
            return
        except Exception as e:  # noqa: BLE001
            logger.exception("撤销操作失败")
            QMessageBox.critical(
                self,
                ui.OPERATION_HISTORY_UNDO_CONFIRM_TITLE,
                ui.UNDO_FAILED.format(error=str(e)),
            )
            return

        # 撤销成功：刷新列表 + 通知 MainWindow
        self._load_history()
        if self._on_undone_callback is not None:
            self._on_undone_callback()
        QMessageBox.information(
            self,
            ui.OPERATION_HISTORY_UNDO_CONFIRM_TITLE,
            ui.UNDO_SUCCESS.format(desc=desc),
        )

    # === 工具方法 ===

    def _get_selected_history(self) -> OperationHistory | None:
        """获取当前选中行的 OperationHistory，未选中返回 None。"""
        current_row = self._table.currentRow()
        if current_row < 0:
            QMessageBox.information(
                self,
                ui.OPERATION_HISTORY_UNDO_CONFIRM_TITLE,
                "请先选择一条历史记录",
            )
            return None
        item = self._table.item(current_row, 0)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)  # type: ignore[return-value]
