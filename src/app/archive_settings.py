"""归档根目录与上次归档位置设置（功能增加1，2026-08-04）。

通过 QSettings 持久化（跨会话保留），供右键归档入口 / Ctrl+W / 扫描跳过使用。

语义（简化版决策，用户确认 2026-08-04）：
- 标记任意文件夹为归档根目录（先支持一个；路径比较用 make_path_key() 归一化，
  存储原始路径串保证 Windows 大小写原样，符合 RecentMoveTargets 既有模式）。
- 上次归档位置（archive/last_target）供「快速归档」Ctrl+W 直接复用。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from app import ui_constants as ui
from infrastructure.path_utils import make_path_key


class ArchiveSettings:
    """归档设置（归档根目录 + 上次归档位置，QSettings 持久化）。"""

    def __init__(self, settings: QSettings) -> None:
        self._settings = settings

    def root_path(self) -> str | None:
        """返回归档根目录路径；未标记返回 None。"""
        value = self._settings.value(ui.QSETTINGS_KEY_ARCHIVE_ROOT)
        return str(value) if value else None

    def set_root(self, path: str | Path) -> None:
        """标记归档根目录（覆盖旧值，先支持一个）。"""
        self._settings.setValue(ui.QSETTINGS_KEY_ARCHIVE_ROOT, str(path))
        self._settings.sync()

    def clear_root(self) -> None:
        """取消归档根目录标记。"""
        self._settings.remove(ui.QSETTINGS_KEY_ARCHIVE_ROOT)
        self._settings.sync()

    def is_root(self, path: str | Path) -> bool:
        """判断路径是否为当前归档根目录（make_path_key 归一化比较）。"""
        current = self.root_path()
        return current is not None and make_path_key(current) == make_path_key(str(path))

    def last_target(self) -> str | None:
        """返回上次归档位置；无记录返回 None。"""
        value = self._settings.value(ui.QSETTINGS_KEY_ARCHIVE_LAST_TARGET)
        return str(value) if value else None

    def record_target(self, target: str | Path) -> None:
        """记录一次成功归档的目标目录（供 Ctrl+W 复用）。"""
        self._settings.setValue(ui.QSETTINGS_KEY_ARCHIVE_LAST_TARGET, str(target))
        self._settings.sync()

    def clear_target(self) -> None:
        """清除上次归档位置（测试隔离 / 用户清除用）。"""
        self._settings.remove(ui.QSETTINGS_KEY_ARCHIVE_LAST_TARGET)
        self._settings.sync()
