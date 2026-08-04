"""网址与搜索设置（操作便捷性8/9，2026-08-04）。

配置项（QSettings 键 url/*，随应用一起持久化）：
- nexus_url_prefix：N 网来源 URL 前缀（默认
  https://www.nexusmods.com/skyrimspecialedition/mods/）
- search_engine_url：浏览器搜索引擎地址（默认 Bing，需含查询参数前缀 ?q=）
- search_prefix：浏览器搜索词前缀（默认 "skyrim "，如 "skyrim mod名字"）

「自动填入网址」「打开网址」「浏览器搜索」都从这里读取配置；
扫描与启动**不**自动填入（用户确认 2026-08-04，仅右键触发）。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import ui_constants as ui


@dataclass(frozen=True)
class UrlSettingsConfig:
    """网址与搜索配置（不可变；修改通过 save 重新写入 QSettings）。"""

    nexus_url_prefix: str
    search_engine_url: str
    search_prefix: str

    @classmethod
    def defaults(cls) -> UrlSettingsConfig:
        return cls(
            nexus_url_prefix=ui.URL_SETTINGS_DEFAULT_NEXUS_PREFIX,
            search_engine_url=ui.URL_SETTINGS_DEFAULT_SEARCH_ENGINE,
            search_prefix=ui.URL_SETTINGS_DEFAULT_SEARCH_PREFIX,
        )

    @classmethod
    def load(cls, settings: QSettings) -> UrlSettingsConfig:
        """从 QSettings 读取；缺省/损坏值回退默认。"""
        defaults = cls.defaults()
        return cls(
            nexus_url_prefix=str(
                settings.value(
                    ui.QSETTINGS_KEY_URL_NEXUS_PREFIX,
                    defaults.nexus_url_prefix,
                    type=str,
                )
            ),
            search_engine_url=str(
                settings.value(
                    ui.QSETTINGS_KEY_URL_SEARCH_ENGINE,
                    defaults.search_engine_url,
                    type=str,
                )
            ),
            search_prefix=str(
                settings.value(
                    ui.QSETTINGS_KEY_URL_SEARCH_PREFIX,
                    defaults.search_prefix,
                    type=str,
                )
            ),
        )

    def save(self, settings: QSettings) -> None:
        """写入 QSettings。"""
        settings.setValue(ui.QSETTINGS_KEY_URL_NEXUS_PREFIX, self.nexus_url_prefix)
        settings.setValue(ui.QSETTINGS_KEY_URL_SEARCH_ENGINE, self.search_engine_url)
        settings.setValue(ui.QSETTINGS_KEY_URL_SEARCH_PREFIX, self.search_prefix)
        settings.sync()


class UrlSettingsDialog(QDialog):
    """网址与搜索设置对话框。确定后通过 resulting_config() 取配置。"""

    def __init__(
        self,
        initial: UrlSettingsConfig | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(ui.URL_SETTINGS_DIALOG_TITLE)
        self.setModal(True)
        self.resize(460, 200)
        self._initial = initial or UrlSettingsConfig.defaults()

        layout = QVBoxLayout(self)

        # N 网网址前缀
        layout.addWidget(QLabel(ui.URL_SETTINGS_NEXUS_PREFIX_LABEL))
        self._nexus_prefix_edit = QLineEdit()
        layout.addWidget(self._nexus_prefix_edit)

        # 搜索引擎网址
        layout.addWidget(QLabel(ui.URL_SETTINGS_SEARCH_ENGINE_LABEL))
        self._search_engine_edit = QLineEdit()
        layout.addWidget(self._search_engine_edit)

        # 搜索前缀
        layout.addWidget(QLabel(ui.URL_SETTINGS_SEARCH_PREFIX_LABEL))
        self._search_prefix_edit = QLineEdit()
        layout.addWidget(self._search_prefix_edit)

        # 恢复默认 + 确定/取消
        reset_row = QHBoxLayout()
        reset_button = QPushButton(ui.URL_SETTINGS_RESET)
        reset_button.clicked.connect(self._reset_to_defaults)
        reset_row.addWidget(reset_button)
        reset_row.addStretch(1)
        layout.addLayout(reset_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load(self._initial)

    def _load(self, config: UrlSettingsConfig) -> None:
        self._nexus_prefix_edit.setText(config.nexus_url_prefix)
        self._search_engine_edit.setText(config.search_engine_url)
        self._search_prefix_edit.setText(config.search_prefix)

    def _reset_to_defaults(self) -> None:
        self._load(UrlSettingsConfig.defaults())

    def resulting_config(self) -> UrlSettingsConfig:
        """返回当前输入对应的配置（未保存，由调用方 save）。"""
        return UrlSettingsConfig(
            nexus_url_prefix=self._nexus_prefix_edit.text().strip(),
            search_engine_url=self._search_engine_edit.text().strip(),
            search_prefix=self._search_prefix_edit.text(),
        )
