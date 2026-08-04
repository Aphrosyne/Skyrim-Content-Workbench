"""视图状态控制器（MainWindow 第二轮拆分，TD-M21 阶段 2）。

封装中栏视图切换（列表/卡片）、缩放、排序控件同步与 QSettings 持久化恢复，
MainWindow 保留同名薄委托与测试访问器（``current_view_index`` /
``card_icon_size`` 等）。
"""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QObject, QSettings, QSize
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QPushButton, QStackedWidget

from app import ui_constants as ui
from app.card_list_model import CardListModel
from app.content_views import _DragDropListView, _RubberBandTableView
from app.file_list_model import (
    SORT_MODIFIED,
    SORT_NAME,
    SORT_SIZE,
    SORT_TYPE,
    FileListModel,
)
from app.main_menu_bar import MainMenuBar

# 视图索引（QStackedWidget）
VIEW_INDEX_LIST = 0
VIEW_INDEX_CARD = 1


class ViewStateController(QObject):
    """视图切换 / 缩放 / 排序同步 / QSettings 恢复控制器。"""

    # 排序键 → 下拉框索引映射（原 MainWindow._SORT_KEY_TO_INDEX）
    _SORT_KEY_TO_INDEX = {
        SORT_NAME: 0,
        SORT_TYPE: 1,
        SORT_SIZE: 2,
        SORT_MODIFIED: 3,
    }

    def __init__(
        self,
        content_stack: QStackedWidget,
        content_view: _RubberBandTableView,
        card_view: _DragDropListView,
        content_list_model: FileListModel,
        card_list_model: CardListModel,
        menu_bar: MainMenuBar,
        view_list_button: QPushButton,
        view_card_button: QPushButton,
        zoom_combo: QComboBox,
        sort_field_combo: QComboBox,
        sort_dir_button: QPushButton,
        qsettings: QSettings,
        parent: QObject | None = None,
    ) -> None:
        """初始化视图状态控制器。

        Args:
            content_stack: 列表/卡片视图容器（QStackedWidget）。
            content_view / card_view: 两个视图实例。
            content_list_model / card_list_model: 两个数据模型（card 委托给 list）。
            menu_bar: 顶部菜单栏（视图选中态同步）。
            view_list_button / view_card_button: 视图切换按钮。
            zoom_combo: 缩放下拉框。
            sort_field_combo / sort_dir_button: 排序控件。
            qsettings: QSettings 持久化（视图模式/缩放）。
        """
        super().__init__(parent)
        self._content_stack = content_stack
        self._content_view = content_view
        self._card_view = card_view
        self._content_list_model = content_list_model
        self._card_list_model = card_list_model
        self._menu_bar = menu_bar
        self._view_list_button = view_list_button
        self._view_card_button = view_card_button
        self._zoom_combo = zoom_combo
        self._sort_field_combo = sort_field_combo
        self._sort_dir_button = sort_dir_button
        self._qsettings = qsettings
        self._current_view_index: int = VIEW_INDEX_LIST  # 默认列表视图
        self._card_icon_size: int = ui.ZOOM_SLIDER_DEFAULT

    # --- 状态读取（MainWindow 镜像属性/测试访问器） ---

    def current_view_index(self) -> int:
        """返回当前活动视图索引（0=列表，1=卡片）。"""
        return self._current_view_index

    def card_icon_size(self) -> int:
        """返回当前卡片图标尺寸。"""
        return self._card_icon_size

    # --- 视图切换 + 缩放 ---

    def switch_view(self, view_index: int) -> None:
        """切换文件列表视图（列表 ↔ 卡片）。

        Q1=A：视图切换按钮组独立一行。
        Q4=A：选中状态跨视图保持（用 entry.path 匹配，行号可能因排序不同而变化）。
        """
        if view_index == self._current_view_index:
            return
        # 记录当前选中条目的 path 集合（从当前活动视图读取）
        selected_paths: set[str] = set()
        current_view = (
            self._card_view if self._current_view_index == VIEW_INDEX_CARD else self._content_view
        )
        current_model = (
            self._card_list_model
            if self._current_view_index == VIEW_INDEX_CARD
            else self._content_list_model
        )
        sm = current_view.selectionModel()
        if sm is not None:
            for idx in sm.selectedRows():
                entry = current_model.entry_at(idx.row())
                if entry is not None:
                    selected_paths.add(entry.path)
        # 切换视图
        self._content_stack.setCurrentIndex(view_index)
        self._current_view_index = view_index
        # 在新视图中恢复选中
        target_view = self._card_view if view_index == VIEW_INDEX_CARD else self._content_view
        target_model = (
            self._card_list_model if view_index == VIEW_INDEX_CARD else self._content_list_model
        )
        target_sm = target_view.selectionModel()
        if target_sm is not None and selected_paths:
            # 清除现有选中
            target_sm.clearSelection()
            # 按 path 重新选中对应行（select 会自动触发 selectionChanged 信号）
            # 注意：QTableView 多列场景必须用 Select | Rows 才能选中整行，
            # 仅 Select 只选中 (row, 0) 单元格，selectedRows() 返回空。
            for row in range(target_model.rowCount()):
                entry = target_model.entry_at(row) if hasattr(target_model, "entry_at") else None
                if entry is not None and entry.path in selected_paths:
                    idx = target_model.index(row, 0)
                    target_sm.select(
                        idx,
                        QItemSelectionModel.SelectionFlag.Select
                        | QItemSelectionModel.SelectionFlag.Rows,
                    )
        # 持久化视图模式（Q1=A）
        view_mode = "card" if view_index == VIEW_INDEX_CARD else "list"
        self._qsettings.setValue(ui.QSETTINGS_KEY_VIEW_MODE, view_mode)
        # UI合理性3：同步菜单栏视图选中态
        self._menu_bar.set_view(view_mode)
        # UI合理性3 验收反馈：菜单切换时同步中栏列表/卡片按钮选中态
        # （按钮自身点击时 Qt 已自动勾选，此处幂等）
        if view_index == VIEW_INDEX_CARD:
            self._view_card_button.setChecked(True)
        else:
            self._view_list_button.setChecked(True)

    def on_zoom_combo_changed(self, index: int) -> None:
        """缩放下拉框变化：应用缩放并持久化。"""
        size = self._zoom_combo.itemData(index)
        if not isinstance(size, int):
            return
        self.apply_zoom(size)

    def apply_zoom(self, value: int) -> None:
        """应用缩放值：调整卡片图标尺寸并持久化。"""
        self._card_icon_size = value
        self._card_view.setIconSize(QSize(value, value))
        # Task 2 验收修复：iconSize 变化时同步 gridSize，保持固定网格
        self._card_view.setGridSize(
            QSize(
                value + ui.CARD_GRID_PADDING_H,
                value + ui.CARD_GRID_PADDING_V,
            )
        )
        self._card_list_model.set_icon_size(value)
        self._card_view.doItemsLayout()
        self._qsettings.setValue(ui.QSETTINGS_KEY_ZOOM, value)

    def restore_state(self) -> None:
        """从 QSettings 恢复缩放值与视图模式（Q1=A）。"""
        zoom = self._qsettings.value(ui.QSETTINGS_KEY_ZOOM, ui.ZOOM_SLIDER_DEFAULT, type=int)
        if zoom in ui.ZOOM_PRESET_SIZES:
            index = ui.ZOOM_PRESET_SIZES.index(zoom)
            self._zoom_combo.setCurrentIndex(index)
            self._card_view.setIconSize(QSize(zoom, zoom))
            # Task 2 验收修复：恢复时同步 gridSize
            self._card_view.setGridSize(
                QSize(
                    zoom + ui.CARD_GRID_PADDING_H,
                    zoom + ui.CARD_GRID_PADDING_V,
                )
            )
            self._card_list_model.set_icon_size(zoom)
            self._card_view.doItemsLayout()
            self._card_icon_size = zoom
        # 恢复视图模式
        view_mode = self._qsettings.value(ui.QSETTINGS_KEY_VIEW_MODE, "list", type=str)
        if view_mode == "card":
            self._view_card_button.setChecked(True)
            self.switch_view(VIEW_INDEX_CARD)
        else:
            self._view_list_button.setChecked(True)
            self.switch_view(VIEW_INDEX_LIST)

    def menu_view_switch(self, mode: str) -> None:
        """UI合理性3：菜单视图切换 → 复用既有 switch_view。"""
        view_index = VIEW_INDEX_CARD if mode == "card" else VIEW_INDEX_LIST
        self.switch_view(view_index)

    def content_view_current(self) -> QAbstractItemView | None:
        """返回当前激活的内容视图（列表或卡片）。"""
        current_widget = self._content_stack.currentWidget()
        if current_widget is self._content_view:
            return self._content_view
        if current_widget is self._card_view:
            return self._card_view
        return None

    # --- 排序同步（Stage 5 Task 2） ---

    def on_content_header_clicked(self, column: int) -> None:
        """文件列表列头点击：切换排序键，同列再点切换升降序。

        阶段 3 Task 2：列头排序。点击不同列切换排序键；点击同列切换升降序。
        Stage 5 Task 2：同步排序下拉框与方向按钮状态。
        """
        key_map = {
            0: SORT_NAME,
            1: SORT_TYPE,
            2: SORT_SIZE,
            3: SORT_MODIFIED,
        }
        new_key = key_map.get(column)
        if new_key is None:
            return
        current_key = self._content_list_model.current_sort_key()
        if new_key == current_key:
            # 同列：翻转升降序
            self._content_list_model.set_sort_key(
                new_key, not self._content_list_model.is_sort_ascending()
            )
        else:
            # 不同列：切换排序键，默认升序
            self._content_list_model.set_sort_key(new_key, True)
        self.sync_sort_controls()

    def on_sort_field_activated(self, combo_index: int) -> None:
        """排序字段下拉框 activated 信号：用户主动点击下拉项时触发。

        Stage 5 Task 2 验收修复（最终版）：仅用 activated 单信号。
        - activated 在用户点击下拉项时触发，程序化 setCurrentIndex 不触发
          （避免 _sync_sort_controls 同步时死循环）
        - “选当前项重新排序”无产品意义，不予支持（currentIndex 不变时
          Qt 不会触发 activated，此场景下排序不变是预期行为）
        - 幂等保护：若 sort_key 与当前一致且方向也未变，set_sort_key 内部
          会提前返回，避免重复 reset model 造成 view 异常
        """
        sort_key = self._sort_field_combo.itemData(combo_index)
        if sort_key is None:
            return
        ascending = self._content_list_model.is_sort_ascending()
        self._content_list_model.set_sort_key(sort_key, ascending)
        self.sync_sort_direction_button(ascending)

    def on_sort_direction_clicked(self) -> None:
        """升降序按钮点击：翻转方向（不依赖 checked 状态，从 model 读取当前方向取反）。"""
        ascending = not self._content_list_model.is_sort_ascending()
        current_key = self._content_list_model.current_sort_key()
        self._content_list_model.set_sort_key(current_key, ascending)
        self.sync_sort_direction_button(ascending)

    def sync_sort_controls(self) -> None:
        """同步排序下拉框与方向按钮到 FileListModel 当前状态。

        Stage 5 Task 2 验收修复（最终版）：activated 不受 blockSignals 影响
        （程序化 setCurrentIndex 本就不触发 activated），blockSignals 仅用于
        阻止 currentIndexChanged——当前已不连接该信号，保留 blockSignals 作为
        防御性措施，避免未来误连接其他信号时死循环。
        """
        current_key = self._content_list_model.current_sort_key()
        ascending = self._content_list_model.is_sort_ascending()
        target_index = self._SORT_KEY_TO_INDEX.get(current_key, 0)
        if self._sort_field_combo.currentIndex() != target_index:
            self._sort_field_combo.blockSignals(True)
            self._sort_field_combo.setCurrentIndex(target_index)
            self._sort_field_combo.blockSignals(False)
        self.sync_sort_direction_button(ascending)

    def sync_sort_direction_button(self, ascending: bool) -> None:
        """同步方向按钮文本与 tooltip（不使用 checked 状态）。"""
        if ascending:
            self._sort_dir_button.setText(ui.SORT_ASC_SYMBOL)
            self._sort_dir_button.setToolTip(ui.SORT_DIRECTION_ASC_TOOLTIP)
        else:
            self._sort_dir_button.setText(ui.SORT_DESC_SYMBOL)
            self._sort_dir_button.setToolTip(ui.SORT_DIRECTION_DESC_TOOLTIP)
