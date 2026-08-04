"""pytest 全局 fixture。

涉及应用数据目录的测试必须使用 temp_app_data fixture，
不得写入真实用户目录（见 AGENTS.md 开发方式）。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.app_paths import get_app_db_path  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    """全局 QApplication fixture（session 级，避免重复创建）。

    Qt 测试中所有需要 QApplication 的测试函数均可注入此 fixture。
    """
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def temp_app_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """将 SCW_DATA_DIR 指向临时目录，返回临时应用数据根目录。

    Task 0.5 后 get_app_data_root() 优先返回项目根 data/（开发环境），
    因此测试必须显式设置 SCW_DATA_DIR 以隔离数据目录，避免污染项目 data/。
    """
    root = tmp_path / "appdata"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SCW_DATA_DIR", str(root))
    # 同时清理 LOCALAPPDATA，保证路径解析只走 SCW_DATA_DIR
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    yield root


@pytest.fixture
def db_path(temp_app_data: Path) -> Path:
    """返回临时应用数据目录下的 app.db 路径。"""
    return get_app_db_path()


@pytest.fixture
def db_connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    """初始化数据库并返回连接。

    测试结束自动关闭连接。连接使用 Row 工厂以便 Repository 按列名访问。
    """
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _clean_shared_qsettings() -> Iterator[None]:
    """清理测试共享的默认 QSettings 持久化键（既有测试隔离缺陷，2026-08-04）。

    背景：test_main_window_assembly.py / test_main_window_move_to.py 的部分用例
    通过 ``_perform_move_to`` 把最近移动目标写入 MainWindow 默认 QSettings
    （真实注册表 ``HKCU\\Software\\SkyrimContentWorkbench\\SkyrimContentWorkbench``），
    跨用例/跨 pytest 进程污染后续运行；test_main_window_metadata.py 的 FakeMenu
    用例在污染状态下会因真实子菜单以 FakeMenu 为父构造而崩溃。

    修复：本 fixture 在每个测试前后移除 ``recent_move_targets`` / ``recent_tags``
    与 ``url/*`` 键（操作便捷性8/9，2026-08-04）
    （测试各自隔离的临时 INI QSettings 实例不受影响），保证共享状态不跨测试残留。
    """
    from PySide6.QtCore import QSettings  # noqa: PLC0415

    from app import ui_constants as ui  # noqa: PLC0415

    settings = QSettings(ui.QSETTINGS_ORGANIZATION, ui.QSETTINGS_APPLICATION)
    settings.remove("recent_move_targets")
    settings.remove("recent_tags")
    settings.remove("url/nexus_url_prefix")
    settings.remove("url/search_engine_url")
    settings.remove("url/search_prefix")
    settings.remove(ui.QSETTINGS_KEY_ARCHIVE_ROOT)
    settings.remove(ui.QSETTINGS_KEY_ARCHIVE_LAST_TARGET)
    settings.remove(ui.QSETTINGS_KEY_FEATURE_TOGGLE_PREFIX)
    settings.remove(ui.QSETTINGS_KEY_SHORTCUT_PREFIX)
    settings.remove(ui.QSETTINGS_KEY_ICON_COLOR_FOLDER)
    settings.remove(ui.QSETTINGS_KEY_ICON_COLOR_ARCHIVE)
    settings.remove(ui.QSETTINGS_KEY_ICON_COLOR_IMAGE)
    settings.remove(ui.QSETTINGS_KEY_ICON_COLOR_DOCUMENT)
    settings.sync()
    try:
        yield
    finally:
        settings.remove("recent_move_targets")
        settings.remove("recent_tags")
        settings.remove("url/nexus_url_prefix")
        settings.remove("url/search_engine_url")
        settings.remove("url/search_prefix")
        settings.remove(ui.QSETTINGS_KEY_ARCHIVE_ROOT)
        settings.remove(ui.QSETTINGS_KEY_ARCHIVE_LAST_TARGET)
        settings.remove(ui.QSETTINGS_KEY_FEATURE_TOGGLE_PREFIX)
        settings.remove(ui.QSETTINGS_KEY_SHORTCUT_PREFIX)
        settings.remove(ui.QSETTINGS_KEY_ICON_COLOR_FOLDER)
        settings.remove(ui.QSETTINGS_KEY_ICON_COLOR_ARCHIVE)
        settings.remove(ui.QSETTINGS_KEY_ICON_COLOR_IMAGE)
        settings.remove(ui.QSETTINGS_KEY_ICON_COLOR_DOCUMENT)
        settings.sync()
