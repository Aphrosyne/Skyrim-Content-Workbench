"""TagFilterBar 单元测试（Stage 4 Task 3）。

覆盖：
- 初始状态（无分类隐藏 / 有分类显示）
- 分类按钮渲染
- 单击分类展开/折叠（互斥）
- 标签按钮多选 toggle
- 信号发射（on_filter_changed 携带 set[tag_id]）
- 清除全部按钮（可用性 + 行为）
- 折叠分类保留已选标签状态
- 折叠态下分类按钮显示已选数徽标
- refresh_categories 保留/剔除已选标签
- is_filter_active / current_selected_tag_ids / has_categories
"""

from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("PySide6")

from app.tag_colors import category_color_hex  # noqa: E402
from app.tag_filter import TagFilterBar  # noqa: E402
from application.tag_service import TagService  # noqa: E402
from infrastructure.repositories.content_unit_tag import (  # noqa: E402
    ContentUnitTagRepository,
)
from infrastructure.repositories.tag import TagRepository  # noqa: E402
from infrastructure.repositories.tag_category import (  # noqa: E402
    TagCategoryRepository,
)


def _make_tag_service(conn: sqlite3.Connection) -> TagService:
    return TagService(
        TagCategoryRepository(conn),
        TagRepository(conn),
        ContentUnitTagRepository(conn),
    )


def _click_button(bar: TagFilterBar, button) -> None:
    """模拟按钮点击。"""
    button.click()


def _find_category_button(bar: TagFilterBar, category_name: str):
    """在分类按钮组中查找指定名称的按钮。"""
    for btn in bar._category_buttons.values():  # noqa: SLF001
        # 去掉徽标后缀（空格 + 数字），匹配纯分类名
        text = btn.text()
        if text.rsplit(" ", 1)[-1].isdigit():
            text = text.rsplit(" ", 1)[0]
        if text == category_name:
            return btn
    return None


def _find_tag_button(bar: TagFilterBar, tag_name: str):
    """在标签按钮组中查找指定名称的按钮。"""
    for btn in bar._tag_buttons.values():  # noqa: SLF001
        if btn.text() == tag_name:
            return btn
    return None


@pytest.fixture
def tag_service_with_categories(db_connection: sqlite3.Connection):
    """构造含两个分类与多个标签的 TagService。"""
    service = _make_tag_service(db_connection)
    cat_armor = service.create_category("服装护甲")  # noqa: F841
    cat_status = service.create_category("状态")
    tag_heavy = service.create_tag("重甲", cat_armor.id)  # noqa: F841
    tag_light = service.create_tag("轻甲", cat_armor.id)  # noqa: F841
    tag_tested = service.create_tag("已测试", cat_status.id)
    return service, cat_armor, cat_status, tag_heavy, tag_light, tag_tested


# === 初始状态 ===


def test_initial_state_no_categories_hidden(qapp, db_connection: sqlite3.Connection):
    """无分类 → 控件隐藏。"""
    service = _make_tag_service(db_connection)
    bar = TagFilterBar(service)
    bar.refresh_categories()
    assert not bar.isVisible()  # 控件未显示
    assert not bar.has_categories()


def test_initial_state_with_categories_visible(qapp, tag_service_with_categories):
    """有分类 → 控件可见 + 分类按钮渲染 + 标签行默认折叠。"""
    service, *_ = tag_service_with_categories
    bar = TagFilterBar(service)
    bar.refresh_categories()
    assert bar.has_categories()
    # 分类按钮存在
    assert _find_category_button(bar, "服装护甲") is not None
    assert _find_category_button(bar, "状态") is not None
    # 默认无展开 → 标签行隐藏
    assert not bar._tag_row.isVisible()  # noqa: SLF001
    # 默认无已选 → 筛选未激活
    assert not bar.is_filter_active()
    assert bar.current_selected_tag_ids() == set()


def test_tag_buttons_filled_by_category_and_category_plain(qapp, tag_service_with_categories):
    """BugFix2 验收反馈：标签按钮背景/边框统一分类色；分类按钮不着色。"""
    service, cat_armor, *_ = tag_service_with_categories
    bar = TagFilterBar(service)
    bar.refresh_categories()
    bar._on_category_clicked(cat_armor.id)  # noqa: SLF001 展开分类重建标签按钮

    btn = _find_tag_button(bar, "重甲")
    assert btn is not None
    assert category_color_hex(cat_armor.color_hue) in btn.styleSheet()

    cat_btn = _find_category_button(bar, cat_armor.name)
    assert cat_btn is not None
    assert category_color_hex(cat_armor.color_hue) not in cat_btn.styleSheet()


# === 分类展开/折叠 ===


def test_click_category_expands_tags(qapp, tag_service_with_categories):
    """单击分类 → 标签列表展开。"""
    service, cat_armor, *_ = tag_service_with_categories
    bar = TagFilterBar(service)
    bar.refresh_categories()

    btn = _find_category_button(bar, "服装护甲")
    _click_button(bar, btn)
    qapp.processEvents()

    assert bar._expanded_category_id == cat_armor.id  # noqa: SLF001
    assert bar._tag_row.isVisible()  # noqa: SLF001
    assert _find_tag_button(bar, "重甲") is not None
    assert _find_tag_button(bar, "轻甲") is not None


def test_click_category_again_collapses(qapp, tag_service_with_categories):
    """再次单击已展开分类 → 折叠。"""
    service, cat_armor, *_ = tag_service_with_categories
    bar = TagFilterBar(service)
    bar.refresh_categories()

    btn = _find_category_button(bar, "服装护甲")
    _click_button(bar, btn)
    _click_button(bar, btn)
    qapp.processEvents()

    assert bar._expanded_category_id is None  # noqa: SLF001
    assert not bar._tag_row.isVisible()  # noqa: SLF001


def test_click_new_category_collapses_old(qapp, tag_service_with_categories):
    """互斥展开：点击新分类自动折叠旧分类。"""
    service, cat_armor, cat_status, *_ = tag_service_with_categories
    bar = TagFilterBar(service)
    bar.refresh_categories()

    btn_armor = _find_category_button(bar, "服装护甲")
    btn_status = _find_category_button(bar, "状态")
    _click_button(bar, btn_armor)
    _click_button(bar, btn_status)
    qapp.processEvents()

    assert bar._expanded_category_id == cat_status.id  # noqa: SLF001
    # 仅展开状态的标签按钮存在
    assert _find_tag_button(bar, "已测试") is not None
    assert _find_tag_button(bar, "重甲") is None


# === 标签多选 toggle ===


def test_click_tag_toggles_selection(qapp, tag_service_with_categories):
    """UI合理性16：标签三态循环 未选 → 已选 → 已排除 → 未选。"""
    service, cat_armor, _, tag_heavy, *_ = tag_service_with_categories
    bar = TagFilterBar(service)
    bar.refresh_categories()

    btn_cat = _find_category_button(bar, "服装护甲")
    _click_button(bar, btn_cat)
    btn_tag = _find_tag_button(bar, "重甲")
    _click_button(bar, btn_tag)
    qapp.processEvents()

    assert tag_heavy.id in bar.current_selected_tag_ids()
    assert bar.is_filter_active()

    # 第二次点击 → 反选（排除）
    _click_button(bar, btn_tag)
    qapp.processEvents()

    assert tag_heavy.id not in bar.current_selected_tag_ids()
    assert bar.current_excluded_tag_ids() == {tag_heavy.id}
    assert bar.is_filter_active()  # 反选仍视为筛选激活
    # 反选态按钮为删除线
    assert btn_tag.font().strikeOut()

    # 第三次点击 → 取消选择
    _click_button(bar, btn_tag)
    qapp.processEvents()

    assert tag_heavy.id not in bar.current_selected_tag_ids()
    assert bar.current_excluded_tag_ids() == set()
    assert not bar.is_filter_active()


def test_click_tag_emits_filter_changed(qapp, tag_service_with_categories):
    """选中标签 → 发射 on_filter_changed 信号，携带 tag_id 集合。"""
    service, cat_armor, _, tag_heavy, *_ = tag_service_with_categories
    bar = TagFilterBar(service)
    bar.refresh_categories()

    received: list[set] = []
    bar.on_filter_changed.connect(lambda s: received.append(s))

    btn_cat = _find_category_button(bar, "服装护甲")
    _click_button(bar, btn_cat)
    btn_tag = _find_tag_button(bar, "重甲")
    _click_button(bar, btn_tag)
    qapp.processEvents()

    assert len(received) >= 1
    assert tag_heavy.id in received[-1]


def test_click_multiple_tags_in_same_category_union(qapp, tag_service_with_categories):
    """同分类多标签 → 全部加入已选集合（OR）。"""
    service, cat_armor, _, tag_heavy, tag_light, _ = tag_service_with_categories
    bar = TagFilterBar(service)
    bar.refresh_categories()

    btn_cat = _find_category_button(bar, "服装护甲")
    _click_button(bar, btn_cat)
    _click_button(bar, _find_tag_button(bar, "重甲"))
    _click_button(bar, _find_tag_button(bar, "轻甲"))
    qapp.processEvents()

    assert bar.current_selected_tag_ids() == {tag_heavy.id, tag_light.id}


# === 清除全部按钮 ===


def test_clear_button_disabled_initially(qapp, tag_service_with_categories):
    """无已选标签 → 清除按钮禁用。"""
    service, *_ = tag_service_with_categories
    bar = TagFilterBar(service)
    bar.refresh_categories()

    assert not bar._clear_button.isEnabled()  # noqa: SLF001


def test_clear_button_enabled_after_select(qapp, tag_service_with_categories):
    """有已选标签 → 清除按钮启用。"""
    service, cat_armor, _, tag_heavy, *_ = tag_service_with_categories
    bar = TagFilterBar(service)
    bar.refresh_categories()

    _click_button(bar, _find_category_button(bar, "服装护甲"))
    _click_button(bar, _find_tag_button(bar, "重甲"))
    qapp.processEvents()

    assert bar._clear_button.isEnabled()  # noqa: SLF001


def test_clear_button_clears_selection(qapp, tag_service_with_categories):
    """点击清除按钮 → 清空已选 + 发射空集合信号。"""
    service, cat_armor, _, tag_heavy, *_ = tag_service_with_categories
    bar = TagFilterBar(service)
    bar.refresh_categories()

    _click_button(bar, _find_category_button(bar, "服装护甲"))
    _click_button(bar, _find_tag_button(bar, "重甲"))
    qapp.processEvents()

    received: list[set] = []
    bar.on_filter_changed.connect(lambda s: received.append(s))

    _click_button(bar, bar._clear_button)  # noqa: SLF001
    qapp.processEvents()

    assert bar.current_selected_tag_ids() == set()
    assert not bar.is_filter_active()
    assert received[-1] == set()
    assert not bar._clear_button.isEnabled()  # noqa: SLF001


# === 折叠保留已选 + 徽标 ===


def test_collapse_category_preserves_selection(qapp, tag_service_with_categories):
    """折叠分类不取消已选标签。"""
    service, cat_armor, _, tag_heavy, *_ = tag_service_with_categories
    bar = TagFilterBar(service)
    bar.refresh_categories()

    btn_cat = _find_category_button(bar, "服装护甲")
    _click_button(bar, btn_cat)
    _click_button(bar, _find_tag_button(bar, "重甲"))
    qapp.processEvents()

    # 折叠
    _click_button(bar, btn_cat)
    qapp.processEvents()

    assert tag_heavy.id in bar.current_selected_tag_ids()
    assert bar.is_filter_active()


def test_category_button_shows_selected_count_badge(qapp, tag_service_with_categories):
    """折叠态下分类按钮显示已选数徽标。"""
    service, cat_armor, _, tag_heavy, tag_light, _ = tag_service_with_categories
    bar = TagFilterBar(service)
    bar.refresh_categories()

    btn_cat = _find_category_button(bar, "服装护甲")
    # 展开并选 2 个标签
    _click_button(bar, btn_cat)
    _click_button(bar, _find_tag_button(bar, "重甲"))
    _click_button(bar, _find_tag_button(bar, "轻甲"))
    # 折叠
    _click_button(bar, btn_cat)
    qapp.processEvents()

    text = btn_cat.text()
    assert "服装护甲" in text
    assert "服装护甲 2" in text


# === refresh_categories ===


def test_refresh_preserves_valid_selection(qapp, tag_service_with_categories):
    """refresh 后已选标签若仍存在则保留。"""
    service, cat_armor, _, tag_heavy, *_ = tag_service_with_categories
    bar = TagFilterBar(service)
    bar.refresh_categories()

    _click_button(bar, _find_category_button(bar, "服装护甲"))
    _click_button(bar, _find_tag_button(bar, "重甲"))
    qapp.processEvents()

    # refresh（标签库未变）
    bar.refresh_categories()
    qapp.processEvents()

    assert tag_heavy.id in bar.current_selected_tag_ids()


def test_refresh_drops_deleted_tags(
    qapp, db_connection: sqlite3.Connection, tag_service_with_categories
):
    """refresh 后已删除的 tag_id 自动从已选中剔除。"""
    service, cat_armor, _, tag_heavy, *_ = tag_service_with_categories
    bar = TagFilterBar(service)
    bar.refresh_categories()

    _click_button(bar, _find_category_button(bar, "服装护甲"))
    _click_button(bar, _find_tag_button(bar, "重甲"))
    qapp.processEvents()

    # 删除标签
    service.delete_tag(tag_heavy.id)
    db_connection.commit()

    received: list[set] = []
    bar.on_filter_changed.connect(lambda s: received.append(s))
    bar.refresh_categories()
    qapp.processEvents()

    assert tag_heavy.id not in bar.current_selected_tag_ids()
    assert not bar.is_filter_active()
    # 应发射空集合信号
    assert received and received[-1] == set()


# === 空分类 ===


def test_empty_category_shows_hint(qapp, db_connection: sqlite3.Connection):
    """分类下无标签 → 展开后显示空提示。"""
    service = _make_tag_service(db_connection)
    service.create_category("空分类")
    bar = TagFilterBar(service)
    bar.refresh_categories()

    btn = _find_category_button(bar, "空分类")
    _click_button(bar, btn)
    qapp.processEvents()

    # 标签行可见，但无标签按钮
    assert bar._tag_row.isVisible()  # noqa: SLF001
    assert not bar._tag_buttons  # noqa: SLF001


# === UI合理性16：反选（三态）补充 ===


def test_multiple_exclusions_coexist_and_emit_signal(qapp, tag_service_with_categories):
    """多个反选标签并存，on_exclusion_changed 携带排除集合。"""
    service, cat_armor, _, tag_heavy, tag_light, _ = tag_service_with_categories
    bar = TagFilterBar(service)
    bar.refresh_categories()

    received: list[str] = []
    bar.on_exclusion_changed.connect(received.append)

    _click_button(bar, _find_category_button(bar, "服装护甲"))
    heavy = _find_tag_button(bar, "重甲")
    light = _find_tag_button(bar, "轻甲")
    _click_button(bar, heavy)  # 已选
    _click_button(bar, heavy)  # 反选 重甲
    assert bar.current_excluded_tag_ids() == {tag_heavy.id}

    _click_button(bar, light)  # 已选
    _click_button(bar, light)  # 反选 轻甲（与重甲并存）
    assert bar.current_excluded_tag_ids() == {tag_heavy.id, tag_light.id}
    assert bar._tag_states[tag_heavy.id] == 2  # noqa: SLF001 重甲仍为反选
    assert received[-1] == {tag_heavy.id, tag_light.id}


def test_clear_selection_resets_exclusion(qapp, tag_service_with_categories):
    """清除全部同时清除反选态。"""
    service, cat_armor, _, tag_heavy, *_ = tag_service_with_categories
    bar = TagFilterBar(service)
    bar.refresh_categories()

    _click_button(bar, _find_category_button(bar, "服装护甲"))
    heavy = _find_tag_button(bar, "重甲")
    _click_button(bar, heavy)
    _click_button(bar, heavy)
    assert bar.current_excluded_tag_ids() == {tag_heavy.id}

    bar.clear_selection()

    assert bar.current_excluded_tag_ids() == set()
    assert not bar.is_filter_active()
    assert not heavy.font().strikeOut()


def test_tag_states_no_width_jump_and_uniform_border(qapp, tag_service_with_categories):
    """三态样式尺寸统一（2px 边框、预留宽度）→ 状态切换不跳动；已选加粗、排除删除线。"""
    service, cat_armor, _, tag_heavy, *_ = tag_service_with_categories
    bar = TagFilterBar(service)
    bar.refresh_categories()

    _click_button(bar, _find_category_button(bar, "服装护甲"))
    heavy = _find_tag_button(bar, "重甲")
    reserved = heavy.minimumWidth()
    assert reserved > 0
    assert "border: 2px" in heavy.styleSheet()  # 未选

    _click_button(bar, heavy)
    assert heavy.text() == "重甲"  # 文字不变（无 ✓/− 前缀）
    assert heavy.font().bold()
    assert "border: 2px" in heavy.styleSheet()  # 已选
    assert heavy.minimumWidth() == reserved  # 宽度不变
    assert heavy.sizeHint().width() <= reserved  # 不撑破预留宽度

    _click_button(bar, heavy)
    assert "border: 2px" in heavy.styleSheet()  # 已排除
    assert heavy.font().strikeOut()
    assert heavy.minimumWidth() == reserved  # 宽度不变
    assert heavy.sizeHint().width() <= reserved


def test_category_badge_does_not_change_button_width(qapp, tag_service_with_categories):
    """分类按钮预留徽标宽度：选中标签后徽标出现，按钮宽度不变（分类行不跳）。"""
    service, cat_armor, _, tag_heavy, *_ = tag_service_with_categories
    bar = TagFilterBar(service)
    bar.refresh_categories()

    btn_cat = _find_category_button(bar, "服装护甲")
    reserved = btn_cat.minimumWidth()
    assert reserved > 0

    _click_button(bar, btn_cat)
    _click_button(bar, _find_tag_button(bar, "重甲"))

    assert btn_cat.minimumWidth() == reserved
    assert btn_cat.sizeHint().width() <= reserved  # 徽标 " (1)" 不撑破预留宽度
