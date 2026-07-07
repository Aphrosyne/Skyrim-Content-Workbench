"""受管理根目录管理服务。

依据 docs/phase-2-plan.md 任务 1、docs/spec.md §6.5、docs/architecture.md §3。
依据 D1 决策：新增独立 managed_root 表，不依赖 folder_node.is_managed_root。

约束：
- 仅写应用数据库；不扫描、不移动、不删除、不重命名、不复制用户文件。
- 路径合法性检查只使用只读文件系统 API（Path.exists / Path.is_dir）。
- 同一 path_key 不能重复添加（A2 路径标准化）。
- 不自动扫描；添加根目录不触发扫描。
- 本任务不实现删除根目录配置（见任务说明）。
"""

from __future__ import annotations

import logging
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
from infrastructure.repositories.managed_root import ManagedRootRepository

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
        now_provider: Callable[[], str] | None = None,
        uuid_provider: Callable[[], str] | None = None,
    ) -> None:
        self._repo = managed_root_repo
        self._now = now_provider or _default_now_utc
        self._new_uuid = uuid_provider or _default_uuid_provider

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
        return self._repo.create(root)

    def list_roots(self) -> list[ManagedRoot]:
        """返回全部受管理根目录，按 real_path 排序。"""
        return self._repo.list_all()

    def get_root(self, root_id: str) -> ManagedRoot:
        """查询指定根目录；不存在抛 ManagedRootNotFoundError。"""
        root = self._repo.get_by_id(root_id)
        if root is None:
            raise ManagedRootNotFoundError(f"受管理根目录不存在：{root_id}")
        return root
