"""BatchTagDialog 单元测试（Stage 4 Task 2）。

覆盖：
- 初始状态 / 目标数提示 / 操作模式默认 add
- 操作模式切换（add ↔ remove）
- chip 添加（输入框回车）/ 移除（chip 点击）
- 重复 chip 警告 / 未知标签警告 / 空白名称 no-op
- 自动补全（QCompleter QStringListModel）
- 预选标签区域：初始填充 / 排除已选 chip / 单击添加 / chip 移除后回归
- 回车行为：仅添加到 chip，不关闭窗口（2026-07-25 修正）
- 应用按钮：batch_attach_tags 调用 / batch_detach_tags 调用 / 结果摘要 / 空标签列表警告
- 中文标签支持

测试使用 tmp_path + init_db 构造真实 service。
QMessageBox 通过 monkeypatch 替换为 lambda，避免模态阻塞。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLabel  # noqa: E402

from app.batch_tag_dialog import BatchTagDialog  # noqa: E402
from app.tag_colors import category_color_hex  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.tag_service import TagService  # noqa: E402
from infrastructure.db import get_connection, init_db  # noqa: E402
from infrastructure.repositories.content_unit import ContentUnitRepository  # noqa: E402
from infrastructure.repositories.content_unit_tag import (  # noqa: E402
    ContentUnitTagRepository,
)
from infrastructure.repositories.tag import TagRepository  # noqa: E402
from infrastructure.repositories.tag_category import (  # noqa: E402
    TagCategoryRepository,
)

# === Fixture ===


@pytest.fixture
def services(tmp_path: Path):
    """构造 ContentService + TagService + 共享 sqlite 连接。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row

    content_repo = ContentUnitRepository(conn)
    content_service = ContentService(content_repo)
    tag_service = TagService(
        TagCategoryRepository(conn),
        TagRepository(conn),
        ContentUnitTagRepository(conn),
    )

    yield content_service, tag_service, conn, content_repo
    conn.close()


@pytest.fixture
def env_with_units(services, tmp_path):
    """构造 3 个 ContentUnit + 2 个分类 + 3 个标签。

    结构：
        tmp_path/Unit1/   ← ContentUnit 1
        tmp_path/Unit2/   ← ContentUnit 2
        tmp_path/Unit3/   ← ContentUnit 3
        分类：服装护甲 / 状态
        标签：重甲 / 轻甲 / 已测试
    """
    content_service, tag_service, conn, content_repo = services

    unit_ids: list[str] = []
    for name in ("Unit1", "Unit2", "Unit3"):
        folder = tmp_path / name
        folder.mkdir()
        unit = content_service.mark_as_content_unit(folder)
        unit_ids.append(unit.id)
    conn.commit()

    cat1 = tag_service.create_category("服装护甲", color_hue=210)
    cat2 = tag_service.create_category("状态", color_hue=120)
    tag1 = tag_service.create_tag("重甲", cat1.id)
    tag2 = tag_service.create_tag("轻甲", cat1.id)
    tag3 = tag_service.create_tag("已测试", cat2.id)
    conn.commit()

    yield content_service, tag_service, conn, content_repo, unit_ids, cat1, cat2, tag1, tag2, tag3


# === 初始状态 ===


def test_dialog_initial_state(qapp, env_with_units):
    """新建对话框：默认 add 模式 / 无 chip / 目标数正确。"""
    _, tag_service, _, _, unit_ids, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    assert dialog.current_mode() == "add"
    assert dialog.is_add_mode()
    assert not dialog.is_remove_mode()
    assert dialog.selected_tag_names() == []
    assert dialog.target_count() == 3
    assert dialog.result_messages() == []


def test_dialog_target_count_zero(qapp, services):
    """空 content_unit_ids 列表：target_count = 0。"""
    _, tag_service, _, _ = services
    dialog = BatchTagDialog(tag_service, [])

    assert dialog.target_count() == 0


# === 操作模式切换 ===


def test_dialog_switch_to_remove_mode(qapp, env_with_units):
    """程序化切换到 remove 模式。"""
    _, tag_service, _, _, unit_ids, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    dialog.set_mode("remove")
    assert dialog.current_mode() == "remove"
    assert dialog.is_remove_mode()
    assert not dialog.is_add_mode()


def test_dialog_switch_back_to_add_mode(qapp, env_with_units):
    """add → remove → add 切换。"""
    _, tag_service, _, _, unit_ids, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    dialog.set_mode("remove")
    assert dialog.current_mode() == "remove"
    dialog.set_mode("add")
    assert dialog.current_mode() == "add"


# === chip 添加 / 移除 ===


def test_dialog_add_tag_via_input(qapp, env_with_units, monkeypatch):
    """输入回车 → chip 添加成功。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)
    dialog.add_tag_via_input("重甲")

    assert dialog.selected_tag_names() == ["重甲"]


def test_dialog_add_multiple_tags(qapp, env_with_units, monkeypatch):
    """连续添加多个 chip。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, tag2, tag3 = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)
    dialog.add_tag_via_input("重甲")
    dialog.add_tag_via_input("轻甲")
    dialog.add_tag_via_input("已测试")

    assert dialog.selected_tag_names() == ["重甲", "轻甲", "已测试"]


def test_dialog_add_tag_click_chip_removes(qapp, env_with_units, monkeypatch):
    """chip 单击 → 移除该 chip。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, tag2, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)
    dialog.add_tag_via_input("重甲")
    dialog.add_tag_via_input("轻甲")
    assert dialog.selected_tag_names() == ["重甲", "轻甲"]

    dialog.click_tag_chip("重甲")
    assert dialog.selected_tag_names() == ["轻甲"]


def test_dialog_add_tag_duplicate_shows_warning(qapp, env_with_units, monkeypatch):
    """重复添加同名标签 → 弹警告，不添加。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    calls: list[tuple] = []
    monkeypatch.setattr(
        "app.batch_tag_dialog.QMessageBox.information",
        lambda *a, **kw: calls.append(a),
    )
    dialog.add_tag_via_input("重甲")
    dialog.add_tag_via_input("重甲")  # 重复

    assert dialog.selected_tag_names() == ["重甲"]
    assert len(calls) == 1


def test_dialog_add_unknown_tag_shows_warning(qapp, env_with_units, monkeypatch):
    """输入不存在的标签名 → 弹警告，不添加。"""
    _, tag_service, _, _, unit_ids, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    calls: list[tuple] = []
    monkeypatch.setattr(
        "app.batch_tag_dialog.QMessageBox.information",
        lambda *a, **kw: calls.append(a),
    )
    dialog.add_tag_via_input("不存在的标签")

    assert dialog.selected_tag_names() == []
    assert len(calls) == 1


def test_dialog_add_empty_tag_name_noop(qapp, env_with_units, monkeypatch):
    """输入空字符串 → no-op。"""
    _, tag_service, _, _, unit_ids, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    calls: list[tuple] = []
    monkeypatch.setattr(
        "app.batch_tag_dialog.QMessageBox.information",
        lambda *a, **kw: calls.append(a),
    )
    dialog.add_tag_via_input("   ")

    assert dialog.selected_tag_names() == []
    assert calls == []


def test_dialog_add_tag_whitespace_stripped(qapp, env_with_units, monkeypatch):
    """输入前后空白 → strip 后匹配。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)
    dialog.add_tag_via_input("  重甲  ")

    assert dialog.selected_tag_names() == ["重甲"]


# === 预选标签区域 ===


def test_dialog_preset_list_initial_state(qapp, env_with_units):
    """新建对话框 → 预选列表包含所有标签。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, tag2, tag3 = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    names = dialog.preset_tag_names()
    assert tag1.name in names
    assert tag2.name in names
    assert tag3.name in names
    assert len(names) == 3


def test_dialog_preset_excludes_added_chips(qapp, env_with_units, monkeypatch):
    """输入回车添加 chip 后 → 该标签从预选列表移除。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, tag2, tag3 = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)
    dialog.add_tag_via_input("重甲")

    names = dialog.preset_tag_names()
    assert tag1.name not in names
    assert tag2.name in names
    assert tag3.name in names


def test_dialog_click_preset_tag_adds_to_chips(qapp, env_with_units, monkeypatch):
    """单击预选标签 → 添加到 chip 列表 + 从预选列表移除。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, tag2, tag3 = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    # 点击预选 tag2
    dialog.click_preset_tag(tag2.name)

    assert tag2.name in dialog.selected_tag_names()
    assert tag2.name not in dialog.preset_tag_names()


def test_dialog_remove_chip_returns_to_preset(qapp, env_with_units, monkeypatch):
    """chip 移除 → 该标签回到预选列表。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, tag2, tag3 = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)
    dialog.add_tag_via_input("重甲")
    assert tag1.name not in dialog.preset_tag_names()

    dialog.click_tag_chip("重甲")
    assert tag1.name not in dialog.selected_tag_names()
    # 回到预选列表
    assert tag1.name in dialog.preset_tag_names()


def test_dialog_preset_excludes_all_chips(qapp, env_with_units, monkeypatch):
    """所有 chip 标签都应排除出预选列表。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, tag2, tag3 = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)
    dialog.add_tag_via_input("重甲")
    dialog.add_tag_via_input("轻甲")
    dialog.add_tag_via_input("已测试")

    # 全部添加到 chip → 预选列表应为空
    assert dialog.preset_tag_names() == []
    assert len(dialog.selected_tag_names()) == 3


# === 回车行为：仅添加到 chip，不关闭窗口（2026-07-25 修正） ===


def test_dialog_enter_does_not_accept_dialog(qapp, env_with_units, monkeypatch):
    """输入回车 → 不调用 accept，仅添加到 chip 列表。

    背景：原行为回车触发默认按钮导致窗口关闭，无法连续添加多个标签。
    通过 setAutoDefault(False) 禁用按钮自动默认行为。
    """
    _, tag_service, _, _, unit_ids, _, _, tag1, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    accepted = {"flag": False}
    monkeypatch.setattr(dialog, "accept", lambda: accepted.__setitem__("flag", True))
    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)

    dialog.add_tag_via_input("重甲")

    # 回车不应触发 accept
    assert not accepted["flag"]
    # 但 chip 已添加
    assert dialog.selected_tag_names() == ["重甲"]


def test_dialog_enter_multiple_times_keeps_open(qapp, env_with_units, monkeypatch):
    """连续多次回车添加多个标签 → 窗口全程不关闭。

    用户验收场景：输入"重"回车 → 显示 chip；
    继续输入"轻甲"回车 → 再添加 chip；
    最后点击「应用」才真正执行。
    """
    _, tag_service, _, _, unit_ids, _, _, tag1, tag2, tag3 = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    accepted = {"flag": False}
    monkeypatch.setattr(dialog, "accept", lambda: accepted.__setitem__("flag", True))
    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)

    # 连续添加 3 个标签
    dialog.add_tag_via_input("重甲")
    dialog.add_tag_via_input("轻甲")
    dialog.add_tag_via_input("已测试")

    # 期间窗口不关闭
    assert not accepted["flag"]
    # 3 个 chip 都添加成功
    assert dialog.selected_tag_names() == ["重甲", "轻甲", "已测试"]


def test_dialog_only_ok_button_accepts(qapp, env_with_units, monkeypatch):
    """点击「应用」按钮 → 才触发 accept。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    accepted = {"flag": False}
    monkeypatch.setattr(dialog, "accept", lambda: accepted.__setitem__("flag", True))
    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)

    dialog.add_tag_via_input("重甲")
    # 添加后回车不关闭
    assert not accepted["flag"]

    dialog.click_ok_button()
    # 点击「应用」后才关闭
    assert accepted["flag"]


# === 应用按钮：add 模式 ===


def test_dialog_ok_add_mode_calls_batch_attach(qapp, env_with_units, monkeypatch):
    """add 模式 + 应用 → batch_attach_tags 被调用，3 个 unit 都关联。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)
    dialog.add_tag_via_input("重甲")
    dialog.click_ok_button()

    # 验证所有 unit 都已关联 tag1
    for uid in unit_ids:
        tags = tag_service.list_tags_of_content_unit(uid)
        flat = [t.name for _, tags_in_cat in tags for t in tags_in_cat]
        assert "重甲" in flat


def test_dialog_ok_add_mode_result_messages(qapp, env_with_units, monkeypatch):
    """add 模式 + 应用 → result_messages 包含正确的摘要。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)
    dialog.add_tag_via_input("重甲")
    dialog.click_ok_button()

    messages = dialog.result_messages()
    assert len(messages) == 1
    assert "3" in messages[0]
    assert "添加" in messages[0]
    assert "重甲" in messages[0]


def test_dialog_ok_add_mode_accepts_dialog(qapp, env_with_units, monkeypatch):
    """add 模式 + 应用成功 → dialog.accept() 被调用。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)
    dialog.add_tag_via_input("重甲")

    # Mock accept 验证调用
    accepted = {"flag": False}
    monkeypatch.setattr(dialog, "accept", lambda: accepted.__setitem__("flag", True))
    dialog.click_ok_button()

    assert accepted["flag"]


def test_dialog_ok_add_mode_multiple_tags(qapp, env_with_units, monkeypatch):
    """add 模式 + 多个标签 → 每个标签都批量关联。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, tag2, tag3 = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)
    dialog.add_tag_via_input("重甲")
    dialog.add_tag_via_input("轻甲")
    dialog.add_tag_via_input("已测试")
    dialog.click_ok_button()

    # 验证所有 unit 都已关联 3 个标签
    for uid in unit_ids:
        tags = tag_service.list_tags_of_content_unit(uid)
        flat = [t.name for _, tags_in_cat in tags for t in tags_in_cat]
        assert "重甲" in flat
        assert "轻甲" in flat
        assert "已测试" in flat

    # result_messages 应有 3 条
    assert len(dialog.result_messages()) == 3


# === 应用按钮：remove 模式 ===


def test_dialog_ok_remove_mode_calls_batch_detach(qapp, env_with_units, monkeypatch):
    """remove 模式 + 应用 → batch_detach_tags 被调用，关联被移除。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    # 先批量添加 tag1 到所有 unit
    tag_service.batch_attach_tags(unit_ids, tag1.id)

    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)
    dialog.set_mode("remove")
    dialog.add_tag_via_input("重甲")
    dialog.click_ok_button()

    # 验证所有 unit 都已移除 tag1
    for uid in unit_ids:
        tags = tag_service.list_tags_of_content_unit(uid)
        flat = [t.name for _, tags_in_cat in tags for t in tags_in_cat]
        assert "重甲" not in flat


def test_dialog_ok_remove_mode_result_messages(qapp, env_with_units, monkeypatch):
    """remove 模式 + 应用 → result_messages 包含"移除"字样。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    # 先批量添加 tag1 到所有 unit
    tag_service.batch_attach_tags(unit_ids, tag1.id)

    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)
    dialog.set_mode("remove")
    dialog.add_tag_via_input("重甲")
    dialog.click_ok_button()

    messages = dialog.result_messages()
    assert len(messages) == 1
    assert "3" in messages[0]
    assert "移除" in messages[0]
    assert "重甲" in messages[0]


# === 应用按钮：空标签列表 ===


def test_dialog_ok_no_tags_shows_warning(qapp, env_with_units, monkeypatch):
    """未添加任何 chip → 弹警告，不执行任何操作。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    calls: list[tuple] = []
    monkeypatch.setattr(
        "app.batch_tag_dialog.QMessageBox.information",
        lambda *a, **kw: calls.append(a),
    )
    # 不添加任何 chip，直接点击应用
    dialog.click_ok_button()

    assert len(calls) == 1
    assert dialog.result_messages() == []


def test_dialog_ok_no_tags_does_not_accept(qapp, env_with_units, monkeypatch):
    """未添加任何 chip → 不调用 accept。"""
    _, tag_service, _, _, unit_ids, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)
    accepted = {"flag": False}
    monkeypatch.setattr(dialog, "accept", lambda: accepted.__setitem__("flag", True))
    dialog.click_ok_button()

    assert not accepted["flag"]


# === 幂等性 ===


def test_dialog_add_mode_idempotent_when_already_attached(qapp, env_with_units, monkeypatch):
    """add 模式：标签已关联 → 不报错，result_messages 中 count 为 0。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    # 预先关联 tag1 到所有 unit
    tag_service.batch_attach_tags(unit_ids, tag1.id)

    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)
    dialog.add_tag_via_input("重甲")
    dialog.click_ok_button()

    messages = dialog.result_messages()
    assert len(messages) == 1
    # 已关联，新增 0 条
    assert "0" in messages[0]


def test_dialog_remove_mode_idempotent_when_not_attached(qapp, env_with_units, monkeypatch):
    """remove 模式：标签未关联 → 不报错，result_messages 中 count 为 0。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)
    dialog.set_mode("remove")
    dialog.add_tag_via_input("重甲")
    dialog.click_ok_button()

    messages = dialog.result_messages()
    assert len(messages) == 1
    # 未关联，移除 0 条
    assert "0" in messages[0]


# === 中文标签 ===


def test_dialog_add_chinese_tag(qapp, env_with_units, monkeypatch):
    """中文标签名添加 chip。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)
    dialog.add_tag_via_input("重甲")

    assert dialog.selected_tag_names() == ["重甲"]


def test_dialog_add_chinese_tag_and_apply(qapp, env_with_units, monkeypatch):
    """中文标签添加后应用 → 关联成功。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)
    dialog.add_tag_via_input("重甲")
    dialog.click_ok_button()

    for uid in unit_ids:
        tags = tag_service.list_tags_of_content_unit(uid)
        flat = [t.name for _, tags_in_cat in tags for t in tags_in_cat]
        assert "重甲" in flat


# === 多 unit 部分已关联 ===


def test_dialog_add_mode_partial_already_attached(qapp, env_with_units, monkeypatch):
    """add 模式：部分 unit 已关联 → 只为未关联的添加，count 为新增数。"""
    _, tag_service, _, _, unit_ids, _, _, tag1, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    # 只关联第 1 个 unit
    tag_service.attach_tag_to_unit(unit_ids[0], tag1.id)

    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)
    dialog.add_tag_via_input("重甲")
    dialog.click_ok_button()

    messages = dialog.result_messages()
    assert len(messages) == 1
    # 新增 2 条（剩 2 个 unit 未关联）
    assert "2" in messages[0]

    # 验证所有 unit 都已关联
    for uid in unit_ids:
        tags = tag_service.list_tags_of_content_unit(uid)
        flat = [t.name for _, tags_in_cat in tags for t in tags_in_cat]
        assert "重甲" in flat


# === UI合理性12：重构（搜索过滤 / 分组折叠 / 无空提示 / 分类色） ===


def test_preset_search_filters_tags(qapp, env_with_units):
    """搜索框输入即过滤预选标签。"""
    _, tag_service, _, _, unit_ids, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    assert len(dialog.preset_tag_names()) == 3
    dialog.search_edit().setText("重")

    names = dialog.preset_tag_names()
    assert names == ["重甲"]

    dialog.search_edit().setText("不存在")
    assert dialog.preset_tag_names() == []


def test_preset_grouped_by_category(qapp, env_with_units):
    """预选标签按分类分组（组头存在，可折叠）。"""
    _, tag_service, _, _, unit_ids, cat1, cat2, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    assert cat1.name in dialog.preset_group_names()
    assert cat2.name in dialog.preset_group_names()

    dialog.click_preset_group(cat1.name)
    assert dialog.is_preset_group_collapsed(cat1.id)

    dialog.click_preset_group(cat1.name)
    assert not dialog.is_preset_group_collapsed(cat1.id)


def test_no_empty_tags_hint_label(qapp, env_with_units):
    """UI合理性12：已删除「（未添加标签）」空提示。"""
    _, tag_service, _, _, unit_ids, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    assert not hasattr(dialog, "_empty_hint")
    labels = dialog.findChildren(QLabel)
    assert all("未添加标签" not in lbl.text() for lbl in labels)


def test_only_one_input_box(qapp, env_with_units):
    """验收反馈：删除独立标签输入框，仅保留搜索框一个输入框。"""
    from PySide6.QtWidgets import QLineEdit

    _, tag_service, _, _, unit_ids, *_ = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)

    line_edits = dialog.findChildren(QLineEdit)
    assert len(line_edits) == 1
    assert line_edits[0] is dialog.search_edit()


def test_chip_and_preset_buttons_colored_by_category(qapp, env_with_units, monkeypatch):
    """BugFix2：chip 与预选标签按钮背景/边框统一分类色；分组头不着色。"""
    _, tag_service, _, _, unit_ids, cat1, cat2, tag1, _tag2, tag3 = env_with_units
    dialog = BatchTagDialog(tag_service, unit_ids)
    monkeypatch.setattr("app.batch_tag_dialog.QMessageBox.information", lambda *a, **kw: None)

    dialog.add_tag_via_input(tag1.name)
    chip_btn = next(btn for t, btn in dialog._chip_buttons if t.id == tag1.id)  # noqa: SLF001
    assert category_color_hex(cat1.color_hue) in chip_btn.styleSheet()

    # tag3（已测试）属于 cat2（状态）
    tag3_btn = next(b for b in dialog._preset_buttons if b.text() == tag3.name)  # noqa: SLF001
    assert category_color_hex(cat2.color_hue) in tag3_btn.styleSheet()

    # 分组头不着色（验收反馈：分类与标签都上色太杂乱）
    from PySide6.QtWidgets import QPushButton as _QPushButton

    headers = [
        w
        for w in dialog._preset_content.findChildren(_QPushButton)  # noqa: SLF001
        if w.text().strip().startswith(("▸", "▾"))
    ]
    assert headers
    assert all(
        category_color_hex(c.color_hue) not in h.styleSheet() for h in headers for c in (cat1, cat2)
    )
