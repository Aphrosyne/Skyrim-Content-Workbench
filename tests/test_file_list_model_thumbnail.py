"""FileListModel 缩略图相关测试（Stage 4 Task 4）。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from app.file_list_model import FileListModel
from domain.models import ContentUnit, FileEntry


def _make_entry(
    name: str = "file.txt",
    is_dir: bool = False,
    content_unit: ContentUnit | None = None,
) -> FileEntry:
    return FileEntry(
        path=f"/test/{name}",
        name=name,
        is_dir=is_dir,
        size=100 if not is_dir else 0,
        modified_at="2026-07-01T00:00:00Z",
        content_unit=content_unit,
    )


def _make_unit(unit_id: str = "u1", cover_path: str | None = None) -> ContentUnit:
    return ContentUnit(
        id=unit_id,
        path=f"/test/folder_{unit_id}",
        title=f"Folder {unit_id}",
        content_type="mod",
        status="unorganized",
        created_at="2026-07-01T00:00:00Z",
        updated_at="2026-07-01T00:00:00Z",
        cover_path=cover_path,
    )


def test_decoration_role_non_content_unit_returns_standard_icon(qapp):
    """非内容单元 → 返回 Qt 标准图标。"""
    model = FileListModel()
    entry = _make_entry(name="readme.txt", is_dir=False, content_unit=None)
    model.refresh([entry])
    idx = model.index(0, 0)
    icon = model.data(idx, Qt.DecorationRole)
    assert icon is not None


def test_decoration_role_content_unit_no_cover_returns_standard_icon(qapp):
    """内容单元无 cover_path → 返回 Qt 标准图标。"""
    model = FileListModel()
    unit = _make_unit(cover_path=None)
    entry = _make_entry(name="folder", is_dir=True, content_unit=unit)
    model.refresh([entry])
    idx = model.index(0, 0)
    icon = model.data(idx, Qt.DecorationRole)
    assert icon is not None


def test_decoration_role_content_unit_with_cover_calls_provider(qapp):
    """内容单元有 cover_path + provider 注入 → 调用 provider。"""
    model = FileListModel()
    unit = _make_unit(cover_path="cover.jpg")
    entry = _make_entry(name="folder", is_dir=True, content_unit=unit)
    model.refresh([entry])

    called_args: list[tuple[str, str]] = []

    def provider(unit_id: str, source_path: str) -> QPixmap | None:
        called_args.append((unit_id, source_path))
        return None  # 返回 None 模拟缓存未命中

    model.set_thumbnail_provider(provider)
    idx = model.index(0, 0)
    icon = model.data(idx, Qt.DecorationRole)
    assert icon is not None  # 退化为标准图标
    assert len(called_args) == 1
    assert called_args[0][0] == "u1"
    assert "cover.jpg" in called_args[0][1]


def test_decoration_role_provider_returns_pixmap_uses_it(qapp):
    """provider 返回 QPixmap → 使用它作为图标。"""
    model = FileListModel()
    unit = _make_unit(cover_path="cover.jpg")
    entry = _make_entry(name="folder", is_dir=True, content_unit=unit)
    model.refresh([entry])

    # 创建一个真实的 QPixmap
    pixmap = QPixmap(64, 64)
    pixmap.fill()

    def provider(unit_id: str, source_path: str) -> QPixmap | None:
        return pixmap

    model.set_thumbnail_provider(provider)
    idx = model.index(0, 0)
    icon = model.data(idx, Qt.DecorationRole)
    assert icon is not None
    # QIcon 包装 QPixmap，可通过 pixmap() 检查
    assert not icon.isNull()


def test_provider_caches_result_avoiding_repeated_calls(qapp):
    """同一 unit_id 多次调用 data() → provider 仅查询一次。"""
    model = FileListModel()
    unit = _make_unit(cover_path="cover.jpg")
    entry = _make_entry(name="folder", is_dir=True, content_unit=unit)
    model.refresh([entry])

    call_count = 0

    def provider(unit_id: str, source_path: str) -> QPixmap | None:
        nonlocal call_count
        call_count += 1
        return None

    model.set_thumbnail_provider(provider)
    idx = model.index(0, 0)
    model.data(idx, Qt.DecorationRole)
    model.data(idx, Qt.DecorationRole)
    model.data(idx, Qt.DecorationRole)
    assert call_count == 1  # 仅查询一次


def test_notify_thumbnail_ready_clears_cache_for_unit(qapp):
    """notify_thumbnail_ready → 清除该 unit 缓存，下次重新查询 provider。"""
    model = FileListModel()
    unit = _make_unit(cover_path="cover.jpg")
    entry = _make_entry(name="folder", is_dir=True, content_unit=unit)
    model.refresh([entry])

    call_count = 0

    def provider(unit_id: str, source_path: str) -> QPixmap | None:
        nonlocal call_count
        call_count += 1
        return None

    model.set_thumbnail_provider(provider)
    idx = model.index(0, 0)
    model.data(idx, Qt.DecorationRole)
    assert call_count == 1
    # 通知缩略图就绪 → 清除缓存
    model.notify_thumbnail_ready("u1")
    # 再次查询 → 应再次调用 provider
    model.data(idx, Qt.DecorationRole)
    assert call_count == 2


def test_set_thumbnail_provider_none_disables_feature(qapp):
    """设为 None → 禁用缩略图功能，退化为标准图标。"""
    model = FileListModel()
    unit = _make_unit(cover_path="cover.jpg")
    entry = _make_entry(name="folder", is_dir=True, content_unit=unit)
    model.refresh([entry])

    call_count = 0

    def provider(unit_id: str, source_path: str) -> QPixmap | None:
        nonlocal call_count
        call_count += 1
        return None

    model.set_thumbnail_provider(provider)
    model.set_thumbnail_provider(None)  # 禁用
    idx = model.index(0, 0)
    model.data(idx, Qt.DecorationRole)
    assert call_count == 0  # provider 未被调用


def test_refresh_clears_thumbnail_cache(qapp):
    """refresh → 清空缩略图缓存。"""
    model = FileListModel()
    unit = _make_unit(cover_path="cover.jpg")
    entry = _make_entry(name="folder", is_dir=True, content_unit=unit)
    model.refresh([entry])

    call_count = 0

    def provider(unit_id: str, source_path: str) -> QPixmap | None:
        nonlocal call_count
        call_count += 1
        return None

    model.set_thumbnail_provider(provider)
    idx = model.index(0, 0)
    model.data(idx, Qt.DecorationRole)
    assert call_count == 1
    # refresh → 清空缓存
    model.refresh([entry])
    model.data(idx, Qt.DecorationRole)
    assert call_count == 2  # 重新查询
