"""全局搜索控制器（MainWindow 第二轮拆分，TD-M21 阶段 3）。

封装搜索框触发 → SearchService 查询 → 非模态 SearchDialog 复用 → 结果跳转
（Stage 5 Task 7）。MainWindow 保留同名薄委托与信号接线。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QAbstractItemView, QDialog, QLineEdit, QMessageBox, QWidget

from app import ui_constants as ui
from application.content_service import ContentService
from application.errors import SearchError
from application.search_service import SearchService
from domain.models import FileEntry

logger = logging.getLogger(__name__)


class SearchController(QObject):
    """全局搜索触发 / 结果跳转控制器。

    状态：``_search_dialog``（非模态对话框实例，复用避免重复弹出）。
    """

    def __init__(
        self,
        search_service: SearchService,
        search_box: QLineEdit,
        content_service: ContentService,
        *,
        navigate_to: Callable[[str], None],
        content_view_current: Callable[[], QAbstractItemView | None],
        dialog_parent: QWidget | None = None,
        parent: QObject | None = None,
    ) -> None:
        """初始化搜索控制器。

        Args:
            search_service: 全局搜索服务。
            search_box: 顶部搜索框（读取查询文本）。
            content_service: 内容单元查询（结果跳转定位）。
            navigate_to: 跳转到目录的回调（委托 NavigationController）。
            content_view_current: 获取当前活动内容视图的回调。
            dialog_parent: 搜索对话框父窗口。
        """
        super().__init__(parent)
        self._search_service = search_service
        self._search_box = search_box
        self._content_service = content_service
        self._navigate_to = navigate_to
        self._content_view_current = content_view_current
        self._dialog_parent = dialog_parent
        # 搜索结果对话框实例（非模态，保持引用避免被 GC）
        self._search_dialog: QDialog | None = None

    def on_triggered(self) -> None:
        """搜索框回车触发（Q1=A）。

        - 空白输入不触发
        - 调用 SearchService.search 获取结果
        - 弹出非模态 SearchDialog（Q3=B）
        - 复用已有对话框实例（避免重复弹出）
        """
        if self._search_service is None:
            return
        query = self._search_box.text().strip()
        if not query:
            return

        try:
            results = self._search_service.search(query)
        except SearchError as e:
            QMessageBox.information(
                self._dialog_parent,
                ui.SEARCH_DIALOG_TITLE,
                ui.SEARCH_DIALOG_ERROR.format(error=str(e)),
            )
            return
        except Exception as e:  # noqa: BLE001 - 兜底，确保 UI 收到友好错误
            logger.exception("搜索发生未预期异常：query=%s", query)
            QMessageBox.information(
                self._dialog_parent,
                ui.SEARCH_DIALOG_TITLE,
                ui.SEARCH_DIALOG_ERROR.format(error=str(e)),
            )
            return

        # 复用对话框实例：若已存在则更新内容，否则新建
        from app.search_dialog import SearchDialog  # noqa: PLC0415

        if self._search_dialog is not None and isinstance(self._search_dialog, SearchDialog):
            # 更新现有对话框内容
            self._search_dialog.update_results(query, results)
        else:
            self._search_dialog = SearchDialog(
                query=query,
                results=results,
                jump_callback=self.on_result_clicked,
                parent=self._dialog_parent,
            )
        # Q3=B 非模态：show() 而非 exec()
        self._search_dialog.show()
        self._search_dialog.raise_()
        self._search_dialog.activateWindow()

    def on_result_clicked(self, unit_id: str) -> None:
        """搜索结果双击跳转回调（Q4=B）。

        - Q4=B：跳转到所在目录 + 选中条目 + 保持对话框打开
        - UX 重构 Phase 1 Task 1：移除模式分支，搜索跳转始终允许。
        """
        if self._content_service is None:
            return

        unit = self._content_service.get_by_id(unit_id)
        if unit is None:
            # 内容单元可能已被删除，提示并刷新搜索结果
            QMessageBox.information(
                self._dialog_parent,
                ui.SEARCH_DIALOG_TITLE,
                ui.SEARCH_DIALOG_EMPTY,
            )
            return

        # 跳转到内容单元所在目录
        parent_dir = str(Path(unit.path).parent)
        self._navigate_to(parent_dir)

        # 延迟选中中栏对应条目（目录刷新后才能匹配）
        # 使用 QTimer.singleShot 给目录树 selection 信号链路留出刷新时间
        from PySide6.QtCore import QTimer  # noqa: PLC0415

        target_path = unit.path

        def _select_in_content_list() -> None:
            """在文件列表中选中对应条目（若可见）。"""
            view = self._content_view_current()
            if view is None:
                return
            model = view.model()
            if model is None:
                return
            # 在 model 中查找 path 匹配的行
            for row in range(model.rowCount()):
                idx = model.index(row, 0)
                data = idx.data(Qt.UserRole)
                if isinstance(data, FileEntry) and data.path == target_path:
                    view.setCurrentIndex(idx)
                    return

        QTimer.singleShot(100, _select_in_content_list)
