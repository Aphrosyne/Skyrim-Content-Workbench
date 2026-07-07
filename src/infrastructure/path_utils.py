r"""路径工具。

A2 决策：原样存储 real_path，另存 path_key 用于路径比较与唯一约束。
path_key = os.path.normcase(os.path.normpath(str(path)))。

本模块不接触实际文件系统，仅对字符串做标准化。
"""

from __future__ import annotations

import os
from pathlib import Path


def make_path_key(path: Path | str) -> str:
    """返回路径比较键。

    Windows 下 normcase 将驱动器字母与路径统一为小写；
    normpath 规范化分隔符与冗余相对段。
    本函数不调用 Path.resolve()，不访问文件系统。
    """
    return os.path.normcase(os.path.normpath(str(path)))
