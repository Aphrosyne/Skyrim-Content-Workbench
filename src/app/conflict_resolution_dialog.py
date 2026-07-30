"""冲突解决对话框（Stage 5 Task 3b，Q3=C 通用冲突处理）。

在粘贴操作遇到同名文件冲突时弹出，让用户对每个冲突选择：
- 覆盖（覆盖已有文件）
- 跳过（不处理该文件）
- 重命名（自动重命名为 file (1).txt 风格）

支持「应用到全部」：将当前决策应用到所有剩余冲突。

UI 结构：
- 顶部提示：「目标目录已存在以下同名文件，请选择处理方式：」
- 中间 QTableWidget：每行一个冲突，列 = [源文件名, 单选按钮组(覆盖/跳过/重命名), 重命名预览]
- 底部按钮：「应用到全部」复选框 + 确定/取消

数据流：
- MainWindow 调用 ConflictResolutionService.scan_conflicts 得到 conflicts 列表
- 若 has_conflict(conflicts) 为 True，弹出本对话框
- 用户对每个冲突选择决策后点击「确定」
- MainWindow 调用 ConflictResolutionService.resolve(conflicts, decisions) 得到 actions
- 按 actions 执行 copy/move（跳过的项 skipped=True）

约束：
- 跨盘剪切（Q7=B）在调用本对话框前由 MainWindow 检测并整体拒绝
- 本对话框不执行任何文件操作，仅收集用户决策
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from application.conflict_resolution_service import (
    RESOLUTION_OVERWRITE,
    RESOLUTION_RENAME,
    RESOLUTION_SKIP,
    ConflictItem,
)

# 列索引
_COL_SOURCE = 0  # 源文件名
_COL_DECISION = 1  # 决策单选组（覆盖/跳过/重命名）
_COL_PREVIEW = 2  # 重命名预览


class ConflictResolutionDialog(QDialog):
    """冲突解决对话框。

    通过构造注入 conflicts 列表，用户选择决策后通过 decisions() 获取结果。
    """

    def __init__(
        self,
        conflicts: list[ConflictItem],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._conflicts = list(conflicts)
        # 每行的决策值（默认 RESOLUTION_RENAME，安全且不破坏已有文件）
        self._decisions: list[str] = [RESOLUTION_RENAME] * len(self._conflicts)
        # 每行的单选按钮组
        self._button_groups: list[QButtonGroup] = []

        self.setWindowTitle(ui.CONFLICT_DIALOG_TITLE)
        self.resize(640, 400)

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # 顶部提示
        hint = QLabel(ui.CONFLICT_DIALOG_HINT)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # 冲突表格
        self._table = QTableWidget(len(self._conflicts), 3, self)
        self._table.setHorizontalHeaderLabels(
            [
                ui.CONFLICT_DIALOG_COL_SOURCE,
                ui.CONFLICT_DIALOG_COL_DECISION,
                ui.CONFLICT_DIALOG_COL_PREVIEW,
            ]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # 列宽
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(_COL_SOURCE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_DECISION, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_PREVIEW, QHeaderView.ResizeMode.Stretch)

        for row, conflict in enumerate(self._conflicts):
            self._setup_row(row, conflict)

        layout.addWidget(self._table)

        # 底部按钮区
        button_row = QHBoxLayout()
        self._apply_all_btn = QPushButton(ui.CONFLICT_DIALOG_APPLY_ALL)
        self._apply_all_btn.clicked.connect(self._on_apply_all)
        button_row.addWidget(self._apply_all_btn)
        button_row.addStretch()
        ok_btn = QPushButton(ui.CONFLICT_DIALOG_OK)
        cancel_btn = QPushButton(ui.CONFLICT_DIALOG_CANCEL)
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(ok_btn)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)

    def _setup_row(self, row: int, conflict: ConflictItem) -> None:
        """设置表格一行的内容。"""
        # 源文件名
        source_item = QTableWidgetItem(conflict.src.name)
        source_item.setToolTip(str(conflict.src))
        source_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self._table.setItem(row, _COL_SOURCE, source_item)

        # 决策单选组
        decision_widget = QWidget()
        decision_layout = QHBoxLayout(decision_widget)
        decision_layout.setContentsMargins(4, 0, 4, 0)
        group = QButtonGroup(decision_widget)
        group.setExclusive(True)

        radio_overwrite = QRadioButton(ui.CONFLICT_DIALOG_RADIO_OVERWRITE)
        radio_skip = QRadioButton(ui.CONFLICT_DIALOG_RADIO_SKIP)
        radio_rename = QRadioButton(ui.CONFLICT_DIALOG_RADIO_RENAME)
        # 默认选中重命名（最安全的选项）
        radio_rename.setChecked(True)
        self._decisions[row] = RESOLUTION_RENAME

        group.addButton(radio_overwrite)
        group.addButton(radio_skip)
        group.addButton(radio_rename)
        # 用 id 存储决策值
        group.setId(radio_overwrite, 0)
        group.setId(radio_skip, 1)
        group.setId(radio_rename, 2)
        # 信号连接需要用 lambda 捕获 row
        radio_overwrite.toggled.connect(
            lambda checked, r=row: self._on_radio_changed(r, 0, checked)
        )
        radio_skip.toggled.connect(lambda checked, r=row: self._on_radio_changed(r, 1, checked))
        radio_rename.toggled.connect(lambda checked, r=row: self._on_radio_changed(r, 2, checked))

        decision_layout.addWidget(radio_overwrite)
        decision_layout.addWidget(radio_skip)
        decision_layout.addWidget(radio_rename)
        decision_layout.addStretch()
        self._table.setCellWidget(row, _COL_DECISION, decision_widget)
        self._button_groups.append(group)

        # 重命名预览
        preview_item = QTableWidgetItem(str(conflict.suggested_dst.name))
        preview_item.setToolTip(str(conflict.suggested_dst))
        preview_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self._table.setItem(row, _COL_PREVIEW, preview_item)

    def _on_radio_changed(self, row: int, radio_id: int, checked: bool) -> None:
        """单选按钮状态变化时更新决策值。"""
        if not checked:
            return
        decision_map = {
            0: RESOLUTION_OVERWRITE,
            1: RESOLUTION_SKIP,
            2: RESOLUTION_RENAME,
        }
        self._decisions[row] = decision_map[radio_id]

    def _on_apply_all(self) -> None:
        """将当前第一行的决策应用到所有行。"""
        if not self._decisions:
            return
        # 取第一个决策作为模板
        template_decision = self._decisions[0]
        for row in range(1, len(self._conflicts)):
            self._decisions[row] = template_decision
            # 同步单选按钮状态
            radio_id_map = {
                RESOLUTION_OVERWRITE: 0,
                RESOLUTION_SKIP: 1,
                RESOLUTION_RENAME: 2,
            }
            target_id = radio_id_map[template_decision]
            group = self._button_groups[row]
            btn = group.button(target_id)
            if btn is not None:
                btn.setChecked(True)

    def decisions(self) -> list[str]:
        """返回用户选择的决策列表。

        仅在 dialog.exec() 返回 QDialog.Accepted 后调用有意义。
        """
        return list(self._decisions)
