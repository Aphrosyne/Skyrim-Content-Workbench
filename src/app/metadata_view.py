"""元数据视图控制器（UX 重构 Task 7 Step 4）。

封装 MetadataPanel 的加载 / 保存提交 / 封面选择编排（TD-M31），
MainWindow 连接 ``saved`` 信号完成中栏刷新。

事务边界：面板不自提交；保存成功由本控制器通过 TransactionScope.commit()
提交，失败通过 rollback() 回滚（M18 修复）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialog, QMessageBox, QWidget

from app import ui_constants as ui
from app.cover_picker_dialog import CoverPickerDialog
from app.metadata_panel import MetadataPanel
from app.transaction_scope import TransactionScope
from application.content_service import ContentService
from domain.models import ContentUnit

logger = logging.getLogger(__name__)


class MetadataView(QObject):
    """元数据面板编排控制器。

    信号：
    - ``saved(object)``：元数据保存成功（事务已提交），参数为更新后的 ContentUnit。
    - ``cover_saved(object)``：封面即时保存成功（操作便捷性6，事务已提交），
      参数为更新后的 ContentUnit。
    """

    saved = Signal(object)  # ContentUnit
    # 封面即时保存成功（操作便捷性6，2026-08-03）：已提交事务
    cover_saved = Signal(object)  # ContentUnit

    def __init__(
        self,
        metadata_panel: MetadataPanel | None,
        content_service: ContentService,
        transaction_scope: TransactionScope,
        dialog_parent: QWidget | None = None,
        parent: QObject | None = None,
    ) -> None:
        """初始化元数据视图控制器。

        Args:
            metadata_panel: 元数据编辑面板（未注入 TagService 时为 None）。
            content_service: 内容单元服务。
            transaction_scope: 事务边界（提交/回滚）。
            dialog_parent: 弹窗父窗口。
            parent: QObject 父对象。
        """
        super().__init__(parent)
        self._panel = metadata_panel
        self._content_service = content_service
        self._tx = transaction_scope
        self._dialog_parent = dialog_parent
        if self._panel is not None:
            self._panel.on_saved.connect(self._on_saved)
            self._panel.on_save_failed.connect(self._on_save_failed)
            self._panel.on_pick_cover_requested.connect(self._on_pick_cover_requested)
            # 操作便捷性6（2026-08-03）：封面即时保存成功 → 转发给 MainWindow 刷新
            self._panel.on_cover_saved.connect(self.cover_saved)

    def load_unit(self, unit: ContentUnit) -> None:
        """加载内容单元到元数据面板（含可见性切换；无面板时为空操作）。"""
        if self._panel is not None:
            self._panel.setVisible(True)
            self._panel.load_unit(unit)

    # --- 内部：面板信号处理 ---

    def _on_saved(self, updated_unit: ContentUnit) -> None:
        """保存成功 → 提交事务 + 通知 MainWindow 刷新。"""
        self._tx.commit()
        self.saved.emit(updated_unit)

    def _on_save_failed(self, _error_message: str) -> None:
        """保存失败 → 回滚事务（M18 修复，避免"部分成功"状态被意外提交）。"""
        self._tx.rollback()

    def _on_pick_cover_requested(self, unit_id: str) -> None:
        """面板请求设置封面 → 弹出 CoverPickerDialog。

        操作便捷性6（2026-08-03）：选定后立即保存（apply_cover），不再等待
        「保存」按钮；提交与中栏刷新由 on_cover_saved → cover_saved 链路完成。
        """
        if self._panel is None:
            return
        try:
            unit = self._content_service.get_by_id(unit_id)
        except Exception:  # noqa: BLE001 - UI 边界需捕获所有异常
            logger.exception("获取内容单元失败：unit_id=%s", unit_id)
            QMessageBox.information(
                self._dialog_parent,
                ui.METADATA_PANEL_SAVE_FAILED,
                "获取内容单元失败。",
            )
            return
        if unit is None:
            QMessageBox.information(
                self._dialog_parent,
                ui.METADATA_PANEL_SAVE_FAILED,
                "内容单元不存在。",
            )
            return

        candidates = self._content_service.list_cover_candidates(unit.path)
        if not candidates:
            QMessageBox.information(
                self._dialog_parent,
                ui.COVER_PICKER_DIALOG_TITLE,
                ui.COVER_PICKER_DIALOG_EMPTY,
            )
            return

        dialog = CoverPickerDialog(
            candidates,
            Path(unit.path),
            current_cover=unit.cover_path,
            parent=self._dialog_parent,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        rel_path = dialog.selected_relative_path()
        if rel_path is None:
            return
        self._panel.apply_cover(rel_path)
