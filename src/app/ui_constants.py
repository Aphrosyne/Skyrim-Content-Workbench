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
REMOVE_ROOT_BUTTON = "移除选中目录"
REMOVE_ROOT_CONFIRM_TITLE = "确认移除"
REMOVE_ROOT_CONFIRM_TEXT = (
    "将移除受管理根目录配置：\n{path}\n\n"
    "此操作仅删除应用内的配置记录，不会删除或修改磁盘上的任何文件，"
    "也不会清理已扫描的目录树记录。"
)
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

# 素材池区域（Task 3）
POOL_GROUP_TITLE = "未归类素材池"
POOL_EMPTY_HINT = "暂无未归类素材。扫描受管理根目录后，未关联到任何 Mod 条目的文件将出现在这里。"
POOL_COL_NAME = "文件名"
POOL_COL_KIND = "类型"

# ModItem 列表区域（Task 3）
MOD_LIST_GROUP_TITLE = "Mod 条目列表"
MOD_LIST_EMPTY_HINT = "暂无 Mod 条目。在素材池中选择素材后点击「新建 Mod 条目」。"
NEW_MOD_BUTTON = "新建 Mod 条目"
NEW_MOD_DIALOG_TITLE = "新建 Mod 条目"
NEW_MOD_DIALOG_LABEL = "条目名称："
NEW_MOD_DIALOG_DEFAULT_NAME = "新 Mod 条目"

# ModItem 详情区域（Task 3）
MOD_DETAIL_GROUP_TITLE = "Mod 条目详情"
MOD_DETAIL_NONE_HINT = "请在左侧选择一个 Mod 条目。"
MOD_DETAIL_NAME_LABEL = "显示名称"
MOD_DETAIL_DESC_LABEL = "说明"
MOD_DETAIL_URL_LABEL = "来源链接"
MOD_DETAIL_TAGS_LABEL = "标签"
MOD_DETAIL_SAVE_BUTTON = "保存元数据"
MOD_DETAIL_SAVED_HINT = "元数据已保存"

# 成员表格区域（Task 3）
MEMBERS_GROUP_TITLE = "成员列表"
MEMBERS_EMPTY_HINT = "该 Mod 条目暂无成员。在素材池中选择素材并关联到此条目。"
MEMBERS_COL_FILENAME = "文件名"
MEMBERS_COL_KIND = "类型"
MEMBERS_COL_ROLE = "角色"
MEMBERS_COL_PATH = "完整路径"
MEMBERS_COL_COVER = "封面"
MEMBERS_COL_ACTION = "操作"
MEMBERS_REMOVE_BUTTON = "移除"
MEMBERS_SET_COVER_BUTTON = "设为封面"
MEMBERS_COVER_MARK = "★ 封面"

# 缩略图与预览（Task 4）
COVER_PREVIEW_TITLE = "封面预览"
COVER_PREVIEW_NONE_HINT = "未设置封面。将预览图成员设为封面后显示缩略图。"
COVER_PREVIEW_LOADING = "正在生成缩略图…"
COVER_PREVIEW_ERROR = "缩略图不可用：{reason}"
THUMBNAIL_PLACEHOLDER_TEXT = "无预览图"

# 角色中文名（与 pool_model.ROLE_DISPLAY_NAMES 一致，集中定义避免漂移）
ROLE_MAIN_MOD = "本体"
ROLE_TRANSLATION = "汉化"
ROLE_PREVIEW = "预览图"
ROLE_README = "说明"
ROLE_OPTIONAL_FILE = "可选文件"
ROLE_UNKNOWN = "未知"

# 操作按钮（Task 3）
ASSOCIATE_BUTTON = "关联到选中条目"
ASSOCIATE_NO_SELECTION = "请先在素材池中选择至少一个素材，并在 Mod 条目列表中选择一个目标条目。"
ASSOCIATE_SUCCESS = "已关联 {n} 个素材到「{name}」。"
ASSOCIATE_FAILED = "关联失败"

# 错误（Task 3）
ERR_NO_MOD_SELECTED = "请先在 Mod 条目列表中选择一个条目。"
ERR_NO_ASSET_SELECTED = "请先在素材池中选择至少一个素材。"
ERR_CREATE_MOD_FAILED = "创建 Mod 条目失败"
ERR_UPDATE_MOD_FAILED = "保存元数据失败"
ERR_SET_ROLE_FAILED = "设置角色失败"
ERR_REMOVE_MEMBER_FAILED = "移除成员失败"

# 错误
ERR_ADD_ROOT_FAILED = "添加目录失败"
ERR_NO_ROOT_SELECTED = "请先在左侧选择一个受管理根目录。"
ERR_DUPLICATE_ROOT = "该目录已添加。"
ERR_INVALID_ROOT = "路径不存在或不是目录。"
ERR_REMOVE_ROOT_FAILED = "移除目录配置失败"

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
