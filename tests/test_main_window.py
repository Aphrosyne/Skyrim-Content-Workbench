"""MainWindow smoke test。

若 PySide6 未安装则跳过整个模块。
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def test_main_window_constructs(qapp: QApplication) -> None:
    window = MainWindow()
    assert window.windowTitle() == "Skyrim Mod Workbench"
