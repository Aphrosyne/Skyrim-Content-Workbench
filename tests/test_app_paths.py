r"""Task 0.5 app_paths 路径决策与目录创建测试。

覆盖：
- 路径优先级（环境变量 > 项目根 data/ > 程序目录 data/ 回退）
- _find_project_root 定位
- 目录创建（ensure_app_directories）
- 2026-08-04（用户反馈）：不再回退 LOCALAPPDATA / 用户主目录
- 中文路径 / 空格路径
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app import app_paths

# === 路径决策测试 ===


def test_env_var_overrides_everything(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SCW_DATA_DIR 环境变量优先级最高。"""
    custom = tmp_path / "custom_data"
    monkeypatch.setenv("SCW_DATA_DIR", str(custom))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))

    result = app_paths.get_app_data_root()

    assert result == custom


def test_project_root_data_dir_in_dev(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """无环境变量 + 有 pyproject.toml → 返回项目根 data/。"""
    monkeypatch.delenv("SCW_DATA_DIR", raising=False)

    # mock _find_project_root 返回 tmp_path 作为项目根
    with patch.object(app_paths, "_find_project_root", return_value=tmp_path):
        result = app_paths.get_app_data_root()

    assert result == tmp_path / "data"


def test_fallback_to_program_dir_ignores_appdata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无环境变量 + 无项目根 → 回退程序目录 data/；即使有 LOCALAPPDATA 也不使用。"""
    monkeypatch.delenv("SCW_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))

    with patch.object(app_paths, "_find_project_root", return_value=None):
        result = app_paths.get_app_data_root()

    expected = Path(app_paths.__file__).resolve().parent.parent.parent / "data"
    assert result == expected


def test_no_fallback_to_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """无项目根 + 无 LOCALAPPDATA → 仍回退程序目录 data/，不使用用户主目录。"""
    monkeypatch.delenv("SCW_DATA_DIR", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    with patch.object(app_paths, "_find_project_root", return_value=None):
        result = app_paths.get_app_data_root()

    expected = Path(app_paths.__file__).resolve().parent.parent.parent / "data"
    assert result == expected
    assert result != Path.home() / f".{app_paths.APP_DATA_DIR_NAME.lower()}"


def test_find_project_root_finds_pyproject(tmp_path: Path) -> None:
    """_find_project_root 能向上定位含 pyproject.toml 的目录。"""
    # 构造结构：tmp_path / proj / src / app / app_paths.py
    proj = tmp_path / "proj"
    src_app = proj / "src" / "app"
    src_app.mkdir(parents=True)
    (proj / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")

    # 创建一个假 app_paths.py
    fake_module = src_app / "app_paths.py"
    fake_module.write_text("", encoding="utf-8")

    # 临时替换 __file__ 让 _find_project_root 从 fake_module 开始查找
    with patch.object(app_paths, "__file__", str(fake_module)):
        result = app_paths._find_project_root()

    assert result == proj


def test_find_project_root_returns_none_in_production(tmp_path: Path) -> None:
    """mock 无 pyproject.toml → 返回 None。"""
    # 构造无 pyproject.toml 的目录结构
    src_app = tmp_path / "deep" / "nested" / "src" / "app"
    src_app.mkdir(parents=True)
    fake_module = src_app / "app_paths.py"
    fake_module.write_text("", encoding="utf-8")

    with patch.object(app_paths, "__file__", str(fake_module)):
        result = app_paths._find_project_root()

    assert result is None


# === 目录创建测试 ===


def test_ensure_app_directories_creates_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """首次运行（无旧数据）创建所有子目录。"""
    new_root = tmp_path / "data"
    monkeypatch.setenv("SCW_DATA_DIR", str(new_root))
    # 清空 LOCALAPPDATA，保证路径解析只走 SCW_DATA_DIR
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    app_paths.ensure_app_directories()

    assert new_root.exists()
    assert (new_root / "thumbnails").exists()
    assert (new_root / "exports").exists()
    assert (new_root / "logs").exists()


def test_ensure_app_directories_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """重复调用 ensure_app_directories 不报错（幂等）。"""
    new_root = tmp_path / "data"
    monkeypatch.setenv("SCW_DATA_DIR", str(new_root))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    app_paths.ensure_app_directories()
    # 第二次调用不应抛异常
    app_paths.ensure_app_directories()

    assert new_root.exists()


# === 环境变量隔离测试 ===


def test_env_var_with_chinese_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SCW_DATA_DIR 含中文路径 → 正常工作。"""
    custom = tmp_path / "自定义数据目录"
    monkeypatch.setenv("SCW_DATA_DIR", str(custom))

    result = app_paths.get_app_data_root()

    assert result == custom


def test_env_var_with_spaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SCW_DATA_DIR 含空格 → 正常工作。"""
    custom = tmp_path / "my data dir"
    monkeypatch.setenv("SCW_DATA_DIR", str(custom))

    result = app_paths.get_app_data_root()

    assert result == custom


def test_db_and_subdir_paths_consistent_with_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_app_db_path / get_thumbnails_dir 等与 get_app_data_root 一致。"""
    custom = tmp_path / "custom"
    monkeypatch.setenv("SCW_DATA_DIR", str(custom))

    root = app_paths.get_app_data_root()
    db = app_paths.get_app_db_path()
    thumb = app_paths.get_thumbnails_dir()
    exports = app_paths.get_exports_dir()
    logs = app_paths.get_logs_dir()

    assert db == root / "app.db"
    assert thumb == root / "thumbnails"
    assert exports == root / "exports"
    assert logs == root / "logs"
