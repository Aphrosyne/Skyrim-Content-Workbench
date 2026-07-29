"""卡片视图 model（Stage 5 Task 1b）。

轻量代理：委托给 FileListModel，共享同一份数据源（Q6:B 复用 FileListModel）。
两个视图（QTableView + QListView）共用同一份 FileEntry 列表，切换不丢失数据。

Task 1b：双档缓存适配。
- icon_size <= 256 → 查询 256 档缓存
- icon_size > 256 → 查询 512 档缓存
- 缓存命中 → 缩放到 icon_size 显示
- 缓存未命中 → 投递后台生成，同时用低档放大显示（避免空白）

数据角色：
- DisplayRole：entry.name（不含 [内容单元] 标记，Q6:B 决策）
- DecorationRole：按 icon_size 选择档位，返回 QPixmap（已缩放到目标尺寸）
- ToolTipRole：路径 + 内容单元状态（Q6:B 决策，卡片空间有限，标记通过 ToolTip 承载）
- UserRole：返回 FileEntry（与 FileListModel 一致，便于 handler 复用）

数据变更响应：
- FileListModel.refresh() 发射 modelReset 信号 → CardListModel 同步重置
- FileListModel.notify_thumbnail_ready() 发射 dataChanged → CardListModel 转发对应行 dataChanged
- 缩放值变化时由 MainWindow 调用 notify_decoration_changed() 触发全表 DecorationRole 重查
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtGui import QPixmap

from app import ui_constants as ui
from app.file_list_model import FileListModel
from domain.models import FileEntry

logger = logging.getLogger(__name__)

# 档位阈值：icon_size <= 此值用 256 档，否则用 512 档
_SIZE_THRESHOLD = 256

# 缩略图 provider 签名（Task 1b：支持 size 参数）
# (content_unit_id: str, source_path: str, size: int) → QPixmap | None
CardThumbnailProvider = Callable[[str, str, int], QPixmap | None]


def _build_tooltip(entry: FileEntry) -> str:
    """构造卡片 ToolTip：路径 + 内容单元状态（Q6:B）。

    卡片空间有限，名称不显示 [内容单元] 标记，完整信息通过 ToolTip 承载。
    """
    parts: list[str] = [entry.path]
    if entry.content_unit is not None:
        status_text = ui.CARD_TOOLTIP_CONTENT_UNIT_STATUS.format(status=entry.content_unit.status)
        parts.append(status_text)
    return ui.CARD_TOOLTIP_SEPARATOR.join(parts)


def _select_cache_size(icon_size: int) -> int:
    """根据 icon_size 选择缓存档位。

    - icon_size <= 256 → 256 档
    - icon_size > 256 → 512 档
    """
    return 256 if icon_size <= _SIZE_THRESHOLD else 512


class CardListModel(QAbstractListModel):
    """卡片视图 model（Stage 5 Task 1b）。

    使用方式：
        file_list_model = FileListModel()
        card_model = CardListModel()
        card_model.set_source(file_list_model)
        card_model.set_thumbnail_provider(provider)  # Task 1b：独立 provider
        card_model.set_icon_size(256)
        list_view.setModel(card_model)
    """

    def __init__(self, parent=None) -> None:  # noqa: ANN001 (Qt 签名)
        super().__init__(parent)
        self._source: FileListModel | None = None
        self._icon_size: int = ui.ZOOM_SLIDER_DEFAULT
        # Task 1b：独立的 provider，支持 size 参数
        self._thumbnail_provider: CardThumbnailProvider | None = None
        # QPixmap 内存缓存：(unit_id, cache_size) → QPixmap（按 icon_size 缩放后的）
        # 避免 data() 高频调用时重复缩放
        self._pixmap_cache: dict[tuple[str, int], QPixmap | None] = {}

    # --- QAbstractListModel 必需方法 ---

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802 (Qt 命名)
        if parent is None:
            parent = QModelIndex()
        if parent.isValid():
            return 0
        return self._source.rowCount(parent) if self._source is not None else 0

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:  # noqa: N802 (Qt 命名)
        if not index.isValid() or self._source is None:
            return None
        row = index.row()
        entry = self._source.entry_at(row)
        if entry is None:
            return None

        if role == Qt.DisplayRole:
            # Q6:B：卡片名称不含 [内容单元] 标记
            return entry.name
        if role == Qt.ToolTipRole:
            # Q6:B：路径 + 内容单元状态
            return _build_tooltip(entry)
        if role == Qt.UserRole:
            return entry
        if role == Qt.DecorationRole:
            return self._get_decoration(entry)
        return None

    def _get_decoration(self, entry: FileEntry) -> QPixmap | None:
        """获取卡片装饰图（Task 1b：双档缓存适配）。

        - 有封面的内容单元 → 按档位查询缩略图，缩放到 icon_size 返回
        - 无封面或非内容单元 → 返回 None（view 会用 Qt 标准图标占位）
        """
        if entry.content_unit is None or not entry.content_unit.cover_path:
            return None

        unit_id = entry.content_unit.id
        cache_size = _select_cache_size(self._icon_size)
        cache_key = (unit_id, cache_size)

        # 内存缓存命中
        if cache_key in self._pixmap_cache:
            pixmap = self._pixmap_cache[cache_key]
            if pixmap is not None:
                return pixmap
            # None 表示已查过但无缩略图 → 返回 None
            return None

        # 查询指定档位缩略图
        pixmap = self._query_thumbnail(unit_id, entry, cache_size)
        if pixmap is not None:
            # 缩放到 icon_size
            scaled = pixmap.scaled(
                self._icon_size,
                self._icon_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._pixmap_cache[cache_key] = scaled
            return scaled
        # 查询失败/未命中 → 缓存 None 避免重复查询
        self._pixmap_cache[cache_key] = None
        return None

    def _query_thumbnail(self, unit_id: str, entry: FileEntry, cache_size: int) -> QPixmap | None:
        """通过 provider 查询指定档位缩略图。

        Task 1b：provider 签名 (unit_id, source_path, size) → QPixmap | None。
        """
        if self._thumbnail_provider is None:
            return None
        source_path = str(Path(entry.content_unit.path) / entry.content_unit.cover_path)
        return self._thumbnail_provider(unit_id, source_path, cache_size)

    # --- 数据源绑定 ---

    def set_source(self, source: FileListModel) -> None:
        """绑定 FileListModel 作为数据源。

        连接 modelReset 信号，FileListModel.refresh() 后自动同步重置。
        """
        if self._source is not None:
            self._source.modelReset.disconnect(self._on_source_reset)  # type: ignore[call-overload]
            self._source.dataChanged.disconnect(self._on_source_data_changed)  # type: ignore[call-overload]
        self._source = source
        self._source.modelReset.connect(self._on_source_reset)
        self._source.dataChanged.connect(self._on_source_data_changed)
        self._on_source_reset()

    def set_thumbnail_provider(self, provider: CardThumbnailProvider | None) -> None:
        """注入缩略图查询回调（Task 1b：支持 size 参数）。

        provider 签名：(content_unit_id: str, source_path: str, size: int) → QPixmap | None
        - 返回 QPixmap：缓存命中，立即显示
        - 返回 None：缓存未命中，由 provider 内部决定是否投递后台生成

        设为 None 可禁用缩略图功能。
        """
        self._thumbnail_provider = provider
        # 切换 provider 时清空缓存，强制重新查询
        self._pixmap_cache.clear()

    def set_icon_size(self, size: int) -> None:
        """设置卡片图标尺寸，触发全表 DecorationRole 重查。

        缩放滑块变化时调用，让 view 重新查询 DecorationRole 并按新尺寸渲染 pixmap。
        Task 1b：尺寸变化时清空内存缓存（因 icon_size 改变后缩放结果不同）。
        """
        self._icon_size = size
        self._pixmap_cache.clear()
        self.notify_decoration_changed()

    def notify_decoration_changed(self) -> None:
        """通知 view 重新查询所有行的 DecorationRole（缩放/缩略图变化时调用）。"""
        if self.rowCount() == 0:
            return
        top_left = self.index(0, 0)
        bottom_right = self.index(self.rowCount() - 1, 0)
        self.dataChanged.emit(top_left, bottom_right, [Qt.DecorationRole])

    def notify_thumbnail_ready(self, unit_id: str, size: int) -> None:
        """指定档位缩略图生成完成：清除缓存并触发对应行重绘。

        Task 1b：按 (unit_id, size) 精确清除缓存，避免清错档位。
        """
        cache_key = (unit_id, size)
        if cache_key in self._pixmap_cache:
            del self._pixmap_cache[cache_key]
        # 找到对应行
        for row in range(self.rowCount()):
            entry = self._source.entry_at(row) if self._source else None
            if (
                entry is not None
                and entry.content_unit is not None
                and entry.content_unit.id == unit_id
            ):
                idx1 = self.index(row, 0)
                idx2 = self.index(row, 0)
                self.dataChanged.emit(idx1, idx2, [Qt.DecorationRole])
                break

    def _on_source_reset(self) -> None:
        """FileListModel 重置时，CardListModel 同步重置。"""
        self._pixmap_cache.clear()
        self.beginResetModel()
        self.endResetModel()

    def _on_source_data_changed(  # noqa: N802 (Qt 命名)
        self,
        top_left: QModelIndex,
        bottom_right: QModelIndex,
        roles: list[int] | None = None,
    ) -> None:
        """FileListModel dataChanged 转发到 CardListModel 对应行。

        缩略图生成完成后 FileListModel 发射 DecorationRole dataChanged，
        CardListModel 需要转发以触发卡片重绘。
        """
        # FileListModel 是 4 列 TableModel，CardListModel 是单列 ListModel
        # 行号一致，列忽略（CardListModel 只有 1 列）
        card_top_left = self.index(top_left.row(), 0)
        card_bottom_right = self.index(bottom_right.row(), 0)
        if roles is not None:
            self.dataChanged.emit(card_top_left, card_bottom_right, roles)
        else:
            self.dataChanged.emit(card_top_left, card_bottom_right)

    # --- 测试接口 ---

    def entry_at(self, row: int) -> FileEntry | None:
        """返回指定行的 FileEntry（委托给 source，供测试）。"""
        if self._source is None:
            return None
        return self._source.entry_at(row)

    def entry_count(self) -> int:
        """返回行数（供测试）。"""
        return self.rowCount()

    def get_icon_size(self) -> int:
        """返回当前 icon_size（供测试）。"""
        return self._icon_size
