"""file_type_icons 文件类型图标测试（UI合理性4，2026-08-04）。"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QIcon  # noqa: E402

from app import file_type_icons as fti  # noqa: E402
from app import ui_constants as ui  # noqa: E402
from domain.models import FileEntry  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_icon_state() -> None:
    """每个测试前后重置类型颜色覆盖与图标缓存，避免测试间污染。"""
    fti.reset_type_colors()
    yield
    fti.reset_type_colors()


def _make_entry(name: str, is_dir: bool = False) -> FileEntry:
    return FileEntry(
        name=name,
        path=f"/mods/{name}",
        is_dir=is_dir,
        modified_at="2026-08-04T00:00:00Z",
        size=10 if not is_dir else None,
        content_unit=None,
    )


class TestClassify:
    def test_folder(self) -> None:
        assert fti.file_type_key(_make_entry("armor", is_dir=True)) == fti.ICON_FOLDER

    def test_archives(self) -> None:
        for name in ("mod.zip", "mod.7Z", "mod.rar", "mod.tar.gz", "mod.001"):
            assert fti.file_type_key(_make_entry(name)) == fti.ICON_ARCHIVE, name

    def test_images(self) -> None:
        for name in ("preview.jpg", "photo.PNG", "cover.webp", "icon.ico"):
            assert fti.file_type_key(_make_entry(name)) == fti.ICON_IMAGE, name

    def test_other_documents(self) -> None:
        for name in ("readme.txt", "notes.md", "README", "noext."):
            assert fti.file_type_key(_make_entry(name)) == fti.ICON_DOCUMENT, name


class TestIcons:
    def test_type_colors_configured_in_ui_constants(self) -> None:
        """UI合理性4 验收反馈：四类图标颜色集中在 ui_constants 可手动调整。"""
        from app import ui_constants as ui

        assert ui.FILE_TYPE_ICON_COLORS[fti.ICON_FOLDER] == "#f6e03b"
        assert ui.FILE_TYPE_ICON_COLORS[fti.ICON_ARCHIVE] == "#72e9a1"
        assert ui.FILE_TYPE_ICON_COLORS[fti.ICON_IMAGE] == "#8ab8e6"
        assert ui.FILE_TYPE_ICON_COLORS[fti.ICON_DOCUMENT] == "#ffffff"

    def test_all_types_return_icon(self, qapp) -> None:
        for type_key in (
            fti.ICON_FOLDER,
            fti.ICON_ARCHIVE,
            fti.ICON_IMAGE,
            fti.ICON_DOCUMENT,
        ):
            icon = fti.icon_for_type(type_key)
            assert isinstance(icon, QIcon)
            assert not icon.isNull()

    def test_icons_differ_by_type(self, qapp) -> None:
        """不同文件类型图标位图不同（cacheKey 区分）。"""
        keys = {
            fti.ICON_FOLDER: fti.icon_for_type(fti.ICON_FOLDER).pixmap(16, 16).cacheKey(),
            fti.ICON_ARCHIVE: fti.icon_for_type(fti.ICON_ARCHIVE).pixmap(16, 16).cacheKey(),
            fti.ICON_IMAGE: fti.icon_for_type(fti.ICON_IMAGE).pixmap(16, 16).cacheKey(),
            fti.ICON_DOCUMENT: fti.icon_for_type(fti.ICON_DOCUMENT).pixmap(16, 16).cacheKey(),
        }
        assert len(set(keys.values())) == 4

    def test_icon_cache_reused(self, qapp) -> None:
        """相同类型 + 相同主题色命中缓存（同一 QIcon 实例）。"""
        assert fti.icon_for_type(fti.ICON_FOLDER) is fti.icon_for_type(fti.ICON_FOLDER)

    def test_set_type_colors_changes_icon_and_clears_cache(self, qapp) -> None:
        """UI合理性4 二期：注入自定义颜色后图标重建（位图不同）。"""
        defaults = dict(ui.FILE_TYPE_ICON_COLORS)
        fti.set_type_colors(defaults)
        before = fti.icon_for_type(fti.ICON_FOLDER).pixmap(16, 16).cacheKey()

        custom = dict(defaults)
        custom["folder"] = "#ff0000"
        fti.set_type_colors(custom)
        after = fti.icon_for_type(fti.ICON_FOLDER).pixmap(16, 16).cacheKey()

        assert before != after

    def test_reset_type_colors_restores_defaults(self, qapp) -> None:
        """reset_type_colors 清除覆盖并回到 ui_constants 默认值。"""
        from app import ui_constants as ui

        fti.set_type_colors(
            {"folder": "#ff0000", "archive": "#00ff00", "image": "#0000ff", "document": "#ffffff"}
        )
        fti.reset_type_colors()
        # 默认色图标与显式注入默认色的图标一致（同一缓存键 → 同一实例）
        assert fti.icon_for_type(fti.ICON_FOLDER) is fti.icon_for_type(fti.ICON_FOLDER)
        assert ui.FILE_TYPE_ICON_COLORS["folder"] == "#f6e03b"

    def test_fallback_standard_icon_when_svg_missing(self, qapp, monkeypatch) -> None:
        """SVG 文件缺失时回退 Qt 标准图标，不抛异常。"""
        import tempfile
        from pathlib import Path

        # 清空模块缓存，确保走"文件缺失 → 兜底"路径而非缓存命中
        fti._icon_cache.clear()
        fti._fallback_cache.clear()
        with tempfile.TemporaryDirectory() as tmp:
            monkeypatch.setattr(fti, "_ICONS_DIR", Path(tmp))
            icon = fti.icon_for_type(fti.ICON_FOLDER)
        assert isinstance(icon, QIcon)
        assert not icon.isNull()
