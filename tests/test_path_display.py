"""path_display 单元测试（UX 重构 Phase 2 Task 5）。"""

from __future__ import annotations

from app.path_display import make_display_path, make_display_path_from_service
from domain.models import ManagedRoot


def _make_root(real_path: str, root_id: str = "r1") -> ManagedRoot:
    return ManagedRoot(
        id=root_id,
        real_path=real_path,
        path_key=real_path.lower(),
        display_name=None,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


class TestMakeDisplayPath:
    """make_display_path 路径简化测试。"""

    def test_path_under_root_returns_relative(self, tmp_path) -> None:
        """路径在受管理根目录下 → 返回含根目录名的相对路径。"""
        root = _make_root(str(tmp_path))
        target = tmp_path / "archive" / "mods" / "bdor"
        result = make_display_path(str(target), [root])
        # 相对路径包含根目录名（验收修正）
        expected = f"{tmp_path.name}\\{target.relative_to(tmp_path)}"
        assert result == expected

    def test_path_equals_root_returns_root_name(self, tmp_path) -> None:
        """路径就是根目录本身 → 返回根目录名。"""
        root = _make_root(str(tmp_path))
        result = make_display_path(str(tmp_path), [root])
        assert result == tmp_path.name

    def test_path_outside_root_gets_external_prefix(self, tmp_path) -> None:
        """路径不在任何受管理根目录下 → 加 [外部] 前缀（Q8=B）。"""
        root = _make_root(str(tmp_path))
        external = tmp_path.parent / "external_dir" / "foo"
        result = make_display_path(str(external), [root])
        assert result.startswith("[外部] ")
        assert str(external) in result

    def test_empty_path_returns_empty(self) -> None:
        """空路径 → 返回空字符串。"""
        assert make_display_path("", []) == ""
        assert make_display_path(None, []) == ""  # type: ignore[arg-type]

    def test_nested_roots_picks_longest_match(self, tmp_path) -> None:
        """嵌套根目录 → 匹配最长根目录。"""
        parent_root = _make_root(str(tmp_path), "parent")
        child_root = _make_root(str(tmp_path / "child"), "child")
        target = tmp_path / "child" / "sub" / "file.txt"
        result = make_display_path(str(target), [parent_root, child_root])
        # 应匹配 child_root，返回含根目录名的相对路径 child\sub\file.txt
        expected = f"child\\{target.relative_to(tmp_path / 'child')}"
        assert result == expected

    def test_multiple_roots_matches_correct_one(self, tmp_path) -> None:
        """多个根目录 → 匹配正确的那个。"""
        root1 = _make_root(str(tmp_path / "mods1"), "r1")
        root2 = _make_root(str(tmp_path / "mods2"), "r2")
        target = tmp_path / "mods2" / "armor" / "bdor"
        result = make_display_path(str(target), [root1, root2])
        # 含根目录名：mods2\armor\bdor
        expected = f"mods2\\{target.relative_to(tmp_path / 'mods2')}"
        assert result == expected

    def test_no_roots_returns_external(self, tmp_path) -> None:
        """无受管理根目录 → 加 [外部] 前缀。"""
        target = tmp_path / "foo"
        result = make_display_path(str(target), [])
        assert result.startswith("[外部] ")

    def test_chinese_path_under_root(self, tmp_path) -> None:
        """中文路径在根目录下 → 正确返回含根目录名的相对路径。"""
        root = _make_root(str(tmp_path))
        target = tmp_path / "护甲" / "BDOR"
        result = make_display_path(str(target), [root])
        expected = f"{tmp_path.name}\\{target.relative_to(tmp_path)}"
        assert result == expected


class TestMakeDisplayPathFromService:
    """make_display_path_from_service 便捷封装测试。"""

    def test_delegates_to_make_display_path(self, tmp_path) -> None:
        """从 service 获取根目录列表后调用 make_display_path。"""

        class FakeService:
            def __init__(self, roots):
                self._roots = roots

            def list_roots(self):
                return self._roots

        root = _make_root(str(tmp_path))
        service = FakeService([root])
        target = tmp_path / "archive" / "bdor"
        result = make_display_path_from_service(str(target), service)
        expected = f"{tmp_path.name}\\{target.relative_to(tmp_path)}"
        assert result == expected
