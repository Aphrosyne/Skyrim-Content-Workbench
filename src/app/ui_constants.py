"""UI 文本常量集中定义。

依据 docs/architecture.md §2 UI 分层规则：UI 字符串集中在 ui 层常量。
阶段 2 Task 2 后：旧 Task 3/4 相关常量将在 Task 3+ 重新启用或重写。
"""

from __future__ import annotations

# 窗口
APP_TITLE = "Skyrim Content Workbench"
WINDOW_DEFAULT_WIDTH = 1024
WINDOW_DEFAULT_HEIGHT = 720

# 受管理根目录区域
ROOTS_GROUP_TITLE = "受管理根目录"
ROOTS_EMPTY_HINT = "尚未配置任何受管理根目录。点击「添加目录」开始。"
ADD_ROOT_BUTTON = "添加目录"
REMOVE_ROOT_BUTTON = "移除选中目录"
REMOVE_ROOT_CONFIRM_TITLE = "确认移除"
REMOVE_ROOT_CONFIRM_TEXT = (
    "将移除受管理根目录配置：\n{path}\n\n"
    "此操作仅删除应用内的配置记录，不会删除或修改磁盘上的任何文件，"
    "也不会清理已扫描的目录树记录。"
)
SCAN_BUTTON = "扫描选中目录"
SCAN_BUTTON_FULL = "全量重扫选中目录"
SCAN_BUTTON_SCANNING = "扫描中…"

# 扫描状态
STATUS_IDLE = "就绪"
STATUS_SCANNING = "正在扫描…"
STATUS_SCAN_COMPLETE = "扫描完成"
STATUS_SCAN_FAILED = "扫描失败"

# 占位区域（Task 3+ 实现）
PLACEHOLDER_CONTENT_TITLE = "内容区（待实现）"
PLACEHOLDER_CONTENT_HINT = "将在阶段 2 Task 3+ 实现：目录树、内容单元列表、详情面板。"

# 错误
ERR_ADD_ROOT_FAILED = "添加目录失败"
ERR_NO_ROOT_SELECTED = "请先在左侧选择一个受管理根目录。"
ERR_DUPLICATE_ROOT = "该目录已添加。"
ERR_INVALID_ROOT = "路径不存在或不是目录。"
ERR_REMOVE_ROOT_FAILED = "移除目录配置失败"


def format_scan_summary(
    scanned_dirs: int,
    content_units_found: int,
    skipped_unchanged: int,
    errors: int,
) -> str:
    """格式化扫描摘要文本。"""
    parts = [
        f"扫描 {scanned_dirs} 个目录",
        f"新增 {content_units_found} 个内容单元",
    ]
    if skipped_unchanged > 0:
        parts.append(f"跳过 {skipped_unchanged} 个未变更目录")
    if errors > 0:
        parts.append(f"错误 {errors} 个")
    return "；".join(parts) + "。"
