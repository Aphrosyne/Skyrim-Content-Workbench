"""内容单元创建服务（D1 重命名：原 ModGroupService）。

阶段 3 Task 3：从暂存区零散压缩包文件创建标准化 Mod 组文件夹。
（UI 术语保留 "Mod 组"，代码层面使用 ContentUnitCreationService 以消除概念混乱）

工作流：
1. 从文件名提取主要名称（剔除版本号、扩展名）。
2. 在暂存区创建以该名称命名的新文件夹（FileOperationService.new_folder）。
3. 把源压缩包文件移入新文件夹（FileOperationService.move）。
4. 取消源文件旧路径的 ContentUnit 标记（若存在，设为 "unmarked" 避免悬挂标记）。
5. 为新文件夹标记 ContentUnit（mark_as_content_unit，spec §5.4 标记文件夹时
   取消子项标记；默认 title=path.name）。

Stage 4.5 H4（TD-M22）：FileOperationService 注入 FolderCacheSyncHelper 后，
new_folder/move 自动同步 folder_cache，本服务不再手动同步。
移除了 _resolve_parent_id_by_path / _new_folder_cache_id / _now_iso 等
重复逻辑（已集中到 FolderCacheSyncHelper）。

失败回滚：若 move 失败，删除已创建的空文件夹（仅当为空时）。
folder_cache 记录由上层 UoW 事务回滚自动撤销。

约束（AGENTS 规则）：
- 不覆盖已有文件/目录（FileOperationService 已保证）。
- 文件操作通过 FileOperationService，本服务不直接调用 shutil / Path.rename。
- 不自提交，由调用方控制事务边界。
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from application.content_service import ContentService
from application.errors import (
    ApplicationError,
    FileOperationError,
    InvalidContentUnitNameError,
    SourceNotInStagingError,
)
from application.file_operation_service import FileOperationService
from application.nexus_filename import extract_mod_name  # noqa: F401  (re-export)
from application.tag_service import TagService
from domain.models import ContentUnit
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.errors import RepositoryError
from infrastructure.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)


@dataclass
class _InheritedMetadata:
    """从源内容单元快照的待继承元数据（操作合理性5，2026-08-04）。"""

    source_url: str | None = None
    notes: str | None = None
    tag_ids: list[str] = field(default_factory=list)

    @property
    def has_any(self) -> bool:
        return self.source_url is not None or self.notes is not None or bool(self.tag_ids)


@dataclass
class CreateContentUnitResult:
    """批量创建 Mod 组的结果。

    UX 重构 Phase 1 Task 1 Commit 3：多选创建 Mod 组。
    """

    unit: ContentUnit
    success_count: int
    failure_count: int


class ContentUnitCreationService:
    """内容单元创建服务（D1 重命名：原 ModGroupService）。

    UI 术语保留 "Mod 组"（用户认知友好），代码层面使用 ContentUnitCreationService
    以消除"Mod 组"与"ContentUnit"概念混用问题。

    Stage 4.5 H4（TD-M22）：folder_cache 同步由 FileOperationService 内部
    的 FolderCacheSyncHelper 自动处理，本服务不再手动同步。

    使用方式：
        service = ContentUnitCreationService(file_op_service, content_service, uow=uow)
        unit = service.create_content_unit_from_file(
            Path("D:/Stash/file.7z"), Path("D:/Stash"), "NewMod"
        )
    """

    def __init__(
        self,
        file_op_service: FileOperationService,
        content_service: ContentService,
        uow: UnitOfWork | None = None,
        tag_service: TagService | None = None,
    ) -> None:
        """初始化 ContentUnitCreationService。

        Args:
            file_op_service: 文件操作服务（Stage 4.5 H4：应注入 FolderCacheSyncHelper，
                new_folder/move 自动同步 folder_cache）。
            content_service: 内容单元服务。
            uow: 事务边界管理器（可选）。Stage 4.5 H6 修复：
                注入后 create_content_unit_from_file 的多步写操作在事务内执行，保证原子性。
                None 时保持原行为（调用方控制事务边界）。
            tag_service: 标签服务（可选）。操作合理性5（2026-08-04）：
                注入后创建 Mod 组时把源文件内容单元的标签继承到新文件夹单元。
                None 时跳过标签继承（向后兼容）。
        """
        self._file_op = file_op_service
        self._content = content_service
        self._uow = uow
        self._tag_service = tag_service

    def create_content_unit_from_file(
        self,
        source_file: Path,
        staging_path: Path,
        name: str | None = None,
    ) -> ContentUnit:
        """创建 Mod 组（UI 术语）：在暂存区建文件夹 + 移入源文件 + 标记 ContentUnit。

        Args:
            source_file: 源压缩包文件路径（必须在 staging_path 之下）。
            staging_path: 暂存区根目录路径。
            name: Mod 组名称。None 时从 source_file 文件名自动提取。

        Returns:
            新创建的 ContentUnit（path 指向新文件夹，title=文件夹名；纯 DELETE 模式
            下记录存在即已标记）。

        Raises:
            SourceNotInStagingError: source_file 不在 staging_path 下。
            InvalidContentUnitNameError: name 为空或仅含空白。
            ConflictError: 目标文件夹已存在（FileOperationService 抛出）。
            FileOperationError: 其他文件操作失败。
        """
        # 校验 source_file 在 staging_path 下
        if not _is_in_directory(source_file, staging_path):
            raise SourceNotInStagingError(
                f"源文件不在暂存区下：{source_file} 不在 {staging_path} 内"
            )

        # 解析名称
        if name is None:
            name = extract_mod_name(source_file.name)
        name = name.strip()
        if not name:
            raise InvalidContentUnitNameError("Mod 组名称不能为空")

        target_folder = staging_path / name
        target_file = target_folder / source_file.name

        # DB + 文件操作在事务内执行（Stage 4.5 H6：保证多步写原子性）
        # 文件操作（new_folder/move）不受事务保护（无法回滚），但异常时
        # 各步骤的 except 块会做文件清理 + re-raise → UoW 回滚 DB 写操作。
        if self._uow is not None:
            with self._uow.transaction():
                return self._create_content_unit_core(
                    source_file, staging_path, target_folder, target_file
                )
        return self._create_content_unit_core(source_file, staging_path, target_folder, target_file)

    def create_content_unit_from_files(
        self,
        source_files: list[Path],
        staging_path: Path,
        name: str | None = None,
    ) -> CreateContentUnitResult:
        """批量创建 Mod 组：建文件夹 + 移入多个源文件 + 标记 ContentUnit。

        UX 重构 Phase 1 Task 1 Commit 3：多选创建 Mod 组。
        原 create_content_unit_from_file 逐个调用会因文件夹已存在抛 ConflictError，
        故新增批量接口：创建一次文件夹 + 逐个移入文件（容错）+ 标记一次。

        Args:
            source_files: 源文件路径列表（必须全部在 staging_path 之下）。
            staging_path: 暂存区根目录路径（新文件夹在此创建）。
            name: Mod 组名称。None 时从第一个文件名自动提取。

        Returns:
            CreateContentUnitResult：包含 ContentUnit、成功数、失败数。

        Raises:
            SourceNotInStagingError: 任一源文件不在 staging_path 下。
            InvalidContentUnitNameError: name 为空或仅含空白。
            ConflictError: 目标文件夹已存在。
            FileOperationError: 文件夹创建失败。
        """
        if not source_files:
            raise InvalidContentUnitNameError("源文件列表不能为空")

        # 校验所有源文件在 staging_path 下
        for source_file in source_files:
            if not _is_in_directory(source_file, staging_path):
                raise SourceNotInStagingError(
                    f"源文件不在暂存区下：{source_file} 不在 {staging_path} 内"
                )

        # 解析名称（F1：按列表顺序的第一项提取名，由调用方保证显示顺序）
        first_file = source_files[0]
        if name is None:
            name = extract_mod_name(first_file.name)
        name = name.strip()
        if not name:
            raise InvalidContentUnitNameError("Mod 组名称不能为空")

        target_folder = staging_path / name

        if self._uow is not None:
            with self._uow.transaction():
                return self._create_content_unit_from_files_core(source_files, target_folder)
        return self._create_content_unit_from_files_core(source_files, target_folder)

    def _create_content_unit_from_files_core(
        self,
        source_files: list[Path],
        target_folder: Path,
    ) -> CreateContentUnitResult:
        """批量创建核心逻辑：建文件夹 + 逐个移入 + 取消旧标记 + 标记新 ContentUnit。

        容错策略（D1）：逐个移动，失败记日志不中断，最终汇总返回。
        """
        # 步骤 1：创建新文件夹（若已存在抛 ConflictError，由调用方处理）
        self._file_op.new_folder(target_folder)

        # 步骤 2 前置：快照源单元元数据（操作合理性5，2026-08-04）
        # move 会由 FileOperationService 改写 ContentUnit.path，且后续 mark 文件夹会
        # 级联删除子项记录（父子不可同时标记），必须在任何移动前收集。
        inherited = self._collect_metadata_from_paths(source_files)

        # 步骤 2：逐个移入源文件（容错：失败记日志不中断）
        success_count = 0
        failure_count = 0
        moved_files: list[Path] = []
        for source_file in source_files:
            target_file = target_folder / source_file.name
            try:
                self._file_op.move(source_file, target_file)
                moved_files.append(source_file)
                success_count += 1
            except (FileOperationError, OSError) as move_err:
                logger.warning("移动源文件失败，跳过：%s：%s", source_file, move_err)
                failure_count += 1

        # 步骤 3：取消已移动源文件的旧 ContentUnit 标记
        for source_file in moved_files:
            old_unit = self._content.get_by_path(str(source_file))
            if old_unit is not None:
                try:
                    self._content.unmark_content_unit(old_unit.id)
                except (ApplicationError, RepositoryError, sqlite3.Error):
                    logger.exception("取消源文件旧 ContentUnit 标记失败：path=%s", source_file)

        # 步骤 4：标记文件夹为 ContentUnit
        try:
            unit = self._content.mark_as_content_unit(target_folder)
        except (ApplicationError, RepositoryError, sqlite3.Error) as create_err:
            logger.exception(
                "创建 ContentUnit 失败（文件已移动到 %s），请手动添加内容单元标记",
                target_folder,
            )
            raise FileOperationError(f"创建 ContentUnit 失败：{create_err}") from create_err

        # 步骤 5：继承源单元元数据（来源 URL / 备注 / 标签并集）
        if inherited.has_any:
            unit = self._apply_inherited_metadata(unit, inherited)

        return CreateContentUnitResult(
            unit=unit, success_count=success_count, failure_count=failure_count
        )

    def _create_content_unit_core(
        self,
        source_file: Path,
        staging_path: Path,
        target_folder: Path,
        target_file: Path,
    ) -> ContentUnit:
        """create_content_unit_from_file 的核心逻辑（文件操作 + DB 写）。

        Stage 4.5 H4（TD-M22）：folder_cache 同步由 FileOperationService.new_folder
        内部的 FolderCacheSyncHelper 自动完成（删除旧 + 插入新 + 更新父 mtime），
        本方法不再手动同步。

        异常处理：move 失败时清理已创建的空文件夹 + re-raise。
        re-raise 传播到 UoW transaction 时触发 DB 回滚（folder_cache 记录
        由 new_folder 自动同步写入，会被 UoW 回滚撤销）。
        """
        # 步骤 1：创建新文件夹（FileOperationService 内部自动同步 folder_cache）
        # 若文件夹已存在，FileOperationService.new_folder 抛 ConflictError
        self._file_op.new_folder(target_folder)

        # 步骤 1.5：快照源单元元数据（操作合理性5，2026-08-04）
        # move 会改写 ContentUnit.path，旧路径查询将失效，必须在移动前收集。
        old_unit = self._content.get_by_path(str(source_file))
        inherited = (
            self._collect_metadata_from_units([old_unit])
            if old_unit is not None
            else _InheritedMetadata()
        )

        # 步骤 2：移入源文件
        # 若 move 失败，回滚：删除刚创建的空文件夹（仅当为空时）
        # folder_cache 记录由 UoW 回滚自动撤销
        try:
            self._file_op.move(source_file, target_file)
        except (FileOperationError, OSError) as move_err:
            _try_cleanup_empty_folder(target_folder)
            raise FileOperationError(f"移动源文件失败：{move_err}") from move_err

        # 步骤 3：取消源文件的旧 ContentUnit 标记（若存在）
        # 源文件已移动，旧路径的 ContentUnit 记录设为 "unmarked"（不可见，
        # 扫描不会重建），避免用户看到悬挂标记。
        if old_unit is not None:
            try:
                self._content.unmark_content_unit(old_unit.id)
            except (ApplicationError, RepositoryError, sqlite3.Error):
                logger.exception("取消源文件旧 ContentUnit 标记失败：path=%s", source_file)

        # 步骤 4：为新文件夹标记 ContentUnit
        # 使用 mark_as_content_unit（spec §5.4：标记文件夹时取消子项标记），
        # 默认 title=path.name（即文件夹名 == name）。
        try:
            unit = self._content.mark_as_content_unit(target_folder)
        except (ApplicationError, RepositoryError, sqlite3.Error) as create_err:
            # ContentUnit 创建失败不回滚文件操作（文件已移动，无法自动复原）
            # 记日志，由用户手动处理
            logger.exception(
                "创建 ContentUnit 失败（文件已移动到 %s），请手动添加内容单元标记",
                target_folder,
            )
            raise FileOperationError(f"创建 ContentUnit 失败：{create_err}") from create_err

        # 步骤 5：继承源单元元数据（来源 URL / 备注 / 标签）
        if inherited.has_any:
            unit = self._apply_inherited_metadata(unit, inherited)
        return unit

    # === 操作合理性5（2026-08-04）：创建 Mod 组继承元数据 ===

    def _collect_metadata_from_paths(self, source_files: list[Path]) -> _InheritedMetadata:
        """从多个源路径收集元数据（tags 并集；source_url/notes 取第一个非空）。"""
        units: list[ContentUnit] = []
        for path in source_files:
            unit = self._content.get_by_path(str(path))
            if unit is not None:
                units.append(unit)
        return self._collect_metadata_from_units(units)

    def _collect_metadata_from_units(self, units: list[ContentUnit]) -> _InheritedMetadata:
        """收集并合并多个源单元的元数据。"""
        merged = _InheritedMetadata()
        for unit in units:
            single = _InheritedMetadata(source_url=unit.source_url, notes=unit.notes)
            if self._tag_service is not None:
                try:
                    for _category, tags in self._tag_service.list_tags_of_content_unit(unit.id):
                        single.tag_ids.extend(t.id for t in tags)
                except (ApplicationError, RepositoryError, sqlite3.Error):
                    logger.exception("读取源内容单元标签失败：unit_id=%s", unit.id)
            merged = self._merge_inherited(merged, single)
        return merged

    def _merge_inherited(
        self, base: _InheritedMetadata, other: _InheritedMetadata
    ) -> _InheritedMetadata:
        """合并两个元数据快照：首个非空优先，标签取并集（保序去重）。"""
        merged = _InheritedMetadata(
            source_url=base.source_url if base.source_url is not None else other.source_url,
            notes=base.notes if base.notes is not None else other.notes,
        )
        seen: set[str] = set(base.tag_ids)
        merged.tag_ids = list(base.tag_ids)
        for tag_id in other.tag_ids:
            if tag_id not in seen:
                seen.add(tag_id)
                merged.tag_ids.append(tag_id)
        return merged

    def _apply_inherited_metadata(
        self, unit: ContentUnit, inherited: _InheritedMetadata
    ) -> ContentUnit:
        """把快照的元数据应用到新文件夹单元（来源 URL / 备注 / 标签）。"""
        updated = unit
        if inherited.source_url is not None or inherited.notes is not None:
            try:
                updated = self._content.update_metadata(
                    unit.id, source_url=inherited.source_url, notes=inherited.notes
                )
            except (ApplicationError, RepositoryError, sqlite3.Error):
                logger.exception("继承来源/备注失败：unit_id=%s", unit.id)
        if self._tag_service is not None:
            for tag_id in inherited.tag_ids:
                try:
                    self._tag_service.attach_tag_to_unit(unit.id, tag_id)
                except (ApplicationError, RepositoryError, sqlite3.Error):
                    logger.exception("继承标签失败：unit_id=%s tag_id=%s", unit.id, tag_id)
        return updated


def _is_in_directory(file_path: Path, dir_path: Path) -> bool:
    """判断 file_path 是否在 dir_path 之下（含 dir_path 自身）。

    使用 make_path_key 归一化后字符串前缀比较，避免大小写/分隔符差异。
    不访问文件系统，仅基于路径字符串比较。
    """
    sep = os.sep
    dir_key = make_path_key(dir_path).rstrip(sep) + sep
    file_key = make_path_key(file_path)
    return file_key.startswith(dir_key)


def _try_cleanup_empty_folder(folder: Path) -> None:
    """尝试删除空文件夹（仅当为空时）。失败静默记日志。"""
    try:
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    except OSError as e:
        logger.warning("清理空文件夹失败 %s: %s", folder, e)
