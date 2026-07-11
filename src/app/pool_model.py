"""未归类素材池与 ModItem 列表的 Qt 模型。

阶段 2 Task 3 实现。依据 docs/architecture.md §2 UI 分层规则。

职责：
- 将 ModAssemblyService 返回的 FileAsset / ModItem 包装为 QAbstractListModel。
- 只读展示，不直接调用 repository 写操作。
- 不访问文件系统；不写数据库；不调用 FileOperationService。

线程边界：UI 主线程构造与访问，使用主线程 SQLite 连接。
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtGui import QIcon

from application.mod_assembly_service import ModAssemblyService
from domain.models import AssetKind, FileAsset, FileRole, ModItem

logger = logging.getLogger(__name__)

# 数据角色
_ASSET_ROLE = Qt.UserRole  # FileAsset 对象
_MOD_ITEM_ROLE = Qt.UserRole  # ModItem 对象（复用 UserRole，两个 model 互不重叠）

# 角色中文显示名（UI 文案集中在 ui 层）
ROLE_DISPLAY_NAMES: dict[FileRole, str] = {
    FileRole.MAIN_MOD: "本体",
    FileRole.TRANSLATION: "汉化",
    FileRole.PREVIEW: "预览图",
    FileRole.README: "说明",
    FileRole.OPTIONAL_FILE: "可选文件",
    FileRole.UNKNOWN: "未知",
}

# 角色下拉顺序（QComboBox 用）
ROLE_ORDER: list[FileRole] = [
    FileRole.MAIN_MOD,
    FileRole.TRANSLATION,
    FileRole.PREVIEW,
    FileRole.README,
    FileRole.OPTIONAL_FILE,
    FileRole.UNKNOWN,
]


class UnassociatedPoolModel(QAbstractListModel):
    """未归类素材池模型。

    展示 mod_item_id 为 None 的 FileAsset。支持多选。
    refresh() 重新加载；关联成功后调用 refresh() 素材从池中消失。
    """

    def __init__(self, service: ModAssemblyService, parent: Any = None) -> None:
        super().__init__(parent)
        self._service = service
        self._assets: list[FileAsset] = []

    def refresh(self) -> None:
        """重新加载未关联素材。"""
        self.beginResetModel()
        try:
            self._assets = self._service.list_unassociated_assets()
        except Exception:  # noqa: BLE001 - model 边界不能崩溃
            logger.exception("加载未关联素材失败")
            self._assets = []
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        if parent.isValid():
            return 0
        return len(self._assets)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:  # noqa: A003
        if not index.isValid():
            return None
        row = index.row()
        if not 0 <= row < len(self._assets):
            return None
        asset = self._assets[row]
        if role == Qt.DisplayRole:
            return self._format_display(asset)
        if role == Qt.ToolTipRole:
            kind = "文件夹" if asset.asset_kind == AssetKind.FOLDER else "文件"
            return f"{kind}\n{asset.real_path}"
        if role == _ASSET_ROLE:
            return asset
        return None

    def asset_at(self, row: int) -> FileAsset | None:
        """返回指定行的 FileAsset；越界返回 None。"""
        if 0 <= row < len(self._assets):
            return self._assets[row]
        return None

    def asset_id_at(self, row: int) -> str | None:
        """返回指定行的 asset_id；越界返回 None。"""
        asset = self.asset_at(row)
        return asset.id if asset else None

    def asset_count(self) -> int:
        """返回当前素材数（供测试）。"""
        return len(self._assets)

    @staticmethod
    def _format_display(asset: FileAsset) -> str:
        """格式化素材池显示文本：文件名、类型、完整路径。"""
        kind_mark = "📁" if asset.asset_kind == AssetKind.FOLDER else "📄"
        kind_text = "文件夹" if asset.asset_kind == AssetKind.FOLDER else "文件"
        return f"{kind_mark} {asset.filename}  ({kind_text})  {asset.real_path}"


class ModItemListModel(QAbstractListModel):
    """ModItem 列表模型。

    展示全部 ModItem。refresh() 重新加载。
    支持 cover 图标（Qt.DecorationRole）和成员数显示（DisplayRole）。
    """

    def __init__(self, service: ModAssemblyService, parent: Any = None) -> None:
        super().__init__(parent)
        self._service = service
        self._items: list[ModItem] = []
        self._member_counts: dict[str, int] = {}
        self._cover_icons: dict[str, QIcon] = {}

    def refresh(self) -> None:
        """重新加载 ModItem 列表。"""
        self.beginResetModel()
        try:
            self._items = self._service.list_mod_items()
            self._member_counts = {}
            for item in self._items:
                try:
                    members = self._service.get_members(item.id)
                    self._member_counts[item.id] = len(members)
                except Exception:  # noqa: BLE001
                    self._member_counts[item.id] = 0
        except Exception:  # noqa: BLE001 - model 边界不能崩溃
            logger.exception("加载 ModItem 列表失败")
            self._items = []
            self._member_counts = {}
        self._cover_icons = {}
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        if parent.isValid():
            return 0
        return len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:  # noqa: A003
        if not index.isValid():
            return None
        row = index.row()
        if not 0 <= row < len(self._items):
            return None
        item = self._items[row]
        if role == Qt.DisplayRole:
            name = item.display_name or "（未命名）"
            count = self._member_counts.get(item.id, 0)
            return f"{name}  ({count} 个成员)"
        if role == Qt.ToolTipRole:
            desc = item.description or "（无说明）"
            return desc
        if role == Qt.DecorationRole:
            return self._cover_icons.get(item.id)
        if role == _MOD_ITEM_ROLE:
            return item
        return None

    def set_cover_icon(self, mod_item_id: str, icon: QIcon | None) -> None:
        """设置 ModItem 的封面图标，并通知 view 刷新。

        icon 为 None 时清除图标。
        """
        row = self._find_row(mod_item_id)
        if row is None:
            return
        if icon is None:
            self._cover_icons.pop(mod_item_id, None)
        else:
            self._cover_icons[mod_item_id] = icon
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [Qt.DecorationRole])

    def _find_row(self, mod_item_id: str) -> int | None:
        for i, item in enumerate(self._items):
            if item.id == mod_item_id:
                return i
        return None

    def mod_item_at(self, row: int) -> ModItem | None:
        """返回指定行的 ModItem；越界返回 None。"""
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def mod_item_id_at(self, row: int) -> str | None:
        """返回指定行的 mod_item_id；越界返回 None。"""
        item = self.mod_item_at(row)
        return item.id if item else None

    def item_count(self) -> int:
        """返回当前 ModItem 数（供测试）。"""
        return len(self._items)
