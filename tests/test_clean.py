"""scripts/clean.py 的单元测试。

覆盖：
- find_safe_targets 正确识别缓存目录和 .pyc 文件
- is_protected 正确保护源码/应用数据/虚拟环境
- clean_safe 不误删受保护目录
- 深度清理识别 pytest tmp 目录
- --dry-run 模式不删除任何内容
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

import pytest

# 将 scripts/ 加入 sys.path 以导入 clean 模块
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from clean import (  # noqa: E402
    APP_DATA_DIR_NAME,
    PROTECTED_NAMES,
    clean_safe,
    find_pytest_tmp_dirs,
    find_safe_targets,
    is_protected,
    main,
)


@pytest.fixture
def fake_project(tmp_path: Path) -> Path:
    """构造一个伪造的项目目录结构，模拟真实项目。

    结构：
        tmp_project/
          src/__pycache__/module.pyc          ← 应删
          tests/__pycache__/test.pyc          ← 应删
          .pytest_cache/                      ← 应删
          .ruff_cache/                        ← 应删
          .cache/                             ← 应删
          src/app.py                          ← 受保护
          tests/test_app.py                   ← 受保护
          docs/spec.md                        ← 受保护
          app.db                              ← 受保护
          thumbnails/                         ← 受保护
          local_appdata/                       ← 受保护
          .venv/                               ← 受保护
          README.md                           ← 受保护
    """
    root = tmp_path / "tmp_project"

    # 应被清理的目录
    (root / "src" / "__pycache__").mkdir(parents=True)
    (root / "tests" / "__pycache__").mkdir(parents=True)
    (root / ".pytest_cache").mkdir(parents=True)
    (root / ".ruff_cache").mkdir(parents=True)
    (root / ".cache").mkdir(parents=True)
    (root / "build").mkdir(parents=True)
    (root / "dist").mkdir(parents=True)
    (root / "mypackage.egg-info").mkdir(parents=True)

    # 应被清理的文件
    (root / "src" / "__pycache__" / "module.pyc").write_bytes(b"\x00")
    (root / "tests" / "__pycache__" / "test.pyc").write_bytes(b"\x00")
    (root / "src" / "app.pyo").write_bytes(b"\x00")

    # 受保护的源码和文件
    (root / "src" / "app.py").write_text("# source", encoding="utf-8")
    (root / "tests" / "test_app.py").write_text("# test", encoding="utf-8")
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "spec.md").write_text("# spec", encoding="utf-8")
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "clean.py").write_text("# script", encoding="utf-8")
    (root / "app.db").write_bytes(b"\x00")
    (root / "thumbnails").mkdir()
    (root / "exports").mkdir()
    (root / "logs").mkdir()
    (root / "local_appdata").mkdir()
    (root / ".venv").mkdir()
    (root / ".git").mkdir()
    (root / "README.md").write_text("# readme", encoding="utf-8")
    (root / "pyproject.toml").write_text("# config", encoding="utf-8")

    return root


# === find_safe_targets ===


class TestFindSafeTargets:
    def test_finds_pycache_dirs(self, fake_project: Path) -> None:
        """识别 src/ 和 tests/ 下的 __pycache__。"""
        dirs, _ = find_safe_targets(fake_project)
        dir_names = [d.name for d in dirs]
        assert "__pycache__" in dir_names
        # 应找到两个 __pycache__（src 和 tests 各一个）
        pycache_count = sum(1 for d in dirs if d.name == "__pycache__")
        assert pycache_count == 2

    def test_finds_pytest_cache(self, fake_project: Path) -> None:
        """识别 .pytest_cache。"""
        dirs, _ = find_safe_targets(fake_project)
        assert any(d.name == ".pytest_cache" for d in dirs)

    def test_finds_ruff_cache(self, fake_project: Path) -> None:
        """识别 .ruff_cache。"""
        dirs, _ = find_safe_targets(fake_project)
        assert any(d.name == ".ruff_cache" for d in dirs)

    def test_finds_pyc_files(self, fake_project: Path) -> None:
        """识别 *.pyc 文件。"""
        _, files = find_safe_targets(fake_project)
        pyc_files = [f.name for f in files if f.suffix == ".pyc"]
        assert len(pyc_files) == 2

    def test_finds_pyo_files(self, fake_project: Path) -> None:
        """识别 *.pyo 文件。"""
        _, files = find_safe_targets(fake_project)
        pyo_files = [f.name for f in files if f.suffix == ".pyo"]
        assert len(pyo_files) == 1

    def test_finds_egg_info(self, fake_project: Path) -> None:
        """识别 *.egg-info 目录。"""
        dirs, _ = find_safe_targets(fake_project)
        assert any(d.name == "mypackage.egg-info" for d in dirs)

    def test_finds_build_dist(self, fake_project: Path) -> None:
        """识别 build/ 和 dist/。"""
        dirs, _ = find_safe_targets(fake_project)
        dir_names = [d.name for d in dirs]
        assert "build" in dir_names
        assert "dist" in dir_names


# === is_protected ===


class TestIsProtected:
    @pytest.fixture(autouse=True)
    def _patch_project_root(self, fake_project: Path, monkeypatch) -> None:
        """将 clean.PROJECT_ROOT 指向 fake_project，使 is_protected 相对它判断。"""
        import clean

        monkeypatch.setattr(clean, "PROJECT_ROOT", fake_project)

    def test_source_files_protected(self, fake_project: Path) -> None:
        """src/ 下源码受保护。"""
        assert is_protected(fake_project / "src" / "app.py")

    def test_test_files_protected(self, fake_project: Path) -> None:
        """tests/ 下测试文件受保护。"""
        assert is_protected(fake_project / "tests" / "test_app.py")

    def test_app_db_protected(self, fake_project: Path) -> None:
        """app.db 受保护。"""
        assert is_protected(fake_project / "app.db")

    def test_thumbnails_protected(self, fake_project: Path) -> None:
        """thumbnails/ 受保护。"""
        assert is_protected(fake_project / "thumbnails")

    def test_local_appdata_protected(self, fake_project: Path) -> None:
        """local_appdata/ 受保护。"""
        assert is_protected(fake_project / "local_appdata")

    def test_git_protected(self, fake_project: Path) -> None:
        """.git/ 受保护。"""
        assert is_protected(fake_project / ".git")

    def test_venv_protected(self, fake_project: Path) -> None:
        """.venv/ 受保护。"""
        assert is_protected(fake_project / ".venv")

    def test_docs_protected(self, fake_project: Path) -> None:
        """docs/ 下文件受保护。"""
        assert is_protected(fake_project / "docs" / "spec.md")

    def test_pyc_not_protected(self, fake_project: Path) -> None:
        """__pycache__ 下的 .pyc 不受保护。"""
        assert not is_protected(fake_project / "src" / "__pycache__" / "module.pyc")

    def test_pytest_cache_not_protected(self, fake_project: Path) -> None:
        """.pytest_cache/ 不受保护。"""
        assert not is_protected(fake_project / ".pytest_cache")

    def test_path_outside_project_protected(self, fake_project: Path, tmp_path: Path) -> None:
        """项目外的路径视为受保护（不应被脚本删除）。"""
        assert is_protected(tmp_path / "outside" / "file.txt")


# === clean_safe ===


class TestCleanSafe:
    def test_deletes_pycache(self, fake_project: Path) -> None:
        """clean_safe 删除 __pycache__ 目录。"""
        dirs_deleted, _ = clean_safe(fake_project)
        assert dirs_deleted >= 2  # src/__pycache__ + tests/__pycache__
        assert not (fake_project / "src" / "__pycache__").exists()
        assert not (fake_project / "tests" / "__pycache__").exists()

    def test_deletes_pyc_files(self, fake_project: Path) -> None:
        """clean_safe 删除 .pyc 文件。"""
        _, files_deleted = clean_safe(fake_project)
        assert files_deleted >= 2

    def test_deletes_cache_dirs(self, fake_project: Path) -> None:
        """clean_safe 删除 .pytest_cache / .ruff_cache / .cache。"""
        clean_safe(fake_project)
        assert not (fake_project / ".pytest_cache").exists()
        assert not (fake_project / ".ruff_cache").exists()
        assert not (fake_project / ".cache").exists()

    def test_preserves_source_files(self, fake_project: Path) -> None:
        """clean_safe 不删除源码。"""
        clean_safe(fake_project)
        assert (fake_project / "src" / "app.py").exists()
        assert (fake_project / "tests" / "test_app.py").exists()

    def test_preserves_app_db(self, fake_project: Path) -> None:
        """clean_safe 不删除 app.db。"""
        clean_safe(fake_project)
        assert (fake_project / "app.db").exists()

    def test_preserves_app_data_dirs(self, fake_project: Path) -> None:
        """clean_safe 不删除应用数据目录。"""
        clean_safe(fake_project)
        assert (fake_project / "thumbnails").exists()
        assert (fake_project / "exports").exists()
        assert (fake_project / "logs").exists()
        assert (fake_project / "local_appdata").exists()

    def test_preserves_venv(self, fake_project: Path) -> None:
        """clean_safe 不删除虚拟环境。"""
        clean_safe(fake_project)
        assert (fake_project / ".venv").exists()

    def test_preserves_git(self, fake_project: Path) -> None:
        """clean_safe 不删除 .git。"""
        clean_safe(fake_project)
        assert (fake_project / ".git").exists()

    def test_preserves_docs(self, fake_project: Path) -> None:
        """clean_safe 不删除文档。"""
        clean_safe(fake_project)
        assert (fake_project / "docs" / "spec.md").exists()


# === find_pytest_tmp_dirs ===


class TestFindPytestTmpDirs:
    def test_returns_list(self) -> None:
        """find_pytest_tmp_dirs 返回列表（可能为空）。"""
        result = find_pytest_tmp_dirs()
        assert isinstance(result, list)

    def test_username_in_path(self) -> None:
        """若存在，路径包含当前用户名。"""
        dirs = find_pytest_tmp_dirs()
        if dirs:
            username = getpass.getuser()
            assert any(f"pytest-of-{username}" in str(d) for d in dirs)


# === main / --dry-run ===


class TestMainDryRun:
    def test_dry_run_does_not_delete(self, fake_project: Path, capsys) -> None:
        """--dry-run 模式不删除任何内容。"""
        # 替换 PROJECT_ROOT 为 fake_project
        import clean

        original_root = clean.PROJECT_ROOT
        clean.PROJECT_ROOT = fake_project
        try:
            exit_code = main(["--dry-run"])
            captured = capsys.readouterr()
            assert exit_code == 0
            assert "dry-run" in captured.out
            # 受保护内容仍存在
            assert (fake_project / "src" / "app.py").exists()
            # __pycache__ 仍存在（dry-run 不删）
            assert (fake_project / "src" / "__pycache__").exists()
        finally:
            clean.PROJECT_ROOT = original_root

    def test_main_normal_run(self, fake_project: Path, capsys) -> None:
        """正常运行删除缓存但保留源码。"""
        import clean

        original_root = clean.PROJECT_ROOT
        clean.PROJECT_ROOT = fake_project
        try:
            exit_code = main([])
            captured = capsys.readouterr()
            assert exit_code == 0
            assert "清理完成" in captured.out
            # __pycache__ 已删
            assert not (fake_project / "src" / "__pycache__").exists()
            # 源码保留
            assert (fake_project / "src" / "app.py").exists()
        finally:
            clean.PROJECT_ROOT = original_root


# === 受保护内容清单 ===


class TestProtectedNames:
    def test_app_data_dir_name(self) -> None:
        """应用数据目录名正确。"""
        assert APP_DATA_DIR_NAME == "SkyrimContentWorkbench"

    def test_critical_names_protected(self) -> None:
        """关键名称在受保护集合中。"""
        for name in [
            "src",
            "tests",
            "docs",
            ".git",
            ".venv",
            "app.db",
            "thumbnails",
            "exports",
            "logs",
            "local_appdata",
        ]:
            assert name in PROTECTED_NAMES, f"{name} 应在 PROTECTED_NAMES 中"
