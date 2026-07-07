"""文件扩展名分类工具。

仅供扫描器内部使用，用于识别图片与压缩包扩展名。
分类结果不持久化到 FileAsset 表（schema 无对应列），
仅作为扫描时的辅助元数据，供未来阶段（如缩略图服务）决策。

依据 docs/spec.md §3：至少识别文件、文件夹、图片、常见压缩包扩展名。
依据 docs/spec.md §4：不解析压缩包内部内容。
"""

from __future__ import annotations

from enum import Enum


class AssetHint(Enum):
    """扩展名给出的文件类型提示。

    注意：此枚举与 FileAsset.asset_kind（file/folder）不同。
    AssetHint 仅用于扫描器内部；FileAsset.asset_kind 持久化到数据库。
    """

    IMAGE = "image"
    ARCHIVE = "archive"
    OTHER = "other"


# 图片扩展名集合（小写，含点）。
# 依据 spec §10：至少支持 JPG、PNG、WEBP；此处补充常见格式。
IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
        ".ico",
        ".tga",
        ".dds",
    }
)

# 压缩包扩展名集合（小写，含点）。
# 依据 spec §3：压缩包为待处理素材之一。
# 包含分卷压缩的序号扩展名（.001, .r01 等）以支持常见 Skyrim 汉化包格式。
ARCHIVE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".7z",
        ".zip",
        ".rar",
        ".001",
        ".r00",
        ".r01",
        ".r02",
        ".r03",
        ".r04",
        ".r05",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".tgz",
        ".tbz2",
        ".txz",
    }
)


def get_extension(filename: str) -> str:
    """返回小写扩展名（含点）；无扩展名返回空字符串。

    对 '.tar.gz' 这类多扩展名仅返回最后一段（'.gz'）。
    不假设文件名格式（AGENTS 规则 6）。
    特例：仅含点号或末尾点号的文件名（如 '.'、'..'、'noext.'）返回空字符串，
    避免将点号本身误识别为扩展名。
    """
    # 使用字符串分割而非 Path.suffix，避免对纯文件名构造 Path 的开销
    if not filename or "." not in filename:
        return ""
    dot_idx = filename.rfind(".")
    # 末尾点号（如 'noext.'）或仅含点号（如 '.'、'..'）视为无扩展名
    if dot_idx == len(filename) - 1:
        return ""
    # 前导点号的隐藏文件（如 '.hidden'）视为无扩展名
    if dot_idx == 0:
        return ""
    ext = filename[dot_idx:]
    return ext.lower()


def classify_by_extension(filename: str) -> AssetHint:
    """根据扩展名返回文件类型提示。"""
    ext = get_extension(filename)
    if ext in IMAGE_EXTENSIONS:
        return AssetHint.IMAGE
    if ext in ARCHIVE_EXTENSIONS:
        return AssetHint.ARCHIVE
    return AssetHint.OTHER
