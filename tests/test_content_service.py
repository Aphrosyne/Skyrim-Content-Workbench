"""ContentService 测试。

覆盖：
- list_by_directory：返回目录及子目录下的所有内容单元；
- list_direct_children：只返回直接子项，不含深层；
- get_by_id：存在/不存在；
- 中文路径；
- 多层嵌套目录；
- list_directory_entries：从文件系统读取目录条目并关联 content_unit（Task 4 2026-07-13 设计修正）。
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from application.content_service import ContentService
from domain.models import ContentUnit, FileEntry
from infrastructure.db import get_connection, init_db
from infrastructure.repositories.content_unit import ContentUnitRepository


@pytest.fixture
def db_connection(tmp_path: Path) -> sqlite3.Connection:
    """临时数据库连接，使用 Row 工厂。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def repo(db_connection: sqlite3.Connection) -> ContentUnitRepository:
    return ContentUnitRepository(db_connection)


@pytest.fixture
def service(repo: ContentUnitRepository) -> ContentService:
    return ContentService(repo)


def _make_unit(
    unit_id: str,
    path: str,
    title: str | None = None,
    created_at: str = "2026-07-12T00:00:00Z",
    status: str = "unorganized",
) -> ContentUnit:
    return ContentUnit(
        id=unit_id,
        path=path,
        created_at=created_at,
        updated_at=created_at,
        title=title,
        status=status,
    )


class TestListByDirectory:
    def test_empty_data_returns_empty(self, service: ContentService) -> None:
        assert service.list_by_directory("C:/mods") == []

    def test_single_unit_in_directory(
        self, repo: ContentUnitRepository, service: ContentService, tmp_path: Path
    ) -> None:
        mods = tmp_path / "mods"
        armor = mods / "armor"
        unit = _make_unit("u1", str(armor), title="护甲")
        repo.create(unit)

        result = service.list_by_directory(str(mods))
        assert len(result) == 1
        assert result[0].id == "u1"

    def test_multiple_units_in_same_directory(
        self, repo: ContentUnitRepository, service: ContentService, tmp_path: Path
    ) -> None:
        mods = tmp_path / "mods"
        mods.mkdir()
        u1 = _make_unit("u1", str(mods / "armor"), title="护甲")
        u2 = _make_unit("u2", str(mods / "weapons"), title="武器")
        repo.create(u1)
        repo.create(u2)

        result = service.list_by_directory(str(mods))
        assert len(result) == 2
        ids = {u.id for u in result}
        assert ids == {"u1", "u2"}

    def test_excludes_units_in_other_directories(
        self, repo: ContentUnitRepository, service: ContentService, tmp_path: Path
    ) -> None:
        mods_a = tmp_path / "mods_a"
        mods_b = tmp_path / "mods_b"
        mods_a.mkdir()
        mods_b.mkdir()
        u1 = _make_unit("u1", str(mods_a / "armor"), title="护甲")
        u2 = _make_unit("u2", str(mods_b / "weapons"), title="武器")
        repo.create(u1)
        repo.create(u2)

        result = service.list_by_directory(str(mods_a))
        assert len(result) == 1
        assert result[0].id == "u1"

    def test_chinese_path(
        self, repo: ContentUnitRepository, service: ContentService, tmp_path: Path
    ) -> None:
        # 构造中文路径（不实际创建文件，ContentUnit 只存字符串路径）
        armor_path = str(tmp_path / "mods" / "护甲")
        u1 = _make_unit("u1", armor_path, title="寒霜之心")
        repo.create(u1)

        result = service.list_by_directory(str(tmp_path / "mods"))
        assert len(result) == 1
        assert result[0].title == "寒霜之心"


class TestListDirectChildren:
    def test_empty_directory_returns_empty(self, service: ContentService) -> None:
        assert service.list_direct_children("C:/mods") == []

    def test_returns_direct_children_only(
        self, repo: ContentUnitRepository, service: ContentService, tmp_path: Path
    ) -> None:
        mods = tmp_path / "mods"
        armor = mods / "armor"
        armor_deep = armor / "deep"
        # 直接子项
        u1 = _make_unit("u1", str(armor), title="护甲")
        # 深层子项
        u2 = _make_unit("u2", str(armor_deep), title="深层")
        repo.create(u1)
        repo.create(u2)

        result = service.list_direct_children(str(mods))
        assert len(result) == 1
        assert result[0].id == "u1"

    def test_excludes_deep_children(
        self, repo: ContentUnitRepository, service: ContentService, tmp_path: Path
    ) -> None:
        mods = tmp_path / "mods"
        l1 = mods / "L1"
        l2 = l1 / "L2"
        l3 = l2 / "L3"
        u1 = _make_unit("u1", str(l1), title="L1")
        u2 = _make_unit("u2", str(l2), title="L2")
        u3 = _make_unit("u3", str(l3), title="L3")
        repo.create(u1)
        repo.create(u2)
        repo.create(u3)

        # 查询 mods 的直接子项，只应返回 u1（L1 是 mods 的直接子项）
        result = service.list_direct_children(str(mods))
        assert len(result) == 1
        assert result[0].id == "u1"

        # 查询 L1 的直接子项，应返回 u1（L1 本身）和 u2（L1 的直接子项），
        # 不返回 u3（L1/L2/L3，深层子项）
        result = service.list_direct_children(str(l1))
        assert len(result) == 2
        ids = {u.id for u in result}
        assert ids == {"u1", "u2"}

        # 查询 L2 的直接子项，应返回 u2（L2 本身）和 u3（L2 的直接子项）
        result = service.list_direct_children(str(l2))
        assert len(result) == 2
        ids = {u.id for u in result}
        assert ids == {"u2", "u3"}

    def test_unit_path_equals_directory_included(
        self, repo: ContentUnitRepository, service: ContentService, tmp_path: Path
    ) -> None:
        """内容单元路径等于目录本身时包含。"""
        mods = tmp_path / "mods"
        u1 = _make_unit("u1", str(mods), title="Mods 本身")
        repo.create(u1)

        result = service.list_direct_children(str(mods))
        assert len(result) == 1
        assert result[0].id == "u1"

    def test_chinese_path(
        self, repo: ContentUnitRepository, service: ContentService, tmp_path: Path
    ) -> None:
        armor_path = str(tmp_path / "mods" / "护甲")
        deep_path = str(tmp_path / "mods" / "护甲" / "深层")
        u1 = _make_unit("u1", armor_path, title="寒霜之心")
        u2 = _make_unit("u2", deep_path, title="深层")
        repo.create(u1)
        repo.create(u2)

        result = service.list_direct_children(str(tmp_path / "mods"))
        assert len(result) == 1
        assert result[0].title == "寒霜之心"

    def test_multiple_direct_children(
        self, repo: ContentUnitRepository, service: ContentService, tmp_path: Path
    ) -> None:
        mods = tmp_path / "mods"
        u1 = _make_unit("u1", str(mods / "armor"), title="护甲")
        u2 = _make_unit("u2", str(mods / "weapons"), title="武器")
        u3 = _make_unit("u3", str(mods / "spells"), title="法术")
        repo.create(u1)
        repo.create(u2)
        repo.create(u3)

        result = service.list_direct_children(str(mods))
        assert len(result) == 3
        ids = {u.id for u in result}
        assert ids == {"u1", "u2", "u3"}


class TestGetById:
    def test_existing_unit(
        self, repo: ContentUnitRepository, service: ContentService, tmp_path: Path
    ) -> None:
        unit = _make_unit("u1", str(tmp_path / "armor"), title="护甲")
        repo.create(unit)

        result = service.get_by_id("u1")
        assert result is not None
        assert result.id == "u1"
        assert result.title == "护甲"

    def test_nonexistent_unit(self, service: ContentService) -> None:
        assert service.get_by_id("nonexistent") is None


class TestListDirectoryEntries:
    """list_directory_entries：从文件系统读取目录条目并关联 content_unit。

    所有测试使用 tmp_path fixture 创建真实文件系统（AGENTS 规则：真实文件测试用临时目录）。
    """

    def test_empty_directory_returns_empty(self, service: ContentService, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        assert service.list_directory_entries(str(empty)) == []

    def test_nonexistent_path_returns_empty(self, service: ContentService, tmp_path: Path) -> None:
        result = service.list_directory_entries(str(tmp_path / "nonexistent"))
        assert result == []

    def test_not_a_directory_returns_empty(self, service: ContentService, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("hello", encoding="utf-8")
        assert service.list_directory_entries(str(f)) == []

    def test_lists_all_files_and_dirs(self, service: ContentService, tmp_path: Path) -> None:
        """非内容单元文件也正常列出（内容单元不是可见性门槛）。"""
        mods = tmp_path / "mods"
        mods.mkdir()
        (mods / "armor").mkdir()
        (mods / "readme.txt").write_text("hello", encoding="utf-8")
        (mods / "screenshot.png").write_bytes(b"\x89PNG")

        entries = service.list_directory_entries(str(mods))
        names = [e.name for e in entries]
        assert "armor" in names
        assert "readme.txt" in names
        assert "screenshot.png" in names
        assert len(entries) == 3

    def test_dirs_sorted_before_files(self, service: ContentService, tmp_path: Path) -> None:
        mods = tmp_path / "mods"
        mods.mkdir()
        (mods / "z_file.txt").write_text("z", encoding="utf-8")
        (mods / "a_dir").mkdir()
        (mods / "m_file.txt").write_text("m", encoding="utf-8")
        (mods / "b_dir").mkdir()

        entries = service.list_directory_entries(str(mods))
        # 文件夹在前，按名称不区分大小写升序
        assert entries[0].is_dir
        assert entries[1].is_dir
        assert entries[0].name == "a_dir"
        assert entries[1].name == "b_dir"
        # 然后是文件
        assert not entries[2].is_dir
        assert not entries[3].is_dir
        assert entries[2].name == "m_file.txt"
        assert entries[3].name == "z_file.txt"

    def test_entry_basic_fields(self, service: ContentService, tmp_path: Path) -> None:
        mods = tmp_path / "mods"
        mods.mkdir()
        (mods / "file.txt").write_text("hello world", encoding="utf-8")

        entries = service.list_directory_entries(str(mods))
        assert len(entries) == 1
        entry = entries[0]
        assert entry.name == "file.txt"
        assert entry.path == str(mods / "file.txt")
        assert entry.is_dir is False
        assert entry.size == 11
        assert entry.modified_at  # ISO 8601 字符串非空

    def test_directory_size_is_none(self, service: ContentService, tmp_path: Path) -> None:
        mods = tmp_path / "mods"
        mods.mkdir()
        (mods / "subdir").mkdir()

        entries = service.list_directory_entries(str(mods))
        assert len(entries) == 1
        assert entries[0].is_dir
        assert entries[0].size is None

    def test_content_unit_association(
        self, repo: ContentUnitRepository, service: ContentService, tmp_path: Path
    ) -> None:
        """路径与 content_unit.path 精确匹配时关联填充。

        spec §5.4 2026-07-13 修正：内容单元 path 为压缩包文件路径。
        """
        mods = tmp_path / "mods"
        mods.mkdir()
        armor = mods / "armor"
        armor.mkdir()
        archive = armor / "寒霜之心.7z"
        archive.write_bytes(b"\x00" * 100)
        # 创建对应内容单元（path 为压缩包文件路径）
        repo.create(_make_unit("u1", str(archive), title="寒霜之心.7z"))

        # 在 armor 目录下查询，应找到压缩包文件并关联
        entries = service.list_directory_entries(str(armor))
        archive_entry = next(e for e in entries if e.name == "寒霜之心.7z")
        assert archive_entry.content_unit is not None
        assert archive_entry.content_unit.id == "u1"
        assert archive_entry.content_unit.title == "寒霜之心.7z"

    def test_non_content_unit_entry_has_none(
        self, repo: ContentUnitRepository, service: ContentService, tmp_path: Path
    ) -> None:
        """未标记为内容单元的条目 content_unit 字段为 None。"""
        mods = tmp_path / "mods"
        mods.mkdir()
        (mods / "armor").mkdir()
        (mods / "weapons").mkdir()
        (mods / "armor" / "a.7z").write_bytes(b"\x00")
        (mods / "weapons" / "w.7z").write_bytes(b"\x00")
        # 只为 armor/a.7z 创建内容单元
        repo.create(_make_unit("u1", str(mods / "armor" / "a.7z"), title="a.7z"))

        # 在 mods 目录下查询
        entries = service.list_directory_entries(str(mods))
        # armor / weapons 都是文件夹，均不是内容单元
        armor_entry = next(e for e in entries if e.name == "armor")
        weapons_entry = next(e for e in entries if e.name == "weapons")
        assert armor_entry.content_unit is None  # 文件夹不作为内容单元
        assert weapons_entry.content_unit is None

        # 在 armor 目录下查询，a.7z 应关联
        armor_entries = service.list_directory_entries(str(mods / "armor"))
        a_entry = next(e for e in armor_entries if e.name == "a.7z")
        assert a_entry.content_unit is not None
        assert a_entry.content_unit.id == "u1"

    def test_chinese_filename(self, service: ContentService, tmp_path: Path) -> None:
        mods = tmp_path / "mods"
        mods.mkdir()
        (mods / "说明.txt").write_text("hello", encoding="utf-8")
        (mods / "护甲").mkdir()

        entries = service.list_directory_entries(str(mods))
        names = {e.name for e in entries}
        assert "说明.txt" in names
        assert "护甲" in names

    def test_returns_file_entry_instances(self, service: ContentService, tmp_path: Path) -> None:
        """确保返回的是 FileEntry 实例。"""
        mods = tmp_path / "mods"
        mods.mkdir()
        (mods / "a.txt").write_text("a", encoding="utf-8")

        entries = service.list_directory_entries(str(mods))
        assert len(entries) == 1
        assert isinstance(entries[0], FileEntry)

    def test_symlink_skipped(self, service: ContentService, tmp_path: Path) -> None:
        """符号链接应被跳过（避免循环）。需要支持创建符号链接时才验证。"""
        if os.name == "nt":
            # Windows 上普通用户可能无权创建符号链接，跳过此测试
            pytest.skip("Windows 上创建符号链接可能需要管理员权限")
        mods = tmp_path / "mods"
        mods.mkdir()
        target = tmp_path / "target.txt"
        target.write_text("t", encoding="utf-8")
        link = mods / "link.txt"
        try:
            link.symlink_to(target)
        except OSError:
            pytest.skip("无法创建符号链接")

        entries = service.list_directory_entries(str(mods))
        # 符号链接应被跳过，返回空
        names = [e.name for e in entries]
        assert "link.txt" not in names


class TestListStagingEntries:
    """list_staging_entries：递归遍历暂存区下所有文件与子目录。

    阶段 3 Task 2：与 list_directory_entries 区别为递归 + 批量 content_unit 关联。
    所有测试使用 tmp_path fixture 创建真实文件系统。
    """

    def test_empty_directory_returns_empty(self, service: ContentService, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        assert service.list_staging_entries(str(empty)) == []

    def test_nonexistent_path_returns_empty(self, service: ContentService, tmp_path: Path) -> None:
        result = service.list_staging_entries(str(tmp_path / "nonexistent"))
        assert result == []

    def test_not_a_directory_returns_empty(self, service: ContentService, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("hello", encoding="utf-8")
        assert service.list_staging_entries(str(f)) == []

    def test_recursive_traversal_includes_subdir_files(
        self, service: ContentService, tmp_path: Path
    ) -> None:
        """递归遍历：暂存区下多层子目录中的文件都应返回。"""
        staging = tmp_path / "staging"
        staging.mkdir()
        # 顶层文件
        (staging / "top.7z").write_bytes(b"\x00" * 100)
        # 一层子目录
        (staging / "汉化").mkdir()
        (staging / "汉化" / "patch.zip").write_bytes(b"\x00" * 50)
        (staging / "汉化" / "readme.txt").write_text("hi", encoding="utf-8")
        # 二层子目录
        (staging / "汉化" / "deep").mkdir()
        (staging / "汉化" / "deep" / "nested.7z").write_bytes(b"\x00" * 20)

        entries = service.list_staging_entries(str(staging))
        names = {e.name for e in entries}
        assert "top.7z" in names
        assert "patch.zip" in names
        assert "readme.txt" in names
        assert "nested.7z" in names
        # 子目录本身也作为条目返回
        assert "汉化" in names
        assert "deep" in names
        assert len(entries) == 6

    def test_batch_content_unit_association(
        self, repo: ContentUnitRepository, service: ContentService, tmp_path: Path
    ) -> None:
        """批量预查：暂存区内多个 content_unit 一次性关联，无 N 次 DB 查询。"""
        staging = tmp_path / "staging"
        staging.mkdir()
        archive1 = staging / "mod1.7z"
        archive2 = staging / "sub" / "mod2.zip"
        archive1.write_bytes(b"\x00" * 10)
        (staging / "sub").mkdir()
        archive2.write_bytes(b"\x00" * 20)
        # 在暂存区外创建一个内容单元，确认不会被错误关联
        outside = tmp_path / "outside.7z"
        outside.write_bytes(b"\x00")
        repo.create(_make_unit("u1", str(archive1), title="mod1"))
        repo.create(_make_unit("u2", str(archive2), title="mod2"))
        repo.create(_make_unit("u3", str(outside), title="outside"))

        entries = service.list_staging_entries(str(staging))
        archive1_entry = next(e for e in entries if e.name == "mod1.7z")
        archive2_entry = next(e for e in entries if e.name == "mod2.zip")
        assert archive1_entry.content_unit is not None
        assert archive1_entry.content_unit.id == "u1"
        assert archive2_entry.content_unit is not None
        assert archive2_entry.content_unit.id == "u2"

    def test_non_content_unit_entry_has_none(
        self, repo: ContentUnitRepository, service: ContentService, tmp_path: Path
    ) -> None:
        """未标记为内容单元的条目 content_unit 字段为 None。"""
        staging = tmp_path / "staging"
        staging.mkdir()
        (staging / "a.7z").write_bytes(b"\x00")
        (staging / "readme.txt").write_text("hi", encoding="utf-8")
        (staging / "sub").mkdir()
        # 只为 a.7z 创建内容单元
        repo.create(_make_unit("u1", str(staging / "a.7z"), title="a.7z"))

        entries = service.list_staging_entries(str(staging))
        a_entry = next(e for e in entries if e.name == "a.7z")
        readme_entry = next(e for e in entries if e.name == "readme.txt")
        sub_entry = next(e for e in entries if e.name == "sub")
        assert a_entry.content_unit is not None
        assert readme_entry.content_unit is None
        assert sub_entry.content_unit is None

    def test_chinese_path_and_filename(self, service: ContentService, tmp_path: Path) -> None:
        """中文路径与文件名正确返回。"""
        staging = tmp_path / "暂存区"
        staging.mkdir()
        (staging / "护甲").mkdir()
        (staging / "护甲" / "寒霜之心.7z").write_bytes(b"\x00" * 100)

        entries = service.list_staging_entries(str(staging))
        names = {e.name for e in entries}
        assert "护甲" in names
        assert "寒霜之心.7z" in names

    def test_dirs_sorted_before_files(self, service: ContentService, tmp_path: Path) -> None:
        """文件夹在前，按名称不区分大小写升序。"""
        staging = tmp_path / "staging"
        staging.mkdir()
        (staging / "z_file.txt").write_text("z", encoding="utf-8")
        (staging / "a_dir").mkdir()
        (staging / "m_file.txt").write_text("m", encoding="utf-8")
        (staging / "b_dir").mkdir()

        entries = service.list_staging_entries(str(staging))
        assert entries[0].is_dir
        assert entries[1].is_dir
        assert entries[0].name == "a_dir"
        assert entries[1].name == "b_dir"
        assert not entries[2].is_dir
        assert not entries[3].is_dir

    def test_entry_basic_fields(self, service: ContentService, tmp_path: Path) -> None:
        """返回的 FileEntry 含正确 name/path/is_dir/size/modified_at。"""
        staging = tmp_path / "staging"
        staging.mkdir()
        (staging / "file.txt").write_text("hello world", encoding="utf-8")

        entries = service.list_staging_entries(str(staging))
        assert len(entries) == 1
        entry = entries[0]
        assert entry.name == "file.txt"
        assert entry.path == str(staging / "file.txt")
        assert entry.is_dir is False
        assert entry.size == 11
        assert entry.modified_at  # ISO 8601 字符串非空

    def test_directory_size_is_none(self, service: ContentService, tmp_path: Path) -> None:
        """文件夹的 size 字段为 None。"""
        staging = tmp_path / "staging"
        staging.mkdir()
        (staging / "subdir").mkdir()

        entries = service.list_staging_entries(str(staging))
        assert len(entries) == 1
        assert entries[0].is_dir
        assert entries[0].size is None

    def test_returns_file_entry_instances(self, service: ContentService, tmp_path: Path) -> None:
        """确保返回的是 FileEntry 实例。"""
        staging = tmp_path / "staging"
        staging.mkdir()
        (staging / "a.txt").write_text("a", encoding="utf-8")

        entries = service.list_staging_entries(str(staging))
        assert len(entries) == 1
        assert isinstance(entries[0], FileEntry)

    def test_symlink_skipped(self, service: ContentService, tmp_path: Path) -> None:
        """符号链接应被跳过（避免循环）。"""
        if os.name == "nt":
            pytest.skip("Windows 上创建符号链接可能需要管理员权限")
        staging = tmp_path / "staging"
        staging.mkdir()
        target = tmp_path / "target.txt"
        target.write_text("t", encoding="utf-8")
        link = staging / "link.txt"
        try:
            link.symlink_to(target)
        except OSError:
            pytest.skip("无法创建符号链接")

        entries = service.list_staging_entries(str(staging))
        names = [e.name for e in entries]
        assert "link.txt" not in names
