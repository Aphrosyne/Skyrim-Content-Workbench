"""卡片视图 model（Stage 5 Task 1b）。

轻量代理：委托给 FileListModel，共享同一份数据源（Q6:B 复用 FileListModel）。
两个视图（QTableView + QListView）共用同一份 FileEntry 列表，切换不丢失数据。

Task 1b 修正：直接加载原图，不走缓存 provider。
Task 2 验收修复：
- 有封面 → QPixmap 加载原图，居中裁剪为 icon_size × icon_size 方形（统一外框）
- 无封面或非内容单元 → 返回 Qt 标准图标（委托 FileListModel）
- 内存缓存 unit_id → QPixmap（方形裁剪后的），避免 data() 高频调用重复加载
- DisplayRole 长文件名 elide 省略号（避免撑大卡片宽度）

数据角色：
- DisplayRole：entry.name（elide 截断，Q6:B 不含 [内容单元] 标记）
- DecorationRole：方形裁剪后的 QPixmap（icon_size × icon_size）
- ToolTipRole：路径 + 内容单元状态（Q6:B 决策，完整信息通过 ToolTip 承载）
- UserRole：返回 FileEntry（与 FileListModel 一致，便于 handler 复用）

数据变更响应：
- FileListModel.refresh() 发射 modelReset 信号 → CardListModel 同步重置
- 缩放值变化时由 MainWindow 调用 notify_decoration_changed() 触发全表 DecorationRole 重查
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPixmap

from app import ui_constants as ui
from app.file_list_model import FileListModel
from domain.models import FileEntry

logger = logging.getLogger(__name__)


def _build_tooltip(entry: FileEntry) -> str:
    """构造卡片 ToolTip：路径 + 内容单元状态（Q6:B）。

    卡片空间有限，名称不显示 [内容单元] 标记，完整信息通过 ToolTip 承载。
    """
    parts: list[str] = [entry.path]
    if entry.content_unit is not None:
        status_text = ui.CARD_TOOLTIP_CONTENT_UNIT_STATUS.format(status=entry.content_unit.status)
        parts.append(status_text)
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
        # QPixmap 内存缓存：unit_id → QPixmap（按 icon_size 缩放后的）
        # 避免 data() 高频调用时重复加载原图
        self._pixmap_cache: dict[str, QPixmap | None] = {}

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
        """获取卡片装饰图（Task 2 验收修复：方形裁剪统一外框）。

        - 有封面的内容单元 → 加载原图，居中裁剪为 icon_size × icon_size 方形
          （Q1=A 居中裁剪，类似 Instagram 缩略图；横竖图统一外框）
        - 无封面或非内容单元 → 回退到 Qt 标准文件夹/文件图标（委托 FileListModel）
        """
        if entry.content_unit is None or not entry.content_unit.cover_path:
            # 无封面 → 委托 source 返回 Qt 标准图标
            if self._source is not None:
                return self._source.icon_for(entry)
            return None

        unit_id = entry.content_unit.id

        # 内存缓存命中
        if unit_id in self._pixmap_cache:
            pixmap = self._pixmap_cache[unit_id]
            if pixmap is not None:
                return pixmap
            # None 表示已查过但无封面图 → 回退标准图标
            if self._source is not None:
                return self._source.icon_for(entry)
            return None

        # 加载原图
        pixmap = self._load_original_pixmap(entry)
        if pixmap is not None:
            # Task 2 验收修复：方形裁剪（居中 crop），统一外框
            cropped = self._crop_to_square(pixmap)
            self._pixmap_cache[unit_id] = cropped
            return cropped
        # 加载失败 → 缓存 None 避免重复加载，回退标准图标
        self._pixmap_cache[unit_id] = None
        if self._source is not None:
            return self._source.icon_for(entry)
        return None

    def _crop_to_square(self, pixmap: QPixmap) -> QPixmap:
        """将 pixmap 居中裁剪为 icon_size × icon_size 方形（Q1=A）。

        步骤：
        1. 先按短边等比放大填满 icon_size（KeepAspectRatioByExpanding）
        2. 居中裁剪多余部分，输出严格方形 pixmap
        """
        scaled = pixmap.scaled(
            self._icon_size,
            self._icon_size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        # 居中裁剪到严格 icon_size × icon_size
        x = max(0, (scaled.width() - self._icon_size) // 2)
        y = max(0, (scaled.height() - self._icon_size) // 2)
        return scaled.copy(x, y, self._icon_size, self._icon_size)

    def _load_original_pixmap(self, entry: FileEntry) -> QPixmap | None:
        """加载原图（Task 1b 修正：不走缓存，直接读文件）。

        原图过大时由 QPixmap 自身处理解码，实测 4K 图无明显卡顿。
        若未来需要限制解码尺寸，可在此处加 QPixmap.load + 尺寸提示。
        """
        unit = entry.content_unit
        if unit is None or not unit.cover_path:
            return None
        full_path = Path(unit.path) / unit.cover_path
        pixmap = QPixmap(str(full_path))
        if pixmap.isNull():
            return None
        return pixmap

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

    def notify_thumbnail_ready(self, content_unit_id: str, size: int) -> None:
        """缩略图生成完成回调（保留接口兼容，当前不走缓存，空实现）。

        Task 1b 修正：不再查询缓存，此方法保留仅为兼容 MainWindow 信号连接。
        """
        # 当前直接加载原图，无需处理缓存回调
        return

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
