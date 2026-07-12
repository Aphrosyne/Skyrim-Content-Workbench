"""pytest 全局 fixture。

涉及应用数据目录的测试必须使用 temp_app_data fixture，
不得写入真实用户目录（见 AGENTS.md 开发方式）。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.app_paths import get_app_db_path
from infrastructure.db import get_connection, init_db


@pytest.fixture
def temp_app_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """将 LOCALAPPDATA 指向临时目录，返回临时应用数据根目录的父目录。

    测试中 app_paths.get_app_data_root() 将返回 <temp_app_data>/SkyrimContentWorkbench。
    """
    root = tmp_path / "appdata"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LOCALAPPDATA", str(root))
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


@pytest.fixture
def sample_mod_tree(tmp_path: Path) -> Path:
    """构造一个混合中英文的样本 Mod 目录树，返回根目录路径。

    结构：
        sample_mods/
        ├── 护甲/
        │   ├── 寒霜之心.7z
        │   ├── 寒霜之心-汉化.zip
        │   └── preview.webp
        ├── Weapons/
        │   ├── DragonSword.rar
        │   └── README.txt
        ├── 空目录/
        ├── normal_file.txt
        └── no_extension
    """
    root = tmp_path / "sample_mods"
    root.mkdir(parents=True, exist_ok=True)

    armor = root / "护甲"
    armor.mkdir()
    (armor / "寒霜之心.7z").write_bytes(b"\x00" * 100)
    (armor / "寒霜之心-汉化.zip").write_bytes(b"\x00" * 50)
    (armor / "preview.webp").write_bytes(b"\x00" * 200)

    weapons = root / "Weapons"
    weapons.mkdir()
    (weapons / "DragonSword.rar").write_bytes(b"\x00" * 80)
    (weapons / "README.txt").write_bytes(b"hello")

    empty = root / "空目录"
    empty.mkdir()

    (root / "normal_file.txt").write_bytes(b"data")
    (root / "no_extension").write_bytes(b"\x00")

    return root
