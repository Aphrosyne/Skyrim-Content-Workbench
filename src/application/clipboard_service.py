"""应用内剪贴板服务（Stage 5 Task 3b）。

Q3=A：应用内剪贴板，状态保存在 ClipboardService 实例中，不与系统剪贴板混用。
Q6=A：应用关闭即清空（不持久化，不跨会话）。

剪贴板保存 ClipboardEntry(paths, operation, timestamp)：
- operation='copy'：粘贴时调用 FileOperationService.copy
- operation='cut'：粘贴时调用 FileOperationService.move，剪切状态下条目半透明

约束：
- 复制/剪切覆盖旧剪贴板状态（标准剪贴板行为，Q5 决策点）
- 剪切状态查询 is_cut(path)：用于 UI 层半透明渲染
- 清空剪贴板时同时清除剪切高亮状态
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ClipboardEntry:
    """剪贴板条目。

    Attributes:
        paths: 源路径列表（绝对路径字符串）。
        operation: 操作类型，'copy' 或 'cut'。
        timestamp: 创建时间戳（ISO 8601 UTC）。
    """

    paths: list[str]
    operation: str
    timestamp: str


class ClipboardService:
    """应用内剪贴板服务。

    使用方式：
        service = ClipboardService()
        service.set_copy([str(path1), str(path2)])
        entry = service.get()  # ClipboardEntry 或 None
        service.is_cut(str(path1))  # True/False
        service.clear()

    线程安全：本服务仅由 UI 主线程访问，不加锁。
    """

    def __init__(self, now_provider: Callable[[], str] | None = None) -> None:
        """初始化剪贴板服务。

        Args:
            now_provider: 时间戳生成器（测试可注入）。
        """
        self._entry: ClipboardEntry | None = None
        self._now = now_provider or _default_now_utc

    def set_copy(self, paths: list[str]) -> ClipboardEntry:
        """设置复制状态。覆盖旧剪贴板。

        Args:
            paths: 源路径列表（绝对路径字符串）。

        Returns:
            新的 ClipboardEntry。
        """
        entry = ClipboardEntry(
            paths=list(paths),
            operation="copy",
            timestamp=self._now(),
        )
        self._entry = entry
        return entry

    def set_cut(self, paths: list[str]) -> ClipboardEntry:
        """设置剪切状态。覆盖旧剪贴板。

        Args:
            paths: 源路径列表（绝对路径字符串）。

        Returns:
            新的 ClipboardEntry。
        """
        entry = ClipboardEntry(
            paths=list(paths),
            operation="cut",
            timestamp=self._now(),
        )
        self._entry = entry
        return entry

    def get(self) -> ClipboardEntry | None:
        """获取当前剪贴板条目；空时返回 None。"""
        return self._entry

    def clear(self) -> None:
        """清空剪贴板。"""
        self._entry = None

    def is_cut(self, path: str) -> bool:
        """查询指定路径是否处于剪切状态。

        用于 UI 层半透明渲染（Q12=A 50% 透明度）。
        仅当当前剪贴板 operation='cut' 且 path 在 paths 中时返回 True。

        Args:
            path: 待查询的路径字符串。

        Returns:
            True 表示该路径处于剪切状态。
        """
        if self._entry is None or self._entry.operation != "cut":
            return False
        return path in self._entry.paths

    def cut_paths(self) -> set[str]:
        """返回当前剪切状态的路径集合（用于 UI 批量渲染）。

        剪贴板为空或 operation != 'cut' 时返回空集合。
        """
        if self._entry is None or self._entry.operation != "cut":
            return set()
        return set(self._entry.paths)


def _default_now_utc() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
