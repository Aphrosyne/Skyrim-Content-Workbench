"""快捷键配置（2026-08-04，设计合理性1 附带）。

快捷键条目（id / 中文标签 / 默认按键 / 适用范围，文案集中在 ui_constants）：
QSettings 键 ``shortcut/<id>``，值为 QKeySequence 字符串；空串 = 禁用该快捷键。
中栏 / 目录树 / 文件夹预览共用同一条配置，改一处生效三处。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QSettings
from PySide6.QtGui import QKeySequence

from app import ui_constants as ui

SHORTCUT_IDS: tuple[str, ...] = (
    "select_all",
    "undo",
    "rename",
    "delete",
    "copy",
    "cut",
    "paste",
    "move_to",
    "move_to_latest",
    "archive_quick",
    "refresh",
    "toggle_pin",
)


def _key(shortcut_id: str) -> str:
    return f"{ui.QSETTINGS_KEY_SHORTCUT_PREFIX}/{shortcut_id}"


@dataclass(frozen=True)
class ShortcutDefinition:
    """单条快捷键的定义（显示用）。"""

    shortcut_id: str
    label: str
    default_key: str
    scope: str


def shortcut_definitions() -> tuple[ShortcutDefinition, ...]:
    """返回全部快捷键定义（顺序 = 配置界面显示顺序）。"""
    return tuple(
        ShortcutDefinition(
            shortcut_id=shortcut_id,
            label=ui.SHORTCUT_LABELS[shortcut_id],
            default_key=ui.SHORTCUT_DEFAULT_KEYS[shortcut_id],
            scope=ui.SHORTCUT_SCOPES[shortcut_id],
        )
        for shortcut_id in SHORTCUT_IDS
    )


@dataclass
class ShortcutConfig:
    """快捷键映射（shortcut_id -> QKeySequence 字符串；空串 = 禁用）。"""

    keys: dict[str, str] = field(default_factory=dict)

    @classmethod
    def defaults(cls) -> ShortcutConfig:
        return cls(
            keys={
                shortcut_id: ui.SHORTCUT_DEFAULT_KEYS[shortcut_id] for shortcut_id in SHORTCUT_IDS
            }
        )

    @classmethod
    def load(cls, settings: QSettings) -> ShortcutConfig:
        """从 QSettings 读取；缺失/非法值回退默认，空串保留为禁用。"""
        keys = cls.defaults().keys
        for shortcut_id in SHORTCUT_IDS:
            raw = settings.value(_key(shortcut_id))
            if raw is None:
                continue
            value = str(raw)
            if value == "":
                keys[shortcut_id] = ""
            elif not QKeySequence(value).toString():
                # Qt 对非法串可能 isEmpty=False 但 toString()=''，统一视为非法
                keys[shortcut_id] = ui.SHORTCUT_DEFAULT_KEYS[shortcut_id]
            else:
                keys[shortcut_id] = QKeySequence(value).toString()
        return cls(keys=keys)

    def save(self, settings: QSettings) -> None:
        for shortcut_id in SHORTCUT_IDS:
            settings.setValue(
                _key(shortcut_id),
                self.keys.get(shortcut_id, ui.SHORTCUT_DEFAULT_KEYS[shortcut_id]),
            )
        settings.sync()

    def key_for(self, shortcut_id: str) -> str:
        """返回按键字符串（空串 = 禁用）。"""
        return self.keys.get(shortcut_id, ui.SHORTCUT_DEFAULT_KEYS[shortcut_id])

    def set_key(self, shortcut_id: str, key: str) -> None:
        """设置按键序列；空串 = 禁用。"""
        normalized = QKeySequence(key).toString() if key else ""
        self.keys[shortcut_id] = normalized

    def reset_defaults(self) -> None:
        self.keys = self.defaults().keys
