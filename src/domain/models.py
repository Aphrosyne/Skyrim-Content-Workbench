"""领域模型。

依据 docs/spec.md §4 定义方向 C 的新实体：
ContentUnit / TagCategory / Tag / OperationHistory / FolderCache / ManagedRoot。

领域模型为纯数据载体，不包含 DB 知识，也不访问文件系统。

时间戳采用 ISO 8601 UTC 字符串（如 '2026-07-07T12:34:56Z'），
由调用方在 application 层生成；模型不自动填充时间。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass
class ContentUnit:
    """内容单元。spec §4.1。

    一个内容单元对应一个真实路径（文件夹或单文件）。
    path 原样存储（可为中文），数据库以 path 列的 UNIQUE 约束去重。
    """

    id: str
    path: str
    created_at: str
    updated_at: str
    title: str | None = None
    content_type: str = "mod"
    source_url: str | None = None
    rating: int | None = None
    cover_path: str | None = None
    status: str = "unorganized"
    notes: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("ContentUnit.id 不能为空")
        if not self.path:
            raise ValueError("ContentUnit.path 不能为空")
        if not self.created_at:
            raise ValueError("ContentUnit.created_at 不能为空")
        if not self.updated_at:
            raise ValueError("ContentUnit.updated_at 不能为空")
        if self.rating is not None and (self.rating < 1 or self.rating > 5):
            raise ValueError("ContentUnit.rating 必须在 1-5 之间")


@dataclass
class TagCategory:
    """标签分类。spec §4.2。"""

    id: str
    name: str
    color_hue: int = 0

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("TagCategory.id 不能为空")
        if not self.name:
            raise ValueError("TagCategory.name 不能为空")
        if self.color_hue < 0 or self.color_hue > 360:
            raise ValueError("TagCategory.color_hue 必须在 0-360 之间")


@dataclass
class Tag:
    """标签。spec §4.3。一个标签只属于一个分类。"""

    id: str
    name: str
    category_id: str

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Tag.id 不能为空")
        if not self.name:
            raise ValueError("Tag.name 不能为空")
        if not self.category_id:
            raise ValueError("Tag.category_id 不能为空")


@dataclass
class OperationHistory:
    """操作历史。spec §4.5。简化版操作记录，类似 PS 历史记录。"""

    id: str
    operation_type: str
    source_path: str
    created_at: str
    target_path: str | None = None
    can_undo: bool = True

    VALID_OPERATION_TYPES: ClassVar[frozenset[str]] = frozenset(
        {"move", "delete", "rename", "new_folder"}
    )

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("OperationHistory.id 不能为空")
        if self.operation_type not in self.VALID_OPERATION_TYPES:
            raise ValueError(
                f"OperationHistory.operation_type 必须是 "
                f"{sorted(self.VALID_OPERATION_TYPES)} 之一，得到：{self.operation_type}"
            )
        if not self.source_path:
            raise ValueError("OperationHistory.source_path 不能为空")
        if not self.created_at:
            raise ValueError("OperationHistory.created_at 不能为空")


@dataclass
class FolderCache:
    """目录树性能缓存。spec §4.7。

    简化版 folder_node，用于加速目录树显示。
    last_scanned_mtime 为 epoch 秒（float），用于增量扫描判断。
    """

    id: str
    path: str
    created_at: str
    parent_id: str | None = None
    last_scanned_mtime: float | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("FolderCache.id 不能为空")
        if not self.path:
            raise ValueError("FolderCache.path 不能为空")
        if not self.created_at:
            raise ValueError("FolderCache.created_at 不能为空")


@dataclass
class ManagedRoot:
    """用户配置的受管理根目录。spec §4.6。schema v2 引入，方向 C 保留。

    real_path 原样存储，path_key 用于比较与唯一约束（A2 决策）。
    本模型不访问文件系统；路径合法性由调用方在 application 层校验。
    """

    id: str
    real_path: str
    path_key: str
    created_at: str
    updated_at: str
    display_name: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("ManagedRoot.id 不能为空")
        if not self.real_path:
            raise ValueError("ManagedRoot.real_path 不能为空")
        if not self.path_key:
            raise ValueError("ManagedRoot.path_key 不能为空")
        if not self.created_at:
            raise ValueError("ManagedRoot.created_at 不能为空")
        if not self.updated_at:
            raise ValueError("ManagedRoot.updated_at 不能为空")


@dataclass
class FileEntry:
    """目录条目（文件或文件夹）+ 可选的内容单元关联。

    用于浏览模式中栏列表（roadmap Task 4 2026-07-13 设计修正）：
    数据源为文件系统，content_unit 表仅作为标记来源。
    内容单元不是可见性门槛——所有文件系统条目均可见可操作。

    name：显示名（文件或文件夹名，可为中文）。
    path：完整路径（原样存储）。
    is_dir：True 为文件夹，False 为文件。
    modified_at：ISO 8601 UTC 字符串（由 service 层从 stat.st_mtime 转换）。
    size：文件大小（字节）；文件夹为 None。
    content_unit：若该路径在 content_unit 表中存在则填充，否则为 None。
    """

    name: str
    path: str
    is_dir: bool
    modified_at: str
    size: int | None = None
    content_unit: ContentUnit | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("FileEntry.name 不能为空")
        if not self.path:
            raise ValueError("FileEntry.path 不能为空")
        if not self.modified_at:
            raise ValueError("FileEntry.modified_at 不能为空")
