"""冲突解决服务（Stage 5 Task 3b，Q3=C 通用冲突处理）。

为粘贴操作提供冲突批量解决能力：
- 预扫描：对剪贴板中每个源路径，检查目标目录是否已有同名文件
- 批量解决：UI 层通过 ConflictResolutionDialog 让用户对每个冲突选择
  覆盖/跳过/重命名，可选"应用到全部"
- 生成最终操作列表：(src, dst) 对，已应用重命名和跳过

设计要点：
- 本服务只负责数据计算和状态管理，不弹窗（UI 层负责对话框交互）
- 支持单条冲突的"应用到全部"（所有冲突使用相同策略）
- 重命名采用 Windows 资源管理器风格：file.txt → file (1).txt → file (2).txt
- 跨盘剪切拒绝（Q7=B）由本服务检测并返回错误
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from application.errors import FileOperationError
from infrastructure.path_utils import make_path_key


@dataclass(frozen=True)
class ConflictItem:
    """单个冲突项。

    Attributes:
        src: 源路径（绝对路径）。
        default_dst: 默认目标路径（dst_dir / src.name，若存在则为冲突）。
        suggested_dst: 建议的重命名目标路径（如 file (1).txt）。
        is_cross_drive: 是否跨盘剪切（Q7=B 拒绝）。
    """

    src: Path
    default_dst: Path
    suggested_dst: Path
    is_cross_drive: bool


@dataclass(frozen=True)
class ResolvedAction:
    """冲突解决后的最终操作项。

    Attributes:
        src: 源路径。
        dst: 最终目标路径（已应用重命名）。
        skipped: 是否跳过（True 时 src/dst 无意义，仅占位）。
        overwrite: 是否覆盖已存在的目标（True 时调用方需先删除 dst 再执行 copy/move）。
    """

    src: Path
    dst: Path
    skipped: bool = False
    overwrite: bool = False


# 冲突解决策略
RESOLUTION_OVERWRITE = "overwrite"  # 覆盖（Q3=C）
RESOLUTION_SKIP = "skip"  # 跳过
RESOLUTION_RENAME = "rename"  # 重命名为 suggested_dst


class ConflictResolutionService:
    """冲突解决服务。

    使用方式：
        service = ConflictResolutionService()
        conflicts = service.scan_conflicts(src_paths, dst_dir, operation='cut')
        # UI 层显示 ConflictResolutionDialog(conflicts) → 用户选择
        resolved = service.resolve(conflicts, decisions)
        # resolved: list[ResolvedAction]，调用方按 action 执行 copy/move
    """

    def scan_conflicts(
        self,
        src_paths: list[Path],
        dst_dir: Path,
        operation: str,
    ) -> list[ConflictItem]:
        """扫描剪贴板路径与目标目录的冲突。

        冲突定义：dst_dir / src.name 已存在。
        跨盘剪切（operation='cut' 且 src 与 dst_dir 不同盘）标记 is_cross_drive=True，
        UI 层应拒绝执行并提示（Q7=B）。

        验收反馈（2026-08-04）：目标路径等于源路径（如快速移动目标就是文件所在
        目录）属于无操作，直接从冲突列表剔除，不弹「覆盖/跳过/重命名」对话框。

        Args:
            src_paths: 源路径列表。
            dst_dir: 目标目录。
            operation: 剪贴板操作类型（'copy' 或 'cut'）。

        Returns:
            冲突项列表（每个 src_path 对应一项）。
        """
        conflicts: list[ConflictItem] = []
        for src in src_paths:
            default_dst = dst_dir / src.name
            # 移动到自身所在目录 = 无操作：不弹冲突对话框、不执行（自动跳过）
            if make_path_key(default_dst) == make_path_key(src):
                continue
            suggested_dst = self._suggest_rename(default_dst)
            is_cross_drive = self._check_cross_drive(src, dst_dir, operation)
            conflicts.append(
                ConflictItem(
                    src=src,
                    default_dst=default_dst,
                    suggested_dst=suggested_dst,
                    is_cross_drive=is_cross_drive,
                )
            )
        return conflicts

    def resolve(
        self,
        conflicts: list[ConflictItem],
        decisions: list[str],
    ) -> list[ResolvedAction]:
        """根据用户决策生成最终操作列表。

        Args:
            conflicts: scan_conflicts 返回的冲突项列表。
            decisions: 每个冲突对应的决策，取值为：
                - RESOLUTION_OVERWRITE：使用 default_dst（覆盖已有文件）
                - RESOLUTION_SKIP：跳过（skipped=True）
                - RESOLUTION_RENAME：使用 suggested_dst（重命名）

        Returns:
            ResolvedAction 列表（跳过的项 skipped=True）。

        Raises:
            FileOperationError: decisions 长度与 conflicts 不匹配，或决策值非法。
        """
        if len(decisions) != len(conflicts):
            raise FileOperationError(
                f"决策数量与冲突数量不匹配：{len(decisions)} vs {len(conflicts)}"
            )

        actions: list[ResolvedAction] = []
        for conflict, decision in zip(conflicts, decisions, strict=True):
            if decision == RESOLUTION_OVERWRITE:
                actions.append(
                    ResolvedAction(
                        src=conflict.src,
                        dst=conflict.default_dst,
                        overwrite=True,
                    )
                )
            elif decision == RESOLUTION_SKIP:
                actions.append(
                    ResolvedAction(src=conflict.src, dst=conflict.default_dst, skipped=True)
                )
            elif decision == RESOLUTION_RENAME:
                actions.append(ResolvedAction(src=conflict.src, dst=conflict.suggested_dst))
            else:
                raise FileOperationError(f"未知的冲突决策值：{decision}")
        return actions

    def _suggest_rename(self, dst: Path) -> Path:
        """生成重命名建议路径（Windows 风格：file (1).txt → file (2).txt）。

        在 dst 父目录下寻找第一个不存在的 "name (N).ext" 变体。
        """
        parent = dst.parent
        stem = dst.stem
        suffix = dst.suffix
        n = 1
        while True:
            candidate = parent / f"{stem} ({n}){suffix}"
            if not candidate.exists():
                return candidate
            n += 1

    def _check_cross_drive(self, src: Path, dst_dir: Path, operation: str) -> bool:
        """检测跨盘剪切（Q7=B）。

        跨盘复制允许（copy 不退化）；跨盘剪切拒绝（剪切 = move，Windows 跨盘 move 退化）。
        """
        if operation != "cut":
            return False
        try:
            src_dev = src.stat().st_dev
            dst_dev = dst_dir.stat().st_dev
            return src_dev != dst_dev
        except OSError:
            # 无法获取设备号时保守返回 False（让后续 FileOperationService 抛具体错误）
            return False


def has_cross_drive_cut(conflicts: list[ConflictItem]) -> bool:
    """检查冲突列表中是否存在跨盘剪切（UI 层用于整体拒绝提示，Q7=B）。"""
    return any(c.is_cross_drive for c in conflicts)


def has_conflict(conflicts: list[ConflictItem]) -> bool:
    """检查冲突列表中是否存在真实冲突（default_dst 已存在）。

    用于判断是否需要弹出 ConflictResolutionDialog。
    """
    return any(c.default_dst.exists() for c in conflicts)
