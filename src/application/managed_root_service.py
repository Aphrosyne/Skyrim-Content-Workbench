"""受管理根目录管理服务。

依据 docs/spec.md §6.5、docs/architecture.md §3。
依据 D1 决策：新增独立 managed_root 表，不依赖 folder_cache。

约束：
- 仅写应用数据库；不扫描、不移动、不删除、不重命名、不复制用户文件。
- 路径合法性检查只使用只读文件系统 API（Path.exists / Path.is_dir）。
- 同一 path_key 不能重复添加（A2 路径标准化）。
- 不自动扫描；添加根目录不触发扫描。
- 移除根目录配置时同步清理该根路径前缀下的 folder_cache / content_unit 扫描记录
  （UX 重构 Task 6，open-questions §6）；重叠守卫：仍属于其他剩余根目录的记录不清理。
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from application.errors import (
    DuplicateManagedRootError,
    InvalidRootPathError,
    ManagedRootNotFoundError,
)
from domain.models import ManagedRoot
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.content_unit import ContentUnitRepository
from infrastructure.repositories.errors import ConstraintViolationError
from infrastructure.repositories.folder_cache import FolderCacheRepository
from infrastructure.repositories.managed_root import ManagedRootRepository
from infrastructure.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)


def _default_now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_uuid_provider() -> str:
    return str(uuid.uuid4())


class ManagedRootService:
    """受管理根目录配置的添加、列出、查询。

    使用方式：
        service = ManagedRootService(managed_root_repo)
        root = service.add_root(Path("D:/Mods"))
        roots = service.list_roots()
    """

    def __init__(
        self,
        managed_root_repo: ManagedRootRepository,
        folder_cache_repo: FolderCacheRepository,
        content_unit_repo: ContentUnitRepository,
        now_provider: Callable[[], str] | None = None,
        uuid_provider: Callable[[], str] | None = None,
        uow: UnitOfWork | None = None,
    ) -> None:
        """初始化 ManagedRootService。

        Args:
            managed_root_repo: 受管理根目录仓储。
            folder_cache_repo: 目录树缓存仓储（remove_root 清理用）。
            content_unit_repo: 内容单元仓储（remove_root 清理用）。
            now_provider: 时间戳提供者（用于测试注入）。
            uuid_provider: UUID 提供者（用于测试注入）。
            uow: 事务边界管理器（可选）。注入后 remove_root 的多步清理写操作
                在事务内执行，保证原子性。
        """
        self._repo = managed_root_repo
        self._folder_cache_repo = folder_cache_repo
        self._content_unit_repo = content_unit_repo
        self._now = now_provider or _default_now_utc
        self._new_uuid = uuid_provider or _default_uuid_provider
        self._uow = uow

    def add_root(self, real_path: Path) -> ManagedRoot:
        """添加一个受管理根目录。

        规则：
        - 路径必须存在且为目录（只读检查）。
        - 同一 path_key 不能重复添加。
        - display_name 初始等于目录名（Path.name）；本任务不支持编辑。

        不扫描、不移动、不复制、不修改该目录或其中任何用户文件。
        """
        # 只读校验路径合法性
        try:
            if not real_path.exists():
                raise InvalidRootPathError(f"路径不存在：{real_path}")
            if not real_path.is_dir():
                raise InvalidRootPathError(f"路径不是目录：{real_path}")
        except OSError as e:
            # 路径访问异常（如权限不足）转为用户可读错误
            raise InvalidRootPathError(f"无法访问路径：{e}") from e

        path_key = make_path_key(real_path)

        # 去重检查
        existing = self._repo.get_by_path_key(path_key)
        if existing is not None:
            raise DuplicateManagedRootError(f"该目录已添加为受管理根目录：{real_path}")

        now = self._now()
        root = ManagedRoot(
            id=self._new_uuid(),
            real_path=str(real_path),
            path_key=path_key,
            display_name=real_path.name,
            created_at=now,
            updated_at=now,
        )
        try:
            return self._repo.create(root)
        except ConstraintViolationError as e:
            # TOCTOU 竞态：去重检查与 create 之间另一线程插入了相同 path_key
            raise DuplicateManagedRootError(f"该目录已添加为受管理根目录：{real_path}") from e

    def list_roots(self) -> list[ManagedRoot]:
        """返回全部受管理根目录，按 real_path 排序。"""
        return self._repo.list_all()

    def get_root(self, root_id: str) -> ManagedRoot:
        """查询指定根目录；不存在抛 ManagedRootNotFoundError。"""
        root = self._repo.get_by_id(root_id)
        if root is None:
            raise ManagedRootNotFoundError(f"受管理根目录不存在：{root_id}")
        return root

    def remove_root(self, root_id: str) -> None:
        """移除受管理根目录配置。

        规则：
        - 删除 managed_root 配置记录，并同步清理该根路径前缀下的
          folder_cache / content_unit 扫描记录（UX 重构 Task 6）。
        - 重叠守卫：仍属于其他剩余受管理根目录前缀的记录不删除
          （避免嵌套/重叠根目录误删共享记录）。
        - content_unit 删除级联清理 content_unit_tag 与 thumbnail_cache 记录
          （缓存文件由启动 GC 清理）。
        - 不删除、不移动、不修改该目录及其中任何用户文件。
        - 实体不存在时抛 ManagedRootNotFoundError。
        """
        # 先校验存在性，提供面向用户的错误类型（Repository 的 NotFoundError
        # 是基础设施层异常，不直接暴露给 UI）。
        if self._repo.get_by_id(root_id) is None:
            raise ManagedRootNotFoundError(f"受管理根目录不存在：{root_id}")
        if self._uow is not None:
            with self._uow.transaction():
                self._remove_root_core(root_id)
        else:
            self._remove_root_core(root_id)

    def _remove_root_core(self, root_id: str) -> None:
        """remove_root 的核心清理逻辑（UoW 事务内执行，或由调用方控制边界）。"""
        root = self._repo.get_by_id(root_id)
        assert root is not None  # remove_root 已校验存在性

        sep = os.sep
        root_key = make_path_key(root.real_path)
        root_prefix = root_key.rstrip(sep) + sep

        # 其余根目录前缀（重叠守卫）：不清理仍属于其他剩余根目录的记录
        other_roots = [r for r in self._repo.list_all() if r.id != root_id]
        other_prefixes = [make_path_key(r.real_path).rstrip(sep) + sep for r in other_roots]

        def _under_removed(key: str) -> bool:
            return key == root_key or key.startswith(root_prefix)

        def _under_other(key: str) -> bool:
            return any(key == p.rstrip(sep) or key.startswith(p) for p in other_prefixes)

        # folder_cache：按路径深度降序删除（parent_id 自引用 FK，先删子节点）
        folders_to_delete = [
            f
            for f in self._folder_cache_repo.list_all()
            if _under_removed(make_path_key(f.path)) and not _under_other(make_path_key(f.path))
        ]
        folders_to_delete.sort(key=lambda f: f.path.count(sep), reverse=True)
        for folder in folders_to_delete:
            self._folder_cache_repo.delete(folder.id)

        # content_unit：级联清理 content_unit_tag + thumbnail_cache 记录
        for unit in self._content_unit_repo.list_all():
            key = make_path_key(unit.path)
            if _under_removed(key) and not _under_other(key):
                self._content_unit_repo.delete(unit.id)

        # 最后删除 managed_root 配置记录
        self._repo.delete(root_id)
