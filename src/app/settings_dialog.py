"""统一设置对话框（设计合理性1 + 快捷键配置，2026-08-04）。

两个页签：
- 「右键功能」：全部右键功能开关（按类别分组），默认全开；
- 「快捷键」：全部快捷键可编辑（QKeySequenceEdit），清空 = 禁用；
  冲突（同一按键分配给多个功能）允许但高亮警告。
确认后由 MainWindow 保存到 QSettings 并立即生效。
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from app.feature_toggle_config import FEATURE_TOGGLE_IDS, FeatureToggleConfig
from app.shortcut_config import ShortcutConfig, shortcut_definitions


class SettingsDialog(QDialog):
    """统一设置对话框：右键功能开关 + 快捷键自定义。"""

    def __init__(
        self,
        feature_config: FeatureToggleConfig,
        shortcut_config: ShortcutConfig,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(ui.SETTINGS_DIALOG_TITLE)
        self.setModal(True)
        self.resize(600, 540)
        self._initial_features = feature_config
        self._initial_shortcuts = shortcut_config
        self._feature_checkboxes: dict[str, QCheckBox] = {}
        self._shortcut_edits: dict[str, QKeySequenceEdit] = {}

        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_features_tab(), ui.SETTINGS_TAB_FEATURES)
        self._tabs.addTab(self._build_shortcuts_tab(), ui.SETTINGS_TAB_SHORTCUTS)
        layout.addWidget(self._tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # --- 页签构建 ---

    def _build_features_tab(self) -> QWidget:
        widget = QWidget(self)
        root = QVBoxLayout(widget)
        root.addWidget(QLabel(ui.SETTINGS_FEATURES_HINT))

        reset_row = QHBoxLayout()
        reset_row.addStretch(1)
        reset_button = QPushButton(ui.SETTINGS_FEATURES_RESET)
        reset_button.clicked.connect(self._reset_features)
        reset_row.addWidget(reset_button)
        root.addLayout(reset_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        col = QVBoxLayout(content)
        col.setSpacing(6)
        current_group: str | None = None
        for feature_id in FEATURE_TOGGLE_IDS:
            group_id = ui.FEATURE_TOGGLE_GROUP_MAP[feature_id]
            if group_id != current_group:
                if current_group is not None:
                    col.addSpacing(10)
                header = QLabel(ui.FEATURE_TOGGLE_GROUPS[group_id])
                header.setStyleSheet("font-weight: bold;")
                col.addWidget(header)
                current_group = group_id
            checkbox = QCheckBox(ui.FEATURE_TOGGLE_LABELS[feature_id])
            checkbox.setChecked(self._initial_features.is_enabled(feature_id))
            self._feature_checkboxes[feature_id] = checkbox
            col.addWidget(checkbox)
        col.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)
        return widget

    def _build_shortcuts_tab(self) -> QWidget:
        widget = QWidget(self)
        root = QVBoxLayout(widget)
        root.addWidget(QLabel(ui.SETTINGS_SHORTCUTS_HINT))

        reset_row = QHBoxLayout()
        reset_row.addStretch(1)
        reset_button = QPushButton(ui.SETTINGS_SHORTCUTS_RESET)
        reset_button.clicked.connect(self._reset_shortcuts)
        reset_row.addWidget(reset_button)
        root.addLayout(reset_row)

        definitions = shortcut_definitions()
        table = QTableWidget(len(definitions), 3)
        table.setHorizontalHeaderLabels(
            [
                ui.SETTINGS_SHORTCUTS_COL_FEATURE,
                ui.SETTINGS_SHORTCUTS_COL_KEY,
                ui.SETTINGS_SHORTCUTS_COL_SCOPE,
            ]
        )
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for row, definition in enumerate(definitions):
            table.setItem(row, 0, QTableWidgetItem(definition.label))
            table.setItem(row, 2, QTableWidgetItem(definition.scope))
            edit = QKeySequenceEdit(
                QKeySequence(self._initial_shortcuts.key_for(definition.shortcut_id)),
                table,
            )
            edit.keySequenceChanged.connect(self._update_conflicts)
            table.setCellWidget(row, 1, edit)
            self._shortcut_edits[definition.shortcut_id] = edit
        root.addWidget(table, stretch=1)
        return widget

    # --- 冲突检测 ---

    def _update_conflicts(self) -> None:
        """对重复按键高亮警告（允许冲突，仅提示）。"""
        key_map: dict[str, list[str]] = {}
        for shortcut_id, edit in self._shortcut_edits.items():
            sequence = edit.keySequence().toString()
            if sequence:
                key_map.setdefault(sequence, []).append(shortcut_id)
        for shortcut_id, edit in self._shortcut_edits.items():
            sequence = edit.keySequence().toString()
            conflicts = key_map.get(sequence, []) if sequence else []
            if len(conflicts) > 1:
                others = [ui.SHORTCUT_LABELS[sid] for sid in conflicts if sid != shortcut_id]
                edit.setStyleSheet(
                    f"QKeySequenceEdit {{ background-color: {ui.SETTINGS_SHORTCUTS_CONFLICT_BG}; }}"
                )
                edit.setToolTip(
                    ui.SETTINGS_SHORTCUTS_CONFLICT_TOOLTIP.format(others="、".join(others))
                )
            else:
                edit.setStyleSheet("")
                edit.setToolTip("")

    # --- 重置 ---

    def _reset_features(self) -> None:
        for checkbox in self._feature_checkboxes.values():
            checkbox.setChecked(True)

    def _reset_shortcuts(self) -> None:
        for shortcut_id, edit in self._shortcut_edits.items():
            edit.setKeySequence(QKeySequence(ui.SHORTCUT_DEFAULT_KEYS[shortcut_id]))
        self._update_conflicts()

    # --- 结果 ---

    def resulting_feature_config(self) -> FeatureToggleConfig:
        """返回当前右键功能开关（应在 accepted 后调用）。"""
        config = FeatureToggleConfig.defaults()
        for feature_id, checkbox in self._feature_checkboxes.items():
            config.toggle(feature_id, checkbox.isChecked())
        return config

    def resulting_shortcut_config(self) -> ShortcutConfig:
        """返回当前快捷键配置（应在 accepted 后调用）。"""
        config = ShortcutConfig.defaults()
        for shortcut_id, edit in self._shortcut_edits.items():
            config.set_key(shortcut_id, edit.keySequence().toString())
        return config

    # --- 测试辅助 ---

    def feature_checkbox(self, feature_id: str) -> QCheckBox:
        return self._feature_checkboxes[feature_id]

    def shortcut_edit(self, shortcut_id: str) -> QKeySequenceEdit:
        return self._shortcut_edits[shortcut_id]
