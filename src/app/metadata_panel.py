"""元数据编辑面板 UI（Stage 4 Task 2）。

spec §7.2 / §10.3：右栏元数据面板，显示与编辑内容单元元数据。

字段：
- 标题（中文别名）→ QLineEdit
- 路径、类型、创建时间 → 只读 QLabel
- 标签 → chip 列表（QListWidget wrap）+ 独立输入框（QLineEdit + QCompleter）
- 来源 URL → QLineEdit
- 备注 → QTextEdit（多行）
- 封面预览 + 设置封面 / 清除封面按钮
- [保存] 按钮

交互（用户确认设计决策 1/5/6）：
- 显式「保存」按钮：用户点击后才写入数据库。
- chip + 独立输入框：QLineEdit 输入回车 → 添加到 chip 列表；chip 单击 → 移除。
- 标签前缀匹配自动补全：QCompleter + TagService.search_tags。
- 标签预选区域：标签输入框下方显示所有已有标签（排除已在 chip 列表的），
  单击预选标签即可快速添加到 chip 列表。
- 2026-07-19 决策修正：整理模式下 MetadataPanel 保留显示（原决策 4/8 被推翻）。

事务边界（与现有 Service 一致）：
- MetadataPanel 调用 ContentService.update_metadata + TagService.attach/detach。
- 保存成功后通过 on_saved(unit) 信号回调 MainWindow 提交事务 + 刷新中栏。

封面选择（决策 2）：
- 通过 on_pick_cover_requested(unit_id) 信号请求 MainWindow 弹 CoverPickerDialog。
- MainWindow 选定后调用 set_cover_path(path) 更新表单（仅 UI 状态，未提交）。
- 保存时把当前 cover_path 一并提交到 ContentService.update_metadata。

标签输入约束：
- 不自动创建新标签。若用户输入的标签名不存在，弹 QMessageBox 提示
  「请先在标签管理中创建」。
- 同名标签（已添加到 chip 列表）忽略重复添加并提示。

异常分层：
- ContentService 抛 InvalidMetadataError / CoverImageNotFoundError →
  MetadataPanel 捕获并弹 QMessageBox 提示。
- TagService 抛 TagNotFoundError / ContentUnitNotFoundError → 同上。
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCompleter,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from application.content_service import ContentService
from application.errors import (
    ApplicationError,
    CoverImageNotFoundError,
    InvalidMetadataError,
)
from application.tag_service import TagService
from domain.models import ContentUnit, Tag

logger = logging.getLogger(__name__)


class _ElidedLabel(QLabel):
    """文本超长时显示省略号（ElideMiddle），不撑大父容器宽度。

    Stage 5 Task 2 验收修复：用于元数据面板的路径/封面值显示。
    与左栏目录树路径省略策略一致：ElideMiddle + ToolTip 显示完整文本。
    QSizePolicy.Ignored 让 label 不参与父容器宽度计算，避免长路径撑大右栏。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setWordWrap(False)
        # Ignored 策略：label 不撑大父容器，宽度由布局分配
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt 命名)
        """设置完整文本，自动 elide 显示并更新 tooltip。"""
        self._full_text = text
        self._update_elided()
        # tooltip 显示完整原文
        self.setToolTip(text)

    def fullText(self) -> str:  # noqa: N802 (Qt 命名)
        """返回完整文本（未经 elide）。"""
        return self._full_text

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """尺寸变化时重新 elide。"""
        super().resizeEvent(event)
        self._update_elided()

    def _update_elided(self) -> None:
        """按当前宽度计算 elide 显示。"""
        if not self._full_text:
            super().setText("")
            return
        fm = QFontMetrics(self.font())
        # 减去内边距，预留 8px 余量
        max_width = max(20, self.width() - 8)
        elided = fm.elidedText(self._full_text, Qt.TextElideMode.ElideMiddle, max_width)
        super().setText(elided)


class _ResizableImageLabel(QWidget):
    """按父容器宽度等比缩放、高度自适应、无反馈循环的图片控件（Task 1b 修正）。

    根本原理（社区验证 + Qt 文档确认）：
    - **绝不在 resizeEvent 里调用 setFixedHeight/setMinimumHeight/setMaximumHeight**
      （那会触发"改尺寸约束→布局重算→resize→再改约束"的正反馈循环，横向图尤其严重）
    - 通过 hasHeightForWidth/heightForWidth 协议让布局系统按宽度计算高度
    - paintEvent 里按当前 size 用 KeepAspectRatio 居中绘制，不改任何约束

    布局交互：
    - 水平 Expanding 撑满右栏宽度
    - 高度由 heightForWidth(width) 决定，不会反向影响宽度，回路断开
    - setMinimumSize(1,1) 允许布局缩小控件，否则 sizeHint 会撑住布局不让缩
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        # 允许收缩到 1x1，否则 sizeHint（pixmap 原尺寸）会撑住布局不让缩小
        self.setMinimumSize(1, 1)
        # 水平 Expanding 撑满右栏宽度，垂直 Preferred（高度按 heightForWidth 计算）
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt 命名)
        """声明高度依赖宽度，让布局调用 heightForWidth 计算高度。"""
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt 命名)
        """按给定宽度计算图片显示高度（限制最大 512）。

        无图时返回占位高度（避免完全塌陷看不到边框）。
        """
        if self._pixmap is None or self._pixmap.isNull() or width <= 0:
            return ui.COVER_PREVIEW_PLACEHOLDER_HEIGHT
        ow = self._pixmap.width()
        oh = self._pixmap.height()
        if ow <= 0:
            return ui.COVER_PREVIEW_PLACEHOLDER_HEIGHT
        h = int(oh * width / ow)
        # 限制最大高度
        if h > ui.COVER_PREVIEW_MAX_HEIGHT:
            h = ui.COVER_PREVIEW_MAX_HEIGHT
        return h

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt 命名)
        """提供合理的首选尺寸（真正的高度由 heightForWidth 决定）。"""
        if self._pixmap is None or self._pixmap.isNull():
            return QSize(ui.COVER_PREVIEW_DEFAULT_WIDTH, ui.COVER_PREVIEW_PLACEHOLDER_HEIGHT)
        return self._pixmap.size()

    def set_original_pixmap(self, pixmap: QPixmap | None) -> None:
        """设置原始 pixmap，触发布局重算高度。"""
        self._pixmap = pixmap
        # pixmap 变化 → sizeHint/heightForWidth 变化 → 通知布局重算
        self.updateGeometry()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """按当前控件尺寸等比缩放并居中绘制 pixmap。"""
        super().paintEvent(event)
        if self._pixmap is None or self._pixmap.isNull():
            return
        # 按当前控件尺寸缩放，保持宽高比
        scaled = self._pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter = QPainter(self)
        # 居中绘制
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)


# chip 列表 item 中存储 Tag 实体的角色
_ROLE_TAG = Qt.UserRole


class MetadataPanel(QWidget):
    """元数据编辑面板。

    通过构造注入 ContentService + TagService。
    使用方式：
        panel = MetadataPanel(content_service, tag_service)
        panel.load_unit(unit)  # 加载并填充表单
        panel.on_saved.connect(handle_save)  # 保存成功信号
    """

    # 保存成功后发射（MainWindow 据此 commit + 刷新中栏）
    on_saved = Signal(object)  # ContentUnit
    # 保存失败后发射（MainWindow 据此 rollback 事务，避免未提交的 metadata 残留）
    on_save_failed = Signal(str)  # 用户可读错误消息
    # 请求打开封面选择对话框
    on_pick_cover_requested = Signal(str)  # unit_id

    def __init__(
        self,
        content_service: ContentService,
        tag_service: TagService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._content_service = content_service
        self._tag_service = tag_service
        self._current_unit: ContentUnit | None = None
        # 当前编辑中（未保存）的 chip 列表：list[Tag]
        self._current_tags: list[Tag] = []
        # 加载时保存的原始标签 ID 集合，用于保存时计算 add / remove diff
        self._original_tag_ids: set[str] = set()

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # 未选中内容单元时的占位提示
        self._hint_label = QLabel(ui.METADATA_PANEL_NO_UNIT_HINT)
        self._hint_label.setStyleSheet("color: #666;")
        self._hint_label.setWordWrap(True)
        layout.addWidget(self._hint_label)

        # === 表单字段 ===

        # 标题
        self._title_label = QLabel(ui.METADATA_TITLE_LABEL)
        layout.addWidget(self._title_label)
        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText(ui.METADATA_PANEL_TITLE_PLACEHOLDER)
        layout.addWidget(self._title_edit)

        # 路径（只读，ElideMiddle 省略显示，不撑大右栏）
        self._path_label = QLabel(ui.METADATA_PATH_LABEL)
        layout.addWidget(self._path_label)
        self._path_value = _ElidedLabel()
        self._path_value.setStyleSheet("color: #555;")
        layout.addWidget(self._path_value)

        # 类型 + 创建时间（一行两列）
        meta_row = QHBoxLayout()
        meta_row.addWidget(QLabel(ui.METADATA_TYPE_LABEL))
        self._type_value = QLabel("")
        self._type_value.setStyleSheet("color: #555;")
        meta_row.addWidget(self._type_value, stretch=1)
        meta_row.addSpacing(12)
        meta_row.addWidget(QLabel(ui.METADATA_CREATED_AT_LABEL))
        self._created_value = QLabel("")
        self._created_value.setStyleSheet("color: #555;")
        meta_row.addWidget(self._created_value, stretch=2)
        layout.addLayout(meta_row)

        # 标签
        self._tags_label = QLabel(ui.METADATA_PANEL_TAGS_LABEL)
        layout.addWidget(self._tags_label)

        # chip 列表：横向 wrap
        self._tag_list = QListWidget()
        self._tag_list.setFlow(QListWidget.Flow.LeftToRight)
        self._tag_list.setWrapping(True)
        self._tag_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._tag_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._tag_list.setFixedHeight(80)
        self._tag_list.setSpacing(2)
        # 单击 → 移除
        self._tag_list.itemClicked.connect(self._on_tag_clicked)
        layout.addWidget(self._tag_list)

        # 空标签提示
        self._tags_empty_hint = QLabel(ui.METADATA_PANEL_EMPTY_TAGS_HINT)
        self._tags_empty_hint.setStyleSheet("color: #999;")
        layout.addWidget(self._tags_empty_hint)

        # 标签输入框 + QCompleter
        self._tag_input = QLineEdit()
        self._tag_input.setPlaceholderText(ui.METADATA_PANEL_TAG_INPUT_PLACEHOLDER)
        self._tag_input.setToolTip(ui.METADATA_PANEL_TAG_INPUT_HINT)
        self._tag_input.returnPressed.connect(self._on_tag_input_return)
        layout.addWidget(self._tag_input)

        # 完成器
        self._tag_completer = QCompleter([], self)
        self._tag_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._tag_input.setCompleter(self._tag_completer)

        # 预选标签区域：显示所有已有标签（排除已在 chip 列表的），单击快速添加
        self._preset_label = QLabel(ui.METADATA_PANEL_PRESET_TAGS_LABEL)
        layout.addWidget(self._preset_label)
        self._preset_list = QListWidget()
        self._preset_list.setFlow(QListWidget.Flow.LeftToRight)
        self._preset_list.setWrapping(True)
        self._preset_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._preset_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._preset_list.setFixedHeight(80)
        self._preset_list.setSpacing(2)
        self._preset_list.itemClicked.connect(self._on_preset_tag_clicked)
        layout.addWidget(self._preset_list)
        self._preset_empty_hint = QLabel(ui.METADATA_PANEL_PRESET_TAGS_EMPTY_HINT)
        self._preset_empty_hint.setStyleSheet("color: #999;")
        layout.addWidget(self._preset_empty_hint)

        # 来源 URL
        self._source_url_label = QLabel(ui.METADATA_SOURCE_URL_LABEL)
        layout.addWidget(self._source_url_label)
        self._source_url_edit = QLineEdit()
        self._source_url_edit.setPlaceholderText(ui.METADATA_PANEL_SOURCE_URL_PLACEHOLDER)
        layout.addWidget(self._source_url_edit)

        # 备注
        self._notes_label = QLabel(ui.METADATA_NOTES_LABEL)
        layout.addWidget(self._notes_label)
        self._notes_edit = QTextEdit()
        self._notes_edit.setPlaceholderText(ui.METADATA_PANEL_NOTES_PLACEHOLDER)
        self._notes_edit.setFixedHeight(80)
        layout.addWidget(self._notes_edit)

        # 封面预览 + 按钮（封面路径 ElideMiddle 省略显示）
        cover_row = QHBoxLayout()
        cover_row.addWidget(QLabel(ui.METADATA_PANEL_COVER_LABEL))
        self._cover_value = _ElidedLabel()
        self._cover_value.setStyleSheet("color: #555;")
        self._cover_value.setText(ui.METADATA_PANEL_COVER_NONE)
        cover_row.addWidget(self._cover_value, stretch=1)
        layout.addLayout(cover_row)

        cover_preview_row = QHBoxLayout()
        self._cover_preview = _ResizableImageLabel()
        # Task 1b 修正：统一加载原图，宽度跟随右栏自适应（Expanding 撑满右栏）
        # 无图时显示边框占位，有图时 paintEvent 绘制
        self._cover_preview.setStyleSheet("border: 1px solid #ccc; background: #fafafa;")
        cover_preview_row.addWidget(self._cover_preview)
        layout.addLayout(cover_preview_row)

        cover_button_row = QHBoxLayout()
        self._pick_cover_button = QPushButton(ui.METADATA_PANEL_PICK_COVER_BUTTON)
        self._pick_cover_button.setToolTip(ui.METADATA_PANEL_PICK_COVER_TOOLTIP)
        self._pick_cover_button.clicked.connect(self._on_pick_cover_clicked)
        cover_button_row.addWidget(self._pick_cover_button)
        self._clear_cover_button = QPushButton(ui.METADATA_PANEL_CLEAR_COVER_BUTTON)
        self._clear_cover_button.clicked.connect(self._on_clear_cover_clicked)
        cover_button_row.addWidget(self._clear_cover_button)
        cover_button_row.addStretch(1)
        layout.addLayout(cover_button_row)

        layout.addStretch(1)

        # 保存按钮（右下）
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self._save_button = QPushButton(ui.METADATA_PANEL_SAVE_BUTTON)
        self._save_button.clicked.connect(self._on_save_clicked)
        save_row.addWidget(self._save_button)
        layout.addLayout(save_row)

        # 初始禁用表单（未加载 unit 时）
        self._set_form_enabled(False)

    # --- 公共接口 ---

    def load_unit(self, unit: ContentUnit | None) -> None:
        """加载内容单元到表单。

        Args:
            unit: 要加载的 ContentUnit；None 表示清空面板（无选中）。
        """
        if unit is None:
            self.clear_panel()
            return

        self._current_unit = unit
        self._hint_label.setVisible(False)

        # 填充字段
        self._title_edit.setText(unit.title or "")
        self._path_value.setText(unit.path)
        self._type_value.setText(unit.content_type)
        self._created_value.setText(unit.created_at)
        self._source_url_edit.setText(unit.source_url or "")
        self._notes_edit.setPlainText(unit.notes or "")

        # 加载封面预览
        self._refresh_cover_preview(unit.cover_path)

        # 加载标签
        self._load_tags_for_unit(unit.id)

        # 刷新自动补全候选
        self._refresh_completer()

        # 刷新预选标签列表（排除已在 chip 列表的）
        self._refresh_preset_list()

        self._set_form_enabled(True)

    def clear_panel(self) -> None:
        """清空面板（无内容单元选中时）。"""
        self._current_unit = None
        self._current_tags = []
        self._original_tag_ids = set()

        self._hint_label.setVisible(True)
        self._title_edit.clear()
        self._path_value.setText("")
        self._type_value.setText("")
        self._created_value.setText("")
        self._source_url_edit.clear()
        self._notes_edit.clear()
        self._tag_list.clear()
        self._tag_input.clear()
        self._tags_empty_hint.setVisible(True)
        self._preset_list.clear()
        self._preset_empty_hint.setVisible(False)
        self._cover_value.setText(ui.METADATA_PANEL_COVER_NONE)
        self._cover_preview.set_original_pixmap(None)  # 清空图片

        self._set_form_enabled(False)

    def current_unit(self) -> ContentUnit | None:
        """返回当前加载的 ContentUnit（供测试）。"""
        return self._current_unit

    def set_cover_path(self, cover_path: str | None) -> None:
        """由 CoverPickerDialog 选定封面后调用，更新表单中的封面字段。

        仅更新 UI 状态；实际写入数据库由「保存」按钮触发。
        """
        if self._current_unit is None:
            return
        # 更新预览（基于 unit.path + cover_path）
        self._refresh_cover_preview(cover_path)

    # --- 测试辅助接口 ---

    def title_text(self) -> str:
        return self._title_edit.text()

    def source_url_text(self) -> str:
        return self._source_url_edit.text()

    def notes_text(self) -> str:
        return self._notes_edit.toPlainText()

    def cover_path_text(self) -> str:
        """返回当前表单中显示的封面相对路径（如已加载）。"""
        if self._current_unit is None:
            return ""
        # cover_path 由 load_unit 或 set_cover_path 设置后通过 _cover_value 显示
        # 使用 fullText() 获取完整文本（避免 elide 后的省略形式）
        if self._cover_value.fullText() == ui.METADATA_PANEL_COVER_NONE:
            return ""
        return self._cover_value.fullText()

    def tag_chips(self) -> list[str]:
        """返回当前 chip 列表中的标签名（供测试）。"""
        return [t.name for t in self._current_tags]

    def preset_tag_names(self) -> list[str]:
        """返回当前预选列表中的标签名（供测试）。"""
        names: list[str] = []
        for i in range(self._preset_list.count()):
            item = self._preset_list.item(i)
            tag = item.data(_ROLE_TAG)
            if tag is not None:
                names.append(tag.name)
        return names

    def click_preset_tag(self, tag_name: str) -> None:
        """程序化点击指定名称的预选标签（添加到 chip，供测试）。"""
        for i in range(self._preset_list.count()):
            item = self._preset_list.item(i)
            tag = item.data(_ROLE_TAG)
            if tag is not None and tag.name == tag_name:
                self._on_preset_tag_clicked(item)
                return

    def is_save_button_enabled(self) -> bool:
        return self._save_button.isEnabled()

    def is_pick_cover_button_enabled(self) -> bool:
        return self._pick_cover_button.isEnabled()

    def is_form_enabled(self) -> bool:
        """返回表单是否处于可编辑状态（已加载 unit 时为 True）。"""
        return self._title_edit.isEnabled()

    def add_tag_via_input(self, tag_name: str) -> None:
        """程序化设置输入框并触发回车（供测试）。"""
        self._tag_input.setText(tag_name)
        self._on_tag_input_return()

    def click_save_button(self) -> None:
        """程序化触发保存按钮点击（供测试）。"""
        self._on_save_clicked()

    def click_pick_cover_button(self) -> None:
        """程序化触发「设置封面」按钮点击（供测试）。"""
        self._on_pick_cover_clicked()

    def click_tag_chip(self, tag_name: str) -> None:
        """程序化点击指定名称的 chip（移除，供测试）。"""
        for i in range(self._tag_list.count()):
            item = self._tag_list.item(i)
            tag = item.data(_ROLE_TAG)
            if tag is not None and tag.name == tag_name:
                self._on_tag_clicked(item)
                return

    # --- 内部实现 ---

    def _set_form_enabled(self, enabled: bool) -> None:
        """启用/禁用表单所有控件。"""
        for w in (
            self._title_edit,
            self._source_url_edit,
            self._notes_edit,
            self._tag_input,
            self._tag_list,
            self._preset_list,
            self._pick_cover_button,
            self._clear_cover_button,
            self._save_button,
        ):
            w.setEnabled(enabled)

    def _load_tags_for_unit(self, unit_id: str) -> None:
        """从 TagService 加载当前 unit 的所有标签，填充 chip 列表。"""
        self._current_tags = []
        self._original_tag_ids = set()
        self._tag_list.clear()
        try:
            grouped = self._tag_service.list_tags_of_content_unit(unit_id)
        except ApplicationError as e:
            logger.warning("加载内容单元标签失败：%s", e)
            self._tags_empty_hint.setVisible(True)
            self._tags_empty_hint.setText(ui.METADATA_PANEL_EMPTY_TAGS_HINT)
            return

        for _category, tags in grouped:
            for tag in tags:
                self._append_tag_chip(tag)
                self._current_tags.append(tag)
                self._original_tag_ids.add(tag.id)

        self._refresh_tags_empty_hint()

    def _refresh_tags_empty_hint(self) -> None:
        """根据当前 chip 列表更新空状态提示可见性。"""
        empty = len(self._current_tags) == 0
        self._tags_empty_hint.setVisible(empty)

    def _append_tag_chip(self, tag: Tag) -> None:
        """添加一个 chip 到列表。"""
        item = QListWidgetItem(f"{tag.name} ×")
        item.setData(_ROLE_TAG, tag)
        item.setToolTip(ui.METADATA_PANEL_TAG_REMOVED.format(name=tag.name))
        self._tag_list.addItem(item)

    def _remove_tag_chip(self, tag: Tag) -> None:
        """从 chip 列表移除指定 Tag。"""
        for i in range(self._tag_list.count()):
            item = self._tag_list.item(i)
            data = item.data(_ROLE_TAG)
            if data is not None and data.id == tag.id:
                self._tag_list.takeItem(i)
                break
        self._current_tags = [t for t in self._current_tags if t.id != tag.id]
        self._refresh_tags_empty_hint()
        # chip 移除后该标签重新出现在预选列表中
        self._refresh_preset_list()

    def _refresh_cover_preview(self, cover_path: str | None) -> None:
        """刷新封面预览（基于 current_unit.path + cover_path）。

        Task 1b 修正：统一加载原图，宽度跟随右栏自适应（_ResizableImageLabel）。
        无图/加载失败 → set_original_pixmap(None)，控件显示占位边框。
        """
        if self._current_unit is None or not cover_path:
            self._cover_value.setText(ui.METADATA_PANEL_COVER_NONE)
            self._cover_preview.set_original_pixmap(None)
            return

        # 显示相对路径
        self._cover_value.setText(cover_path)
        # 加载原图（_ResizableImageLabel 负责按宽度缩放绘制）
        full_path = Path(self._current_unit.path) / cover_path
        pixmap = QPixmap(str(full_path))
        if pixmap.isNull():
            self._cover_preview.set_original_pixmap(None)
            return
        self._cover_preview.set_original_pixmap(pixmap)

    # --- 事件处理 ---

    def _on_tag_input_return(self) -> None:
        """输入框回车：尝试添加标签到 chip 列表。"""
        if self._current_unit is None:
            return
        name = self._tag_input.text().strip()
        if not name:
            return
        # 检查是否已添加（重复）
        for t in self._current_tags:
            if t.name == name:
                QMessageBox.information(
                    self,
                    ui.METADATA_PANEL_TAGS_LABEL,
                    ui.METADATA_PANEL_DUPLICATE_TAG.format(name=name),
                )
                self._tag_input.clear()
                return
        # 通过 TagService 查询标签是否存在（取第一个匹配）
        try:
            candidates = self._tag_service.search_tags(name, limit=20)
        except ApplicationError as e:
            self._show_error(ui.METADATA_PANEL_SAVE_FAILED, str(e))
            return
        # 精确匹配 name（区分大小写避免歧义）
        exact: Tag | None = None
        for c in candidates:
            if c.name == name:
                exact = c
                break
        if exact is None:
            QMessageBox.information(
                self,
                ui.METADATA_PANEL_TAGS_LABEL,
                ui.METADATA_PANEL_TAG_NOT_FOUND.format(name=name),
            )
            return
        # 添加到 chip
        self._append_tag_chip(exact)
        self._current_tags.append(exact)
        self._refresh_tags_empty_hint()
        # chip 添加后从预选列表中移除（避免重复显示）
        self._refresh_preset_list()
        self._tag_input.clear()

    def _on_tag_clicked(self, item: QListWidgetItem) -> None:
        """chip 单击 → 移除。"""
        tag = item.data(_ROLE_TAG)
        if tag is None:
            return
        self._remove_tag_chip(tag)

    def _on_preset_tag_clicked(self, item: QListWidgetItem) -> None:
        """预选标签单击 → 添加到 chip 列表。

        与输入框回车添加等效，但不重复检查（预选列表本身已排除 chip 中的标签）。
        """
        tag = item.data(_ROLE_TAG)
        if tag is None:
            return
        if self._current_unit is None:
            return
        # 防御性重复检查（理论上不会触发）
        for t in self._current_tags:
            if t.id == tag.id:
                return
        self._append_tag_chip(tag)
        self._current_tags.append(tag)
        self._refresh_tags_empty_hint()
        # 添加后从预选列表中移除
        self._refresh_preset_list()

    def _refresh_preset_list(self) -> None:
        """刷新预选标签列表：显示所有已有标签，排除已在 chip 列表中的。

        加载时机：load_unit 时 / chip 增删后 / clear_panel 时。
        """
        self._preset_list.clear()
        if self._current_unit is None:
            self._preset_empty_hint.setVisible(False)
            return
        try:
            all_tags = self._tag_service.list_all_tags()
        except ApplicationError as e:
            logger.warning("加载预选标签列表失败：%s", e)
            self._preset_empty_hint.setVisible(True)
            return
        current_ids = {t.id for t in self._current_tags}
        for tag in all_tags:
            if tag.id in current_ids:
                continue
            item = QListWidgetItem(tag.name)
            item.setData(_ROLE_TAG, tag)
            item.setToolTip(ui.METADATA_PANEL_PRESET_TAGS_LABEL)
            self._preset_list.addItem(item)
        # 无可用标签时显示空提示
        self._preset_empty_hint.setVisible(self._preset_list.count() == 0)

    def _on_pick_cover_clicked(self) -> None:
        """点击「设置封面」→ 请求 MainWindow 打开 CoverPickerDialog。"""
        if self._current_unit is None:
            return
        self.on_pick_cover_requested.emit(self._current_unit.id)

    def _on_clear_cover_clicked(self) -> None:
        """点击「清除封面」→ 清空表单中的封面字段（实际清空在保存时生效）。"""
        if self._current_unit is None:
            return
        self._refresh_cover_preview(None)

    def _on_save_clicked(self) -> None:
        """点击「保存」→ 调用 service 写入数据库。

        步骤：
        1. 调用 ContentService.update_metadata 更新 title/source_url/notes/cover_path。
        2. 计算标签 diff：original_ids 与 current_ids 比较，分别 attach/detach。
        3. 发射 on_saved(unit) 信号通知 MainWindow 提交事务 + 刷新中栏。

        异常处理（Stage 4.5 M18 修复）：
        - InvalidMetadataError / CoverImageNotFoundError → 弹 QMessageBox 提示。
        - TagNotFoundError / ContentUnitNotFoundError → 标签关联失败时发射
          on_save_failed 信号通知 MainWindow rollback 事务（避免 metadata 已写入
          但标签关联失败的"部分成功"状态被意外提交），不发射 on_saved。
        - 其他 ApplicationError → 同上。
        """
        if self._current_unit is None:
            return

        unit = self._current_unit
        # 禁用按钮防止重复提交
        self._save_button.setText(ui.METADATA_PANEL_SAVING)
        self._save_button.setEnabled(False)

        try:
            # 1. 更新元数据（cover_path 使用表单中当前显示的值，由 load_unit / set_cover_path 设置）
            cover_path_value = self._get_form_cover_path()
            updated_unit = self._content_service.update_metadata(
                unit.id,
                title=self._title_edit.text(),
                source_url=self._source_url_edit.text(),
                notes=self._notes_edit.toPlainText(),
                cover_path=cover_path_value,
            )

            # 2. 标签 diff
            current_ids = {t.id for t in self._current_tags}
            to_add = current_ids - self._original_tag_ids
            to_remove = self._original_tag_ids - current_ids

            # M18 修复：标签 attach/detach 失败不再静默吞异常，而是抛出
            # 让外层 except 捕获后发射 on_save_failed 通知 MainWindow rollback。
            for tag_id in to_add:
                self._tag_service.attach_tag_to_unit(unit.id, tag_id)

            for tag_id in to_remove:
                self._tag_service.detach_tag_from_unit(unit.id, tag_id)

            # 3. 更新内部状态
            self._current_unit = updated_unit
            self._original_tag_ids = current_ids

            # 4. 发射信号
            self.on_saved.emit(updated_unit)

        except (InvalidMetadataError, CoverImageNotFoundError) as e:
            # 元数据校验失败：update_metadata 未写入，无需 rollback
            self._show_error(ui.METADATA_PANEL_SAVE_FAILED, str(e))
        except ApplicationError as e:
            # 标签关联失败（TagNotFoundError 等）：metadata 已写入但标签失败，
            # 发射 on_save_failed 通知 MainWindow rollback，避免部分成功状态残留。
            logger.warning("保存失败（将通知 MainWindow rollback）：%s", e)
            self._show_error(ui.METADATA_PANEL_SAVE_FAILED, str(e))
            self.on_save_failed.emit(str(e))
        finally:
            self._save_button.setText(ui.METADATA_PANEL_SAVE_BUTTON)
            self._save_button.setEnabled(True)

    def _get_form_cover_path(self) -> str | None:
        """返回表单中当前封面字段的值。

        None 表示「不改」（仅在 _current_unit.cover_path 已存在时）；
        空字符串表示「清空」；非空字符串表示具体路径。

        实现逻辑：通过对比 _current_unit.cover_path 与 _cover_value 显示判断是否变化。
        - 若 _cover_value 显示「（未设置）」：当前表单无封面。
            - 若 _current_unit.cover_path 原本就有：传 "" 清空。
            - 若原本就没有：传 None 不改（避免无意义写）。
        - 若 _cover_value 显示路径：传该路径（即使与原相同也无副作用）。
        """
        if self._current_unit is None:
            return None
        # 使用 fullText() 获取完整路径（避免 elide 后的省略形式）
        text = self._cover_value.fullText()
        if text == ui.METADATA_PANEL_COVER_NONE:
            # 表单中无封面
            if self._current_unit.cover_path:
                return ""  # 清空
            return None  # 原本也无，不改
        # 表单中显示路径 → 传具体路径
        return text

    def _refresh_completer(self) -> None:
        """刷新自动补全候选标签列表。

        在 load_unit 时调用一次。QCompleter 内部会根据用户输入做前缀过滤
        （默认 MatchStartsWith，与决策 5 一致）。
        """
        try:
            all_tags = self._tag_service.list_all_tags()
        except ApplicationError:
            return
        from PySide6.QtCore import QStringListModel

        names = [t.name for t in all_tags]
        # QStringListModel 已设置时直接替换内容；否则首次创建
        existing_model = self._tag_completer.model()
        if isinstance(existing_model, QStringListModel):
            existing_model.setStringList(names)
        else:
            self._tag_completer.setModel(QStringListModel(names, self))

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)
