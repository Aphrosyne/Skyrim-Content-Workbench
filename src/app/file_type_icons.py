"""文件类型 SVG 图标（UI合理性4，2026-08-04）。

使用 Nieobie/game-icon-pack（CC0-1.0，见
``assets/third-party/game-icon-pack-v1.4-svg-zh/NOTICE.md``）9-媒体 分类的 4 个图标
（无间距变体，运行时副本位于 ``src/app/resources/icons/``，ASCII 短名）：

- folder.svg（文件夹）→ 文件夹
- archive.svg（文件）→ 压缩包
- image.svg（图像）→ 图片文件
- document.svg（文档）→ 其他文档

图标源 SVG 为 ``fill="currentColor"`` 单色路径；加载时把填充色替换为
``ui.FILE_TYPE_ICON_COLORS`` 中按类型配置的颜色（验收反馈 2026-08-04：
文件夹黄 / 压缩包浅绿 / 图片浅蓝 / 其他文档白，便于快速区分；颜色集中定义在
``ui_constants.py``，可手动调整）。所有尺寸按需用 QSvgRenderer 矢量渲染
（列表 16-36 / 卡片占位 96-256），并按 (类型, 颜色) 缓存 QIcon。
任一环节失败回退 Qt 标准图标，不影响现有功能。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QStyle

from app import ui_constants as ui
from domain.models import FileEntry
from infrastructure.file_classify import ARCHIVE_EXTENSIONS, get_extension

# 类型键（同时是 resources/icons/ 下的 SVG 文件名）
ICON_FOLDER = "folder"
ICON_ARCHIVE = "archive"
ICON_IMAGE = "image"
ICON_DOCUMENT = "document"

# 图片扩展名集合（小写，含点）。
# 与 application.content_service._COVER_IMAGE_EXTENSIONS 保持一致（技术债：
# 暂不合并，见 workflow-test-issues.md UI合理性4 归档记录）。
_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".ico"}
)

# 运行时图标目录（通过 __file__ 定位，不依赖 cwd）
_ICONS_DIR = Path(__file__).parent / "resources" / "icons"

# 矢量渲染尺寸：覆盖列表缩放（16-36）与卡片占位图标（96-256）全部档位，
# 中间加 64 作为过渡，避免任意档位需要放大。
_RENDER_SIZES: tuple[int, ...] = (
    16,
    20,
    24,
    28,
    32,
    36,
    40,
    48,
    64,
    96,
    128,
    160,
    192,
    224,
    256,
)

# QIcon 缓存：(type_key, 颜色 hex) → QIcon；颜色按类型固定，配置变化换键重建
_icon_cache: dict[tuple[str, str], QIcon] = {}
# 标准图标兜底缓存：type_key → QIcon
_fallback_cache: dict[str, QIcon] = {}
# 运行时颜色覆盖（「视图 → 文件类型图标颜色…」保存后注入；None = 用默认值）
_color_override: dict[str, str] | None = None


def file_type_key(entry: FileEntry) -> str:
    """返回条目图标分类键（folder / archive / image / document）。"""
    if entry.is_dir:
        return ICON_FOLDER
    ext = get_extension(entry.name)
    if ext in ARCHIVE_EXTENSIONS:
        return ICON_ARCHIVE
    if ext in _IMAGE_EXTENSIONS:
        return ICON_IMAGE
    return ICON_DOCUMENT


def icon_for_type(type_key: str) -> QIcon:
    """返回指定类型的 QIcon（按类型颜色着色 + 缓存，失败回退标准图标）。"""
    app = QApplication.instance()
    if app is None:
        return _fallback_icon(type_key)
    source = _color_override if _color_override is not None else ui.FILE_TYPE_ICON_COLORS
    color_hex = source.get(type_key)
    if color_hex is None:
        # 未配置颜色（正常情况下不会发生）→ 回退系统主题文字色
        color_hex = app.palette().color(QPalette.ColorRole.Text).name()
    cache_key = (type_key, color_hex)
    cached = _icon_cache.get(cache_key)
    if cached is not None:
        return cached
    icon = _build_icon(type_key, color_hex)
    if icon is None:
        icon = _fallback_icon(type_key)
    _icon_cache[cache_key] = icon
    return icon


def set_type_colors(colors: dict[str, str]) -> None:
    """设置运行时类型颜色覆盖并清空图标缓存（颜色配置保存后调用）。"""
    global _color_override
    _color_override = dict(colors)
    _icon_cache.clear()


def reset_type_colors() -> None:
    """清除类型颜色覆盖，恢复 ui_constants 默认值（供测试/恢复默认）。"""
    global _color_override
    _color_override = None
    _icon_cache.clear()


def _build_icon(type_key: str, color_hex: str) -> QIcon | None:
    """从 SVG 构建主题色 QIcon；文件缺失/渲染失败返回 None（调用方兜底）。"""
    svg_path = _ICONS_DIR / f"{type_key}.svg"
    if not svg_path.is_file():
        return None
    try:
        svg_text = svg_path.read_text(encoding="utf-8")
        svg_data = svg_text.replace('fill="currentColor"', f'fill="{color_hex}"').replace(
            "fill:currentColor", f"fill:{color_hex}"
        )
        renderer = QSvgRenderer()
        if not renderer.load(svg_data.encode("utf-8")):
            return None
        icon = QIcon()
        for size in _RENDER_SIZES:
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(painter, QRectF(0, 0, size, size))
            painter.end()
            icon.addPixmap(pixmap)
        return icon
    except Exception:  # noqa: BLE001 - 图标加载失败不阻塞 UI，回退标准图标
        return None


def _fallback_icon(type_key: str) -> QIcon:
    """回退 Qt 标准图标（文件夹 → SP_DirIcon，其余 → SP_FileIcon）。"""
    cached = _fallback_cache.get(type_key)
    if cached is not None:
        return cached
    app = QApplication.instance()
    if app is None:
        return QIcon()
    style = app.style()
    if type_key == ICON_FOLDER:
        icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
    else:
        icon = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
    _fallback_cache[type_key] = icon
    return icon
