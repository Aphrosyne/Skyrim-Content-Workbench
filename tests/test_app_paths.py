"""app_paths 测试。"""

from __future__ import annotations

from pathlib import Path

from app import app_paths


def test_get_app_data_root_uses_localappdata(temp_app_data: Path) -> None:
    root = app_paths.get_app_data_root()
    assert root == temp_app_data / app_paths.APP_DATA_DIR_NAME
    # 方向 C 重建后应用数据目录名应为 SkyrimContentWorkbench（旧名 SkyrimModWorkbench 已废弃）
    assert app_paths.APP_DATA_DIR_NAME == "SkyrimContentWorkbench"


def test_ensure_app_directories_creates_all(temp_app_data: Path) -> None:
    root = app_paths.ensure_app_directories()
    assert root.exists()
    assert app_paths.get_thumbnails_dir().exists()
    assert app_paths.get_exports_dir().exists()
    assert app_paths.get_logs_dir().exists()
    # app.db 的父目录应已存在
    assert app_paths.get_app_db_path().parent.exists()


def test_ensure_app_directories_idempotent(temp_app_data: Path) -> None:
    app_paths.ensure_app_directories()
    # 重复调用不应报错
    app_paths.ensure_app_directories()
    assert app_paths.get_app_data_root().exists()
