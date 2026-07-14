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
