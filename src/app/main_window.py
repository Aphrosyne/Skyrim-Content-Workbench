"""主窗口。第一版（Task 1）仅空窗口占位。

三栏布局、目录树、卡片、详情编辑等在阶段 2 实现。
"""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QWidget


class MainWindow(QMainWindow):
    """应用主窗口。

    第一版（Task 1）仅为占位空窗口，不实现三栏布局、目录树或卡片。
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Skyrim Mod Workbench")
        self.resize(1024, 720)
        # 占位中央 widget
        self.setCentralWidget(QWidget(self))
