"""Application 层错误类型。

Application 层负责协调 UI 与领域逻辑，错误在此包装为面向用户的中文消息。
"""

from __future__ import annotations


class ApplicationError(Exception):
    """Application 层基础错误。"""


class ManagedRootNotFoundError(ApplicationError):
    """ManagedRoot 不存在。"""


class DuplicateManagedRootError(ApplicationError):
    """同一 path_key 的受管理根目录已存在。"""


class InvalidRootPathError(ApplicationError):
    """受管理根目录路径非法：不存在或非目录。"""


class FileOperationError(ApplicationError):
    """文件操作基础错误。"""


class ConflictError(FileOperationError):
    """目标路径已存在（不覆盖，AGENTS 规则 2）。"""


class CrossDriveError(FileOperationError):
    """跨盘移动不支持。"""


class SelfSubdirectoryError(FileOperationError):
    """不能移动到自身子目录。"""


class SourceNotFoundError(FileOperationError):
    """源文件或目录不存在。"""


class SourceNotInStagingError(ApplicationError):
    """创建 Mod 组失败：源文件不在暂存区下。

    D1 重命名：原 ModGroupSourceNotInStagingError（UI 术语保留 "Mod 组"）。
    """


class InvalidContentUnitNameError(ApplicationError):
    """创建 Mod 组失败：名称无效（空或仅含空白）。

    D1 重命名：原 InvalidModGroupNameError（UI 术语保留 "Mod 组"）。
    """


class ContentUnitNotFoundError(ApplicationError):
    """ContentUnit 不存在。"""


class InvalidContentUnitPathError(ApplicationError):
    """ContentUnit 路径非法：不存在或不可访问。"""


class ContentUnitCascadeError(ApplicationError):
    """子项 ContentUnit 级联取消失败（spec §5.4 不变量：父子不可同时标记）。

    Stage 4.5 H2 修复：原实现静默吞异常导致父标记继续创建，破坏不变量。
    现在任一子项删除失败时抛出本异常，中止父标记创建。

    Attributes:
        failures: 失败子项的 (unit_id, error_message) 列表。
    """

    def __init__(self, message: str, failures: list[tuple[str, str]] | None = None) -> None:
        super().__init__(message)
        self.failures = failures or []


# === 标签系统（Stage 4 Task 1） ===


class TagCategoryNotFoundError(ApplicationError):
    """标签分类不存在。"""


class TagNotFoundError(ApplicationError):
    """标签不存在。"""


class DuplicateTagCategoryNameError(ApplicationError):
    """同名标签分类已存在。"""


class DuplicateTagNameError(ApplicationError):
    """该分类下同名标签已存在。"""


class InvalidTagJsonError(ApplicationError):
    """标签 JSON 文件格式不合法：缺少必需字段、schema_version 不支持等。"""


# === 元数据编辑（Stage 4 Task 2） ===


class InvalidMetadataError(ApplicationError):
    """元数据字段校验失败：title 过长、source_url 格式非法等。"""


class CoverImageNotFoundError(ApplicationError):
    """封面图片在内容单元目录下不存在或不可访问。"""


# === 操作历史撤销（Stage 5 Task 6） ===


class UndoError(ApplicationError):
    """撤销操作基础错误。"""


class UndoNotAllowedError(UndoError):
    """该操作不允许撤销（can_undo=False 或 operation_type='undo'/'delete'）。"""


class UndoSafetyError(UndoError):
    """撤销安全检查失败：源文件不存在 / 已被外部修改 / 目标已存在。

    Attributes:
        reason: 具体失败原因（面向用户的中文消息）。
    """

    def __init__(self, message: str, reason: str = "") -> None:
        super().__init__(message)
        self.reason = reason or message


class UndoAlreadyUndoneError(UndoError):
    """该操作已被撤销（undone_at 非空），不可重复撤销。"""


# === 剪贴板（Stage 5 Task 3b） ===


class ClipboardError(ApplicationError):
    """剪贴板操作基础错误。"""


class EmptyClipboardError(ClipboardError):
    """剪贴板为空时执行粘贴操作。"""


class SearchError(ApplicationError):
    """搜索失败（Stage 5 Task 7）。"""
