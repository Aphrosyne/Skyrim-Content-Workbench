"""MetadataPanel 单元测试（Stage 4 Task 2）。

覆盖：
- 初始状态 / load_unit / clear_panel
- 标签 chip 添加（输入框回车）/ 移除（chip 点击）
- 标签自动补全（QCompleter QStringListModel）
- 保存按钮：成功写入 metadata + 标签 attach/detach diff + 发射 on_saved 信号
- 保存失败：InvalidMetadataError 弹 QMessageBox
- 封面设置回调：on_pick_cover_requested 信号 + set_cover_path 更新预览
- 清除封面按钮
- 测试接口：title_text / source_url_text / notes_text / cover_path_text / tag_chips

测试使用 tmp_path + init_db 构造真实 service。
QMessageBox 通过 monkeypatch 替换为 lambda，避免模态阻塞。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from app.metadata_panel import MetadataPanel  # noqa: E402
from application.content_service import ContentService  # noqa: E402
from application.errors import InvalidMetadataError  # noqa: E402
from application.tag_service import TagService  # noqa: E402
from domain.models import ContentUnit  # noqa: E402
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
def unit_with_tags(services, tmp_path):
    """构造一个已标记的 ContentUnit + 2 个分类 + 2 个标签（已关联 1 个）。"""
    content_service, tag_service, conn, content_repo = services

    # 内容单元对应真实文件夹（用于封面路径校验）
    unit_folder = tmp_path / "MyMod"
    unit_folder.mkdir()
    # 写入一张图片作为封面候选
    (unit_folder / "cover.jpg").write_bytes(b"\x00" * 50)

    unit = content_service.mark_as_content_unit(unit_folder)
    conn.commit()

    # 创建分类 + 标签
    cat1 = tag_service.create_category("服装护甲", color_hue=210)
    cat2 = tag_service.create_category("状态", color_hue=120)
    tag1 = tag_service.create_tag("重甲", cat1.id)  # 将与 unit 关联
    tag2 = tag_service.create_tag("已测试", cat2.id)  # 不关联
    tag_service.attach_tag_to_unit(unit.id, tag1.id)
    conn.commit()

    yield content_service, tag_service, conn, content_repo, unit, cat1, cat2, tag1, tag2


# === 初始状态 ===


def test_panel_initial_state(qapp, services):
    """新建面板：无 unit / 表单禁用 / hint 显示。"""
    content_service, tag_service, _, _ = services
    panel = MetadataPanel(content_service, tag_service)

    assert panel.current_unit() is None
    assert panel.title_text() == ""
    assert panel.source_url_text() == ""
    assert panel.notes_text() == ""
    assert panel.tag_chips() == []
    assert not panel.is_form_enabled()
    assert not panel.is_save_button_enabled()
    assert not panel.is_pick_cover_button_enabled()


# === load_unit ===


def test_panel_load_unit_fills_fields(qapp, unit_with_tags):
    """load_unit 后字段被填充，表单启用。"""
    _, _, _, _, unit, *_ = unit_with_tags
    (
        content_service,
        tag_service,
        _,
        _,
    ) = (
        unit_with_tags[0],
        unit_with_tags[1],
        unit_with_tags[2],
        unit_with_tags[3],
    )
    panel = MetadataPanel(content_service, tag_service)

    panel.load_unit(unit)
    assert panel.current_unit() is not None
    assert panel.current_unit().id == unit.id
    # mark_as_content_unit 默认 title = 文件夹名
    assert panel.title_text() == "MyMod"
    assert panel.is_form_enabled()
    assert panel.is_save_button_enabled()
    assert panel.is_pick_cover_button_enabled()


def test_panel_load_unit_loads_existing_tags(qapp, unit_with_tags):
    """load_unit 后已关联的标签显示为 chip。"""
    content_service, tag_service, _, _, unit, _, _, tag1, _ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)

    panel.load_unit(unit)
    assert panel.tag_chips() == [tag1.name]


def test_panel_load_unit_loads_cover_preview(qapp, unit_with_tags):
    """load_unit 后封面字段正确显示（unit 无封面时显示未设置）。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)

    panel.load_unit(unit)
    # mark_as_content_unit 自动录入目录下第一张图作为封面
    assert panel.cover_path_text() == "cover.jpg"


def test_panel_load_none_clears(qapp, unit_with_tags):
    """load_unit(None) 等同于 clear_panel。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)
    assert panel.current_unit() is not None

    panel.load_unit(None)
    assert panel.current_unit() is None
    assert panel.title_text() == ""
    assert not panel.is_form_enabled()


# === clear_panel ===


def test_clear_panel_resets_all(qapp, unit_with_tags):
    """clear_panel 清空所有字段并禁用表单。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    panel.clear_panel()
    assert panel.current_unit() is None
    assert panel.title_text() == ""
    assert panel.source_url_text() == ""
    assert panel.notes_text() == ""
    assert panel.tag_chips() == []
    assert not panel.is_form_enabled()


# === 标签 chip 操作 ===


def test_add_tag_chip_via_input(qapp, unit_with_tags, monkeypatch):
    """输入已存在标签名回车 → 添加到 chip 列表。"""
    content_service, tag_service, _, _, unit, _, _, tag1, tag2 = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    # 初始只有 tag1
    assert panel.tag_chips() == [tag1.name]

    # 输入 tag2 名称回车
    panel.add_tag_via_input(tag2.name)
    assert tag2.name in panel.tag_chips()
    assert len(panel.tag_chips()) == 2


def test_add_tag_chip_unknown_warns(qapp, unit_with_tags, monkeypatch):
    """输入不存在的标签名 → 弹 QMessageBox.information 提示，不添加。"""
    content_service, tag_service, _, _, unit, _, _, tag1, _ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    info_calls = []
    monkeypatch.setattr(
        "app.metadata_panel.QMessageBox.information", lambda *a, **kw: info_calls.append(a)
    )
    panel.add_tag_via_input("不存在的标签名")
    assert len(info_calls) == 1
    assert panel.tag_chips() == [tag1.name]  # 仍只有 tag1


def test_add_tag_chip_duplicate_warns(qapp, unit_with_tags, monkeypatch):
    """输入已添加的标签名 → 弹 QMessageBox.information 提示，不重复添加。"""
    content_service, tag_service, _, _, unit, _, _, tag1, _ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    info_calls = []
    monkeypatch.setattr(
        "app.metadata_panel.QMessageBox.information", lambda *a, **kw: info_calls.append(a)
    )
    panel.add_tag_via_input(tag1.name)
    assert len(info_calls) == 1
    assert panel.tag_chips() == [tag1.name]


def test_add_tag_chip_empty_name_no_op(qapp, unit_with_tags, monkeypatch):
    """输入空白名称回车 → 不调用 QMessageBox，不添加。"""
    content_service, tag_service, _, _, unit, _, _, tag1, _ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    info_calls = []
    monkeypatch.setattr(
        "app.metadata_panel.QMessageBox.information", lambda *a, **kw: info_calls.append(a)
    )
    panel.add_tag_via_input("   ")
    assert info_calls == []
    assert panel.tag_chips() == [tag1.name]


def test_remove_tag_chip_on_click(qapp, unit_with_tags, monkeypatch):
    """chip 单击 → 移除该标签。"""
    content_service, tag_service, _, _, unit, _, _, tag1, tag2 = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)
    panel.add_tag_via_input(tag2.name)
    assert len(panel.tag_chips()) == 2

    # 点击 tag1 chip 移除
    panel.click_tag_chip(tag1.name)
    assert tag1.name not in panel.tag_chips()
    assert tag2.name in panel.tag_chips()


# === 预选标签区域 ===


def test_preset_list_initially_empty(qapp, services):
    """无 unit 加载时：预选列表为空。"""
    content_service, tag_service, _, _ = services
    panel = MetadataPanel(content_service, tag_service)

    assert panel.preset_tag_names() == []


def test_preset_list_populated_on_load_unit(qapp, unit_with_tags):
    """load_unit → 预选列表填充所有标签，排除已在 chip 列表的。"""
    content_service, tag_service, _, _, unit, _, _, tag1, tag2 = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)

    panel.load_unit(unit)
    # unit 已关联 tag1，预选列表只应包含 tag2
    assert panel.preset_tag_names() == [tag2.name]


def test_click_preset_tag_adds_to_chips(qapp, unit_with_tags):
    """单击预选标签 → 添加到 chip 列表，并从预选列表移除。"""
    content_service, tag_service, _, _, unit, _, _, tag1, tag2 = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)
    assert panel.preset_tag_names() == [tag2.name]
    assert panel.tag_chips() == [tag1.name]

    # 点击预选 tag2
    panel.click_preset_tag(tag2.name)
    qapp.processEvents()

    # chip 列表应包含 tag1 + tag2，预选列表应为空
    assert tag2.name in panel.tag_chips()
    assert tag2.name not in panel.preset_tag_names()


def test_remove_chip_adds_back_to_preset(qapp, unit_with_tags):
    """chip 移除 → 该标签回到预选列表（排除已添加的）。"""
    content_service, tag_service, _, _, unit, _, _, tag1, tag2 = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    # 先把 tag2 加到 chip
    panel.click_preset_tag(tag2.name)
    assert tag2.name not in panel.preset_tag_names()
    assert tag2.name in panel.tag_chips()

    # 移除 tag2 chip
    panel.click_tag_chip(tag2.name)
    assert tag2.name not in panel.tag_chips()
    # tag2 应该回到预选列表
    assert tag2.name in panel.preset_tag_names()


def test_clear_panel_clears_preset_list(qapp, unit_with_tags):
    """clear_panel → 预选列表清空。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)
    assert panel.preset_tag_names() != []

    panel.clear_panel()
    assert panel.preset_tag_names() == []


def test_preset_list_excludes_all_chips(qapp, unit_with_tags):
    """所有 chip 标签都应排除出预选列表（多标签场景）。"""
    content_service, tag_service, _, _, unit, _, _, tag1, tag2 = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)
    # 初始 chip = [tag1]，预选 = [tag2]
    panel.click_preset_tag(tag2.name)
    # 现在 chip = [tag1, tag2]，预选 = []
    assert panel.preset_tag_names() == []
    assert len(panel.tag_chips()) == 2


# === 自动补全 ===


def test_completer_loaded_on_load_unit(qapp, unit_with_tags):
    """load_unit 后 QCompleter 模型填充所有标签名。"""
    content_service, tag_service, _, _, unit, _, _, tag1, tag2 = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    completer = panel._tag_input.completer()  # noqa: SLF001
    model = completer.model()
    # 应包含 tag1 / tag2 两个名称
    names = [model.data(model.index(i, 0)) for i in range(model.rowCount())]
    assert tag1.name in names
    assert tag2.name in names


# === 保存 ===


def test_save_writes_metadata(qapp, unit_with_tags):
    """保存 → ContentService.update_metadata 写入 title/source_url/notes。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    panel._title_edit.setText("新标题")  # noqa: SLF001
    panel._source_url_edit.setText("https://example.com/mod")  # noqa: SLF001
    panel._notes_edit.setPlainText("测试备注")  # noqa: SLF001

    panel.click_save_button()

    # 从数据库重新查询验证
    updated = content_service.get_by_id(unit.id)
    assert updated is not None
    assert updated.title == "新标题"
    assert updated.source_url == "https://example.com/mod"
    assert updated.notes == "测试备注"


def test_save_emits_on_saved_signal(qapp, unit_with_tags):
    """保存成功 → 发射 on_saved 信号，参数为更新后的 ContentUnit。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    received: list[ContentUnit] = []
    panel.on_saved.connect(lambda u: received.append(u))

    panel._title_edit.setText("信号测试")  # noqa: SLF001
    panel.click_save_button()

    assert len(received) == 1
    assert received[0].id == unit.id
    assert received[0].title == "信号测试"


def test_save_attaches_new_tags(qapp, unit_with_tags):
    """保存 → 新添加的 chip 写入 content_unit_tag。"""
    content_service, tag_service, _, _, unit, _, _, tag1, tag2 = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)
    # 添加 tag2
    panel.add_tag_via_input(tag2.name)
    assert tag2.name in panel.tag_chips()

    panel.click_save_button()

    # 重新加载验证
    panel.load_unit(unit)
    assert tag1.name in panel.tag_chips()
    assert tag2.name in panel.tag_chips()


def test_save_detaches_removed_tags(qapp, unit_with_tags):
    """保存 → 移除的 chip 从 content_unit_tag 删除。"""
    content_service, tag_service, _, _, unit, _, _, tag1, _ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)
    assert tag1.name in panel.tag_chips()

    # 移除 tag1
    panel.click_tag_chip(tag1.name)
    assert tag1.name not in panel.tag_chips()

    panel.click_save_button()

    # 重新加载验证
    panel.load_unit(unit)
    assert tag1.name not in panel.tag_chips()


def test_save_invalid_metadata_warns(qapp, unit_with_tags, monkeypatch):
    """保存时校验失败 → 弹 QMessageBox.warning，不发射 on_saved。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    # 设置超长 title 触发 InvalidMetadataError（_TITLE_MAX_LENGTH = 200）
    panel._title_edit.setText("x" * 300)  # noqa: SLF001

    warning_calls = []
    monkeypatch.setattr(
        "app.metadata_panel.QMessageBox.warning", lambda *a, **kw: warning_calls.append(a)
    )

    received: list[ContentUnit] = []
    panel.on_saved.connect(lambda u: received.append(u))

    panel.click_save_button()

    assert len(warning_calls) == 1
    assert received == []


def test_save_does_not_emit_on_failure(qapp, unit_with_tags, monkeypatch):
    """保存失败时 on_saved 不发射。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    # 通过 monkeypatch 让 update_metadata 抛错
    def _raise(*args, **kwargs):
        raise InvalidMetadataError("模拟失败")

    monkeypatch.setattr(content_service, "update_metadata", _raise)
    monkeypatch.setattr("app.metadata_panel.QMessageBox.warning", lambda *a, **kw: None)

    received: list[ContentUnit] = []
    panel.on_saved.connect(lambda u: received.append(u))

    panel.click_save_button()
    assert received == []


# === 封面 ===


def test_pick_cover_button_emits_signal(qapp, unit_with_tags):
    """点击「设置封面」→ 发射 on_pick_cover_requested 信号。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    received: list[str] = []
    panel.on_pick_cover_requested.connect(lambda uid: received.append(uid))

    panel.click_pick_cover_button()
    assert received == [unit.id]


def test_set_cover_path_updates_preview(qapp, unit_with_tags):
    """set_cover_path 后 cover_path_text 返回新路径。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)
    assert panel.cover_path_text() == "cover.jpg"  # mark 时自动录入

    panel.set_cover_path("preview.png")
    assert panel.cover_path_text() == "preview.png"


def test_cover_preview_uses_resizable_label(qapp, unit_with_tags):
    """Task 1b 修正：封面预览使用 _ResizableImageLabel，统一加载原图。

    验证：_cover_preview 为 _ResizableImageLabel 实例（支持宽度自适应缩放）。
    注意：fixture 中 cover.jpg 是假图片数据，pixmap 为 null，仅验证控件类型。
    """
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    # _cover_preview 应为 _ResizableImageLabel 实例
    from app.metadata_panel import _ResizableImageLabel

    assert isinstance(panel._cover_preview, _ResizableImageLabel)  # noqa: SLF001


def test_clear_cover_button_resets_preview(qapp, unit_with_tags):
    """点击「清除封面」→ cover_path_text 返回空字符串。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)
    panel.set_cover_path("cover.jpg")
    assert panel.cover_path_text() == "cover.jpg"

    panel._on_clear_cover_clicked()  # noqa: SLF001
    assert panel.cover_path_text() == ""


def test_save_persists_cover_path(qapp, unit_with_tags):
    """保存 → cover_path 写入数据库。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)
    panel.set_cover_path("cover.jpg")

    panel.click_save_button()

    updated = content_service.get_by_id(unit.id)
    assert updated is not None
    assert updated.cover_path == "cover.jpg"


def test_save_clears_cover_when_form_empty(qapp, unit_with_tags):
    """保存 → 表单中无封面时清空数据库 cover_path。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    # 先设置一个封面并保存
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)
    panel.set_cover_path("cover.jpg")
    panel.click_save_button()
    assert content_service.get_by_id(unit.id).cover_path == "cover.jpg"

    # 重新从数据库读取最新 unit 后再加载
    updated_unit = content_service.get_by_id(unit.id)
    assert updated_unit is not None
    panel.load_unit(updated_unit)
    panel._on_clear_cover_clicked()  # noqa: SLF001
    panel.click_save_button()

    final = content_service.get_by_id(unit.id)
    assert final is not None
    assert final.cover_path is None


# === 中文支持 ===


def test_save_chinese_metadata(qapp, unit_with_tags):
    """保存中文标题、URL、备注 → 正确写入。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    panel._title_edit.setText("寒霜之心-汉化")  # noqa: SLF001
    panel._notes_edit.setPlainText("这是一个中文备注")  # noqa: SLF001

    panel.click_save_button()

    updated = content_service.get_by_id(unit.id)
    assert updated is not None
    assert updated.title == "寒霜之心-汉化"
    assert updated.notes == "这是一个中文备注"


def test_add_chinese_tag_chip(qapp, unit_with_tags):
    """添加中文标签名 → 正常添加到 chip 列表。"""
    content_service, tag_service, _, _, unit, _, _, _, tag2 = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    panel.add_tag_via_input(tag2.name)  # "已测试"
    assert tag2.name in panel.tag_chips()


# === Stage 4.5 M18：标签 attach 失败路径测试 ===


def test_save_tag_attach_failure_emits_on_save_failed(qapp, unit_with_tags, monkeypatch):
    """标签 attach 抛 TagNotFoundError → 发射 on_save_failed，不发射 on_saved。

    M18 修复：标签关联失败时，metadata 已写入但标签关联失败，应通知
    MainWindow rollback 事务（避免"部分成功"状态被意外提交）。
    """
    from application.errors import TagNotFoundError

    content_service, tag_service, conn, _, unit, _, _, _, tag2 = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)
    # 添加 tag2 chip（让 to_add 非空，触发 attach_tag_to_unit 调用）
    panel.add_tag_via_input(tag2.name)
    assert tag2.name in panel.tag_chips()

    # 模拟 attach_tag_to_unit 抛 TagNotFoundError
    def _raise_tag_not_found(*args, **kwargs):
        raise TagNotFoundError("标签不存在（模拟）")

    monkeypatch.setattr(tag_service, "attach_tag_to_unit", _raise_tag_not_found)
    # 抑制 QMessageBox 模态对话框
    warning_calls = []
    monkeypatch.setattr(
        "app.metadata_panel.QMessageBox.warning", lambda *a, **kw: warning_calls.append(a)
    )

    saved: list[ContentUnit] = []
    failed: list[str] = []
    panel.on_saved.connect(lambda u: saved.append(u))
    panel.on_save_failed.connect(lambda msg: failed.append(msg))

    panel.click_save_button()

    # on_saved 不应发射
    assert saved == []
    # on_save_failed 应发射，包含错误消息
    assert len(failed) == 1
    assert "标签不存在" in failed[0]
    # 用户应看到错误提示
    assert len(warning_calls) == 1


def test_save_tag_attach_failure_does_not_persist(qapp, unit_with_tags, monkeypatch):
    """标签 attach 失败 → on_save_failed 通知 MainWindow rollback → metadata 未持久化。

    验证事务一致性：MainWindow 收到 on_save_failed 后调用 rollback，
    update_metadata 的写入应被回滚（title 未变更）。
    """
    from application.errors import TagNotFoundError

    content_service, tag_service, conn, content_repo, unit, _, _, _, tag2 = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)
    panel.add_tag_via_input(tag2.name)
    # 修改 title（触发 update_metadata 写入）
    panel._title_edit.setText("新标题-应被回滚")  # noqa: SLF001

    # 模拟 attach_tag_to_unit 抛 TagNotFoundError
    def _raise_tag_not_found(*args, **kwargs):
        raise TagNotFoundError("标签不存在（模拟）")

    monkeypatch.setattr(tag_service, "attach_tag_to_unit", _raise_tag_not_found)
    monkeypatch.setattr("app.metadata_panel.QMessageBox.warning", lambda *a, **kw: None)

    # 模拟 MainWindow 的 on_save_failed 回调：调用 conn.rollback()
    panel.on_save_failed.connect(lambda msg: conn.rollback())

    panel.click_save_button()

    # 验证 metadata 未持久化（被 rollback）
    # 重新从数据库读取 unit
    persisted_unit = content_repo.get_by_id(unit.id)
    assert persisted_unit is not None
    # title 应保持原值（未被修改为"新标题-应被回滚"）
    assert persisted_unit.title != "新标题-应被回滚"
