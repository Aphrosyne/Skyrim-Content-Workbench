"""只读目录树查询服务。

从 managed_root + folder_cache 表构建目录树节点，供 UI 展示。
不访问文件系统；不写数据库。

关联逻辑（决策问题 1 选项 B）：
- ManagedRoot 与 FolderCache 通过 path 关联。
- ManagedRoot.path_key 已归一化（make_path_key = normcase + normpath）。
- FolderCache.path 原样存储（str(Path)，Windows 为反斜杠）。
- 关联时对 FolderCache.path 也调用 make_path_key 归一化后比较，不改 schema。

节点 ID 约定：
- "mr:<managed_root_id>"：受管理根目录节点（可能已扫描或未扫描）
- "fc:<folder_cache_id>"：folder_cache 表中的目录节点
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from infrastructure.path_utils import make_path_key
from infrastructure.repositories.folder_cache import FolderCacheRepository
from infrastructure.repositories.managed_root import ManagedRootRepository

logger = logging.getLogger(__name__)


@dataclass
class TreeNode:
    """目录树节点。

    node_id 格式：
    - "mr:<managed_root_id>"：受管理根目录（可能已扫描或未扫描）
    - "fc:<folder_cache_id>"：folder_cache 中的目录

    category 取值：
    - "managed_root"：已扫描的受管理根目录（关联了 folder_cache）
    - "unscanned_root"：未扫描的受管理根目录（无 folder_cache 关联）
    - "folder"：普通子目录
    """

    node_id: str
    display_name: str
    real_path: str
    category: str
    is_managed_root: bool
    managed_root_id: str | None
    folder_cache_id: str | None
    parent_id: str | None

    def __post_init__(self) -> None:
        valid_categories = {"managed_root", "unscanned_root", "folder"}
        if self.category not in valid_categories:
            raise ValueError(
                f"TreeNode.category 必须是 {valid_categories} 之一，得到：{self.category}"
            )


class FolderTreeService:
    """只读目录树查询服务。

    使用方式：
        service = FolderTreeService(managed_root_repo, folder_cache_repo)
        roots = service.list_root_nodes()
        children = service.list_children("mr:<id>")
    """

    def __init__(
        self,
        managed_root_repo: ManagedRootRepository,
        folder_cache_repo: FolderCacheRepository,
    ) -> None:
        self._managed_root_repo = managed_root_repo
        self._folder_cache_repo = folder_cache_repo

    def list_root_nodes(self) -> list[TreeNode]:
        """返回顶层节点列表（受管理根目录）。

        已扫描的根目录 → category="managed_root"，关联 folder_cache_id。
        未扫描的根目录 → category="unscanned_root"。
        按 real_path 排序。
        """
        roots = self._managed_root_repo.list_all()
        if not roots:
            return []

        # 查询 folder_cache 中所有根节点（parent_id IS NULL）
        fc_roots = self._folder_cache_repo.list_by_parent(parent_id=None)

        # 构造 path_key → folder_cache 映射，用于关联
        fc_root_map: dict[str, object] = {}
        for fc in fc_roots:
            fc_root_map[make_path_key(fc.path)] = fc

        nodes: list[TreeNode] = []
        for root in roots:
            root_key = root.path_key  # 已归一化
            fc = fc_root_map.get(root_key)
            if fc is not None:
                nodes.append(
                    TreeNode(
                        node_id=f"mr:{root.id}",
                        display_name=root.display_name or root.real_path,
                        real_path=root.real_path,
                        category="managed_root",
                        is_managed_root=True,
                        managed_root_id=root.id,
                        folder_cache_id=fc.id,  # type: ignore[union-attr]
                        parent_id=None,
                    )
                )
            else:
                nodes.append(
                    TreeNode(
                        node_id=f"mr:{root.id}",
                        display_name=root.display_name or root.real_path,
                        real_path=root.real_path,
                        category="unscanned_root",
                        is_managed_root=True,
                        managed_root_id=root.id,
                        folder_cache_id=None,
                        parent_id=None,
                    )
                )
        return nodes

    def list_children(self, node_id: str) -> list[TreeNode]:
        """返回指定节点的子节点列表。

        node_id 前缀：
        - "mr:" → 查询该 managed_root 关联的 folder_cache 根节点的子节点
        - "fc:" → 查询该 folder_cache 的子节点

        未扫描的 managed_root 返回空列表。
        无效 node_id 返回空列表。
        """
        if not node_id:
            return []

        if node_id.startswith("mr:"):
            return self._list_children_of_managed_root(node_id[3:])
        if node_id.startswith("fc:"):
            return self._list_children_of_folder_cache(node_id[3:])
        return []

    def get_node(self, node_id: str) -> TreeNode | None:
        """获取单个节点。不存在返回 None。"""
        if not node_id:
            return None

        if node_id.startswith("mr:"):
            return self._get_managed_root_node(node_id[3:])
        if node_id.startswith("fc:"):
            return self._get_folder_cache_node(node_id[3:])
        return None

    def count_children(self, node_id: str) -> int:
        """返回直接子节点数量。无效 node_id 返回 0。"""
        return len(self.list_children(node_id))

    def has_scan_data(self, managed_root_id: str) -> bool:
        """判断受管理根目录是否已扫描（folder_cache 中有对应记录）。"""
        node = self.get_node(f"mr:{managed_root_id}")
        if node is None:
            return False
        return node.folder_cache_id is not None

    # --- 内部方法 ---

    def _list_children_of_managed_root(self, managed_root_id: str) -> list[TreeNode]:
        """查询受管理根目录的子节点。

        未扫描的 managed_root 返回空列表。
        """
        root = self._managed_root_repo.get_by_id(managed_root_id)
        if root is None:
            return []

        # 查找关联的 folder_cache 根节点
        fc_roots = self._folder_cache_repo.list_by_parent(parent_id=None)
        root_key = root.path_key
        fc_root = None
        for fc in fc_roots:
            if make_path_key(fc.path) == root_key:
                fc_root = fc
                break

        if fc_root is None:
            return []

        # 查询 folder_cache 根节点的子节点
        return self._build_folder_children(fc_root.id, f"mr:{managed_root_id}")

    def _list_children_of_folder_cache(self, folder_cache_id: str) -> list[TreeNode]:
        """查询 folder_cache 节点的子节点。"""
        fc = self._folder_cache_repo.get_by_id(folder_cache_id)
        if fc is None:
            return []
        return self._build_folder_children(fc.id, f"fc:{folder_cache_id}")

    def _build_folder_children(self, parent_folder_id: str, parent_node_id: str) -> list[TreeNode]:
        """构造 folder_cache 子节点列表。"""
        children = self._folder_cache_repo.list_by_parent(parent_id=parent_folder_id)
        nodes: list[TreeNode] = []
        for fc in children:
            display_name = _extract_dirname(fc.path)
            nodes.append(
                TreeNode(
                    node_id=f"fc:{fc.id}",
                    display_name=display_name,
                    real_path=fc.path,
                    category="folder",
                    is_managed_root=False,
                    managed_root_id=None,
                    folder_cache_id=fc.id,
                    parent_id=parent_node_id,
                )
            )
        return nodes

    def _get_managed_root_node(self, managed_root_id: str) -> TreeNode | None:
        """获取受管理根目录节点。"""
        root = self._managed_root_repo.get_by_id(managed_root_id)
        if root is None:
            return None

        # 查找关联的 folder_cache
        fc_roots = self._folder_cache_repo.list_by_parent(parent_id=None)
        root_key = root.path_key
        fc_root = None
        for fc in fc_roots:
            if make_path_key(fc.path) == root_key:
                fc_root = fc
                break

        if fc_root is not None:
            return TreeNode(
                node_id=f"mr:{root.id}",
                display_name=root.display_name or root.real_path,
                real_path=root.real_path,
                category="managed_root",
                is_managed_root=True,
                managed_root_id=root.id,
                folder_cache_id=fc_root.id,
                parent_id=None,
            )
        return TreeNode(
            node_id=f"mr:{root.id}",
            display_name=root.display_name or root.real_path,
            real_path=root.real_path,
            category="unscanned_root",
            is_managed_root=True,
            managed_root_id=root.id,
            folder_cache_id=None,
            parent_id=None,
        )

    def _get_folder_cache_node(self, folder_cache_id: str) -> TreeNode | None:
        """获取 folder_cache 节点。"""
        fc = self._folder_cache_repo.get_by_id(folder_cache_id)
        if fc is None:
            return None

        # 判断是否为根节点（parent_id IS NULL）
        if fc.parent_id is None:
            # 根节点：查找关联的 managed_root
            roots = self._managed_root_repo.list_all()
            fc_key = make_path_key(fc.path)
            for root in roots:
                if root.path_key == fc_key:
                    return TreeNode(
                        node_id=f"mr:{root.id}",
                        display_name=root.display_name or root.real_path,
                        real_path=root.real_path,
                        category="managed_root",
                        is_managed_root=True,
                        managed_root_id=root.id,
                        folder_cache_id=fc.id,
                        parent_id=None,
                    )
            # folder_cache 根节点但无 managed_root（不应发生，容忍处理）
            return TreeNode(
                node_id=f"fc:{fc.id}",
                display_name=_extract_dirname(fc.path),
                real_path=fc.path,
                category="folder",
                is_managed_root=False,
                managed_root_id=None,
                folder_cache_id=fc.id,
                parent_id=None,
            )

        # 普通子节点：查询父 folder_cache 以确定 parent_node_id
        parent_fc = self._folder_cache_repo.get_by_id(fc.parent_id)
        if parent_fc is None:
            # 父节点不存在（数据不一致），容忍处理
            parent_node_id = None
        elif parent_fc.parent_id is None:
            # 父节点是根 folder_cache：查找关联的 managed_root
            parent_node_id = self._find_managed_root_node_id(parent_fc)
        else:
            # 父节点是普通 folder_cache
            parent_node_id = f"fc:{parent_fc.id}"

        return TreeNode(
            node_id=f"fc:{fc.id}",
            display_name=_extract_dirname(fc.path),
            real_path=fc.path,
            category="folder",
            is_managed_root=False,
            managed_root_id=None,
            folder_cache_id=fc.id,
            parent_id=parent_node_id,
        )

    def _find_managed_root_node_id(self, fc_root) -> str:
        """查找 folder_cache 根节点关联的 managed_root，返回 "mr:<id>"。

        若未找到关联的 managed_root，回退返回 "fc:<folder_cache_id>"。
        """
        roots = self._managed_root_repo.list_all()
        fc_key = make_path_key(fc_root.path)
        for root in roots:
            if root.path_key == fc_key:
                return f"mr:{root.id}"
        return f"fc:{fc_root.id}"


def _extract_dirname(path: str) -> str:
    """从路径字符串提取最后一级目录名。

    使用 PurePath.name 以兼容 Windows/POSIX 路径分隔符。
    空路径或根路径返回原字符串。
    """
    from pathlib import PurePath

    name = PurePath(path).name
    return name if name else path
