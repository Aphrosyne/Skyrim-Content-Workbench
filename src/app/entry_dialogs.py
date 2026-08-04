"""条目操作对话框（MainWindow 第二轮拆分，TD-M21 阶段 8）。

从 MainWindow 迁出两个独立对话框 view：
- ``show_rename_dialog``：重命名对话框（预填名称，选中文件名部分）。
- ``show_create_mod_group_dialog``：创建 Mod 组名称对话框。

MainWindow 保留同名薄委托，兼容测试对实例方法（``_show_rename_dialog`` /
``_show_create_mod_group_dialog``）的 monkeypatch 替换。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui


def show_rename_dialog(parent: QWidget, old_name: str) -> tuple[str, bool]:
    """弹出重命名对话框，预填当前名称，选中文件名部分（不含扩展名）。

    UX 重构 Phase 1 Task 2 修复2：避免重命名时误改后缀，
    初始选区忽略扩展名（如 "readme.txt" 只选中 "readme"）。

    Returns:
        (new_name, ok)：new_name 为去空白后的名称；ok 为是否确认。
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle(ui.MENU_RENAME_DIALOG_TITLE)
    layout = QVBoxLayout(dialog)

    label = QLabel(ui.MENU_RENAME_DIALOG_LABEL)
    layout.addWidget(label)

    edit = QLineEdit(old_name)
    layout.addWidget(edit)

    button_box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    button_box.accepted.connect(dialog.accept)
    button_box.rejected.connect(dialog.reject)
    layout.addWidget(button_box)

    # 选中文件名部分（不含扩展名）
    # .gitignore 等以点开头的文件 suffix 为整个名称，此时全选
    old_path = Path(old_name)
    suffix = old_path.suffix
    if suffix and len(suffix) < len(old_name):
        select_len = len(old_name) - len(suffix)
    else:
        select_len = len(old_name)
    if 0 < select_len < len(old_name):
        edit.setSelection(0, select_len)
    else:
        edit.selectAll()
    edit.setFocus()

    # UI合理性6（2026-08-02）：重命名弹窗适当调宽（约为默认宽度的 3/2）
    dialog.adjustSize()
    hint = dialog.sizeHint()
    dialog.resize(int(hint.width() * 1.5), hint.height())

    if dialog.exec() == QDialog.DialogCode.Accepted:
        return edit.text().strip(), True
    return "", False


def show_create_mod_group_dialog(parent: QWidget, pure_name: str, full_name: str) -> str | None:
    """弹出创建 Mod 组对话框，返回用户选择的名称；取消返回 None。

    下拉框直接以名称作为显示文本（不带"纯 Mod 名："等前缀），
    避免前缀被写入最终名称。若 pure_name == full_name 只添加一项。
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle(ui.CREATE_MOD_GROUP_DIALOG_TITLE)
    layout = QVBoxLayout(dialog)

    label = QLabel(ui.CREATE_MOD_GROUP_DIALOG_LABEL)
    layout.addWidget(label)

    combo = QComboBox()
    combo.setEditable(True)
    # 显示文本直接用名称，data 也存名称；选择后编辑框即为纯名称
    combo.addItem(pure_name, pure_name)
    if full_name != pure_name:
        combo.addItem(full_name, full_name)
    combo.setCurrentIndex(0)
    # 设置编辑框初始文本为纯 Mod 名
    combo.setEditText(pure_name)
    layout.addWidget(combo)

    button_box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    button_box.accepted.connect(dialog.accept)
    button_box.rejected.connect(dialog.reject)
    layout.addWidget(button_box)

    if dialog.exec() == QDialog.DialogCode.Accepted:
        # 优先返回用户编辑后的文本
        return combo.currentText().strip()
    return None
