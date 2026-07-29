"""内容单元服务：查询与元数据写入。

从 content_unit 表查询内容单元，并提供元数据写入方法
（create_content_unit / mark_as_content_unit / unmark_content_unit）。

写方法仅修改数据库记录，不触发任何文件操作（不创建、不移动、不删除、
不重命名真实文件）。文件操作由 FileOperationService 负责。

list_direct_children：只返回 path 直接属于该目录的内容单元
（即 Path(unit.path).parent == dir_path），不含深层子目录的内容单元。
通过在 service 层过滤 list_by_path_prefix_normalized 结果实现，保持 Repository 简单。

list_directory_entries：从文件系统读取目录下所有条目（roadmap Task 4 2026-07-13 设计修正），
并按 path 关联 content_unit 表中的内容单元。内容单元不是可见性门槛——
所有文件系统条目均返回。仅使用 Path.iterdir / is_dir / is_file / stat（只读）。

路径比较统一使用 make_path_key()（normcase + normpath）归一化，
不依赖 Path.resolve()（后者会访问文件系统解析符号链接，语义不一致）。

Stage 4 Task 2 新增：
- update_metadata：编辑 title / source_url / notes / cover_path。
- list_cover_candidates：列出内容单元目录内所有支持的图片格式（用于 CoverPickerDialog）。
- 委托 TagService 完成标签关联与批量打标签。
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from application.errors import (
    ContentUnitCascadeError,
    ContentUnitNotFoundError,
    CoverImageNotFoundError,
    InvalidContentUnitPathError,
    InvalidMetadataError,
)
from domain.models import ContentUnit, FileEntry
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.errors import (
    ConstraintViolationError,  # noqa: F401
    RepositoryError,
)
from infrastructure.unit_of_work import UnitOfWork

if TYPE_CHECKING:
    from application.thumbnail_service import ThumbnailService

logger = logging.getLogger(__name__)

# 支持的封面图片扩展名（spec §9）
_COVER_IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".ico"}
)

# title 最大长度（避免过长破坏 UI 布局）
_TITLE_MAX_LENGTH = 200

# source_url 最大长度
_URL_MAX_LENGTH = 2000


def _default_now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_uuid_provider() -> str:
    return str(uuid.uuid4())


class ContentService:
    """内容单元服务：查询与元数据写入。"""

    def __init__(
        self,
        content_unit_repo: ContentUnitRepository,
        now_provider: Callable[[], str] | None = None,
        uuid_provider: Callable[[], str] | None = None,
        thumbnail_service: ThumbnailService | None = None,
        uow: UnitOfWork | None = None,
    ) -> None:
        """初始化 ContentService。

        Args:
            content_unit_repo: ContentUnit 仓储。
            now_provider: 时间戳提供者（用于测试注入）。
            uuid_provider: UUID 提供者（用于测试注入）。
            thumbnail_service: 缩略图服务（可选）。Stage 4.5 M4 修复：
                注入后 update_metadata 修改 cover_path 时主动 invalidate
                缩略图缓存，避免依赖 UI 层兜底。None 时不主动失效
                （向后兼容旧调用方）。
            uow: 事务边界管理器（可选）。Stage 4.5 H6 修复：
                注入后 mark_as_content_unit 的多步写操作（删除子项 + 创建/恢复
                父标记）在事务内执行，保证原子性。None 时保持原行为（调用方
                控制事务边界）。单步写方法（create_content_unit /
                unmark_content_unit / update_metadata）不使用 UoW，保持原行为。
        """
        self._repo = content_unit_repo
        self._now = now_provider or _default_now_utc
        self._new_uuid = uuid_provider or _default_uuid_provider
        self._thumbnail_service = thumbnail_service
        self._uow = uow

    def list_by_directory(self, dir_path: str) -> list[ContentUnit]:
        """返回 dir_path 及其所有子目录下的内容单元。

        委托 ContentUnitRepository.list_by_path_prefix_normalized（TD-H7 修复：
        原 list_by_path_prefix 已删除，统一使用 normalized 接口）。
        """
        return self._repo.list_by_path_prefix_normalized(dir_path)

    def list_direct_children(self, dir_path: str) -> list[ContentUnit]:
        """只返回 path 直接属于 dir_path 的内容单元。

        判断规则：Path(unit.path).parent 与 dir_path 指向同一目录。
        使用 make_path_key() 归一化后比较，避免大小写/分隔符差异。

        特别地，当 unit.path 本身就是 dir_path（内容单元路径等于目录路径）时，
        也视为直接子项返回。
        """
        all_units = self._repo.list_by_path_prefix_normalized(dir_path)
        if not all_units:
            return []

        target_key = make_path_key(dir_path)
        result: list[ContentUnit] = []
        for unit in all_units:
            unit_path_key = make_path_key(unit.path)
            parent_key = make_path_key(str(Path(unit.path).parent))
            # 内容单元路径等于目录本身 或 其父目录等于目录
            if unit_path_key == target_key or parent_key == target_key:
                result.append(unit)
        return result

    def get_by_id(self, unit_id: str) -> ContentUnit | None:
        """按 ID 查询内容单元；不存在返回 None。"""
        return self._repo.get_by_id(unit_id)

    def get_by_path(self, path: str) -> ContentUnit | None:
        """按路径精确查询内容单元；不存在返回 None。"""
        return self._repo.get_by_path(path)

    def create_content_unit(
        self,
        path: Path,
        title: str | None = None,
        content_type: str = "mod",
        status: str = "unorganized",
    ) -> ContentUnit:
        """创建新 ContentUnit。

        Args:
            path: 内容单元对应的真实路径（文件或文件夹）。
            title: 标题，默认 None（显示时回退到路径名）。
            content_type: 类型，默认 "mod"。
            status: 状态，默认 "unorganized"。

        Returns:
            新创建的 ContentUnit。

        Raises:
            ConstraintViolationError: path 已存在 ContentUnit。
        """
        now = self._now()
        unit = ContentUnit(
            id=self._new_uuid(),
            path=str(path),
            title=title,
            content_type=content_type,
            status=status,
            created_at=now,
            updated_at=now,
        )
        return self._repo.create(unit)

    def mark_as_content_unit(self, path: Path) -> ContentUnit:
        """标记路径为内容单元。

        spec §5.4 关键规则：手动标记文件夹为内容单元时，其内部的所有内容单元
        标记自动取消（避免父子同时标记）。

        行为：
        - 若 path 已是 ContentUnit 且 status != "unmarked"：返回现有 unit（不重复创建）。
        - 若 path 已是 ContentUnit 且 status == "unmarked"：恢复为 "unorganized"（重新标记）。
        - 若 path 是文件夹：先 list_by_path_prefix_normalized 查询子项 ContentUnit
          （不含自身），逐个 delete 非 "unmarked" 子项（ContentUnitRepository.delete
          已级联清理 content_unit_tag）；"unmarked" 子项保留（用户显式取消标记的偏好
          不应被覆盖）；然后创建或恢复 ContentUnit。
        - 若 path 是文件：直接创建（不查子项）。

        Stage 4.5 H6 修复：若注入了 uow，多步写操作（删除子项 + 创建/恢复父标记）
        在事务内执行，保证原子性。任一子项删除失败抛 ContentUnitCascadeError 时，
        整个事务回滚（已删除的子项不会丢失——事务未提交）。文件系统校验保留在
        事务外（只读操作不需要事务保护）。

        Args:
            path: 待标记的文件或文件夹路径。

        Returns:
            新创建或已存在的 ContentUnit。

        Raises:
            InvalidContentUnitPathError: 路径不存在或不可访问。
            ContentUnitCascadeError: 子项 ContentUnit 删除失败（spec §5.4
                不变量：父子不可同时标记。任一子项失败即中止父标记创建）。
        """
        # 路径合法性校验（只读文件系统检查，不需要事务）
        try:
            if not path.exists():
                raise InvalidContentUnitPathError(f"路径不存在：{path}")
        except OSError as e:
            raise InvalidContentUnitPathError(f"无法访问路径：{e}") from e

        try:
            is_dir = path.is_dir()
        except OSError as e:
            raise InvalidContentUnitPathError(f"无法访问路径：{e}") from e

        # DB 操作在事务内执行（Stage 4.5 H6：保证多步写原子性）
        if self._uow is not None:
            with self._uow.transaction():
                return self._mark_as_content_unit_core(path, is_dir)
        return self._mark_as_content_unit_core(path, is_dir)

    def _mark_as_content_unit_core(self, path: Path, is_dir: bool) -> ContentUnit:
        """mark_as_content_unit 的核心 DB 逻辑。

        包含：查询现有记录 → 取消子项标记（文件夹） → 创建/恢复父标记。
        由 mark_as_content_unit 在事务内调用（当 uow 注入时），
        或直接调用（当 uow 为 None 时，调用方控制事务边界）。
        """
        # 查询现有记录
        existing = self._repo.get_by_path(str(path))

        # 已标记且非 unmarked：返回现有（不重复创建）
        if existing is not None and existing.status != "unmarked":
            return existing

        # 文件夹：取消子项标记（保留 "unmarked" 子项）
        if is_dir:
            children = self._repo.list_by_path_prefix_normalized(str(path))
            # 排除 path 自身（list_by_path_prefix_normalized 含 prefix 自身）
            failures: list[tuple[str, str]] = []
            for child in children:
                if make_path_key(child.path) != make_path_key(str(path)):
                    if child.status == "unmarked":
                        continue  # 保留用户显式取消标记的偏好
                    try:
                        self._repo.delete(child.id)
                    except (RepositoryError, sqlite3.Error) as e:  # noqa: BLE001
                        # Stage 4.5 H2 修复：不再静默吞异常。
                        # spec §5.4 不变量：父子不可同时标记。
                        # 任一子项删除失败即中止父标记创建。
                        logger.exception("取消子项标记失败：unit_id=%s", child.id)
                        failures.append((child.id, str(e)))
            if failures:
                raise ContentUnitCascadeError(
                    f"取消子项标记失败（{len(failures)} 项），已中止父标记创建",
                    failures=failures,
                )

        # 创建新记录或恢复 unmarked 记录
        if existing is not None:
            # existing.status == "unmarked" → 恢复为 unorganized
            updated = replace(existing, status="unorganized", updated_at=self._now())
            result = self._repo.update(updated)
        else:
            # 默认 title=path.name（文件名或文件夹名），避免元数据面板显示"（无标题）"
            result = self.create_content_unit(path, title=path.name)

        # Stage 5 Task 1：标记文件夹为内容单元时自动录入封面
        # 仅文件夹内容单元 + cover_path 为空时尝试，无图片不报错
        if is_dir:
            return self._auto_set_cover_for_folder_unit(result)
        return result

    def _auto_set_cover_for_folder_unit(self, unit: ContentUnit) -> ContentUnit:
        """文件夹内容单元自动录入封面（Stage 5 Task 1）。

        触发场景：mark_as_content_unit 标记文件夹后。
        规则：
        - 仅当 unit.path 是目录且 cover_path 为空时尝试
        - 取 list_cover_candidates 第一张图片（已按文件名升序排序）
        - 写入 cover_path（相对路径），触发缩略图后台生成
        - 无图片 / 路径不可访问 → 静默跳过，不报错，返回原 unit
        - 已有手动封面 → 不覆盖（cover_path 非空时不进入此分支），返回原 unit

        在 mark_as_content_unit 的事务内调用，写操作原子性由 UoW 保证。
        返回更新后的 unit（无更新时返回原 unit）。
        """
        if unit.cover_path:
            return unit  # 已有封面，不覆盖
        try:
            if not Path(unit.path).is_dir():
                return unit
        except OSError:
            return unit  # 路径不可访问，静默跳过

        candidates = self.list_cover_candidates(unit.path)
        if not candidates:
            return unit  # 无图片，静默跳过

        first = candidates[0]
        rel_path = first.name  # list_cover_candidates 扫描 unit.path 顶层，name 即相对路径
        try:
            updated = replace(unit, cover_path=rel_path, updated_at=self._now())
            result = self._repo.update(updated)
        except (RepositoryError, sqlite3.Error):  # noqa: BLE001
            logger.exception("自动录入封面失败：unit_id=%s", unit.id)
            return unit  # 失败不阻断 mark 流程，返回原 unit

        # 触发缩略图后台生成（与 update_metadata 行为一致）
        if self._thumbnail_service is not None:
            try:
                self._thumbnail_service.invalidate(unit.id)
            except Exception:  # noqa: BLE001
                logger.exception("invalidate 缩略图缓存失败：unit_id=%s", unit.id)
        return result

    def unmark_content_unit(self, unit_id: str) -> None:
        """取消内容单元标记。

        将 ContentUnit 的 status 设为 "unmarked"（而非删除记录），使扫描不再
        重复创建该路径的内容单元（roadmap：扫描候选的纠错能力）。**不删除真实文件**。

        UI 层将 "unmarked" 状态视为无内容单元（不显示标记、不响应双击）。
        若用户再次 mark_as_content_unit，status 恢复为 "unorganized"。

        Args:
            unit_id: 待取消的 ContentUnit ID。

        Raises:
            ContentUnitNotFoundError: unit_id 不存在。
        """
        unit = self._repo.get_by_id(unit_id)
        if unit is None:
            raise ContentUnitNotFoundError(f"内容单元不存在：{unit_id}")
        if unit.status == "unmarked":
            return  # 已取消标记，幂等
        updated = replace(unit, status="unmarked", updated_at=self._now())
        self._repo.update(updated)

    def list_directory_entries(self, dir_path: str) -> list[FileEntry]:
        """返回 dir_path 下所有文件和文件夹条目，并关联 content_unit。

        数据源为文件系统（Path.iterdir），仅读取元数据（is_dir / is_file / stat）。
        对每个条目按 path 查询 content_unit 表，命中则填充 content_unit 字段。

        排序规则：文件夹在前（is_dir=True 优先），同类型按 name 升序（不区分大小写）。

        若 dir_path 不存在、不是目录或读取失败，返回空列表（记日志）。
        """
        root = Path(dir_path)
        try:
            if not root.is_dir():
                return []
        except OSError as e:
            logger.warning("list_directory_entries: 路径检查失败 %s: %s", dir_path, e)
            return []

        entries: list[FileEntry] = []
        try:
            for child in root.iterdir():
                entry = self._build_entry(child)
                if entry is not None:
                    entries.append(entry)
        except OSError as e:
            logger.warning("list_directory_entries: 读取目录失败 %s: %s", dir_path, e)
            return []

        # 文件夹在前，名称不区分大小写升序
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower(), e.name))
        return entries

    def list_staging_entries(self, staging_path: str) -> list[FileEntry]:
        """递归返回暂存区 staging_path 下所有文件和文件夹条目，并关联 content_unit。

        阶段 3 Task 2：暂存区文件列表。

        与 list_directory_entries 区别：
        - 递归遍历所有子目录（Path.rglob("*")），不只单层；
        - 批量预查 content_unit（一次 list_by_path_prefix_normalized 取回所有
          相关单元，构建 path_key → ContentUnit 映射），避免 N 次 DB 查询。

        数据源为文件系统，仅读取元数据（is_dir / is_file / stat），跳过符号链接。
        单条目读取失败不中断整体遍历（记日志后跳过）。

        排序规则：文件夹在前（is_dir=True 优先），同类型按 name 升序（不区分大小写）。
        排序为初始默认顺序；UI 层可通过 FileListModel.set_sort_key 切换排序键。

        若 staging_path 不存在、不是目录或读取失败，返回空列表（记日志）。
        """
        root = Path(staging_path)
        try:
            if not root.is_dir():
                return []
        except OSError as e:
            logger.warning("list_staging_entries: 路径检查失败 %s: %s", staging_path, e)
            return []

        # 批量预查 content_unit：一次 SQL 拿回所有相关单元，构建 path_key 映射
        # "unmarked" 状态的单元不纳入映射（视为无内容单元）
        # 使用 list_by_path_prefix_normalized（统一归一化接口，原 list_by_path_prefix
        # 已在 TD-L20 清理中删除）
        unit_map: dict[str, ContentUnit] = {}
        try:
            units = self._repo.list_by_path_prefix_normalized(staging_path)
            for unit in units:
                if unit.status == "unmarked":
                    continue
                unit_map[make_path_key(unit.path)] = unit
        except (RepositoryError, sqlite3.Error):  # 数据库查询失败不阻塞文件系统遍历
            logger.exception("list_staging_entries: 预查 content_unit 失败：%s", staging_path)

        entries: list[FileEntry] = []
        try:
            for child in root.rglob("*"):
                entry = self._build_entry_with_map(child, unit_map)
                if entry is not None:
                    entries.append(entry)
        except OSError as e:
            logger.warning("list_staging_entries: 递归读取失败 %s: %s", staging_path, e)
            return []

        # spec §7.3：暂存区文件列表显示"零散文件"。
        # 若某个文件夹已被标记为内容单元（即 Mod 组文件夹），
        # 其内部的子文件/子文件夹视为"已收纳"，不再显示在列表中。
        # 这与 spec §5.4（标记文件夹时取消子项标记）的语义一致。
        cu_folder_keys: set[str] = set()
        for entry in entries:
            if entry.is_dir and entry.content_unit is not None:
                cu_folder_keys.add(make_path_key(entry.path))

        if cu_folder_keys:
            filtered: list[FileEntry] = []
            for entry in entries:
                if self._has_ancestor_in_set(entry.path, cu_folder_keys):
                    continue
                filtered.append(entry)
            entries = filtered

        # 文件夹在前，名称不区分大小写升序
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower(), e.name))
        return entries

    # --- 元数据编辑（Stage 4 Task 2） ---

    def update_metadata(
        self,
        unit_id: str,
        title: str | None = None,
        source_url: str | None = None,
        notes: str | None = None,
        cover_path: str | None = None,
    ) -> ContentUnit:
        """更新内容单元的元数据字段。

        仅修改显式传入的字段；None 参数表示「不改」。空字符串表示「清空」。
        每次更新自动更新 updated_at。

        Stage 4.5 M4 修复：若注入了 thumbnail_service 且 cover_path 发生变化
        （设置、替换或清空），在数据库写入后主动调 invalidate 缩略图缓存，
        避免 UI 层兜底。

        Args:
            unit_id: 内容单元 ID。
            title: 新标题。None 不改；"" 清空；strip 后为空视为清空。
            source_url: 新来源 URL。None 不改；"" 清空。
            notes: 新备注。None 不改；"" 清空。
            cover_path: 新封面相对路径。None 不改；"" 清空。
                非 None 且非空时校验图片在内容单元目录下存在。

        Returns:
            更新后的 ContentUnit。

        Raises:
            ContentUnitNotFoundError: unit_id 不存在。
            InvalidMetadataError: title 过长 / source_url 过长 / cover_path 不存在。
            CoverImageNotFoundError: cover_path 指定的图片在内容单元目录下不存在。
        """
        unit = self._repo.get_by_id(unit_id)
        if unit is None:
            raise ContentUnitNotFoundError(f"内容单元不存在：{unit_id}")

        # 记录 cover_path 是否变化（用于写入后 invalidate 缩略图缓存）
        cover_changed = False
        original_cover_path = unit.cover_path

        # 校验并应用各字段
        if title is not None:
            title = title.strip()
            if len(title) > _TITLE_MAX_LENGTH:
                raise InvalidMetadataError(f"标题不能超过 {_TITLE_MAX_LENGTH} 个字符")
            unit.title = title or None  # 空字符串 → None

        if source_url is not None:
            source_url = source_url.strip()
            if len(source_url) > _URL_MAX_LENGTH:
                raise InvalidMetadataError(f"来源 URL 不能超过 {_URL_MAX_LENGTH} 个字符")
            unit.source_url = source_url or None

        if notes is not None:
            unit.notes = notes  # 保留原样（包括首尾空白）但空字符串 → None
            if not unit.notes:
                unit.notes = None

        if cover_path is not None:
            cover_path = cover_path.strip()
            if cover_path:
                # 校验图片在内容单元目录下存在
                self._validate_cover_path(unit.path, cover_path)
                unit.cover_path = cover_path
            else:
                unit.cover_path = None  # 清空
            # 检测 cover_path 是否实际变化（归一化比较）
            if unit.cover_path != original_cover_path:
                cover_changed = True

        unit.updated_at = self._now()
        updated_unit = self._repo.update(unit)

        # Stage 4.5 M4 修复：cover_path 变化后主动 invalidate 缩略图缓存
        if cover_changed and self._thumbnail_service is not None:
            try:
                self._thumbnail_service.invalidate(unit_id)
            except Exception:  # noqa: BLE001
                # invalidate 失败不应影响元数据保存（已成功写入）
                logger.exception("invalidate 缩略图缓存失败：unit_id=%s", unit_id)

        return updated_unit

    def _validate_cover_path(self, unit_path: str, cover_path: str) -> None:
        """校验 cover_path 是 unit_path 下的图片文件且存在。

        cover_path 应为相对内容单元路径的相对路径。绝对路径或包含 .. 的路径被拒绝。
        文件扩展名必须在支持列表内。

        Raises:
            InvalidMetadataError: 路径非法（绝对路径 / 包含 .. / 扩展名不支持）。
            CoverImageNotFoundError: 文件不存在。
        """
        # 路径合法性
        if Path(cover_path).is_absolute():
            raise InvalidMetadataError("封面路径必须是相对路径，不能是绝对路径")
        try:
            normalized = Path(cover_path)
            # 检查 .. 出现在路径中
            if ".." in normalized.parts:
                raise InvalidMetadataError("封面路径不能包含 ..")
        except ValueError as e:
            raise InvalidMetadataError(f"封面路径非法：{e}") from e

        # 扩展名校验
        ext = normalized.suffix.lower()
        if ext not in _COVER_IMAGE_EXTENSIONS:
            raise InvalidMetadataError(
                f"封面图片扩展名不支持：{ext}（支持：{sorted(_COVER_IMAGE_EXTENSIONS)}）"
            )

        # 文件存在性
        full_path = Path(unit_path) / normalized
        if not full_path.is_file():
            raise CoverImageNotFoundError(f"封面图片不存在：{full_path}")

    def list_cover_candidates(self, unit_path: str) -> list[Path]:
        """列出内容单元目录下所有支持的图片格式文件，按文件名升序排序。

        用于 CoverPickerDialog 的图片网格。仅扫描目录顶层（不递归子目录）。
        跳过符号链接与子目录。

        若 unit_path 不存在或不是目录，返回空列表（记日志）。
        """
        root = Path(unit_path)
        try:
            if not root.is_dir():
                return []
        except OSError as e:
            logger.warning("list_cover_candidates: 路径检查失败 %s: %s", unit_path, e)
            return []

        candidates: list[Path] = []
        try:
            for child in root.iterdir():
                try:
                    if child.is_symlink() or not child.is_file():
                        continue
                    if child.suffix.lower() in _COVER_IMAGE_EXTENSIONS:
                        candidates.append(child)
                except OSError as e:
                    logger.warning("list_cover_candidates: 跳过条目 %s: %s", child, e)
        except OSError as e:
            logger.warning("list_cover_candidates: 读取目录失败 %s: %s", unit_path, e)
            return []

        # 按文件名升序（不区分大小写）
        candidates.sort(key=lambda p: (p.name.lower(), p.name))
        return candidates

    def quick_set_cover(self, unit_id: str) -> bool:
        """快速设置封面（Stage 5 Task 1）。

        取内容单元目录下第一张图片（list_cover_candidates 已排序）设为封面。
        若已有手动封面则不覆盖。仅文件夹内容单元可用。

        Args:
            unit_id: 内容单元 ID。

        Returns:
            True 表示设置成功；False 表示无可用图片或非文件夹内容单元（不报错）。

        Raises:
            ContentUnitNotFoundError: unit_id 不存在。
        """
        unit = self._repo.get_by_id(unit_id)
        if unit is None:
            raise ContentUnitNotFoundError(f"内容单元不存在：{unit_id}")

        # 仅文件夹内容单元可用；压缩包内容单元直接跳过
        try:
            if not Path(unit.path).is_dir():
                return False
        except OSError:
            return False

        # 已有手动封面不覆盖
        if unit.cover_path:
            return False

        candidates = self.list_cover_candidates(unit.path)
        if not candidates:
            return False  # 无图片，不报错

        first = candidates[0]
        rel_path = first.name
        # 走 update_metadata 以复用 cover_path 校验 + 缩略图 invalidate 链路
        self.update_metadata(unit_id, cover_path=rel_path)
        return True

    def _build_entry(self, child: Path) -> FileEntry | None:
        """从单个 Path 构建 FileEntry（单次精确查询 content_unit）。跳过符号链接。"""
        try:
            if child.is_symlink():
                return None
            is_dir = child.is_dir()
            stat = child.stat()
            modified_at = _mtime_to_iso(stat.st_mtime)
            size: int | None = None if is_dir else stat.st_size
        except OSError as e:
            logger.warning("list_directory_entries: 读取条目失败 %s: %s", child, e)
            return None

        # 关联 content_unit（按 path 精确匹配）
        content_unit: ContentUnit | None = None
        try:
            content_unit = self._repo.get_by_path(str(child))
            # "unmarked" 状态视为无内容单元（用户显式取消标记）
            if content_unit is not None and content_unit.status == "unmarked":
                content_unit = None
        except (RepositoryError, sqlite3.Error):  # 数据库查询失败不应中断遍历
            logger.exception("查询 content_unit 失败：path=%s", child)

        return FileEntry(
            name=child.name,
            path=str(child),
            is_dir=is_dir,
            modified_at=modified_at,
            size=size,
            content_unit=content_unit,
        )

    def _build_entry_with_map(
        self, child: Path, unit_map: dict[str, ContentUnit]
    ) -> FileEntry | None:
        """从单个 Path 构建 FileEntry，content_unit 从预构建的 path_key 映射查询。

        用于 list_staging_entries 的批量关联场景，避免 N 次 DB 查询。
        """
        try:
            if child.is_symlink():
                return None
            is_dir = child.is_dir()
            stat = child.stat()
            modified_at = _mtime_to_iso(stat.st_mtime)
            size: int | None = None if is_dir else stat.st_size
        except OSError as e:
            logger.warning("list_staging_entries: 读取条目失败 %s: %s", child, e)
            return None

        content_unit = unit_map.get(make_path_key(str(child)))

        return FileEntry(
            name=child.name,
            path=str(child),
            is_dir=is_dir,
            modified_at=modified_at,
            size=size,
            content_unit=content_unit,
        )

    def _has_ancestor_in_set(self, path: str, ancestor_keys: set[str]) -> bool:
        """检查 path 的任一祖先（不含自身）是否在 ancestor_keys 集合中。

        基于 make_path_key 归一化后比较。
        从 path.parent 逐级向上直到根目录。
        """
        p = Path(path)
        parent = p.parent
        while parent != parent.parent:
            if make_path_key(parent) in ancestor_keys:
                return True
            parent = parent.parent
        return False


def _mtime_to_iso(mtime: float) -> str:
    """把 stat.st_mtime（epoch 秒）转为 ISO 8601 UTC 字符串。"""
    dt = datetime.fromtimestamp(mtime, tz=UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
