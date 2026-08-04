"""操作历史对话框（Stage 5 Task 6 + UX 重构 Phase 2 Task 5）。

spec §7.7：顶部工具栏「操作历史」按钮 → 弹出对话框。

UI（UX 重构 Phase 2 Task 5 优化）：
- QTableWidget 展示历史记录（时间 / 操作 / 状态），不再显示描述列
- 鼠标悬浮在操作列上显示详细描述（含简化路径）— open-questions §9
- 已撤销的记录不显示（open-questions §3）
- 删除操作保留显示但灰色不可撤销（Q4=B：保留可追溯性）
- can_undo=False 的行整行灰色，撤销按钮禁用
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
- Q9=A：清理 undo 遗留分支（D4 决策已消除 undo 记录）
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QSettings, Qt
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
from app.app_paths import get_app_settings
from app.path_display import make_display_path_from_service
from app.splitter_state import SplitterStateHelper
from application.errors import (
    UndoAlreadyUndoneError,
    UndoError,
    UndoNotAllowedError,
    UndoSafetyError,
)
from application.undo_service import UndoService
from domain.models import OperationHistory

logger = logging.getLogger(__name__)


def _format_history_description(history: OperationHistory, managed_root_service) -> str:
    """格式化历史记录为用户可读描述（含简化路径）。

    UX 重构 Phase 2 Task 5：路径使用 make_display_path 简化显示（open-questions §9）。
    Q9=A：移除 "undo" 分支（D4 决策已消除 undo 记录，不会再命中）。
    """
    op = history.operation_type
    # 路径简化（managed_root_service 可能为 None，降级显示原路径）
    svc = managed_root_service
    target = (
        make_display_path_from_service(history.target_path, svc)
        if history.target_path and svc is not None
        else (history.target_path or "")
    )
    source = (
        make_display_path_from_service(history.source_path, svc)
        if history.source_path and svc is not None
        else (history.source_path or "")
    )
    if op == "new_folder":
        return ui.HISTORY_DESC_NEW_FOLDER.format(target=target)
    if op == "rename":
        return ui.HISTORY_DESC_RENAME.format(source=source, target=target)
    if op == "move":
        return ui.HISTORY_DESC_MOVE.format(source=source, target=target)
    if op == "delete":
        return ui.HISTORY_DESC_DELETE.format(source=source)
    if op == "copy":
        return ui.HISTORY_DESC_COPY.format(source=source, target=target)
    if op == "strip":
        # 操作便捷性1（2026-08-04）：剥离（提取内容）
        return ui.HISTORY_DESC_STRIP.format(source=source, target=target)
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
        dialog.set_managed_root_service(managed_root_service)  # 用于路径简化
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
        settings: QSettings | None = None,
    ) -> None:
        super().__init__(parent)
        self._undo_service = undo_service
        self._limit = limit
        self._on_undone_callback: Callable[[], None] | None = None
        # UX 重构 Phase 2 Task 5：受管理根目录服务，用于路径简化显示
        self._managed_root_service = None
        # UI合理性2：列宽持久化（测试可注入 ini 隔离实例）
        self._settings = settings or get_app_settings()
        self._splitter_state = SplitterStateHelper(self._settings)

        self.setWindowTitle(ui.OPERATION_HISTORY_DIALOG_TITLE)
        self.resize(700, 500)

        self._setup_ui()
        self._load_history()

    def set_on_undone_callback(self, callback: Callable[[], None]) -> None:
        """设置撤销成功后的回调（用于刷新 MainWindow 的中栏/目录树）。"""
        self._on_undone_callback = callback

    def set_managed_root_service(self, managed_root_service) -> None:
        """设置受管理根目录服务，用于路径简化显示（open-questions §9）。"""
        self._managed_root_service = managed_root_service

    # === UI 构建 ===

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # 历史记录表格（UX 重构 Phase 2 Task 5：3 列，移除描述列，改用 Tooltip）
        self._table = QTableWidget(0, 3, self)
        self._table.setHorizontalHeaderLabels(["时间", "操作", "状态"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        # 列宽（UI合理性2）：Interactive 可拖动 + QSettings 持久化，
        # 默认宽度见 LAYOUT_OPERATION_HISTORY_COLUMN_WIDTHS
        header = self._table.horizontalHeader()
        self._splitter_state.restore_header(
            header,
            ui.QSETTINGS_KEY_HEADER_OPERATION_HISTORY,
            ui.LAYOUT_OPERATION_HISTORY_COLUMN_WIDTHS,
        )
        # 验收反馈（2026-08-03）：列宽固定后右侧会留白被误认为"空列"，
        # 末列（状态）显式 Stretch：自动吸收剩余宽度且不可拖动（避免右边缘被拉长）；
        # 时间/操作列保持 Interactive 可拖动
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.sectionResized.connect(
            lambda *_: self._splitter_state.save_header(
                header, ui.QSETTINGS_KEY_HEADER_OPERATION_HISTORY
            )
        )
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
        """从 UndoService 加载最近的历史记录。

        UX 重构 Phase 2 Task 5：
        - 已撤销的记录不显示（open-questions §3）
        - 删除操作保留显示但灰色不可撤销（Q4=B：保留可追溯性）
        """
        try:
            histories = self._undo_service.list_recent(limit=self._limit)
        except Exception as e:  # noqa: BLE001
            logger.exception("加载操作历史失败")
            QMessageBox.information(
                self,
                ui.OPERATION_HISTORY_DIALOG_TITLE,
                ui.MENU_OPERATION_FAILED.format(error=str(e)),
            )
            return

        self._table.setRowCount(0)
        for history in histories:
            # 过滤已撤销的记录（open-questions §3）
            if history.undone_at is not None:
                continue
            self._add_history_row(history)

    def _add_history_row(self, history: OperationHistory) -> None:
        """添加一行历史记录。"""
        row = self._table.rowCount()
        self._table.insertRow(row)

        # 时间
        time_item = QTableWidgetItem(history.created_at)
        time_item.setFlags(time_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, 0, time_item)

        # 操作（Tooltip 显示详细描述，含简化路径）
        # 操作列显示中文名，非原始英文
        op_label = ui.HISTORY_OP_LABELS.get(history.operation_type, history.operation_type)
        op_item = QTableWidgetItem(op_label)
        op_item.setFlags(op_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        desc = _format_history_description(history, self._managed_root_service)
        op_item.setToolTip(desc)
        # 时间项也设置 Tooltip，方便用户在任意列悬浮查看
        time_item.setToolTip(desc)
        self._table.setItem(row, 1, op_item)

        # 状态
        status_item = QTableWidgetItem(_format_status(history))
        status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        status_item.setToolTip(desc)
        self._table.setItem(row, 2, status_item)

        # 不可撤销的行整行灰色（Q4=B：删除操作保留显示但灰色）
        if not history.can_undo:
            for col in range(3):
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
        desc = _format_history_description(history, self._managed_root_service)
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
            # delete / can_undo=False
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
            QMessageBox.information(
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
