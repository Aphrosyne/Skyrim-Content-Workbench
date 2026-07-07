"""pytest 全局 fixture。

涉及应用数据目录的测试必须使用 temp_app_data fixture，
不得写入真实用户目录（见 AGENTS.md 开发方式）。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def temp_app_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """将 LOCALAPPDATA 指向临时目录，返回临时应用数据根目录的父目录。

    测试中 app_paths.get_app_data_root() 将返回 <temp_app_data>/SkyrimModWorkbench。
    """
    root = tmp_path / "appdata"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LOCALAPPDATA", str(root))
    yield root
