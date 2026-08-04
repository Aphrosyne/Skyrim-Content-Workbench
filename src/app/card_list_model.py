"""卡片视图 model（Stage 5 Task 1b + UI合理性16）。

轻量代理：委托给 FileListModel，共享同一份数据源（Q6:B 复用 FileListModel）。
两个视图（QTableView + QListView）共用同一份 FileEntry 列表，切换不丢失数据。

UI合理性16（2026-08-03）：启用 256px 图片缓存机制，消除多内容下原图全尺寸
解码导致的卡顿。
- 有封面 → 查询 256 档缓存缩略图（provider 注入），缩放到 icon_size 显示；
  缓存缩略图为方形居中裁剪（与 Task 2 验收视觉一致）
- 未命中 → 固定尺寸占位图标（icon_size × icon_size 透明底 + 居中标准图标），
  后台生成完成后 notify_thumbnail_ready 刷新——占位图与缩略图占地一致，
  避免首次批量生成缓存时布局抖动
- 无封面或非内容单元 → 同样返回固定尺寸占位图标（网格布局稳定）
- 内存缓存 (unit_id, size) → QPixmap，避免 data() 高频调用重复查询
- DisplayRole 长文件名 elide 省略号（避免撑大卡片宽度）

数据角色：
- DisplayRole：entry.name（elide 截断，Q6:B 不含 -- 标记）
- DecorationRole：方形裁剪后的 QPixmap（icon_size × icon_size）
- ToolTipRole：路径 + 内容单元状态（Q6:B 决策，完整信息通过 ToolTip 承载）
- UserRole：返回 FileEntry（与 FileListModel 一致，便于 handler 复用）

数据变更响应：
- FileListModel.refresh() 发射 modelReset 信号 → CardListModel 同步重置
- 缩放值变化时由 MainWindow 调用 notify_decoration_changed() 触发全表 DecorationRole 重查
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QMimeData, QModelIndex, Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPixmap

from app import ui_constants as ui
from app.file_list_model import FileListModel
from domain.models import FileEntry

logger = logging.getLogger(__name__)

# 缩略图缓存档位（UI合理性16：256px；缩放滑块最大档即 256，纯降采样足够）
_THUMBNAIL_CACHE_SIZE = 256

# 缩略图 provider 签名：(content_unit_id, source_path, size) → QPixmap | None
CardThumbnailProvider = Callable[[str, str, int], QPixmap | None]


def _build_tooltip(entry: FileEntry) -> str:
    """构造卡片 ToolTip：路径 + 内容单元标记。

    Stage 5 Task 7 收尾：status 简化为两态（organized / unmarked），
    unmarked 视为无内容单元（不显示标记），故仅显示固定"内容单元"文案。
    """
    parts: list[str] = [entry.path]
    if entry.content_unit is not None:
        parts.append(ui.CARD_TOOLTIP_CONTENT_UNIT)
    return ui.CARD_TOOLTIP_SEPARATOR.join(parts)


class CardListModel(QAbstractListModel):
    """卡片视图 model（Stage 5 Task 1b）。

    使用方式：
        file_list_model = FileListModel()
        card_model = CardListModel()
        card_model.set_source(file_list_model)
        card_model.set_icon_size(160)
        list_view.setModel(card_model)
    """

    def __init__(self, parent=None) -> None:  # noqa: ANN001 (Qt 签名)
        super().__init__(parent)
        self._source: FileListModel | None = None
        self._icon_size: int = ui.ZOOM_SLIDER_DEFAULT
        # UI合理性16：缩略图 provider（缓存命中同步返回，未命中投递后台生成）
        self._thumbnail_provider: CardThumbnailProvider | None = None
        # QPixmap 内存缓存：(unit_id, size) → QPixmap（按 icon_size 缩放后的）
        # 避免 data() 高频调用时重复查询/缩放
        self._pixmap_cache: dict[tuple[str, int], QPixmap | None] = {}
        # 占位图标缓存：is_dir → QPixmap（icon_size × icon_size）
        # 占位图与缩略图占地一致，保持网格布局稳定
        self._placeholder_cache: dict[bool, QPixmap] = {}

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
            # Q6:B：卡片名称不含 -- 标记
            # Task 2 验收修复：长文件名 elide 省略号，避免撑大卡片宽度
            return self._elide_name(entry.name)
        if role == Qt.ToolTipRole:
            # Q6:B：路径 + 内容单元状态
            return _build_tooltip(entry)
        if role == Qt.UserRole:
            return entry
        if role == Qt.DecorationRole:
            return self._get_decoration(entry)
        if role == Qt.ForegroundRole:
            # Stage 5 Task 3b：剪切状态半透明渲染（委托 FileListModel 的 cut_paths）
            if self._source is not None and entry.path in self._source._cut_paths:  # noqa: SLF001
                return QBrush(QColor(0, 0, 0, 128))
            return None
        return None

    def _elide_name(self, name: str) -> str:
        """长文件名 elide 省略号，限制最大显示宽度 = icon_size - padding。

        避免 QListView IconMode 下长文件名换行撑宽卡片，破坏网格布局。
        """
        # 使用固定 font metrics 计算 elide 宽度
        from PySide6.QtGui import QFont, QFontMetrics

        # 文本宽度 = icon_size - 左右 padding
        text_width = max(20, self._icon_size - ui.CARD_TEXT_PADDING_H)
        metrics = QFontMetrics(QFont())
        return metrics.elidedText(name, Qt.TextElideMode.ElideRight, text_width)

    def _get_decoration(self, entry: FileEntry) -> QPixmap | QIcon | None:
        """获取卡片装饰图（UI合理性16：256 档缓存 + 固定尺寸占位）。"""
        if entry.content_unit is None or not entry.content_unit.cover_path:
            return self._get_placeholder(entry)
        if self._thumbnail_provider is None:
            # 未注入 provider（未接线）→ 退化占位图标
            return self._get_placeholder(entry)

        unit_id = entry.content_unit.id
        cache_key = (unit_id, _THUMBNAIL_CACHE_SIZE)

        # 内存缓存命中
        if cache_key in self._pixmap_cache:
            pixmap = self._pixmap_cache[cache_key]
            if pixmap is not None:
                return pixmap
            # None = 已查询但未命中 → 占位图标
            return self._get_placeholder(entry)

        pixmap = self._query_thumbnail(unit_id, entry, _THUMBNAIL_CACHE_SIZE)
        if pixmap is not None:
            # 缓存为方形，直接缩放到 icon_size（缩放档 ≤ 256，纯降采样）
            scaled = pixmap.scaled(
                self._icon_size,
                self._icon_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._pixmap_cache[cache_key] = scaled
            return scaled
        self._pixmap_cache[cache_key] = None
        return self._get_placeholder(entry)

    def _get_placeholder(self, entry: FileEntry) -> QPixmap:
        """返回固定尺寸占位图标（icon_size × icon_size 透明底 + 居中标准图标）。

        UI合理性16：未生成缩略图时占位图与缩略图占地一致，保证网格布局稳定。
        """
        is_dir = entry.is_dir
        if is_dir in self._placeholder_cache:
            return self._placeholder_cache[is_dir]
        pixmap = QPixmap(self._icon_size, self._icon_size)
        pixmap.fill(Qt.GlobalColor.transparent)
        if self._source is not None:
            icon = self._source.icon_for(entry)
            if icon is not None:
                painter = QPainter(pixmap)
                icon.paint(
                    painter,
                    pixmap.rect(),
                    Qt.AlignmentFlag.AlignCenter,
                    QIcon.Mode.Normal,
                    QIcon.State.Off,
                )
                painter.end()
        self._placeholder_cache[is_dir] = pixmap
        return pixmap

    def _query_thumbnail(self, unit_id: str, entry: FileEntry, size: int) -> QPixmap | None:
        """通过 provider 查询指定档位缩略图。"""
        if self._thumbnail_provider is None or entry.content_unit is None:
            return None
        source_path = str(Path(entry.content_unit.path) / entry.content_unit.cover_path)
        return self._thumbnail_provider(unit_id, source_path, size)

    # --- 拖拽支持（UX 重构 Phase 1 Task 4）---

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:  # noqa: N802 (Qt 命名)
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        )

    def mimeTypes(self) -> list[str]:  # noqa: N802 (Qt 命名)
        return ["text/uri-list"]

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData | None:  # noqa: N802 (Qt 命名)
        if self._source is None:
            return None
        urls: list[QUrl] = []
        seen: set[str] = set()
        for idx in indexes:
            if not idx.isValid():
                continue
            entry = self._source.entry_at(idx.row())
            if entry is None or entry.path in seen:
                continue
            seen.add(entry.path)
            urls.append(QUrl.fromLocalFile(entry.path))
        if not urls:
            return None
        mime = QMimeData()
        mime.setUrls(urls)
        return mime

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

    def set_icon_size(self, size: int) -> None:
        """设置卡片图标尺寸，触发全表 DecorationRole 重查。

        缩放滑块变化时调用，让 view 重新查询 DecorationRole 并按新尺寸渲染 pixmap。
        尺寸变化时清空内存缓存（缩放结果不同）+ 占位图标（尺寸随 icon_size）。
        """
        self._icon_size = size
        self._pixmap_cache.clear()
        self._placeholder_cache.clear()
        self.notify_decoration_changed()

    def notify_decoration_changed(self) -> None:
        """通知 view 重新查询所有行的 DecorationRole（缩放/缩略图变化时调用）。"""
        if self.rowCount() == 0:
            return
        top_left = self.index(0, 0)
        bottom_right = self.index(self.rowCount() - 1, 0)
        self.dataChanged.emit(top_left, bottom_right, [Qt.DecorationRole])

    def notify_thumbnail_ready(self, content_unit_id: str, size: int) -> None:
        """缩略图生成完成回调：清除对应档位缓存并触发对应行重绘。

        清除 (unit_id, size) 内存缓存，下次 data() 重新查询 provider 获取
        新生成的缩略图。
        """
        cache_key = (content_unit_id, size)
        if cache_key in self._pixmap_cache:
            del self._pixmap_cache[cache_key]
        if self._source is None:
            return
        for row in range(self._source.rowCount()):
            entry = self._source.entry_at(row)
            if entry is None or entry.content_unit is None:
                continue
            if entry.content_unit.id == content_unit_id:
                idx = self.index(row, 0)
                self.dataChanged.emit(idx, idx, [Qt.DecorationRole])
                break

    def invalidate_icons(self) -> None:
        """清除占位图标缓存并触发全表 DecorationRole 重查。

        文件类型图标颜色变化（UI合理性4 二期）后调用：占位图是从旧 QIcon
        渲染的缓存位图，必须清除后才会用新颜色重建。
        """
        self._placeholder_cache.clear()
        self.notify_decoration_changed()

    def set_thumbnail_provider(self, provider: CardThumbnailProvider | None) -> None:
        """注入缩略图查询回调。

        provider 签名：(content_unit_id: str, source_path: str, size: int) → QPixmap | None
        - 返回 QPixmap：缓存命中，立即显示
        - 返回 None：缓存未命中，由 provider 内部决定是否投递后台生成；
          本模型先显示固定尺寸占位图标，生成完成后 notify_thumbnail_ready 刷新

        设为 None 可禁用缩略图功能（退化为占位标准图标）。
        """
        self._thumbnail_provider = provider
        self._pixmap_cache.clear()
        self.notify_decoration_changed()

    def _on_source_reset(self) -> None:
        """FileListModel 重置时，CardListModel 同步重置。"""
        self._pixmap_cache.clear()
        self._placeholder_cache.clear()
        self.beginResetModel()
        self.endResetModel()

    def _on_source_data_changed(  # noqa: N802 (Qt 命名)
        self,
        top_left: QModelIndex,
        bottom_right: QModelIndex,
        roles: list[int] | None = None,
    ) -> None:
        """FileListModel dataChanged 转发到 CardListModel 对应行。"""
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
