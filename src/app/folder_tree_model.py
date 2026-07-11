"""目录树 QAbstractItemModel。

依据 docs/architecture.md §2.1 model/view 边界。阶段 2 Task 2 实现。

职责：
- 将 FolderTreeService 的 TreeNode 包装为 Qt 树模型。
- 惰性加载子节点：仅在 view 请求时（rowCount/canFetchMore/fetchMore）查询数据库。
- 不访问文件系统；不写数据库；不调用 FileOperationService。

节点内部 ID 使用 TreeNode.node_id（"mr:<id>" / "fn:<id>"），
通过 QAbstractItemModel 的 internalPointer 在 index 与 node 间往返。

线程边界：本 model 在 UI 主线程构造与访问；FolderTreeService 使用的 SQLite
连接必须由调用方保证在主线程使用（与 ManagedRootService 共享主线程连接）。
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt

from application.folder_tree_service import FolderTreeService, TreeNode

logger = logging.getLogger(__name__)

# TreeNode.node_id 存储 roles
_NODE_ID_ROLE = Qt.UserRole  # TreeNode.node_id
_NODE_ROLE = Qt.UserRole + 1  # TreeNode 对象（详情面板用）


class FolderTreeModel(QAbstractItemModel):
    """受管理目录树模型。

    使用方式：
        model = FolderTreeModel(tree_service)
        model.refresh()
        tree_view.setModel(model)
    """

    def __init__(self, tree_service: FolderTreeService, parent: Any = None) -> None:
        super().__init__(parent)
        self._service = tree_service
        # 根节点列表（顶层 TreeNode）
        self._root_nodes: list[TreeNode] = []
        # node_id -> 子节点列表缓存（惰性加载）
        self._children_cache: dict[str, list[TreeNode]] = {}
        # node_id -> 是否已加载子节点
        self._loaded: set[str] = set()

    def refresh(self) -> None:
        """重新加载顶层节点并清空缓存。

        扫描完成、根目录变更后调用。会发出 beginResetModel/endResetModel。
        """
        self.beginResetModel()
        try:
            self._root_nodes = self._service.list_root_nodes()
            self._children_cache.clear()
            self._loaded.clear()
        except Exception:  # noqa: BLE001 - model 边界不能崩溃
            logger.exception("加载目录树顶层节点失败")
            self._root_nodes = []
            self._children_cache.clear()
            self._loaded.clear()
        self.endResetModel()

    def _node_id(self, index: QModelIndex) -> str | None:
        """从 index 提取 node_id；无效 index 返回 None。"""
        if not index.isValid():
            return None
        node_id = index.internalPointer()
        return node_id  # type: ignore[no-any-return]

    def _node_for_index(self, index: QModelIndex) -> TreeNode | None:
        """返回 index 对应的 TreeNode；无效返回 None。"""
        if not index.isValid():
            return None
        node_id = index.internalPointer()
        # 在根节点列表中查找
        for root in self._root_nodes:
            if root.node_id == node_id:
                return root
        # 在缓存中查找
        for children in self._children_cache.values():
            for child in children:
                if child.node_id == node_id:
                    return child
        return None

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:  # noqa: B008 (Qt API 约定)
        """返回指定行列父节点的 index。"""
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        if not parent.isValid():
            # 顶层节点
            if 0 <= row < len(self._root_nodes):
                node_id = self._root_nodes[row].node_id
                return self.createIndex(row, column, node_id)
            return QModelIndex()

        parent_node_id = parent.internalPointer()
        children = self._children_cache.get(parent_node_id, [])
        if 0 <= row < len(children):
            node_id = children[row].node_id
            return self.createIndex(row, column, node_id)
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:  # noqa: A003 (Qt 命名)
        """返回 index 的父 index；顶层节点返回无效 index。"""
        if not index.isValid():
            return QModelIndex()

        node_id = index.internalPointer()
        # 顶层节点无父
        for _i, root in enumerate(self._root_nodes):
            if root.node_id == node_id:
                return QModelIndex()

        # 查找该节点的父节点
        target_node = self._node_for_index(index)
        if target_node is None or target_node.parent_id is None:
            return QModelIndex()

        parent_id = target_node.parent_id
        # 父节点在根列表中
        for i, root in enumerate(self._root_nodes):
            if root.node_id == parent_id:
                return self.createIndex(i, 0, root.node_id)
        # 父节点在某缓存列表中
        for _parent_id, children in self._children_cache.items():
            for i, child in enumerate(children):
                if child.node_id == parent_id:
                    return self.createIndex(i, 0, parent_id)
        return QModelIndex()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008 (Qt 命名/API 约定)
        """返回 parent 下的行数。"""
        if not parent.isValid():
            return len(self._root_nodes)

        parent_node_id = parent.internalPointer()
        # 确保已加载
        if parent_node_id not in self._loaded:
            self._fetch(parent_node_id)
        return len(self._children_cache.get(parent_node_id, []))

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008 (Qt 命名/API 约定)
        return 1

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:  # noqa: A003 (Qt 命名)
        """返回 index 对应数据。"""
        if not index.isValid():
            return None

        node = self._node_for_index(index)
        if node is None:
            return None

        if role == Qt.DisplayRole:
            name = node.display_name
            if node.category == "unscanned_root":
                return f"{name}（未扫描）"
            return name
        if role == Qt.ToolTipRole:
            return node.real_path
        if role == Qt.DecorationRole:
            # 返回 None，由 view 默认图标处理；未来可按 category 返回不同图标
            return None
        if role == _NODE_ID_ROLE:
            return node.node_id
        if role == _NODE_ROLE:
            return node
        return None

    def canFetchMore(self, parent: QModelIndex) -> bool:  # noqa: N802 (Qt 命名)
        """是否还有未加载的子节点。"""
        if not parent.isValid():
            return False
        parent_node_id = parent.internalPointer()
        return parent_node_id not in self._loaded

    def fetchMore(self, parent: QModelIndex) -> None:  # noqa: N802 (Qt 命名)
        """加载 parent 的子节点。"""
        if not parent.isValid():
            return
        parent_node_id = parent.internalPointer()
        if parent_node_id in self._loaded:
            return
        self._fetch(parent_node_id)

    def _fetch(self, parent_node_id: str) -> None:
        """实际加载子节点并发出 rowsInserted 信号。

        重入保护：调用方（rowCount / fetchMore）可能在 beginInsertRows
        同步触发 view 查询时再次进入本方法，因此开头必须检查 _loaded。
        数据写入与 _loaded 标记必须在 beginInsertRows 之前完成，
        避免 view 在 rowsAboutToBeInserted 信号中查询 rowCount 时重入。
        """
        if parent_node_id in self._loaded:
            return

        try:
            children = self._service.list_children(parent_node_id)
        except Exception:  # noqa: BLE001 - model 边界不能崩溃
            logger.exception("加载子节点失败：%s", parent_node_id)
            children = []

        # 先更新缓存与 _loaded 标记，再发信号，
        # 避免 beginInsertRows 同步触发 view 查询 rowCount 时重入 _fetch。
        self._children_cache[parent_node_id] = children
        self._loaded.add(parent_node_id)

        parent_index = self._find_index_by_node_id(parent_node_id)
        # 空子节点不发 rowsInserted 信号（endInsertRows 要求 first<=last）
        if not parent_index.isValid() or not children:
            return

        self.beginInsertRows(parent_index, 0, len(children) - 1)
        self.endInsertRows()

    def _find_index_by_node_id(self, node_id: str) -> QModelIndex:
        """在已加载节点中查找指定 node_id 的 index。"""
        for i, root in enumerate(self._root_nodes):
            if root.node_id == node_id:
                return self.createIndex(i, 0, root.node_id)
        for _parent_id, children in self._children_cache.items():
            for i, child in enumerate(children):
                if child.node_id == node_id:
                    return self.createIndex(i, 0, child.node_id)
        return QModelIndex()

    def node_id_at(self, index: QModelIndex) -> str | None:
        """返回 index 对应的 node_id（供测试与外部使用）。"""
        if not index.isValid():
            return None
        return index.internalPointer()

    def node_at(self, index: QModelIndex) -> TreeNode | None:
        """返回 index 对应的 TreeNode（供详情面板使用）。"""
        return self._node_for_index(index)

    def root_node_count(self) -> int:
        """返回顶层节点数（供测试）。"""
        return len(self._root_nodes)
