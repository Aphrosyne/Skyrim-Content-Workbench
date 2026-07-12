"""FileScanner 测试。

覆盖：
- 全量扫描：递归扫描所有子目录
- 增量扫描：mtime 未变跳过，mtime 变化重新扫描
- 内容单元识别：含压缩包的文件夹 → 候选；不含 → 非候选
- 内容单元识别后停止递归其子目录
- 中文路径支持
- 符号链接不跟随
- 根目录不存在 → 错误结果
- 单个目录扫描失败不中断整体
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from infrastructure.file_scanner import FileScanner


@pytest.fixture
def scanner() -> FileScanner:
    return FileScanner()


@pytest.fixture
def mod_tree(tmp_path: Path) -> Path:
    """构造样本目录树：
    root/
    ├── 护甲/
    │   ├── 寒霜之心.7z
    │   └── preview.webp
    ├── Weapons/
    │   ├── DragonSword.rar
    │   └── sub/
    │       └── note.txt
    ├── 空目录/
    ├── 普通文件夹/
    │   └── readme.txt
    └── normal_file.txt
    """
    root = tmp_path / "root"
    root.mkdir()

    armor = root / "护甲"
    armor.mkdir()
    (armor / "寒霜之心.7z").write_bytes(b"\x00" * 100)
    (armor / "preview.webp").write_bytes(b"\x00" * 200)

    weapons = root / "Weapons"
    weapons.mkdir()
    (weapons / "DragonSword.rar").write_bytes(b"\x00" * 80)
    (weapons / "sub").mkdir()
    (weapons / "sub" / "note.txt").write_bytes(b"hello")

    (root / "空目录").mkdir()

    normal = root / "普通文件夹"
    normal.mkdir()
    (normal / "readme.txt").write_bytes(b"data")

    (root / "normal_file.txt").write_bytes(b"data")
    return root


class TestScanFull:
    def test_scans_all_subdirs(self, scanner: FileScanner, mod_tree: Path) -> None:
        result = scanner.scan_full(mod_tree)
        paths = {e.path for e in result.scanned_dirs}
        assert str(mod_tree) in paths
        assert str(mod_tree / "护甲") in paths
        assert str(mod_tree / "Weapons") in paths
        assert str(mod_tree / "空目录") in paths
        assert str(mod_tree / "普通文件夹") in paths

    def test_identifies_content_unit_candidates(self, scanner: FileScanner, mod_tree: Path) -> None:
        result = scanner.scan_full(mod_tree)
        candidate_paths = {e.path for e in result.content_unit_candidates}
        # 护甲（含 .7z）和 Weapons（含 .rar）应为候选
        assert str(mod_tree / "护甲") in candidate_paths
        assert str(mod_tree / "Weapons") in candidate_paths
        # 普通文件夹（无压缩包）不应为候选
        assert str(mod_tree / "普通文件夹") not in candidate_paths

    def test_does_not_recurse_into_content_unit(self, scanner: FileScanner, mod_tree: Path) -> None:
        result = scanner.scan_full(mod_tree)
        paths = {e.path for e in result.scanned_dirs}
        # Weapons 是内容单元候选，其 sub 子目录不应被扫描
        assert str(mod_tree / "Weapons" / "sub") not in paths

    def test_chinese_path_scanned(self, scanner: FileScanner, mod_tree: Path) -> None:
        result = scanner.scan_full(mod_tree)
        paths = {e.path for e in result.scanned_dirs}
        assert str(mod_tree / "护甲") in paths
        assert str(mod_tree / "普通文件夹") in paths

    def test_root_not_exist(self, scanner: FileScanner, tmp_path: Path) -> None:
        result = scanner.scan_full(tmp_path / "nonexistent")
        assert len(result.scanned_dirs) == 0
        assert result.has_errors
        assert "不存在" in result.errors[0].message

    def test_root_not_a_directory(self, scanner: FileScanner, tmp_path: Path) -> None:
        file_path = tmp_path / "file.txt"
        file_path.write_text("x")
        result = scanner.scan_full(file_path)
        assert len(result.scanned_dirs) == 0
        assert result.has_errors
        assert "不是目录" in result.errors[0].message

    def test_empty_root(self, scanner: FileScanner, tmp_path: Path) -> None:
        empty_root = tmp_path / "empty"
        empty_root.mkdir()
        result = scanner.scan_full(empty_root)
        assert len(result.scanned_dirs) == 1
        assert result.scanned_dirs[0].path == str(empty_root)
        assert not result.content_unit_candidates


class TestScanIncremental:
    def test_unchanged_dir_skipped(self, scanner: FileScanner, mod_tree: Path) -> None:
        # 第一次全量扫描获取 mtime
        full_result = scanner.scan_full(mod_tree)
        mtime_map = {e.path: e.mtime for e in full_result.scanned_dirs}

        # 增量扫描应跳过所有未变更目录
        inc_result = scanner.scan_incremental(mod_tree, mtime_map)
        assert inc_result.skipped_unchanged > 0
        assert len(inc_result.scanned_dirs) == 0

    def test_changed_dir_rescanned(self, scanner: FileScanner, mod_tree: Path) -> None:
        full_result = scanner.scan_full(mod_tree)
        mtime_map = {e.path: e.mtime for e in full_result.scanned_dirs}

        # 修改一个子目录的 mtime（创建新文件）
        time.sleep(0.01)
        (mod_tree / "普通文件夹" / "new.txt").write_text("new")

        inc_result = scanner.scan_incremental(mod_tree, mtime_map)
        # 普通文件夹应被重新扫描
        paths = {e.path for e in inc_result.scanned_dirs}
        assert str(mod_tree / "普通文件夹") in paths
        # 未变更的目录应被跳过
        assert str(mod_tree / "护甲") not in paths

    def test_no_cache_full_scan(self, scanner: FileScanner, mod_tree: Path) -> None:
        """空 mtime_map 等效于全量扫描。"""
        result = scanner.scan_incremental(mod_tree, {})
        assert len(result.scanned_dirs) > 0
        assert result.skipped_unchanged == 0


class TestSymlink:
    def test_symlink_not_followed(self, scanner: FileScanner, tmp_path: Path) -> None:
        """符号链接不应被跟随（避免循环）。"""
        if not hasattr(os, "symlink"):
            pytest.skip("当前平台不支持 symlink")

        root = tmp_path / "root"
        root.mkdir()
        target = tmp_path / "target"
        target.mkdir()
        (target / "mod.7z").write_bytes(b"\x00")

        try:
            os.symlink(target, root / "link_to_target", target_is_directory=True)
        except OSError:
            pytest.skip("无法创建符号链接（权限不足）")

        result = scanner.scan_full(root)
        paths = {e.path for e in result.scanned_dirs}
        # link_to_target 不应出现在扫描结果中
        assert str(root / "link_to_target") not in paths
