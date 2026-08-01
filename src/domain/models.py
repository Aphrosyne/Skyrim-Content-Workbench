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
    """内容单元。spec §4.1（2026-07-18 移除 rating 字段）。

    一个内容单元对应一个真实路径（文件夹或单文件）。
    path 原样存储（可为中文），数据库以 path + path_key 列的 UNIQUE 约束去重
    （path_key 为 make_path_key(path)，DB 层强制路径归一化唯一）。

    v11 schema（Stage 5 Code Review D2/D3）：status 字段重构为 is_marked: bool。
    v13 schema（UX 重构 Task 6）：移除 is_marked 字段，回归纯 DELETE 模式——
    记录存在即已标记，取消标记 = DELETE 记录，无需表达"曾标记但已取消"的状态。
    path_key 为 DB 层列（UNIQUE 约束），Domain 实体不含该字段。
    """

    id: str
    path: str
    created_at: str
    updated_at: str
    title: str | None = None
    content_type: str = "mod"
    source_url: str | None = None
    cover_path: str | None = None
    notes: str | None = None

    # M13：Domain 层取值范围校验（与 OperationHistory.operation_type 校验对齐）
    # content_type 当前仅 'mod'；未来扩展类型时需同步更新此集合
    VALID_CONTENT_TYPES: ClassVar[frozenset[str]] = frozenset({"mod"})

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("ContentUnit.id 不能为空")
        if not self.path:
            raise ValueError("ContentUnit.path 不能为空")
        if not self.created_at:
            raise ValueError("ContentUnit.created_at 不能为空")
        if not self.updated_at:
            raise ValueError("ContentUnit.updated_at 不能为空")
        if self.content_type not in self.VALID_CONTENT_TYPES:
            raise ValueError(
                f"ContentUnit.content_type 必须是 {sorted(self.VALID_CONTENT_TYPES)} 之一，"
                f"得到：{self.content_type}"
            )


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
    """操作历史。spec §4.5。简化版操作记录，类似 PS 历史记录。

    Stage 5 Task 6：
    - 新增 undone_at 字段：标记原操作已被撤销的时间戳（None 表示未撤销）。
    - 新增 operation_type='undo'：撤销记录，source_path 指向被撤销的原 history.id，
      can_undo=False（避免无限循环撤销）。

    Stage 5 Task 3b：
    - 新增 operation_type='copy'：复制操作记录，source_path=原路径，target_path=新路径，
      can_undo=False（复制不可撤销，避免撤销=删除副本的语义模糊，Q4=A）。
    """

    id: str
    operation_type: str
    source_path: str
    created_at: str
    target_path: str | None = None
    can_undo: bool = True
    # Stage 5 Task 6：原操作被撤销的时间戳（None 表示未撤销）
    undone_at: str | None = None

    VALID_OPERATION_TYPES: ClassVar[frozenset[str]] = frozenset(
        {"move", "delete", "rename", "new_folder", "undo", "copy"}
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
        # TD-H1：operation_type 与 target_path 一致性校验
        # move/rename/new_folder/copy 必须有 target_path；delete/undo 不允许 target_path
        if self.operation_type in ("move", "rename", "new_folder", "copy"):
            if not self.target_path:
                raise ValueError(
                    f"OperationHistory.operation_type={self.operation_type} 要求 target_path 非空"
                )
        elif self.operation_type in ("delete", "undo") and self.target_path is not None:
            raise ValueError(
                f"OperationHistory.operation_type={self.operation_type} 要求 target_path 为 None"
            )
        # TD-L19：delete 不可撤销，can_undo 必须为 False
        if self.operation_type == "delete" and self.can_undo:
            raise ValueError(
                "OperationHistory.operation_type=delete 不可撤销，can_undo 必须为 False"
            )
        # Stage 5 Task 3b：copy 不可撤销（Q4=A，避免撤销=删除副本的语义模糊）
        if self.operation_type == "copy" and self.can_undo:
            raise ValueError("OperationHistory.operation_type=copy 不可撤销，can_undo 必须为 False")
        # Stage 5 Task 6：undo 记录本身不可再撤销（避免无限循环）
        if self.operation_type == "undo" and self.can_undo:
            raise ValueError(
                "OperationHistory.operation_type=undo 不可再次撤销，can_undo 必须为 False"
            )
        # undo 记录的 undone_at 必须为 None（undo 记录本身不会被撤销）
        if self.operation_type == "undo" and self.undone_at is not None:
            raise ValueError("OperationHistory.operation_type=undo 的 undone_at 必须为 None")


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
class ThumbnailCache:
    """缩略图缓存记录。spec §4.8 / §9。

    Task 1a：支持多尺寸缓存（256/512 双档），复合主键 (content_unit_id, size)。
    一个内容单元可有多条缓存记录（不同档位）。
    缓存有效性由调用方按 (source_size_bytes, source_modified_at, 文件存在性) 判断。

    status 取值：
    - 'ok'：生成成功
    - 'missing'：源图文件不存在
    - 'corrupt'：Pillow 无法解码（文件损坏）
    - 'unsupported'：不支持的图片格式
    - 'error'：其他异常
    """

    content_unit_id: str
    size: int  # 缓存档位（64 旧档/256/512）
    source_size_bytes: int
    source_modified_at: str  # ISO 8601 UTC
    cache_filename: str  # 相对 thumbnails 目录的文件名（如 "{unit_id}_{size}.webp"）
    status: str
    generated_at: str  # ISO 8601 UTC
    error_message: str | None = None

    # M13：与 DB CHECK 约束对齐，Domain 层同步校验以早期暴露非法取值
    VALID_STATUSES: ClassVar[frozenset[str]] = frozenset(
        {"ok", "missing", "corrupt", "unsupported", "error"}
    )

    def __post_init__(self) -> None:
        if not self.content_unit_id:
            raise ValueError("ThumbnailCache.content_unit_id 不能为空")
        if self.status not in self.VALID_STATUSES:
            raise ValueError(
                f"ThumbnailCache.status 必须是 {sorted(self.VALID_STATUSES)} 之一，"
                f"得到：{self.status}"
            )

    def is_ok(self) -> bool:
        """返回缓存是否可用（status == 'ok'）。"""
        return self.status == "ok"


@dataclass
class FileEntry:
    """目录条目（文件或文件夹）+ 可选的内容单元关联。

    用于中栏文件列表（roadmap Task 4 2026-07-13 设计修正）：
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


@dataclass
class SearchResult:
    """搜索结果项（Stage 5 Task 7）。

    spec §8：搜索范围为内容单元标题 + 标签名 + 备注。
    一个内容单元匹配多个字段时只返回一条记录，matched_field 取最高优先级
    （标题 > 标签 > 备注，Q7=B）。

    - unit_id：内容单元 ID
    - title：内容单元标题（可能为 None，UI 显示时回退到 path）
    - path：内容单元路径
    - content_type：内容单元类型
    - matched_field：命中的字段名（'title' / 'tag' / 'notes'），按优先级取
    - tags：聚合的标签名列表（可能为空列表）
    """

    unit_id: str
    title: str | None
    path: str
    content_type: str
    matched_field: str
    tags: list[str]

    def __post_init__(self) -> None:
        if not self.unit_id:
            raise ValueError("SearchResult.unit_id 不能为空")
        if not self.path:
            raise ValueError("SearchResult.path 不能为空")
        if self.matched_field not in ("title", "tag", "notes"):
            raise ValueError(
                f"SearchResult.matched_field 必须是 'title' / 'tag' / 'notes' 之一，"
                f"得到：{self.matched_field}"
            )
