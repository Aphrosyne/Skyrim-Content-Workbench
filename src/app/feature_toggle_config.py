"""右键功能开关配置（设计合理性1，2026-08-04）。

列出全部可关闭的右键功能（按类别分组），QSettings 键 ``context_menu/<id>``，
默认全部启用；关闭后对应菜单项（含子菜单）不再出现，立即生效。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QSettings

from app import ui_constants as ui

# 全部可开关的右键功能 id（顺序 = 配置界面分组内显示顺序）
FEATURE_TOGGLE_IDS: tuple[str, ...] = (
    "create_mod_group",
    "mark_content_unit",
    "batch_tag",
    "recent_tag",
    "autofill_url",
    "open_url",
    "browser_search",
    "archive_quick",
    "archive_to",
    "mark_archive",
    "generate_manifest",
    "open",
    "new_folder",
    "rename",
    "delete",
    "copy",
    "cut",
    "paste",
    "move_to",
    "move_to_recent",
    "strip",
    "add_to_pinned",
    "pin_folder",
    "open_in_explorer",
    "copy_path",
    "collapse_all",
)


def _key(feature_id: str) -> str:
    return f"{ui.QSETTINGS_KEY_FEATURE_TOGGLE_PREFIX}/{feature_id}"


@dataclass
class FeatureToggleConfig:
    """右键功能开关（True = 显示，False = 隐藏）。"""

    enabled: dict[str, bool] = field(default_factory=dict)

    @classmethod
    def defaults(cls) -> FeatureToggleConfig:
        return cls(enabled={feature_id: True for feature_id in FEATURE_TOGGLE_IDS})

    @classmethod
    def load(cls, settings: QSettings) -> FeatureToggleConfig:
        """从 QSettings 读取；缺失/损坏值回退默认（开启）。"""
        enabled = cls.defaults().enabled
        for feature_id in FEATURE_TOGGLE_IDS:
            raw = settings.value(_key(feature_id))
            if raw is None:
                continue
            # QSettings INI 中存储为 "true"/"false" 字符串
            enabled[feature_id] = str(raw).strip().lower() in ("true", "1", "yes")
        return cls(enabled=enabled)

    def save(self, settings: QSettings) -> None:
        for feature_id in FEATURE_TOGGLE_IDS:
            settings.setValue(_key(feature_id), self.enabled.get(feature_id, True))
        settings.sync()

    def is_enabled(self, feature_id: str) -> bool:
        """返回该右键功能是否启用（未知 id 默认启用，向前兼容）。"""
        return self.enabled.get(feature_id, True)

    def toggle(self, feature_id: str, enabled: bool) -> None:
        self.enabled[feature_id] = enabled

    def reset_defaults(self) -> None:
        self.enabled = self.defaults().enabled
