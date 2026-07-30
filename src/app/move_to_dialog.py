"""「移动到……」快捷对话框（Stage 5 Task 5）。

spec §6.1 / §7.2：用户选中文件/文件夹 → 右键或快捷键触发 →
弹出本对话框。内嵌 FolderTreeModel + QTreeView，用户选择目标目录 →
确认 → 由 MainWindow 执行 FileOperationService.move。

UI：
- 顶部提示（含移动条目数量）
- 中间：QTreeView + FolderTreeModel（惰性加载，显示暂存区标记 [S]）
- 底部：选中路径回显 + 确定 / 取消按钮

数据流：
- MainWindow 在弹出前收集 src_paths，传给本 dialog。
- 用户选择目录 + 确定后，dialog.exec() 返回 Accepted。
- MainWindow 调用 dialog.selected_target_path() 获取目标目录 Path，
  再调用 FileOperationService.move 执行移动 + ConflictResolutionService 处理冲突。

设计决策（Q1-Q10 用户确认）：
- Q1=A 多选支持：对话框顶部提示「移动 N 项」
- Q6=B 不提供「新建文件夹」入口
- Q7=A 默认展开源所在目录的父目录并选中
- Q8=A 显示暂存区标记 [S]（FolderTreeModel 自带）
- Q9=A 不需要二次确认弹窗（对话框本身即确认）

约束：
- 选中源自身/子目录时确定按钮禁用（R1）
- 对话框新建独立 FolderTreeModel 实例，不共享主窗口 model（R2）
- 对话框不执行任何文件操作，仅收集用户选择
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui
from app.folder_tree_model import FolderTreeModel
from application.folder_tree_service import FolderTreeService
from infrastructure.path_utils import make_path_key

logger = logging.getLogger(__name__)


class MoveToDialog(QDialog):
    """「移动到……」目录选择对话框。

    通过构造注入 FolderTreeService（只读）+ 源路径列表 + 默认展开路径。
    用户选择后通过 selected_target_path() 获取目标目录。
    """

    def __init__(
        self,
        folder_tree_service: FolderTreeService,
        src_paths: list[Path],
        default_expand_path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._src_paths: list[Path] = list(src_paths)
        self._default_expand_path = default_expand_path
        self._selected_target: Path | None = None

        self.setWindowTitle(ui.MOVE_TO_DIALOG_TITLE)
        self.resize(640, 480)

        # 独立的 FolderTreeModel 实例（R2：不共享主窗口 model）
        self._tree_model = FolderTreeModel(folder_tree_service)
        self._tree_model.refresh()

        self._setup_ui()
        self._default_expand()

    def _setup_ui(self) -> None:
        """构造对话框 UI。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # 顶部提示
        count = len(self._src_paths)
        hint_text = ui.MOVE_TO_DIALOG_HINT.format(n=count)
        self._hint_label = QLabel(hint_text)
        self._hint_label.setWordWrap(True)
        layout.addWidget(self._hint_label)

        # 目录树
        self._tree_view = QTreeView()
        self._tree_view.setHeaderHidden(True)
        self._tree_view.setModel(self._tree_model)
        # 选中变化 → 实时更新确定按钮状态 + 路径回显
        sm = self._tree_view.selectionModel()
        if sm is not None:
            sm.currentChanged.connect(self._on_selection_changed)
        layout.addWidget(self._tree_view, 1)

        # 选中路径回显
        self._path_label = QLabel(ui.MOVE_TO_DIALOG_NO_SELECTION)
        self._path_label.setWordWrap(True)
        self._path_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self._path_label)

        # 按钮栏
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._ok_button = QPushButton(ui.MOVE_TO_DIALOG_OK)
        self._ok_button.setAutoDefault(False)
        self._ok_button.setEnabled(False)  # 初始未选中目标，禁用
        self._ok_button.clicked.connect(self._on_ok_clicked)
        button_row.addWidget(self._ok_button)
        self._cancel_button = QPushButton(ui.MOVE_TO_DIALOG_CANCEL)
        self._cancel_button.setAutoDefault(False)
        self._cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self._cancel_button)
        layout.addLayout(button_row)

    def _default_expand(self) -> None:
        """Q7=A：默认展开源所在目录的父目录并选中。"""
        if self._default_expand_path is None:
            return
        try:
            target_str = str(self._default_expand_path)
            idx = self._tree_model.find_index_by_path(self._tree_view, target_str)
            if idx.isValid():
                self._tree_view.setCurrentIndex(idx)
                # 展开父节点使选中可见
                parent = idx.parent()
                if parent.isValid():
                    self._tree_view.setExpanded(parent, True)
        except Exception:  # noqa: BLE001
            # 默认展开失败不影响对话框使用，用户可手动展开
            logger.debug("默认展开目录树失败", exc_info=True)

    def _on_selection_changed(self, current, _previous) -> None:  # noqa: ANN001 (Qt 签名)
        """选中变化 → 更新路径回显 + 校验源自身/子目录。"""
        if not current.isValid():
            self._selected_target = None
            self._path_label.setText(ui.MOVE_TO_DIALOG_NO_SELECTION)
            self._ok_button.setEnabled(False)
            return

        node = self._tree_model.node_at(current)
        if node is None:
            self._selected_target = None
            self._path_label.setText(ui.MOVE_TO_DIALOG_NO_SELECTION)
            self._ok_button.setEnabled(False)
            return

        target_path = Path(node.real_path)
        self._selected_target = target_path
        self._path_label.setText(ui.MOVE_TO_DIALOG_SELECTED.format(path=str(target_path)))

        # R1：校验源自身/子目录 → 禁用确定按钮
        if self._is_self_or_subdirectory(target_path):
            self._path_label.setText(ui.MOVE_TO_DIALOG_INVALID_TARGET)
            self._ok_button.setEnabled(False)
        else:
            self._ok_button.setEnabled(True)

    def _is_self_or_subdirectory(self, target: Path) -> bool:
        """检查目标是否为任一源的自身或子目录（R1）。

        使用 make_path_key 归一化比较（AGENTS 规则 9）。
        """
        target_key = make_path_key(str(target))
        for src in self._src_paths:
            src_key = make_path_key(str(src))
            if target_key == src_key:
                return True
            # 检查 target 是否在 src 子树内
            # src 为目录时，target = src/sub/... 应被阻止
            # 用尾部加分隔符的方式判断前缀（避免 D:/abc 误匹配 D:/abcd）
            if target_key.startswith(src_key.rstrip("\\/") + "\\") or target_key.startswith(
                src_key.rstrip("\\/") + "/"
            ):
                return True
        return False

    def _on_ok_clicked(self) -> None:
        """确定按钮：校验选中后 accept。"""
        if self._selected_target is None:
            return
        if self._is_self_or_subdirectory(self._selected_target):
            return
        self.accept()

    # --- 公共接口 ---

    def selected_target_path(self) -> Path | None:
        """返回选中的目标目录路径（None 表示未选中或取消）。"""
        return self._selected_target

    def is_ok_button_enabled(self) -> bool:
        """返回确定按钮是否启用（供测试）。"""
        return self._ok_button.isEnabled()

    def click_ok_button(self) -> None:
        """程序化触发「确定」按钮（供测试）。"""
        self._on_ok_clicked()

    def click_cancel_button(self) -> None:
        """程序化触发「取消」按钮（供测试）。"""
        self.reject()

    def select_target_by_path(self, target_path: str) -> bool:
        """程序化按路径选中目标目录（供测试）。

        Returns:
            True 表示找到并选中；False 表示未找到。
        """
        idx = self._tree_model.find_index_by_path(self._tree_view, target_path)
        if not idx.isValid():
            return False
        self._tree_view.setCurrentIndex(idx)
        return True

    def src_count(self) -> int:
        """返回源条目数量（供测试）。"""
        return len(self._src_paths)
