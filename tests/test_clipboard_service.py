"""ClipboardService 单元测试（Stage 5 Task 3b）。

覆盖：
- set_copy / set_cut 设置状态，覆盖旧剪贴板
- get 返回当前条目，空时返回 None
- is_cut 查询剪切状态
- cut_paths 返回剪切路径集合
- clear 清空剪贴板
- now_provider 可注入（测试确定性时间戳）
- Q6=A：不持久化，关闭即清空（实例变量语义）
"""

from __future__ import annotations

from application.clipboard_service import ClipboardEntry, ClipboardService


def test_set_copy_returns_entry() -> None:
    """set_copy 返回 ClipboardEntry，operation='copy'。"""
    svc = ClipboardService(now_provider=lambda: "2026-07-30T00:00:00Z")
    entry = svc.set_copy(["D:/a.txt", "D:/b.txt"])

    assert isinstance(entry, ClipboardEntry)
    assert entry.paths == ["D:/a.txt", "D:/b.txt"]
    assert entry.operation == "copy"
    assert entry.timestamp == "2026-07-30T00:00:00Z"


def test_set_cut_returns_entry() -> None:
    """set_cut 返回 ClipboardEntry，operation='cut'。"""
    svc = ClipboardService(now_provider=lambda: "2026-07-30T00:00:00Z")
    entry = svc.set_cut(["D:/a.txt"])

    assert entry.operation == "cut"
    assert entry.paths == ["D:/a.txt"]


def test_get_returns_current_entry() -> None:
    """get 返回当前剪贴板条目。"""
    svc = ClipboardService()
    assert svc.get() is None

    entry = svc.set_copy(["D:/a.txt"])
    assert svc.get() is entry


def test_set_copy_overrides_cut() -> None:
    """复制覆盖剪切状态（标准剪贴板行为）。"""
    svc = ClipboardService()
    svc.set_cut(["D:/a.txt"])
    svc.set_copy(["D:/b.txt"])

    entry = svc.get()
    assert entry is not None
    assert entry.operation == "copy"
    assert entry.paths == ["D:/b.txt"]
    # 剪切高亮应失效
    assert svc.is_cut("D:/a.txt") is False


def test_set_cut_overrides_copy() -> None:
    """剪切覆盖复制状态。"""
    svc = ClipboardService()
    svc.set_copy(["D:/a.txt"])
    svc.set_cut(["D:/b.txt"])

    entry = svc.get()
    assert entry is not None
    assert entry.operation == "cut"
    assert svc.is_cut("D:/b.txt") is True


def test_is_cut_only_true_for_cut_operation() -> None:
    """is_cut 仅在 operation='cut' 且路径匹配时返回 True。"""
    svc = ClipboardService()
    svc.set_copy(["D:/a.txt"])
    # 复制状态下 is_cut 返回 False
    assert svc.is_cut("D:/a.txt") is False

    svc.set_cut(["D:/a.txt"])
    assert svc.is_cut("D:/a.txt") is True
    assert svc.is_cut("D:/other.txt") is False


def test_is_cut_returns_false_when_empty() -> None:
    """剪贴板为空时 is_cut 返回 False。"""
    svc = ClipboardService()
    assert svc.is_cut("D:/a.txt") is False


def test_cut_paths_returns_set() -> None:
    """cut_paths 返回剪切路径集合。"""
    svc = ClipboardService()
    assert svc.cut_paths() == set()

    svc.set_cut(["D:/a.txt", "D:/b.txt"])
    assert svc.cut_paths() == {"D:/a.txt", "D:/b.txt"}


def test_cut_paths_empty_when_copy_operation() -> None:
    """复制状态下 cut_paths 返回空集合。"""
    svc = ClipboardService()
    svc.set_copy(["D:/a.txt"])
    assert svc.cut_paths() == set()


def test_clear_empties_clipboard() -> None:
    """clear 清空剪贴板。"""
    svc = ClipboardService()
    svc.set_cut(["D:/a.txt"])
    svc.clear()

    assert svc.get() is None
    assert svc.is_cut("D:/a.txt") is False
    assert svc.cut_paths() == set()


def test_set_copy_does_not_mutate_input_list() -> None:
    """set_copy/set_cut 不应修改调用方传入的列表。"""
    svc = ClipboardService()
    original = ["D:/a.txt", "D:/b.txt"]
    svc.set_copy(original)

    # 修改原列表不应影响剪贴板
    original.append("D:/c.txt")
    entry = svc.get()
    assert entry is not None
    assert entry.paths == ["D:/a.txt", "D:/b.txt"]


def test_now_provider_injected() -> None:
    """now_provider 可注入，用于测试确定性时间戳。"""
    svc = ClipboardService(now_provider=lambda: "2025-01-01T00:00:00Z")
    entry = svc.set_copy(["D:/a.txt"])
    assert entry.timestamp == "2025-01-01T00:00:00Z"
