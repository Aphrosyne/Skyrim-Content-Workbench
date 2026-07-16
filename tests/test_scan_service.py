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
    counter = {"n": 0}

    def fake_uuid() -> str:
        counter["n"] += 1
        return f"root-{counter['n']}"

    return ManagedRootService(
        ManagedRootRepository(db_connection),
        now_provider=lambda: "2026-07-12T00:00:00Z",
        uuid_provider=fake_uuid,
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


class TestCleanupDeletedFolders:
    """扫描后清理已删除目录的 folder_cache 残留记录（2026-07-16 修复）。"""

    def test_full_scan_cleans_deleted_dir(
        self,
        scan_service: ScanService,
        managed_root_service: ManagedRootService,
        mod_tree: Path,
        db_connection,
    ) -> None:
        """全量扫描后删除目录，重新扫描应清理 folder_cache 中的残留记录。"""
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)
        db_connection.commit()

        repo = FolderCacheRepository(db_connection)
        before_count = len(repo.list_all())
        assert before_count > 0

        # 删除"普通文件夹"目录
        import shutil

        shutil.rmtree(mod_tree / "普通文件夹")

        # 重新全量扫描
        scan_service.scan_root(root.id, incremental=False)
        db_connection.commit()

        # folder_cache 中不应再有"普通文件夹"的记录
        folders = repo.list_all()
        paths = [f.path for f in folders]
        deleted_path = str(mod_tree / "普通文件夹")
        assert deleted_path not in paths

    def test_incremental_scan_cleans_deleted_dir(
        self,
        scan_service: ScanService,
        managed_root_service: ManagedRootService,
        mod_tree: Path,
        db_connection,
    ) -> None:
        """增量扫描也应清理已删除目录的残留记录。

        增量扫描用 all_visited_dirs（实际访问到的所有目录）对比，
        即使 mtime 未变的目录也会被访问到，已删除目录不在访问集合中，
        会被清理。
        """
        root = managed_root_service.add_root(mod_tree)
        scan_service.scan_root(root.id, incremental=False)
        db_connection.commit()

        # 删除"Weapons"目录
        import shutil

        shutil.rmtree(mod_tree / "Weapons")

        # 增量扫描
        scan_service.scan_root(root.id, incremental=True)
        db_connection.commit()

        repo = FolderCacheRepository(db_connection)
        folders = repo.list_all()
        paths = [f.path for f in folders]
        assert str(mod_tree / "Weapons") not in paths
        # 子目录也应被清理
        assert str(mod_tree / "Weapons" / "sub") not in paths

    def test_cleanup_only_affects_scanned_root(
        self,
        scan_service: ScanService,
        managed_root_service: ManagedRootService,
        mod_tree: Path,
        tmp_path: Path,
        db_connection,
    ) -> None:
        """清理只影响当前扫描的 root，不误删其他 root 的记录。"""
        # 两个独立的 root
        root1_dir = mod_tree  # 第一个 root
        root2_dir = tmp_path / "other_root"
        root2_dir.mkdir()
        (root2_dir / "SubDir").mkdir()

        root1 = managed_root_service.add_root(root1_dir)
        root2 = managed_root_service.add_root(root2_dir)

        # 扫描两个 root
        scan_service.scan_root(root1.id, incremental=False)
        scan_service.scan_root(root2.id, incremental=False)
        db_connection.commit()

        repo = FolderCacheRepository(db_connection)
        assert len(repo.list_all()) > 0

        # 删除 root1 下的目录
        import shutil

        shutil.rmtree(root1_dir / "普通文件夹")

        # 只扫描 root1
        scan_service.scan_root(root1.id, incremental=False)
        db_connection.commit()

        # root2 的记录应保留
        folders = repo.list_all()
        paths = [f.path for f in folders]
        assert str(root2_dir / "SubDir") in paths

    def test_all_visited_dirs_populated(
        self,
        scan_service: ScanService,
        managed_root_service: ManagedRootService,
        mod_tree: Path,
        db_connection,
    ) -> None:
        """FileScanner 的 all_visited_dirs 收集所有访问到的目录。"""
        from infrastructure.file_scanner import FileScanner

        scanner = FileScanner()
        result = scanner.scan_full(mod_tree)

        # all_visited_dirs 应包含所有目录（含根、子目录）
        assert str(mod_tree) in result.all_visited_dirs
        assert str(mod_tree / "护甲") in result.all_visited_dirs
        assert str(mod_tree / "Weapons") in result.all_visited_dirs
        assert str(mod_tree / "Weapons" / "sub") in result.all_visited_dirs
        assert str(mod_tree / "普通文件夹") in result.all_visited_dirs
