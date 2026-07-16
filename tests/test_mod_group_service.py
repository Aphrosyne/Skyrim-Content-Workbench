"""ModGroupService 测试。

覆盖：
- 文件名提取规则（6 种格式）
- create_mod_group 完整流程
- 失败回滚（move 失败时清理空文件夹）
- ContentUnit 创建
- 中文路径
- 源不在暂存区
- 名称冲突
- 名称无效
- 操作历史写入
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from application.content_service import ContentService
from application.errors import (
    ConflictError,
    FileOperationError,
    InvalidModGroupNameError,
    ModGroupSourceNotInStagingError,
)
from application.mod_group_service import ModGroupService, extract_mod_name
from domain.models import ContentUnit
from infrastructure.db import get_connection, init_db
from infrastructure.file_operation_service import FileOperationService
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.operation_history import OperationHistoryRepository

# === 文件名提取规则 ===


class TestExtractModName:
    def test_strips_version_decimal(self) -> None:
        assert extract_mod_name("BDOR Black Knight 1.0.7z") == "BDOR Black Knight"

    def test_strips_version_v_prefix(self) -> None:
        assert extract_mod_name("SkyUI 5.1 SE.zip") == "SkyUI"

    def test_strips_version_separator(self) -> None:
        assert extract_mod_name("Armor Pack - 2.3.7z") == "Armor Pack"

    def test_no_version_returns_stem(self) -> None:
        assert extract_mod_name("RealisticWater.7z") == "RealisticWater"

    def test_chinese_filename(self) -> None:
        assert extract_mod_name("寒霜之心 1.0.7z") == "寒霜之心"

    def test_strips_extension_only(self) -> None:
        assert extract_mod_name("readme.txt") == "readme"

    def test_no_extension(self) -> None:
        assert extract_mod_name("noextension") == "noextension"

    def test_multiple_extensions(self) -> None:
        """多个点分隔的文件名（如 file.1.0.7z）应正确去版本号。"""
        # "file.1.0.7z" → stem = "file.1.0" → 去版本号 "1.0" → "file"
        assert extract_mod_name("file.1.0.7z") == "file"

    # === Nexus Mods 下载命名规则 ===

    def test_nexus_name_with_hyphen(self) -> None:
        """Nexus 命名：名称内部含 -，ID 后有版本号 + 时间戳。"""
        assert extract_mod_name("Alt-Tab Fix-148466-1-0-0-1745430887.zip") == "Alt-Tab Fix"

    def test_nexus_name_lowercase_with_spaces(self) -> None:
        """Nexus 命名：小写 + 空格的 Mod 名。"""
        assert (
            extract_mod_name("monster race crash fix-19899-1-2-1583905408.zip")
            == "monster race crash fix"
        )

    def test_nexus_name_no_extension(self) -> None:
        """Nexus 命名：无扩展名的文件。"""
        assert extract_mod_name("Erin Suzu preset-173150-1-0-1771738716") == "Erin Suzu preset"

    def test_nexus_name_se_version(self) -> None:
        """Nexus 命名：含 SE 后缀的 7z 文件。"""
        assert (
            extract_mod_name("Slow Sprint Bug Fix-57245-1-0-1634664801.7z") == "Slow Sprint Bug Fix"
        )

    def test_nexus_name_multiple_version_segments(self) -> None:
        """Nexus 命名：版本号有多个段（1-0-1）。"""
        assert extract_mod_name("Media Keys Fix-92948-1-0-1-1716329765.7z") == "Media Keys Fix"

    def test_nexus_name_strips_trailing_whitespace(self) -> None:
        """Nexus 命名：名称前后无多余空白。"""
        assert extract_mod_name("MyMod-12345-1-0-1700000000.zip") == "MyMod"

    def test_non_nexus_short_name_not_matched(self) -> None:
        """短名 Mod-123（ID 后无版本段）不匹配 Nexus 规则，回退通用策略。"""
        # "Mod-123.7z" → stem = "Mod-123" → 不匹配 Nexus（要求 ID 后至少一个段）
        # → 回退通用版本号：无 "." 分隔的版本号 → 返回 "Mod-123"
        assert extract_mod_name("Mod-123.7z") == "Mod-123"


# === create_mod_group 完整流程 ===


@pytest.fixture
def mod_group_env(tmp_path: Path):
    """构造 ModGroupService + ContentService + FileOperationService + 已初始化 DB。"""
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
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    content_svc = ContentService(
        ContentUnitRepository(conn),
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    mod_group_svc = ModGroupService(file_op, content_svc)

    # 构造暂存区目录
    staging = tmp_path / "Stash"
    staging.mkdir()

    yield mod_group_svc, content_svc, conn, staging

    conn.close()


class TestCreateModGroup:
    def test_creates_folder_and_moves_file(self, mod_group_env, tmp_path: Path) -> None:
        """完整流程：建文件夹 + 移文件。"""
        svc, _, conn, staging = mod_group_env
        src = staging / "BDOR Black Knight 1.0.7z"
        src.write_bytes(b"mod-content")

        unit = svc.create_mod_group(src, staging)

        # 文件夹被创建
        target_folder = staging / "BDOR Black Knight"
        assert target_folder.is_dir()
        # 源文件被移入
        assert not src.exists()
        target_file = target_folder / "BDOR Black Knight 1.0.7z"
        assert target_file.is_file()
        assert target_file.read_bytes() == b"mod-content"
        # ContentUnit 指向新文件夹
        assert isinstance(unit, ContentUnit)
        assert unit.path == str(target_folder)
        assert unit.title == "BDOR Black Knight"
        assert unit.status == "unorganized"

    def test_writes_two_operation_history(self, mod_group_env) -> None:
        """创建 Mod 组写 2 条 operation_history：new_folder + move。"""
        svc, _, conn, staging = mod_group_env
        src = staging / "mod 1.0.7z"
        src.write_bytes(b"data")

        svc.create_mod_group(src, staging)
        conn.commit()

        rows = conn.execute("SELECT * FROM operation_history ORDER BY created_at").fetchall()
        assert len(rows) == 2
        types = [r["operation_type"] for r in rows]
        assert "new_folder" in types
        assert "move" in types

    def test_rejects_existing_folder_name(self, mod_group_env) -> None:
        """同名文件夹已存在抛 ConflictError。"""
        svc, _, _, staging = mod_group_env
        src = staging / "mod 1.0.7z"
        src.write_bytes(b"data")
        # 预先创建同名文件夹
        (staging / "mod").mkdir()

        with pytest.raises(ConflictError):
            svc.create_mod_group(src, staging, name="mod")

    def test_move_failure_rolls_back_empty_folder(self, mod_group_env) -> None:
        """move 失败时清理已创建的空文件夹。"""
        svc, _, _, staging = mod_group_env
        # 构造 move 失败：源文件不存在
        # 但 source_file 必须先通过 _is_in_directory 校验
        src = staging / "nonexistent.7z"

        with pytest.raises(FileOperationError):
            svc.create_mod_group(src, staging, name="NewMod")

        # 空文件夹应被清理
        assert not (staging / "NewMod").exists()

    def test_chinese_name(self, mod_group_env) -> None:
        """中文名 Mod 组。"""
        svc, _, _, staging = mod_group_env
        src = staging / "寒霜之心 1.0.7z"
        src.write_bytes(b"data")

        unit = svc.create_mod_group(src, staging)

        target_folder = staging / "寒霜之心"
        assert target_folder.is_dir()
        assert unit.title == "寒霜之心"

    def test_source_not_in_staging_raises(self, mod_group_env, tmp_path: Path) -> None:
        """源文件不在暂存区下抛 ModGroupSourceNotInStagingError。"""
        svc, _, _, staging = mod_group_env
        # 在暂存区外构造源文件
        outside = tmp_path / "outside.7z"
        outside.write_bytes(b"data")

        with pytest.raises(ModGroupSourceNotInStagingError):
            svc.create_mod_group(outside, staging)

    def test_invalid_name_raises(self, mod_group_env) -> None:
        """空名称抛 InvalidModGroupNameError。"""
        svc, _, _, staging = mod_group_env
        src = staging / "mod 1.0.7z"
        src.write_bytes(b"data")

        with pytest.raises(InvalidModGroupNameError):
            svc.create_mod_group(src, staging, name="")

    def test_invalid_name_whitespace_only(self, mod_group_env) -> None:
        """仅空白名称抛 InvalidModGroupNameError。"""
        svc, _, _, staging = mod_group_env
        src = staging / "mod 1.0.7z"
        src.write_bytes(b"data")

        with pytest.raises(InvalidModGroupNameError):
            svc.create_mod_group(src, staging, name="   ")

    def test_explicit_name_overrides_extraction(self, mod_group_env) -> None:
        """显式指定 name 时跳过文件名提取。"""
        svc, _, _, staging = mod_group_env
        src = staging / "mod 1.0.7z"
        src.write_bytes(b"data")

        unit = svc.create_mod_group(src, staging, name="CustomName")

        target_folder = staging / "CustomName"
        assert target_folder.is_dir()
        assert unit.title == "CustomName"

    def test_source_file_content_preserved(self, mod_group_env) -> None:
        """源文件内容在移动后保持不变。"""
        svc, _, _, staging = mod_group_env
        src = staging / "mod 1.0.7z"
        content = b"\x00" * 1024 + b"end"
        src.write_bytes(content)

        svc.create_mod_group(src, staging)

        target_file = staging / "mod" / "mod 1.0.7z"
        assert target_file.read_bytes() == content


# === folder_cache 同步写入（2026-07-16 修复） ===


@pytest.fixture
def mod_group_env_with_folder_cache(tmp_path: Path):
    """构造注入了 FolderCacheRepository 的 ModGroupService 环境。

    用于测试 create_mod_group 同步写入 folder_cache 时 parent_id 的正确关联。
    """
    from domain.models import FolderCache
    from infrastructure.repositories.folder_cache import FolderCacheRepository

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
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    content_svc = ContentService(
        ContentUnitRepository(conn),
        now_provider=lambda: "2026-07-14T00:00:00Z",
        uuid_provider=fake_uuid,
    )
    folder_cache_repo = FolderCacheRepository(conn)
    mod_group_svc = ModGroupService(file_op, content_svc, folder_cache_repo)

    # 构造暂存区目录
    staging = tmp_path / "Stash"
    staging.mkdir()

    # 预先在 folder_cache 中插入暂存区记录（模拟扫描结果）
    staging_fc = FolderCache(
        id="staging-fc-id",
        path=str(staging),
        parent_id=None,
        last_scanned_mtime=staging.stat().st_mtime,
        created_at="2026-07-14T00:00:00Z",
    )
    folder_cache_repo.create(staging_fc)
    conn.commit()

    yield mod_group_svc, folder_cache_repo, conn, staging

    conn.close()


class TestFolderCacheSync:
    """create_mod_group 同步写入 folder_cache 的 parent_id 关联测试。"""

    def test_writes_folder_cache_with_correct_parent_id(
        self, mod_group_env_with_folder_cache
    ) -> None:
        """创建 Mod 组后 folder_cache 中新记录的 parent_id 正确指向暂存区记录。"""
        svc, folder_cache_repo, conn, staging = mod_group_env_with_folder_cache
        src = staging / "BDOR Black Knight 1.0.7z"
        src.write_bytes(b"data")

        svc.create_mod_group(src, staging)
        conn.commit()

        # 查询新文件夹的 folder_cache 记录
        target_path = str(staging / "BDOR Black Knight")
        new_fc = folder_cache_repo.get_by_path(target_path)
        assert new_fc is not None
        # parent_id 应指向暂存区的 folder_cache.id
        assert new_fc.parent_id == "staging-fc-id"

    def test_parent_id_lookup_normalizes_path(
        self, mod_group_env_with_folder_cache, tmp_path: Path
    ) -> None:
        """staging_path 与 folder_cache.path 字符串存在分隔符差异时仍能正确关联。

        回归测试：旧实现用 get_by_path 精确字符串匹配，若 staging_path 用
        反斜杠而 folder_cache.path 用正斜杠（或反之），会返回 None 导致
        parent_id=None，新文件夹成为孤儿节点，目录树不显示。
        新实现用 make_path_key 归一化查找，避免此问题。
        """
        svc, folder_cache_repo, conn, staging = mod_group_env_with_folder_cache

        # 修改 folder_cache 中暂存区记录的 path 为正斜杠形式
        # （模拟 FileScanner 存储路径与 staging_path 字符串不一致的场景）
        staging_fc = folder_cache_repo.get_by_path(str(staging))
        assert staging_fc is not None
        # 用正斜杠形式更新 path（模拟路径字符串差异）
        posix_path = str(staging).replace("\\", "/")
        conn.execute(
            "UPDATE folder_cache SET path = ? WHERE id = ?",
            (posix_path, staging_fc.id),
        )
        conn.commit()

        # create_mod_group 传入反斜杠的 staging_path
        src = staging / "TestMod 1.0.7z"
        src.write_bytes(b"data")
        svc.create_mod_group(src, staging)
        conn.commit()

        # 新文件夹的 parent_id 仍应正确指向暂存区记录
        target_path = str(staging / "TestMod")
        new_fc = folder_cache_repo.get_by_path(target_path)
        assert new_fc is not None
        assert new_fc.parent_id == staging_fc.id
