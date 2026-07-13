"""ScanService 测试。

覆盖（spec §5.4 2026-07-13 修正）：
- scan_root 增量模式：跳过未变更目录
- scan_root 全量模式：全量扫描
- scan_root 持久化：folder_cache 表有记录，content_unit 表有压缩包候选记录
- scan_root 重复扫描：已存在的 content_unit 不重复创建
- scan_root 不存在 → ManagedRootNotFoundError
- scan_root_by_path 成功
- ScanSummary 字段正确
- 中文路径端到端
- 压缩包文件本身作为 ContentUnit.path（新规则）
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from application.errors import ManagedRootNotFoundError
from application.managed_root_service import ManagedRootService
from application.scan_service import ScanService
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.folder_cache import FolderCacheRepository
from infrastructure.repositories.managed_root import ManagedRootRepository


@pytest.fixture
def scan_service(db_connection) -> ScanService:
    """构造使用固定时间/UUID 的 ScanService，便于测试。"""
    counter = {"n": 0}

    def fake_uuid() -> str:
        counter["n"] += 1
        return f"uuid-{counter['n']}"

    return ScanService(
        managed_root_repo=ManagedRootRepository(db_connection),
        folder_cache_repo=FolderCacheRepository(db_connection),
        content_unit_repo=ContentUnitRepository(db_connection),
        now_provider=lambda: "2026-07-12T00:00:00Z",
        uuid_provider=fake_uuid,
    )


@pytest.fixture
def managed_root_service(db_connection) -> ManagedRootService:
    return ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-12T00:00:00Z",
        uuid_provider=lambda: "root-uuid",
    )


@pytest.fixture
def mod_tree(tmp_path: Path) -> Path:
    """构造样本目录树（含两个压缩包 + 一个普通文件夹 + 嵌套压缩包）。

    spec §5.4 2026-07-13 修正：压缩包文件本身作为内容单元候选。
    """
    root = tmp_path / "mods"
    root.mkdir()

    armor = root / "护甲"
    armor.mkdir()
    (armor / "寒霜之心.7z").write_bytes(b"\x00" * 100)

    weapons = root / "Weapons"
    weapons.mkdir()
    (weapons / "DragonSword.rar").write_bytes(b"\x00" * 80)
    # 嵌套压缩包（验证递归）
    (weapons / "sub").mkdir()
    (weapons / "sub" / "nested.zip").write_bytes(b"\x00" * 60)

    normal = root / "普通文件夹"
    normal.mkdir()
    (normal / "readme.txt").write_bytes(b"data")

    return root


class TestScanRootFull:
    def test_full_scan_persists_folder_cache(
        self, scan_service: ScanService, managed_root_service: ManagedRootService, mod_tree: Path
    ) -> None:
        root = managed_root_service.add_root(mod_tree)
        summary = scan_service.scan_root(root.id, incremental=False)

        assert summary.scanned_dirs > 0
        # 三个压缩包：寒霜之心.7z + DragonSword.rar + nested.zip
        assert summary.content_units_found == 3
        assert summary.skipped_unchanged == 0
        assert summary.root_id == root.id

    def test_full_scan_persists_content_units_as_archive_paths(
        self,
        scan_service: ScanService,
        managed_root_service: ManagedRootService,
        mod_tree: Path,
        db_connection,
    ) -> None:
        """新规则：ContentUnit.path 为压缩包文件路径，不是文件夹路径。"""
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)

        repo = ContentUnitRepository(db_connection)
        units = repo.list_all()
        paths = {u.path for u in units}
        # 压缩包文件路径
        assert str(mod_tree / "护甲" / "寒霜之心.7z") in paths
        assert str(mod_tree / "Weapons" / "DragonSword.rar") in paths
        assert str(mod_tree / "Weapons" / "sub" / "nested.zip") in paths
        # 文件夹路径不应为内容单元
        assert str(mod_tree / "护甲") not in paths
        assert str(mod_tree / "Weapons") not in paths
        assert str(mod_tree / "普通文件夹") not in paths

    def test_full_scan_content_unit_default_status(
        self,
        scan_service: ScanService,
        managed_root_service: ManagedRootService,
        mod_tree: Path,
        db_connection,
    ) -> None:
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)

        repo = ContentUnitRepository(db_connection)
        for unit in repo.list_all():
            assert unit.status == "unorganized"
            assert unit.content_type == "mod"

    def test_full_scan_content_unit_title_is_filename_with_ext(
        self,
        scan_service: ScanService,
        managed_root_service: ManagedRootService,
        mod_tree: Path,
        db_connection,
    ) -> None:
        """新规则：title 为压缩包文件名（含扩展名）。"""
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)

        repo = ContentUnitRepository(db_connection)
        units = repo.list_all()
        titles = {u.title for u in units}
        assert "寒霜之心.7z" in titles
        assert "DragonSword.rar" in titles
        assert "nested.zip" in titles


class TestScanRootIncremental:
    def test_incremental_skips_unchanged(
        self, scan_service: ScanService, managed_root_service: ManagedRootService, mod_tree: Path
    ) -> None:
        root = managed_root_service.add_root(mod_tree)
        # 第一次扫描（全量）
        first = scan_service.scan_root(root.id, incremental=False)
        assert first.skipped_unchanged == 0

        # 第二次扫描（增量）应跳过所有未变更目录
        second = scan_service.scan_root(root.id, incremental=True)
        assert second.skipped_unchanged > 0
        assert second.scanned_dirs == 0
        # 已存在的内容单元不重复创建
        assert second.content_units_found == 0

    def test_incremental_rescans_changed(
        self,
        scan_service: ScanService,
        managed_root_service: ManagedRootService,
        mod_tree: Path,
        db_connection,
    ) -> None:
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)

        # 修改"普通文件夹"使其 mtime 变化
        time.sleep(0.01)
        (mod_tree / "普通文件夹" / "new.txt").write_text("new")

        # 增量扫描应重新扫描"普通文件夹"
        summary = scan_service.scan_root(root.id, incremental=True)
        assert summary.scanned_dirs > 0
        assert summary.skipped_unchanged > 0


class TestScanRootErrors:
    def test_root_not_exist_raises(self, scan_service: ScanService) -> None:
        with pytest.raises(ManagedRootNotFoundError):
            scan_service.scan_root("nonexistent-id", incremental=False)

    def test_scan_nonexistent_root_path_records_error(
        self, scan_service: ScanService, managed_root_service: ManagedRootService, tmp_path: Path
    ) -> None:
        """添加一个真实目录为受管理根，然后删除该目录，扫描应记录错误。"""
        root_dir = tmp_path / "will_delete"
        root_dir.mkdir()
        root = managed_root_service.add_root(root_dir)
        # 删除目录
        import shutil

        shutil.rmtree(root_dir)

        summary = scan_service.scan_root(root.id, incremental=False)
        assert summary.has_errors
        assert any("不存在" in err for err in summary.errors)


class TestScanRootByPath:
    def test_scan_by_path_full(
        self, scan_service: ScanService, mod_tree: Path, db_connection
    ) -> None:
        summary = scan_service.scan_root_by_path(mod_tree, incremental=False)
        assert summary.scanned_dirs > 0
        assert summary.content_units_found == 3  # 三个压缩包
        assert summary.root_id == "_adhoc"

        # 验证 content_unit 已持久化
        repo = ContentUnitRepository(db_connection)
        assert len(repo.list_all()) == 3


class TestRepeatScan:
    def test_repeat_scan_no_duplicate_content_units(
        self,
        scan_service: ScanService,
        managed_root_service: ManagedRootService,
        mod_tree: Path,
        db_connection,
    ) -> None:
        root = managed_root_service.add_root(mod_tree)

        # 第一次扫描
        scan_service.scan_root(root.id, incremental=False)
        # 第二次全量扫描
        scan_service.scan_root(root.id, incremental=False)

        repo = ContentUnitRepository(db_connection)
        units = repo.list_all()
        # 仍只有 3 个内容单元（path 唯一约束去重）
        assert len(units) == 3

    def test_repeat_scan_no_duplicate_folder_cache(
        self,
        scan_service: ScanService,
        managed_root_service: ManagedRootService,
        mod_tree: Path,
        db_connection,
    ) -> None:
        root = managed_root_service.add_root(mod_tree)

        scan_service.scan_root(root.id, incremental=False)
        scan_service.scan_root(root.id, incremental=False)

        repo = FolderCacheRepository(db_connection)
        folders = repo.list_all()
        paths = [f.path for f in folders]
        # 无重复路径
        assert len(paths) == len(set(paths))
