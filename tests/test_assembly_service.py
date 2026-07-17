"""AssemblyService 测试（阶段 3 Task 4）。

覆盖：
- list_mod_group_files：列出 Mod 组文件夹内容
- add_file：从暂存区移入文件 + folder_cache 同步
- remove_file：从 Mod 组移回暂存区根目录
- rename_as_cover：手动重命名预览图（单张/多张/冲突/非图片/不在文件夹内）
- 不自动重命名（add_file 保留原文件名）
- 中文文件名 + 中文 Mod 组名
- ContentUnit 不存在抛异常
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from application.assembly_service import AssemblyService, is_image_file
from application.content_service import ContentService
from application.errors import (
    ConflictError,
    ContentUnitNotFoundError,
    InvalidContentUnitPathError,
)
from infrastructure.db import get_connection, init_db
from infrastructure.file_operation_service import FileOperationService
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.folder_cache import FolderCacheRepository
from infrastructure.repositories.operation_history import OperationHistoryRepository


@pytest.fixture
def assembly_env(tmp_path: Path):
    """构造 AssemblyService + ContentService + FileOperationService + 已初始化 DB。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row

    counter = {"n": 0}

    def fake_uuid() -> str:
        counter["n"] += 1
        return f"uuid-{counter['n']}"

    file_op = FileOperationService(
        OperationHistoryRepository(conn),
        now_provider=lambda: "2026-07-16T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    content_svc = ContentService(
        ContentUnitRepository(conn),
        now_provider=lambda: "2026-07-16T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    folder_cache_repo = FolderCacheRepository(conn)
    assembly_svc = AssemblyService(file_op, ContentUnitRepository(conn), folder_cache_repo)

    # 构造暂存区 + Mod 组文件夹
    staging = tmp_path / "Stash"
    staging.mkdir()
    mod_folder = staging / "BDOR Black Knight"
    mod_folder.mkdir()
    # Mod 组内放入一个本体文件
    (mod_folder / "BDOR Black Knight 1.0.7z").write_bytes(b"mod-content")

    # 标记 Mod 组文件夹为 ContentUnit
    unit = content_svc.mark_as_content_unit(mod_folder)
    conn.commit()

    yield assembly_svc, content_svc, conn, staging, mod_folder, unit

    conn.close()


# === list_mod_group_files ===


class TestListModGroupFiles:
    def test_lists_files_in_mod_group(self, assembly_env) -> None:
        """列出 Mod 组文件夹内所有文件。"""
        svc, _, _, _, mod_folder, unit = assembly_env
        # 再放一个文件
        (mod_folder / "readme.txt").write_bytes(b"readme")

        entries = svc.list_mod_group_files(unit.id)

        names = [e.name for e in entries]
        assert "BDOR Black Knight 1.0.7z" in names
        assert "readme.txt" in names

    def test_lists_subdirectories(self, assembly_env) -> None:
        """列出 Mod 组文件夹内的子目录。"""
        svc, _, _, _, mod_folder, unit = assembly_env
        (mod_folder / "预览图").mkdir()

        entries = svc.list_mod_group_files(unit.id)

        subdirs = [e for e in entries if e.is_dir]
        assert len(subdirs) == 1
        assert subdirs[0].name == "预览图"

    def test_folders_sorted_before_files(self, assembly_env) -> None:
        """文件夹排在文件之前。"""
        svc, _, _, _, mod_folder, unit = assembly_env
        (mod_folder / "zzz_file.txt").write_bytes(b"data")
        (mod_folder / "aaa_folder").mkdir()

        entries = svc.list_mod_group_files(unit.id)

        # 第一个应为文件夹
        assert entries[0].is_dir
        assert entries[0].name == "aaa_folder"

    def test_unit_not_exist_raises(self, assembly_env) -> None:
        """ContentUnit 不存在抛 ContentUnitNotFoundError。"""
        svc, _, _, _, _, _ = assembly_env
        with pytest.raises(ContentUnitNotFoundError):
            svc.list_mod_group_files("nonexistent-id")

    def test_path_not_directory_returns_empty(self, assembly_env, tmp_path: Path) -> None:
        """ContentUnit 路径不是目录返回空列表。"""
        svc, content_svc, conn, _, _, _ = assembly_env
        # 创建一个指向文件的 ContentUnit
        file_path = tmp_path / "single.7z"
        file_path.write_bytes(b"data")
        unit = content_svc.mark_as_content_unit(file_path)
        conn.commit()

        entries = svc.list_mod_group_files(unit.id)

        assert entries == []


# === add_file ===


class TestAddFile:
    def test_moves_file_to_mod_group(self, assembly_env) -> None:
        """从暂存区移入文件到 Mod 组文件夹。"""
        svc, _, _, staging, mod_folder, unit = assembly_env
        src = staging / "汉化.zip"
        src.write_bytes(b"localization")

        entry = svc.add_file(unit.id, src)

        # 源文件已移走
        assert not src.exists()
        # 文件出现在 Mod 组文件夹内
        target = mod_folder / "汉化.zip"
        assert target.is_file()
        assert target.read_bytes() == b"localization"
        # 返回的 FileEntry 指向新路径
        assert entry.name == "汉化.zip"
        assert entry.path == str(target)

    def test_preserves_original_filename(self, assembly_env) -> None:
        """add_file 不自动重命名（spec §7.4：自动整理阶段不修改文件名）。"""
        svc, _, _, staging, mod_folder, unit = assembly_env
        src = staging / "preview_v2.png"
        src.write_bytes(b"img")

        svc.add_file(unit.id, src)

        # 文件名保持原样
        assert (mod_folder / "preview_v2.png").is_file()
        # 不应被重命名为 Mod 组名
        assert not (mod_folder / "BDOR Black Knight.png").exists()

    def test_conflict_when_target_exists(self, assembly_env) -> None:
        """Mod 组内已存在同名文件抛 ConflictError。"""
        svc, _, _, staging, mod_folder, unit = assembly_env
        src = staging / "BDOR Black Knight 1.0.7z"
        src.write_bytes(b"duplicate")

        with pytest.raises(ConflictError):
            svc.add_file(unit.id, src)

    def test_syncs_folder_cache_mtime(self, assembly_env) -> None:
        """add_file 后同步更新 folder_cache.last_scanned_mtime。"""
        svc, _, conn, staging, mod_folder, unit = assembly_env
        # 先在 folder_cache 中记录 Mod 组文件夹
        from domain.models import FolderCache

        fc_repo = FolderCacheRepository(conn)
        fc = FolderCache(
            id="fc-test",
            path=str(mod_folder),
            parent_id=None,
            last_scanned_mtime=1000.0,
            created_at="2026-07-16T00:00:00Z",
        )
        fc_repo.create(fc)
        conn.commit()

        src = staging / "汉化.zip"
        src.write_bytes(b"data")
        svc.add_file(unit.id, src)
        conn.commit()

        # folder_cache.mtime 应已更新（不再是 1000.0）
        updated = fc_repo.get_by_path(str(mod_folder))
        assert updated is not None
        assert updated.last_scanned_mtime != 1000.0

    def test_unit_not_exist_raises(self, assembly_env, tmp_path: Path) -> None:
        """ContentUnit 不存在抛 ContentUnitNotFoundError。"""
        svc, _, _, staging, _, _ = assembly_env
        src = staging / "file.zip"
        src.write_bytes(b"data")

        with pytest.raises(ContentUnitNotFoundError):
            svc.add_file("nonexistent-id", src)


# === remove_file ===


class TestRemoveFile:
    def test_moves_file_back_to_staging_root(self, assembly_env) -> None:
        """从 Mod 组移除文件 → 移回暂存区根目录（不保留原子目录结构）。"""
        svc, _, _, staging, mod_folder, unit = assembly_env
        # Mod 组内放入文件
        target = mod_folder / "汉化.zip"
        target.write_bytes(b"localization")

        result = svc.remove_file(unit.id, "汉化.zip", staging)

        # 文件已从 Mod 组移走
        assert not target.exists()
        # 文件移回暂存区根目录
        assert (staging / "汉化.zip").is_file()
        assert result == staging / "汉化.zip"

    def test_conflict_when_staging_has_same_name(self, assembly_env) -> None:
        """暂存区根目录已存在同名文件抛 ConflictError。"""
        svc, _, _, staging, mod_folder, unit = assembly_env
        target = mod_folder / "汉化.zip"
        target.write_bytes(b"mod-copy")
        # 暂存区已存在同名文件
        (staging / "汉化.zip").write_bytes(b"staging-copy")

        with pytest.raises(ConflictError):
            svc.remove_file(unit.id, "汉化.zip", staging)

    def test_unit_not_exist_raises(self, assembly_env) -> None:
        """ContentUnit 不存在抛 ContentUnitNotFoundError。"""
        svc, _, _, staging, _, _ = assembly_env
        with pytest.raises(ContentUnitNotFoundError):
            svc.remove_file("nonexistent-id", "file.zip", staging)


# === rename_as_cover ===


class TestRenameAsCover:
    def test_renames_single_image_to_mod_name(self, assembly_env) -> None:
        """单张图片重命名为 {Mod组名}.{扩展名}。"""
        svc, _, _, _, mod_folder, unit = assembly_env
        img = mod_folder / "preview.png"
        img.write_bytes(b"img-data")

        result = svc.rename_as_cover(unit.id, img)

        # 原文件已不在
        assert not img.exists()
        # 新文件名为 Mod 组名 + 原扩展名
        assert result == mod_folder / "BDOR Black Knight.png"
        assert result.is_file()
        assert result.read_bytes() == b"img-data"

    def test_multiple_images_get_suffix(self, assembly_env) -> None:
        """多张图片：第一张为 {Mod组名}.ext，后续为 _2、_3……"""
        svc, _, _, _, mod_folder, unit = assembly_env
        img1 = mod_folder / "preview1.png"
        img1.write_bytes(b"img1")
        img2 = mod_folder / "preview2.png"
        img2.write_bytes(b"img2")
        img3 = mod_folder / "preview3.png"
        img3.write_bytes(b"img3")

        r1 = svc.rename_as_cover(unit.id, img1)
        r2 = svc.rename_as_cover(unit.id, img2)
        r3 = svc.rename_as_cover(unit.id, img3)

        assert r1.name == "BDOR Black Knight.png"
        assert r2.name == "BDOR Black Knight_2.png"
        assert r3.name == "BDOR Black Knight_3.png"

    def test_idempotent_when_already_renamed(self, assembly_env) -> None:
        """图片已叫 {Mod组名}.ext 时幂等返回（不抛 ConflictError）。"""
        svc, _, _, _, mod_folder, unit = assembly_env
        img = mod_folder / "BDOR Black Knight.png"
        img.write_bytes(b"img-data")

        result = svc.rename_as_cover(unit.id, img)

        assert result == img  # 原路径返回

    def test_non_image_raises(self, assembly_env) -> None:
        """非图片文件抛 InvalidContentUnitPathError。"""
        svc, _, _, _, mod_folder, unit = assembly_env
        txt = mod_folder / "readme.txt"
        txt.write_bytes(b"text")

        with pytest.raises(InvalidContentUnitPathError):
            svc.rename_as_cover(unit.id, txt)

    def test_image_outside_mod_group_raises(self, assembly_env, tmp_path: Path) -> None:
        """图片不在 Mod 组文件夹内抛 InvalidContentUnitPathError。"""
        svc, _, _, _, _, unit = assembly_env
        outside = tmp_path / "outside.png"
        outside.write_bytes(b"img")

        with pytest.raises(InvalidContentUnitPathError):
            svc.rename_as_cover(unit.id, outside)

    def test_preserves_original_extension(self, assembly_env) -> None:
        """保留原扩展名（.jpg 不转换为 .png）。"""
        svc, _, _, _, mod_folder, unit = assembly_env
        img = mod_folder / "preview.jpg"
        img.write_bytes(b"jpg-data")

        result = svc.rename_as_cover(unit.id, img)

        assert result.suffix == ".jpg"
        assert result.name == "BDOR Black Knight.jpg"

    def test_chinese_mod_name(self, assembly_env, tmp_path: Path) -> None:
        """中文 Mod 组名的图片重命名。"""
        svc, content_svc, conn, staging, _, _ = assembly_env
        # 构造中文 Mod 组
        cn_folder = staging / "寒霜之心"
        cn_folder.mkdir()
        (cn_folder / "寒霜之心 1.0.7z").write_bytes(b"data")
        cn_unit = content_svc.mark_as_content_unit(cn_folder)
        conn.commit()

        img = cn_folder / "preview.png"
        img.write_bytes(b"img")

        result = svc.rename_as_cover(cn_unit.id, img)

        assert result.name == "寒霜之心.png"

    def test_unit_not_exist_raises(self, assembly_env, tmp_path: Path) -> None:
        """ContentUnit 不存在抛 ContentUnitNotFoundError。"""
        svc, _, _, _, _, _ = assembly_env
        img = tmp_path / "test.png"
        img.write_bytes(b"data")

        with pytest.raises(ContentUnitNotFoundError):
            svc.rename_as_cover("nonexistent-id", img)


# === is_image_file ===


class TestIsImageFile:
    def test_supported_extensions(self) -> None:
        """支持的图片扩展名返回 True。"""
        assert is_image_file(Path("test.png"))
        assert is_image_file(Path("test.jpg"))
        assert is_image_file(Path("test.JPEG"))  # 大小写不敏感
        assert is_image_file(Path("test.webp"))
        assert is_image_file(Path("test.gif"))
        assert is_image_file(Path("test.bmp"))
        assert is_image_file(Path("test.tif"))
        assert is_image_file(Path("test.tiff"))
        assert is_image_file(Path("test.ico"))

    def test_unsupported_extensions(self) -> None:
        """非图片扩展名返回 False。"""
        assert not is_image_file(Path("test.7z"))
        assert not is_image_file(Path("test.zip"))
        assert not is_image_file(Path("test.txt"))
        assert not is_image_file(Path("test"))  # 无扩展名
