"""Application 层错误类型。

Application 层负责协调 UI 与领域逻辑，错误在此包装为面向用户的中文消息。
"""

from __future__ import annotations


class ApplicationError(Exception):
    """Application 层基础错误。"""


class ModItemNotFoundError(ApplicationError):
    """ModItem 不存在。"""


class FileAssetNotFoundError(ApplicationError):
    """FileAsset 不存在。"""


class MemberLimitError(ApplicationError):
    """成员角色数量超限。

    阶段 1 最小约束：MAIN_MOD 与 README 各最多 1 个。
    见 docs/open-questions.md Q19。
    """


class DuplicateMemberError(ApplicationError):
    """同一 FileAsset 已关联到同一 ModItem。"""
