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


class ScanError(ApplicationError):
    """扫描过程中发生的可向用户展示的错误（非单个目录的扫描错误，而是整体性错误）。"""


class StagingAreaNotFoundError(ApplicationError):
    """StagingArea 不存在。"""


class DuplicateStagingAreaError(ApplicationError):
    """同一 path_key 的暂存区已存在。"""


class StagingAreaNestingError(ApplicationError):
    """暂存区不允许嵌套：祖先目录或子目录已是暂存区。"""


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


class ModGroupSourceNotInStagingError(ApplicationError):
    """创建 Mod 组失败：源文件不在暂存区下。"""


class InvalidModGroupNameError(ApplicationError):
    """创建 Mod 组失败：Mod 组名称无效（空或仅含空白）。"""


class ContentUnitNotFoundError(ApplicationError):
    """ContentUnit 不存在。"""


class InvalidContentUnitPathError(ApplicationError):
    """ContentUnit 路径非法：不存在或不可访问。"""


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
