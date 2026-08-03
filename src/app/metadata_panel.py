"""元数据编辑面板 UI（Stage 4 Task 2）。

spec §7.2 / §10.3：右栏元数据面板，显示与编辑内容单元元数据。

字段：
- 重命名栏（UI合理性13：显示真实文件名，回车即重命名，不参与元数据保存）→ QLineEdit
- 路径、类型、创建时间 → 只读 QLabel
- 标签 → chip 列表（QListWidget wrap）+ 独立输入框（QLineEdit + QCompleter）
- 来源 URL → QLineEdit
- 备注 → QTextEdit（多行）
- 封面预览 + 设置封面 / 清除封面按钮
- [保存] 按钮

交互（用户确认设计决策 1/5/6）：
- 显式「保存」按钮：用户点击后才写入数据库。
- UI合理性13（2026-08-03）：原「标题」输入框改为「重命名」栏——显示真实文件名，
  回车通过 rename_requested(unit_id, new_name) 信号交给 MainWindow 执行文件重命名，
  不走元数据「保存」按钮；保存按钮仅负责来源 URL / 备注。
- chip + 独立输入框：QLineEdit 输入回车 → 添加到 chip 列表；chip 单击 → 移除。
- 标签前缀匹配自动补全：QCompleter + TagService.search_tags。
- 标签预选区域：标签输入框下方显示所有已有标签（排除已在 chip 列表的），
  单击预选标签即可快速添加到 chip 列表。
- 2026-07-19 决策修正：统一面板下 MetadataPanel 常驻右栏（原"整理模式隐藏"决策被推翻）。

事务边界（与现有 Service 一致）：
- MetadataPanel 调用 ContentService.update_metadata（source_url/notes/cover_path）
  + TagService.attach/detach；重命名通过 FileOperationService（由 MainWindow 执行）。
- 保存成功后通过 on_saved(unit) 信号回调 MainWindow 提交事务 + 刷新中栏。

封面选择（决策 2，操作便捷性6 修正 2026-08-03）：
- 通过 on_pick_cover_requested(unit_id) 信号请求 MainWindow 弹 CoverPickerDialog。
- MainWindow 选定后调用 apply_cover(path) 立即写入数据库（不再等待「保存」按钮）。
- 「清除封面」同样立即清空并保存。

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
import sqlite3
import warnings
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from app.flow_layout import FlowLayout
from app.path_display import make_display_path_from_service
from app.recent_tags import RecentTags
from application.content_service import ContentService
from application.errors import (
    ApplicationError,
    CoverImageNotFoundError,
    InvalidMetadataError,
)
from application.tag_service import TagService
from domain.models import ContentUnit, Tag
from infrastructure.repositories.errors import RepositoryError

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
    # 封面即时保存成功（操作便捷性6，2026-08-03）：设置/清除封面立即落库后发射
    on_cover_saved = Signal(object)  # ContentUnit
    # 重命名请求（UI合理性13）：unit_id + 新名称，由 MainWindow 执行文件重命名
    rename_requested = Signal(str, str)

    def __init__(
        self,
        content_service: ContentService,
        tag_service: TagService,
        commit_callback: Callable[[], None] | None = None,
        on_tags_saved: Callable[[], None] | None = None,
        recent_tags: RecentTags | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._content_service = content_service
        self._tag_service = tag_service
        # 操作便捷性4（2026-08-02）：标签即时保存的提交回调 / 保存成功通知
        self._commit_callback = commit_callback
        self._on_tags_saved = on_tags_saved
        # UI合理性8（2026-08-02）：最近使用标签记录（显示 + 记录）
        self._recent_tags = recent_tags
        self._current_unit: ContentUnit | None = None
        # 当前已保存的 chip 列表（即时保存模式）：list[Tag]
        self._current_tags: list[Tag] = []
        # chip 按钮映射（tag → QPushButton，FlowLayout 中顺序一致）
        self._chip_buttons: list[tuple[Tag, QPushButton]] = []
        # 预选区域分组折叠状态：category_id → 是否折叠
        self._preset_collapsed: set[str] = set()
        # 预选分组内容容器：category_id → QWidget（折叠控制）
        self._preset_groups: dict[str, QWidget] = {}
        # 预选标签按钮（测试接口遍历用）
        self._preset_buttons: list[QPushButton] = []
        # UX 重构 Phase 2 Task 5 修复：受管理根目录服务，用于路径简化显示
        self._managed_root_service = None

        self._setup_ui()

    def set_managed_root_service(self, managed_root_service) -> None:
        """设置受管理根目录服务，用于路径简化显示（open-questions §9）。"""
        self._managed_root_service = managed_root_service

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # 统一区域样式：背景取系统 palette Base（与左栏受管理根目录列表 / 目录树
        # 内部矩形、以及输入框一致的颜色），无边框无圆角。
        self._region_bg = self.palette().color(QPalette.ColorRole.Base).name()
        self.setStyleSheet(
            ui.PANEL_REGION_STYLE_TEMPLATE.format(
                bg=self._region_bg, obj=ui.PANEL_REGION_OBJECT_NAME
            )
        )

        # 未选中内容单元时的占位提示
        self._hint_label = QLabel(ui.METADATA_PANEL_NO_UNIT_HINT)
        self._hint_label.setStyleSheet("color: #666;")
        self._hint_label.setWordWrap(True)
        layout.addWidget(self._hint_label)

        # === 表单字段 ===

        # 重命名栏（UI合理性13：显示真实文件名，回车触发重命名请求）
        self._rename_label = QLabel(ui.METADATA_RENAME_LABEL)
        layout.addWidget(self._rename_label)
        self._rename_edit = QLineEdit()
        self._rename_edit.setPlaceholderText(ui.METADATA_PANEL_RENAME_PLACEHOLDER)
        self._rename_edit.setToolTip(ui.METADATA_PANEL_RENAME_TOOLTIP)
        self._rename_edit.returnPressed.connect(self._on_rename_return)
        layout.addWidget(self._rename_edit)

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

        # chip 区：QFrame + FlowLayout 按钮（UI合理性8 布局修复）。
        # QListWidget 流式模式下 item 高度大于单行固定高度会产生偏移/裁切，
        # 且 item 无边框；改用与「最近使用/已有标签」一致的按钮（浅灰描边），
        # FlowLayout 无 viewport 偏移，标签与背景对齐。
        self._tag_list = QFrame(self)
        self._tag_list.setObjectName(ui.PANEL_REGION_OBJECT_NAME)
        self._tag_list.setFrameShape(QFrame.Shape.NoFrame)
        # 显式设置自身背景与圆角（同色边框使 radius 生效，视觉无边框线）
        self._tag_list.setStyleSheet(
            f"QFrame {{ background: {self._region_bg}; "
            f"border: 1px solid {self._region_bg}; border-radius: 4px; }}"
        )
        self._tag_list.setFixedHeight(ui.METADATA_PANEL_TAG_LIST_HEIGHT)
        self._tag_flow = FlowLayout(self._tag_list)
        self._tag_flow.setContentsMargins(2, 1, 2, 1)
        layout.addWidget(self._tag_list)

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

        # 最近使用标签区域（UI合理性8）：标题独立成行（无背景、字号稍小），
        # 标签按钮单独放在圆角容器内（背景与输入框一致），点击直接添加（即时保存）。
        # 修复：所有容器显式传 parent，避免无 parent 成为顶级窗口导致启动/刷新时闪窗
        # （与 UX 重构 Phase 1 Task 4 修复 3 同根因）
        self._recent_title = QLabel(ui.METADATA_PANEL_RECENT_TAGS_LABEL)
        self._recent_title.setStyleSheet(ui.PANEL_SECTION_TITLE_STYLE)
        layout.addWidget(self._recent_title)
        self._recent_widget = QFrame(self)
        self._recent_widget.setObjectName(ui.PANEL_REGION_OBJECT_NAME)
        self._recent_widget.setFrameShape(QFrame.Shape.NoFrame)  # QFrame 默认 frame 会盖住 QSS 背景
        # panel 级 QSS 对 QFrame 背景不生效，显式设置自身背景与圆角
        # （同色边框使 radius 生效，视觉无边框线）。
        self._recent_widget.setStyleSheet(
            f"QFrame {{ background: {self._region_bg}; "
            f"border: 1px solid {self._region_bg}; border-radius: 4px; }}"
        )
        self._recent_flow_layout = FlowLayout(self._recent_widget)
        layout.addWidget(self._recent_widget)
        self._recent_widget.setVisible(False)

        # 预选标签区域：按分类分组（标题按钮可折叠 + 组内标签按钮流）。
        # UI合理性8：垂直分组替代 QListWidget 流式平铺，分组头与标签不再混排。
        self._preset_label = QLabel(ui.METADATA_PANEL_PRESET_TAGS_LABEL)
        self._preset_label.setStyleSheet(ui.PANEL_SECTION_TITLE_STYLE)
        layout.addWidget(self._preset_label)
        self._preset_scroll = QScrollArea(self)
        self._preset_scroll.setWidgetResizable(True)
        # 统一区域样式（面板级 QSS 提供背景；NoFrame 避免默认边框）
        self._preset_scroll.setObjectName(ui.PANEL_REGION_OBJECT_NAME)
        self._preset_scroll.setFrameShape(QFrame.Shape.NoFrame)
        # 高度可压缩（60~120，Expanding 优先被压缩）：窗口较小时先压缩本区，
        # 保住来源 URL / 备注不被遮挡。
        self._preset_scroll.setMinimumHeight(60)
        self._preset_scroll.setMaximumHeight(ui.METADATA_PANEL_PRESET_SCROLL_HEIGHT)
        self._preset_scroll.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        self._preset_content = QWidget(self._preset_scroll)
        self._preset_layout = QVBoxLayout(self._preset_content)
        self._preset_layout.setContentsMargins(0, 0, 0, 0)
        self._preset_layout.setSpacing(2)
        self._preset_scroll.setWidget(self._preset_content)
        layout.addWidget(self._preset_scroll)
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
        self._notes_edit.setFixedHeight(ui.METADATA_PANEL_NOTES_EDIT_HEIGHT)
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

        # 注意：这里不再 addStretch —— 预选标签区（Expanding）需要吸收面板剩余空间，
        # METADATA_PANEL_PRESET_SCROLL_HEIGHT 才作为实际高度上限生效。

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

        # 填充字段（重命名栏显示真实文件名，UI合理性13 不再读 title）
        self._rename_edit.setText(Path(unit.path).name)
        # 路径简化显示（UX 重构 Phase 2 Task 5 修复：从受管理根目录开始显示）
        display_path = (
            make_display_path_from_service(unit.path, self._managed_root_service)
            if self._managed_root_service is not None
            else unit.path
        )
        self._path_value.setText(display_path)
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
        self._preset_collapsed = set()

        self._hint_label.setVisible(True)
        self._rename_edit.clear()
        self._path_value.setText("")
        self._type_value.setText("")
        self._created_value.setText("")
        self._source_url_edit.clear()
        self._notes_edit.clear()
        self._disconnect_flow_buttons(self._tag_flow)
        self._tag_flow.clear()
        self._chip_buttons = []
        self._tag_input.clear()
        self._disconnect_flow_buttons(self._recent_flow_layout)
        self._recent_flow_layout.clear()
        self._recent_widget.setVisible(False)
        self._recent_title.setVisible(False)
        self._clear_preset_groups()
        self._preset_empty_hint.setVisible(False)
        self._cover_value.setText(ui.METADATA_PANEL_COVER_NONE)
        self._cover_preview.set_original_pixmap(None)  # 清空图片

        self._set_form_enabled(False)

    def _clear_preset_groups(self) -> None:
        """清空预选分组内容（删除全部子 widget）。"""
        while self._preset_layout.count() > 0:
            item = self._preset_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                self._disconnect_button_signals(widget)
                for child in widget.findChildren(QPushButton):
                    self._disconnect_button_signals(child)
                widget.deleteLater()
        self._preset_groups = {}
        self._preset_buttons = []

    def _disconnect_button_signals(self, widget: QWidget) -> None:
        """断开按钮信号，打破 clicked/toggled lambda 对 self 的引用环。

        测试稳定性1（2026-08-03）：chip / 预设 / 最近标签按钮的 lambda 闭包捕获 self，
        deleteLater 后若 panel 包装器已被回收，事件循环处理 DeferredDelete 时会在按钮
        析构途中拆除连接、释放 lambda，触发 panel 二次删除（PySide6 6.11.1 +
        Python 3.14 原生崩溃）。删除前断开信号，将引用环在 panel 仍存活时打破。
        """
        if isinstance(widget, QPushButton):
            for signal_name in ("clicked", "toggled"):
                try:
                    with warnings.catch_warnings():
                        # 无连接时 PySide6 会打印 RuntimeWarning，这里忽略
                        warnings.simplefilter("ignore", RuntimeWarning)
                        getattr(widget, signal_name).disconnect()
                except (RuntimeError, TypeError):
                    pass

    def _disconnect_flow_buttons(self, flow: FlowLayout) -> None:
        """断开 flow 内（含子层）按钮信号，供 flow.clear() 前调用（测试稳定性1）。"""
        for i in range(flow.count()):
            item = flow.itemAt(i)
            widget = item.widget() if item is not None else None
            if widget is not None:
                self._disconnect_button_signals(widget)
                for child in widget.findChildren(QPushButton):
                    self._disconnect_button_signals(child)

    def current_unit(self) -> ContentUnit | None:
        """返回当前加载的 ContentUnit（供测试）。"""
        return self._current_unit

    def apply_cover(self, cover_path: str) -> None:
        """封面即时保存（操作便捷性6，2026-08-03）。

        由 CoverPickerDialog 选定（MetadataView 调用）或「清除封面」触发：
        立即调用 update_metadata 写入 cover_path（空串 = 清空）→ 更新表单状态 →
        提交事务 → 发射 on_cover_saved。不重载表单，未保存的来源/备注保留。

        失败时不改表单状态、不提交，弹错误提示（与 _apply_tag_toggle 一致）。
        """
        if self._current_unit is None:
            return
        unit_id = self._current_unit.id
        try:
            updated = self._content_service.update_metadata(unit_id, cover_path=cover_path)
        except (ApplicationError, RepositoryError, sqlite3.Error) as e:
            logger.warning("封面即时保存失败：%s", e)
            self._show_error(ui.METADATA_PANEL_SAVE_FAILED, str(e))
            return

        # 更新内部状态（保留来源/备注等未保存编辑）
        self._current_unit = updated
        self._refresh_cover_preview(updated.cover_path)

        # 提交 + 通知调用方（刷新中栏封面图标/缩略图）
        if self._commit_callback is not None:
            self._commit_callback()
        self.on_cover_saved.emit(updated)

    # --- 测试辅助接口 ---

    def rename_text(self) -> str:
        """返回重命名栏当前文本（UI合理性13 替代原 title_text）。"""
        return self._rename_edit.text()

    def apply_renamed_unit(self, unit: ContentUnit) -> None:
        """重命名成功后更新面板状态（UI合理性13）。

        由 MainWindow 在文件重命名成功后调用：只更新当前 unit 与重命名栏文本，
        不重载表单，保留未保存的来源/备注编辑（与 apply_cover 同策略）。
        """
        self._current_unit = unit
        self._rename_edit.setText(Path(unit.path).name)

    def source_url_text(self) -> str:
        return self._source_url_edit.text()

    def notes_text(self) -> str:
        return self._notes_edit.toPlainText()

    def cover_path_text(self) -> str:
        """返回当前表单中显示的封面相对路径（如已加载）。"""
        if self._current_unit is None:
            return ""
        # cover_path 由 load_unit 或 apply_cover 设置后通过 _cover_value 显示
        # 使用 fullText() 获取完整文本（避免 elide 后的省略形式）
        if self._cover_value.fullText() == ui.METADATA_PANEL_COVER_NONE:
            return ""
        return self._cover_value.fullText()

    def tag_chips(self) -> list[str]:
        """返回当前 chip 列表中的标签名（供测试）。"""
        return [t.name for t in self._current_tags]

    def preset_tag_names(self) -> list[str]:
        """返回当前预选区域中的标签名（供测试）。"""
        return [b.text() for b in self._preset_buttons]

    def click_preset_tag(self, tag_name: str) -> None:
        """程序化点击指定名称的预选标签（即时添加，供测试）。"""
        for btn in self._preset_buttons:
            if btn.text() == tag_name:
                btn.click()
                return

    def preset_group_names(self) -> list[str]:
        """返回当前预选区域的分组名（供测试）。"""
        names: list[str] = []
        for i in range(self._preset_layout.count()):
            item = self._preset_layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if isinstance(widget, QPushButton) and widget.isCheckable():
                names.append(widget.text().lstrip("▸▾ ").strip())
        return names

    def click_preset_group(self, category_name: str) -> None:
        """程序化点击指定分类的分组标题按钮（折叠/展开，供测试）。"""
        for i in range(self._preset_layout.count()):
            item = self._preset_layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if (
                isinstance(widget, QPushButton)
                and widget.isCheckable()
                and widget.text().lstrip("▸▾ ").strip() == category_name
            ):
                widget.click()
                return

    def is_preset_group_collapsed(self, category_id: str) -> bool:
        """返回指定分类分组是否处于折叠状态（供测试）。"""
        return category_id in self._preset_collapsed

    def recent_tag_names(self) -> list[str]:
        """返回当前最近使用标签按钮文本（供测试）。"""
        names: list[str] = []
        for i in range(self._recent_flow_layout.count()):
            item = self._recent_flow_layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if isinstance(widget, QPushButton):
                names.append(widget.text())
        return names

    def click_recent_tag(self, tag_name: str) -> None:
        """程序化点击指定名称的最近标签按钮（即时添加，供测试）。"""
        for i in range(self._recent_flow_layout.count()):
            item = self._recent_flow_layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if isinstance(widget, QPushButton) and widget.text() == tag_name:
                widget.click()
                return

    def is_recent_tag_enabled(self, tag_name: str) -> bool:
        """返回指定最近标签按钮是否可点击（已在 chip 时禁用，供测试）。"""
        for i in range(self._recent_flow_layout.count()):
            item = self._recent_flow_layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if isinstance(widget, QPushButton) and widget.text() == tag_name:
                return widget.isEnabled()
        return False

    def is_save_button_enabled(self) -> bool:
        return self._save_button.isEnabled()

    def is_pick_cover_button_enabled(self) -> bool:
        return self._pick_cover_button.isEnabled()

    def is_form_enabled(self) -> bool:
        """返回表单是否处于可编辑状态（已加载 unit 时为 True）。"""
        return self._rename_edit.isEnabled()

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
        for tag, btn in self._chip_buttons:
            if tag.name == tag_name:
                btn.click()
                return

    # --- 内部实现 ---

    def _set_form_enabled(self, enabled: bool) -> None:
        """启用/禁用表单所有控件。"""
        for w in (
            self._rename_edit,
            self._source_url_edit,
            self._notes_edit,
            self._tag_input,
            self._tag_list,
            self._recent_widget,
            self._preset_scroll,
            self._pick_cover_button,
            self._clear_cover_button,
            self._save_button,
        ):
            w.setEnabled(enabled)

    def _load_tags_for_unit(self, unit_id: str) -> None:
        """从 TagService 加载当前 unit 的所有标签，填充 chip 列表。"""
        self._current_tags = []
        self._disconnect_flow_buttons(self._tag_flow)
        self._tag_flow.clear()
        self._chip_buttons = []
        try:
            grouped = self._tag_service.list_tags_of_content_unit(unit_id)
        except ApplicationError as e:
            logger.warning("加载内容单元标签失败：%s", e)
            return

        for _category, tags in grouped:
            for tag in tags:
                self._append_tag_chip(tag)
                self._current_tags.append(tag)

        self._refresh_recent_list()

    def _append_tag_chip(self, tag: Tag) -> None:
        """添加一个 chip 按钮（与「最近使用/已有标签」按钮样式一致，浅灰描边）。"""
        btn = QPushButton(f"{tag.name} ×", self._tag_list)
        btn.setStyleSheet(ui.METADATA_TAG_BUTTON_STYLE.format(bg=self._region_bg))
        btn.setToolTip(ui.METADATA_PANEL_TAG_REMOVED.format(name=tag.name))
        btn.clicked.connect(lambda checked=False, t=tag: self._apply_tag_toggle(t, attach=False))
        self._tag_flow.addWidget(btn)
        self._chip_buttons.append((tag, btn))

    def _remove_tag_chip(self, tag: Tag) -> None:
        """从 chip 列表移除指定 Tag。"""
        for i, (t, btn) in enumerate(self._chip_buttons):
            if t.id == tag.id:
                self._tag_flow.takeAt(i)
                self._disconnect_button_signals(btn)
                btn.deleteLater()
                del self._chip_buttons[i]
                break
        self._current_tags = [t for t in self._current_tags if t.id != tag.id]
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
        # 操作便捷性4：添加到 chip 并即时保存
        self._apply_tag_toggle(exact, attach=True)
        self._tag_input.clear()

    def _refresh_preset_list(self) -> None:
        """刷新预选标签区域：按分类垂直分组（UI合理性8），排除已在 chip 中的。

        - 分组标题按钮（可折叠，▾/▸ 指示，默认展开）：点击折叠/展开该组。
        - 组内标签为 FlowLayout 按钮，按名称排序（同分类相邻，UI合理性7），
          点击 → 即时保存（操作便捷性4）。
        加载时机：load_unit 时 / chip 增删后 / clear_panel 时。
        """
        self._clear_preset_groups()
        if self._current_unit is None:
            self._preset_empty_hint.setVisible(False)
            return
        try:
            grouped = self._tag_service.list_categories_with_tags()
        except ApplicationError as e:
            logger.warning("加载预选标签列表失败：%s", e)
            self._preset_empty_hint.setVisible(True)
            return
        current_ids = {t.id for t in self._current_tags}
        total_shown = 0
        for category, tags in grouped:
            available = sorted(
                (t for t in tags if t.id not in current_ids),
                key=lambda t: t.name.lower(),
            )
            if not available:
                continue
            collapsed = category.id in self._preset_collapsed
            # 分组标题按钮（可折叠）
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
            # 组内标签按钮（FlowLayout）
            flow = QWidget(self._preset_content)
            flow_layout = FlowLayout(flow)
            for tag in available:
                btn = QPushButton(tag.name, flow)
                btn.setStyleSheet(ui.METADATA_TAG_BUTTON_STYLE.format(bg=self._region_bg))
                btn.clicked.connect(lambda checked=False, t=tag: self._apply_tag_toggle(t, True))
                flow_layout.addWidget(btn)
                self._preset_buttons.append(btn)
                total_shown += 1
            flow.setVisible(not collapsed)
            self._preset_layout.addWidget(flow)
            self._preset_groups[category.id] = flow
        self._preset_layout.addStretch(1)
        # 无可用标签时显示空提示
        self._preset_empty_hint.setVisible(total_shown == 0)

    def _toggle_preset_group(self, category_id: str, checked: bool) -> None:
        """折叠/展开预选分组（UI合理性8：分类标签折叠）。"""
        if checked:
            self._preset_collapsed.discard(category_id)
        else:
            self._preset_collapsed.add(category_id)
        flow = self._preset_groups.get(category_id)
        if flow is not None:
            flow.setVisible(checked)
        # 更新分组标题按钮指示符（sender 为标题按钮）
        btn = self.sender()
        if isinstance(btn, QPushButton) and btn.text():
            name = btn.text().lstrip("▸▾ ").strip()
            btn.setText(f"{'▾' if checked else '▸'} {name}")

    def _refresh_recent_list(self) -> None:
        """刷新最近使用标签区域（UI合理性8）。无记录/无 unit 时整体隐藏。"""
        self._disconnect_flow_buttons(self._recent_flow_layout)
        self._recent_flow_layout.clear()
        if self._current_unit is None or self._recent_tags is None:
            self._recent_widget.setVisible(False)
            self._recent_title.setVisible(False)
            return
        tag_ids = self._recent_tags.list_recent()
        if not tag_ids:
            self._recent_widget.setVisible(False)
            self._recent_title.setVisible(False)
            return
        # 映射 id → Tag（list_categories_with_tags 一次获取全部）
        id_to_tag: dict[str, Tag] = {}
        try:
            for _category, tags in self._tag_service.list_categories_with_tags():
                for t in tags:
                    id_to_tag[t.id] = t
        except ApplicationError:
            self._recent_widget.setVisible(False)
            self._recent_title.setVisible(False)
            return
        current_ids = {t.id for t in self._current_tags}
        shown = 0
        for tag_id in tag_ids:
            tag = id_to_tag.get(tag_id)
            if tag is None:
                continue  # 标签已删除，跳过
            btn = QPushButton(tag.name, self._recent_widget)
            btn.setStyleSheet(ui.METADATA_TAG_BUTTON_STYLE.format(bg=self._region_bg))
            if tag.id in current_ids:
                btn.setEnabled(False)  # 已在 chip：灰显不可点
            btn.clicked.connect(lambda checked=False, t=tag: self._apply_tag_toggle(t, True))
            self._recent_flow_layout.addWidget(btn)
            shown += 1
        self._recent_widget.setVisible(shown > 0)
        self._recent_title.setVisible(shown > 0)

    def _apply_tag_toggle(self, tag: Tag, attach: bool) -> None:
        """即时保存标签变更（操作便捷性4，2026-08-02）。

        立即执行 attach/detach + 提交回调，再更新本地 chip/预选/最近状态；
        写库失败时不改本地状态并提示。
        """
        if self._current_unit is None:
            return
        unit_id = self._current_unit.id
        try:
            if attach:
                self._tag_service.attach_tag_to_unit(unit_id, tag.id)
            else:
                self._tag_service.detach_tag_from_unit(unit_id, tag.id)
        except (ApplicationError, RepositoryError, sqlite3.Error) as e:
            logger.warning("标签即时保存失败：%s", e)
            self._show_error(ui.METADATA_PANEL_SAVE_FAILED, str(e))
            return

        # 更新本地状态
        if attach:
            self._append_tag_chip(tag)
            self._current_tags.append(tag)
            self._refresh_preset_list()
            if self._recent_tags is not None:
                self._recent_tags.record(tag.id)
        else:
            self._remove_tag_chip(tag)

        # 提交 + 通知调用方（刷新中栏/状态）
        if self._commit_callback is not None:
            self._commit_callback()
        self._refresh_recent_list()
        if self._on_tags_saved is not None:
            self._on_tags_saved()

    def _on_pick_cover_clicked(self) -> None:
        """点击「设置封面」→ 请求 MainWindow 打开 CoverPickerDialog。"""
        if self._current_unit is None:
            return
        self.on_pick_cover_requested.emit(self._current_unit.id)

    def _on_clear_cover_clicked(self) -> None:
        """点击「清除封面」→ 立即清空并保存（操作便捷性6，2026-08-03）。"""
        if self._current_unit is None:
            return
        self.apply_cover("")

    def _on_save_clicked(self) -> None:
        """点击「保存」→ 调用 service 写入数据库。

        步骤：
        1. 调用 ContentService.update_metadata 更新 source_url/notes/cover_path。
        2. 发射 on_saved(unit) 信号通知 MainWindow 提交事务 + 刷新中栏。

        操作便捷性4（2026-08-02）：标签已改为即时保存（chip 增删立即 attach/detach），
        「保存」按钮不再处理标签 diff，仅负责元数据字段。
        UI合理性13（2026-08-03）：重命名走 rename_requested，保存按钮不再含 title。

        异常处理（Stage 4.5 M18 修复）：
        - InvalidMetadataError / CoverImageNotFoundError → 弹 QMessageBox 提示。
        - 其他 ApplicationError → 发射 on_save_failed 通知 MainWindow rollback
          （避免元数据部分成功状态被意外提交），不发射 on_saved。
        """
        if self._current_unit is None:
            return

        unit = self._current_unit
        # 禁用按钮防止重复提交
        self._save_button.setText(ui.METADATA_PANEL_SAVING)
        self._save_button.setEnabled(False)

        try:
            # 1. 更新元数据（cover_path 使用表单中当前显示的值，由 load_unit / apply_cover 设置）
            cover_path_value = self._get_form_cover_path()
            updated_unit = self._content_service.update_metadata(
                unit.id,
                source_url=self._source_url_edit.text(),
                notes=self._notes_edit.toPlainText(),
                cover_path=cover_path_value,
            )

            # 2. 更新内部状态（标签已即时保存）
            self._current_unit = updated_unit

            # 3. 发射信号
            self.on_saved.emit(updated_unit)

        except (InvalidMetadataError, CoverImageNotFoundError) as e:
            # 元数据校验失败：update_metadata 未写入，无需 rollback
            self._show_error(ui.METADATA_PANEL_SAVE_FAILED, str(e))
        except ApplicationError as e:
            logger.warning("保存失败（将通知 MainWindow rollback）：%s", e)
            self._show_error(ui.METADATA_PANEL_SAVE_FAILED, str(e))
            self.on_save_failed.emit(str(e))
        finally:
            self._save_button.setText(ui.METADATA_PANEL_SAVE_BUTTON)
            self._save_button.setEnabled(True)

    def _on_rename_return(self) -> None:
        """重命名栏回车 → 请求 MainWindow 执行文件重命名（UI合理性13）。

        仅做基础校验（非空、有变化），实际文件操作与冲突/非法名处理由 MainWindow
        通过 FileOperationService 完成；面板自身不触碰文件系统。
        """
        if self._current_unit is None:
            return
        new_name = self._rename_edit.text().strip()
        if not new_name:
            return
        if new_name == Path(self._current_unit.path).name:
            return
        self.rename_requested.emit(self._current_unit.id, new_name)

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
        QMessageBox.information(self, title, message)
