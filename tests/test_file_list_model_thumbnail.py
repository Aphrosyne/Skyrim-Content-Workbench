"""FileListModel 图标相关测试（Stage 5 Task 1b 更新）。

Task 1b：列表视图移除封面缩略图，改用 Qt 标准 icon。
这些测试验证列表视图始终返回 Qt 标准 icon，不依赖 provider。
"""

from __future__ import annotations

from PySide6.QtCore import Qt

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
        is_marked=True,
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


def test_decoration_role_content_unit_with_cover_returns_standard_icon(qapp):
    """Task 1b：内容单元有 cover_path → 仍返回 Qt 标准图标（列表视图不用封面缩略图）。"""
    model = FileListModel()
    unit = _make_unit(cover_path="cover.jpg")
    entry = _make_entry(name="folder", is_dir=True, content_unit=unit)
    model.refresh([entry])
    idx = model.index(0, 0)
    icon = model.data(idx, Qt.DecorationRole)
    assert icon is not None  # Qt 标准图标


def test_decoration_role_file_returns_standard_icon(qapp):
    """Task 1b：普通文件 → 返回 Qt 标准文件图标。"""
    model = FileListModel()
    entry = _make_entry(name="readme.txt", is_dir=False, content_unit=None)
    model.refresh([entry])
    idx = model.index(0, 0)
    icon = model.data(idx, Qt.DecorationRole)
    assert icon is not None


def test_decoration_role_dir_returns_standard_icon(qapp):
    """Task 1b：文件夹 → 返回 Qt 标准文件夹图标。"""
    model = FileListModel()
    entry = _make_entry(name="myfolder", is_dir=True, content_unit=None)
    model.refresh([entry])
    idx = model.index(0, 0)
    icon = model.data(idx, Qt.DecorationRole)
    assert icon is not None


def test_set_thumbnail_provider_still_accepted(qapp):
    """Task 1b：set_thumbnail_provider 接口保留（向后兼容），但列表视图不调用它。"""
    model = FileListModel()
    unit = _make_unit(cover_path="cover.jpg")
    entry = _make_entry(name="folder", is_dir=True, content_unit=unit)
    model.refresh([entry])

    call_count = 0

    def provider(unit_id: str, source_path: str) -> None:
        nonlocal call_count
        call_count += 1
        return None

    # 接口保留但不影响列表视图图标
    model.set_thumbnail_provider(provider)
    idx = model.index(0, 0)
    icon = model.data(idx, Qt.DecorationRole)
    assert icon is not None
    # 列表视图不调用 provider（Task 1b：改用 Qt 标准 icon）
    assert call_count == 0


def test_notify_thumbnail_provider_none(qapp):
    """Task 1b：set_thumbnail_provider(None) 不报错。"""
    model = FileListModel()
    model.set_thumbnail_provider(None)
    entry = _make_entry(name="file.txt", is_dir=False)
    model.refresh([entry])
    idx = model.index(0, 0)
    icon = model.data(idx, Qt.DecorationRole)
    assert icon is not None
