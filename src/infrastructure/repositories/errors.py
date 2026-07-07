"""Repository 层错误类型。

所有 DB 异常在此包装为面向用户的错误，并保留技术日志（见 AGENTS.md 开发方式）。
"""

from __future__ import annotations


class RepositoryError(Exception):
    """Repository 层基础错误。"""


class NotFoundError(RepositoryError):
    """实体不存在。"""


class ConstraintViolationError(RepositoryError):
    """约束违反：唯一约束、外键、CHECK 等。"""
