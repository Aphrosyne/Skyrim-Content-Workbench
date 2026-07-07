"""领域模型。

依据 docs/spec.md §6 定义 ModItem、FileAsset、FolderNode、OperationLog。
领域模型为纯数据载体，不包含 DB 知识，也不访问文件系统。

字段对应 spec §6.1-§6.4。待确认字段（ModItem.status、FileAsset.batch_id）
按 docs/open-questions.md Q1/Q2 的兼容性约束不引入。

时间戳采用 ISO 8601 UTC 字符串（如 '2026-07-07T12:34:56Z'），
由调用方在 application 层生成；模型不自动填充时间。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar


class AssetKind(Enum):
    """FileAsset 的物理类型。"""

    FILE = "file"
    FOLDER = "folder"


class FileRole(Enum):
    """FileAsset 在 Mod 条目中的角色。"""

    MAIN_MOD = "main_mod"
    TRANSLATION = "translation"
    PREVIEW = "preview"
    README = "readme"
    OPTIONAL_FILE = "optional_file"
    UNKNOWN = "unknown"


class OperationStatus(Enum):
    """OperationLog 的状态。spec §6.4。"""

    PLANNED = "planned"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    FAILED = "failed"
    UNDONE = "undone"


class ConflictPolicy(Enum):
    """冲突策略。B3 决策：阶段 1 仅 ASK。"""

    ASK = "ask"


class OperationType(Enum):
    """操作类型。

    spec §6.4 未枚举完整值集；代码层定义 MOVE 与 UNDO。
    DB 不加 CHECK 约束以避免限制未来扩展。
    待确认：完整值集（见 docs/open-questions.md C16，Task 5 决策）。
    """

    MOVE = "move"
    UNDO = "undo"


@dataclass
class ModItem:
    """逻辑上的一个 Mod 条目，可包含多个真实文件。spec §6.1。"""

    id: str
    created_at: str
    updated_at: str
    display_name: str | None = None
    description: str | None = None
    source_url: str | None = None
    category_folder_id: str | None = None
    tags: set[str] = field(default_factory=set)
    cover_asset_id: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("ModItem.id 不能为空")
        if not self.created_at:
            raise ValueError("ModItem.created_at 不能为空")
        if not self.updated_at:
            raise ValueError("ModItem.updated_at 不能为空")
        if not isinstance(self.tags, set):
            raise TypeError("ModItem.tags 必须是 set[str]")


@dataclass
class FileAsset:
    """一个真实文件或文件夹。spec §6.2。

    real_path 原样存储，path_key 用于比较与唯一约束（A2 决策）。
    本模型不访问实际文件系统；size_bytes、modified_at 由调用方提供。
    """

    id: str
    real_path: str
    path_key: str
    filename: str
    asset_kind: AssetKind
    role: FileRole
    size_bytes: int
    modified_at: str
    imported_at: str
    extension: str = ""
    mod_item_id: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("FileAsset.id 不能为空")
        if not self.real_path:
            raise ValueError("FileAsset.real_path 不能为空")
        if not self.path_key:
            raise ValueError("FileAsset.path_key 不能为空")
        if not self.filename:
            raise ValueError("FileAsset.filename 不能为空")
        if not isinstance(self.asset_kind, AssetKind):
            raise TypeError("FileAsset.asset_kind 必须是 AssetKind")
        if not isinstance(self.role, FileRole):
            raise TypeError("FileAsset.role 必须是 FileRole")
        if self.size_bytes < 0:
            raise ValueError("FileAsset.size_bytes 不能为负")
        if not self.modified_at:
            raise ValueError("FileAsset.modified_at 不能为空")
        if not self.imported_at:
            raise ValueError("FileAsset.imported_at 不能为空")


@dataclass
class FolderNode:
    """一个受管理的真实目录节点。spec §6.3。

    parent_id 为 None 表示受管理根目录。
    is_managed_root=True 表示用户配置的扫描根。
    """

    id: str
    real_path: str
    path_key: str
    created_at: str
    updated_at: str
    parent_id: str | None = None
    display_name: str | None = None
    is_managed_root: bool = False

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("FolderNode.id 不能为空")
        if not self.real_path:
            raise ValueError("FolderNode.real_path 不能为空")
        if not self.path_key:
            raise ValueError("FolderNode.path_key 不能为空")
        if not self.created_at:
            raise ValueError("FolderNode.created_at 不能为空")
        if not self.updated_at:
            raise ValueError("FolderNode.updated_at 不能为空")


@dataclass
class OperationLog:
    """所有会影响真实文件的操作记录。spec §6.4。

    undo_payload 为 JSON 字符串；其内部结构由 Task 5 定义（Q14）。
    本模型不校验 undo_payload 内容。
    """

    id: str
    operation_type: OperationType
    status: OperationStatus
    conflict_policy: ConflictPolicy
    created_at: str
    affected_asset_ids: list[str] = field(default_factory=list)
    source_paths: list[str] = field(default_factory=list)
    target_paths: list[str] = field(default_factory=list)
    completed_at: str | None = None
    undo_payload: str | None = None
    error_message: str | None = None

    # 合法状态值集合，供 Repository 反序列化时校验
    VALID_STATUSES: ClassVar[frozenset[str]] = frozenset(s.value for s in OperationStatus)
    VALID_CONFLICT_POLICIES: ClassVar[frozenset[str]] = frozenset(p.value for p in ConflictPolicy)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("OperationLog.id 不能为空")
        if not isinstance(self.operation_type, OperationType):
            raise TypeError("OperationLog.operation_type 必须是 OperationType")
        if not isinstance(self.status, OperationStatus):
            raise TypeError("OperationLog.status 必须是 OperationStatus")
        if not isinstance(self.conflict_policy, ConflictPolicy):
            raise TypeError("OperationLog.conflict_policy 必须是 ConflictPolicy")
        if not self.created_at:
            raise ValueError("OperationLog.created_at 不能为空")
        if not isinstance(self.affected_asset_ids, list):
            raise TypeError("OperationLog.affected_asset_ids 必须是 list[str]")
        if not isinstance(self.source_paths, list):
            raise TypeError("OperationLog.source_paths 必须是 list[str]")
        if not isinstance(self.target_paths, list):
            raise TypeError("OperationLog.target_paths 必须是 list[str]")


@dataclass
class ManagedRoot:
    """用户配置的受管理根目录。spec §6.5。schema v2 引入。

    与 FolderNode 的区别：ManagedRoot 保存用户配置，独立于扫描结果；
    FolderNode 表示扫描得到的目录树节点，is_managed_root 标识扫描时的根。
    移除 ManagedRoot 配置不自动清理对应 FolderNode 记录。

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
