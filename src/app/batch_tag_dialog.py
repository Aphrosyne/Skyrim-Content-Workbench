"""批量打标签对话框（Stage 4 Task 2）。

spec §7.5 / §10.3：文件列表多选内容单元 → 右键 → "批量打标签" → 弹出对话框。

UI：
- 目标数提示："目标内容单元数：N"
- 操作模式单选：「添加标签」/「移除标签」
- 已选标签 chip 列表
- 标签输入框 + QCompleter（前缀自动补全）
- 应用 / 取消按钮

数据流：
- MainWindow 收集选中的 content_unit_ids → 构造 BatchTagDialog
- 用户添加 chip → 输入框回车（chip 来自已存在 Tag）
- 用户选择操作模式
- 点击「应用」→ 调用 TagService.batch_attach_tags 或 batch_detach_tags
- 显示结果摘要："已为 N 个内容单元添加/移除标签「X」"
- MainWindow 在 dialog 关闭后 commit 事务

事务边界：
- Dialog 调用 service 完成所有写入。
- Dialog 不自提交，由 MainWindow 在 dialog.exec() 返回后 commit。
- 失败时由 MainWindow rollback。

约束：
- 不自动创建新标签。输入不存在的标签名 → 弹 QMessageBox.information 提示。
- 同名 chip 不重复添加。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCompleter,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from application.errors import ApplicationError, TagNotFoundError
from application.tag_service import TagService
from domain.models import Tag

logger = logging.getLogger(__name__)

# chip 列表 item 中存储 Tag 实体的角色
_ROLE_TAG = Qt.UserRole


class BatchTagDialog(QDialog):
    """批量打标签对话框。

    通过构造注入 TagService + content_unit_ids 列表。
    用户选择标签 + 操作模式（添加/移除）后点击「应用」执行批量操作。
    """

    def __init__(
        self,
        tag_service: TagService,
        content_unit_ids: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = tag_service
        self._content_unit_ids = list(content_unit_ids)
        # 操作模式："add" / "remove"
        self._mode = "add"
        # 当前选中的标签列表：list[Tag]
        self._selected_tags: list[Tag] = []
        # 应用结果摘要（供 MainWindow 状态栏提示）
        self._result_messages: list[str] = []

        self.setWindowTitle(ui.BATCH_TAG_DIALOG_TITLE)
        self.resize(420, 480)

        self._setup_ui()
        self._refresh_completer()
        self._refresh_preset_list()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # 目标数提示
        self._hint_label = QLabel(
            ui.BATCH_TAG_DIALOG_TARGET_HINT.format(count=len(self._content_unit_ids))
        )
        layout.addWidget(self._hint_label)

        # 操作模式单选
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(ui.BATCH_TAG_DIALOG_TAGS_LABEL + "："))
        self._add_radio = QRadioButton(ui.BATCH_TAG_DIALOG_ADD_BUTTON)
        self._add_radio.setChecked(True)
        self._add_radio.toggled.connect(lambda checked: self._on_mode_changed("add", checked))
        mode_row.addWidget(self._add_radio)
        self._remove_radio = QRadioButton(ui.BATCH_TAG_DIALOG_REMOVE_BUTTON)
        self._remove_radio.toggled.connect(lambda checked: self._on_mode_changed("remove", checked))
        mode_row.addWidget(self._remove_radio)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self._add_radio)
        self._mode_group.addButton(self._remove_radio)

        # chip 列表
        self._tag_list = QListWidget()
        self._tag_list.setFlow(QListWidget.Flow.LeftToRight)
        self._tag_list.setWrapping(True)
        self._tag_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._tag_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._tag_list.setFixedHeight(120)
        self._tag_list.setSpacing(2)
        self._tag_list.itemClicked.connect(self._on_tag_clicked)
        layout.addWidget(self._tag_list)

        # 空状态提示
        self._empty_hint = QLabel(ui.BATCH_TAG_DIALOG_EMPTY_TAGS_HINT)
        self._empty_hint.setStyleSheet("color: #999;")
        layout.addWidget(self._empty_hint)

        # 标签输入框 + QCompleter
        self._tag_input = QLineEdit()
        self._tag_input.setPlaceholderText(ui.BATCH_TAG_DIALOG_TAG_INPUT_PLACEHOLDER)
        self._tag_input.setToolTip(ui.BATCH_TAG_DIALOG_TAG_INPUT_HINT)
        self._tag_input.returnPressed.connect(self._on_tag_input_return)
        layout.addWidget(self._tag_input)

        # 完成器
        self._tag_completer = QCompleter([], self)
        self._tag_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._tag_input.setCompleter(self._tag_completer)

        # 预选标签区域：显示所有已有标签（排除已在 chip 列表的），单击快速添加
        self._preset_label = QLabel(ui.BATCH_TAG_DIALOG_PRESET_TAGS_LABEL)
        layout.addWidget(self._preset_label)
        self._preset_list = QListWidget()
        self._preset_list.setFlow(QListWidget.Flow.LeftToRight)
        self._preset_list.setWrapping(True)
        self._preset_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._preset_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._preset_list.setFixedHeight(100)
        self._preset_list.setSpacing(2)
        self._preset_list.itemClicked.connect(self._on_preset_tag_clicked)
        layout.addWidget(self._preset_list)
        self._preset_empty_hint = QLabel(ui.BATCH_TAG_DIALOG_PRESET_TAGS_EMPTY_HINT)
        self._preset_empty_hint.setStyleSheet("color: #999;")
        layout.addWidget(self._preset_empty_hint)

        layout.addStretch(1)

        # 按钮栏
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._ok_button = QPushButton(ui.BATCH_TAG_DIALOG_OK)
        # 关闭 autoDefault，避免在 QLineEdit 按回车时触发默认按钮导致窗口关闭
        self._ok_button.setAutoDefault(False)
        self._ok_button.clicked.connect(self._on_ok_clicked)
        button_row.addWidget(self._ok_button)
        self._cancel_button = QPushButton(ui.BATCH_TAG_DIALOG_CANCEL)
        self._cancel_button.setAutoDefault(False)
        self._cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self._cancel_button)
        layout.addLayout(button_row)

    # --- 公共接口 ---

    def result_messages(self) -> list[str]:
        """返回本次操作的摘要消息列表（供 MainWindow 状态栏提示）。"""
        return list(self._result_messages)

    def selected_tag_names(self) -> list[str]:
        """返回当前 chip 列表中的标签名（供测试）。"""
        return [t.name for t in self._selected_tags]

    def current_mode(self) -> str:
        """返回当前操作模式："add" / "remove"（供测试）。"""
        return self._mode

    def is_add_mode(self) -> bool:
        return self._mode == "add"

    def is_remove_mode(self) -> bool:
        return self._mode == "remove"

    def target_count(self) -> int:
        """返回目标内容单元数（供测试）。"""
        return len(self._content_unit_ids)

    def set_mode(self, mode: str) -> None:
        """程序化设置操作模式（供测试）。"""
        if mode == "add":
            self._add_radio.setChecked(True)
        elif mode == "remove":
            self._remove_radio.setChecked(True)

    def add_tag_via_input(self, tag_name: str) -> None:
        """程序化设置输入框并触发回车（供测试）。"""
        self._tag_input.setText(tag_name)
        self._on_tag_input_return()

    def click_tag_chip(self, tag_name: str) -> None:
        """程序化点击指定名称的 chip（移除，供测试）。"""
        for i in range(self._tag_list.count()):
            item = self._tag_list.item(i)
            tag = item.data(_ROLE_TAG)
            if tag is not None and tag.name == tag_name:
                self._on_tag_clicked(item)
                return

    def click_preset_tag(self, tag_name: str) -> None:
        """程序化点击指定名称的预选标签（添加到 chip，供测试）。"""
        for i in range(self._preset_list.count()):
            item = self._preset_list.item(i)
            tag = item.data(_ROLE_TAG)
            if tag is not None and tag.name == tag_name:
                self._on_preset_tag_clicked(item)
                return

    def preset_tag_names(self) -> list[str]:
        """返回当前预选列表中的标签名（供测试）。"""
        names: list[str] = []
        for i in range(self._preset_list.count()):
            item = self._preset_list.item(i)
            tag = item.data(_ROLE_TAG)
            if tag is not None:
                names.append(tag.name)
        return names

    def click_ok_button(self) -> None:
        """程序化触发「应用」按钮（供测试）。"""
        self._on_ok_clicked()

    # --- 内部实现 ---

    def _on_mode_changed(self, mode: str, checked: bool) -> None:
        """单选按钮切换。"""
        if checked:
            self._mode = mode

    def _on_tag_input_return(self) -> None:
        """输入框回车：尝试添加标签到 chip 列表。"""
        name = self._tag_input.text().strip()
        if not name:
            return
        # 重复检查
        for t in self._selected_tags:
            if t.name == name:
                QMessageBox.information(
                    self,
                    ui.BATCH_TAG_DIALOG_TAGS_LABEL,
                    ui.BATCH_TAG_DIALOG_DUPLICATE_TAG.format(name=name),
                )
                self._tag_input.clear()
                return
        # 查询精确匹配
        try:
            candidates = self._service.search_tags(name, limit=20)
        except ApplicationError as e:
            QMessageBox.information(self, ui.BATCH_TAG_DIALOG_TITLE, str(e))
            return
        exact: Tag | None = None
        for c in candidates:
            if c.name == name:
                exact = c
                break
        if exact is None:
            QMessageBox.information(
                self,
                ui.BATCH_TAG_DIALOG_TAGS_LABEL,
                ui.BATCH_TAG_DIALOG_TAG_NOT_FOUND.format(name=name),
            )
            return
        self._append_tag_chip(exact)
        self._selected_tags.append(exact)
        self._refresh_empty_hint()
        # chip 添加后从预选列表中移除（避免重复显示）
        self._refresh_preset_list()
        self._tag_input.clear()

    def _on_tag_clicked(self, item: QListWidgetItem) -> None:
        """chip 单击 → 移除。"""
        tag = item.data(_ROLE_TAG)
        if tag is None:
            return
        for i in range(self._tag_list.count()):
            if self._tag_list.item(i) is item:
                self._tag_list.takeItem(i)
                break
        self._selected_tags = [t for t in self._selected_tags if t.id != tag.id]
        self._refresh_empty_hint()
        # chip 移除后该标签重新出现在预选列表中
        self._refresh_preset_list()

    def _on_preset_tag_clicked(self, item: QListWidgetItem) -> None:
        """预选标签单击 → 添加到 chip 列表。

        与输入框回车添加等效，但不重复检查（预选列表本身已排除 chip 中的标签）。
        """
        tag = item.data(_ROLE_TAG)
        if tag is None:
            return
        # 防御性重复检查（理论上不会触发）
        for t in self._selected_tags:
            if t.id == tag.id:
                return
        self._append_tag_chip(tag)
        self._selected_tags.append(tag)
        self._refresh_empty_hint()
        # 添加后从预选列表中移除
        self._refresh_preset_list()

    def _append_tag_chip(self, tag: Tag) -> None:
        item = QListWidgetItem(f"{tag.name} ×")
        item.setData(_ROLE_TAG, tag)
        self._tag_list.addItem(item)

    def _refresh_empty_hint(self) -> None:
        self._empty_hint.setVisible(len(self._selected_tags) == 0)

    def _refresh_preset_list(self) -> None:
        """刷新预选标签列表：显示所有已有标签，排除已在 chip 列表中的。"""
        self._preset_list.clear()
        try:
            all_tags = self._service.list_all_tags()
        except ApplicationError:
            self._preset_empty_hint.setVisible(True)
            return
        selected_ids = {t.id for t in self._selected_tags}
        for tag in all_tags:
            if tag.id in selected_ids:
                continue
            item = QListWidgetItem(tag.name)
            item.setData(_ROLE_TAG, tag)
            item.setToolTip(ui.BATCH_TAG_DIALOG_PRESET_TAGS_LABEL)
            self._preset_list.addItem(item)
        # 无可用标签时显示空提示
        self._preset_empty_hint.setVisible(self._preset_list.count() == 0)

    def _refresh_completer(self) -> None:
        """加载所有标签名到 completer。"""
        try:
            all_tags = self._service.list_all_tags()
        except ApplicationError:
            return
        names = [t.name for t in all_tags]
        existing_model = self._tag_completer.model()
        if isinstance(existing_model, QStringListModel):
            existing_model.setStringList(names)
        else:
            self._tag_completer.setModel(QStringListModel(names, self))

    def _on_ok_clicked(self) -> None:
        """应用 → 批量调用 TagService，记录结果摘要。"""
        if not self._selected_tags:
            QMessageBox.information(
                self,
                ui.BATCH_TAG_DIALOG_TITLE,
                ui.BATCH_TAG_DIALOG_NO_TAGS,
            )
            return

        self._result_messages = []
        success_count = 0
        failure_count = 0

        for tag in self._selected_tags:
            try:
                if self._mode == "add":
                    n = self._service.batch_attach_tags(self._content_unit_ids, tag.id)
                else:
                    n = self._service.batch_detach_tags(self._content_unit_ids, tag.id)
                self._result_messages.append(
                    ui.BATCH_TAG_DIALOG_RESULT_TEXT.format(
                        count=n,
                        action="添加" if self._mode == "add" else "移除",
                        name=tag.name,
                    )
                )
                success_count += 1
            except TagNotFoundError:
                logger.warning("批量打标签：标签不存在：%s", tag.id)
                failure_count += 1
            except ApplicationError as e:
                logger.warning("批量打标签失败：%s", e)
                failure_count += 1

        if failure_count > 0:
            QMessageBox.information(
                self,
                ui.BATCH_TAG_DIALOG_TITLE,
                f"{failure_count} 个标签操作失败，请查看日志。",
            )

        # 至少一个成功 → 接受对话框
        if success_count > 0:
            self.accept()
        else:
            self.reject()
