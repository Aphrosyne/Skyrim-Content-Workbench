"""路径显示工具（UX 重构 Phase 2 Task 5）。

open-questions §9：所有路径不显示绝对路径，从受管理根目录开始显示。
如 `D:\\Skyrim\\archive\\mods\\bdor` → `Skyrim\\archive\\mods\\bdor`。
受管理目录的父级路径不显示。

Q8 决策（B）：路径不在任何受管理根目录下时，加前缀 `[外部]` 显示相对路径，
保留可追溯性同时明确标识外部路径。

修正：相对路径需包含受管理根目录名（用户验收反馈），便于在多根目录场景下
区分路径所属根目录。例：根 `D:\\testPath\\A`，路径 `D:\\testPath\\A\\B\\C`
→ `A\\B\\C`（而非 `B\\C`）。
"""

from __future__ import annotations

from pathlib import Path, PurePath

from domain.models import ManagedRoot


def make_display_path(
    abs_path: str | Path,
    managed_roots: list[ManagedRoot],
) -> str:
    """将绝对路径转换为从受管理根目录开始的显示路径。

    规则（Q8=B + 验收修正）：
    - 路径在某受管理根目录下：返回相对该根目录父目录的路径（含根目录名）。
      例：根 `D:\\Skyrim`，路径 `D:\\Skyrim\\archive\\mods\\bdor`
      → `Skyrim\\archive\\mods\\bdor`
    - 路径就是根目录本身：返回根目录名。
      例：根 `D:\\testPath\\A`，路径 `D:\\testPath\\A` → `A`
    - 路径不在任何受管理根目录下：加 `[外部]` 前缀，返回完整路径。
      例：`C:\\Temp\\foo` → `[外部] C:\\Temp\\foo`
    - 空路径：返回空字符串。

    比较使用 PurePath（跨平台安全），匹配最长根目录（处理嵌套根目录场景）。

    Args:
        abs_path: 绝对路径字符串或 Path 对象。
        managed_roots: 受管理根目录列表。

    Returns:
        简化后的显示路径字符串。
    """
    if abs_path is None:
        return ""
    path_str = str(abs_path)
    if not path_str:
        return ""

    target = PurePath(path_str)
    # 找最长匹配的根目录（处理嵌套根目录）
    best_root: PurePath | None = None
    best_root_str: str | None = None
    for root in managed_roots:
        root_path = PurePath(root.real_path)
        try:
            # target.relative_to(root_path) 在 root 是 target 的父级时返回相对路径
            # PurePath.relative_to 仅支持严格相对（root 必须是 target 的前缀）
            if target == root_path:
                # 路径就是根目录本身：显示根目录名
                return root_path.name
            rel = target.relative_to(root_path)
            # 匹配成功，选择最长根目录
            if best_root is None or len(root_path.parts) > len(best_root.parts):
                best_root = root_path
                # relative_to 返回的 rel 直接用（PurePath 跨平台）
                best_root_str = str(rel)
        except ValueError:
            continue

    if best_root is not None and best_root_str is not None:
        # 匹配到根目录，返回包含根目录名的相对路径
        # 例：根 D:\testPath\A，路径 D:\testPath\A\B\C → A\B\C
        return f"{best_root.name}\\{best_root_str}" if best_root_str else best_root.name

    # 未匹配任何根目录，加 [外部] 前缀（Q8=B）
    return f"[外部] {path_str}"


def make_display_path_from_service(
    abs_path: str | Path,
    managed_root_service,
) -> str:
    """便捷封装：从 ManagedRootService 获取根目录列表后调用 make_display_path。

    Args:
        abs_path: 绝对路径。
        managed_root_service: ManagedRootService 实例。

    Returns:
        简化后的显示路径。
    """
    roots = managed_root_service.list_roots()
    return make_display_path(abs_path, roots)
