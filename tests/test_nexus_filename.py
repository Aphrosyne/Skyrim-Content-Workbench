"""nexus_filename 共享模块测试（操作便捷性8/9，2026-08-04）。

覆盖：
- extract_nexus_id：Nexus 模式识别 / 非 Nexus 返回 None
- build_nexus_url：文件自身名 / 文件夹自身名 / 文件夹内部最小 ID（本体优先）/
  无匹配返回 None
- mod_search_query：去尾号（与创建 Mod 组同名提取）+ _/- → 空格 + 前缀
"""

from __future__ import annotations

from pathlib import Path

from application.nexus_filename import (
    build_nexus_url,
    extract_mod_name,
    extract_nexus_id,
    mod_search_query,
)

PREFIX = "https://www.nexusmods.com/skyrimspecialedition/mods/"


class TestExtractNexusId:
    def test_nexus_filename(self) -> None:
        """标准 N 网下载命名（用户示例）。"""
        assert extract_nexus_id("Birthplace of a Kitsune-26416-1-1-1588673209.zip") == "26416"

    def test_nexus_filename_with_hyphen_in_name(self) -> None:
        assert extract_nexus_id("Alt-Tab Fix-148466-1-0-0-1745430887.zip") == "148466"

    def test_non_nexus_archive_returns_none(self) -> None:
        """普通压缩包（社区分享/汉化包）→ None（格式检查，不填"前缀+空值"）。"""
        assert extract_nexus_id("RealisticWater.7z") is None
        assert extract_nexus_id("汉化包.zip") is None
        assert extract_nexus_id("readme.txt") is None

    def test_short_name_with_number_not_matched(self) -> None:
        """短名 Mod-123（ID 后无版本段）不匹配 Nexus 模式。"""
        assert extract_nexus_id("Mod-123.7z") is None


class TestBuildNexusUrl:
    def test_file_unit_nexus_name(self, tmp_path: Path) -> None:
        path = tmp_path / "Birthplace of a Kitsune-26416-1-1-1588673209.zip"
        path.write_bytes(b"x")
        assert build_nexus_url(path, PREFIX) == PREFIX + "26416"

    def test_file_unit_non_nexus_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "RealisticWater.7z"
        path.write_bytes(b"x")
        assert build_nexus_url(path, PREFIX) is None

    def test_folder_name_with_id(self, tmp_path: Path) -> None:
        """文件夹名自身含 Nexus ID → 直接用。"""
        folder = tmp_path / "Foo-26416-1-0"
        folder.mkdir()
        assert build_nexus_url(folder, PREFIX) == PREFIX + "26416"

    def test_folder_uses_min_id_of_internal_files(self, tmp_path: Path) -> None:
        """文件夹内部多个 ID → 取最小（汉化后发 → 最小者即本体）。"""
        folder = tmp_path / "Birthplace of a Kitsune"
        folder.mkdir()
        # 本体 ID 26416，汉化后发 ID 更大（如 120000）
        (folder / "Birthplace of a Kitsune-26416-1-1-1588673209.zip").write_bytes(b"a")
        (folder / "汉化补丁-120000-1-0.zip").write_bytes(b"b")
        assert build_nexus_url(folder, PREFIX) == PREFIX + "26416"

    def test_folder_no_id_returns_none(self, tmp_path: Path) -> None:
        """文件夹内部无 Nexus 命名文件 → None（静默跳过）。"""
        folder = tmp_path / "普通文件夹"
        folder.mkdir()
        (folder / "readme.txt").write_bytes(b"x")
        (folder / "RealisticWater.7z").write_bytes(b"y")
        assert build_nexus_url(folder, PREFIX) is None

    def test_folder_prefix_without_trailing_slash(self, tmp_path: Path) -> None:
        """前缀未以 / 结尾时补一个斜杠。"""
        path = tmp_path / "Foo-26416-1-0.zip"
        path.write_bytes(b"x")
        assert build_nexus_url(path, "https://www.nexusmods.com/skyrimspecialedition/mods") == (
            "https://www.nexusmods.com/skyrimspecialedition/mods/26416"
        )


class TestModSearchQuery:
    def test_nexus_name_strips_tail_and_separators(self) -> None:
        """N 网文件：去 ID/版本/时间戳尾号，横线/下划线替换为空格（与创建 Mod 组同名）。"""
        query = mod_search_query("Alt-Tab_Fix-148466-1-0-0-1745430887.zip", "skyrim ")
        assert query == "skyrim Alt Tab Fix"

    def test_user_example(self) -> None:
        query = mod_search_query("Birthplace of a Kitsune-26416-1-1-1588673209.zip", "skyrim ")
        assert query == "skyrim Birthplace of a Kitsune"

    def test_generic_version_stripped(self) -> None:
        """通用命名（社区分享）同样去版本号。"""
        assert mod_search_query("SkyUI 5.1 SE.zip", "skyrim ") == "skyrim SkyUI"

    def test_folder_name(self) -> None:
        """文件夹名不含尾号 → 仅替换分隔符。"""
        assert mod_search_query("Alt-Tab Fix", "skyrim ") == "skyrim Alt Tab Fix"

    def test_empty_prefix(self) -> None:
        assert mod_search_query("Some_Mod-123-1-0.zip", "") == "Some Mod"

    def test_search_and_extract_mod_name_consistency(self) -> None:
        """搜索名与创建 Mod 组提取名一致（用户确认 2026-08-04）。"""
        name = "Birthplace of a Kitsune-26416-1-1-1588673209.zip"
        assert extract_mod_name(name) == "Birthplace of a Kitsune"
        assert mod_search_query(name, "") == "Birthplace of a Kitsune"
