"""元数据文本格式化与 Elide 纯函数（MainWindow 第二轮拆分，TD-M21 阶段 8）。

从 MainWindow 迁出：
- ``format_metadata_lines``：元数据面板多行文本构造（兼容 metadata_full_text()）。
- ``elide_label_lines`` / ``elide_single_line``：路径行 ElideMiddle 渲染。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel

from app import ui_constants as ui
from app.path_display import make_display_path_from_service
from domain.models import ContentUnit

# 需要对值部分做 ElideMiddle 的路径前缀列表
ELIDE_PATH_PREFIXES = ("路径：", "完整路径：", "目标：")


def format_metadata_lines(unit: ContentUnit, managed_root_service) -> str:
    """构造元数据面板多行文本（原 MainWindow._update_metadata 格式化部分）。

    保留 `metadata_full_text()` 兼容格式：路径 / 类型 / 来源 / 备注 / 创建时间。
    """
    source_url = unit.source_url or ui.METADATA_SOURCE_URL_EMPTY
    notes = unit.notes or ui.METADATA_NOTES_EMPTY

    lines = [
        f"{ui.METADATA_PATH_LABEL}："
        f"{make_display_path_from_service(unit.path, managed_root_service)}",
        f"{ui.METADATA_TYPE_LABEL}：{unit.content_type}",
        f"{ui.METADATA_SOURCE_URL_LABEL}：{source_url}",
        f"{ui.METADATA_NOTES_LABEL}：{notes}",
        f"{ui.METADATA_CREATED_AT_LABEL}：{unit.created_at}",
    ]
    return "\n".join(lines)


def elide_label_lines(label: QLabel, full_text: str) -> None:
    """对 label 的多行文本逐行 Elide，并设置 Tooltip 显示完整文本。"""
    if not full_text:
        label.setText("")
        label.setToolTip("")
        return

    fm = QFontMetrics(label.font())
    # 减去内边距，预留 16px 余量
    max_width = max(50, label.width() - 16)

    lines = full_text.split("\n")
    out: list[str] = []
    for line in lines:
        elided_line = elide_single_line(line, fm, max_width)
        out.append(elided_line)
    label.setText("\n".join(out))
    # Tooltip 显示完整原文（统一路径显示策略：Elide + 悬停查看完整路径）
    label.setToolTip(full_text)


def elide_single_line(line: str, fm: QFontMetrics, max_width: int) -> str:
    """对单行文本应用 Elide。

    识别路径前缀（"路径：" / "完整路径：" / "目标："），对值部分 ElideMiddle；
    其他行若超宽则整体 ElideMiddle。
    """
    for prefix_str in ELIDE_PATH_PREFIXES:
        if prefix_str in line:
            idx = line.index(prefix_str)
            prefix = line[: idx + len(prefix_str)]
            value = line[idx + len(prefix_str) :]
            available = max_width - fm.horizontalAdvance(prefix)
            elided = fm.elidedText(value, Qt.TextElideMode.ElideMiddle, available)
            return prefix + elided
    # 非路径行：若仍超宽，整体 ElideMiddle
    if fm.horizontalAdvance(line) > max_width:
        return fm.elidedText(line, Qt.TextElideMode.ElideMiddle, max_width)
    return line
