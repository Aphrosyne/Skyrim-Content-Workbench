"""批量打标签对话框（Stage 4 Task 2 + UI合理性12 重构，2026-08-03）。

spec §7.5 / §10.3：文件列表多选内容单元 → 右键 →「批量打标签」→ 弹出对话框。

UI（UI合理性12 重构，参考 UI合理性10 二期规划）：
- 目标数提示 + 添加/移除模式单选
- 已选标签 chip 区（FlowLayout 按钮，「名称 ×」点击移除，按分类色边框）
- 标签输入框 + QCompleter（前缀自动补全）
- 预选标签区：搜索过滤框（输入即过滤）+ 按分类分组（组头可折叠，
  组内标签按钮 FlowLayout，排除已选，按分类色边框）
- 应用 / 取消按钮
- 已删除「（未添加标签）」空提示（UI合理性12）

数据流 / 事务边界 / 约束沿用原实现：不自动创建新标签、同名 chip 不重复、
service 写入后由 MainWindow 在 dialog.exec() 返回后 commit。
"""

from __future__ import annotations

import logging

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from app.flow_layout import FlowLayout
from app.tag_colors import category_color_hex, text_color_hex
from application.errors import ApplicationError, TagNotFoundError
from application.tag_service import TagService
from domain.models import Tag

logger = logging.getLogger(__name__)


class BatchTagDialog(QDialog):
    """批量打标签对话框。"""

    def __init__(
        self,
        tag_service: TagService,
        content_unit_ids: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = tag_service
        self._content_unit_ids = list(content_unit_ids)
        # 操作模式：'add' / 'remove'
        self._mode = "add"
        # 当前选中的标签列表：list[Tag]
        self._selected_tags: list[Tag] = []
        # 应用结果摘要（供 MainWindow 状态栏提示）
        self._result_messages: list[str] = []
        # chip 按钮映射（与 tag_flow 顺序一致）
        self._chip_buttons: list[tuple[Tag, QPushButton]] = []
        # 预选标签按钮（含被搜索过滤隐藏的，供 preset_tag_names 与点击）
        self._preset_buttons: list[QPushButton] = []
        # 预选分组：category_id → 组内 FlowLayout 容器
        self._preset_groups: dict[str, QWidget] = {}
        # 折叠分组集合
        self._preset_collapsed: set[str] = set()
        # 分类色映射（BugFix2；schema v15 起存完整颜色）：category_id → color_hex
        self._category_colors: dict[str, str] = {}
        self._region_bg = self.palette().color(QPalette.ColorRole.Base).name()

        self.setWindowTitle(ui.BATCH_TAG_DIALOG_TITLE)
        self.resize(420, 520)

        self._setup_ui()
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

        # chip 区（FlowLayout 按钮，点击移除；UI合理性12 重构）
        self._tag_frame = QFrame(self)
        self._tag_frame.setObjectName(ui.PANEL_REGION_OBJECT_NAME)
        self._tag_frame.setFrameShape(QFrame.Shape.NoFrame)
        self._tag_frame.setStyleSheet(
            f"QFrame {{ background: {self._region_bg}; "
            f"border: 1px solid {self._region_bg}; border-radius: 4px; }}"
        )
        self._tag_frame.setFixedHeight(ui.BATCH_TAG_DIALOG_CHIP_AREA_HEIGHT)
        self._tag_flow = FlowLayout(self._tag_frame)
        self._tag_flow.setContentsMargins(2, 1, 2, 1)
        layout.addWidget(self._tag_frame)

        # 预选标签区（UI合理性12：搜索过滤 + 按分类分组；无独立输入框）
        self._preset_label = QLabel(ui.BATCH_TAG_DIALOG_PRESET_TAGS_LABEL)
        self._preset_label.setStyleSheet(ui.PANEL_SECTION_TITLE_STYLE)
        layout.addWidget(self._preset_label)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText(ui.BATCH_TAG_DIALOG_SEARCH_PLACEHOLDER)
        self._search_edit.setToolTip(ui.BATCH_TAG_DIALOG_SEARCH_TOOLTIP)
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(lambda _text: self._refresh_preset_list())
        layout.addWidget(self._search_edit)

        self._preset_scroll = QScrollArea(self)
        self._preset_scroll.setWidgetResizable(True)
        self._preset_scroll.setObjectName(ui.PANEL_REGION_OBJECT_NAME)
        self._preset_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._preset_scroll.setMinimumHeight(140)
        self._preset_scroll.setMaximumHeight(300)
        self._preset_content = QWidget(self._preset_scroll)
        self._preset_layout = QVBoxLayout(self._preset_content)
        self._preset_layout.setContentsMargins(0, 0, 0, 0)
        self._preset_layout.setSpacing(2)
        self._preset_scroll.setWidget(self._preset_content)
        layout.addWidget(self._preset_scroll, stretch=1)

        self._preset_empty_hint = QLabel(ui.BATCH_TAG_DIALOG_PRESET_TAGS_EMPTY_HINT)
        self._preset_empty_hint.setStyleSheet("color: #999;")
        layout.addWidget(self._preset_empty_hint)

        # 按钮行
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

    # --- 公共接口（保持与旧版兼容，供测试/调用方） ---

    def result_messages(self) -> list[str]:
        return list(self._result_messages)

    def selected_tag_names(self) -> list[str]:
        return [t.name for t in self._selected_tags]

    def current_mode(self) -> str:
        return self._mode

    def is_add_mode(self) -> bool:
        return self._mode == "add"

    def is_remove_mode(self) -> bool:
        return self._mode == "remove"

    def target_count(self) -> int:
        return len(self._content_unit_ids)

    def set_mode(self, mode: str) -> None:
        if mode == "add":
            self._add_radio.setChecked(True)
        elif mode == "remove":
            self._remove_radio.setChecked(True)

    def add_tag_via_input(self, tag_name: str) -> None:
        """程序化按名称添加标签（保留给调用方/测试；UI 侧通过搜索+点击添加）。"""
        self._add_tag_by_name(tag_name)

    def click_tag_chip(self, tag_name: str) -> None:
        for tag, btn in self._chip_buttons:
            if tag.name == tag_name:
                btn.click()
                return

    def preset_tag_names(self) -> list[str]:
        return [b.text() for b in self._preset_buttons]

    def click_preset_tag(self, tag_name: str) -> None:
        for btn in self._preset_buttons:
            if btn.text() == tag_name:
                btn.click()
                return

    def click_ok_button(self) -> None:
        self._on_ok_clicked()

    # --- 分组辅助（测试接口，与元数据面板一致） ---

    def preset_group_names(self) -> list[str]:
        names: list[str] = []
        for i in range(self._preset_layout.count()):
            item = self._preset_layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if isinstance(widget, QPushButton) and widget.text().strip().startswith(("▸", "▾")):
                names.append(widget.text().lstrip("▸▾ ").strip())
        return names

    def click_preset_group(self, category_name: str) -> None:
        for i in range(self._preset_layout.count()):
            item = self._preset_layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if isinstance(widget, QPushButton) and category_name in widget.text():
                widget.click()
                return

    def is_preset_group_collapsed(self, category_id: str) -> bool:
        return category_id in self._preset_collapsed

    def search_edit(self) -> QLineEdit:
        return self._search_edit

    # --- 内部实现 ---

    def _on_mode_changed(self, mode: str, checked: bool) -> None:
        if checked:
            self._mode = mode

    def _add_tag_by_name(self, tag_name: str) -> None:
        name = tag_name.strip()
        if not name:
            return
        for t in self._selected_tags:
            if t.name == name:
                QMessageBox.information(
                    self,
                    ui.BATCH_TAG_DIALOG_TAGS_LABEL,
                    ui.BATCH_TAG_DIALOG_DUPLICATE_TAG.format(name=name),
                )
                return
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
        self._refresh_preset_list()

    def _append_tag_chip(self, tag: Tag) -> None:
        btn = QPushButton(f"{tag.name} ×", self._tag_frame)
        color = self._category_colors.get(tag.category_id)
        btn.setStyleSheet(
            ui.TAG_BUTTON_FILLED_STYLE.format(
                color=category_color_hex(color) if color is not None else "#c0c0c0",
                text=text_color_hex(color) if color is not None else "#1a1a1a",
            )
        )
        btn.setToolTip(ui.BATCH_TAG_DIALOG_CHIP_REMOVE_TOOLTIP)
        btn.clicked.connect(lambda checked=False, t=tag: self._remove_tag_chip(t))
        self._tag_flow.addWidget(btn)
        self._chip_buttons.append((tag, btn))

    def _remove_tag_chip(self, tag: Tag) -> None:
        for i, (t, btn) in enumerate(self._chip_buttons):
            if t.id == tag.id:
                self._tag_flow.takeAt(i)
                btn.deleteLater()
                del self._chip_buttons[i]
                break
        self._selected_tags = [t for t in self._selected_tags if t.id != tag.id]
        self._refresh_preset_list()

    def _on_preset_tag_clicked(self, tag: Tag) -> None:
        for t in self._selected_tags:
            if t.id == tag.id:
                return
        self._append_tag_chip(tag)
        self._selected_tags.append(tag)
        self._refresh_preset_list()

    def _refresh_preset_list(self) -> None:
        """重建预选标签区：搜索过滤 + 按分类分组（组头可折叠，排除已选）。"""
        self._clear_preset_groups()
        self._preset_buttons = []
        query = self._search_edit.text().strip().lower()
        try:
            grouped = self._service.list_categories_with_tags()
        except ApplicationError:
            self._preset_empty_hint.setVisible(True)
            return
        self._category_colors = {category.id: category.color_hex for category, _tags in grouped}
        selected_ids = {t.id for t in self._selected_tags}
        total_shown = 0
        for category, tags in grouped:
            available = [
                t for t in sorted(tags, key=lambda t: t.name.lower()) if t.id not in selected_ids
            ]
            if query:
                available = [t for t in available if query in t.name.lower()]
            if not available:
                continue
            collapsed = category.id in self._preset_collapsed
            header = QPushButton(
                f"{'▸' if collapsed else '▾'} {category.name}", self._preset_content
            )
            header.setCheckable(True)
            header.setChecked(not collapsed)
            header.setFlat(True)
            header.setStyleSheet(
                "QPushButton { text-align: left; font-weight: bold; border: none; }"
            )
            header.toggled.connect(
                lambda checked, cid=category.id: self._toggle_preset_group(cid, checked)
            )
            self._preset_layout.addWidget(header)
            flow = QWidget(self._preset_content)
            flow_layout = FlowLayout(flow)
            for tag in available:
                btn = QPushButton(tag.name, flow)
                btn.setStyleSheet(
                    ui.TAG_BUTTON_FILLED_STYLE.format(
                        color=category_color_hex(category.color_hex),
                        text=text_color_hex(category.color_hex),
                    )
                )
                btn.clicked.connect(lambda checked=False, t=tag: self._on_preset_tag_clicked(t))
                flow_layout.addWidget(btn)
                self._preset_buttons.append(btn)
                total_shown += 1
            flow.setVisible(not collapsed)
            self._preset_layout.addWidget(flow)
            self._preset_groups[category.id] = flow
        self._preset_layout.addStretch(1)
        self._preset_empty_hint.setVisible(total_shown == 0)

    def _toggle_preset_group(self, category_id: str, checked: bool) -> None:
        if checked:
            self._preset_collapsed.discard(category_id)
        else:
            self._preset_collapsed.add(category_id)
        flow = self._preset_groups.get(category_id)
        if flow is not None:
            flow.setVisible(checked)
        btn = self.sender()
        if isinstance(btn, QPushButton) and btn.text():
            name = btn.text().lstrip("▸▾ ").strip()
            btn.setText(f"{'▾' if checked else '▸'} {name}")

    def _clear_preset_groups(self) -> None:
        while self._preset_layout.count() > 0:
            item = self._preset_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self._preset_groups = {}

    def _on_ok_clicked(self) -> None:
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

        if success_count > 0:
            self.accept()
        else:
            self.reject()
