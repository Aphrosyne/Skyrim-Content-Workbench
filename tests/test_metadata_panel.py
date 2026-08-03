"""MetadataPanel 单元测试（Stage 4 Task 2）。

覆盖：
- 初始状态 / load_unit / clear_panel
- 标签 chip 添加（输入框回车）/ 移除（chip 点击）
- 标签自动补全（QCompleter QStringListModel）
- 保存按钮：成功写入 metadata + 标签 attach/detach diff + 发射 on_saved 信号
- 保存失败：InvalidMetadataError 弹 QMessageBox
- 封面即时保存（操作便捷性6）：on_pick_cover_requested 信号 + apply_cover 立即落库
- 清除封面按钮（同样立即落库）
- 测试接口：rename_text / source_url_text / notes_text / cover_path_text / tag_chips

测试使用 tmp_path + init_db 构造真实 service。
QMessageBox 通过 monkeypatch 替换为 lambda，避免模态阻塞。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402

from app.metadata_panel import MetadataPanel  # noqa: E402
from app.recent_tags import RecentTags  # noqa: E402
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
    assert panel.rename_text() == ""
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
    # 重命名栏显示真实文件名（UI合理性13）
    assert panel.rename_text() == "MyMod"
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
    assert panel.rename_text() == ""
    assert not panel.is_form_enabled()


# === clear_panel ===


def test_clear_panel_resets_all(qapp, unit_with_tags):
    """clear_panel 清空所有字段并禁用表单。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    panel.clear_panel()
    assert panel.current_unit() is None
    assert panel.rename_text() == ""
    assert panel.source_url_text() == ""
    assert panel.notes_text() == ""
    assert panel.tag_chips() == []
    assert not panel.is_form_enabled()


def test_clear_panel_disconnects_chip_handlers(qapp, unit_with_tags, monkeypatch):
    """测试稳定性1：clear_panel 后旧 chip 按钮信号已断开，点击不再触发操作。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)
    chips = [btn for _, btn in panel._chip_buttons]  # noqa: SLF001
    assert chips

    calls: list[tuple] = []
    monkeypatch.setattr(panel, "_apply_tag_toggle", lambda *a, **kw: calls.append(a))

    panel.clear_panel()
    for btn in chips:
        btn.click()

    assert calls == []  # 旧 chip 按钮信号已断开，点击无副作用


def test_clear_panel_drop_panel_handles_deferred_delete_safely(qapp, unit_with_tags):
    """测试稳定性1 回归：clear_panel 后 panel 回收 + DeferredDelete 处理不原生崩溃。

    修复前：chip 按钮 clicked lambda 闭包引用 self，deleteLater 后 panel 包装器回收，
    事件循环处理 DeferredDelete 时在按钮析构途中触发 panel 二次删除（Windows
    access violation / Fatal Python error: Aborted）。修复后应正常通过。
    该测试若回归会直接终止整个 pytest 进程（原生崩溃无法以异常捕获）。
    """
    from PySide6.QtCore import QCoreApplication, QEvent

    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)
    panel.clear_panel()
    del panel

    # 处理挂起的 DeferredDelete（等价于后续测试中 QEventLoop.exec 的行为）
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


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
    """保存 → ContentService.update_metadata 写入 source_url/notes（title 不再写）。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    panel._source_url_edit.setText("https://example.com/mod")  # noqa: SLF001
    panel._notes_edit.setPlainText("测试备注")  # noqa: SLF001

    panel.click_save_button()

    # 从数据库重新查询验证
    updated = content_service.get_by_id(unit.id)
    assert updated is not None
    assert updated.title is None  # UI合理性13：保存不再写 title
    assert updated.source_url == "https://example.com/mod"
    assert updated.notes == "测试备注"


def test_save_emits_on_saved_signal(qapp, unit_with_tags):
    """保存成功 → 发射 on_saved 信号，参数为更新后的 ContentUnit。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    received: list[ContentUnit] = []
    panel.on_saved.connect(lambda u: received.append(u))

    panel._notes_edit.setPlainText("信号测试")  # noqa: SLF001
    panel.click_save_button()

    assert len(received) == 1
    assert received[0].id == unit.id
    assert received[0].notes == "信号测试"


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

    # 设置超长 source_url 触发 InvalidMetadataError（_URL_MAX_LENGTH = 2000）
    panel._source_url_edit.setText("x" * 2001)  # noqa: SLF001

    warning_calls = []
    monkeypatch.setattr(
        "app.metadata_panel.QMessageBox.information", lambda *a, **kw: warning_calls.append(a)
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
    monkeypatch.setattr("app.metadata_panel.QMessageBox.information", lambda *a, **kw: None)

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


def test_apply_cover_persists_immediately(qapp, unit_with_tags):
    """操作便捷性6：apply_cover 立即写库 + 更新表单 + 提交回调 + 信号。"""
    content_service, tag_service, conn, _, unit, *_ = unit_with_tags
    # 目录内再放一张候选图（apply_cover 会校验文件存在）
    (Path(unit.path) / "preview.png").write_bytes(b"\x00" * 50)
    commits: list[str] = []
    saved_units: list[ContentUnit] = []
    panel = MetadataPanel(
        content_service,
        tag_service,
        commit_callback=lambda: commits.append("commit"),
    )
    panel.on_cover_saved.connect(lambda u: saved_units.append(u))
    panel.load_unit(unit)
    assert panel.cover_path_text() == "cover.jpg"  # mark 时自动录入

    panel.apply_cover("preview.png")

    assert content_service.get_by_id(unit.id).cover_path == "preview.png"
    assert panel.cover_path_text() == "preview.png"
    assert commits == ["commit"]
    assert [u.id for u in saved_units] == [unit.id]
    assert saved_units[0].cover_path == "preview.png"
    conn.commit()
    row = conn.execute("SELECT cover_path FROM content_unit WHERE id = ?", (unit.id,)).fetchone()
    assert row["cover_path"] == "preview.png"


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


def test_clear_cover_button_persists_immediately(qapp, unit_with_tags):
    """操作便捷性6：点击「清除封面」→ 立即清空数据库 + 表单。"""
    content_service, tag_service, conn, _, unit, *_ = unit_with_tags
    saved_units: list[ContentUnit] = []
    panel = MetadataPanel(content_service, tag_service)
    panel.on_cover_saved.connect(lambda u: saved_units.append(u))
    panel.load_unit(unit)
    assert panel.cover_path_text() == "cover.jpg"

    panel._on_clear_cover_clicked()  # noqa: SLF001

    assert panel.cover_path_text() == ""
    assert content_service.get_by_id(unit.id).cover_path is None
    assert len(saved_units) == 1
    assert saved_units[0].cover_path is None
    conn.commit()
    row = conn.execute("SELECT cover_path FROM content_unit WHERE id = ?", (unit.id,)).fetchone()
    assert row["cover_path"] is None


def test_save_persists_cover_path(qapp, unit_with_tags):
    """保存 → cover_path 写入数据库。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)
    panel.apply_cover("cover.jpg")

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
    panel.apply_cover("cover.jpg")
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


def test_apply_cover_keeps_unsaved_form_edits(qapp, unit_with_tags):
    """操作便捷性6：封面即时保存不重载表单，未保存的来源/备注编辑保留。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)
    panel._notes_edit.setPlainText("未保存的备注")  # noqa: SLF001

    panel.apply_cover("cover.jpg")

    assert panel.notes_text() == "未保存的备注"
    # 数据库备注未被封面保存改动
    assert content_service.get_by_id(unit.id).notes is None


def test_apply_cover_invalid_path_fails_without_changes(qapp, unit_with_tags, monkeypatch):
    """操作便捷性6：封面路径不存在 → 弹提示、不写库、表单不变。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    monkeypatch.setattr("app.metadata_panel.QMessageBox.information", lambda *a, **kw: None)
    saved_units: list[ContentUnit] = []
    panel = MetadataPanel(content_service, tag_service)
    panel.on_cover_saved.connect(lambda u: saved_units.append(u))
    panel.load_unit(unit)

    panel.apply_cover("missing.png")

    assert content_service.get_by_id(unit.id).cover_path == "cover.jpg"
    assert panel.cover_path_text() == "cover.jpg"
    assert saved_units == []


# === 重命名栏（UI合理性13） ===


def test_rename_field_shows_real_filename(qapp, unit_with_tags):
    """重命名栏显示真实文件名（path basename），而非 title。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    # unit 对应文件夹 MyMod（title 为 None），重命名栏显示文件名
    assert unit.title is None
    assert panel.rename_text() == "MyMod"


def test_rename_return_emits_request(qapp, unit_with_tags):
    """重命名栏回车 → 发射 rename_requested(unit_id, new_name)。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    received: list[tuple[str, str]] = []
    panel.rename_requested.connect(lambda unit_id, name: received.append((unit_id, name)))

    panel._rename_edit.setText("NewName")  # noqa: SLF001
    panel._on_rename_return()  # noqa: SLF001

    assert received == [(unit.id, "NewName")]


def test_rename_return_ignores_empty_and_unchanged(qapp, unit_with_tags):
    """重命名栏回车：空名称 / 名称未变化 → 不发射请求。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    received: list[tuple[str, str]] = []
    panel.rename_requested.connect(lambda unit_id, name: received.append((unit_id, name)))

    panel._rename_edit.setText("")  # noqa: SLF001
    panel._on_rename_return()  # noqa: SLF001

    # 与当前文件名相同 → 不发射
    panel._rename_edit.setText("MyMod")  # noqa: SLF001
    panel._on_rename_return()  # noqa: SLF001

    assert received == []


def test_apply_renamed_unit_updates_name_only(qapp, unit_with_tags):
    """重命名成功后 apply_renamed_unit：更新文件名，保留未保存编辑。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)
    panel._notes_edit.setPlainText("未保存的备注")  # noqa: SLF001

    renamed = ContentUnit(
        id=unit.id,
        path=str(Path(unit.path).parent / "Renamed"),
        content_type=unit.content_type,
        created_at=unit.created_at,
        updated_at=unit.updated_at,
    )
    panel.apply_renamed_unit(renamed)

    assert panel.rename_text() == "Renamed"
    assert panel.notes_text() == "未保存的备注"
    assert panel.current_unit().path == renamed.path


# === 中文支持 ===


def test_save_chinese_metadata(qapp, unit_with_tags):
    """保存中文 URL、备注 → 正确写入（title 不再写）。"""
    content_service, tag_service, _, _, unit, *_ = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    panel._notes_edit.setPlainText("这是一个中文备注")  # noqa: SLF001

    panel.click_save_button()

    updated = content_service.get_by_id(unit.id)
    assert updated is not None
    assert updated.title is None  # UI合理性13：title 不再被写入
    assert updated.notes == "这是一个中文备注"


def test_add_chinese_tag_chip(qapp, unit_with_tags):
    """添加中文标签名 → 正常添加到 chip 列表。"""
    content_service, tag_service, _, _, unit, _, _, _, tag2 = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    panel.add_tag_via_input(tag2.name)  # "已测试"
    assert tag2.name in panel.tag_chips()


# === 操作便捷性4：标签即时保存失败路径（原 M18 保存期失败测试改写） ===


def test_immediate_tag_attach_failure_shows_error_and_keeps_state(
    qapp, unit_with_tags, monkeypatch
):
    """即时添加标签 attach 抛错 → 提示错误，chip 不添加，on_saved/on_save_failed 不发射。"""
    from application.errors import TagNotFoundError

    content_service, tag_service, _, _, unit, _, _, _, tag2 = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    # 模拟 attach_tag_to_unit 抛 TagNotFoundError
    def _raise_tag_not_found(*args, **kwargs):
        raise TagNotFoundError("标签不存在（模拟）")

    monkeypatch.setattr(tag_service, "attach_tag_to_unit", _raise_tag_not_found)
    # 抑制 QMessageBox 模态对话框
    warning_calls = []
    monkeypatch.setattr(
        "app.metadata_panel.QMessageBox.information", lambda *a, **kw: warning_calls.append(a)
    )

    saved: list[ContentUnit] = []
    failed: list[str] = []
    panel.on_saved.connect(lambda u: saved.append(u))
    panel.on_save_failed.connect(lambda msg: failed.append(msg))

    panel.add_tag_via_input(tag2.name)

    # 错误提示出现
    assert len(warning_calls) == 1
    # chip 不添加（本地状态未变）
    assert tag2.name not in panel.tag_chips()
    # on_saved / on_save_failed 均不发射（即时路径不经过保存按钮）
    assert saved == []
    assert failed == []


def test_immediate_tag_attach_failure_does_not_attach(qapp, unit_with_tags, monkeypatch):
    """即时添加标签 attach 失败 → 数据库无该关联写入。"""
    from application.errors import TagNotFoundError

    content_service, tag_service, conn, _, unit, _, _, _, tag2 = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    # 模拟 attach_tag_to_unit 抛 TagNotFoundError
    def _raise_tag_not_found(*args, **kwargs):
        raise TagNotFoundError("标签不存在（模拟）")

    monkeypatch.setattr(tag_service, "attach_tag_to_unit", _raise_tag_not_found)
    monkeypatch.setattr("app.metadata_panel.QMessageBox.information", lambda *a, **kw: None)

    panel.add_tag_via_input(tag2.name)

    # 数据库无该标签关联（即时保存失败不写库）
    rows = conn.execute(
        "SELECT COUNT(*) FROM content_unit_tag WHERE content_unit_id = ? AND tag_id = ?",
        (unit.id, tag2.id),
    ).fetchone()
    assert rows[0] == 0


# === UI合理性8 / 操作便捷性4：分组预选 / 最近标签 / 即时保存（2026-08-02） ===


def _make_recent_tags(tmp_path: Path, tag_ids: list[str]) -> RecentTags:
    """构造指向临时 ini 的 RecentTags 并预置记录。"""
    recent = RecentTags(QSettings(str(tmp_path / "tags.ini"), QSettings.Format.IniFormat))
    for tag_id in tag_ids:
        recent.record(tag_id)
    return recent


def test_preset_list_grouped_by_category(qapp, unit_with_tags):
    """UI合理性8：预选标签按分类分组显示（分组头 + 组内标签）。"""
    content_service, tag_service, _, _, unit, cat1, cat2, tag1, tag2 = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    # 分组头存在（服装护甲组为空——tag1 已关联，该组不显示；状态组显示 tag2）
    assert panel.preset_group_names() == [cat2.name]
    # 组内标签按名称显示；已关联的 tag1 不显示
    assert panel.preset_tag_names() == [tag2.name]


def test_preset_group_collapse_toggle(qapp, unit_with_tags):
    """UI合理性8：点击分组头折叠/展开组内标签。"""
    content_service, tag_service, _, _, unit, cat1, cat2, tag1, tag2 = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    # 初始展开
    assert not panel.is_preset_group_collapsed(cat2.id)
    flow = panel._preset_groups[cat2.id]  # noqa: SLF001
    assert not flow.isHidden()

    panel.click_preset_group(cat2.name)
    assert panel.is_preset_group_collapsed(cat2.id)
    assert flow.isHidden()

    panel.click_preset_group(cat2.name)
    assert not panel.is_preset_group_collapsed(cat2.id)
    assert not flow.isHidden()


def test_immediate_tag_add_persists_and_commits(qapp, unit_with_tags, tmp_path):
    """操作便捷性4：点击预选标签立即写库并触发提交回调。"""
    content_service, tag_service, conn, _, unit, cat1, cat2, tag1, tag2 = unit_with_tags
    commits: list[str] = []
    panel = MetadataPanel(
        content_service,
        tag_service,
        commit_callback=lambda: commits.append("commit"),
    )
    panel.load_unit(unit)

    panel.click_preset_tag(tag2.name)

    rows = conn.execute(
        "SELECT COUNT(*) FROM content_unit_tag WHERE content_unit_id = ? AND tag_id = ?",
        (unit.id, tag2.id),
    ).fetchone()
    assert rows[0] == 1
    assert commits == ["commit"]
    assert tag2.name in panel.tag_chips()


def test_immediate_tag_remove_persists(qapp, unit_with_tags):
    """操作便捷性4：点击 chip 立即 detach 并写库。"""
    content_service, tag_service, conn, _, unit, cat1, cat2, tag1, tag2 = unit_with_tags
    panel = MetadataPanel(content_service, tag_service)
    panel.load_unit(unit)

    panel.click_tag_chip(tag1.name)

    rows = conn.execute(
        "SELECT COUNT(*) FROM content_unit_tag WHERE content_unit_id = ? AND tag_id = ?",
        (unit.id, tag1.id),
    ).fetchone()
    assert rows[0] == 0
    assert tag1.name not in panel.tag_chips()


def test_recent_tags_area_shows_and_adds(qapp, unit_with_tags, tmp_path):
    """UI合理性8：最近标签区域显示并可点击即时添加。"""
    content_service, tag_service, conn, _, unit, cat1, cat2, tag1, tag2 = unit_with_tags
    recent = _make_recent_tags(tmp_path, [tag2.id])
    panel = MetadataPanel(content_service, tag_service, recent_tags=recent)
    panel.load_unit(unit)

    assert panel.recent_tag_names() == [tag2.name]

    panel.click_recent_tag(tag2.name)

    rows = conn.execute(
        "SELECT COUNT(*) FROM content_unit_tag WHERE content_unit_id = ? AND tag_id = ?",
        (unit.id, tag2.id),
    ).fetchone()
    assert rows[0] == 1
    assert tag2.name in panel.tag_chips()


def test_recent_tag_already_in_chip_disabled(qapp, unit_with_tags, tmp_path):
    """UI合理性8：已在 chip 的最近标签灰显不可点。"""
    content_service, tag_service, _, _, unit, cat1, cat2, tag1, tag2 = unit_with_tags
    recent = _make_recent_tags(tmp_path, [tag1.id])
    panel = MetadataPanel(content_service, tag_service, recent_tags=recent)
    panel.load_unit(unit)

    assert tag1.name in panel.recent_tag_names()
    assert not panel.is_recent_tag_enabled(tag1.name)


def test_immediate_tag_add_records_recent(qapp, unit_with_tags, tmp_path):
    """操作便捷性4：即时添加标签后记录到最近标签。"""
    content_service, tag_service, _, _, unit, cat1, cat2, tag1, tag2 = unit_with_tags
    recent = _make_recent_tags(tmp_path, [])
    panel = MetadataPanel(content_service, tag_service, recent_tags=recent)
    panel.load_unit(unit)

    panel.click_preset_tag(tag2.name)

    assert recent.list_recent() == [tag2.id]
