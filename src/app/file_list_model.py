"""文件列表 Qt Model（阶段 3 Task 2 重构为 TableModel）。

数据源为 FileEntry 列表（来自文件系统 + content_unit 表关联）。
内容单元不是可见性门槛——所有文件系统条目均可见。

4 列布局：
- 名称列（COL_NAME=0）：图标 + 内容单元标记 + 名称。
- 类型列（COL_TYPE=1）：文件夹 / 扩展名。
- 大小列（COL_SIZE=2）：字节数格式化；文件夹显示空字符串。
- 修改日期列（COL_MODIFIED=3）：ISO 8601 UTC 字符串。

排序：
- set_sort_key(key, ascending) 在 model 内部重新排序（不依赖 QSortFilterProxyModel）。
- 名称/类型列排序时文件夹优先在前；大小/日期列按值排序，文件夹（None）排到最后。
- 默认排序：文件夹优先 + 名称升序。

Stage 4 Task 4（缩略图）：
- set_thumbnail_provider(provider)：注入缩略图查询回调（unit_id, source_path）→ QPixmap | None。
- DecorationRole 优先级：
  1. 内容单元 + 有 cover_path + provider 返回 QPixmap → 显示封面缩略图
  2. 其他情况 → Qt 标准文件/文件夹图标
- notify_thumbnail_ready(unit_id)：缩略图后台生成完成后调用，触发对应行 dataChanged。
- 缓存 QPixmap（按 unit_id），避免每次 data() 都查询 provider。

数据角色：
- DisplayRole：各列文本。
- DecorationRole：仅名称列返回 QIcon。
- ToolTipRole：名称列返回完整路径。
- UserRole：返回 FileEntry 对象（任意列均可）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QMimeData, QModelIndex, Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QIcon, QPixmap

from app import ui_constants as ui
from app.file_type_icons import file_type_key, icon_for_type
from domain.models import FileEntry

logger = logging.getLogger(__name__)

# 列索引常量
COL_NAME = 0
COL_TYPE = 1
COL_SIZE = 2
COL_MODIFIED = 3
COLUMN_COUNT = 4

# 排序键常量（不入 domain，UI 层局部使用）
SORT_NAME = "name"
SORT_TYPE = "type"
SORT_SIZE = "size"
SORT_MODIFIED = "modified"
# BugFix3（2026-08-04）：下拉框内升降序项的 data 标记（区别于排序字段键，
# 用于 PressSelectComboBox 区分"字段项"与"方向项"）
SORT_DIRECTION_ASC = "sort-asc"
SORT_DIRECTION_DESC = "sort-desc"

# 缩略图 provider 签名：(content_unit_id, source_path) → QPixmap | None
ThumbnailProvider = Callable[[str, str], QPixmap | None]
# 封面图标 provider 签名：(content_unit_id, cover_source_path) → QIcon | None
# （UI合理性5：只读复用现有封面缓存，不产生新缓存）
CoverIconProvider = Callable[[str, str], QIcon | None]


def _display_name(entry: FileEntry) -> str:
    """构造名称列 DisplayRole 文本：纯文件名。

    Stage 5 Task 7 收尾：status 简化为两态（organized / unmarked），
    unmarked 视为无内容单元（不在 UI 显示标记）。
    UI合理性12（2026-08-03）：曾用 -- 文本前缀标记内容单元。
    UI合理性13（2026-08-04）：🔗 徽章改为 delegate 绘制位图（emoji 拼进
    文本会改变行高度量导致 1px 垂直偏移），DisplayRole 保持纯文件名。
    """
    return entry.name


def _type_text(entry: FileEntry) -> str:
    """构造类型列文本：文件夹固定显示"文件夹"，文件显示扩展名（小写，无点）。"""
    if entry.is_dir:
        return ui.COL_TYPE_FOLDER
    suffix = ""
    if "." in entry.name:
        suffix = entry.name.rsplit(".", 1)[-1].lower()
    return suffix if suffix else ui.COL_TYPE_FILE


def _size_text(entry: FileEntry) -> str:
    """构造大小列文本：文件返回带单位的自动缩写；文件夹返回空字符串。

    UI合理性5（2026-08-02）：B / KB / MB / GB / TB（1024 进制，保留 1 位小数，
    去除尾随 0）。排序仍基于 entry.size 原始值，不受显示格式影响。
    """
    if entry.is_dir or entry.size is None:
        return ""
    size = entry.size
    if size < 1024:
        return f"{size} B"
    units = ("KB", "MB", "GB", "TB")
    value = float(size)
    for unit in units:
        value /= 1024.0
        if value < 1024 or unit == units[-1]:
            text = f"{value:.1f}".rstrip("0").rstrip(".")
            return f"{text} {unit}"
    return f"{size} B"


def _modified_text(entry: FileEntry) -> str:
    """构造修改日期列文本：直接返回 modified_at（ISO 8601 UTC）。"""
    return entry.modified_at


def _sort_value_key(entry: FileEntry, sort_key: str) -> tuple:
    """返回纯值排序键（不含文件夹优先标志）。

    用于第一步排序，受 ascending 方向影响。
    文件夹的位置由第二步稳定排序处理，不受 ascending 影响。
    """
    if sort_key == SORT_NAME:
        return (entry.name.lower(), entry.name)
    if sort_key == SORT_TYPE:
        return (_type_text(entry).lower(), entry.name.lower())
    if sort_key == SORT_SIZE:
        size_val = entry.size if entry.size is not None else float("inf")
        return (size_val, entry.name.lower())
    if sort_key == SORT_MODIFIED:
        return (entry.modified_at, entry.name.lower())
    return (entry.name.lower(), entry.name)


class FileListModel(QAbstractTableModel):
    """文件列表 model（4 列 TableModel；`single_column` 模式用于装配面板）。

    使用方式：
        model = FileListModel()
        model.refresh(entries)
        table_view.setModel(model)
        # 列头点击切换排序
        model.set_sort_key(SORT_NAME, ascending=True)

    UX 重构 Task 7 Step 6（TD-M36）：装配面板复用本模型（`single_column=True`），
    替代原 AssemblyListModel——单列模式只显示文件名 + 标准图标（不显示内容单元
    标记 / 封面缩略图 / 剪切态），与装配面板既有视觉行为一致，消除双模型维护。
    """

    def __init__(self, parent=None, *, single_column: bool = False) -> None:
        super().__init__(parent)
        self._single_column = single_column
        self._entries: list[FileEntry] = []
        self._sort_key: str = SORT_NAME
        self._sort_ascending: bool = True
        # Stage 4 Task 4：缩略图 provider + QPixmap 缓存
        self._thumbnail_provider: ThumbnailProvider | None = None
        # unit_id → QPixmap (None 表示不可用)
        self._thumbnail_cache: dict[str, QPixmap | None] = {}
        # UI合理性5：封面图标 provider + QIcon 缓存（列表视图区分是否有封面）
        self._cover_icon_provider: CoverIconProvider | None = None
        self._cover_icon_cache: dict[str, QIcon | None] = {}
        # Stage 5 Task 3b：剪切状态路径集合（用于半透明渲染，Q12=A 50% 透明度）
        self._cut_paths: set[str] = set()

    # --- QAbstractTableModel 必需方法 ---

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802 (Qt 命名)
        if parent is None:
            parent = QModelIndex()
        if parent.isValid():
            return 0
        return len(self._entries)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802 (Qt 命名)
        if parent is None:
            parent = QModelIndex()
        if parent.isValid():
            return 0
        return 1 if self._single_column else COLUMN_COUNT

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:  # noqa: N802 (Qt 命名)
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._entries):
            return None
        col = index.column()
        if col < 0 or col >= self.columnCount():
            return None

        entry = self._entries[row]

        if role == Qt.DisplayRole:
            if self._single_column:
                # 装配面板：纯文件名（与 AssemblyListModel 行为一致）
                return entry.name
            if col == COL_NAME:
                return _display_name(entry)
            if col == COL_TYPE:
                return _type_text(entry)
            if col == COL_SIZE:
                return _size_text(entry)
            if col == COL_MODIFIED:
                return _modified_text(entry)
            return None
        if role == Qt.ToolTipRole and col == COL_NAME:
            return entry.path
        if role == Qt.UserRole:
            return entry
        if role == Qt.DecorationRole and col == COL_NAME:
            return self.icon_for(entry)
        if role == Qt.ForegroundRole:
            # Stage 5 Task 3b：剪切状态半透明渲染（Q12=A 50% 透明度）
            if not self._single_column and entry.path in self._cut_paths:
                return QBrush(QColor(0, 0, 0, 128))
            return None
        return None

    def headerData(  # noqa: N802 (Qt 命名)
        self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole
    ) -> object:
        if role != Qt.DisplayRole:
            return None
        if orientation != Qt.Orientation.Horizontal:
            return None
        if section < 0 or section >= self.columnCount():
            return None
        # Stage 5 Task 2：当前排序列追加 ▲/▼ 方向指示（Q1=A 文本方案）
        header = ui.FILE_LIST_COLUMN_HEADERS[section]
        if section == self._sort_section():
            direction = ui.SORT_ASC_SYMBOL if self._sort_ascending else ui.SORT_DESC_SYMBOL
            return f"{header} {direction}"
        return header

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
        urls: list[QUrl] = []
        seen: set[str] = set()
        for idx in indexes:
            if not idx.isValid():
                continue
            if idx.row() < 0 or idx.row() >= len(self._entries):
                continue
            entry = self._entries[idx.row()]
            if entry.path in seen:
                continue
            seen.add(entry.path)
            urls.append(QUrl.fromLocalFile(entry.path))
        if not urls:
            return None
        mime = QMimeData()
        mime.setUrls(urls)
        return mime

    # --- 刷新 ---

    def refresh(self, entries: list[FileEntry]) -> None:
        """重置列表并应用当前排序。"""
        self.beginResetModel()
        self._entries = list(entries)
        self._apply_sort()
        # 清空缩略图缓存（新列表可能 unit_id 集合不同）
        self._thumbnail_cache.clear()
        # 清空封面图标缓存（封面可能变化）
        self._cover_icon_cache.clear()
        # Stage 5 Task 3b：切换目录后清空剪切高亮（Q8=A：剪贴板状态保留，视觉仅在原目录显示）
        self._cut_paths = set()
        self.endResetModel()

    def set_cut_paths(self, paths: set[str]) -> None:
        """设置剪切状态路径集合，触发 dataChanged 更新渲染。

        Stage 5 Task 3b：剪切后条目半透明显示（Q12=A 50% 透明度）。
        切换目录时 refresh 会清空 cut_paths（Q8=A：视觉仅在原目录显示）。

        Args:
            paths: 处于剪切状态的路径字符串集合。
        """
        self._cut_paths = set(paths)
        if self._entries:
            top_left = self.index(0, 0)
            bottom_right = self.index(len(self._entries) - 1, COLUMN_COUNT - 1)
            self.dataChanged.emit(top_left, bottom_right, [Qt.ForegroundRole])

    def set_sort_key(self, sort_key: str, ascending: bool) -> None:
        """切换排序键与方向，重新对现有条目排序。"""
        if sort_key not in (SORT_NAME, SORT_TYPE, SORT_SIZE, SORT_MODIFIED):
            return
        old_section = self._sort_section()
        self.beginResetModel()
        self._sort_key = sort_key
        self._sort_ascending = ascending
        self._apply_sort()
        self.endResetModel()
        # Stage 5 Task 2：刷新列头方向指示（Q1=A 文本方案）
        new_section = self._sort_section()
        if old_section != new_section and old_section >= 0:
            self.headerDataChanged.emit(old_section, old_section, [Qt.DisplayRole])
        if new_section >= 0:
            self.headerDataChanged.emit(new_section, new_section, [Qt.DisplayRole])

    def current_sort_key(self) -> str:
        """返回当前排序键（供测试）。"""
        return self._sort_key

    def is_sort_ascending(self) -> bool:
        """返回当前是否升序（供测试）。"""
        return self._sort_ascending

    def _sort_section(self) -> int:
        """返回当前排序键对应的列索引（用于 headerData 方向指示）。"""
        return {
            SORT_NAME: COL_NAME,
            SORT_TYPE: COL_TYPE,
            SORT_SIZE: COL_SIZE,
            SORT_MODIFIED: COL_MODIFIED,
        }.get(self._sort_key, COL_NAME)

    def _apply_sort(self) -> None:
        """对 self._entries 应用当前排序。

        两步排序（Python sort 稳定）：
        1. 按值排序（受 ascending 影响）。
        2. 稳定排序调整文件夹位置（不受 ascending 影响）：
           - 名称/类型列：文件夹优先在前。
           - 大小/日期列：文件夹排到最后（size=None 无法参与值比较）。
        """
        # 第一步：按值排序
        self._entries.sort(
            key=lambda e: _sort_value_key(e, self._sort_key),
            reverse=not self._sort_ascending,
        )
        # 第二步：稳定排序调整文件夹位置
        if self._sort_key in (SORT_NAME, SORT_TYPE):
            # 文件夹优先在前
            self._entries.sort(key=lambda e: not e.is_dir)
        else:
            # 大小/日期列：文件夹排到最后
            self._entries.sort(key=lambda e: e.is_dir)

    # --- 测试接口 ---

    def entry_at(self, row: int) -> FileEntry | None:
        """返回指定行的 FileEntry（供测试）。"""
        if row < 0 or row >= len(self._entries):
            return None
        return self._entries[row]

    def entry_count(self) -> int:
        """返回行数（供测试）。"""
        return len(self._entries)

    # --- 图标接口（Stage 5 Task 1：icon_for 公开供 CardListModel 复用） ---

    def icon_for(self, entry: FileEntry) -> QIcon | None:
        """返回条目图标（Stage 5 Task 1b：列表视图改用 Qt 标准 icon）。

        UI合理性5：文件夹类内容单元有封面 → 复用现有封面缓存图（64×64）
        作为图标以区分是否有封面；缓存不存在时不触发新缓存生成。
        UI合理性4（2026-08-04）：非封面场景按文件类型返回 SVG 图标
        （文件夹 / 压缩包 / 图片 / 其他文档，跟随系统主题着色），
        加载失败回退 Qt 标准图标（见 file_type_icons）。

        优先级：
        1. 文件夹内容单元有封面（且缓存可用）→ 封面图标
        2. 其余 → 按类型 SVG 图标（file_type_icons）
        """
        if (
            entry.is_dir
            and entry.content_unit is not None
            and entry.content_unit.cover_path
            and self._cover_icon_provider is not None
        ):
            cover_icon = self._query_cover_icon(entry.content_unit)
            if cover_icon is not None:
                return cover_icon
        return icon_for_type(file_type_key(entry))

    def _query_cover_icon(self, unit) -> QIcon | None:
        """查询并缓存封面图标（缺失缓存 → None，不投递生成任务）。"""
        unit_id = unit.id
        if unit_id in self._cover_icon_cache:
            return self._cover_icon_cache[unit_id]
        source_path = str(Path(unit.path) / unit.cover_path)
        icon = self._cover_icon_provider(unit_id, source_path)  # type: ignore[misc]
        self._cover_icon_cache[unit_id] = icon
        return icon

    # --- Stage 4 Task 4：缩略图接口 ---

    def set_thumbnail_provider(self, provider: ThumbnailProvider | None) -> None:
        """注入缩略图查询回调。

        provider 签名：(content_unit_id: str, source_path: str) → QPixmap | None
        - 返回 QPixmap：缓存命中，立即显示
        - 返回 None：缓存未命中，由 provider 内部决定是否投递后台生成

        设为 None 可禁用缩略图功能（退化为标准图标）。
        """
        self._thumbnail_provider = provider
        # 切换 provider 时清空缓存，强制重新查询
        self._thumbnail_cache.clear()

    def set_cover_icon_provider(self, provider: CoverIconProvider | None) -> None:
        """注入封面图标查询回调（UI合理性5，只读复用现有缓存，不产生新缓存）。"""
        self._cover_icon_provider = provider
        self._cover_icon_cache.clear()

    def notify_thumbnail_ready(self, content_unit_id: str) -> None:
        """缩略图后台生成完成后调用，触发对应行重绘。

        清除该 unit_id 的缓存（下次 data() 调用会重新查询 provider），
        然后发射 dataChanged 信号触发 view 重绘对应行。
        """
        # 清除缓存（让下次 data() 重新查询 provider 获取新生成的缩略图）
        if content_unit_id in self._thumbnail_cache:
            del self._thumbnail_cache[content_unit_id]
        # 找到对应行
        for row, entry in enumerate(self._entries):
            if entry.content_unit is not None and entry.content_unit.id == content_unit_id:
                idx1 = self.index(row, COL_NAME)
                idx2 = self.index(row, COL_NAME)
                self.dataChanged.emit(idx1, idx2, [Qt.DecorationRole])
                break
