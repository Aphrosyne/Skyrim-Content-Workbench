"""暂存区标记管理服务。

依据 docs/spec.md §5.2、docs/roadmap.md 阶段 3 Task 1。

约束：
- 仅写应用数据库；不扫描、不移动、不删除、不重命名、不复制用户文件。
- 路径合法性检查只使用只读文件系统 API（Path.exists / Path.is_dir）。
- 同一 path_key 不能重复标记（A2 路径标准化）。
- 不允许嵌套：标记时检查祖先链和子树是否已是暂存区。
- 取消标记仅删除 staging_area 记录，不修改用户文件。
- 路径丢失检测：list_staging 返回时检查路径是否存在，标记 path_exists 字段。
  完整的"路径丢失提示与重新关联 UI"留给阶段 5 Task 3。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from application.errors import (
    DuplicateStagingAreaError,
    StagingAreaNestingError,
    StagingAreaNotFoundError,
)
from domain.models import StagingArea
from infrastructure.path_utils import make_path_key
from infrastructure.repositories.errors import ConstraintViolationError
from infrastructure.repositories.staging_area import StagingAreaRepository

logger = logging.getLogger(__name__)


def _default_now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_uuid_provider() -> str:
    return str(uuid.uuid4())


class StagingService:
    """暂存区标记的添加、列出、查询、取消。

    使用方式：
        service = StagingService(staging_repo)
        staging = service.mark_staging(Path("D:/Mods/Stash"))
        stgings = service.list_staging()
    """

    def __init__(
        self,
        staging_repo: StagingAreaRepository,
        now_provider: Callable[[], str] | None = None,
        uuid_provider: Callable[[], str] | None = None,
    ) -> None:
        self._repo = staging_repo
        self._now = now_provider or _default_now_utc
        self._new_uuid = uuid_provider or _default_uuid_provider

    def mark_staging(self, real_path: Path) -> StagingArea:
        """标记一个目录为暂存区。

        规则：
        - 路径必须存在且为目录（只读检查）。
        - 同一 path_key 不能重复标记。
        - 不允许嵌套：祖先目录或子目录已是暂存区时拒绝。
        - display_name 初始等于目录名（Path.name）。

        不扫描、不移动、不复制、不修改该目录或其中任何用户文件。
        """
        # 只读校验路径合法性
        try:
            if not real_path.exists():
                raise StagingAreaNotFoundError(f"路径不存在：{real_path}")
            if not real_path.is_dir():
                raise StagingAreaNotFoundError(f"路径不是目录：{real_path}")
        except OSError as e:
            raise StagingAreaNotFoundError(f"无法访问路径：{e}") from e

        path_key = make_path_key(real_path)

        # 去重检查
        existing = self._repo.get_by_path_key(path_key)
        if existing is not None:
            raise DuplicateStagingAreaError(f"该目录已标记为暂存区：{real_path}")

        # 嵌套检查
        self._check_nesting(real_path, path_key)

        now = self._now()
        staging = StagingArea(
            id=self._new_uuid(),
            real_path=str(real_path),
            path_key=path_key,
            display_name=real_path.name,
            created_at=now,
            updated_at=now,
        )
        try:
            return self._repo.create(staging)
        except ConstraintViolationError as e:
            # TOCTOU 竞态：去重检查与 create 之间另一线程插入了相同 path_key
            raise DuplicateStagingAreaError(f"该目录已标记为暂存区：{real_path}") from e

    def unmark_staging(self, staging_id: str) -> None:
        """取消暂存区标记。

        规则：
        - 仅删除 staging_area 表中的配置记录。
        - 不删除、不移动、不修改该目录及其中任何用户文件。
        - 实体不存在时抛 StagingAreaNotFoundError。
        """
        if self._repo.get_by_id(staging_id) is None:
            raise StagingAreaNotFoundError(f"暂存区不存在：{staging_id}")
        self._repo.delete(staging_id)

    def list_staging(self) -> list[StagingArea]:
        """返回全部暂存区，按 real_path 排序。

        路径丢失检测：返回前检查 real_path 是否仍存在（只读检查），
        不存在的暂存区仍保留在返回列表中，由调用方决定如何呈现。
        """
        return self._repo.list_all()

    def get_staging(self, staging_id: str) -> StagingArea:
        """查询指定暂存区；不存在抛 StagingAreaNotFoundError。"""
        staging = self._repo.get_by_id(staging_id)
        if staging is None:
            raise StagingAreaNotFoundError(f"暂存区不存在：{staging_id}")
        return staging

    def is_staging(self, real_path: Path) -> bool:
        """检查指定路径是否为暂存区标记（按 path_key 精确匹配）。"""
        return self._repo.get_by_path_key(make_path_key(real_path)) is not None

    def get_staging_path_keys(self) -> set[str]:
        """返回全部暂存区的 path_key 集合（供 FolderTreeService 批量填充标记）。"""
        return {s.path_key for s in self._repo.list_all()}

    def _check_nesting(self, real_path: Path, path_key: str) -> None:
        """检查嵌套：祖先目录或子目录已是暂存区时抛 StagingAreaNestingError。

        - 祖先检查：遍历现有暂存区，若任一暂存区的 path_key 是当前路径的祖先，
          则当前路径嵌套在该暂存区内。
        - 子树检查：若任一暂存区的路径以当前路径为前缀（当前路径是其祖先），
          则该暂存区嵌套在当前路径内。
        """
        current_path_str = str(real_path)
        for staging in self._repo.list_all():
            # 祖先检查：现有暂存区是当前路径的祖先
            if _is_ancestor(staging.real_path, current_path_str):
                raise StagingAreaNestingError(f"祖先目录已是暂存区：{staging.real_path}")
            # 子树检查：现有暂存区在当前路径的子树内
            if staging.path_key != path_key and _is_ancestor(current_path_str, staging.real_path):
                raise StagingAreaNestingError(f"子目录已是暂存区：{staging.real_path}")


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    """判断 ancestor 是否是 descendant 的祖先目录（只读字符串比较）。

    使用 os.sep 边界判断，避免 'a/b' 误判为 'a/bc' 的祖先。
    不访问文件系统，仅基于路径字符串比较。
    """
    import os

    sep = os.sep
    # 统一末尾分隔符便于前缀比较
    a = ancestor.rstrip(sep) + sep
    d = descendant.rstrip(sep) + sep
    return d.startswith(a) and a != d
