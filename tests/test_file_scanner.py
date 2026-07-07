"""FileScanner 与 persist_scan_result 测试。

所有测试使用 tmp_path / sample_mod_tree fixture，
扫描器仅读取临时目录，不写入、不移动、不删除用户文件。
"""

from __future__ import annotations

import os
import stat
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from domain.models import AssetKind, FileRole
from infrastructure.file_classify import AssetHint
from infrastructure.file_scanner import (
    FileScanner,
    persist_scan_result,
)
from infrastructure.repositories.file_asset import FileAssetRepository
from infrastructure.repositories.folder_node import FolderNodeRepository

# ---------- 固定时间 / UUID provider，便于测试断言 ----------


def _fixed_now() -> str:
    return "2026-07-07T00:00:00Z"


def _sequential_uuid() -> str:
    """每次调用返回新 UUID（测试中无需固定值，仅保证唯一）。"""
    return str(uuid.uuid4())


# ---------- 正常扫描 ----------


def test_scan_empty_directory(tmp_path: Path) -> None:
    """空目录：folders 含根，files 为空。"""
    empty_root = tmp_path / "empty"
    empty_root.mkdir()

    scanner = FileScanner(now_provider=_fixed_now)
    result = scanner.scan(empty_root)

    assert len(result.folders) == 1
    assert result.folders[0].real_path == empty_root
    assert result.folders[0].is_dir is True
    assert result.folders[0].size_bytes == 0
    assert result.folders[0].extension == ""
    assert result.folders[0].asset_hint == AssetHint.OTHER
    assert len(result.files) == 0
    assert len(result.errors) == 0


def test_scan_sample_tree(sample_mod_tree: Path) -> None:
    """扫描样本目录树，验证目录与文件数量。"""
    scanner = FileScanner(now_provider=_fixed_now)
    result = scanner.scan(sample_mod_tree)

    # folders: 根 + 护甲 + Weapons + 空目录 = 4
    assert len(result.folders) == 4
    # files: 寒霜之心.7z + 汉化.zip + preview.webp + DragonSword.rar + README.txt
    #      + normal_file.txt + no_extension = 7
    assert len(result.files) == 7
    assert len(result.errors) == 0


def test_scan_chinese_directories(sample_mod_tree: Path) -> None:
    """中文目录名应正确出现在结果中。"""
    scanner = FileScanner(now_provider=_fixed_now)
    result = scanner.scan(sample_mod_tree)

    folder_names = {f.real_path.name for f in result.folders}
    assert "护甲" in folder_names
    assert "空目录" in folder_names


def test_scan_chinese_filenames(sample_mod_tree: Path) -> None:
    """中文文件名应正确出现在结果中。"""
    scanner = FileScanner(now_provider=_fixed_now)
    result = scanner.scan(sample_mod_tree)

    file_names = {f.real_path.name for f in result.files}
    assert "寒霜之心.7z" in file_names
    assert "寒霜之心-汉化.zip" in file_names


def test_scan_english_directories(sample_mod_tree: Path) -> None:
    """英文目录名应正确出现在结果中。"""
    scanner = FileScanner(now_provider=_fixed_now)
    result = scanner.scan(sample_mod_tree)

    folder_names = {f.real_path.name for f in result.folders}
    assert "Weapons" in folder_names


def test_scan_image_classification(sample_mod_tree: Path) -> None:
    """图片文件 asset_hint 应为 IMAGE。"""
    scanner = FileScanner(now_provider=_fixed_now)
    result = scanner.scan(sample_mod_tree)

    images = [f for f in result.files if f.asset_hint == AssetHint.IMAGE]
    assert len(images) == 1
    assert images[0].real_path.name == "preview.webp"


def test_scan_archive_classification(sample_mod_tree: Path) -> None:
    """压缩包文件 asset_hint 应为 ARCHIVE。"""
    scanner = FileScanner(now_provider=_fixed_now)
    result = scanner.scan(sample_mod_tree)

    archives = [f for f in result.files if f.asset_hint == AssetHint.ARCHIVE]
    archive_names = {a.real_path.name for a in archives}
    assert archive_names == {"寒霜之心.7z", "寒霜之心-汉化.zip", "DragonSword.rar"}


def test_scan_other_classification(sample_mod_tree: Path) -> None:
    """非图片非压缩包文件 asset_hint 应为 OTHER。"""
    scanner = FileScanner(now_provider=_fixed_now)
    result = scanner.scan(sample_mod_tree)

    others = [f for f in result.files if f.asset_hint == AssetHint.OTHER]
    other_names = {o.real_path.name for o in others}
    assert other_names == {"README.txt", "normal_file.txt", "no_extension"}


def test_scan_file_size(sample_mod_tree: Path) -> None:
    """文件 size_bytes 应来自 stat。"""
    scanner = FileScanner(now_provider=_fixed_now)
    result = scanner.scan(sample_mod_tree)

    by_name = {f.real_path.name: f for f in result.files}
    assert by_name["寒霜之心.7z"].size_bytes == 100
    assert by_name["寒霜之心-汉化.zip"].size_bytes == 50
    assert by_name["preview.webp"].size_bytes == 200


def test_scan_folder_size_zero(sample_mod_tree: Path) -> None:
    """文件夹 size_bytes 应为 0。"""
    scanner = FileScanner(now_provider=_fixed_now)
    result = scanner.scan(sample_mod_tree)

    for folder in result.folders:
        assert folder.size_bytes == 0
        assert folder.extension == ""


def test_scan_modified_at_iso_format(sample_mod_tree: Path) -> None:
    """modified_at 应为 ISO 8601 UTC 字符串。"""
    scanner = FileScanner(now_provider=_fixed_now)
    result = scanner.scan(sample_mod_tree)

    for entry in result.folders + result.files:
        # 应能被 ISO 8601 解析
        parsed = datetime.strptime(entry.modified_at, "%Y-%m-%dT%H:%M:%SZ")
        assert parsed.tzinfo is None  # strptime 不带 tz，但格式正确

    # 根目录的 modified_at 应接近当前时间（目录刚创建）
    root_entry = result.folders[0]
    root_mtime = sample_mod_tree.stat().st_mtime
    expected = datetime.fromtimestamp(root_mtime, tz=UTC)
    actual = datetime.strptime(root_entry.modified_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    # 允许 2 秒误差（strftime 截断到秒）
    assert abs((expected - actual).total_seconds()) < 2


def test_scan_extension_lowercase(sample_mod_tree: Path) -> None:
    """文件扩展名应为小写。"""
    scanner = FileScanner(now_provider=_fixed_now)
    result = scanner.scan(sample_mod_tree)

    by_name = {f.real_path.name: f for f in result.files}
    assert by_name["寒霜之心.7z"].extension == ".7z"
    assert by_name["preview.webp"].extension == ".webp"
    assert by_name["no_extension"].extension == ""


# ---------- 异常处理 ----------


def test_scan_nonexistent_root(tmp_path: Path) -> None:
    """根目录不存在：返回仅含错误的 ScanResult。"""
    nonexistent = tmp_path / "does_not_exist"
    scanner = FileScanner(now_provider=_fixed_now)
    result = scanner.scan(nonexistent)

    assert len(result.folders) == 0
    assert len(result.files) == 0
    assert len(result.errors) == 1
    assert "不存在" in result.errors[0].reason
    assert result.errors[0].exception_type == "FileNotFoundError"


def test_scan_root_is_file_not_directory(tmp_path: Path) -> None:
    """根路径为文件而非目录：返回仅含错误。"""
    file_path = tmp_path / "a_file.txt"
    file_path.write_bytes(b"data")

    scanner = FileScanner(now_provider=_fixed_now)
    result = scanner.scan(file_path)

    assert len(result.folders) == 0
    assert len(result.files) == 0
    assert len(result.errors) == 1
    assert "不是目录" in result.errors[0].reason
    assert result.errors[0].exception_type == "NotADirectoryError"


@pytest.mark.skipif(
    os.name == "nt", reason="Windows 上 chmod 000 不一定能阻止 stat（取决于所有权）"
)
def test_scan_permission_denied_directory(tmp_path: Path) -> None:
    """子目录无读取权限：记入 errors，其他目录仍扫描。"""
    root = tmp_path / "root"
    root.mkdir()
    accessible = root / "accessible"
    accessible.mkdir()
    (accessible / "ok.txt").write_bytes(b"ok")

    denied = root / "denied"
    denied.mkdir()
    (denied / "secret.txt").write_bytes(b"secret")
    denied.chmod(stat.S_IRUSR)  # 仅可读，不可进入

    try:
        scanner = FileScanner(now_provider=_fixed_now)
        result = scanner.scan(root)

        # accessible 下的文件应被扫描到
        file_names = {f.real_path.name for f in result.files}
        assert "ok.txt" in file_names
        # denied 应在 errors 中（具体是否包含 secret.txt 取决于 iterdir 是否能列出）
        assert len(result.errors) >= 1
        denied_errors = [e for e in result.errors if denied in e.path.parents or e.path == denied]
        assert len(denied_errors) >= 1
    finally:
        # 恢复权限以便清理
        denied.chmod(stat.S_IRWXU)


def test_scan_symlink_not_followed(tmp_path: Path) -> None:
    """符号链接不跟随，按文件处理。"""
    if os.name == "nt":
        pytest.skip("Windows 上创建符号链接需要管理员权限或开发者模式")

    root = tmp_path / "root"
    root.mkdir()
    target = tmp_path / "target_dir"
    target.mkdir()
    (target / "inside.txt").write_bytes(b"inside")

    link = root / "link_to_target"
    os.symlink(target, link, target_is_directory=True)

    scanner = FileScanner(now_provider=_fixed_now)
    result = scanner.scan(root)

    # 符号链接应出现在 files 中，而非 folders
    file_names = {f.real_path.name for f in result.files}
    assert "link_to_target" in file_names

    # inside.txt 不应被扫描到（未跟随符号链接）
    assert "inside.txt" not in file_names


def test_scan_many_independent_roots(tmp_path: Path) -> None:
    """scan_many 扫描多个独立根。"""
    root1 = tmp_path / "root1"
    root1.mkdir()
    (root1 / "a.txt").write_bytes(b"a")
    root2 = tmp_path / "root2"
    root2.mkdir()
    (root2 / "b.txt").write_bytes(b"b")

    scanner = FileScanner(now_provider=_fixed_now)
    results = scanner.scan_many([root1, root2])

    assert len(results) == 2
    assert results[0].root_path == root1
    assert results[1].root_path == root2
    assert {f.real_path.name for f in results[0].files} == {"a.txt"}
    assert {f.real_path.name for f in results[1].files} == {"b.txt"}


# ---------- persist_scan_result ----------


def test_persist_writes_folders_and_files(sample_mod_tree: Path, db_connection) -> None:
    """persist_scan_result 应写入 FolderNode 与 FileAsset。"""
    folder_repo = FolderNodeRepository(db_connection)
    file_repo = FileAssetRepository(db_connection)
    scanner = FileScanner(now_provider=_fixed_now)

    result = scanner.scan(sample_mod_tree)
    outcome = persist_scan_result(
        result,
        folder_repo,
        file_repo,
        now_provider=_fixed_now,
        uuid_provider=_sequential_uuid,
    )

    # 4 folders, 7 files
    assert len(outcome.inserted_folders) == 4
    assert len(outcome.inserted_files) == 7
    assert len(outcome.skipped_folders) == 0
    assert len(outcome.skipped_files) == 0

    # 通过 Repository 读取验证
    roots = folder_repo.list_managed_roots()
    assert len(roots) == 1
    assert roots[0].is_managed_root is True
    assert roots[0].real_path == str(sample_mod_tree)

    all_files = file_repo.list_unassociated()
    assert len(all_files) == 7


def test_persist_root_is_managed_root(sample_mod_tree: Path, db_connection) -> None:
    """只有根目录 is_managed_root=True。"""
    folder_repo = FolderNodeRepository(db_connection)
    file_repo = FileAssetRepository(db_connection)
    scanner = FileScanner(now_provider=_fixed_now)

    result = scanner.scan(sample_mod_tree)
    persist_scan_result(
        result,
        folder_repo,
        file_repo,
        now_provider=_fixed_now,
        uuid_provider=_sequential_uuid,
    )

    roots = folder_repo.list_managed_roots()
    assert len(roots) == 1

    # 子目录的 is_managed_root 应为 False
    all_folders = folder_repo.list_by_parent(None)
    assert len(all_folders) == 1
    children = folder_repo.list_by_parent(roots[0].id)
    for child in children:
        assert child.is_managed_root is False


def test_persist_parent_child_relationship(sample_mod_tree: Path, db_connection) -> None:
    """子目录的 parent_id 应指向根目录。"""
    folder_repo = FolderNodeRepository(db_connection)
    file_repo = FileAssetRepository(db_connection)
    scanner = FileScanner(now_provider=_fixed_now)

    result = scanner.scan(sample_mod_tree)
    persist_scan_result(
        result,
        folder_repo,
        file_repo,
        now_provider=_fixed_now,
        uuid_provider=_sequential_uuid,
    )

    roots = folder_repo.list_managed_roots()
    assert len(roots) == 1
    root_node = roots[0]

    children = folder_repo.list_by_parent(root_node.id)
    child_names = {c.real_path.split(os.sep)[-1] for c in children}
    # 注意：Windows 上 os.sep 是反斜杠，real_path 可能含反斜杠
    # 改用 Path 比较
    child_names = {Path(c.real_path).name for c in children}
    assert child_names == {"护甲", "Weapons", "空目录"}


def test_persist_file_fields_complete(sample_mod_tree: Path, db_connection) -> None:
    """FileAsset 字段应完整持久化。"""
    folder_repo = FolderNodeRepository(db_connection)
    file_repo = FileAssetRepository(db_connection)
    scanner = FileScanner(now_provider=_fixed_now)

    result = scanner.scan(sample_mod_tree)
    outcome = persist_scan_result(
        result,
        folder_repo,
        file_repo,
        now_provider=_fixed_now,
        uuid_provider=_sequential_uuid,
    )

    # 找到 preview.webp
    preview = next(f for f in outcome.inserted_files if f.filename == "preview.webp")
    assert preview.asset_kind == AssetKind.FILE
    assert preview.role == FileRole.UNKNOWN  # 默认角色
    assert preview.size_bytes == 200
    assert preview.extension == ".webp"
    assert preview.mod_item_id is None
    assert preview.imported_at == "2026-07-07T00:00:00Z"
    assert preview.modified_at  # 非空

    # path_key 应为小写规范化
    assert "preview.webp" in preview.path_key


def test_persist_chinese_path_roundtrip(sample_mod_tree: Path, db_connection) -> None:
    """中文路径应正确持久化与读取。"""
    folder_repo = FolderNodeRepository(db_connection)
    file_repo = FileAssetRepository(db_connection)
    scanner = FileScanner(now_provider=_fixed_now)

    result = scanner.scan(sample_mod_tree)
    outcome = persist_scan_result(
        result,
        folder_repo,
        file_repo,
        now_provider=_fixed_now,
        uuid_provider=_sequential_uuid,
    )

    # 找到寒霜之心.7z
    frost = next(f for f in outcome.inserted_files if f.filename == "寒霜之心.7z")
    assert "护甲" in frost.real_path
    assert "寒霜之心.7z" in frost.real_path
    assert "护甲" in frost.path_key
    assert "寒霜之心.7z" in frost.path_key


def test_persist_overlapping_roots_dedup(sample_mod_tree: Path, db_connection) -> None:
    """A3：重叠根目录去重。

    根 A = sample_mod_tree
    根 B = sample_mod_tree / 护甲
    第二次持久化时，重叠的路径应被跳过。
    """
    folder_repo = FolderNodeRepository(db_connection)
    file_repo = FileAssetRepository(db_connection)
    scanner = FileScanner(now_provider=_fixed_now)

    root_a = sample_mod_tree
    root_b = sample_mod_tree / "护甲"

    results = scanner.scan_many([root_a, root_b])

    # 持久化第一次（根 A）
    outcome_a = persist_scan_result(
        results[0],
        folder_repo,
        file_repo,
        now_provider=_fixed_now,
        uuid_provider=_sequential_uuid,
    )
    assert len(outcome_a.inserted_folders) == 4
    assert len(outcome_a.inserted_files) == 7

    # 持久化第二次（根 B，与根 A 重叠）
    outcome_b = persist_scan_result(
        results[1],
        folder_repo,
        file_repo,
        now_provider=_fixed_now,
        uuid_provider=_sequential_uuid,
    )
    # 根 B 自身（护甲）已被根 A 包含，path_key 冲突 → 跳过
    assert len(outcome_b.inserted_folders) == 0
    assert len(outcome_b.skipped_folders) == 1
    # 护甲下的 3 个文件也已被根 A 插入 → 跳过
    assert len(outcome_b.inserted_files) == 0
    assert len(outcome_b.skipped_files) == 3


def test_persist_idempotent(sample_mod_tree: Path, db_connection) -> None:
    """同一扫描结果重复持久化：第二次全部跳过。"""
    folder_repo = FolderNodeRepository(db_connection)
    file_repo = FileAssetRepository(db_connection)
    scanner = FileScanner(now_provider=_fixed_now)

    result = scanner.scan(sample_mod_tree)

    outcome1 = persist_scan_result(
        result,
        folder_repo,
        file_repo,
        now_provider=_fixed_now,
        uuid_provider=_sequential_uuid,
    )
    assert len(outcome1.inserted_folders) == 4
    assert len(outcome1.inserted_files) == 7

    outcome2 = persist_scan_result(
        result,
        folder_repo,
        file_repo,
        now_provider=_fixed_now,
        uuid_provider=_sequential_uuid,
    )
    assert len(outcome2.inserted_folders) == 0
    assert len(outcome2.inserted_files) == 0
    assert len(outcome2.skipped_folders) == 4
    assert len(outcome2.skipped_files) == 7


def test_persist_multiple_managed_roots(tmp_path: Path, db_connection) -> None:
    """多个独立根目录都标记为 is_managed_root。"""
    folder_repo = FolderNodeRepository(db_connection)
    file_repo = FileAssetRepository(db_connection)
    scanner = FileScanner(now_provider=_fixed_now)

    root1 = tmp_path / "mods_a"
    root1.mkdir()
    (root1 / "a.7z").write_bytes(b"a")
    root2 = tmp_path / "mods_b"
    root2.mkdir()
    (root2 / "b.zip").write_bytes(b"b")

    results = scanner.scan_many([root1, root2])

    for result in results:
        persist_scan_result(
            result,
            folder_repo,
            file_repo,
            now_provider=_fixed_now,
            uuid_provider=_sequential_uuid,
        )

    roots = folder_repo.list_managed_roots()
    assert len(roots) == 2
    root_paths = {Path(r.real_path).name for r in roots}
    assert root_paths == {"mods_a", "mods_b"}


# ---------- 只读保证 ----------


def test_scan_does_not_modify_files(sample_mod_tree: Path) -> None:
    """扫描前后，目录内文件的 mtime 与内容应一致。"""
    # 记录扫描前的状态
    before = {}
    for path in sample_mod_tree.rglob("*"):
        if path.is_file():
            stat = path.stat(follow_symlinks=False)
            before[path] = (stat.st_mtime, stat.st_size, path.read_bytes())

    # 执行扫描
    scanner = FileScanner(now_provider=_fixed_now)
    scanner.scan(sample_mod_tree)

    # 验证扫描后状态一致
    for path, (mtime, size, content) in before.items():
        stat = path.stat(follow_symlinks=False)
        assert stat.st_mtime == mtime, f"mtime 被修改：{path}"
        assert stat.st_size == size, f"size 被修改：{path}"
        assert path.read_bytes() == content, f"内容被修改：{path}"


def test_scan_does_not_create_or_delete_files(sample_mod_tree: Path, tmp_path: Path) -> None:
    """扫描不应在受扫描目录或其外部创建/删除任何文件。"""
    # 记录扫描前目录树
    before_entries = {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")}

    scanner = FileScanner(now_provider=_fixed_now)
    scanner.scan(sample_mod_tree)

    after_entries = {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")}
    assert before_entries == after_entries, "扫描创建了或删除了文件"
