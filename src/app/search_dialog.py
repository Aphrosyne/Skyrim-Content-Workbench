"""搜索结果对话框（Stage 5 Task 7）。

spec §8：搜索范围为内容单元标题 + 标签名 + 备注。

UI（Q3=B 非模态对话框）：
- 顶部标题：显示查询词 + 结果数量
- 中间：QTableWidget 显示结果列表（标题 / 路径 / 匹配字段 / 标签）
- 空结果：显示「未找到匹配的内容单元」
- 双击行 → 触发 jump_callback（Q4=B 跳转后保持对话框打开）

交互：
- Q4=B：跳转到所在目录 + 保持对话框打开 + 选中条目
- UX 重构 Phase 1 Task 1：移除模式分支，搜索跳转始终允许
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from domain.models import SearchResult

logger = logging.getLogger(__name__)

# 表格列索引
_COL_TITLE = 0
_COL_PATH = 1
_COL_MATCHED_FIELD = 2
_COL_TAGS = 3
_COL_COUNT = 4

# matched_field 中文映射
_FIELD_LABELS = {
    "title": ui.SEARCH_MATCHED_FIELD_TITLE,
    "tag": ui.SEARCH_MATCHED_FIELD_TAG,
    "notes": ui.SEARCH_MATCHED_FIELD_NOTES,
}


class SearchDialog(QDialog):
    """搜索结果对话框（非模态）。

    通过构造注入查询词、结果列表和 jump 回调。
    双击结果行触发 jump_callback(unit_id)，对话框保持打开（Q4=B）。
    """

    def __init__(
        self,
        query: str,
        results: list[SearchResult],
        jump_callback: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """初始化对话框。

        Args:
            query: 搜索关键词（用于标题显示）。
            results: 搜索结果列表。
            jump_callback: 跳转回调，签名 (unit_id: str) -> None。
                双击结果行时调用。None 时仅模拟流程（测试用）。
            parent: 父窗口。
        """
        super().__init__(parent)
        # Q3=B 非模态：setModal(False)，调用方用 show() 而非 exec()
        self.setModal(False)
        self._query = query
        self._results: list[SearchResult] = list(results)
        self._jump_callback = jump_callback

        self.setWindowTitle(ui.SEARCH_DIALOG_TITLE)
        self.resize(820, 480)

        self._setup_ui()
        self._load_results()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 顶部标题
        self._title_label = QLabel(
            ui.SEARCH_DIALOG_TITLE_WITH_QUERY.format(query=self._query, count=len(self._results))
        )
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._title_label)

        # 空状态提示
        self._empty_label = QLabel(ui.SEARCH_DIALOG_EMPTY)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #999; padding: 40px;")
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)

        # 结果表格
        self._table = QTableWidget(0, _COL_COUNT, self)
        self._table.setHorizontalHeaderLabels(
            [
                ui.SEARCH_COL_TITLE,
                ui.SEARCH_COL_PATH,
                ui.SEARCH_COL_MATCHED_FIELD,
                ui.SEARCH_COL_TAGS,
            ]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_PATH, QHeaderView.ResizeMode.Stretch
        )
        self._table.setToolTip(ui.SEARCH_JUMP_TOOLTIP)
        # 双击跳转
        self._table.doubleClicked.connect(self._on_double_clicked)
        layout.addWidget(self._table, 1)

        # 关闭按钮
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._close_button = QPushButton("关闭")
        self._close_button.setAutoDefault(False)
        self._close_button.clicked.connect(self.accept)
        button_row.addWidget(self._close_button)
        layout.addLayout(button_row)

    def _load_results(self) -> None:
        """加载结果到表格。"""
        if not self._results:
            self._empty_label.setVisible(True)
            self._table.setVisible(False)
            return

        self._table.setRowCount(len(self._results))
        for row, result in enumerate(self._results):
            # 标题（None 回退到 path）
            title_text = result.title or Path(result.path).name or result.path
            title_item = QTableWidgetItem(title_text)
            title_item.setToolTip(result.title or result.path)
            title_item.setData(Qt.UserRole, result.unit_id)
            self._table.setItem(row, _COL_TITLE, title_item)

            # 路径
            path_item = QTableWidgetItem(result.path)
            path_item.setToolTip(result.path)
            self._table.setItem(row, _COL_PATH, path_item)

            # 匹配字段（中文映射）
            field_label = _FIELD_LABELS.get(result.matched_field, result.matched_field)
            field_item = QTableWidgetItem(field_label)
            self._table.setItem(row, _COL_MATCHED_FIELD, field_item)

            # 标签（逗号分隔）
            tags_text = "、".join(result.tags) if result.tags else ""
            tags_item = QTableWidgetItem(tags_text)
            tags_item.setToolTip(tags_text)
            self._table.setItem(row, _COL_TAGS, tags_item)

    def _on_double_clicked(self, index) -> None:
        """双击结果行 → 触发跳转回调。

        Q4=B：跳转后保持对话框打开。
        回调由 MainWindow 实现，负责导航到所在目录 + 选中条目。
        """
        row = index.row()
        item = self._table.item(row, _COL_TITLE)
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not isinstance(data, str):
            return
        unit_id = data
        if self._jump_callback is not None:
            try:
                self._jump_callback(unit_id)
            except Exception:  # noqa: BLE001 - 跳转失败不应关闭对话框
                logger.exception("跳转失败：unit_id=%s", unit_id)

    # --- 公共接口（供测试与调用方） ---

    def update_results(self, query: str, results: list[SearchResult]) -> None:
        """更新对话框内容（复用对话框实例时调用）。

        Args:
            query: 新的搜索关键词。
            results: 新的搜索结果列表。
        """
        self._query = query
        self._results = list(results)
        # 更新标题
        self._title_label.setText(
            ui.SEARCH_DIALOG_TITLE_WITH_QUERY.format(query=query, count=len(results))
        )
        # 清空并重新加载表格
        self._table.setRowCount(0)
        if not self._results:
            self._empty_label.setVisible(True)
            self._table.setVisible(False)
        else:
            self._empty_label.setVisible(False)
            self._table.setVisible(True)
            self._load_results()

    def result_count(self) -> int:
        """返回结果数量（供测试）。"""
        return len(self._results)

    def row_count(self) -> int:
        """返回表格行数（供测试）。"""
        return self._table.rowCount()

    def is_empty_label_visible(self) -> bool:
        """返回空状态标签是否可见（供测试）。"""
        return self._empty_label.isVisibleTo(self)

    def title_text(self) -> str:
        """返回顶部标题文本（供测试）。"""
        return self._title_label.text()

    def row_unit_id(self, row: int) -> str | None:
        """返回指定行的 unit_id（供测试）。"""
        item = self._table.item(row, _COL_TITLE)
        if item is None:
            return None
        data = item.data(Qt.UserRole)
        return data if isinstance(data, str) else None

    def row_matched_field_label(self, row: int) -> str:
        """返回指定行的匹配字段中文标签（供测试）。"""
        item = self._table.item(row, _COL_MATCHED_FIELD)
        return item.text() if item is not None else ""

    def row_tags_text(self, row: int) -> str:
        """返回指定行的标签文本（供测试）。"""
        item = self._table.item(row, _COL_TAGS)
        return item.text() if item is not None else ""

    def select_row(self, row: int) -> None:
        """程序化选中指定行（供测试）。"""
        sm = self._table.selectionModel()
        if sm is None:
            return
        sm.clearSelection()
        idx = self._table.model().index(row, 0)
        sm.select(idx, sm.SelectionFlag.Select | sm.SelectionFlag.Rows)

    def double_click_row(self, row: int) -> None:
        """程序化触发双击事件（供测试）。"""
        idx = self._table.model().index(row, 0)
        self._on_double_clicked(idx)

    def click_close_button(self) -> None:
        """程序化触发「关闭」按钮（供测试）。"""
        self.accept()
