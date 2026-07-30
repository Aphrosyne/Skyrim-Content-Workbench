"""windows_recycle_bin 模块测试（Stage 5 Task 3a）。

覆盖：
- move_to_recycle_bin：基本删除 / 批量删除 / 中文路径 / 空列表 / 目录删除
- RecycleBinError：非 Windows 平台抛异常
- SHFileOperation 标志位常量

注意：真实移至回收站仅在 Windows 平台可执行，且会修改系统回收站状态。
为避免污染用户回收站，测试在 tmp_path 下创建临时文件后删除，回收站中
会留下临时条目（与真实使用场景一致）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from infrastructure.windows_recycle_bin import (
    FO_DELETE,
    FOF_ALLOWUNDO,
    FOF_NOCONFIRMATION,
    FOF_SILENT,
    RecycleBinError,
    move_to_recycle_bin,
)

IS_WINDOWS = sys.platform == "win32"


@pytest.mark.skipif(not IS_WINDOWS, reason="仅 Windows 平台")
class TestMoveToRecycleBinWindows:
    """Windows 平台真实回收站测试。"""

    def test_delete_single_file(self, tmp_path: Path) -> None:
        """删除单个文件：文件不存在，回收站接收。"""
        f = tmp_path / "to_delete.txt"
        f.write_bytes(b"data")

        move_to_recycle_bin([f])

        assert not f.exists()

    def test_delete_directory(self, tmp_path: Path) -> None:
        """删除目录（含子文件）。"""
        d = tmp_path / "to_delete_dir"
        d.mkdir()
        (d / "inner.txt").write_text("data", encoding="utf-8")

        move_to_recycle_bin([d])

        assert not d.exists()

    def test_delete_multiple_paths(self, tmp_path: Path) -> None:
        """批量删除多个文件 + 目录。"""
        f1 = tmp_path / "f1.txt"
        f1.write_bytes(b"1")
        f2 = tmp_path / "f2.txt"
        f2.write_bytes(b"2")
        d = tmp_path / "dir"
        d.mkdir()
        (d / "inner.txt").write_text("data", encoding="utf-8")

        move_to_recycle_bin([f1, f2, d])

        assert not f1.exists()
        assert not f2.exists()
        assert not d.exists()

    def test_delete_chinese_path(self, tmp_path: Path) -> None:
        """中文路径删除。"""
        f = tmp_path / "中文文件.txt"
        f.write_bytes(b"data")

        move_to_recycle_bin([f])

        assert not f.exists()

    def test_delete_empty_list_is_noop(self) -> None:
        """空列表不调用 SHFileOperation，直接返回。"""
        # 空列表在任何平台都应安全返回（os.name 检查在前，非 Windows 平台会先抛异常）
        if os.name != "nt":
            pytest.skip("非 Windows 平台")
        move_to_recycle_bin([])

    def test_delete_resolves_relative_path(self, tmp_path: Path, monkeypatch) -> None:
        """相对路径被 resolve() 为绝对路径后删除。"""
        f = tmp_path / "relative.txt"
        f.write_bytes(b"data")
        monkeypatch.chdir(tmp_path)
        relative = Path("relative.txt")

        move_to_recycle_bin([relative])

        assert not f.exists()


class TestRecycleBinConstants:
    """SHFileOperation 标志位常量校验（不依赖平台）。"""

    def test_fof_allow_undo_value(self) -> None:
        """FOF_ALLOWUNDO = 0x0040（移至回收站而非永久删除）。"""
        assert FOF_ALLOWUNDO == 0x0040

    def test_fof_no_confirmation_value(self) -> None:
        """FOF_NOCONFIRMATION = 0x0010（跳过系统确认对话框）。"""
        assert FOF_NOCONFIRMATION == 0x0010

    def test_fof_silent_value(self) -> None:
        """FOF_SILENT = 0x0004（不显示进度对话框）。"""
        assert FOF_SILENT == 0x0004

    def test_fo_delete_value(self) -> None:
        """FO_DELETE = 0x0003（删除操作类型）。"""
        assert FO_DELETE == 0x0003


@pytest.mark.skipif(IS_WINDOWS, reason="非 Windows 平台异常路径测试")
class TestNonWindowsPlatform:
    """非 Windows 平台：move_to_recycle_bin 应抛 RecycleBinError。"""

    def test_raises_on_non_windows(self, tmp_path: Path) -> None:
        f = tmp_path / "f.txt"
        f.write_bytes(b"data")
        with pytest.raises(RecycleBinError, match="仅支持 Windows"):
            move_to_recycle_bin([f])

    def test_raises_on_non_windows_even_empty(self) -> None:
        """非 Windows 平台，即使传入空列表也抛异常（os.name 检查在前）。"""
        with pytest.raises(RecycleBinError, match="仅支持 Windows"):
            move_to_recycle_bin([])
