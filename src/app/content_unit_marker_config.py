"""内容单元标记配置模型（UI合理性21，2026-08-04）。

QSettings 持久化（键 marker/*）：
- icon_enabled / icon_glyph：行首徽章开关与字符（单个 Unicode 字符）
- stripe_enabled / stripe_color：左侧色条开关与颜色（#RRGGBB）

规则：
- 图标与色条至少启用一个（"必须启用一个"）；
- reserved_width 按启用组合自动派生：仅色条 = 5、仅图标 = 18、双启用 = 23，
  所有行内容统一右移该宽度保证对齐。

默认（用户确认 2026-08-04）：只启用紫色色条；🔗 预填但不启用。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings

from app import ui_constants as ui


@dataclass(frozen=True)
class ContentUnitMarkerConfig:
    """内容单元标记配置（不可变；修改通过 with_* 或整体替换）。"""

    icon_enabled: bool
    icon_glyph: str
    stripe_enabled: bool
    stripe_color: str

    @classmethod
    def defaults(cls) -> ContentUnitMarkerConfig:
        """默认配置：只启用紫色色条，🔗 预填但不启用。"""
        return cls(
            icon_enabled=False,
            icon_glyph=ui.CONTENT_UNIT_MARKER,
            stripe_enabled=True,
            stripe_color=ui.CONTENT_UNIT_STRIPE_COLOR,
        )

    @classmethod
    def load(cls, settings: QSettings) -> ContentUnitMarkerConfig:
        """从 QSettings 读取；缺省/损坏值回退默认。"""
        defaults = cls.defaults()
        return cls(
            icon_enabled=bool(
                settings.value(
                    ui.QSETTINGS_KEY_MARKER_ICON_ENABLED, defaults.icon_enabled, type=bool
                )
            ),
            icon_glyph=str(
                settings.value(ui.QSETTINGS_KEY_MARKER_ICON_GLYPH, defaults.icon_glyph, type=str)
            ),
            stripe_enabled=bool(
                settings.value(
                    ui.QSETTINGS_KEY_MARKER_STRIPE_ENABLED, defaults.stripe_enabled, type=bool
                )
            ),
            stripe_color=str(
                settings.value(
                    ui.QSETTINGS_KEY_MARKER_STRIPE_COLOR, defaults.stripe_color, type=str
                )
            ),
        )

    def save(self, settings: QSettings) -> None:
        """写入 QSettings。"""
        settings.setValue(ui.QSETTINGS_KEY_MARKER_ICON_ENABLED, self.icon_enabled)
        settings.setValue(ui.QSETTINGS_KEY_MARKER_ICON_GLYPH, self.icon_glyph)
        settings.setValue(ui.QSETTINGS_KEY_MARKER_STRIPE_ENABLED, self.stripe_enabled)
        settings.setValue(ui.QSETTINGS_KEY_MARKER_STRIPE_COLOR, self.stripe_color)
        settings.sync()

    @property
    def reserved_width(self) -> int:
        """内容统一右移的预留宽度：按启用组合自动派生。"""
        width = 0
        if self.stripe_enabled:
            width += ui.CONTENT_UNIT_STRIPE_WIDTH + ui.CONTENT_UNIT_BADGE_LEADING_GAP
        if self.icon_enabled:
            width += ui.CONTENT_UNIT_BADGE_SIZE + ui.CONTENT_UNIT_BADGE_TRAILING_GAP
        return width


def validate_config(
    icon_enabled: bool,
    icon_glyph: str,
    stripe_enabled: bool,
) -> str | None:
    """校验配置；返回错误文案或 None（供对话框与测试共用）。"""
    if not icon_enabled and not stripe_enabled:
        return ui.MARKER_CONFIG_NEED_ONE
    if icon_enabled:
        glyph = icon_glyph.strip()
        if len(glyph) != 1:
            return ui.MARKER_CONFIG_GLYPH_INVALID
    return None
