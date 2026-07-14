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

# 目录树区域
TREE_GROUP_TITLE = "目录树"
TREE_EMPTY_HINT = "尚未扫描任何目录。请先在左侧选择根目录并点击「扫描」。"
TREE_UNSCANNED_HINT = "（未扫描）"

# 选中目录详情区域
DETAIL_GROUP_TITLE = "选中目录详情"
DETAIL_NAME_LABEL = "目录名称"
DETAIL_PATH_LABEL = "完整路径"
DETAIL_IS_ROOT_LABEL = "是否受管理根目录"
DETAIL_TYPE_LABEL = "类型"
DETAIL_CHILD_COUNT_LABEL = "直接子目录数"
DETAIL_TYPE_MANAGED_ROOT = "已扫描根目录"
DETAIL_TYPE_UNSCANNED_ROOT = "未扫描根目录"
DETAIL_TYPE_FOLDER = "子目录"
DETAIL_NOT_SELECTED = "未选中任何目录。请在目录树中点击选择。"

# 内容单元列表区域
CONTENT_LIST_GROUP_TITLE = "文件列表"
CONTENT_LIST_EMPTY_HINT = "该目录为空或无可见文件。"
CONTENT_LIST_NO_SELECTION = "请在左侧目录树中选择一个目录。"

# 文件列表项标记（roadmap Task 4 2026-07-13 设计修正）
CONTENT_UNIT_MARKER_ORGANIZED = " [内容单元 ✓]"
CONTENT_UNIT_MARKER_UNORGANIZED = " [内容单元]"

# 右键菜单
CONTEXT_MENU_COPY_PATH = "复制路径"
CONTEXT_MENU_COPY_PATH_OK = "路径已复制到剪贴板。"

# 元数据面板区域
METADATA_GROUP_TITLE = "元数据"
METADATA_NOT_SELECTED = "双击内容单元查看元数据。"
METADATA_NOT_CONTENT_UNIT = "此项不是内容单元，无元数据。"
METADATA_TITLE_LABEL = "标题"
METADATA_PATH_LABEL = "路径"
METADATA_TYPE_LABEL = "类型"
METADATA_SOURCE_URL_LABEL = "来源 URL"
METADATA_RATING_LABEL = "评分"
METADATA_STATUS_LABEL = "整理状态"
METADATA_NOTES_LABEL = "备注"
METADATA_CREATED_AT_LABEL = "创建时间"
METADATA_STATUS_UNORGANIZED = "未整理"
METADATA_STATUS_ORGANIZED = "已整理"
METADATA_RATING_EMPTY = "未评分"
METADATA_NOTES_EMPTY = "（无）"
METADATA_SOURCE_URL_EMPTY = "（无）"

# 错误
ERR_ADD_ROOT_FAILED = "添加目录失败"
ERR_NO_ROOT_SELECTED = "请先在左侧选择一个受管理根目录。"
ERR_DUPLICATE_ROOT = "该目录已添加。"
ERR_INVALID_ROOT = "路径不存在或不是目录。"
ERR_REMOVE_ROOT_FAILED = "移除目录配置失败"

# 模式切换（spec §5.1/§5.2，roadmap 阶段 2 Task 5）
MODE_SWITCH_GROUP_TITLE = "模式"
MODE_BROWSE = "浏览"
MODE_ORGANIZE = "整理"
MODE_BROWSE_HINT = "浏览模式：点击目录树节点切换中栏内容。"
MODE_ORGANIZE_HINT = "整理模式：中栏内容已冻结，目录树作为目标选择器。"
MODE_ORGANIZE_WORKAREA_HINT = "整理模式 - 工作区：{name}"
MODE_ORGANIZE_TARGET_HINT = "目标：{path}"
MODE_ORGANIZE_NO_WORKAREA = "整理模式：请先在浏览模式选中目录后再切换。"


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
