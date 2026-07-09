"""目录树查询服务。

依据 docs/architecture.md §3、§2.1。阶段 2 Task 2 实现。

职责：
- 将 ManagedRoot 配置与扫描得到的 FolderNode 关联为统一树视图。
- 为 UI 层提供只读、无 Qt 依赖的树节点数据结构。
- 不访问文件系统；不重新扫描；不写数据库。

关联策略（D1 决策延续）：
- ManagedRoot 表示用户配置（持久化、跨扫描保留）。
- FolderNode 表示扫描时观察到的目录节点。
- 通过 path_key 将二者关联：ManagedRoot.path_key == FolderNode.path_key
  且 FolderNode.is_managed_root=True 时，该 FolderNode 为该配置对应的扫描根节点。
- 已配置但未扫描的 ManagedRoot 在树中作为"未扫描"虚拟节点展示。
- 移除 ManagedRoot 不自动清理 FolderNode（清理策略待确认）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import PurePath

from domain.models import FolderNode, ManagedRoot
from infrastructure.repositories.folder_node import FolderNodeRepository
from infrastructure.repositories.managed_root import ManagedRootRepository

logger = logging.getLogger(__name__)


@dataclass
class TreeNode:
    """目录树节点数据结构（UI 无关）。

    category 区分：
    - "managed_root"：已配置且已扫描的受管理根目录（关联 ManagedRoot + FolderNode）。
    - "unscanned_root"：已配置但尚未扫描的受管理根目录（仅 ManagedRoot，无 FolderNode）。
    - "folder"：扫描得到的子目录节点（仅 FolderNode）。
    """

    node_id: str
    display_name: str
    real_path: str
    category: str
    is_managed_root: bool
    managed_root_id: str | None = None
    folder_node_id: str | None = None
    parent_id: str | None = None

    def __post_init__(self) -> None:
        if self.category not in ("managed_root", "unscanned_root", "folder"):
            raise ValueError(f"非法 TreeNode.category：{self.category}")
        if not self.node_id:
            raise ValueError("TreeNode.node_id 不能为空")
        if not self.display_name:
            raise ValueError("TreeNode.display_name 不能为空")
        if not self.real_path:
            raise ValueError("TreeNode.real_path 不能为空")


def _display_name_for_folder(node: FolderNode) -> str:
    """从 FolderNode 推导显示名。

    FileScanner 持久化时 display_name 为 None（见 file_scanner.py），
    因此统一回退到 real_path 的最后一段；根目录无名称时回退到完整路径。
    """
    if node.display_name:
        return node.display_name
    name = PurePath(node.real_path).name
    return name if name else node.real_path


def _display_name_for_root(root: ManagedRoot) -> str:
    """从 ManagedRoot 推导显示名。"""
    if root.display_name:
        return root.display_name
    name = PurePath(root.real_path).name
    return name if name else root.real_path


class FolderTreeService:
    """目录树查询服务。

    使用方式：
        service = FolderTreeService(managed_root_repo, folder_repo)
        roots = service.list_root_nodes()           # 顶层节点
        children = service.list_children(node_id)    # 子节点
        node = service.get_node(node_id)             # 单节点详情
        count = service.count_children(node_id)      # 子目录数

    所有方法仅读取数据库，不访问文件系统，不写数据库。
    """

    def __init__(
        self,
        managed_root_repo: ManagedRootRepository,
        folder_repo: FolderNodeRepository,
    ) -> None:
        self._managed_root_repo = managed_root_repo
        self._folder_repo = folder_repo

    def list_root_nodes(self) -> list[TreeNode]:
        """返回目录树顶层节点。

        合并 ManagedRoot 配置与 FolderNode 扫描根：
        - 每个 ManagedRoot 对应一个顶层节点。
        - 若该 ManagedRoot 的 path_key 在 folder_node 表中存在且 is_managed_root=True，
          则 category="managed_root"，关联 FolderNode。
        - 否则 category="unscanned_root"，表示已配置但未扫描。
        - 顶层节点按 real_path 排序。

        注意：folder_node 表中可能存在 is_managed_root=True 但已无对应 ManagedRoot 配置
        的孤儿节点（配置被移除但扫描结果未清理）。本任务不展示这类孤儿节点，
        避免与 ManagedRoot 配置职责混淆。
        """
        roots = self._managed_root_repo.list_all()
        nodes: list[TreeNode] = []
        for root in roots:
            folder = self._folder_repo.get_by_path_key(root.path_key)
            if folder is not None and folder.is_managed_root:
                nodes.append(
                    TreeNode(
                        node_id=f"mr:{root.id}",
                        display_name=_display_name_for_root(root),
                        real_path=root.real_path,
                        category="managed_root",
                        is_managed_root=True,
                        managed_root_id=root.id,
                        folder_node_id=folder.id,
                        parent_id=None,
                    )
                )
            else:
                nodes.append(
                    TreeNode(
                        node_id=f"mr:{root.id}",
                        display_name=_display_name_for_root(root),
                        real_path=root.real_path,
                        category="unscanned_root",
                        is_managed_root=True,
                        managed_root_id=root.id,
                        folder_node_id=None,
                        parent_id=None,
                    )
                )
        return nodes

    def list_children(self, node_id: str) -> list[TreeNode]:
        """返回指定节点的子目录节点。

        - node_id 格式 "mr:<managed_root_id>" 表示顶层 ManagedRoot 节点，
          其子节点为关联 FolderNode 的直接子目录。
        - node_id 格式 "fn:<folder_node_id>" 表示 FolderNode 节点，
          其子节点为该 FolderNode 的直接子目录。
        - unscanned_root 无子节点（返回空列表）。
        - 子节点按 real_path 排序。

        若 node_id 格式非法或关联的 FolderNode 不存在，返回空列表（不抛异常）。
        """
        if not node_id.startswith(("mr:", "fn:")):
            logger.warning("非法 node_id 格式：%s", node_id)
            return []

        if node_id.startswith("mr:"):
            managed_root_id = node_id[3:]
            root = self._managed_root_repo.get_by_id(managed_root_id)
            if root is None:
                return []
            folder = self._folder_repo.get_by_path_key(root.path_key)
            if folder is None or not folder.is_managed_root:
                # unscanned_root 或扫描数据丢失
                return []
            children = self._folder_repo.list_by_parent(folder.id)
        else:
            folder_node_id = node_id[3:]
            folder = self._folder_repo.get_by_id(folder_node_id)
            if folder is None:
                return []
            children = self._folder_repo.list_by_parent(folder.id)

        return [
            TreeNode(
                node_id=f"fn:{child.id}",
                display_name=_display_name_for_folder(child),
                real_path=child.real_path,
                category="folder",
                is_managed_root=False,
                managed_root_id=None,
                folder_node_id=child.id,
                parent_id=node_id,
            )
            for child in children
        ]

    def get_node(self, node_id: str) -> TreeNode | None:
        """查询单个节点详情；不存在返回 None。

        用于详情面板展示选中节点的元数据。
        """
        if not node_id.startswith(("mr:", "fn:")):
            return None

        if node_id.startswith("mr:"):
            managed_root_id = node_id[3:]
            root = self._managed_root_repo.get_by_id(managed_root_id)
            if root is None:
                return None
            folder = self._folder_repo.get_by_path_key(root.path_key)
            if folder is not None and folder.is_managed_root:
                return TreeNode(
                    node_id=node_id,
                    display_name=_display_name_for_root(root),
                    real_path=root.real_path,
                    category="managed_root",
                    is_managed_root=True,
                    managed_root_id=root.id,
                    folder_node_id=folder.id,
                    parent_id=None,
                )
            return TreeNode(
                node_id=node_id,
                display_name=_display_name_for_root(root),
                real_path=root.real_path,
                category="unscanned_root",
                is_managed_root=True,
                managed_root_id=root.id,
                folder_node_id=None,
                parent_id=None,
            )

        # fn:<folder_node_id>
        folder_node_id = node_id[3:]
        folder = self._folder_repo.get_by_id(folder_node_id)
        if folder is None:
            return None
        return TreeNode(
            node_id=node_id,
            display_name=_display_name_for_folder(folder),
            real_path=folder.real_path,
            category="folder",
            is_managed_root=folder.is_managed_root,
            managed_root_id=None,
            folder_node_id=folder.id,
            parent_id=None,  # 详情面板不依赖 parent_id
        )

    def count_children(self, node_id: str) -> int:
        """返回指定节点的子目录数量。

        用于详情面板展示基础统计，无需加载完整子节点列表。
        unscanned_root 返回 0。
        """
        if not node_id.startswith(("mr:", "fn:")):
            return 0

        if node_id.startswith("mr:"):
            managed_root_id = node_id[3:]
            root = self._managed_root_repo.get_by_id(managed_root_id)
            if root is None:
                return 0
            folder = self._folder_repo.get_by_path_key(root.path_key)
            if folder is None or not folder.is_managed_root:
                return 0
            return self._folder_repo.count_children(folder.id)

        folder_node_id = node_id[3:]
        folder = self._folder_repo.get_by_id(folder_node_id)
        if folder is None:
            return 0
        return self._folder_repo.count_children(folder.id)

    def has_scan_data(self, managed_root_id: str) -> bool:
        """指定 ManagedRoot 是否有扫描数据（folder_node 表中存在对应根节点）。"""
        root = self._managed_root_repo.get_by_id(managed_root_id)
        if root is None:
            return False
        folder = self._folder_repo.get_by_path_key(root.path_key)
        return folder is not None and folder.is_managed_root
