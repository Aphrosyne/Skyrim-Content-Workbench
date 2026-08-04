"""快捷键配置应用测试（2026-08-04，设计合理性1 附带）。

覆盖 ShortcutRegistry：自定义键应用到中栏/目录树、空键跳过注册、
重注册替换旧快捷键（设置对话框保存后立即生效）。
"""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QWidget

from app.shortcut_config import ShortcutConfig
from app.shortcut_registry import ShortcutRegistry


class _FakeHost(QObject):
    """满足 ShortcutRegistry 属性访问的最小宿主（handler 均为 no-op）。"""

    def __init__(self, content_view: QWidget, tree_view: QWidget) -> None:
        super().__init__()
        self._content_view = content_view
        self._tree_view = tree_view
        self._undo_service = None
        self._file_operation_service = object()
        self._clipboard_service = object()
        self._assembly_panel = None

    def __getattr__(self, name: str):
        if name.startswith("_on_"):
            return lambda *args, **kwargs: None
        raise AttributeError(name)


def _make_registry(
    config: ShortcutConfig | None = None,
) -> tuple[ShortcutRegistry, _FakeHost]:
    content_view = QWidget()
    tree_view = QWidget()
    host = _FakeHost(content_view, tree_view)
    return ShortcutRegistry(host, config), host


class TestShortcutRegistryConfig:
    def test_custom_key_applied_to_all_scopes(self, qapp) -> None:
        config = ShortcutConfig.defaults()
        config.set_key("rename", "Ctrl+E")
        registry, host = _make_registry(config)
        registry.register()
        assert host._shortcut_rename.key() == QKeySequence("Ctrl+E")  # noqa: SLF001
        assert host._shortcut_rename_tree.key() == QKeySequence("Ctrl+E")  # noqa: SLF001

    def test_disabled_key_skips_registration(self, qapp) -> None:
        config = ShortcutConfig.defaults()
        config.set_key("delete", "")
        registry, host = _make_registry(config)
        registry.register()
        assert not hasattr(host, "_shortcut_delete")
        assert not hasattr(host, "_shortcut_delete_tree")
        assert hasattr(host, "_shortcut_rename")

    def test_re_register_replaces_old_shortcuts(self, qapp) -> None:
        config = ShortcutConfig.defaults()
        registry, host = _make_registry(config)
        registry.register()
        old = host._shortcut_copy  # noqa: SLF001

        new_config = ShortcutConfig.defaults()
        new_config.set_key("copy", "Ctrl+H")
        ShortcutRegistry(host, new_config).register()

        assert host._shortcut_copy is not old  # noqa: SLF001
        assert host._shortcut_copy.key() == QKeySequence("Ctrl+H")  # noqa: SLF001
        assert not old.isEnabled()

    def test_register_without_config_uses_defaults(self, qapp) -> None:
        registry, host = _make_registry()
        registry.register()
        assert host._shortcut_rename.key() == QKeySequence("F2")  # noqa: SLF001
        assert host._shortcut_select_all.key() == QKeySequence("Ctrl+A")  # noqa: SLF001
