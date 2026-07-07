"""只读文件扫描器。

本模块仅使用只读文件系统 API（Path.iterdir / is_dir / stat / suffix），
不移动、不重命名、不删除、不修改、不打开（读取内容）任何用户文件。
不解析压缩包内部内容。

依据 docs/roadmap.md Task 3。
依据 docs/architecture.md §3：File Scanner 属于 infrastructure 层。
依据 A3 决策：递归扫描，所有子目录生成 FolderNode；重叠目录在持久化时去重。

扫描与持久化解耦：
- FileScanner.scan / scan_many 仅产出 ScanResult，不写数据库。
- persist_scan_result 将 ScanResult 通过 Repository 写入 DB，处理 path_key 去重。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from domain.models import AssetKind, FileAsset, FileRole, FolderNode
from infrastructure.file_classify import AssetHint, classify_by_extension, get_extension
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.errors import ConstraintViolationError
from infrastructure.repositories.file_asset import FileAssetRepository
from infrastructure.repositories.folder_node import FolderNodeRepository

logger = logging.getLogger(__name__)


def _default_now_utc() -> str:
    """默认 now_provider：返回当前 UTC 时间的 ISO 8601 字符串。"""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_uuid_provider() -> str:
    return str(uuid.uuid4())


def _mtime_to_iso(epoch_seconds: float) -> str:
    """将 epoch 秒转为 ISO 8601 UTC 字符串。"""
    return datetime.fromtimestamp(epoch_seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ScannedFileEntry:
    """扫描产出的单个文件/文件夹条目（未持久化）。

    与 FileAsset dataclass 不同：此处保留 Path 对象与 AssetHint，
    持久化时由 persist_scan_result 转换为 FileAsset/FolderNode。
    """

    real_path: Path
    is_dir: bool
    size_bytes: int
    modified_at: str
    extension: str
    asset_hint: AssetHint


@dataclass
class ScanError:
    """扫描中遇到的非致命错误。"""

    path: Path
    reason: str  # 用户可读中文消息
    exception_type: str  # 技术异常类型名


@dataclass
class ScanResult:
    """一次扫描的完整结果。"""

    root_path: Path
    folders: list[ScannedFileEntry] = field(default_factory=list)
    files: list[ScannedFileEntry] = field(default_factory=list)
    errors: list[ScanError] = field(default_factory=list)


@dataclass
class PersistOutcome:
    """persist_scan_result 的结果。"""

    inserted_folders: list[FolderNode] = field(default_factory=list)
    inserted_files: list[FileAsset] = field(default_factory=list)
    skipped_folders: list[tuple[Path, str]] = field(default_factory=list)
    skipped_files: list[tuple[Path, str]] = field(default_factory=list)


class FileScanner:
    """只读文件扫描器。

    使用方式：
        scanner = FileScanner()
        result = scanner.scan(Path("D:/Mods"))
        # 持久化：
        outcome = persist_scan_result(result, folder_repo, file_repo)
    """

    def __init__(self, now_provider: Callable[[], str] | None = None) -> None:
        """now_provider 返回 ISO 8601 UTC 字符串，便于测试注入。"""
        self._now_provider = now_provider or _default_now_utc

    def scan(self, root: Path) -> ScanResult:
        """扫描单个根目录，返回结果。不写入数据库。

        若根目录不存在或非目录，返回仅含错误的 ScanResult。
        """
        result = ScanResult(root_path=root)

        # 验证根目录
        try:
            if not root.exists():
                result.errors.append(
                    ScanError(
                        path=root,
                        reason=f"根目录不存在：{root}",
                        exception_type="FileNotFoundError",
                    )
                )
                return result
            if not root.is_dir():
                result.errors.append(
                    ScanError(
                        path=root,
                        reason=f"根路径不是目录：{root}",
                        exception_type="NotADirectoryError",
                    )
                )
                return result
        except OSError as e:
            result.errors.append(
                ScanError(
                    path=root,
                    reason=f"无法访问根目录：{e}",
                    exception_type=type(e).__name__,
                )
            )
            return result

        # 将根目录本身加入 folders
        root_entry = self._make_entry(root, is_dir=True)
        if root_entry is not None:
            result.folders.append(root_entry)
        else:
            # 根目录 stat 失败，无法继续
            return result

        # 递归扫描
        self._scan_recursive(root, result)
        return result

    def scan_many(self, roots: list[Path]) -> list[ScanResult]:
        """扫描多个根目录。重叠目录由 persist_scan_result 按 path_key 去重。"""
        return [self.scan(root) for root in roots]

    def _scan_recursive(self, current_dir: Path, result: ScanResult) -> None:
        """递归扫描目录。使用 Path.iterdir 而非 os.walk，便于精细控制异常。"""
        try:
            entries = list(current_dir.iterdir())
        except PermissionError as e:
            result.errors.append(
                ScanError(
                    path=current_dir,
                    reason=f"无权限访问目录：{e}",
                    exception_type="PermissionError",
                )
            )
            return
        except OSError as e:
            result.errors.append(
                ScanError(
                    path=current_dir,
                    reason=f"无法读取目录：{e}",
                    exception_type=type(e).__name__,
                )
            )
            return

        for entry in entries:
            try:
                is_symlink = entry.is_symlink()
            except OSError as e:
                result.errors.append(
                    ScanError(
                        path=entry,
                        reason=f"无法判断符号链接：{e}",
                        exception_type=type(e).__name__,
                    )
                )
                continue

            # 符号链接与 junction：不跟随，按文件处理（asset_hint=OTHER）
            # 避免循环、避免越过受管理根目录
            if is_symlink:
                symlink_entry = self._make_entry(entry, is_dir=False)
                if symlink_entry is not None:
                    result.files.append(symlink_entry)
                continue

            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError as e:
                result.errors.append(
                    ScanError(
                        path=entry,
                        reason=f"无法判断目录类型：{e}",
                        exception_type=type(e).__name__,
                    )
                )
                continue

            if is_dir:
                dir_entry = self._make_entry(entry, is_dir=True)
                if dir_entry is not None:
                    result.folders.append(dir_entry)
                    self._scan_recursive(entry, result)
            else:
                file_entry = self._make_entry(entry, is_dir=False)
                if file_entry is not None:
                    result.files.append(file_entry)

    def _make_entry(self, path: Path, is_dir: bool) -> ScannedFileEntry | None:
        """构造 ScannedFileEntry。stat 失败时返回 None 并记录错误。

        注意：调用方需自行记录错误；此处仅返回 None。
        本方法的错误记录由调用方处理（避免错误重复）。
        实际上为简化，本方法不记录错误，由调用方在调用前/后处理。
        """
        try:
            stat = path.stat(follow_symlinks=False)
        except OSError:
            # stat 失败，返回 None；调用方需记录错误
            return None

        if is_dir:
            return ScannedFileEntry(
                real_path=path,
                is_dir=True,
                size_bytes=0,
                modified_at=_mtime_to_iso(stat.st_mtime),
                extension="",
                asset_hint=AssetHint.OTHER,
            )
        filename = path.name
        return ScannedFileEntry(
            real_path=path,
            is_dir=False,
            size_bytes=stat.st_size,
            modified_at=_mtime_to_iso(stat.st_mtime),
            extension=get_extension(filename),
            asset_hint=classify_by_extension(filename),
        )


def persist_scan_result(
    scan_result: ScanResult,
    folder_repo: FolderNodeRepository,
    file_repo: FileAssetRepository,
    now_provider: Callable[[], str] | None = None,
    uuid_provider: Callable[[], str] | None = None,
) -> PersistOutcome:
    """将扫描结果写入 DB。

    - FolderNode：按路径深度排序，确保父先于子插入；path_key 冲突时跳过。
    - FileAsset：path_key 冲突时跳过。
    - 根目录：is_managed_root=True；其余 False。
    - parent_id：通过 path_key 查找已插入的父节点。
    - FileAsset.role 默认 UNKNOWN（角色由 Task 4 用户手动指定）。
    """
    now = (now_provider or _default_now_utc)()
    new_uuid = uuid_provider or _default_uuid_provider
    outcome = PersistOutcome()

    # path_key -> FolderNode 的映射，用于查找 parent_id
    path_key_to_folder: dict[str, FolderNode] = {}

    # 预加载已存在的 FolderNode（避免重复插入冲突）
    for existing in folder_repo.list_managed_roots():
        path_key_to_folder[existing.path_key] = existing
    # 也加载所有 FolderNode 以支持子目录的 parent_id 查找
    # 注意：list_by_parent(None) 仅返回根；这里需要全量加载
    # 改为直接查表（通过 list_managed_roots 已加载根，子节点按需查）
    # 简化：维护 path_key -> id 的内存映射，逐步填充

    # 按 real_path 字符串长度排序，确保父目录先于子目录
    sorted_folders = sorted(scan_result.folders, key=lambda f: str(f.real_path))

    # 临时维护 path_key -> folder_id，包含预加载的与本次插入的
    # 预加载所有现有 FolderNode 的 path_key -> id
    _preload_existing_folders(folder_repo, path_key_to_folder)

    for entry in sorted_folders:
        path_key = make_path_key(entry.real_path)
        if path_key in path_key_to_folder:
            outcome.skipped_folders.append((entry.real_path, "路径已存在或被其他根目录包含"))
            continue

        # 查找 parent_id
        parent_id = _find_parent_id(entry.real_path, path_key_to_folder)

        is_managed_root = entry.real_path == scan_result.root_path
        node = FolderNode(
            id=new_uuid(),
            real_path=str(entry.real_path),
            path_key=path_key,
            parent_id=parent_id,
            display_name=None,
            is_managed_root=is_managed_root,
            created_at=now,
            updated_at=now,
        )

        try:
            inserted = folder_repo.create(node)
            path_key_to_folder[path_key] = inserted
            outcome.inserted_folders.append(inserted)
        except ConstraintViolationError as e:
            outcome.skipped_folders.append((entry.real_path, str(e)))

    # 持久化 FileAsset
    for entry in scan_result.files:
        path_key = make_path_key(entry.real_path)
        asset = FileAsset(
            id=new_uuid(),
            mod_item_id=None,
            real_path=str(entry.real_path),
            path_key=path_key,
            filename=entry.real_path.name,
            extension=entry.extension,
            asset_kind=AssetKind.FOLDER if entry.is_dir else AssetKind.FILE,
            role=FileRole.UNKNOWN,
            size_bytes=entry.size_bytes,
            modified_at=entry.modified_at,
            imported_at=now,
        )

        try:
            inserted = file_repo.create(asset)
            outcome.inserted_files.append(inserted)
        except ConstraintViolationError as e:
            outcome.skipped_files.append((entry.real_path, str(e)))

    return outcome


def _preload_existing_folders(
    folder_repo: FolderNodeRepository,
    path_key_to_folder: dict[str, FolderNode],
) -> None:
    """预加载所有现有 FolderNode 到映射，避免重复插入。

    由于 FolderNodeRepository 未提供 list_all，这里递归从根开始加载。
    """
    roots = folder_repo.list_by_parent(None)
    for root in roots:
        path_key_to_folder[root.path_key] = root
        _preload_children(folder_repo, root, path_key_to_folder)


def _preload_children(
    folder_repo: FolderNodeRepository,
    parent: FolderNode,
    path_key_to_folder: dict[str, FolderNode],
) -> None:
    """递归预加载子目录。"""
    children = folder_repo.list_by_parent(parent.id)
    for child in children:
        path_key_to_folder[child.path_key] = child
        _preload_children(folder_repo, child, path_key_to_folder)


def _find_parent_id(
    path: Path,
    path_key_to_folder: dict[str, FolderNode],
) -> str | None:
    """查找路径的父目录 FolderNode.id。

    依据 A2：path_key 使用 normcase+normpath。
    """
    parent_path = path.parent
    parent_key = make_path_key(parent_path)
    parent_node = path_key_to_folder.get(parent_key)
    return parent_node.id if parent_node else None
