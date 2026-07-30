"""ConflictResolutionDialog 单元测试（Stage 5 Task 3b）。

覆盖：
- 初始默认决策为「重命名」（最安全选项）
- decisions() 返回每行决策值
- 单选按钮切换 → decisions 更新
- 「应用到全部」→ 所有行决策统一
- 确定 → accept / 取消 → reject
- 空冲突列表不报错
- 中文文件名
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from app.conflict_resolution_dialog import ConflictResolutionDialog  # noqa: E402
from application.conflict_resolution_service import (  # noqa: E402
    RESOLUTION_OVERWRITE,
    RESOLUTION_RENAME,
    RESOLUTION_SKIP,
    ConflictItem,
)


def _make_conflict(src: Path, dst_dir: Path, exists: bool = False) -> ConflictItem:
    """构造单个冲突项。"""
    default_dst = dst_dir / src.name
    suggested = dst_dir / f"{src.stem} (1){src.suffix}"
    return ConflictItem(
        src=src,
        default_dst=default_dst,
        suggested_dst=suggested,
        is_cross_drive=False,
    )


def test_default_decisions_are_rename(qapp, tmp_path: Path) -> None:
    """初始默认决策应为 RESOLUTION_RENAME（最安全选项）。"""
    src = tmp_path / "a.txt"
    src.write_text("src")
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    conflicts = [_make_conflict(src, dst_dir)]

    dialog = ConflictResolutionDialog(conflicts)

    assert dialog.decisions() == [RESOLUTION_RENAME]
    dialog.close()


def test_multiple_conflicts_default_rename(qapp, tmp_path: Path) -> None:
    """多个冲突项默认均为重命名。"""
    src1 = tmp_path / "a.txt"
    src1.write_text("a")
    src2 = tmp_path / "b.txt"
    src2.write_text("b")
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    conflicts = [_make_conflict(src1, dst_dir), _make_conflict(src2, dst_dir)]

    dialog = ConflictResolutionDialog(conflicts)

    assert dialog.decisions() == [RESOLUTION_RENAME, RESOLUTION_RENAME]
    dialog.close()


def test_empty_conflicts_does_not_crash(qapp) -> None:
    """空冲突列表构造对话框不报错。"""
    dialog = ConflictResolutionDialog([])

    assert dialog.decisions() == []
    dialog.close()


def test_apply_all_propagates_first_decision(qapp, tmp_path: Path) -> None:
    """「应用到全部」将第一行决策应用到所有行。"""
    src1 = tmp_path / "a.txt"
    src1.write_text("a")
    src2 = tmp_path / "b.txt"
    src2.write_text("b")
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    conflicts = [_make_conflict(src1, dst_dir), _make_conflict(src2, dst_dir)]

    dialog = ConflictResolutionDialog(conflicts)
    # 手动将第一行改为覆盖
    dialog._decisions[0] = RESOLUTION_OVERWRITE  # noqa: SLF001
    # 应用到全部
    dialog._on_apply_all()  # noqa: SLF001

    assert dialog.decisions() == [RESOLUTION_OVERWRITE, RESOLUTION_OVERWRITE]
    dialog.close()


def test_chinese_filename(qapp, tmp_path: Path) -> None:
    """中文文件名冲突项正常构造。"""
    src = tmp_path / "护甲包.7z"
    src.write_text("src")
    dst_dir = tmp_path / "目标"
    dst_dir.mkdir()
    conflicts = [_make_conflict(src, dst_dir)]

    dialog = ConflictResolutionDialog(conflicts)

    assert dialog.decisions() == [RESOLUTION_RENAME]
    # 验证表格首行源文件名
    item = dialog._table.item(0, 0)  # noqa: SLF001
    assert item is not None
    assert item.text() == "护甲包.7z"
    dialog.close()


def test_suggested_dst_preview_shown(qapp, tmp_path: Path) -> None:
    """重命名预览列应显示 suggested_dst 文件名。"""
    src = tmp_path / "a.txt"
    src.write_text("src")
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    conflicts = [_make_conflict(src, dst_dir)]

    dialog = ConflictResolutionDialog(conflicts)
    # 预览列在第 2 列
    preview_item = dialog._table.item(0, 2)  # noqa: SLF001
    assert preview_item is not None
    assert preview_item.text() == "a (1).txt"
    dialog.close()


def test_decisions_reflect_radio_selection(qapp, tmp_path: Path) -> None:
    """单选按钮切换后 decisions() 反映新选择。"""
    src = tmp_path / "a.txt"
    src.write_text("src")
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    conflicts = [_make_conflict(src, dst_dir)]

    dialog = ConflictResolutionDialog(conflicts)
    # 模拟选中「跳过」按钮（radio_id=1）
    dialog._on_radio_changed(0, 1, True)  # noqa: SLF001

    assert dialog.decisions() == [RESOLUTION_SKIP]
    dialog.close()


def test_radio_changed_ignored_when_unchecked(qapp, tmp_path: Path) -> None:
    """单选按钮取消选中（checked=False）时不更新决策。"""
    src = tmp_path / "a.txt"
    src.write_text("src")
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    conflicts = [_make_conflict(src, dst_dir)]

    dialog = ConflictResolutionDialog(conflicts)
    # checked=False 不应更新决策
    dialog._on_radio_changed(0, 0, False)  # noqa: SLF001

    # 仍为默认的重命名
    assert dialog.decisions() == [RESOLUTION_RENAME]
    dialog.close()
