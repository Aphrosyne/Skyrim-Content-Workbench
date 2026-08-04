"""ConflictResolutionService 单元测试（Stage 5 Task 3b）。

覆盖：
- scan_conflicts：无冲突 / 有冲突 / 跨盘剪切检测
- resolve：覆盖 / 跳过 / 重命名 / 决策数量不匹配 / 非法决策值
- _suggest_rename：Windows 风格 file (1).txt 递增
- has_conflict / has_cross_drive_cut 辅助函数
"""

from __future__ import annotations

from pathlib import Path

import pytest

from application.conflict_resolution_service import (
    RESOLUTION_OVERWRITE,
    RESOLUTION_RENAME,
    RESOLUTION_SKIP,
    ConflictResolutionService,
    has_conflict,
    has_cross_drive_cut,
)
from application.errors import FileOperationError


class TestScanConflicts:
    def test_no_conflict_when_dst_empty(self, tmp_path: Path) -> None:
        """目标目录无同名文件时，default_dst 不存在，无真实冲突。"""
        svc = ConflictResolutionService()
        src = tmp_path / "a.txt"
        src.write_text("src")
        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()

        conflicts = svc.scan_conflicts([src], dst_dir, operation="copy")

        assert len(conflicts) == 1
        assert conflicts[0].src == src
        assert conflicts[0].default_dst == dst_dir / "a.txt"
        assert conflicts[0].default_dst.exists() is False
        assert conflicts[0].is_cross_drive is False
        # has_conflict 应为 False
        assert has_conflict(conflicts) is False

    def test_same_location_move_is_noop(self, tmp_path: Path) -> None:
        """目标路径等于源路径（移动到自身所在目录）→ 自动跳过、无冲突（验收反馈 2026-08-04）。"""
        svc = ConflictResolutionService()
        src = tmp_path / "a.txt"
        src.write_text("src")

        conflicts = svc.scan_conflicts([src], tmp_path, operation="cut")

        assert conflicts == []
        assert has_conflict(conflicts) is False
        # 空冲突列表 + 空决策 → 空操作列表（调用方不会执行任何移动）
        assert svc.resolve(conflicts, []) == []

    def test_same_location_skipped_while_other_conflicts_kept(self, tmp_path: Path) -> None:
        """混合场景：同位置条目被剔除，其他真实冲突保留。"""
        svc = ConflictResolutionService()
        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()
        src_same = dst_dir / "same.txt"
        src_same.write_text("src")
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        src_other = other_dir / "b.txt"
        src_other.write_text("src2")
        (dst_dir / "b.txt").write_text("existing")

        conflicts = svc.scan_conflicts([src_same, src_other], dst_dir, operation="cut")

        assert len(conflicts) == 1
        assert conflicts[0].src == src_other
        assert has_conflict(conflicts) is True

    def test_conflict_when_dst_exists(self, tmp_path: Path) -> None:
        """目标目录已有同名文件时，has_conflict 返回 True。"""
        svc = ConflictResolutionService()
        src = tmp_path / "a.txt"
        src.write_text("src")
        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()
        (dst_dir / "a.txt").write_text("existing")

        conflicts = svc.scan_conflicts([src], dst_dir, operation="copy")

        assert has_conflict(conflicts) is True
        assert conflicts[0].suggested_dst.name == "a (1).txt"

    def test_multiple_sources(self, tmp_path: Path) -> None:
        """多个源路径生成多个冲突项。"""
        svc = ConflictResolutionService()
        src1 = tmp_path / "a.txt"
        src1.write_text("a")
        src2 = tmp_path / "b.txt"
        src2.write_text("b")
        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()

        conflicts = svc.scan_conflicts([src1, src2], dst_dir, operation="copy")

        assert len(conflicts) == 2
        assert conflicts[0].src == src1
        assert conflicts[1].src == src2

    def test_cross_drive_cut_detected(self, tmp_path: Path) -> None:
        """跨盘剪切应标记 is_cross_drive=True（Q7=B）。

        同盘场景无法在 tmp_path 中可靠模拟跨盘（取决于测试环境盘符），
        此处仅验证同盘剪切时 is_cross_drive=False。
        跨盘检测的实际拒绝逻辑在 MainWindow._perform_paste 中通过
        has_cross_drive_cut 判断，由 UI 集成测试覆盖。
        """
        svc = ConflictResolutionService()
        src = tmp_path / "a.txt"
        src.write_text("src")
        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()

        # 同盘剪切 → is_cross_drive=False
        conflicts = svc.scan_conflicts([src], dst_dir, operation="cut")
        assert conflicts[0].is_cross_drive is False
        assert has_cross_drive_cut(conflicts) is False

    def test_cross_drive_not_checked_for_copy(self, tmp_path: Path) -> None:
        """复制操作不检测跨盘（copy 不退化，Q7=B 仅拒绝跨盘剪切）。"""
        svc = ConflictResolutionService()
        src = tmp_path / "a.txt"
        src.write_text("src")
        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()

        conflicts = svc.scan_conflicts([src], dst_dir, operation="copy")
        assert conflicts[0].is_cross_drive is False


class TestResolve:
    def test_overwrite_uses_default_dst(self, tmp_path: Path) -> None:
        """覆盖决策使用 default_dst，overwrite=True。"""
        svc = ConflictResolutionService()
        src = tmp_path / "a.txt"
        src.write_text("src")
        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()
        (dst_dir / "a.txt").write_text("existing")

        conflicts = svc.scan_conflicts([src], dst_dir, operation="copy")
        actions = svc.resolve(conflicts, [RESOLUTION_OVERWRITE])

        assert len(actions) == 1
        assert actions[0].src == src
        assert actions[0].dst == dst_dir / "a.txt"
        assert actions[0].skipped is False
        assert actions[0].overwrite is True

    def test_skip_marks_skipped(self, tmp_path: Path) -> None:
        """跳过决策标记 skipped=True。"""
        svc = ConflictResolutionService()
        src = tmp_path / "a.txt"
        src.write_text("src")
        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()
        (dst_dir / "a.txt").write_text("existing")

        conflicts = svc.scan_conflicts([src], dst_dir, operation="copy")
        actions = svc.resolve(conflicts, [RESOLUTION_SKIP])

        assert actions[0].skipped is True

    def test_rename_uses_suggested_dst(self, tmp_path: Path) -> None:
        """重命名决策使用 suggested_dst。"""
        svc = ConflictResolutionService()
        src = tmp_path / "a.txt"
        src.write_text("src")
        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()
        (dst_dir / "a.txt").write_text("existing")

        conflicts = svc.scan_conflicts([src], dst_dir, operation="copy")
        actions = svc.resolve(conflicts, [RESOLUTION_RENAME])

        assert actions[0].dst == conflicts[0].suggested_dst
        assert actions[0].dst.name == "a (1).txt"

    def test_mismatched_decision_length_raises(self, tmp_path: Path) -> None:
        """决策数量与冲突数量不匹配应抛 FileOperationError。"""
        svc = ConflictResolutionService()
        src = tmp_path / "a.txt"
        src.write_text("src")
        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()

        conflicts = svc.scan_conflicts([src], dst_dir, operation="copy")
        with pytest.raises(FileOperationError):
            svc.resolve(conflicts, [RESOLUTION_OVERWRITE, RESOLUTION_SKIP])

    def test_invalid_decision_raises(self, tmp_path: Path) -> None:
        """非法决策值应抛 FileOperationError。"""
        svc = ConflictResolutionService()
        src = tmp_path / "a.txt"
        src.write_text("src")
        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()

        conflicts = svc.scan_conflicts([src], dst_dir, operation="copy")
        with pytest.raises(FileOperationError):
            svc.resolve(conflicts, ["invalid_decision"])


class TestSuggestRename:
    def test_first_rename_suffix(self, tmp_path: Path) -> None:
        """无冲突时第一个重命名建议为 file (1).ext。"""
        svc = ConflictResolutionService()
        dst = tmp_path / "a.txt"
        # dst 不存在 → 第一个建议应为 a (1).txt
        suggested = svc._suggest_rename(dst)  # noqa: SLF001
        assert suggested.name == "a (1).txt"

    def test_increments_until_available(self, tmp_path: Path) -> None:
        """已存在 a (1).txt 时建议 a (2).txt。"""
        svc = ConflictResolutionService()
        (tmp_path / "a (1).txt").write_text("x")
        (tmp_path / "a (2).txt").write_text("x")

        suggested = svc._suggest_rename(tmp_path / "a.txt")  # noqa: SLF001
        assert suggested.name == "a (3).txt"

    def test_no_extension(self, tmp_path: Path) -> None:
        """无扩展名文件的重命名建议。"""
        svc = ConflictResolutionService()
        dst = tmp_path / "noext"
        suggested = svc._suggest_rename(dst)  # noqa: SLF001
        assert suggested.name == "noext (1)"


def test_has_conflict_false_when_no_conflict(tmp_path: Path) -> None:
    """无冲突时 has_conflict 返回 False。"""
    svc = ConflictResolutionService()
    src = tmp_path / "a.txt"
    src.write_text("src")
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()

    conflicts = svc.scan_conflicts([src], dst_dir, operation="copy")
    assert has_conflict(conflicts) is False


def test_has_conflict_true_when_dst_exists(tmp_path: Path) -> None:
    """有冲突时 has_conflict 返回 True。"""
    svc = ConflictResolutionService()
    src = tmp_path / "a.txt"
    src.write_text("src")
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    (dst_dir / "a.txt").write_text("existing")

    conflicts = svc.scan_conflicts([src], dst_dir, operation="copy")
    assert has_conflict(conflicts) is True


def test_has_cross_drive_cut_false_for_copy(tmp_path: Path) -> None:
    """复制操作无跨盘剪切标记。"""
    svc = ConflictResolutionService()
    src = tmp_path / "a.txt"
    src.write_text("src")
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()

    conflicts = svc.scan_conflicts([src], dst_dir, operation="copy")
    assert has_cross_drive_cut(conflicts) is False
