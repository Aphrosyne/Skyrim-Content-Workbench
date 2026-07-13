"""FileScanner 测试。

覆盖（spec §5.4 2026-07-13 修正）：
- 全量扫描：递归扫描所有子目录（不再因压缩包停止递归）
- 增量扫描：mtime 未变跳过，mtime 变化重新扫描
- 压缩包文件识别：所有压缩包文件路径记入 archive_candidates
- 嵌套目录中的压缩包也被识别
- 文件夹不作为候选（新规则）
- 中文路径支持
- 符号链接不跟随
- 根目录不存在 → 错误结果
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
    │       └── nested.zip
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
    (weapons / "sub" / "nested.zip").write_bytes(b"\x00" * 60)

    (root / "空目录").mkdir()

    normal = root / "普通文件夹"
    normal.mkdir()
    (normal / "readme.txt").write_bytes(b"data")

    (root / "normal_file.txt").write_bytes(b"data")
    return root


class TestScanFull:
    def test_scans_all_subdirs(self, scanner: FileScanner, mod_tree: Path) -> None:
        """新规则：递归所有子目录，包括含压缩包的目录的子目录。"""
        result = scanner.scan_full(mod_tree)
        paths = {e.path for e in result.scanned_dirs}
        assert str(mod_tree) in paths
        assert str(mod_tree / "护甲") in paths
        assert str(mod_tree / "Weapons") in paths
        assert str(mod_tree / "Weapons" / "sub") in paths  # 新规则：递归进入
        assert str(mod_tree / "空目录") in paths
        assert str(mod_tree / "普通文件夹") in paths

    def test_identifies_archive_candidates(self, scanner: FileScanner, mod_tree: Path) -> None:
        """新规则：压缩包文件路径记入 archive_candidates。"""
        result = scanner.scan_full(mod_tree)
        candidates = set(result.archive_candidates)
        # 三个压缩包文件均应被识别
        assert str(mod_tree / "护甲" / "寒霜之心.7z") in candidates
        assert str(mod_tree / "Weapons" / "DragonSword.rar") in candidates
        assert str(mod_tree / "Weapons" / "sub" / "nested.zip") in candidates
        # 普通文件不应在候选中
        assert str(mod_tree / "normal_file.txt") not in candidates
        assert str(mod_tree / "普通文件夹" / "readme.txt") not in candidates

    def test_folders_not_in_candidates(self, scanner: FileScanner, mod_tree: Path) -> None:
        """新规则：文件夹不作为内容单元候选。"""
        result = scanner.scan_full(mod_tree)
        candidates = set(result.archive_candidates)
        # 文件夹路径不应出现在候选中
        assert str(mod_tree / "护甲") not in candidates
        assert str(mod_tree / "Weapons") not in candidates

    def test_old_candidates_field_empty(self, scanner: FileScanner, mod_tree: Path) -> None:
        """新规则下 content_unit_candidates 字段为空（向后兼容保留）。"""
        result = scanner.scan_full(mod_tree)
        assert result.content_unit_candidates == []
        # scanned_dirs 中 is_content_unit_candidate 恒为 False
        for entry in result.scanned_dirs:
            assert entry.is_content_unit_candidate is False

    def test_recurses_into_archive_parent_subdirs(
        self, scanner: FileScanner, mod_tree: Path
    ) -> None:
        """新规则：递归进入含压缩包目录的子目录。"""
        result = scanner.scan_full(mod_tree)
        paths = {e.path for e in result.scanned_dirs}
        # Weapons 含 .rar，但其 sub 子目录仍应被递归扫描
        assert str(mod_tree / "Weapons" / "sub") in paths
        # sub 中的 nested.zip 也应被识别
        assert str(mod_tree / "Weapons" / "sub" / "nested.zip") in set(result.archive_candidates)

    def test_chinese_path_scanned(self, scanner: FileScanner, mod_tree: Path) -> None:
        result = scanner.scan_full(mod_tree)
        paths = {e.path for e in result.scanned_dirs}
        assert str(mod_tree / "护甲") in paths
        assert str(mod_tree / "普通文件夹") in paths

    def test_chinese_archive_name_identified(self, scanner: FileScanner, mod_tree: Path) -> None:
        """中文压缩包文件名正确识别。"""
        result = scanner.scan_full(mod_tree)
        candidates = set(result.archive_candidates)
        assert str(mod_tree / "护甲" / "寒霜之心.7z") in candidates

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
        assert not result.archive_candidates


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
