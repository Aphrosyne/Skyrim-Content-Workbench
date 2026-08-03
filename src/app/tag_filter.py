"""标签筛选栏 UI（Stage 4 Task 3）。

spec §5.1 / §7.2 / §10.3：中栏顶部标签筛选栏，多选标签实时筛选内容单元列表。

交互（用户确认设计决策 Q1-Q8）：
- 默认全部折叠。点击分类按钮 → 展开该分类下标签列表。
- 互斥展开：同时只展开一个分类，点击新分类自动折叠旧分类。
- 标签按钮多选高亮：选中态使用边框高亮（Q2: A、Q5: A、Q7: A）。
- 折叠分类时保留已选标签状态，分类按钮显示已选数量徽标「分类名 (N)」。
- 跨分类 AND：内容单元必须每个被选分类下至少有一个标签命中才保留。
- 同分类内 OR：同分类下多标签取并集。
- 「清除全部」按钮：清空所有已选标签。
- 筛选状态在切换目录树节点时保留，自动应用于新目录（Q3: A）。

数据流：
- TagFilterBar 不直接查询 content_unit，仅发射 on_filter_changed(set[str]) 信号。
- MainWindow 接收信号后调用 TagService.filter_unit_ids_by_category_and
  得到允许显示的 unit_id 集合，对中栏文件列表过滤。
- 非内容单元条目在筛选激活时全部隐藏（Q1: B：列表变成纯结果集）。

约束：
- TagService 未注入时不创建 TagFilterBar（MainWindow 层降级处理）。
- 标签库为空时 TagFilterBar 隐藏（MainWindow 层根据 categories 数量显隐）。
- 不修改数据库；只读访问 TagService。
"""

from __future__ import annotations

import logging
import warnings

from PySide6.QtCore import Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from app.tag_colors import (
    category_color_faded_hex,
    category_color_hex,
    category_color_vivid_hex,
    text_color_faded_hex,
    text_color_hex,
    text_color_vivid_hex,
)
from application.tag_service import TagService
from domain.models import Tag, TagCategory

logger = logging.getLogger(__name__)


def _disconnect_button(btn: QPushButton) -> None:
    """断开按钮 clicked 连接（测试稳定性1：避免 lambda 闭包引用环在析构期崩溃）。"""
    try:
        with warnings.catch_warnings():
            # 无连接时 PySide6 会打印 RuntimeWarning，这里忽略
            warnings.simplefilter("ignore", RuntimeWarning)
            btn.clicked.disconnect()
    except (RuntimeError, TypeError):
        pass


def _tag_button_style(bg: str, text: str, border: str) -> str:
    """三态统一样式的标签按钮（2px 边框、同 padding/圆角 → 高度不跳动）。

    UI合理性16 验收反馈：原选中态样式与常规态 padding/边框不同，
    导致点击选中时按钮高度变化、中栏上方内容跳动几像素。
    """
    return (
        f"QPushButton {{ background: {bg}; color: {text}; "
        f"border: 2px solid {border}; border-radius: 4px; padding: 2px 8px; }}"
    )


def _tag_fallback_style() -> str:
    """未知分类色相的回退样式（灰底，2px 边框，与三态同尺寸）。"""
    return _tag_button_style("#fafafa", "#1a1a1a", "#c0c0c0")


# 分类按钮展开态样式
_CATEGORY_EXPANDED_STYLE = """
QPushButton {
    border: 1px solid #1976d2;
    background: #e3f2fd;
    color: #1a1a1a;
    padding: 4px 10px;
    border-radius: 3px;
    font-weight: bold;
}
"""

_CATEGORY_NORMAL_STYLE = """
QPushButton {
    border: 1px solid #bbb;
    background: #f5f5f5;
    color: #1a1a1a;
    padding: 4px 10px;
    border-radius: 3px;
}
QPushButton:hover {
    border: 1px solid #1976d2;
    background: #f0f7ff;
    color: #1a1a1a;
}
"""


class TagFilterBar(QWidget):
    """标签筛选栏控件。

    使用方式：
        bar = TagFilterBar(tag_service)
        bar.on_filter_changed.connect(self._on_tag_filter_changed)
        bar.refresh_categories()

    信号：
        on_filter_changed(selected_tag_ids: set[str])：
            已选标签 ID 集合变化时发射。空集合表示「无筛选」。
        on_exclusion_changed(excluded_tag_ids: set[str])：
            反选（排除）标签 ID 集合变化时发射；空集合表示无排除。
    """

    on_filter_changed = Signal(set)
    on_exclusion_changed = Signal(set)

    def __init__(self, tag_service: TagService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tag_service = tag_service

        # 内部状态：
        # - _categories: list[(TagCategory, list[Tag])]（按 category.name 排序）
        # - _selected_tag_ids: set[str]（已选标签 ID）
        # - _expanded_category_id: str | None（当前展开的分类 ID，互斥）
        self._categories: list[tuple[TagCategory, list[Tag]]] = []
        # BugFix2：分类色映射（tag_id → color_hue），供标签按钮填充着色
        self._tag_hues: dict[str, int] = {}
        self._selected_tag_ids: set[str] = set()
        # UI合理性16：三态（0=未选 / 1=已选 / 2=已排除），反选可多个
        self._tag_states: dict[str, int] = {}
        self._excluded_tag_ids: set[str] = set()
        self._expanded_category_id: str | None = None

        # 分类按钮组（互斥展开）
        self._category_buttons: dict[str, QPushButton] = {}  # category_id → button
        # 标签按钮（三态，非 checkable，点击由 _cycle_tag 处理）
        self._tag_buttons: dict[str, QPushButton] = {}  # tag_id → button

        self._setup_ui()

    # --- UI 构建 ---

    def _setup_ui(self) -> None:
        """构建控件布局。"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(2)

        # 提示文本
        self._hint_label = QLabel(ui.TAG_FILTER_BAR_HINT)
        self._hint_label.setWordWrap(False)
        self._hint_label.setStyleSheet("color: #666; font-size: 11px;")
        outer.addWidget(self._hint_label)

        # 分类按钮行（横排，可换行）
        # 显式传 parent：避免无 parent QFrame 成为顶级窗口导致启动闪窗
        # （与 UX 重构 Phase 1 Task 4 修复 3 同根因，2026-08-02）
        self._category_row = QFrame(self)
        self._category_row.setObjectName("categoryRow")
        self._category_layout = QHBoxLayout(self._category_row)
        self._category_layout.setContentsMargins(0, 0, 0, 0)
        self._category_layout.setSpacing(4)
        self._category_layout.addStretch(1)  # 默认空，refresh 时填充
        outer.addWidget(self._category_row)

        # 标签按钮行（展开分类时填充）
        self._tag_row = QFrame(self)
        self._tag_row.setObjectName("tagRow")
        self._tag_row.setVisible(False)
        self._tag_layout = QHBoxLayout(self._tag_row)
        self._tag_layout.setContentsMargins(8, 2, 8, 2)
        self._tag_layout.setSpacing(4)
        self._tag_layout.addStretch(1)
        outer.addWidget(self._tag_row)

        # 底部操作行：清除全部按钮（右对齐）
        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)
        self._clear_button = QPushButton(ui.TAG_FILTER_CLEAR_BUTTON)
        self._clear_button.setEnabled(False)
        self._clear_button.clicked.connect(self._on_clear_clicked)
        bottom_row.addWidget(self._clear_button)
        outer.addLayout(bottom_row)

        # 控件本身自适应高度
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    # --- 公开接口 ---

    def refresh_categories(self) -> None:
        """从 TagService 重新加载分类与标签，重建分类按钮。

        已选标签若在新标签库中仍存在则保留，否则剔除。
        """
        try:
            self._categories = self._tag_service.list_categories_with_tags()
        except Exception:  # noqa: BLE001
            logger.exception("加载标签分类失败")
            self._categories = []
        self._tag_hues = {
            tag.id: category.color_hue for category, tags in self._categories for tag in tags
        }
        # 剔除已不存在的已选标签
        valid_tag_ids = {tag.id for _, tags in self._categories for tag in tags}
        invalid = self._selected_tag_ids - valid_tag_ids
        if invalid:
            self._selected_tag_ids = self._selected_tag_ids & valid_tag_ids
            logger.info("刷新后剔除失效标签：%s", invalid)
        invalid_excluded = self._excluded_tag_ids - valid_tag_ids
        if invalid_excluded:
            logger.info("刷新后剔除失效反选标签：%s", invalid_excluded)
            self._excluded_tag_ids = self._excluded_tag_ids & valid_tag_ids

        # 重建三态映射：已选 / 已排除 / 未选
        self._tag_states = {
            tag.id: (
                2
                if tag.id in self._excluded_tag_ids
                else 1
                if tag.id in self._selected_tag_ids
                else 0
            )
            for _, tags in self._categories
            for tag in tags
        }

        # 重建分类按钮
        self._rebuild_category_buttons()
        # 重建当前展开分类的标签按钮
        self._rebuild_tag_buttons_for_expanded()

        # 显隐：无分类时整体隐藏（由 MainWindow 控制 setVisible）
        self._update_visibility_state()

        # 若剔除了失效标签/反选标签，发射信号
        if invalid:
            self.on_filter_changed.emit(self._selected_tag_ids.copy())
        if invalid_excluded:
            self.on_exclusion_changed.emit(self._excluded_tag_ids.copy())

    def current_selected_tag_ids(self) -> set[str]:
        """返回当前已选标签 ID 集合的副本（供测试）。"""
        return self._selected_tag_ids.copy()

    def current_excluded_tag_ids(self) -> set[str]:
        """返回当前反选（排除）标签 ID 集合的副本（供测试）。"""
        return self._excluded_tag_ids.copy()

    def is_filter_active(self) -> bool:
        """返回筛选是否激活（有已选或反选标签）。"""
        return len(self._selected_tag_ids) > 0 or bool(self._excluded_tag_ids)

    def clear_selection(self) -> None:
        """清空所有已选标签并发射信号（不重建按钮）。"""
        if not self._selected_tag_ids and not self._excluded_tag_ids:
            return
        self._selected_tag_ids.clear()
        self._excluded_tag_ids.clear()
        for tag_id in self._tag_states:
            self._tag_states[tag_id] = 0
        # 更新所有标签按钮视觉态
        for tag_id, btn in self._tag_buttons.items():
            self._apply_tag_button_style(tag_id, btn)
        self._update_clear_button_state()
        self._refresh_category_badges()
        self.on_filter_changed.emit(set())
        self.on_exclusion_changed.emit(set())

    def has_categories(self) -> bool:
        """返回是否存在任何标签分类（供 MainWindow 决定显隐）。"""
        return len(self._categories) > 0

    # --- 内部：UI 重建 ---

    def _rebuild_category_buttons(self) -> None:
        """重建分类按钮行。"""
        # 清空旧按钮（保留末尾 stretch）
        while self._category_layout.count() > 1:
            item = self._category_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                _disconnect_button(widget)
                widget.deleteLater()
        self._category_buttons.clear()

        for category, _ in self._categories:
            btn = QPushButton(category.name)
            btn.setCheckable(True)
            btn.setChecked(category.id == self._expanded_category_id)
            btn.clicked.connect(
                lambda checked=False, cid=category.id: self._on_category_clicked(cid)
            )
            self._apply_category_button_style(category.id, btn)
            # 预留加粗文字 + 徽标宽度，避免选中计数徽标导致分类行跳动
            self._reserve_button_width(
                btn, f"{category.name}{ui.TAG_FILTER_CATEGORY_BADGE_RESERVE}"
            )
            self._category_buttons[category.id] = btn
            self._category_layout.insertWidget(self._category_layout.count() - 1, btn)

        self._refresh_category_badges()

    def _rebuild_tag_buttons_for_expanded(self) -> None:
        """重建当前展开分类的标签按钮行。无展开时隐藏行。"""
        # 清空旧按钮（保留末尾 stretch）
        while self._tag_layout.count() > 1:
            item = self._tag_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                _disconnect_button(widget)
                widget.deleteLater()
        self._tag_buttons.clear()

        if self._expanded_category_id is None:
            self._tag_row.setVisible(False)
            return

        # 找到展开分类的标签列表
        tags = next(
            (t for cat, t in self._categories if cat.id == self._expanded_category_id),
            [],
        )

        if not tags:
            # 空提示
            hint = QLabel(ui.TAG_FILTER_CATEGORY_EMPTY_HINT)
            hint.setStyleSheet("color: #999; font-style: italic;")
            self._tag_layout.insertWidget(self._tag_layout.count() - 1, hint)
            self._tag_row.setVisible(True)
            return

        for tag in tags:
            btn = QPushButton(tag.name)
            btn.setCheckable(False)
            btn.clicked.connect(lambda checked=False, tid=tag.id: self._cycle_tag(tid))
            self._apply_tag_button_style(tag.id, btn)
            # 预留加粗文字宽度，避免 加粗/删除线 状态切换导致标签行跳动
            self._reserve_button_width(btn, tag.name)
            self._tag_buttons[tag.id] = btn
            self._tag_layout.insertWidget(self._tag_layout.count() - 1, btn)

        self._tag_row.setVisible(True)

    # --- 内部：事件处理 ---

    def _on_category_clicked(self, category_id: str) -> None:
        """分类按钮点击：互斥展开/折叠。"""
        if self._expanded_category_id == category_id:
            # 再次点击 → 折叠
            self._expanded_category_id = None
        else:
            self._expanded_category_id = category_id

        # 更新所有分类按钮视觉态
        for cid, btn in self._category_buttons.items():
            btn.setChecked(cid == self._expanded_category_id)
            self._apply_category_button_style(cid, btn)

        # 重建标签按钮行
        self._rebuild_tag_buttons_for_expanded()

    def _cycle_tag(self, tag_id: str) -> None:
        """标签按钮三态循环（UI合理性16）：
        未选 → 已选 → 已排除（反选）→ 未选。
        已排除可多个标签并存；再点一次即取消。
        """
        state = self._tag_states.get(tag_id, 0)
        if state == 0:
            self._tag_states[tag_id] = 1
            self._selected_tag_ids.add(tag_id)
        elif state == 1:
            # 已选 → 反选：移出正选集，加入排除集合
            self._tag_states[tag_id] = 2
            self._selected_tag_ids.discard(tag_id)
            self._excluded_tag_ids.add(tag_id)
        else:
            # 已排除 → 取消
            self._tag_states[tag_id] = 0
            self._excluded_tag_ids.discard(tag_id)

        # 更新全部按钮视觉态
        for tid, btn in self._tag_buttons.items():
            self._apply_tag_button_style(tid, btn)

        # 更新清除按钮可用性与分类徽标
        self._update_clear_button_state()
        self._refresh_category_badges()

        # 发射信号
        self.on_filter_changed.emit(self._selected_tag_ids.copy())
        self.on_exclusion_changed.emit(self._excluded_tag_ids.copy())

    def _apply_tag_button_style(self, tag_id: str, btn: QPushButton) -> None:
        """根据三态应用标签按钮样式（2px 边框，尺寸统一防跳动）。

        - 未选：彩色圆角 + 亮度自适应黑/白字
        - 已选：略微提饱和背景 + 白色描边环 + 加粗
        - 已排除：降饱和/变淡背景 + 删除线
        文字内容不变（不用 ✓/− 前缀），宽度由 _reserve_button_width 预留，状态切换不跳动。
        """
        state = self._tag_states.get(tag_id, 0)
        hue = self._tag_hues.get(tag_id)

        if state == 1:
            bg = category_color_vivid_hex(hue) if hue is not None else "#b3d4fc"
            text = text_color_vivid_hex(hue) if hue is not None else "#1a1a1a"
            btn.setStyleSheet(_tag_button_style(bg, text, "#ffffff"))
            font = btn.font()
            font.setBold(True)
            font.setStrikeOut(False)
            btn.setFont(font)
            btn.setToolTip("")
        elif state == 2:
            bg = category_color_faded_hex(hue) if hue is not None else "#e0e0e0"
            text = text_color_faded_hex(hue) if hue is not None else "#1a1a1a"
            btn.setStyleSheet(_tag_button_style(bg, text, bg))
            btn.setToolTip(ui.TAG_FILTER_EXCLUDED_TOOLTIP)
            font = btn.font()
            font.setBold(False)
            font.setStrikeOut(True)
            btn.setFont(font)
        else:
            if hue is not None:
                btn.setStyleSheet(
                    _tag_button_style(
                        category_color_hex(hue), text_color_hex(hue), category_color_hex(hue)
                    )
                )
            else:
                btn.setStyleSheet(_tag_fallback_style())
            btn.setToolTip("")
            font = btn.font()
            font.setBold(False)
            font.setStrikeOut(False)
            btn.setFont(font)

    def _reserve_button_width(self, btn: QPushButton, text: str) -> None:
        """按加粗文字 + padding/边框预留按钮最小宽度（状态切换不改变按钮尺寸）。"""
        font = btn.font()
        font.setBold(True)
        metrics = QFontMetrics(font)
        btn.setMinimumWidth(metrics.horizontalAdvance(text) + 24)

    def _apply_category_button_style(self, category_id: str, btn: QPushButton) -> None:
        """根据展开态应用分类按钮样式。"""
        if category_id == self._expanded_category_id:
            btn.setStyleSheet(_CATEGORY_EXPANDED_STYLE)
        else:
            btn.setStyleSheet(_CATEGORY_NORMAL_STYLE)

    def _update_clear_button_state(self) -> None:
        """清除按钮在无已选/反选时禁用。"""
        self._clear_button.setEnabled(
            len(self._selected_tag_ids) > 0 or bool(self._excluded_tag_ids)
        )

    def _refresh_category_badges(self) -> None:
        """刷新所有分类按钮的徽标（已选数）。"""
        # 按分类统计已选数
        counts: dict[str, int] = {}
        for category, tags in self._categories:
            count = sum(1 for t in tags if t.id in self._selected_tag_ids)
            counts[category.id] = count

        for cid, btn in self._category_buttons.items():
            count = counts.get(cid, 0)
            # 找到分类名（去掉旧徽标）
            category_name = next(
                (c.name for c, _ in self._categories if c.id == cid),
                btn.text(),
            )
            if count > 0:
                badge = ui.TAG_FILTER_CATEGORY_BADGE.format(count=count)
                btn.setText(f"{category_name}{badge}")
            else:
                btn.setText(category_name)

    def _on_clear_clicked(self) -> None:
        """清除全部按钮：清空已选并发射信号。"""
        self.clear_selection()

    def _update_visibility_state(self) -> None:
        """无分类时隐藏控件本体。"""
        self.setVisible(self.has_categories())
