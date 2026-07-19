"""TagManagerDialog UI 测试（阶段 4 Task 1）。

覆盖：
- 构造与初始状态（空库 / 已有数据）；
- _refresh_tree 正确加载分类与标签；
- 空状态提示可见性；
- _selected_category / _selected_tag 逻辑；
- _make_category_item / _make_tag_item 渲染；
- _on_add_category 通过 monkeypatch 模拟 QInputDialog / QColorDialog；
- _on_delete_category / _on_delete_tag 通过 monkeypatch 模拟 QMessageBox.question；
- 异常路径：service 抛 ApplicationError 时弹 QMessageBox.critical（通过 monkeypatch 验证）。

模态对话框（QInputDialog / QColorDialog / QFileDialog）通过 monkeypatch
替换为非阻塞桩函数，避免阻塞测试。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QInputDialog, QMessageBox  # noqa: E402

from app.tag_manager_dialog import TagManagerDialog  # noqa: E402
from application.errors import DuplicateTagCategoryNameError  # noqa: E402
from application.tag_service import TagService  # noqa: E402
from domain.models import Tag, TagCategory  # noqa: E402
from infrastructure.repositories.content_unit_tag import ContentUnitTagRepository  # noqa: E402
from infrastructure.repositories.tag import TagRepository  # noqa: E402
from infrastructure.repositories.tag_category import TagCategoryRepository  # noqa: E402


def _make_service(conn: sqlite3.Connection) -> TagService:
    counter = {"n": 0}

    def fake_uuid() -> str:
        counter["n"] += 1
        return f"id-{counter['n']}"

    return TagService(
        TagCategoryRepository(conn),
        TagRepository(conn),
        ContentUnitTagRepository(conn),
        now_provider=lambda: "2026-07-18T00:00:00Z",
        uuid_provider=fake_uuid,
    )


@pytest.fixture
def tag_dialog_env(qapp, db_path: Path):
    """构造 TagService + 数据库连接，返回 (service, conn)。"""
    from infrastructure.db import get_connection, init_db

    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    service = _make_service(conn)
    yield service, conn
    conn.close()


# === 构造与初始状态 ===


class TestConstruction:
    def test_empty_state_shows_hint(self, tag_dialog_env, qapp) -> None:
        service, conn = tag_dialog_env
        dialog = TagManagerDialog(service, parent=None)
        dialog.show()
        qapp.processEvents()
        # 空库时 empty_hint 应可见
        assert dialog._empty_hint.isVisible() is True
        # QTreeWidget 无顶层节点
        assert dialog._tree.topLevelItemCount() == 0
        dialog.close()

    def test_with_existing_data_hides_hint(self, tag_dialog_env, qapp) -> None:
        service, conn = tag_dialog_env
        cat = service.create_category("服装护甲", color_hue=210)
        service.create_tag("重甲", cat.id)
        service.create_tag("轻甲", cat.id)
        conn.commit()

        dialog = TagManagerDialog(service, parent=None)
        dialog.show()
        qapp.processEvents()
        # 已有数据时 empty_hint 应隐藏
        assert dialog._empty_hint.isVisible() is False
        # 顶层节点数 = 分类数
        assert dialog._tree.topLevelItemCount() == 1
        # 第一个分类下应有 2 个标签
        cat_item = dialog._tree.topLevelItem(0)
        assert cat_item.childCount() == 2
        dialog.close()

    def test_injected_callbacks_invoked_on_commit(self, tag_dialog_env) -> None:
        """注入的 commit_callback 在 dialog 内部 _commit() 时被调用。"""
        service, conn = tag_dialog_env
        commit_mock = MagicMock()
        rollback_mock = MagicMock()
        dialog = TagManagerDialog(
            service, commit_callback=commit_mock, rollback_callback=rollback_mock, parent=None
        )
        dialog._commit()
        commit_mock.assert_called_once()
        rollback_mock.assert_not_called()
        dialog.close()


# === _refresh_tree ===


class TestRefreshTree:
    def test_loads_categories_sorted_by_name(self, tag_dialog_env) -> None:
        service, conn = tag_dialog_env
        service.create_category("武器")
        service.create_category("服装护甲")
        service.create_category("来源")
        conn.commit()

        dialog = TagManagerDialog(service, parent=None)
        # 按 SQLite BINARY 排序（Unicode 码点）：服 < 来 < 武
        names = [dialog._tree.topLevelItem(i).text(0) for i in range(3)]
        assert "服装护甲" in names[0]
        assert "来源" in names[1]
        assert "武器" in names[2]
        dialog.close()

    def test_loads_tags_under_category(self, tag_dialog_env) -> None:
        service, conn = tag_dialog_env
        cat = service.create_category("服装护甲")
        service.create_tag("重甲", cat.id)
        service.create_tag("轻甲", cat.id)
        service.create_tag("法袍", cat.id)
        conn.commit()

        dialog = TagManagerDialog(service, parent=None)
        cat_item = dialog._tree.topLevelItem(0)
        # 按 name 排序
        tag_names = [cat_item.child(i).text(0) for i in range(3)]
        assert tag_names == ["法袍", "轻甲", "重甲"]
        dialog.close()

    def test_refresh_after_external_change(self, tag_dialog_env) -> None:
        """外部修改数据后调 _refresh_tree 应同步。"""
        service, conn = tag_dialog_env
        dialog = TagManagerDialog(service, parent=None)
        # 初始为空
        assert dialog._tree.topLevelItemCount() == 0

        # 外部新增分类
        service.create_category("新分类")
        conn.commit()
        dialog._refresh_tree()

        assert dialog._tree.topLevelItemCount() == 1
        dialog.close()


# === _make_category_item / _make_tag_item ===


class TestMakeItems:
    def test_category_item_stores_entity_and_color_icon(self, tag_dialog_env) -> None:
        service, conn = tag_dialog_env
        dialog = TagManagerDialog(service, parent=None)
        cat = TagCategory(id="c-1", name="服装护甲", color_hue=210)
        item = dialog._make_category_item(cat)
        assert item.data(0, Qt.UserRole + 2) is True  # _ROLE_IS_CATEGORY
        stored_cat = item.data(0, Qt.UserRole)
        assert stored_cat.id == "c-1"
        # 色块图标存在
        assert not item.icon(0).isNull()
        dialog.close()

    def test_tag_item_stores_entity(self, tag_dialog_env) -> None:
        service, conn = tag_dialog_env
        dialog = TagManagerDialog(service, parent=None)
        tag = Tag(id="t-1", name="重甲", category_id="c-1")
        item = dialog._make_tag_item(tag)
        assert item.data(0, Qt.UserRole + 2) is False  # _ROLE_IS_CATEGORY
        stored_tag = item.data(0, Qt.UserRole + 1)
        assert stored_tag.id == "t-1"
        # 标签节点无图标
        assert item.icon(0).isNull()
        dialog.close()


# === _selected_category / _selected_tag ===


class TestSelection:
    def test_no_selection_returns_none(self, tag_dialog_env) -> None:
        service, conn = tag_dialog_env
        cat = service.create_category("服装护甲")
        service.create_tag("重甲", cat.id)
        conn.commit()

        dialog = TagManagerDialog(service, parent=None)
        assert dialog._selected_category() is None
        assert dialog._selected_tag() is None
        dialog.close()

    def test_selected_category_returns_parent_when_tag_selected(self, tag_dialog_env) -> None:
        service, conn = tag_dialog_env
        cat = service.create_category("服装护甲")
        service.create_tag("重甲", cat.id)
        conn.commit()

        dialog = TagManagerDialog(service, parent=None)
        # 选中标签节点
        cat_item = dialog._tree.topLevelItem(0)
        tag_item = cat_item.child(0)
        tag_item.setSelected(True)
        dialog._tree.setCurrentItem(tag_item)

        result_cat = dialog._selected_category()
        assert result_cat is not None
        assert result_cat.id == cat.id

        result_tag = dialog._selected_tag()
        assert result_tag is not None
        assert result_tag.name == "重甲"
        dialog.close()


# === _on_add_category（通过 monkeypatch 模拟模态对话框） ===


class TestOnAddCategory:
    def test_creates_category_when_user_confirms(self, tag_dialog_env, monkeypatch) -> None:
        service, conn = tag_dialog_env
        dialog = TagManagerDialog(service, parent=None)

        # 模拟 QInputDialog.getText 返回 ("新分类", True)
        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("新分类", True))
        # 模拟 _ask_color_hue 返回 100（绕过 QColorDialog）
        monkeypatch.setattr(dialog, "_ask_color_hue", lambda default=210: 100)

        dialog._on_add_category()
        conn.commit()

        cats = service.list_categories()
        assert len(cats) == 1
        assert cats[0].name == "新分类"
        assert cats[0].color_hue == 100
        dialog.close()

    def test_skips_when_user_cancels_input(self, tag_dialog_env, monkeypatch) -> None:
        service, conn = tag_dialog_env
        dialog = TagManagerDialog(service, parent=None)

        # 模拟用户取消输入
        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("", False))
        dialog._on_add_category()
        # 未创建任何分类
        assert service.list_categories() == []
        dialog.close()

    def test_skips_when_user_cancels_color(self, tag_dialog_env, monkeypatch) -> None:
        service, conn = tag_dialog_env
        dialog = TagManagerDialog(service, parent=None)

        # 输入有效名称，但颜色对话框被取消
        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("新分类", True))
        monkeypatch.setattr(dialog, "_ask_color_hue", lambda default=210: None)
        dialog._on_add_category()
        # 未创建任何分类
        assert service.list_categories() == []
        dialog.close()

    def test_duplicate_name_shows_error(self, tag_dialog_env, monkeypatch) -> None:
        service, conn = tag_dialog_env
        service.create_category("已存在")
        conn.commit()

        dialog = TagManagerDialog(service, parent=None)

        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("已存在", True))
        monkeypatch.setattr(dialog, "_ask_color_hue", lambda default=210: 100)
        # 拦截 QMessageBox.critical 避免阻塞
        critical_mock = MagicMock()
        monkeypatch.setattr(QMessageBox, "critical", critical_mock)

        dialog._on_add_category()

        # 应弹出错误对话框
        assert critical_mock.called
        # 数据库中分类数仍为 1（原已存在的）
        assert len(service.list_categories()) == 1
        dialog.close()


# === _on_delete_category / _on_delete_tag ===


class TestOnDelete:
    def test_delete_category_with_confirm(self, tag_dialog_env, monkeypatch) -> None:
        service, conn = tag_dialog_env
        cat = service.create_category("服装护甲")
        service.create_tag("重甲", cat.id)
        conn.commit()

        dialog = TagManagerDialog(service, parent=None)
        # 选中分类节点
        cat_item = dialog._tree.topLevelItem(0)
        cat_item.setSelected(True)
        dialog._tree.setCurrentItem(cat_item)

        # 模拟 QMessageBox.question 返回 Yes
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
        )
        # 拦截 information（_show_info 不应被调用）
        information_mock = MagicMock()
        monkeypatch.setattr(QMessageBox, "information", information_mock)

        dialog._on_delete_category()
        conn.commit()

        # 分类已删除
        assert service.list_categories() == []
        # 标签已级联删除
        assert service.list_all_tags() == []
        dialog.close()

    def test_delete_category_without_selection_shows_info(
        self, tag_dialog_env, monkeypatch
    ) -> None:
        service, conn = tag_dialog_env
        dialog = TagManagerDialog(service, parent=None)

        # 拦截 information
        information_mock = MagicMock()
        monkeypatch.setattr(QMessageBox, "information", information_mock)

        dialog._on_delete_category()

        # 应弹出提示"未选中分类"
        assert information_mock.called
        dialog.close()

    def test_delete_tag_with_confirm(self, tag_dialog_env, monkeypatch) -> None:
        service, conn = tag_dialog_env
        cat = service.create_category("服装护甲")
        service.create_tag("重甲", cat.id)
        conn.commit()

        dialog = TagManagerDialog(service, parent=None)
        # 选中标签节点
        cat_item = dialog._tree.topLevelItem(0)
        tag_item = cat_item.child(0)
        tag_item.setSelected(True)
        dialog._tree.setCurrentItem(tag_item)

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
        )
        information_mock = MagicMock()
        monkeypatch.setattr(QMessageBox, "information", information_mock)

        dialog._on_delete_tag()
        conn.commit()

        # 标签已删除
        assert service.list_all_tags() == []
        # 分类保留
        assert len(service.list_categories()) == 1
        dialog.close()


# === 空名校验（问题 4/5） ===


class TestEmptyNameValidation:
    def test_add_category_empty_name_shows_error(self, tag_dialog_env, monkeypatch) -> None:
        """新增分类输入空名称：弹错误提示，不创建分类。"""
        service, conn = tag_dialog_env
        dialog = TagManagerDialog(service, parent=None)

        # 模拟用户输入空字符串并确认
        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("", True))
        critical_mock = MagicMock()
        monkeypatch.setattr(QMessageBox, "critical", critical_mock)

        dialog._on_add_category()

        assert critical_mock.called
        assert service.list_categories() == []
        dialog.close()

    def test_add_category_whitespace_name_shows_error(self, tag_dialog_env, monkeypatch) -> None:
        """新增分类输入仅含空白：弹错误提示，不创建分类。"""
        service, conn = tag_dialog_env
        dialog = TagManagerDialog(service, parent=None)

        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("   ", True))
        critical_mock = MagicMock()
        monkeypatch.setattr(QMessageBox, "critical", critical_mock)

        dialog._on_add_category()

        assert critical_mock.called
        assert service.list_categories() == []
        dialog.close()

    def test_rename_category_empty_name_shows_error(self, tag_dialog_env, monkeypatch) -> None:
        """重命名分类输入空名称：弹错误提示，不修改。"""
        service, conn = tag_dialog_env
        service.create_category("原分类")
        conn.commit()
        dialog = TagManagerDialog(service, parent=None)
        # 选中分类
        cat_item = dialog._tree.topLevelItem(0)
        cat_item.setSelected(True)
        dialog._tree.setCurrentItem(cat_item)

        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("", True))
        critical_mock = MagicMock()
        monkeypatch.setattr(QMessageBox, "critical", critical_mock)

        dialog._on_rename_category()

        assert critical_mock.called
        # 名称未变
        cats = service.list_categories()
        assert cats[0].name == "原分类"
        dialog.close()

    def test_add_tag_empty_name_shows_error(self, tag_dialog_env, monkeypatch) -> None:
        """新增标签输入空名称：弹错误提示，不创建标签。"""
        service, conn = tag_dialog_env
        service.create_category("服装护甲")
        conn.commit()
        dialog = TagManagerDialog(service, parent=None)
        # 选中分类
        cat_item = dialog._tree.topLevelItem(0)
        cat_item.setSelected(True)
        dialog._tree.setCurrentItem(cat_item)

        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("", True))
        critical_mock = MagicMock()
        monkeypatch.setattr(QMessageBox, "critical", critical_mock)

        dialog._on_add_tag()

        assert critical_mock.called
        assert service.list_all_tags() == []
        dialog.close()

    def test_rename_tag_empty_name_shows_error(self, tag_dialog_env, monkeypatch) -> None:
        """重命名标签输入空名称：弹错误提示，不修改。"""
        service, conn = tag_dialog_env
        cat = service.create_category("服装护甲")
        service.create_tag("原标签", cat.id)
        conn.commit()
        dialog = TagManagerDialog(service, parent=None)
        # 选中标签
        cat_item = dialog._tree.topLevelItem(0)
        tag_item = cat_item.child(0)
        tag_item.setSelected(True)
        dialog._tree.setCurrentItem(tag_item)

        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("", True))
        critical_mock = MagicMock()
        monkeypatch.setattr(QMessageBox, "critical", critical_mock)

        dialog._on_rename_tag()

        assert critical_mock.called
        tags = service.list_all_tags()
        assert tags[0].name == "原标签"
        dialog.close()


# === JSON 导入按钮（问题 6） ===


class TestImportButtons:
    def test_append_import_button_exists(self, tag_dialog_env) -> None:
        """UI 应存在「追加导入」按钮。"""
        service, conn = tag_dialog_env
        dialog = TagManagerDialog(service, parent=None)
        assert hasattr(dialog, "_import_append_btn")
        assert dialog._import_append_btn.text() == "追加导入"
        dialog.close()

    def test_overwrite_import_button_exists(self, tag_dialog_env) -> None:
        """UI 应存在「覆盖导入」按钮。"""
        service, conn = tag_dialog_env
        dialog = TagManagerDialog(service, parent=None)
        assert hasattr(dialog, "_import_overwrite_btn")
        assert dialog._import_overwrite_btn.text() == "覆盖导入"
        dialog.close()

    def test_append_import_invalid_json_shows_error(
        self, tag_dialog_env, monkeypatch, tmp_path
    ) -> None:
        """追加导入非法 JSON：弹错误提示，不向上抛 JSONDecodeError。"""
        service, conn = tag_dialog_env
        dialog = TagManagerDialog(service, parent=None)

        # 准备非法 JSON 文件
        bad_json = tmp_path / "bad.json"
        bad_json.write_text("not a valid json {", encoding="utf-8")

        # 拦截 QFileDialog 返回非法 JSON 文件路径
        from PySide6.QtWidgets import QFileDialog

        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(bad_json), "")
        )
        critical_mock = MagicMock()
        monkeypatch.setattr(QMessageBox, "critical", critical_mock)

        # 不应抛 JSONDecodeError
        dialog._on_import_append_json()

        assert critical_mock.called
        # 数据库无任何分类被创建
        assert service.list_categories() == []
        dialog.close()

    def test_overwrite_import_with_confirm(self, tag_dialog_env, monkeypatch, tmp_path) -> None:
        """覆盖导入：用户确认后先清空再导入。"""
        service, conn = tag_dialog_env
        # 数据库已有数据
        old_cat = service.create_category("旧分类")
        service.create_tag("旧标签", old_cat.id)
        conn.commit()

        # 准备新 JSON 文件
        new_json = tmp_path / "new.json"
        new_json.write_text(
            '{"schema_version": 1, "categories": ['
            '{"name": "新分类", "color_hue": 100, "tags": ["新标签"]}'
            "]}",
            encoding="utf-8",
        )

        dialog = TagManagerDialog(service, parent=None)

        # 拦截 QFileDialog 返回新 JSON 文件路径
        from PySide6.QtWidgets import QFileDialog

        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(new_json), "")
        )
        # 用户确认覆盖
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
        )
        # 拦截 information 防止阻塞
        monkeypatch.setattr(QMessageBox, "information", MagicMock())

        dialog._on_import_overwrite_json()
        conn.commit()

        # 旧分类应被清空，新分类被创建
        cats = service.list_categories()
        assert {c.name for c in cats} == {"新分类"}
        tags = service.list_all_tags()
        assert {t.name for t in tags} == {"新标签"}
        dialog.close()

    def test_overwrite_import_cancelled_no_change(self, tag_dialog_env, monkeypatch) -> None:
        """覆盖导入：用户在确认对话框取消，不修改数据。"""
        service, conn = tag_dialog_env
        old_cat = service.create_category("旧分类")
        service.create_tag("旧标签", old_cat.id)
        conn.commit()

        dialog = TagManagerDialog(service, parent=None)

        # 用户在确认对话框选择 No
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.No,
        )
        # 如果意外触发了文件对话框，返回空字符串
        from PySide6.QtWidgets import QFileDialog

        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: ("", ""))

        dialog._on_import_overwrite_json()
        conn.commit()

        # 数据未变化
        cats = service.list_categories()
        assert len(cats) == 1
        assert cats[0].name == "旧分类"
        tags = service.list_all_tags()
        assert len(tags) == 1
        assert tags[0].name == "旧标签"
        dialog.close()

    def test_overwrite_import_invalid_json_shows_error(
        self, tag_dialog_env, monkeypatch, tmp_path
    ) -> None:
        """覆盖导入非法 JSON：弹错误提示，不向上抛 JSONDecodeError。"""
        service, conn = tag_dialog_env
        old_cat = service.create_category("旧分类")
        service.create_tag("旧标签", old_cat.id)
        conn.commit()

        bad_json = tmp_path / "bad.json"
        bad_json.write_text("not a valid json {", encoding="utf-8")

        dialog = TagManagerDialog(service, parent=None)

        from PySide6.QtWidgets import QFileDialog

        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(bad_json), "")
        )
        # 用户在确认对话框选择 Yes
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
        )
        critical_mock = MagicMock()
        monkeypatch.setattr(QMessageBox, "critical", critical_mock)

        # 不应抛 JSONDecodeError
        dialog._on_import_overwrite_json()

        assert critical_mock.called
        # service rollback 后旧数据保留
        conn.rollback()
        cats = service.list_categories()
        assert len(cats) == 1
        assert cats[0].name == "旧分类"
        dialog.close()


# === 异常处理 ===


class TestErrorHandling:
    def test_service_failure_shows_critical_message(self, tag_dialog_env, monkeypatch) -> None:
        """service.list_categories_with_tags 抛 ApplicationError 时弹错误提示。"""
        service, conn = tag_dialog_env
        dialog = TagManagerDialog(service, parent=None)

        # 替换 service.list_categories_with_tags 抛异常
        monkeypatch.setattr(
            service,
            "list_categories_with_tags",
            lambda: (_ for _ in ()).throw(DuplicateTagCategoryNameError("模拟错误")),
        )
        critical_mock = MagicMock()
        monkeypatch.setattr(QMessageBox, "critical", critical_mock)

        dialog._refresh_tree()

        # 应弹出错误对话框
        assert critical_mock.called
        dialog.close()
