"""Qt 目录树 model（重构版）。

采用 Qt 推荐的内部节点对象 + 对象引用作为 internalPointer 的标准实现。

核心设计：
- _Node 内部类持有 TreeNode、父 _Node 引用、子 _Node 列表、loaded 标记、
  row_in_parent 行号。所有状态集中在 _Node 对象内，消除多处缓存不一致风险。
- internalPointer 存储 _Node 对象引用（非字符串 node_id），parent() 可 O(1)
  返回父 index，无需反查 service 或线性扫描。
- fetchMore 直接使用 View 传入的 parent（其 internalPointer 即 _Node 对象），
  自然满足 Qt C++ 层 persistent index 机制对 index 对象身份的要求。
- 公开接口与旧版保持一致（node_at / node_id_at / root_node_count / refresh），
  调用方（main_window）无需修改。

参考：
- Qt 官方示例 Simple Tree Model：internalPointer 存储节点对象。
- QStandardItemModel：节点持有 parent 引用与 children 列表。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt

from application.folder_tree_service import FolderTreeService, TreeNode

logger = logging.getLogger(__name__)


class _Node:
    """目录树内部节点。

    持有 TreeNode 数据、父节点引用、子节点列表、加载状态与在父中的行号。
    所有树结构状态集中在 _Node 对象内，避免分散缓存导致不一致。
    """

    __slots__ = ("tree_node", "parent", "children", "loaded", "row_in_parent")

    def __init__(self, tree_node: TreeNode, parent: _Node | None) -> None:
        self.tree_node: TreeNode = tree_node
        self.parent: _Node | None = parent
        self.children: list[_Node] = []
        self.loaded: bool = False
        self.row_in_parent: int = 0


class FolderTreeModel(QAbstractItemModel):
    """目录树 model。

    使用方式：
        model = FolderTreeModel(folder_tree_service)
        model.refresh()
        tree_view.setModel(model)
    """

    def __init__(self, service: FolderTreeService, parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._root_nodes: list[_Node] = []

    # --- QAbstractItemModel 必需方法 ---

    def index(self, row: int, column: int, parent: QModelIndex | None = None) -> QModelIndex:
        """返回 (row, column) 处的子节点 index。"""
        if parent is None:
            parent = QModelIndex()
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        parent_node = self._node_at_index(parent)
        children = self._children_of(parent_node)
        if row < 0 or row >= len(children):
            return QModelIndex()

        return self.createIndex(row, 0, children[row])

    def parent(self, index: QModelIndex) -> QModelIndex:  # noqa: N802 (Qt 命名)
        """返回 index 的父节点 index。O(1)。

        通过 _Node.parent 引用直接获取父节点，通过 row_in_parent 直接构造
        父 index，无需反查 service 或线性扫描。
        """
        node = self._node_at_index(index)
        if node is None or node.parent is None:
            return QModelIndex()
        # 父节点的 row 即其在祖父中的位置，存储在 node.parent.row_in_parent
        return self.createIndex(node.parent.row_in_parent, 0, node.parent)

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802 (Qt 命名)
        """返回 parent 的子节点数。"""
        if parent is None:
            parent = QModelIndex()
        if parent.column() > 0:
            return 0
        node = self._node_at_index(parent)
        return len(self._children_of(node))

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802 (Qt 命名)
        return 1

    def hasChildren(self, parent: QModelIndex | None = None) -> bool:  # noqa: N802 (Qt 命名)
        """返回 parent 是否有子节点。

        惰性加载关键：未加载的节点返回 True，使 QTreeView 显示展开按钮，
        用户点击展开时触发 fetchMore。加载后根据实际子节点数判断，
        无子节点时 View 自动移除展开按钮。
        """
        if parent is None:
            parent = QModelIndex()
        if not parent.isValid():
            return len(self._root_nodes) > 0

        node = self._node_at_index(parent)
        if node is None:
            return False
        if not node.loaded:
            return True
        return len(node.children) > 0

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:  # noqa: N802 (Qt 命名)
        """返回 index 处的数据。"""
        node = self._node_at_index(index)
        if node is None:
            return None
        tn = node.tree_node

        if role == Qt.DisplayRole:
            name = tn.display_name
            if tn.category == "unscanned_root":
                name = f"{name}（未扫描）"
            return name
        if role == Qt.ToolTipRole:
            return tn.real_path
        if role == Qt.UserRole:
            return tn.node_id
        return None

    # --- 惰性加载 ---

    def canFetchMore(self, parent: QModelIndex) -> bool:  # noqa: N802 (Qt 命名)
        """判断 parent 是否还可以 fetchMore 子节点。"""
        node = self._node_at_index(parent)
        if node is None:
            return False
        return not node.loaded

    def fetchMore(self, parent: QModelIndex) -> None:  # noqa: N802 (Qt 命名)
        """惰性加载 parent 的子节点。

        直接使用 View 传入的 parent（其 internalPointer 即 _Node 对象），
        不需要重新创建或查找 index。beginInsertRows 接收的 parent 与 View
        持有的是同一对象，满足 Qt C++ 层 persistent index 机制要求。
        """
        node = self._node_at_index(parent)
        if node is None or node.loaded:
            return

        try:
            children_tn = self._service.list_children(node.tree_node.node_id)
        except Exception:  # noqa: BLE001 - model 边界需捕获所有异常
            logger.exception("加载目录树子节点失败：node_id=%s", node.tree_node.node_id)
            children_tn = []

        # 构造 _Node 子节点并挂到父节点上
        for child_tn in children_tn:
            child = _Node(child_tn, parent=node)
            child.row_in_parent = len(node.children)
            node.children.append(child)
        node.loaded = True

        if not children_tn:
            return

        # 必须先更新 _Node 状态再 beginInsertRows，
        # 因为 beginInsertRows 会同步触发 View 查询 rowCount（此时应返回新数量）
        self.beginInsertRows(parent, 0, len(children_tn) - 1)
        self.endInsertRows()

    # --- 刷新 ---

    def refresh(self) -> None:
        """重新加载根节点列表，重置所有缓存。"""
        self.beginResetModel()
        try:
            root_tns = self._service.list_root_nodes()
        except Exception:  # noqa: BLE001 - model 边界需捕获所有异常
            logger.exception("加载目录树根节点失败")
            root_tns = []
        self._root_nodes = []
        for i, tn in enumerate(root_tns):
            node = _Node(tn, parent=None)
            node.row_in_parent = i
            self._root_nodes.append(node)
        self.endResetModel()

    # --- 测试接口 ---

    def node_at(self, index: QModelIndex) -> TreeNode | None:
        """返回 index 处的 TreeNode（供测试）。"""
        node = self._node_at_index(index)
        return node.tree_node if node is not None else None

    def node_id_at(self, index: QModelIndex) -> str | None:
        """返回 index 处的 node_id（供测试）。"""
        node = self._node_at_index(index)
        return node.tree_node.node_id if node is not None else None

    def root_node_count(self) -> int:
        """返回根节点数量（供测试）。"""
        return len(self._root_nodes)

    # --- 内部方法 ---

    def _node_at_index(self, index: QModelIndex) -> _Node | None:
        """从 QModelIndex 提取 _Node 对象。

        无效 index 返回 None（对应 model 根，调用方通过 _children_of(None)
        获取顶层节点列表）。internalPointer 非 _Node 类型时也返回 None，
        防御 PySide6 在某些调用路径下传入非预期对象。
        """
        if not index.isValid():
            return None
        ptr = index.internalPointer()
        if not isinstance(ptr, _Node):
            return None
        return ptr

    def _children_of(self, node: _Node | None) -> list[_Node]:
        """返回 node 的子 _Node 列表。

        node=None 返回顶层节点列表。
        未加载的节点返回空列表（避免 rowCount 触发递归加载）。
        """
        if node is None:
            return self._root_nodes
        if not node.loaded:
            return []
        return node.children
