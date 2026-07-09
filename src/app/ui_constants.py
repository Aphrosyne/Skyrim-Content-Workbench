"""UI 文本常量集中定义。

依据 docs/architecture.md §2 UI 分层规则：UI 字符串集中在 ui 层常量，
不散布到业务层（见 docs/open-questions.md Q9：阶段 2 不强制 i18n 框架）。
"""

from __future__ import annotations

# 窗口
APP_TITLE = "Skyrim Mod Workbench"
WINDOW_DEFAULT_WIDTH = 1024
WINDOW_DEFAULT_HEIGHT = 720

# 受管理根目录区域
ROOTS_GROUP_TITLE = "受管理根目录"
ROOTS_EMPTY_HINT = "尚未配置任何受管理根目录。点击「添加目录」开始。"
ADD_ROOT_BUTTON = "添加目录"
SCAN_BUTTON = "扫描选中目录"
SCAN_BUTTON_SCANNING = "扫描中…"

# 扫描状态
STATUS_IDLE = "就绪"
STATUS_SCANNING = "正在扫描…"
STATUS_SCAN_COMPLETE = "扫描完成"
STATUS_SCAN_FAILED = "扫描失败"

# 占位区域（阶段 2 后续任务实现）
PLACEHOLDER_TREE_TITLE = "目录树（待实现）"
PLACEHOLDER_TREE_HINT = "将在阶段 2 任务 3 实现：以 FolderNode 为数据源展示目录层级。"
PLACEHOLDER_POOL_TITLE = "素材池 / ModItem 列表（待实现）"
PLACEHOLDER_POOL_HINT = "将在阶段 2 任务 3-4 实现：未关联素材与 ModItem 列表。"
PLACEHOLDER_DETAIL_TITLE = "详情（待实现）"
PLACEHOLDER_DETAIL_HINT = "将在阶段 2 任务 4-5 实现：成员、角色、移动预演与撤销。"

# 目录树区域（Task 2）
TREE_GROUP_TITLE = "受管理目录树"
TREE_EMPTY_HINT = "尚未配置任何受管理根目录。点击「添加目录」开始。"
TREE_UNSCANNED_HINT = "已配置但尚未扫描。点击「扫描选中目录」加载目录结构。"

# 详情区域（Task 2）
DETAIL_GROUP_TITLE = "选中目录信息"
DETAIL_NONE_HINT = "未选中任何目录。"
DETAIL_NAME_LABEL = "目录名称"
DETAIL_PATH_LABEL = "完整路径"
DETAIL_IS_ROOT_LABEL = "是否为受管理根目录"
DETAIL_CHILDREN_COUNT_LABEL = "子目录数量"
DETAIL_CATEGORY_ROOT = "受管理根目录（已扫描）"
DETAIL_CATEGORY_UNSCANNED = "受管理根目录（未扫描）"
DETAIL_CATEGORY_FOLDER = "子目录"

# 错误
ERR_ADD_ROOT_FAILED = "添加目录失败"
ERR_NO_ROOT_SELECTED = "请先在左侧选择一个受管理根目录。"
ERR_DUPLICATE_ROOT = "该目录已添加。"
ERR_INVALID_ROOT = "路径不存在或不是目录。"

# 摘要
SUMMARY_TEMPLATE = (
    "扫描完成：扫描 {folders} 个目录、{files} 个文件；"
    "持久化 {pfolders} 个目录、{pfiles} 个文件；错误 {errors} 个。"
)
SUMMARY_ERRORS_PREFIX = "错误摘要（前 {n} 条）："


def format_summary(  # noqa: D401 - 简单格式化函数
    folders: int,
    files: int,
    persisted_folders: int,
    persisted_files: int,
    errors: int,
) -> str:
    """格式化扫描摘要文本。"""
    return SUMMARY_TEMPLATE.format(
        folders=folders,
        files=files,
        pfolders=persisted_folders,
        pfiles=persisted_files,
        errors=errors,
    )
