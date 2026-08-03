"""SearchDialog 单元测试（Stage 5 Task 7）。

覆盖：
- 空结果 → 空状态提示可见
- 有结果 → 表格正确填充
- 标题显示查询词和数量
- 双击行 → 触发 jump_callback（Q4=B 保持对话框打开）
- 双击行 → jump_callback 抛异常不关闭对话框
- matched_field 中文映射
- 标签聚合显示
- update_results 更新内容
- 名称列显示真实文件名（UI合理性13 替代 title）
- 关闭按钮
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.search_dialog import SearchDialog  # noqa: E402
from domain.models import SearchResult  # noqa: E402


def _make_result(
    unit_id: str = "u1",
    name: str = "测试名称",
    path: str = "D:/mod/test.7z",
    matched_field: str = "name",
    tags: list[str] | None = None,
) -> SearchResult:
    """构造测试用 SearchResult。"""
    return SearchResult(
        unit_id=unit_id,
        name=name,
        path=path,
        content_type="mod",
        matched_field=matched_field,
        tags=tags if tags is not None else [],
    )


class TestEmptyResult:
    """空结果测试。"""

    def test_empty_results_shows_empty_label(self, qapp) -> None:
        """空结果 → 空状态提示可见，表格隐藏。"""
        dialog = SearchDialog("测试", [])
        try:
            assert dialog.is_empty_label_visible()
            assert dialog.row_count() == 0
            assert dialog.result_count() == 0
        finally:
            dialog.close()

    def test_empty_results_title_shows_count_zero(self, qapp) -> None:
        """空结果标题显示数量为 0。"""
        dialog = SearchDialog("关键词", [])
        try:
            title = dialog.title_text()
            assert "0" in title
            assert "关键词" in title
        finally:
            dialog.close()


class TestResultDisplay:
    """结果展示测试。"""

    def test_results_populate_table(self, qapp) -> None:
        """有结果 → 表格正确填充。"""
        results = [
            _make_result("u1", "名称1", "D:/mod1.7z"),
            _make_result("u2", "名称2", "D:/mod2.7z"),
        ]
        dialog = SearchDialog("测试", results)
        try:
            assert not dialog.is_empty_label_visible()
            assert dialog.row_count() == 2
            assert dialog.row_unit_id(0) == "u1"
            assert dialog.row_unit_id(1) == "u2"
        finally:
            dialog.close()

    def test_title_shows_query_and_count(self, qapp) -> None:
        """标题显示查询词和结果数量。"""
        results = [_make_result("u1"), _make_result("u2"), _make_result("u3")]
        dialog = SearchDialog("搜索词", results)
        try:
            title = dialog.title_text()
            assert "搜索词" in title
            assert "3" in title
        finally:
            dialog.close()

    def test_matched_field_chinese_mapping(self, qapp) -> None:
        """matched_field 中文映射正确。"""
        results = [
            _make_result("u1", matched_field="name"),
            _make_result("u2", matched_field="tag"),
            _make_result("u3", matched_field="notes"),
        ]
        dialog = SearchDialog("测试", results)
        try:
            assert dialog.row_matched_field_label(0) == "名称"
            assert dialog.row_matched_field_label(1) == "标签"
            assert dialog.row_matched_field_label(2) == "备注"
        finally:
            dialog.close()

    def test_tags_display(self, qapp) -> None:
        """标签列正确显示。"""
        results = [
            _make_result("u1", tags=["重甲", "女性", "HDT"]),
            _make_result("u2", tags=[]),
        ]
        dialog = SearchDialog("测试", results)
        try:
            assert "重甲" in dialog.row_tags_text(0)
            assert "女性" in dialog.row_tags_text(0)
            assert "HDT" in dialog.row_tags_text(0)
            assert dialog.row_tags_text(1) == ""
        finally:
            dialog.close()

    def test_name_column_shows_real_filename(self, qapp) -> None:
        """名称列显示真实文件名（UI合理性13）。"""
        results = [_make_result("u1", name="寒霜之心.7z", path="D:/mods/寒霜之心.7z")]
        dialog = SearchDialog("测试", results)
        try:
            item = dialog._table.item(0, 0)  # noqa: SLF001
            assert "寒霜之心.7z" in item.text()
        finally:
            dialog.close()


class TestDoubleClickJump:
    """双击跳转测试（Q4=B 保持对话框打开）。"""

    def test_double_click_triggers_jump_callback(self, qapp) -> None:
        """双击行 → 触发 jump_callback。"""
        called_with: list[str] = []

        def jump_callback(unit_id: str) -> None:
            called_with.append(unit_id)

        results = [_make_result("u1"), _make_result("u2")]
        dialog = SearchDialog("测试", results, jump_callback=jump_callback)
        try:
            dialog.double_click_row(0)
            assert called_with == ["u1"]

            dialog.double_click_row(1)
            assert called_with == ["u1", "u2"]
        finally:
            dialog.close()

    def test_jump_callback_exception_does_not_close_dialog(self, qapp) -> None:
        """jump_callback 抛异常 → 对话框保持打开（Q4=B）。"""

        def jump_callback(unit_id: str) -> None:
            raise RuntimeError("跳转失败")

        results = [_make_result("u1")]
        dialog = SearchDialog("测试", results, jump_callback=jump_callback)
        try:
            # 异常被捕获，不向外抛出
            dialog.double_click_row(0)
            # 对话框未被 accept（result != Accepted 表示未关闭）
            from PySide6.QtWidgets import QDialog

            assert dialog.result() != QDialog.DialogCode.Accepted
        finally:
            dialog.close()

    def test_no_callback_does_not_raise(self, qapp) -> None:
        """无 jump_callback → 双击不报错。"""
        results = [_make_result("u1")]
        dialog = SearchDialog("测试", results, jump_callback=None)
        try:
            dialog.double_click_row(0)  # 不应抛异常
        finally:
            dialog.close()


class TestUpdateResults:
    """update_results 测试（复用对话框实例）。"""

    def test_update_results_replaces_content(self, qapp) -> None:
        """update_results 替换表格内容。"""
        initial = [_make_result("u1", "旧结果1")]
        dialog = SearchDialog("旧", initial)
        try:
            assert dialog.row_count() == 1
            assert dialog.row_unit_id(0) == "u1"

            new_results = [_make_result("u2", "新结果1"), _make_result("u3", "新结果2")]
            dialog.update_results("新", new_results)

            assert dialog.row_count() == 2
            assert dialog.row_unit_id(0) == "u2"
            assert dialog.row_unit_id(1) == "u3"
            assert "新" in dialog.title_text()
            assert "2" in dialog.title_text()
        finally:
            dialog.close()

    def test_update_to_empty_shows_empty_label(self, qapp) -> None:
        """update_results 到空结果 → 显示空状态。"""
        initial = [_make_result("u1")]
        dialog = SearchDialog("有", initial)
        try:
            assert not dialog.is_empty_label_visible()

            dialog.update_results("无", [])

            assert dialog.is_empty_label_visible()
            assert dialog.row_count() == 0
            assert "0" in dialog.title_text()
        finally:
            dialog.close()


class TestCloseButton:
    """关闭按钮测试。"""

    def test_close_button_accepts(self, qapp) -> None:
        """点击关闭 → accept（对话框关闭）。"""
        results = [_make_result("u1")]
        dialog = SearchDialog("测试", results)
        try:
            dialog.click_close_button()
            # accept 后对话框应处于隐藏状态
            assert dialog.isHidden() or not dialog.isVisible()
        finally:
            dialog.close()


class TestNonModal:
    """非模态对话框测试（Q3=B）。"""

    def test_dialog_is_non_modal(self, qapp) -> None:
        """对话框设置为非模态（Q3=B）。"""
        dialog = SearchDialog("测试", [])
        try:
            assert not dialog.isModal()
        finally:
            dialog.close()
