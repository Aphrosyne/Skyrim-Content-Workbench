"""扫描 UI 状态联动（MainWindow 第二轮拆分，TD-M21 阶段 8）。

封装扫描按钮状态 / 状态栏文本 / 扫描完成后目录树与中栏刷新联动
（roadmap 阶段 2 Task 5 验收项 5）。线程生命周期仍由 ScanController 管理。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QPushButton, QTreeView

from app import ui_constants as ui
from app.folder_tree_model import FolderTreeModel
from app.scan_controller import ScanController
from application.scan_service import ScanSummary

# 错误摘要最多展示条数
MAX_ERROR_SUMMARY_LINES = 5


class ScanUiState:
    """扫描按钮/状态栏/刷新联动的 UI 状态机（不含线程生命周期）。"""

    def __init__(
        self,
        scan_button: QPushButton,
        scan_full_button: QPushButton,
        add_button: QPushButton,
        remove_button: QPushButton,
        tree_view: QTreeView,
        tree_model: FolderTreeModel,
        scan_controller: ScanController,
        *,
        selected_root_id: Callable[[], str | None],
        set_status: Callable[[str], None],
        refresh_tree: Callable[[], None],
        refresh_content_list: Callable[[str], None],
        archive_root_provider: Callable[[], str | None] | None = None,
    ) -> None:
        """初始化扫描 UI 状态。"""
        self._scan_button = scan_button
        self._scan_full_button = scan_full_button
        self._add_button = add_button
        self._remove_button = remove_button
        self._tree_view = tree_view
        self._tree_model = tree_model
        self._scan_controller = scan_controller
        self._selected_root_id = selected_root_id
        self._set_status = set_status
        self._refresh_tree = refresh_tree
        self._refresh_content_list = refresh_content_list
        self._archive_root_provider = archive_root_provider

    def on_scan(self, incremental: bool = True) -> None:
        """启动后台扫描。扫描期间禁用扫描入口。"""
        if self._scan_controller.is_scanning():
            return
        root_id = self._selected_root_id()
        if root_id is None:
            self._set_status(ui.ERR_NO_ROOT_SELECTED)
            return

        self.begin()
        # UX 重构 Task 7 Step 2：线程生命周期由 ScanController 管理
        archive_root = self._archive_root_provider() if self._archive_root_provider else None
        self._scan_controller.start_scan(
            root_id, incremental=incremental, archive_root=archive_root
        )

    def begin(self) -> None:
        """扫描开始：禁用扫描入口与根目录操作按钮（UI 状态）。"""
        self._scan_button.setText(ui.SCAN_BUTTON_SCANNING)
        self._scan_button.setEnabled(False)
        self._scan_full_button.setEnabled(False)
        self._add_button.setEnabled(False)
        self._remove_button.setEnabled(False)
        self._set_status(ui.STATUS_SCANNING)

    def end(self) -> None:
        """恢复按钮状态。"""
        self._scan_button.setText(ui.SCAN_BUTTON)
        self._add_button.setEnabled(True)
        has_selection = self._selected_root_id() is not None
        self._scan_button.setEnabled(has_selection)
        self._scan_full_button.setEnabled(has_selection)
        self._remove_button.setEnabled(has_selection)

    def on_started(self) -> None:
        """扫描开始信号 → 状态栏。"""
        self._set_status(ui.STATUS_SCANNING)

    def on_progress(self, text: str) -> None:
        """TD-M13：扫描进度文本 → 状态栏（ScanWorker 当前仅发送"正在扫描…"）。"""
        self._set_status(text)

    def on_finished(self, summary: ScanSummary) -> None:
        """扫描完成：展示摘要、刷新目录树、刷新当前中栏文件列表。"""
        text = ui.format_scan_summary(
            scanned_dirs=summary.scanned_dirs,
            content_units_found=summary.content_units_found,
            skipped_unchanged=summary.skipped_unchanged,
            errors=len(summary.errors),
        )
        if summary.errors:
            lines = [text, ""]
            lines.append(f"错误摘要（前 {MAX_ERROR_SUMMARY_LINES} 条）：")
            for err in summary.errors[:MAX_ERROR_SUMMARY_LINES]:
                lines.append(f"• {err}")
            if len(summary.errors) > MAX_ERROR_SUMMARY_LINES:
                lines.append(f"…（共 {len(summary.errors)} 个错误）")
            text = "\n".join(lines)
        self._set_status(f"{ui.STATUS_SCAN_COMPLETE}\n{text}")
        self.end()
        # 扫描完成 → 刷新目录树
        self._refresh_tree()
        # 扫描完成 → 刷新当前中栏文件列表（扫描联动）
        self.refresh_content_list_after_scan()

    def refresh_content_list_after_scan(self) -> None:
        """扫描完成后刷新中栏文件列表（扫描联动）。

        UX 重构 Phase 1 Task 1：移除模式分支，统一为原 browse 行为。
        若目录树有选中节点，重新读取该目录文件列表；否则无操作。
        """
        sm = self._tree_view.selectionModel()
        indexes = sm.selectedIndexes() if sm is not None else []
        if not indexes:
            return
        node = self._tree_model.node_at(indexes[0])
        if node is not None:
            self._refresh_content_list(node.real_path)

    def on_failed(self, message: str) -> None:
        """扫描失败 → 状态栏 + 恢复按钮状态。"""
        self._set_status(f"{ui.STATUS_SCAN_FAILED}\n{message}")
        self.end()
