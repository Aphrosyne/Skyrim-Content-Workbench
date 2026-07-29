r"""Task 0.5 app_paths 路径决策与目录创建测试。

覆盖：
- 路径优先级（环境变量 > 项目根 data/ > AppData 回退）
- _find_project_root 定位
- 目录创建（ensure_app_directories）
- 旧目录检测仅提示、不执行任何文件操作
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


def test_fallback_to_appdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """无环境变量 + 无项目根 → 回退 AppData。"""
    monkeypatch.delenv("SCW_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))

    with patch.object(app_paths, "_find_project_root", return_value=None):
        result = app_paths.get_app_data_root()

    assert result == tmp_path / "appdata" / app_paths.APP_DATA_DIR_NAME


def test_fallback_to_home_on_non_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """无环境变量 + 无项目根 + 无 LOCALAPPDATA → 回退 ~/.skyrimmodworkbench/。"""
    monkeypatch.delenv("SCW_DATA_DIR", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    with patch.object(app_paths, "_find_project_root", return_value=None):
        result = app_paths.get_app_data_root()

    assert result == Path.home() / f".{app_paths.APP_DATA_DIR_NAME.lower()}"


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
    # 清空 LOCALAPPDATA 避免触发旧目录提示
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


# === 旧目录提示测试（仅提示，不动数据）===


def test_log_legacy_appdata_hint_does_not_copy_anything(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """检测到旧目录时仅输出日志提示，不复制、不移动、不删除任何文件。"""
    # 构造旧目录（仅含一个 app.db 标记文件）
    appdata_root = tmp_path / "appdata"
    old_root = appdata_root / app_paths.APP_DATA_DIR_NAME
    old_root.mkdir(parents=True)
    (old_root / "app.db").write_bytes(b"OLD_DB_CONTENT")

    new_root = tmp_path / "data"
    monkeypatch.setenv("SCW_DATA_DIR", str(new_root))
    monkeypatch.setenv("LOCALAPPDATA", str(appdata_root))

    with caplog.at_level("INFO", logger="app.app_paths"):
        app_paths.ensure_app_directories()

    # 新目录已创建，但 app.db 不应被复制（程序不动数据）
    assert new_root.exists()
    assert not (new_root / "app.db").exists(), "程序不应自动复制旧数据"
    # 旧目录应原样保留
    assert (old_root / "app.db").read_bytes() == b"OLD_DB_CONTENT"
    # 日志应包含提示
    assert any("检测到旧数据目录" in r.message for r in caplog.records)


def test_log_legacy_appdata_hint_skipped_when_new_db_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """新目录已有 app.db 时不再提示迁移。"""
    appdata_root = tmp_path / "appdata"
    old_root = appdata_root / app_paths.APP_DATA_DIR_NAME
    old_root.mkdir(parents=True)
    (old_root / "app.db").write_bytes(b"OLD")

    new_root = tmp_path / "data"
    new_root.mkdir(parents=True)
    (new_root / "app.db").write_bytes(b"NEW")
    monkeypatch.setenv("SCW_DATA_DIR", str(new_root))
    monkeypatch.setenv("LOCALAPPDATA", str(appdata_root))

    with caplog.at_level("INFO", logger="app.app_paths"):
        app_paths.ensure_app_directories()

    # 不应有迁移提示
    assert not any("检测到旧数据目录" in r.message for r in caplog.records)
    # 新旧 app.db 都不应被改动
    assert (new_root / "app.db").read_bytes() == b"NEW"
    assert (old_root / "app.db").read_bytes() == b"OLD"


def test_log_legacy_appdata_hint_skipped_when_no_old_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """无旧目录时不提示迁移。"""
    new_root = tmp_path / "data"
    monkeypatch.setenv("SCW_DATA_DIR", str(new_root))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))

    with caplog.at_level("INFO", logger="app.app_paths"):
        app_paths.ensure_app_directories()

    assert not any("检测到旧数据目录" in r.message for r in caplog.records)


def test_log_legacy_appdata_hint_skipped_when_no_localappdata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """无 LOCALAPPDATA 环境变量时不提示迁移。"""
    new_root = tmp_path / "data"
    monkeypatch.setenv("SCW_DATA_DIR", str(new_root))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    with caplog.at_level("INFO", logger="app.app_paths"):
        app_paths.ensure_app_directories()

    assert not any("检测到旧数据目录" in r.message for r in caplog.records)


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
