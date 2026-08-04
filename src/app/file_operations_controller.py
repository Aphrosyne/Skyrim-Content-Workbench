"""文件操作编排控制器（MainWindow 第二轮拆分，TD-M21 阶段 6）。

封装文件操作编排：新建文件夹 / 重命名 / 删除 / 粘贴 / 移动到（含冲突解决）/
撤销，以及对应快捷键 handler。MainWindow 保留同名薄委托与测试接口。

约束：
- UI 层不直接调用文件写 API，全部经 FileOperationService。
- 重命名弹窗与最近移动目标经 ``host`` 运行时读取，兼容既有测试对
  ``window._show_rename_dialog`` / ``window._recent_move_targets`` 的替换。
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox, QStatusBar, QTreeView, QWidget

from app import ui_constants as ui
from app.file_list_model import FileListModel
from app.folder_tree_model import FolderTreeModel
from app.transaction_scope import TransactionScope
from application.clipboard_service import ClipboardService
from application.errors import (
    ConflictError,
    CrossDriveError,
    FileOperationError,
    SelfSubdirectoryError,
    SourceNotFoundError,
)
from application.file_operation_service import FileOperationService
from application.folder_tree_service import FolderTreeService
from application.managed_root_service import ManagedRootService
from application.undo_service import UndoService
from domain.models import FileEntry


class FileOperationsController(QObject):
    """文件操作编排控制器（新建/重命名/删除/粘贴/移动到/撤销）。"""

    def __init__(
        self,
        file_operation_service: FileOperationService | None,
        clipboard_service: ClipboardService | None,
        undo_service: UndoService | None,
        content_list_model: FileListModel,
        tree_view: QTreeView,
        tree_model: FolderTreeModel,
        tree_service: FolderTreeService,
        managed_root_service: ManagedRootService,
        assembly_panel,
        transaction_scope: TransactionScope,
        status_bar: QStatusBar,
        *,
        refresh_tree: Callable[[], None],
        refresh_middle_current: Callable[[], None],
        refresh_middle: Callable[[str], None],
        refresh_assembly_if_affected: Callable[..., None],
        get_selected_entries: Callable[[], list[FileEntry]],
        current_displayed_dir: Callable[[], str | None],
        handle_error: Callable[[Exception, str], None],
        dialog_parent: QWidget,
        host: object,
        parent: QObject | None = None,
    ) -> None:
        """初始化文件操作控制器。

        Args:
            host: 运行时状态宿主（MainWindow）——重命名弹窗与最近移动目标
            经 ``host`` 读取，兼容测试实例替换。
        """
        super().__init__(parent)
        self._file_operation_service = file_operation_service
        self._clipboard_service = clipboard_service
        self._undo_service = undo_service
        self._content_list_model = content_list_model
        self._tree_view = tree_view
        self._tree_model = tree_model
        self._tree_service = tree_service
        self._service = managed_root_service
        self._assembly_panel = assembly_panel
        self._tx = transaction_scope
        self._status_bar = status_bar
        self._refresh_tree = refresh_tree
        self._refresh_middle_current = refresh_middle_current
        self._refresh_middle = refresh_middle
        self._refresh_assembly_if_affected = refresh_assembly_if_affected
        self._get_selected_entries = get_selected_entries
        self._current_displayed_dir = current_displayed_dir
        self._handle_error = handle_error
        self._dialog_parent = dialog_parent
        self._host = host

    # === 新建文件夹 ===

    def new_folder_for_entry(self, entry: FileEntry) -> None:
        """右键条目 → 新建文件夹（基于该条目所在父目录）。"""
        # 父目录：文件所在目录或文件夹本身的父目录
        target_dir = str(Path(entry.path).parent)
        self.new_folder_in_dir(target_dir)

    def new_folder_in_dir(self, dir_path: str) -> None:
        """在指定目录下新建文件夹。"""
        if self._file_operation_service is None:
            return
        # 弹出输入对话框，默认填"新建文件夹"
        name, ok = QInputDialog.getText(
            self._dialog_parent,
            ui.MENU_NEW_FOLDER_DIALOG_TITLE,
            ui.MENU_NEW_FOLDER_DIALOG_LABEL,
            text=ui.MENU_NEW_FOLDER_DEFAULT_NAME,
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        try:
            new_path = Path(dir_path) / name
            self._file_operation_service.new_folder(new_path)
            self._tx.commit()
            self._refresh_tree()
            # _refresh_tree 会清空列表，必须用保存的 dir_path 直接刷新
            # （_refresh_content_list_for_current_mode 依赖 selection 可能失效）
            self.refresh_content_list_after_file_op(dir_path)
            # 修复1：若新建文件夹发生在钉住的装配面板文件夹内，同步刷新装配面板
            self._refresh_assembly_if_affected(dir_path)
            self._status_bar.showMessage(ui.MENU_NEW_FOLDER_SUCCESS.format(name=name), 3000)
        except Exception as e:  # noqa: BLE001
            self._handle_error(e, ui.MENU_OPERATION_FAILED.format(error=str(e)))

    # === 重命名 ===

    def rename_entry_core(self, entry: FileEntry, refresh_middle: bool = True) -> bool:
        """重命名核心逻辑。

        UX 重构 Phase 1 Task 2 修复1：抽取核心逻辑，装配面板调用时
        refresh_middle=False，避免中栏被刷新到文件父目录（错误进入文件夹）。

        修复5（系统性修复）：_refresh_tree 会清空中栏列表（content_list_model.refresh([])），
        且 restore_expanded_paths 可能在 _refresh_tree 内部已恢复目录树选中节点。
        若选中节点已被恢复，再调用 setCurrentIndex 设置相同节点不会触发
        selectionChanged 信号，导致 _on_tree_selection_changed 不执行，
        中栏内容保持空白。

        解决方案：_refresh_tree 后统一通过 restore_middle_after_tree_refresh
        恢复目录树选中 + 直接刷新中栏内容（不依赖 selectionChanged 信号）。

        Args:
            entry: 待重命名的条目。
            refresh_middle: True 刷新中栏到文件父目录；False 保持中栏原显示目录。

        Returns:
            True 表示执行了重命名；False 表示用户取消或无变化。
        """
        if self._file_operation_service is None:
            return False
        old_path = Path(entry.path)
        old_name = old_path.name
        # 保存父目录路径：rename 后 _refresh_tree 会清空列表，需用此路径直接刷新
        dir_path = str(old_path.parent)
        # 修复5：refresh_middle=False 时记录原显示目录，_refresh_tree 后恢复
        # （_refresh_tree 会清空中栏，不恢复会导致中栏空白）
        preserved_display_dir = self._current_displayed_dir() if not refresh_middle else None
        name, ok = self._host._show_rename_dialog(old_name)
        if not ok or not name:
            return False
        # 同名跳过（无变化）
        if name == old_name:
            return False
        try:
            self._file_operation_service.rename(old_path, name)
            self._tx.commit()
            self._refresh_tree()
            # 修复5：统一恢复中栏显示（不依赖 selectionChanged 信号）
            if refresh_middle:
                self.restore_middle_after_tree_refresh(dir_path)
            elif preserved_display_dir is not None:
                self.restore_middle_after_tree_refresh(preserved_display_dir)
            self._status_bar.showMessage(ui.MENU_RENAME_SUCCESS.format(name=name), 3000)
            return True
        except Exception as e:  # noqa: BLE001
            self._handle_error(e, ui.MENU_OPERATION_FAILED.format(error=str(e)))
            return False

    def rename_entry(self, entry: FileEntry) -> None:
        """右键条目 → 重命名（中栏，刷新中栏到父目录）。"""
        self.rename_entry_core(entry, refresh_middle=True)

    def restore_middle_after_tree_refresh(self, dir_path: str) -> None:
        """_refresh_tree 后恢复中栏显示：恢复目录树选中 + 直接刷新中栏内容。

        _refresh_tree 会：
        1. reset tree model（beginResetModel/endResetModel）
        2. restore_expanded_paths 尝试恢复选中（仅在父节点已展开时成功）
        3. 清空 content_list_model

        问题：若步骤 2 已恢复选中节点，再 setCurrentIndex 相同节点不会触发
        selectionChanged 信号，_on_tree_selection_changed 不执行，中栏空白。
        若步骤 2 未恢复选中（父节点未展开），setCurrentIndex 新节点会触发信号，
        但信号处理内的 _refresh_content_list 依赖 selectionModel，时序不可控。

        解决方案：始终通过 find_index_by_path 恢复目录树选中（处理父节点未展开情况），
        然后直接调用 _refresh_content_list 刷新中栏（不依赖 selectionChanged 信号）。
        """
        # 恢复目录树选中节点（find_index_by_path 会 fetchMore 加载未展开的子节点）
        target_idx = self._tree_model.find_index_by_path(self._tree_view, dir_path)
        if target_idx.isValid():
            self._tree_view.setCurrentIndex(target_idx)
        # 直接刷新中栏内容（_refresh_tree 已清空列表，
        # 不能依赖 setCurrentIndex 触发 selectionChanged，因为选中可能未变）
        self._refresh_middle(dir_path)
        # 修复1：若受影响目录与装配面板钉住文件夹相同，同步刷新装配面板
        self._refresh_assembly_if_affected(dir_path)

    def refresh_content_list_after_file_op(self, dir_path: str | None) -> None:
        """文件操作后刷新中栏（Stage 5 Task 3a）。"""
        if dir_path is None:
            return
        self._refresh_middle(dir_path)

    # === 删除 ===

    def delete_entries(self, entries: list[FileEntry]) -> None:
        """右键条目 → 删除（移至回收站）。"""
        if self._file_operation_service is None:
            return
        # 确认对话框
        n = len(entries)
        if n == 1:
            text = ui.MENU_DELETE_CONFIRM_TEXT_SINGLE
        else:
            text = ui.MENU_DELETE_CONFIRM_TEXT_MULTI.format(n=n)
        # 操作合理性3（2026-08-02）：删除确认时提示文件夹内部条目数（顶层，快速）
        dir_file_count = 0
        for e in entries:
            if e.is_dir:
                with contextlib.suppress(OSError):
                    dir_file_count += sum(1 for _ in Path(e.path).iterdir())
        if dir_file_count > 0:
            text = text.replace(
                "此操作不可撤销。",
                ui.MENU_DELETE_CONFIRM_FOLDER_FILES.format(n=dir_file_count),
            )
        reply = QMessageBox.question(
            self._dialog_parent,
            ui.MENU_DELETE_CONFIRM_TITLE,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        # 批量删除
        paths = [Path(e.path) for e in entries]
        # 保存删除条目所在父目录路径（取第一个条目的父目录）：
        # _refresh_tree 后 selection 可能失效，用此路径直接刷新列表
        dir_path = str(paths[0].parent) if paths else None
        try:
            # delete_to_recycle_bin 返回 (histories, sync_errors)：
            # - SHFileOperation 失败时抛 FileOperationError（文件未删除，可 rollback）
            # - 同步失败时返回 sync_errors（文件已删除，需 commit 保留历史）
            histories, sync_errors = self._file_operation_service.delete_to_recycle_bin(paths)
            self._tx.commit()
            self._refresh_tree()
            self.refresh_content_list_after_file_op(dir_path)
            # 修复1：若删除发生在钉住的装配面板文件夹内，同步刷新装配面板
            if dir_path is not None:
                self._refresh_assembly_if_affected(dir_path)
            ok_count = len(histories)
            fail_count = n - ok_count
            if sync_errors:
                # 同步有错误但文件已删除：弹窗提示部分成功 + 错误明细
                QMessageBox.information(
                    self._dialog_parent,
                    ui.MENU_DELETE_CONFIRM_TITLE,
                    ui.MENU_DELETE_PARTIAL.format(ok=ok_count, fail=fail_count),
                )
            elif fail_count == 0:
                self._status_bar.showMessage(ui.MENU_DELETE_SUCCESS.format(n=ok_count), 3000)
            else:
                QMessageBox.information(
                    self._dialog_parent,
                    ui.MENU_DELETE_CONFIRM_TITLE,
                    ui.MENU_DELETE_PARTIAL.format(ok=ok_count, fail=fail_count),
                )
        except Exception as e:  # noqa: BLE001
            self._handle_error(e, ui.MENU_OPERATION_FAILED.format(error=str(e)))

    # === 复制 / 剪切 / 粘贴（应用内剪贴板） ===

    def on_shortcut_copy(self) -> None:
        """Ctrl+C：复制中栏选中条目到应用内剪贴板。"""
        if self._clipboard_service is None:
            return
        entries = self._get_selected_entries()
        if not entries:
            self._status_bar.showMessage(ui.SHORTCUT_NO_SELECTION, 2000)
            return
        paths = [e.path for e in entries]
        self._clipboard_service.set_copy(paths)
        # 清除之前的剪切高亮
        self._content_list_model.set_cut_paths(set())
        self._status_bar.showMessage(ui.SHORTCUT_COPIED.format(n=len(paths)), 3000)

    def on_shortcut_cut(self) -> None:
        """Ctrl+X：剪切中栏选中条目到应用内剪贴板。"""
        if self._clipboard_service is None:
            return
        entries = self._get_selected_entries()
        if not entries:
            self._status_bar.showMessage(ui.SHORTCUT_NO_SELECTION, 2000)
            return
        paths = [e.path for e in entries]
        self._clipboard_service.set_cut(paths)
        # 更新剪切高亮（Q12=A 50% 透明度）
        self._content_list_model.set_cut_paths(set(paths))
        self._status_bar.showMessage(ui.SHORTCUT_CUT.format(n=len(paths)), 3000)

    def on_shortcut_paste(self) -> None:
        """Ctrl+V：粘贴到中栏当前目录。"""
        if self._clipboard_service is None or self._file_operation_service is None:
            return
        dst_dir = self._current_displayed_dir()
        if dst_dir is None:
            return
        self.perform_paste(Path(dst_dir))

    def on_shortcut_copy_tree(self) -> None:
        """Ctrl+C：复制目录树选中节点到应用内剪贴板。"""
        if self._clipboard_service is None:
            return
        node = self._host._get_selected_tree_node()
        if node is None:
            self._status_bar.showMessage(ui.SHORTCUT_NO_SELECTION, 2000)
            return
        self._clipboard_service.set_copy([node.real_path])
        self._content_list_model.set_cut_paths(set())
        self._status_bar.showMessage(ui.SHORTCUT_COPIED.format(n=1), 3000)

    def on_shortcut_cut_tree(self) -> None:
        """Ctrl+X：剪切目录树选中节点到应用内剪贴板。"""
        if self._clipboard_service is None:
            return
        node = self._host._get_selected_tree_node()
        if node is None:
            self._status_bar.showMessage(ui.SHORTCUT_NO_SELECTION, 2000)
            return
        self._clipboard_service.set_cut([node.real_path])
        self._content_list_model.set_cut_paths({node.real_path})
        self._status_bar.showMessage(ui.SHORTCUT_CUT.format(n=1), 3000)

    def on_shortcut_paste_tree(self) -> None:
        """Ctrl+V：粘贴到目录树选中节点。"""
        if self._clipboard_service is None or self._file_operation_service is None:
            return
        node = self._host._get_selected_tree_node()
        if node is None:
            self._status_bar.showMessage(ui.SHORTCUT_NO_SELECTION, 2000)
            return
        self.perform_paste(Path(node.real_path))

    def perform_paste(self, dst_dir: Path) -> None:
        """执行粘贴操作（共享逻辑，供中栏/目录树 Ctrl+V 调用）。

        流程：
        1. 检查剪贴板是否为空
        2. 跨盘剪切检测（Q7=B 拒绝）
        3. 扫描冲突（ConflictResolutionService）
        4. 若有冲突，弹出 ConflictResolutionDialog（Q3=C 用户选择覆盖/跳过/重命名）
        5. 按 ResolvedAction 执行 copy/move，收集成功与失败
        6. 刷新 UI + 状态栏提示
        """
        from application.conflict_resolution_service import (  # noqa: PLC0415
            ConflictResolutionService,
            has_conflict,
            has_cross_drive_cut,
        )

        entry = self._clipboard_service.get()
        if entry is None or not entry.paths:
            self._status_bar.showMessage(ui.SHORTCUT_PASTE_EMPTY, 2000)
            return

        src_paths = [Path(p) for p in entry.paths]
        operation = entry.operation  # 'copy' or 'cut'

        # 跨盘剪切检测（Q7=B）
        conflict_service = ConflictResolutionService()
        conflicts = conflict_service.scan_conflicts(src_paths, dst_dir, operation)
        if operation == "cut" and has_cross_drive_cut(conflicts):
            QMessageBox.information(
                self._dialog_parent,
                ui.CONFLICT_DIALOG_TITLE,
                ui.SHORTCUT_PASTE_CROSS_DRIVE_CUT,
            )
            return

        # 冲突解决（Q3=C）
        if has_conflict(conflicts):
            from app.conflict_resolution_dialog import ConflictResolutionDialog  # noqa: PLC0415

            dialog = ConflictResolutionDialog(conflicts, self._dialog_parent)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return  # 用户取消
            decisions = dialog.decisions()
        else:
            # 无冲突，全部用默认目标路径
            decisions = ["overwrite"] * len(conflicts)

        actions = conflict_service.resolve(conflicts, decisions)

        # 执行 copy/move
        ok_count = 0
        fail_count = 0
        errors: list[str] = []
        for action in actions:
            if action.skipped:
                continue
            try:
                if operation == "copy":
                    self._file_operation_service.copy(
                        action.src, action.dst, overwrite=action.overwrite
                    )
                else:  # cut
                    self._file_operation_service.move(
                        action.src, action.dst, overwrite=action.overwrite
                    )
                ok_count += 1
            except SourceNotFoundError:
                fail_count += 1
                errors.append(ui.SHORTCUT_PASTE_SRC_NOT_FOUND.format(name=action.src.name))
            except (ConflictError, CrossDriveError, SelfSubdirectoryError, FileOperationError) as e:
                fail_count += 1
                errors.append(ui.SHORTCUT_PASTE_FAILED.format(error=str(e)))

        # cut 模式粘贴后清空剪贴板 + 清除剪切高亮
        if operation == "cut":
            self._clipboard_service.clear()
            self._content_list_model.set_cut_paths(set())

        # 提交事务 + 刷新 UI
        self._tx.commit()
        self._refresh_tree()
        self._refresh_middle_current()
        # 修复1：若粘贴目标目录与钉住的装配面板文件夹相同，同步刷新装配面板。
        # 若为 cut 操作，源目录内容也变化，需一并检查。
        affected_dirs: list[Path] = [dst_dir]
        if operation == "cut":
            affected_dirs.extend(Path(p).parent for p in entry.paths if p)
        self._refresh_assembly_if_affected(*affected_dirs)

        # 状态栏提示
        if fail_count == 0:
            self._status_bar.showMessage(
                ui.SHORTCUT_PASTED.format(n=ok_count, dir_name=dst_dir.name), 3000
            )
        else:
            QMessageBox.information(
                self._dialog_parent,
                ui.CONFLICT_DIALOG_TITLE,
                ui.SHORTCUT_PASTE_PARTIAL.format(ok=ok_count, fail=fail_count)
                + "\n\n"
                + "\n".join(errors[:5]),
            )

    # === 删除（目录树） ===

    def on_shortcut_delete_tree(self) -> None:
        """Delete：删除目录树选中节点。"""
        if self._file_operation_service is None:
            return
        node = self._host._get_selected_tree_node()
        if node is None:
            self._status_bar.showMessage(ui.SHORTCUT_NO_SELECTION, 2000)
            return
        entry = FileEntry(
            path=node.real_path,
            name=Path(node.real_path).name,
            is_dir=True,
            size=0,
            modified_at="1970-01-01T00:00:00Z",
            content_unit=None,
        )
        self.delete_entries([entry])

    # === 快捷键 handler（重命名/删除入口） ===

    def on_shortcut_rename_content(self) -> None:
        """F2：重命名中栏选中条目（Q1=A：多选取第一个）。"""
        if self._file_operation_service is None:
            return
        entries = self._get_selected_entries()
        if not entries:
            self._status_bar.showMessage(ui.SHORTCUT_NO_SELECTION, 2000)
            return
        # Q1=A：多选取第一个选中条目
        self.rename_entry(entries[0])

    def on_shortcut_rename_tree(self) -> None:
        """F2：重命名目录树选中节点（用户补充：目录树也需要重命名快捷键）。

        复用 rename_entry 逻辑，从目录树节点构造 FileEntry。
        """
        if self._file_operation_service is None:
            return
        # 获取目录树选中节点
        sm = self._tree_view.selectionModel()
        if sm is None:
            return
        indexes = sm.selectedIndexes()
        if not indexes:
            self._status_bar.showMessage(ui.SHORTCUT_NO_SELECTION, 2000)
            return
        node = self._tree_model.node_at(indexes[0])
        if node is None:
            return
        # 构造 FileEntry 并复用 rename_entry
        entry = FileEntry(
            path=node.real_path,
            name=Path(node.real_path).name,
            is_dir=True,
            size=0,
            modified_at="1970-01-01T00:00:00Z",
            content_unit=None,
        )
        self.rename_entry(entry)

    def on_shortcut_delete(self) -> None:
        """Delete：删除中栏选中条目。"""
        if self._file_operation_service is None:
            return
        entries = self._get_selected_entries()
        if not entries:
            self._status_bar.showMessage(ui.SHORTCUT_NO_SELECTION, 2000)
            return
        self.delete_entries(entries)

    # === 撤销 ===

    def on_shortcut_undo(self) -> None:
        """Ctrl+Z：撤销最近一条可撤销操作。

        Q2=A：二次确认弹窗。
        Q3=B：跳过 delete 和已撤销的记录，取第一条可撤销且未撤销的。
        """
        if self._undo_service is None:
            return

        # Q3=B：取 list_recent 中第一条 can_undo=True 且 undone_at IS NULL 的记录
        try:
            histories = self._undo_service.list_recent(limit=100)
        except Exception as e:  # noqa: BLE001
            self._status_bar.showMessage(ui.SHORTCUT_UNDO_FAILED.format(error=str(e)), 3000)
            return

        target = None
        for h in histories:
            if h.can_undo and h.undone_at is None and h.operation_type != "undo":
                target = h
                break

        if target is None:
            self._status_bar.showMessage(ui.SHORTCUT_NO_UNDOABLE, 2000)
            return

        # Q2=A：二次确认弹窗
        from app.operation_history_dialog import _format_history_description  # noqa: PLC0415

        desc = _format_history_description(target, self._service)
        reply = QMessageBox.question(
            self._dialog_parent,
            ui.SHORTCUT_UNDO_CONFIRM_TITLE,
            ui.SHORTCUT_UNDO_CONFIRM_TEXT.format(desc=desc),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # 执行撤销
        from application.errors import (  # noqa: PLC0415
            UndoAlreadyUndoneError,
            UndoNotAllowedError,
            UndoSafetyError,
        )

        try:
            self._undo_service.undo(target)
            self._tx.commit()
            self._refresh_tree()
            self._refresh_middle_current()
            self._status_bar.showMessage(ui.SHORTCUT_UNDO_SUCCESS.format(desc=desc), 3000)
        except UndoNotAllowedError:
            QMessageBox.information(
                self._dialog_parent,
                ui.SHORTCUT_UNDO_CONFIRM_TITLE,
                ui.SHORTCUT_UNDO_NOT_ALLOWED,
            )
        except UndoAlreadyUndoneError:
            self._status_bar.showMessage(ui.SHORTCUT_NO_UNDOABLE, 2000)
        except UndoSafetyError as e:
            QMessageBox.information(
                self._dialog_parent,
                ui.SHORTCUT_UNDO_CONFIRM_TITLE,
                ui.SHORTCUT_UNDO_SAFETY_FAILED.format(reason=e.reason),
            )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self._dialog_parent,
                ui.SHORTCUT_UNDO_CONFIRM_TITLE,
                ui.SHORTCUT_UNDO_FAILED.format(error=str(e)),
            )

    # === 移动到（对话框 + 冲突解决 + 最近目标） ===

    def on_shortcut_move_to(self) -> None:
        """Ctrl+M 中栏：触发移动到对话框。"""
        entries = self._get_selected_entries()
        if not entries:
            self._status_bar.showMessage(ui.SHORTCUT_MOVE_TO_NO_SELECTION, 2000)
            return
        self.on_move_to(entries)

    def on_shortcut_move_to_latest(self) -> None:
        """Ctrl+Q：目录树/中栏选中条目 → 直接移动到最近目标（操作便捷性3）。

        BugFix1（2026-08-02）：目录树获得焦点时优先移动树选中节点（与 Ctrl+M
        的树版本行为对称），否则移动中栏选中条目；移动后统一 _refresh_tree。
        """
        src_paths: list[Path] = []
        if self._tree_view.hasFocus():
            tree_path = self._host._tree_selected_path()
            if tree_path is None:
                self._status_bar.showMessage(ui.SHORTCUT_MOVE_TO_NO_SELECTION, 2000)
                return
            src_paths = [tree_path]
        else:
            entries = self._get_selected_entries()
            if not entries:
                self._status_bar.showMessage(ui.SHORTCUT_MOVE_TO_NO_SELECTION, 2000)
                return
            src_paths = [Path(e.path) for e in entries]
        latest = self._host._recent_move_targets.latest()
        if latest is None:
            self._status_bar.showMessage(ui.SHORTCUT_MOVE_TO_LATEST_NO_TARGET, 3000)
            return
        self.perform_move_to(src_paths, Path(latest))

    def on_shortcut_move_to_tree(self) -> None:
        """Ctrl+M 目录树：触发移动到对话框。"""
        sm = self._tree_view.selectionModel()
        if sm is None:
            return
        indexes = sm.selectedIndexes()
        if not indexes:
            self._status_bar.showMessage(ui.SHORTCUT_MOVE_TO_NO_SELECTION, 2000)
            return
        node = self._tree_model.node_at(indexes[0])
        if node is None:
            return
        self.on_move_to_tree(node)

    def on_move_to(self, entries: list[FileEntry]) -> None:
        """中栏右键「移动到...」入口。"""
        if self._file_operation_service is None:
            return
        if not entries:
            self._status_bar.showMessage(ui.SHORTCUT_MOVE_TO_NO_SELECTION, 2000)
            return
        src_paths = [Path(e.path) for e in entries]
        # Q7=A：默认展开源所在目录的父目录
        default_expand = Path(entries[0].path).parent
        self.open_move_to_dialog(src_paths, default_expand)

    def on_move_to_tree(self, node) -> None:
        """目录树右键「移动到...」入口。"""
        if self._file_operation_service is None:
            return
        src_path = Path(node.real_path)
        # Q7=A：默认展开源所在目录的父目录
        default_expand = src_path.parent
        self.open_move_to_dialog([src_path], default_expand)

    def on_move_to_recent(self, src_paths: list[Path], target: str) -> None:
        """执行移动到最近目标（复用 perform_move_to 完整安全流程）。"""
        self.perform_move_to(src_paths, Path(target))

    def open_move_to_dialog(self, src_paths: list[Path], default_expand: Path | None) -> None:
        """打开「移动到...」对话框并处理结果。"""
        from app.move_to_dialog import MoveToDialog  # noqa: PLC0415

        dialog = MoveToDialog(
            folder_tree_service=self._tree_service,
            src_paths=src_paths,
            default_expand_path=default_expand,
            recent_targets=self._host._recent_move_targets.list_recent(),
            parent=self._dialog_parent,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._status_bar.showMessage(ui.SHORTCUT_MOVE_TO_CANCELLED, 2000)
            return
        target_dir = dialog.selected_target_path()
        if target_dir is None:
            self._status_bar.showMessage(ui.SHORTCUT_MOVE_TO_NO_TARGET, 2000)
            return
        self.perform_move_to(src_paths, target_dir)

    def perform_move_to(
        self,
        src_paths: list[Path],
        target_dir: Path,
        *,
        refresh_assembly: bool = False,
        ok_msg: str = ui.SHORTCUT_MOVE_TO_OK,
        fail_title: str = ui.MOVE_TO_DIALOG_TITLE,
        partial_msg: str = ui.SHORTCUT_MOVE_TO_PARTIAL,
    ) -> None:
        """执行移动到目标目录（复用 ConflictResolutionService 处理冲突）。

        流程与 perform_paste 类似，但 operation 固定为 'cut'（移动），
        且不涉及剪贴板清理。

        UX 重构 Phase 1 Task 4 修复3：拖拽 / 添加到钉住文件夹也走此路径，
        统一冲突解决流程（重命名/跳过/覆盖询问），统一自目录检测（修复4）。
        """
        from application.conflict_resolution_service import (  # noqa: PLC0415
            ConflictResolutionService,
            has_conflict,
            has_cross_drive_cut,
        )

        if self._file_operation_service is None:
            return

        conflict_service = ConflictResolutionService()
        conflicts = conflict_service.scan_conflicts(src_paths, target_dir, operation="cut")

        # 跨盘剪切检测（Q7=B 拒绝）
        if has_cross_drive_cut(conflicts):
            QMessageBox.information(
                self._dialog_parent, fail_title, ui.SHORTCUT_MOVE_TO_CROSS_DRIVE
            )
            return

        # 冲突解决（Q5=A 复用 ConflictResolutionDialog）
        if has_conflict(conflicts):
            from app.conflict_resolution_dialog import ConflictResolutionDialog  # noqa: PLC0415

            conflict_dialog = ConflictResolutionDialog(conflicts, self._dialog_parent)
            if conflict_dialog.exec() != QDialog.DialogCode.Accepted:
                return  # 用户取消
            decisions = conflict_dialog.decisions()
        else:
            # 无冲突，全部用默认目标路径
            decisions = ["overwrite"] * len(conflicts)

        actions = conflict_service.resolve(conflicts, decisions)

        # 执行 move
        ok_count = 0
        fail_count = 0
        errors: list[str] = []
        for action in actions:
            if action.skipped:
                continue
            try:
                self._file_operation_service.move(
                    action.src, action.dst, overwrite=action.overwrite
                )
                ok_count += 1
            except SourceNotFoundError:
                fail_count += 1
                errors.append(ui.SHORTCUT_MOVE_TO_SRC_NOT_FOUND.format(name=action.src.name))
            except SelfSubdirectoryError:
                fail_count += 1
                errors.append(ui.SHORTCUT_MOVE_TO_SELF_SUBDIR)
            except CrossDriveError:
                fail_count += 1
                errors.append(ui.SHORTCUT_MOVE_TO_CROSS_DRIVE)
            except (ConflictError, FileOperationError) as e:
                fail_count += 1
                errors.append(ui.SHORTCUT_MOVE_TO_FAILED.format(error=str(e)))

        # 操作便捷性3：记录最近移动目标（至少 1 项成功）
        if ok_count > 0:
            self._host._recent_move_targets.record(target_dir)

        # 提交事务 + 刷新 UI
        self._tx.commit()
        self._refresh_tree()
        self._refresh_middle_current()
        # 修复1：拖拽到中栏被钉住文件夹后同步刷新装配面板。
        # 检查 target_dir（目标）和各 src 的父目录（源），任一命中钉住文件夹则刷新。
        # refresh_assembly=True（拖入装配面板）时无条件刷新。
        if refresh_assembly:
            if self._assembly_panel is not None:
                self._assembly_panel.refresh_current()
        else:
            affected_dirs = [target_dir] + [Path(p).parent for p in src_paths]
            self._refresh_assembly_if_affected(*affected_dirs)

        # 状态栏提示
        if fail_count == 0:
            self._status_bar.showMessage(
                ok_msg.format(n=ok_count, dir_name=target_dir.name, name=target_dir.name),
                3000,
            )
        else:
            QMessageBox.information(
                self._dialog_parent,
                fail_title,
                partial_msg.format(ok=ok_count, fail=fail_count) + "\n\n" + "\n".join(errors[:5]),
            )
