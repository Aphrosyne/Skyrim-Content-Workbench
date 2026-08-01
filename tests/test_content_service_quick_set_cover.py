"""ContentService.quick_set_cover 与 mark 自动录入封面测试（Stage 5 Task 1）。

覆盖：
- quick_set_cover：文件夹内容单元 + 有图片 → 设置第一张为封面
- quick_set_cover：文件夹内容单元 + 无图片 → 返回 False，不报错
- quick_set_cover：压缩包内容单元 → 返回 False（非目录）
- quick_set_cover：已有手动封面 → 返回 False，不覆盖
- quick_set_cover：unit_id 不存在 → 抛 ContentUnitNotFoundError
- mark_as_content_unit：标记文件夹后自动录入封面
- mark_as_content_unit：标记文件夹无图片 → 不报错，cover_path 保持为空
- mark_as_content_unit：标记压缩包 → 不触发自动录入
- mark_as_content_unit：已有手动封面 → 不覆盖
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from application.content_service import ContentService
from application.errors import ContentUnitNotFoundError
from infrastructure.repositories.content_unit import ContentUnitRepository


@pytest.fixture
def db_connection(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE content_unit (
            id TEXT PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            path_key TEXT NOT NULL UNIQUE,
            title TEXT,
            content_type TEXT NOT NULL,
            source_url TEXT,
            cover_path TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    # repo.delete 级联清理 content_unit_tag / thumbnail_cache（Task 6 unmark = DELETE）
    conn.execute("""
        CREATE TABLE content_unit_tag (
            content_unit_id TEXT NOT NULL,
            tag_id TEXT NOT NULL,
            PRIMARY KEY (content_unit_id, tag_id)
        )
    """)
    conn.execute("""
        CREATE TABLE thumbnail_cache (
            content_unit_id TEXT NOT NULL,
            size INTEGER NOT NULL DEFAULT 64,
            source_size_bytes INTEGER NOT NULL,
            source_modified_at TEXT NOT NULL,
            cache_filename TEXT NOT NULL,
            status TEXT NOT NULL,
            error_message TEXT,
            generated_at TEXT NOT NULL,
            PRIMARY KEY (content_unit_id, size)
        )
    """)
    return conn


@pytest.fixture
def repo(db_connection: sqlite3.Connection) -> ContentUnitRepository:
    return ContentUnitRepository(db_connection)


@pytest.fixture
def service(repo: ContentUnitRepository) -> ContentService:
    return ContentService(
        repo,
        now_provider=lambda: "2026-07-29T00:00:00Z",
        uuid_provider=lambda: "uuid-quick-set-cover",
    )


class TestQuickSetCover:
    def test_folder_unit_with_image_sets_cover(
        self, service: ContentService, repo: ContentUnitRepository, tmp_path: Path
    ) -> None:
        """文件夹内容单元 + 目录有图片 → 设置第一张为 cover_path。"""
        folder = tmp_path / "ModA"
        folder.mkdir()
        # 创建两张图片，验证取第一张（按文件名升序）
        (folder / "preview2.webp").write_bytes(b"img2")
        (folder / "preview1.jpg").write_bytes(b"img1")
        # 标记为内容单元（触发自动录入，应已设置 preview1.jpg）
        unit = service.mark_as_content_unit(folder)
        # 清空 cover_path 模拟"未自动录入"场景，再走 quick_set_cover
        from dataclasses import replace

        cleared = replace(unit, cover_path=None)
        repo.update(cleared)

        ok = service.quick_set_cover(unit.id)

        assert ok is True
        updated = repo.get_by_id(unit.id)
        assert updated is not None
        assert updated.cover_path == "preview1.jpg"

    def test_folder_unit_without_image_returns_false(
        self, service: ContentService, repo: ContentUnitRepository, tmp_path: Path
    ) -> None:
        """文件夹内容单元 + 目录无图片 → 返回 False，不报错。"""
        folder = tmp_path / "EmptyMod"
        folder.mkdir()
        unit = service.mark_as_content_unit(folder)
        # 清空 cover_path（mark 时无图片，应为空，这里二次保险）
        from dataclasses import replace

        cleared = replace(unit, cover_path=None)
        repo.update(cleared)

        ok = service.quick_set_cover(unit.id)

        assert ok is False
        updated = repo.get_by_id(unit.id)
        assert updated is not None
        assert updated.cover_path is None

    def test_archive_unit_returns_false(
        self, service: ContentService, repo: ContentUnitRepository, tmp_path: Path
    ) -> None:
        """压缩包内容单元 → 返回 False（非目录）。"""
        archive = tmp_path / "mod.7z"
        archive.write_bytes(b"data")
        unit = service.mark_as_content_unit(archive)

        ok = service.quick_set_cover(unit.id)

        assert ok is False

    def test_existing_cover_not_overwritten(
        self, service: ContentService, repo: ContentUnitRepository, tmp_path: Path
    ) -> None:
        """已有手动封面 → 返回 False，不覆盖。"""
        folder = tmp_path / "ModB"
        folder.mkdir()
        (folder / "auto.jpg").write_bytes(b"auto")
        (folder / "manual.png").write_bytes(b"manual")
        unit = service.mark_as_content_unit(folder)
        # 手动设置一张不同的封面
        from dataclasses import replace

        manual_set = replace(unit, cover_path="manual.png")
        repo.update(manual_set)

        ok = service.quick_set_cover(unit.id)

        assert ok is False
        updated = repo.get_by_id(unit.id)
        assert updated is not None
        assert updated.cover_path == "manual.png"  # 未被覆盖

    def test_nonexistent_unit_raises(self, service: ContentService) -> None:
        """unit_id 不存在 → 抛 ContentUnitNotFoundError。"""
        with pytest.raises(ContentUnitNotFoundError):
            service.quick_set_cover("nonexistent-id")

    def test_chinese_path_folder_unit(
        self, service: ContentService, repo: ContentUnitRepository, tmp_path: Path
    ) -> None:
        """中文路径文件夹内容单元 + 中文图片名 → 正常设置。"""
        folder = tmp_path / "护甲包"
        folder.mkdir()
        (folder / "预览.webp").write_bytes(b"img")

        unit = service.mark_as_content_unit(folder)
        from dataclasses import replace

        cleared = replace(unit, cover_path=None)
        repo.update(cleared)

        ok = service.quick_set_cover(unit.id)

        assert ok is True
        updated = repo.get_by_id(unit.id)
        assert updated is not None
        assert updated.cover_path == "预览.webp"


class TestMarkAsContentUnitAutoCover:
    def test_mark_folder_auto_sets_cover(
        self, service: ContentService, repo: ContentUnitRepository, tmp_path: Path
    ) -> None:
        """标记文件夹 → 自动录入第一张图片为封面。"""
        folder = tmp_path / "ModC"
        folder.mkdir()
        (folder / "a.jpg").write_bytes(b"a")
        (folder / "b.png").write_bytes(b"b")

        unit = service.mark_as_content_unit(folder)

        assert unit.cover_path == "a.jpg"
        persisted = repo.get_by_id(unit.id)
        assert persisted is not None
        assert persisted.cover_path == "a.jpg"

    def test_mark_folder_without_image_no_error(
        self, service: ContentService, repo: ContentUnitRepository, tmp_path: Path
    ) -> None:
        """标记文件夹 + 目录无图片 → 不报错，cover_path 为空。"""
        folder = tmp_path / "EmptyMod"
        folder.mkdir()
        (folder / "readme.txt").write_text("readme")

        unit = service.mark_as_content_unit(folder)

        assert unit.cover_path is None
        persisted = repo.get_by_id(unit.id)
        assert persisted is not None
        assert persisted.cover_path is None

    def test_mark_archive_does_not_set_cover(
        self, service: ContentService, repo: ContentUnitRepository, tmp_path: Path
    ) -> None:
        """标记压缩包 → 不触发自动录入（压缩包无目录内图片语义）。"""
        archive = tmp_path / "mod.7z"
        archive.write_bytes(b"data")

        unit = service.mark_as_content_unit(archive)

        assert unit.cover_path is None

    def test_remark_folder_creates_new_unit_with_auto_cover(
        self, service: ContentService, repo: ContentUnitRepository, tmp_path: Path
    ) -> None:
        """纯 DELETE 模式（Task 6）：unmark 删除记录后重新 mark 创建新记录。

        场景：用户先 mark → 自动录入 a.jpg → unmark（记录删除）→ 再 mark。
        再 mark 时创建全新记录，自动录入第一张图片（a.jpg）；
        原手动封面/标题等元数据随记录删除而丢失（roadmap 决策：取消标记 = DELETE）。
        """
        folder = tmp_path / "ModD"
        folder.mkdir()
        (folder / "a.jpg").write_bytes(b"a")
        (folder / "b.png").write_bytes(b"b")

        # 第一次 mark → 自动录入 a.jpg
        unit = service.mark_as_content_unit(folder)
        assert unit.cover_path == "a.jpg"

        # 手动改为 b.png
        from dataclasses import replace

        manual = replace(unit, cover_path="b.png")
        repo.update(manual)

        # unmark
        service.unmark_content_unit(unit.id)
        # 记录已删除
        assert repo.get_by_id(unit.id) is None

        # 再 mark → 创建新记录，自动录入第一张图片
        remark_unit = service.mark_as_content_unit(Path(folder))
        assert remark_unit.cover_path == "a.jpg"
        persisted = repo.get_by_id(remark_unit.id)
        assert persisted is not None
        assert persisted.cover_path == "a.jpg"
