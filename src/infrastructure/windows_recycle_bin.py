"""Windows 回收站封装（ctypes SHFileOperation）。

Stage 5 Task 3a：删除文件/目录到回收站（不是永久删除），支持用户通过
回收站恢复。仅 Windows 平台可用；非 Windows 平台抛 RuntimeError。

约束（AGENTS 规则 2）：
- 删除前不校验目标存在（SHFileOperation 自身处理），但建议调用方先校验
- 使用 FOF_ALLOWUNDO 标志实现"移至回收站"而非永久删除
- 使用 FOF_NOCONFIRMATION 跳过系统确认对话框（应用层已确认）
- 使用 FOF_SILENT 抑制进度对话框（应用层自行提示）
- 不读写文件内容（仅删除）
"""

from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


# SHFileOperation 标志位
# 允许撤销（移至回收站而非永久删除）
FOF_ALLOWUNDO = 0x0040
# 不显示确认对话框
FOF_NOCONFIRMATION = 0x0010
# 不显示进度对话框
FOF_SILENT = 0x0004
# 不报错（部分文件不存在时继续）
FOF_NOERRORUI = 0x0400

# 操作类型
FO_DELETE = 0x0003


class SHFILEOPSTRUCTW(ctypes.Structure):
    """SHFileOperation 的参数结构（Unicode 版本）。"""

    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", ctypes.c_bool),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


class RecycleBinError(Exception):
    """移至回收站失败。"""


def move_to_recycle_bin(paths: list[Path]) -> None:
    """将多个文件/目录移至 Windows 回收站。

    Args:
        paths: 待删除的路径列表。每个路径必须存在（不存在由 SHFileOperation
            报错，但不中断其他文件）。

    Raises:
        RecycleBinError: SHFileOperation 返回非零错误码，或非 Windows 平台。
    """
    if os.name != "nt":
        raise RecycleBinError("移至回收站仅支持 Windows 平台")

    if not paths:
        return

    # SHFileOperation 要求路径以双 \0 结尾，多个路径以 \0 分隔
    path_strs = []
    for p in paths:
        # 转为绝对路径字符串（避免相对路径导致 SHFileOperation 找不到）
        path_strs.append(str(p.resolve()))
    # 双 \0 结尾是 SHFileOperation 的契约
    pFrom = "\0".join(path_strs) + "\0\0"  # noqa: N806 (ctypes 命名)

    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = pFrom
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    op.fAnyOperationsAborted = False
    op.hNameMappings = None
    op.lpszProgressTitle = None

    try:
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    except OSError as e:
        raise RecycleBinError(f"调用 SHFileOperation 失败：{e}") from e

    if result != 0:
        # result 为 SHFileOperation 错误码（非 Win32 错误码）
        # 常见：0x7E = 路径不存在，0x75 = 用户取消，0x78 = 磁盘满
        raise RecycleBinError(f"SHFileOperation 返回错误码：0x{result:X}（路径：{paths}）")

    if op.fAnyOperationsAborted:
        raise RecycleBinError("用户取消了部分操作")

    logger.info("已将 %d 项移至回收站：%s", len(paths), paths)
