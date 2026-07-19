"""标签管理对话框 UI（阶段 4 Task 1）。

spec §10.3：标签管理对话框，提供：
- 标签分类和标签的增删改
- 「导入标签」按钮（QFileDialog 选 JSON → 加载到数据库）
- 「导出标签」按钮（QFileDialog 选保存位置 → 导出为 JSON）

交互方式（用户确认 B1-B4）：
- QTreeWidget 树形展示（分类为顶级节点，标签为子节点）。
- 工具栏按钮触发操作；双击分类/标签进入重命名编辑模式。
- color_hue 通过「改颜色」按钮弹出颜色选择子对话框（QSlider + 色块预览）。
- 增删改立即提交数据库（无"应用"按钮）。

事务边界（用户确认 F6）：
- Dialog 持有 commit_callback 引用，每次操作后立即提交。
- commit_callback 由 MainWindow 注入（与现有 service 一致）。

异常分层：
- service 抛 ApplicationError 子类（DuplicateTagCategoryNameError 等）→
  Dialog 捕获并弹 QMessageBox 提示用户。
- service 抛 RepositoryError / sqlite3.Error 等基础设施异常 →
  Dialog 捕获并弹 QMessageBox 提示（commit_callback 同步 rollback 由 MainWindow 触发）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from application.errors import (
    ApplicationError,
    DuplicateTagCategoryNameError,
    DuplicateTagNameError,
    InvalidTagJsonError,
    TagCategoryNotFoundError,
    TagNotFoundError,
)
from application.tag_service import TagService
from domain.models import Tag, TagCategory

logger = logging.getLogger(__name__)

# QTreeWidgetItem.data 中存储的实体角色
_ROLE_CATEGORY = Qt.UserRole  # TagCategory 实体
_ROLE_TAG = Qt.UserRole + 1  # Tag 实体
_ROLE_IS_CATEGORY = Qt.UserRole + 2  # bool：本节点是分类还是标签


class TagManagerDialog(QDialog):
    """标签管理对话框。

    通过构造注入 TagService + commit_callback。打开时自动加载所有分类与标签。
    增删改操作完成后立即 commit 并刷新 QTreeWidget。
    """

    def __init__(
        self,
        tag_service: TagService,
        commit_callback: Callable[[], None] | None = None,
        rollback_callback: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = tag_service
        self._commit = commit_callback or (lambda: None)
        self._rollback = rollback_callback or (lambda: None)
        self.setWindowTitle(ui.TAG_MANAGER_DIALOG_TITLE)
        self.resize(640, 480)

        self._setup_ui()
        self._refresh_tree()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # 顶部提示
        self._hint_label = QLabel(ui.TAG_MANAGER_ROOT_HINT)
        layout.addWidget(self._hint_label)

        # 工具栏：分类操作
        cat_bar = QHBoxLayout()
        self._add_cat_btn = QPushButton(ui.TAG_MANAGER_ADD_CATEGORY)
        self._add_cat_btn.clicked.connect(self._on_add_category)
        cat_bar.addWidget(self._add_cat_btn)

        self._rename_cat_btn = QPushButton(ui.TAG_MANAGER_RENAME_CATEGORY)
        self._rename_cat_btn.clicked.connect(self._on_rename_category)
        cat_bar.addWidget(self._rename_cat_btn)

        self._change_color_btn = QPushButton(ui.TAG_MANAGER_CHANGE_COLOR)
        self._change_color_btn.clicked.connect(self._on_change_color)
        cat_bar.addWidget(self._change_color_btn)

        self._del_cat_btn = QPushButton(ui.TAG_MANAGER_DELETE_CATEGORY)
        self._del_cat_btn.clicked.connect(self._on_delete_category)
        cat_bar.addWidget(self._del_cat_btn)

        cat_bar.addStretch(1)
        layout.addLayout(cat_bar)

        # 工具栏：标签操作
        tag_bar = QHBoxLayout()
        self._add_tag_btn = QPushButton(ui.TAG_MANAGER_ADD_TAG)
        self._add_tag_btn.clicked.connect(self._on_add_tag)
        tag_bar.addWidget(self._add_tag_btn)

        self._rename_tag_btn = QPushButton(ui.TAG_MANAGER_RENAME_TAG)
        self._rename_tag_btn.clicked.connect(self._on_rename_tag)
        tag_bar.addWidget(self._rename_tag_btn)

        self._move_tag_btn = QPushButton(ui.TAG_MANAGER_MOVE_TAG)
        self._move_tag_btn.clicked.connect(self._on_move_tag)
        tag_bar.addWidget(self._move_tag_btn)

        self._del_tag_btn = QPushButton(ui.TAG_MANAGER_DELETE_TAG)
        self._del_tag_btn.clicked.connect(self._on_delete_tag)
        tag_bar.addWidget(self._del_tag_btn)

        tag_bar.addStretch(1)
        layout.addLayout(tag_bar)

        # 工具栏：JSON 导入导出
        json_bar = QHBoxLayout()
        self._import_append_btn = QPushButton(ui.TAG_MANAGER_IMPORT_APPEND)
        self._import_append_btn.clicked.connect(self._on_import_append_json)
        json_bar.addWidget(self._import_append_btn)

        self._import_overwrite_btn = QPushButton(ui.TAG_MANAGER_IMPORT_OVERWRITE)
        self._import_overwrite_btn.clicked.connect(self._on_import_overwrite_json)
        json_bar.addWidget(self._import_overwrite_btn)

        self._export_btn = QPushButton(ui.TAG_MANAGER_EXPORT)
        self._export_btn.clicked.connect(self._on_export_json)
        json_bar.addWidget(self._export_btn)

        json_bar.addStretch(1)
        layout.addLayout(json_bar)

        # QTreeWidget
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(1)
        self._tree.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)  # 双击重命名由按钮触发
        layout.addWidget(self._tree, stretch=1)

        # 空状态提示
        self._empty_hint = QLabel(ui.TAG_MANAGER_EMPTY_HINT)
        self._empty_hint.setStyleSheet("color: #666;")
        layout.addWidget(self._empty_hint)

        # 关闭按钮
        close_bar = QHBoxLayout()
        close_bar.addStretch(1)
        self._close_btn = QPushButton(ui.TAG_MANAGER_CLOSE)
        self._close_btn.clicked.connect(self.accept)
        close_bar.addWidget(self._close_btn)
        layout.addLayout(close_bar)

    # --- 数据加载 ---

    def _refresh_tree(self) -> None:
        """重新加载 QTreeWidget。"""
        self._tree.clear()
        try:
            categories_with_tags = self._service.list_categories_with_tags()
        except ApplicationError as e:
            self._show_error(ui.TAG_OP_FAILED, str(e))
            return

        for cat, tags in categories_with_tags:
            cat_item = self._make_category_item(cat)
            for tag in tags:
                tag_item = self._make_tag_item(tag)
                cat_item.addChild(tag_item)
            self._tree.addTopLevelItem(cat_item)

        # 更新空状态提示
        has_categories = self._tree.topLevelItemCount() > 0
        self._empty_hint.setVisible(not has_categories)

        # 展开所有分类节点
        for i in range(self._tree.topLevelItemCount()):
            self._tree.topLevelItem(i).setExpanded(True)

    def _make_category_item(self, cat: TagCategory) -> QTreeWidgetItem:
        item = QTreeWidgetItem()
        item.setText(0, f"{cat.name}（H={cat.color_hue}）")
        item.setData(0, _ROLE_CATEGORY, cat)
        item.setData(0, _ROLE_IS_CATEGORY, True)
        # 色块图标
        pixmap_color = QColor.fromHsl(cat.color_hue, 200, 120)
        item.setIcon(0, _color_icon(pixmap_color))
        return item

    def _make_tag_item(self, tag: Tag) -> QTreeWidgetItem:
        item = QTreeWidgetItem()
        item.setText(0, tag.name)
        item.setData(0, _ROLE_TAG, tag)
        item.setData(0, _ROLE_IS_CATEGORY, False)
        return item

    # --- 选中辅助 ---

    def _selected_item(self) -> QTreeWidgetItem | None:
        items = self._tree.selectedItems()
        return items[0] if items else None

    def _selected_category(self) -> TagCategory | None:
        """返回当前选中的分类（含选中标签时返回其父分类）。"""
        item = self._selected_item()
        if item is None:
            return None
        if item.data(0, _ROLE_IS_CATEGORY):
            return item.data(0, _ROLE_CATEGORY)  # type: ignore[no-any-return]
        # 标签节点的父节点是分类
        parent = item.parent()
        if parent is None:
            return None
        return parent.data(0, _ROLE_CATEGORY)  # type: ignore[no-any-return]

    def _selected_tag(self) -> Tag | None:
        item = self._selected_item()
        if item is None:
            return None
        if item.data(0, _ROLE_IS_CATEGORY):
            return None
        return item.data(0, _ROLE_TAG)  # type: ignore[no-any-return]

    # --- 分类操作 ---

    def _on_add_category(self) -> None:
        name, ok = QInputDialog.getText(
            self, ui.TAG_INPUT_CATEGORY_TITLE, ui.TAG_INPUT_CATEGORY_LABEL
        )
        if not ok:
            return
        if not name.strip():
            self._show_error(ui.TAG_MANAGER_EMPTY_NAME_TITLE, ui.TAG_MANAGER_EMPTY_NAME_TEXT)
            return
        # 让用户选颜色（默认 210 蓝色）
        color_hue = self._ask_color_hue(default=210)
        if color_hue is None:
            return
        try:
            self._service.create_category(name, color_hue=color_hue)
            self._commit()
            self._refresh_tree()
        except (DuplicateTagCategoryNameError, InvalidTagJsonError) as e:
            self._rollback()
            self._show_error(ui.TAG_OP_FAILED, str(e))
        except ApplicationError as e:
            self._rollback()
            self._show_error(ui.TAG_OP_FAILED, str(e))

    def _on_rename_category(self) -> None:
        cat = self._selected_category()
        if cat is None:
            self._show_info(ui.TAG_MANAGER_NO_CATEGORY_SELECTED)
            return
        name, ok = QInputDialog.getText(
            self,
            ui.TAG_INPUT_RENAME_CATEGORY_TITLE,
            ui.TAG_INPUT_CATEGORY_LABEL,
            text=cat.name,
        )
        if not ok:
            return
        if not name.strip():
            self._show_error(ui.TAG_MANAGER_EMPTY_NAME_TITLE, ui.TAG_MANAGER_EMPTY_NAME_TEXT)
            return
        try:
            self._service.rename_category(cat.id, name)
            self._commit()
            self._refresh_tree()
        except (DuplicateTagCategoryNameError, InvalidTagJsonError) as e:
            self._rollback()
            self._show_error(ui.TAG_OP_FAILED, str(e))
        except (TagCategoryNotFoundError, ApplicationError) as e:
            self._rollback()
            self._show_error(ui.TAG_OP_FAILED, str(e))

    def _on_change_color(self) -> None:
        cat = self._selected_category()
        if cat is None:
            self._show_info(ui.TAG_MANAGER_NO_CATEGORY_SELECTED)
            return
        new_hue = self._ask_color_hue(default=cat.color_hue)
        if new_hue is None:
            return
        try:
            self._service.update_category_color(cat.id, new_hue)
            self._commit()
            self._refresh_tree()
        except (TagCategoryNotFoundError, ApplicationError) as e:
            self._rollback()
            self._show_error(ui.TAG_OP_FAILED, str(e))

    def _on_delete_category(self) -> None:
        cat = self._selected_category()
        if cat is None:
            self._show_info(ui.TAG_MANAGER_NO_CATEGORY_SELECTED)
            return
        # 询问影响范围
        try:
            tag_count = len(self._service.list_tags_by_category(cat.id))
            link_count = self._service._cut_repo.count_by_category(cat.id)  # noqa: SLF001
        except ApplicationError as e:
            self._show_error(ui.TAG_OP_FAILED, str(e))
            return
        # 确认对话框
        confirm = QMessageBox.question(
            self,
            ui.TAG_CONFIRM_DELETE_CATEGORY_TITLE,
            ui.TAG_CONFIRM_DELETE_CATEGORY_TEXT.format(
                name=cat.name, tag_count=tag_count, link_count=link_count
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self._service.delete_category(cat.id)
            self._commit()
            self._refresh_tree()
        except (TagCategoryNotFoundError, ApplicationError) as e:
            self._rollback()
            self._show_error(ui.TAG_OP_FAILED, str(e))

    # --- 标签操作 ---

    def _on_add_tag(self) -> None:
        cat = self._selected_category()
        if cat is None:
            self._show_info(ui.TAG_MANAGER_NO_CATEGORY_SELECTED)
            return
        name, ok = QInputDialog.getText(self, ui.TAG_INPUT_TAG_TITLE, ui.TAG_INPUT_TAG_LABEL)
        if not ok:
            return
        if not name.strip():
            self._show_error(ui.TAG_MANAGER_EMPTY_NAME_TITLE, ui.TAG_MANAGER_EMPTY_NAME_TEXT)
            return
        try:
            self._service.create_tag(name, cat.id)
            self._commit()
            self._refresh_tree()
        except (DuplicateTagNameError, InvalidTagJsonError, TagCategoryNotFoundError) as e:
            self._rollback()
            self._show_error(ui.TAG_OP_FAILED, str(e))
        except ApplicationError as e:
            self._rollback()
            self._show_error(ui.TAG_OP_FAILED, str(e))

    def _on_rename_tag(self) -> None:
        tag = self._selected_tag()
        if tag is None:
            self._show_info(ui.TAG_MANAGER_NO_TAG_SELECTED)
            return
        name, ok = QInputDialog.getText(
            self, ui.TAG_INPUT_RENAME_TAG_TITLE, ui.TAG_INPUT_TAG_LABEL, text=tag.name
        )
        if not ok:
            return
        if not name.strip():
            self._show_error(ui.TAG_MANAGER_EMPTY_NAME_TITLE, ui.TAG_MANAGER_EMPTY_NAME_TEXT)
            return
        try:
            self._service.rename_tag(tag.id, name)
            self._commit()
            self._refresh_tree()
        except (DuplicateTagNameError, InvalidTagJsonError, TagNotFoundError) as e:
            self._rollback()
            self._show_error(ui.TAG_OP_FAILED, str(e))
        except ApplicationError as e:
            self._rollback()
            self._show_error(ui.TAG_OP_FAILED, str(e))

    def _on_move_tag(self) -> None:
        tag = self._selected_tag()
        if tag is None:
            self._show_info(ui.TAG_MANAGER_NO_TAG_SELECTED)
            return
        # 收集目标分类
        try:
            categories = self._service.list_categories()
        except ApplicationError as e:
            self._show_error(ui.TAG_OP_FAILED, str(e))
            return
        # 弹出选择框
        target_cat = self._ask_target_category(categories, exclude_id=tag.category_id)
        if target_cat is None:
            return
        try:
            self._service.move_tag_to_category(tag.id, target_cat.id)
            self._commit()
            self._refresh_tree()
        except (DuplicateTagNameError, InvalidTagJsonError, TagNotFoundError) as e:
            self._rollback()
            self._show_error(ui.TAG_OP_FAILED, str(e))
        except ApplicationError as e:
            self._rollback()
            self._show_error(ui.TAG_OP_FAILED, str(e))

    def _on_delete_tag(self) -> None:
        tag = self._selected_tag()
        if tag is None:
            self._show_info(ui.TAG_MANAGER_NO_TAG_SELECTED)
            return
        try:
            link_count = self._service._cut_repo.count_by_tag(tag.id)  # noqa: SLF001
        except ApplicationError as e:
            self._show_error(ui.TAG_OP_FAILED, str(e))
            return
        confirm = QMessageBox.question(
            self,
            ui.TAG_CONFIRM_DELETE_TAG_TITLE,
            ui.TAG_CONFIRM_DELETE_TAG_TEXT.format(name=tag.name, link_count=link_count),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self._service.delete_tag(tag.id)
            self._commit()
            self._refresh_tree()
        except (TagNotFoundError, ApplicationError) as e:
            self._rollback()
            self._show_error(ui.TAG_OP_FAILED, str(e))

    # --- JSON 导入导出 ---

    def _on_import_append_json(self) -> None:
        """追加导入：保留现有标签，按合并跳过策略导入 JSON。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            ui.TAG_MANAGER_IMPORT_APPEND,
            "",
            ui.TAG_IMPORT_FILE_FILTER,
        )
        if not file_path:
            return
        try:
            result = self._service.import_from_json(Path(file_path))
            self._commit()
            self._refresh_tree()
            QMessageBox.information(
                self,
                ui.TAG_IMPORT_OK_TITLE,
                ui.TAG_IMPORT_OK_TEXT.format(**result),
            )
        except (InvalidTagJsonError, ApplicationError) as e:
            self._rollback()
            self._show_error(ui.TAG_OP_FAILED, str(e))
        except OSError as e:
            self._show_error(ui.TAG_OP_FAILED, f"无法读取文件：{e}")

    def _on_import_overwrite_json(self) -> None:
        """覆盖导入：先清空现有标签，再导入 JSON。

        清空前弹出确认对话框展示当前规模（分类数 + 标签数）。
        """
        # 统计当前规模
        try:
            categories_with_tags = self._service.list_categories_with_tags()
        except ApplicationError as e:
            self._show_error(ui.TAG_OP_FAILED, str(e))
            return
        category_count = len(categories_with_tags)
        tag_count = sum(len(tags) for _, tags in categories_with_tags)

        # 确认对话框
        confirm = QMessageBox.question(
            self,
            ui.TAG_CONFIRM_OVERWRITE_IMPORT_TITLE,
            ui.TAG_CONFIRM_OVERWRITE_IMPORT_TEXT.format(
                category_count=category_count, tag_count=tag_count
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            ui.TAG_MANAGER_IMPORT_OVERWRITE,
            "",
            ui.TAG_IMPORT_FILE_FILTER,
        )
        if not file_path:
            return
        try:
            result = self._service.overwrite_import_from_json(Path(file_path))
            self._commit()
            self._refresh_tree()
            QMessageBox.information(
                self,
                ui.TAG_IMPORT_OK_TITLE,
                ui.TAG_IMPORT_OK_TEXT.format(**result),
            )
        except (InvalidTagJsonError, ApplicationError) as e:
            self._rollback()
            self._show_error(ui.TAG_OP_FAILED, str(e))
        except OSError as e:
            self._show_error(ui.TAG_OP_FAILED, f"无法读取文件：{e}")

    def _on_export_json(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            ui.TAG_MANAGER_EXPORT,
            "tags.json",
            ui.TAG_EXPORT_FILE_FILTER,
        )
        if not file_path:
            return
        path = Path(file_path)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        try:
            self._service.export_to_json(path)
            QMessageBox.information(
                self, ui.TAG_EXPORT_OK_TITLE, ui.TAG_EXPORT_OK_TEXT.format(path=path)
            )
        except ApplicationError as e:
            self._show_error(ui.TAG_OP_FAILED, str(e))
        except OSError as e:
            self._show_error(ui.TAG_OP_FAILED, f"无法写入文件：{e}")

    # --- 辅助对话框 ---

    def _ask_color_hue(self, default: int = 210) -> int | None:
        """弹出颜色选择对话框，返回 color_hue（0-360）。取消返回 None。"""
        # 先用 QColorDialog 预览
        initial = QColor.fromHsl(default, 200, 120)
        color = QColorDialog.getColor(
            initial,
            self,
            ui.TAG_COLOR_DIALOG_TITLE,
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if not color.isValid():
            return None
        return color.hslHue() % 360

    def _ask_target_category(
        self, categories: list[TagCategory], exclude_id: str | None = None
    ) -> TagCategory | None:
        """弹出对话框选择目标分类。"""
        # 用 QInputDialog 选择
        choices = [c for c in categories if c.id != exclude_id]
        if not choices:
            self._show_info("没有可选的目标分类。")
            return None
        names = [c.name for c in choices]
        name, ok = QInputDialog.getItem(
            self,
            ui.TAG_INPUT_MOVE_TAG_TITLE,
            ui.TAG_INPUT_MOVE_TAG_LABEL,
            names,
            0,
            False,  # 不可编辑
        )
        if not ok or not name:
            return None
        for c in choices:
            if c.name == name:
                return c
        return None

    # --- 错误提示 ---

    def _show_error(self, title: str, text: str) -> None:
        QMessageBox.critical(self, title, text)

    def _show_info(self, text: str) -> None:
        QMessageBox.information(self, ui.TAG_OP_OK, text)


def _color_icon(color: QColor) -> QPixmap:
    """生成 16x16 色块图标。"""
    pixmap = QPixmap(16, 16)
    pixmap.fill(color)
    return pixmap
