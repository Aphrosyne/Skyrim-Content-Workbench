"""QMessageBox 系统提示音抑制工具。

Windows 上 QMessageBox.information/warning/critical 静态方法会触发
系统提示音（Asterisk/Exclamation/Hand），在频繁操作时很吵。

本模块通过 patch QMessageBox 的静态方法，使用 setIcon(NoIcon) + setIconPixmap
方式显示消息，保留视觉图标但抑制系统音效。

使用方式：在 MainWindow.__init__ 中调用一次 suppress_message_box_sound()。
测试环境也会触发（创建 MainWindow 实例时），但测试中的 monkeypatch.setattr
会在 patch 之上覆盖，不影响 mock 行为。
"""

from __future__ import annotations

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QStyle

_patched = False


def suppress_message_box_sound() -> None:
    """Patch QMessageBox 静态方法，抑制系统提示音。

    幂等：多次调用安全，只 patch 一次。
    """
    global _patched
    if _patched:
        return
    _patched = True

    @staticmethod
    def _information(  # noqa: ANN001
        parent,
        title: str,
        text: str,
        buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
        defaultButton: QMessageBox.StandardButton = QMessageBox.StandardButton.NoButton,
    ) -> QMessageBox.StandardButton:
        return _show_message_box(
            parent,
            title,
            text,
            buttons,
            defaultButton,
            QStyle.StandardPixmap.SP_MessageBoxInformation,
        )

    @staticmethod
    def _warning(  # noqa: ANN001
        parent,
        title: str,
        text: str,
        buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
        defaultButton: QMessageBox.StandardButton = QMessageBox.StandardButton.NoButton,
    ) -> QMessageBox.StandardButton:
        return _show_message_box(
            parent,
            title,
            text,
            buttons,
            defaultButton,
            QStyle.StandardPixmap.SP_MessageBoxWarning,
        )

    @staticmethod
    def _critical(  # noqa: ANN001
        parent,
        title: str,
        text: str,
        buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
        defaultButton: QMessageBox.StandardButton = QMessageBox.StandardButton.NoButton,
    ) -> QMessageBox.StandardButton:
        return _show_message_box(
            parent,
            title,
            text,
            buttons,
            defaultButton,
            QStyle.StandardPixmap.SP_MessageBoxCritical,
        )

    def _show_message_box(
        parent,
        title: str,
        text: str,
        buttons: QMessageBox.StandardButton,
        defaultButton: QMessageBox.StandardButton,
        standard_pixmap: QStyle.StandardPixmap,
    ) -> QMessageBox.StandardButton:
        """构造 QMessageBox 实例并显示，不触发系统音效。

        关键：setIcon(NoIcon) 避免触发 Windows MessageBeep，
        setIconPixmap 保留视觉图标。
        """
        box = QMessageBox(parent) if parent is not None else QMessageBox()
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Icon.NoIcon)
        # 手动设置图标 pixmap，保留视觉图标
        app = QApplication.instance()
        if app is not None:
            style = app.style()
            if style is not None:
                icon = style.standardIcon(standard_pixmap)
                if icon is not None:
                    pix: QPixmap = icon.pixmap(32, 32)
                    if not pix.isNull():
                        box.setIconPixmap(pix)
        box.setStandardButtons(buttons)
        box.setDefaultButton(defaultButton)
        return box.exec()

    QMessageBox.information = _information  # type: ignore[assignment]
    QMessageBox.warning = _warning  # type: ignore[assignment]
    QMessageBox.critical = _critical  # type: ignore[assignment]
