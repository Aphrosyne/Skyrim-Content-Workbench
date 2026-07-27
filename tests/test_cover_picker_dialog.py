"""CoverPickerDialog 单元测试（Stage 4 Task 2）。

覆盖：
- 初始状态：有候选 / 无候选
- 默认选中第一张（设计决策 2）
- 选中当前封面（若提供）
- 切换选择 → selected_path / selected_relative_path 更新
- 确定/取消按钮 → accept / reject
- 空候选 → 确定按钮禁用 + 空状态提示
- 相对路径 POSIX 风格
- 中文文件名

测试使用 tmp_path 构造真实图片文件。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from app.cover_picker_dialog import CoverPickerDialog  # noqa: E402

# 最小化的 PNG 文件头（1x1 像素透明 PNG）
_PNG_BYTES = bytes(
    [
        0x89,
        0x50,
        0x4E,
        0x47,
        0x0D,
        0x0A,
        0x1A,
        0x0A,
        0x00,
        0x00,
        0x00,
        0x0D,
        0x49,
        0x48,
        0x44,
        0x52,
        0x00,
        0x00,
        0x00,
        0x01,
        0x00,
        0x00,
        0x00,
        0x01,
        0x08,
        0x06,
        0x00,
        0x00,
        0x00,
        0x1F,
        0x15,
        0xC4,
        0x89,
        0x00,
        0x00,
        0x00,
        0x0D,
        0x49,
        0x44,
        0x41,
        0x54,
        0x78,
        0x9C,
        0x63,
        0x00,
        0x01,
        0x00,
        0x00,
        0x05,
        0x00,
        0x01,
        0x0D,
        0x0A,
        0x2D,
        0xB4,
        0x00,
        0x00,
        0x00,
        0x00,
        0x49,
        0x45,
        0x4E,
        0x44,
        0xAE,
        0x42,
        0x60,
        0x82,
    ]
)


@pytest.fixture
def unit_with_images(tmp_path: Path) -> tuple[Path, list[Path]]:
    """构造内容单元目录 + 3 张图片。"""
    unit = tmp_path / "MyMod"
    unit.mkdir()
    images = []
    for name in ("cover.jpg", "preview.png", "screenshot.jpg"):
        p = unit / name
        p.write_bytes(_PNG_BYTES)
        images.append(p)
    return unit, images


@pytest.fixture
def unit_with_no_images(tmp_path: Path) -> Path:
    """构造无图片的内容单元目录。"""
    unit = tmp_path / "EmptyMod"
    unit.mkdir()
    (unit / "readme.txt").write_text("data", encoding="utf-8")
    return unit


# === 初始状态 ===


def test_dialog_initial_state_with_candidates(qapp, unit_with_images):
    """有候选：候选数正确 + 默认选中第一张。"""
    unit, images = unit_with_images
    dialog = CoverPickerDialog(images, unit)

    assert dialog.candidate_count() == 3
    assert dialog.current_selection_row() == 0
    assert dialog.is_ok_button_enabled()


def test_dialog_initial_state_no_candidates(qapp, unit_with_no_images):
    """无候选：候选数为 0 + 确定按钮禁用。"""
    dialog = CoverPickerDialog([], unit_with_no_images)

    assert dialog.candidate_count() == 0
    assert not dialog.is_ok_button_enabled()
    assert dialog.selected_path() is None
    assert dialog.selected_relative_path() is None


# === 默认选中第一张（设计决策 2） ===


def test_dialog_default_selects_first(qapp, unit_with_images):
    """默认选中第一张图片。"""
    unit, images = unit_with_images
    dialog = CoverPickerDialog(images, unit)

    assert dialog.current_selection_row() == 0
    selected = dialog.selected_path()
    assert selected is not None
    assert selected.name == "cover.jpg"


def test_dialog_default_relative_path(qapp, unit_with_images):
    """默认选中的相对路径正确。"""
    unit, images = unit_with_images
    dialog = CoverPickerDialog(images, unit)

    rel = dialog.selected_relative_path()
    assert rel == "cover.jpg"


# === 选中当前封面 ===


def test_dialog_selects_current_cover_when_provided(qapp, unit_with_images):
    """提供 current_cover → 选中对应的图片。"""
    unit, images = unit_with_images
    # 第二张作为当前封面
    dialog = CoverPickerDialog(images, unit, current_cover="preview.png")

    assert dialog.current_selection_row() == 1
    assert dialog.selected_path() is not None
    assert dialog.selected_path().name == "preview.png"


def test_dialog_current_cover_not_in_candidates_falls_back_to_first(qapp, unit_with_images):
    """current_cover 不在候选列表中 → 回退到第一张。"""
    unit, images = unit_with_images
    dialog = CoverPickerDialog(images, unit, current_cover="nonexistent.jpg")

    assert dialog.current_selection_row() == 0
    assert dialog.selected_path() is not None
    assert dialog.selected_path().name == "cover.jpg"


# === 切换选择 ===


def test_dialog_click_item_changes_selection(qapp, unit_with_images):
    """程序化选中第 2 项 → selected_path 更新。"""
    unit, images = unit_with_images
    dialog = CoverPickerDialog(images, unit)

    dialog.click_item(1)
    assert dialog.current_selection_row() == 1
    selected = dialog.selected_path()
    assert selected is not None
    assert selected.name == "preview.png"


def test_dialog_click_item_updates_relative_path(qapp, unit_with_images):
    """切换选中 → selected_relative_path 更新。"""
    unit, images = unit_with_images
    dialog = CoverPickerDialog(images, unit)

    dialog.click_item(2)
    assert dialog.selected_relative_path() == "screenshot.jpg"


# === 确定 / 取消按钮 ===


def test_dialog_ok_button_accepts(qapp, unit_with_images, monkeypatch):
    """确定按钮 → dialog.accept() 被调用。"""
    unit, images = unit_with_images
    dialog = CoverPickerDialog(images, unit)

    accepted = {"flag": False}
    monkeypatch.setattr(dialog, "accept", lambda: accepted.__setitem__("flag", True))
    dialog.click_ok_button()

    assert accepted["flag"]


def test_dialog_cancel_button_rejects(qapp, unit_with_images, monkeypatch):
    """取消按钮 → dialog.reject() 被调用。"""
    unit, images = unit_with_images
    dialog = CoverPickerDialog(images, unit)

    rejected = {"flag": False}
    monkeypatch.setattr(dialog, "reject", lambda: rejected.__setitem__("flag", True))
    dialog.click_cancel_button()

    assert rejected["flag"]


# === 空候选 ===


def test_dialog_empty_candidates_ok_disabled(qapp, unit_with_no_images):
    """空候选 → 确定按钮禁用。"""
    dialog = CoverPickerDialog([], unit_with_no_images)

    assert not dialog.is_ok_button_enabled()


def test_dialog_empty_candidates_selected_path_none(qapp, unit_with_no_images):
    """空候选 → selected_path 返回 None。"""
    dialog = CoverPickerDialog([], unit_with_no_images)

    assert dialog.selected_path() is None
    assert dialog.selected_relative_path() is None


# === 中文文件名 ===


def test_dialog_chinese_filename(qapp, tmp_path):
    """中文文件名能正确显示与选中。"""
    unit = tmp_path / "ChineseMod"
    unit.mkdir()
    chinese_img = unit / "封面.png"
    chinese_img.write_bytes(_PNG_BYTES)
    other_img = unit / "preview.jpg"
    other_img.write_bytes(_PNG_BYTES)

    dialog = CoverPickerDialog([chinese_img, other_img], unit)

    assert dialog.candidate_count() == 2
    assert dialog.current_selection_row() == 0
    assert dialog.selected_path() is not None
    assert dialog.selected_path().name == "封面.png"
    assert dialog.selected_relative_path() == "封面.png"


# === 相对路径 POSIX 风格 ===


def test_dialog_relative_path_posix_style(qapp, tmp_path):
    """子目录中的图片 → 相对路径使用正斜杠。"""
    unit = tmp_path / "DeepMod"
    unit.mkdir()
    sub = unit / "previews"
    sub.mkdir()
    img = sub / "shot.png"
    img.write_bytes(_PNG_BYTES)

    dialog = CoverPickerDialog([img], unit)

    rel = dialog.selected_relative_path()
    assert rel == "previews/shot.png"
    assert "\\" not in rel


# === 单候选 ===


def test_dialog_single_candidate(qapp, tmp_path):
    """只有一个候选 → 默认选中它。"""
    unit = tmp_path / "SingleMod"
    unit.mkdir()
    img = unit / "only.png"
    img.write_bytes(_PNG_BYTES)

    dialog = CoverPickerDialog([img], unit)

    assert dialog.candidate_count() == 1
    assert dialog.current_selection_row() == 0
    assert dialog.selected_relative_path() == "only.png"
