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
    "此操作将删除应用数据库中的根目录配置及该目录下的扫描记录"
    "（目录树缓存与内容单元元数据），"
    "不会删除或修改磁盘上的任何文件。"
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
CONTENT_LIST_EMPTY_HINT = "该目录为空"
CONTENT_LIST_NO_SELECTION = "请在左侧目录树中选择一个目录。"

# 文件列表列头（阶段 3 Task 2 4 列 TableModel）
FILE_LIST_COLUMN_HEADERS = ("名称", "类型", "大小", "修改日期")
COL_TYPE_FOLDER = "文件夹"
COL_TYPE_FILE = "文件"

# 文件列表项内容单元标记
# Stage 5 Task 7 收尾：status 简化为两态（organized / unmarked），
# unmarked 不显示标记，故仅需一个统一标记。
CONTENT_UNIT_MARKER = " [内容单元]"

# 右键菜单
CONTEXT_MENU_COPY_PATH = "复制路径"
CONTEXT_MENU_COPY_PATH_OK = "路径已复制到剪贴板。"

# 文件列表右键菜单（阶段 3 Task 3）
MENU_CREATE_MOD_GROUP = "创建 Mod 组"
MENU_MARK_CONTENT_UNIT = "标记为内容单元"
MENU_UNMARK_CONTENT_UNIT = "取消内容单元标记"
MENU_BATCH_MARK_CONTENT_UNIT = "批量标记为内容单元"
MENU_BATCH_UNMARK_CONTENT_UNIT = "批量取消内容单元标记"
MENU_BATCH_TAG = "批量打标签"
MENU_ADD_RECENT_TAG = "添加最近标签"
# UX 重构 Phase 1 Task 2（B2-2）：移除 MENU_ADD_TO_ASSEMBLY，Task 4 由「添加到钉住文件夹」替代
MENU_QUICK_SET_COVER = "快速设置封面"
MENU_QUICK_SET_COVER_NO_IMAGE = "该目录无可用图片"
MENU_QUICK_SET_COVER_ALREADY_SET = "已设置封面，未覆盖"
MENU_QUICK_SET_COVER_OK = "封面已设置"
MENU_OPEN_IN_EXPLORER = "在资源管理器中打开"
MENU_OPEN_IN_EXPLORER_FAILED = "无法打开资源管理器"
# UX 重构 Phase 2 Task 5：右键「打开」项（行为与双击一致）
MENU_OPEN = "打开"
MENU_COLLAPSE_ALL = "折叠全部"

# Stage 5 Task 3a：文件操作菜单项
MENU_NEW_FOLDER = "新建文件夹"
MENU_RENAME = "重命名"
MENU_DELETE = "删除"
MENU_DELETE_CONFIRM_TITLE = "确认删除"
MENU_DELETE_CONFIRM_TEXT_SINGLE = "确定将以下 1 项移至 Windows 回收站？\n此操作不可撤销。"
MENU_DELETE_CONFIRM_TEXT_MULTI = "确定将以下 {n} 项移至 Windows 回收站？\n此操作不可撤销。"
MENU_DELETE_CONFIRM_FOLDER_FILES = "（文件夹内含 {n} 个文件）\n此操作不可撤销。"
MENU_DELETE_SUCCESS = "已移至回收站：{n} 项"
MENU_DELETE_PARTIAL = "成功删除 {ok} 项，失败 {fail} 项（详见日志）"
MENU_NEW_FOLDER_DIALOG_TITLE = "新建文件夹"
MENU_NEW_FOLDER_DIALOG_LABEL = "文件夹名称："
MENU_NEW_FOLDER_DEFAULT_NAME = "新建文件夹"
MENU_RENAME_DIALOG_TITLE = "重命名"
MENU_RENAME_DIALOG_LABEL = "新名称："
MENU_NEW_FOLDER_SUCCESS = "已创建文件夹：{name}"
MENU_RENAME_SUCCESS = "已重命名为：{name}"
MENU_OPERATION_FAILED = "操作失败：{error}"

# === Stage 5 Task 6：操作历史与撤销 ===
TOOLBAR_OPERATION_HISTORY = "操作历史"
OPERATION_HISTORY_DIALOG_TITLE = "操作历史"
OPERATION_HISTORY_REFRESH = "刷新"
OPERATION_HISTORY_UNDO = "撤销选中"
OPERATION_HISTORY_CLOSE = "关闭"
OPERATION_HISTORY_UNDO_CONFIRM_TITLE = "确认撤销"
OPERATION_HISTORY_UNDO_CONFIRM_TEXT = (
    "确定要撤销以下操作？\n\n{desc}\n\n此操作将还原文件到操作前的状态。"
)
# 历史记录描述格式
# UX 重构 Phase 2 Task 5（Q9=A）：移除 HISTORY_DESC_UNDO（D4 决策已消除 undo 记录）
HISTORY_DESC_NEW_FOLDER = "新建文件夹：{target}"
HISTORY_DESC_RENAME = "重命名：{source} → {target}"
HISTORY_DESC_MOVE = "移动：{source} → {target}"
HISTORY_DESC_DELETE = "删除：{source}（不可撤销）"
HISTORY_DESC_COPY = "复制：{source} → {target}（不可撤销）"
HISTORY_DESC_UNKNOWN = "未知操作：{op}"
# 操作类型中文名映射（操作历史对话框操作列显示）
HISTORY_OP_LABELS = {
    "new_folder": "新建文件夹",
    "rename": "重命名",
    "move": "移动",
    "delete": "删除",
    "copy": "复制",
}
# 状态显示
HISTORY_STATUS_CAN_UNDO = "可撤销"
HISTORY_STATUS_CANNOT_UNDO = "不可撤销"
HISTORY_STATUS_UNDONE = "已撤销"
# 撤销结果
UNDO_SUCCESS = "已撤销：{desc}"
UNDO_NOT_ALLOWED = "该操作不可撤销"
UNDO_DELETE_NOT_ALLOWED = "删除操作不可撤销，请从 Windows 回收站手动还原"
UNDO_FAILED = "撤销失败：{error}"
UNDO_SAFETY_FAILED = "无法撤销：{reason}"
UNDO_ALREADY_UNDONE = "该操作已被撤销，不可重复撤销"

# === Stage 5 Task 4：键盘快捷键 ===
SHORTCUT_NO_SELECTION = "未选中任何条目"
SHORTCUT_NO_UNDOABLE = "无可撤销操作"
SHORTCUT_UNDO_SUCCESS = "已撤销：{desc}"
SHORTCUT_UNDO_FAILED = "撤销失败：{error}"
SHORTCUT_UNDO_SAFETY_FAILED = "无法撤销：{reason}"
SHORTCUT_UNDO_NOT_ALLOWED = "该操作不可撤销"
SHORTCUT_UNDO_CONFIRM_TITLE = "确认撤销"
SHORTCUT_UNDO_CONFIRM_TEXT = "确定要撤销以下操作？\n\n{desc}\n\n此操作将还原文件到操作前的状态。"
# Q4=C：Ctrl+C/X/V 静默忽略，不提示
# （无文案，handler 直接 return）

# === Stage 5 Task 3b：剪贴板与冲突解决 ===
SHORTCUT_COPIED = "已复制 {n} 项到剪贴板"
SHORTCUT_CUT = "已剪切 {n} 项"
SHORTCUT_PASTED = "已粘贴 {n} 项到 {dir_name}"
SHORTCUT_PASTE_EMPTY = "剪贴板为空"
SHORTCUT_PASTE_PARTIAL = "部分操作失败：成功 {ok} 项，失败 {fail} 项"
SHORTCUT_PASTE_CROSS_DRIVE_CUT = "跨盘剪切不支持，请改为复制后手动删除原文件"
SHORTCUT_PASTE_SRC_NOT_FOUND = "源文件不存在，可能已被外部删除：{name}"
SHORTCUT_PASTE_FAILED = "粘贴失败：{error}"

# 冲突解决对话框
CONFLICT_DIALOG_TITLE = "冲突解决"
CONFLICT_DIALOG_HINT = "目标目录已存在以下同名文件，请选择处理方式："
CONFLICT_DIALOG_COL_SOURCE = "源文件名"
CONFLICT_DIALOG_COL_DECISION = "处理方式"
CONFLICT_DIALOG_COL_PREVIEW = "重命名预览"
CONFLICT_DIALOG_RADIO_OVERWRITE = "覆盖"
CONFLICT_DIALOG_RADIO_SKIP = "跳过"
CONFLICT_DIALOG_RADIO_RENAME = "重命名"
CONFLICT_DIALOG_APPLY_ALL = "应用到全部"
CONFLICT_DIALOG_OK = "确定"
CONFLICT_DIALOG_CANCEL = "取消"

# 右键菜单剪贴板项
MENU_COPY = "复制"
MENU_CUT = "剪切"
MENU_PASTE = "粘贴"

# Stage 5 Task 5：「移动到……」对话框
MENU_MOVE_TO = "移动到..."
MENU_MOVE_TO_RECENT = "移动到最近目录"
SHORTCUT_MOVE_TO_LATEST_NO_TARGET = "暂无最近移动目标，请先使用「移动到...」选择一次目标"
SHORTCUT_MOVE_TO_NO_SELECTION = "未选中任何条目"
SHORTCUT_MOVE_TO_CANCELLED = "已取消移动"
SHORTCUT_MOVE_TO_NO_TARGET = "未选择目标目录"
SHORTCUT_MOVE_TO_OK = "已移动 {n} 项到 {dir_name}"
SHORTCUT_MOVE_TO_PARTIAL = "部分移动失败：成功 {ok} 项，失败 {fail} 项"
SHORTCUT_MOVE_TO_SRC_NOT_FOUND = "源文件不存在，可能已被外部删除：{name}"
SHORTCUT_MOVE_TO_FAILED = "移动失败：{error}"
SHORTCUT_MOVE_TO_CROSS_DRIVE = "跨盘移动暂不支持"
SHORTCUT_MOVE_TO_SELF_SUBDIR = "不能移动到自身或子目录"

MOVE_TO_DIALOG_TITLE = "移动到..."
MOVE_TO_DIALOG_HINT = "请选择目标目录（将移动 {n} 项）："
MOVE_TO_DIALOG_NO_SELECTION = "未选择目标目录"
MOVE_TO_DIALOG_SELECTED = "目标：{path}"
MOVE_TO_DIALOG_INVALID_TARGET = "不能移动到自身或子目录，请选择其他目录"
MOVE_TO_DIALOG_OK = "确定"
MOVE_TO_DIALOG_CANCEL = "取消"
MOVE_TO_DIALOG_RECENT_LABEL = "最近目标："

# 创建 Mod 组对话框
CREATE_MOD_GROUP_DIALOG_TITLE = "创建 Mod 组"
CREATE_MOD_GROUP_DIALOG_LABEL = "请选择或输入 Mod 组名称："
CREATE_MOD_GROUP_OPTION_PURE = "纯 Mod 名：{name}"
CREATE_MOD_GROUP_OPTION_FULL = "完整原名：{name}"
CREATE_MOD_GROUP_DEFAULT_OK = "已创建 Mod 组：{name}"
CREATE_MOD_GROUP_MULTI_OK = "已创建 Mod 组「{name}」，共 {count} 个文件移入"
CREATE_MOD_GROUP_MULTI_PARTIAL = "创建 Mod 组完成：成功 {ok} 个，失败 {fail} 个"
CREATE_MOD_GROUP_FAILED = "创建 Mod 组失败"

# 标记/取消标记状态提示
MARK_CONTENT_UNIT_OK = "已标记为内容单元"
UNMARK_CONTENT_UNIT_OK = "已取消内容单元标记"
BATCH_MARK_CONTENT_UNIT_OK = "已批量标记 {count} 个文件"
BATCH_UNMARK_CONTENT_UNIT_OK = "已批量取消 {count} 个内容单元标记"
MARK_CONTENT_UNIT_FAILED = "标记失败"
UNMARK_CONTENT_UNIT_FAILED = "取消标记失败"
BATCH_MARK_CONTENT_UNIT_FAILED = "批量标记失败"
BATCH_UNMARK_CONTENT_UNIT_FAILED = "批量取消标记失败"

# 装配面板（阶段 3 Task 4）
# UX 重构 Phase 1 Task 2：移除 ASSEMBLY_PANEL_CLOSE_BUTTON（B1-1 关闭按钮已删）
# UI 术语（2026-08-02，UI合理性1）：显示名已改为「文件夹预览」。
# 代码标识符保留 Assembly*/assembly_* 命名（legacy），待 UX 重构 Task 8 统一改名。
ASSEMBLY_PANEL_TITLE = "文件夹预览"
ASSEMBLY_PANEL_HINT = "当前 Mod 组：{name}"
# UX 重构 Phase 1 Task 2：非内容单元文件夹透视时的提示文案
ASSEMBLY_PANEL_FOLDER_HINT = "当前文件夹：{name}"
ASSEMBLY_PANEL_EMPTY = "无固定内容"
ASSEMBLY_MENU_RENAME_COVER = "重命名为与 Mod 组同名"
ASSEMBLY_MENU_COPY_PATH = "复制路径"
# UX 重构 Phase 1 Task 2 Commit 2：空白处移动整个透视文件夹
ASSEMBLY_MENU_MOVE_FOLDER = "移动到..."
# UX 重构 Phase 1 Task 2（B2-2）：移除 ASSEMBLY_ADD_FILE_OK/FAILED，加入装配功能已删
ASSEMBLY_RENAME_COVER_OK = "已重命名为：{name}"
ASSEMBLY_RENAME_COVER_FAILED = "重命名失败"
ASSEMBLY_NOT_IMAGE_HINT = "仅图片文件可重命名为 Mod 组同名。"
# UX 重构 Phase 1 Task 3：📌 钉住功能
# B3 决策：钉住时切换图标（📌 → 📍），未钉住时显示 📌
ASSEMBLY_PIN_BUTTON_UNPINNED = "📌"
ASSEMBLY_PIN_BUTTON_PINNED = "📍"
ASSEMBLY_PIN_TOOLTIP_UNPINNED = "钉住当前文件夹"
ASSEMBLY_PIN_TOOLTIP_PINNED = "取消钉住"
ASSEMBLY_PIN_STATUS_PINNED = "已钉住：{name}"
ASSEMBLY_PIN_STATUS_UNPINNED_FOLLOW = "已取消钉住，跟随中栏选中"

# 添加到钉住文件夹（UX 重构 Phase 1 Task 4）
MENU_ADD_TO_PINNED = "添加到钉住文件夹"
# UX 重构 Phase 2 Task 5（Q2=C）：钉住/取消钉住右键菜单项
MENU_PIN_FOLDER = "钉住此文件夹"
MENU_UNPIN_FOLDER = "取消钉住"
MENU_PIN_REPLACE_HINT = "已有钉住文件夹，将替换为当前选择"
# UX 重构 Phase 2 Task 5（Q5=B）：刷新按钮 + F5
REFRESH_BUTTON = "↻"
REFRESH_BUTTON_TOOLTIP = "刷新当前目录（F5）"
REFRESH_NO_DIR = "未选择目录"
REFRESH_DONE = "已刷新当前目录"
ADD_TO_PINNED_OK = "已添加 {n} 个文件到「{name}」"
ADD_TO_PINNED_FAILED = "添加到钉住文件夹失败"
ADD_TO_PINNED_PARTIAL = "部分文件添加失败（成功 {ok}，失败 {fail}）"

# 拖拽到文件夹（UX 重构 Phase 1 Task 4）
DROP_TO_FOLDER_OK = "已移动 {n} 个文件到「{name}」"
DROP_TO_FOLDER_FAILED = "拖拽移动失败"
DROP_TO_FOLDER_PARTIAL = "部分文件移动失败（成功 {ok}，失败 {fail}）"

# 元数据面板区域
METADATA_GROUP_TITLE = "元数据"
METADATA_NOT_SELECTED = "单击内容单元查看元数据。"
METADATA_NOT_CONTENT_UNIT = "此项不是内容单元，无元数据。"
METADATA_TITLE_LABEL = "标题"
METADATA_PATH_LABEL = "路径"
METADATA_TYPE_LABEL = "类型"
METADATA_SOURCE_URL_LABEL = "来源 URL"
METADATA_NOTES_LABEL = "备注"
METADATA_CREATED_AT_LABEL = "创建时间"
METADATA_NOTES_EMPTY = "（无）"
METADATA_SOURCE_URL_EMPTY = "（无）"

# MetadataPanel 编辑表单（Stage 4 Task 2）
METADATA_PANEL_SAVE_BUTTON = "保存"
METADATA_PANEL_SAVING = "保存中…"
METADATA_PANEL_PICK_COVER_BUTTON = "设置封面"
METADATA_PANEL_PICK_COVER_TOOLTIP = "从内容单元目录内选择一张图片作为封面"
METADATA_PANEL_CLEAR_COVER_BUTTON = "清除封面"
METADATA_PANEL_TAG_INPUT_HINT = "输入标签名后回车添加，前缀自动补全"
METADATA_PANEL_TAG_INPUT_PLACEHOLDER = "输入标签名（回车添加）…"
METADATA_PANEL_PRESET_TAGS_LABEL = "已有标签（点击快速添加）"
METADATA_PANEL_PRESET_TAGS_EMPTY_HINT = "（暂无可用标签，可在标签管理中创建）"
METADATA_PANEL_RECENT_TAGS_LABEL = "最近使用："
METADATA_PANEL_RECENT_TAGS_EMPTY_HINT = "（暂无最近使用的标签）"
METADATA_PANEL_NO_UNIT_HINT = "请在文件列表选中一个内容单元查看元数据。"
METADATA_PANEL_SAVE_OK = "元数据已保存"
METADATA_PANEL_SAVE_FAILED = "保存失败"
METADATA_PANEL_TAG_NOT_FOUND = "标签「{name}」不存在，请先在标签管理中创建。"
METADATA_PANEL_COVER_NONE = "（未设置）"
METADATA_PANEL_TITLE_PLACEHOLDER = ""
METADATA_PANEL_SOURCE_URL_PLACEHOLDER = "https://www.nexusmods.com/skyrim/..."
METADATA_PANEL_NOTES_PLACEHOLDER = "备注…"
METADATA_PANEL_TAGS_LABEL = "标签"
METADATA_PANEL_COVER_LABEL = "封面"
METADATA_PANEL_COVER_PREVIEW_PLACEHOLDER = "（无预览）"
METADATA_PANEL_INVALID_TAG_NAME = "标签名称不能为空或仅含空白。"
METADATA_PANEL_DUPLICATE_TAG = "标签「{name}」已添加。"
METADATA_PANEL_TAG_REMOVED = "已移除标签「{name}」"
METADATA_PANEL_TAG_LIST_HEIGHT = 28  # 标签 chip 区单行高度（可手动调整）
METADATA_PANEL_PRESET_SCROLL_HEIGHT = 240  # 已有标签区高度（可手动调整）
METADATA_PANEL_NOTES_EDIT_HEIGHT = 60  # 备注编辑框高度（可手动调整）

# 元数据/装配面板统一区域样式模板（Task 8 主题化前的最小统一）。
# 背景用 {bg} 占位：运行时取系统 palette Base 色（与左栏受管理根目录列表 / 目录树
# 内部矩形、输入框一致的颜色）。
# 圆角：Qt 的 border-radius 仅在声明边框时才对背景生效，因此用与背景同色的
# 1px 边框（视觉无边框线）使圆角正常渲染。
PANEL_REGION_OBJECT_NAME = "scwPanelRegion"
PANEL_REGION_STYLE_TEMPLATE = (
    "QWidget#{obj} {{ background: {bg}; border: 1px solid {bg}; border-radius: 4px; }}"
    "QScrollArea#{obj} > QWidget > QWidget {{ background: transparent; }}"
)
# 区块小标题（「最近使用」「已有标签」等）：独立成行、无背景、字号稍小
PANEL_SECTION_TITLE_STYLE = "font-size: 11px; color: #888;"
# 标签按钮本身：背景跟随容器 {bg}（与区块同色），浅灰边框区分，避免白底白字
METADATA_TAG_BUTTON_STYLE = (
    "QPushButton {{ background: {bg}; border: 1px solid #c0c0c0; "
    "border-radius: 4px; padding: 2px 8px; }}"
)

# BatchTagDialog 批量打标签对话框（Stage 4 Task 2）
BATCH_TAG_DIALOG_TITLE = "批量打标签"
BATCH_TAG_DIALOG_TARGET_HINT = "目标内容单元数：{count}"
BATCH_TAG_DIALOG_TAG_INPUT_PLACEHOLDER = "输入标签名（回车添加）…"
BATCH_TAG_DIALOG_TAG_INPUT_HINT = "输入标签名后回车添加，前缀自动补全"
BATCH_TAG_DIALOG_PRESET_TAGS_LABEL = "已有标签（点击快速添加）"
BATCH_TAG_DIALOG_PRESET_TAGS_EMPTY_HINT = "（暂无可用标签，可在标签管理中创建）"
BATCH_TAG_DIALOG_TAGS_LABEL = "本次操作的标签"
BATCH_TAG_DIALOG_EMPTY_TAGS_HINT = "（未添加标签）"
BATCH_TAG_DIALOG_TAG_NOT_FOUND = "标签「{name}」不存在，请先在标签管理中创建。"
BATCH_TAG_DIALOG_INVALID_TAG_NAME = "标签名称不能为空或仅含空白。"
BATCH_TAG_DIALOG_DUPLICATE_TAG = "标签「{name}」已添加。"
BATCH_TAG_DIALOG_ADD_BUTTON = "添加标签"
BATCH_TAG_DIALOG_REMOVE_BUTTON = "移除标签"
BATCH_TAG_DIALOG_OK = "应用"
BATCH_TAG_DIALOG_CANCEL = "取消"
BATCH_TAG_DIALOG_RESULT_TITLE = "批量打标签结果"
BATCH_TAG_DIALOG_RESULT_TEXT = "已为 {count} 个内容单元{action}标签「{name}」"
BATCH_TAG_DIALOG_NO_TAGS = "请先添加至少一个标签。"

# CoverPickerDialog 封面选择对话框（Stage 4 Task 2）
COVER_PICKER_DIALOG_TITLE = "选择封面"
COVER_PICKER_DIALOG_HINT = "从内容单元目录内选择一张图片作为封面"
COVER_PICKER_DIALOG_EMPTY = "内容单元目录下未找到支持的图片格式。"
COVER_PICKER_DIALOG_OK = "确定"
COVER_PICKER_DIALOG_CANCEL = "取消"
COVER_PICKER_DIALOG_NO_SELECTION = "请先选中一张图片。"

# 标签管理对话框（阶段 4 Task 1）
TAG_MANAGER_BUTTON = "标签管理"
TAG_MANAGER_DIALOG_TITLE = "标签管理"
TAG_MANAGER_TOOLTIP = "管理标签分类与标签，支持 JSON 导入导出"
TAG_MANAGER_ADD_CATEGORY = "新增分类"
TAG_MANAGER_DELETE_CATEGORY = "删除分类"
TAG_MANAGER_RENAME_CATEGORY = "重命名分类"
TAG_MANAGER_CHANGE_COLOR = "改颜色"
TAG_MANAGER_ADD_TAG = "新增标签"
TAG_MANAGER_DELETE_TAG = "删除标签"
TAG_MANAGER_RENAME_TAG = "重命名标签"
TAG_MANAGER_MOVE_TAG = "移动到分类..."
TAG_MANAGER_IMPORT_APPEND = "追加导入"
TAG_MANAGER_IMPORT_OVERWRITE = "覆盖导入"
TAG_MANAGER_EXPORT = "导出 JSON"
TAG_MANAGER_CLOSE = "关闭"
TAG_MANAGER_ROOT_HINT = "所有标签分类"
TAG_MANAGER_EMPTY_HINT = "尚无标签分类。点击「新增分类」或「追加导入」开始。"
TAG_MANAGER_NO_SELECTION = "请先在左侧选择一项。"
TAG_MANAGER_NO_CATEGORY_SELECTED = "请先选择一个分类。"
TAG_MANAGER_NO_TAG_SELECTED = "请先选择一个标签。"
TAG_MANAGER_EMPTY_NAME_TITLE = "名称不能为空"
TAG_MANAGER_EMPTY_NAME_TEXT = "名称不能为空或仅含空白字符，请重新输入。"

# 标签管理 - 输入对话框
TAG_INPUT_CATEGORY_TITLE = "新增标签分类"
TAG_INPUT_CATEGORY_LABEL = "请输入分类名称："
TAG_INPUT_CATEGORY_COLOR_LABEL = "色相值（0-360）："
TAG_INPUT_TAG_TITLE = "新增标签"
TAG_INPUT_TAG_LABEL = "请输入标签名称："
TAG_INPUT_RENAME_CATEGORY_TITLE = "重命名分类"
TAG_INPUT_RENAME_TAG_TITLE = "重命名标签"
TAG_INPUT_MOVE_TAG_TITLE = "移动标签到分类"
TAG_INPUT_MOVE_TAG_LABEL = "请选择目标分类："
TAG_COLOR_DIALOG_TITLE = "选择分类颜色"

# 标签管理 - 确认对话框
TAG_CONFIRM_DELETE_CATEGORY_TITLE = "确认删除分类"
TAG_CONFIRM_DELETE_CATEGORY_TEXT = (
    "将删除分类「{name}」及其下所有标签：\n\n"
    "标签数：{tag_count}\n"
    "受影响的内容单元关联：{link_count}\n\n"
    "此操作不可撤销，是否继续？"
)
TAG_CONFIRM_DELETE_TAG_TITLE = "确认删除标签"
TAG_CONFIRM_DELETE_TAG_TEXT = (
    "将删除标签「{name}」。\n\n受影响的内容单元关联：{link_count}\n\n此操作不可撤销，是否继续？"
)
TAG_CONFIRM_OVERWRITE_IMPORT_TITLE = "确认覆盖导入"
TAG_CONFIRM_OVERWRITE_IMPORT_TEXT = (
    "覆盖导入将先删除当前所有标签分类与标签，再从 JSON 文件导入。\n\n"
    "当前标签分类数：{category_count}\n"
    "当前标签总数：{tag_count}\n\n"
    "此操作不可撤销，是否继续？"
)

# 标签管理 - 操作结果提示
TAG_OP_OK = "操作成功"
TAG_OP_FAILED = "操作失败"
TAG_IMPORT_OK_TITLE = "导入完成"
TAG_IMPORT_OK_TEXT = (
    "导入完成：\n\n"
    "新增分类：{created_categories}\n"
    "跳过分类：{skipped_categories}\n"
    "新增标签：{created_tags}\n"
    "跳过标签：{skipped_tags}"
)
TAG_EXPORT_OK_TITLE = "导出完成"
TAG_EXPORT_OK_TEXT = "标签库已导出到：\n{path}"
TAG_IMPORT_FILE_FILTER = "JSON 文件 (*.json)"
TAG_EXPORT_FILE_FILTER = "JSON 文件 (*.json)"

# 错误
ERR_ADD_ROOT_FAILED = "添加目录失败"
ERR_NO_ROOT_SELECTED = "请先在左侧选择一个受管理根目录。"
ERR_DUPLICATE_ROOT = "该目录已添加。"
ERR_INVALID_ROOT = "路径不存在或不是目录。"
ERR_REMOVE_ROOT_FAILED = "移除目录配置失败"

# 数据库错误提示（TD-M11）
DB_COMMIT_FAILED_TITLE = "数据库提交失败"
DB_COMMIT_FAILED_MESSAGE = "数据未能保存到数据库，请查看日志。最近的操作可能未持久化。"


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


# TagFilterBar 标签筛选栏（Stage 4 Task 3）
TAG_FILTER_BAR_TITLE = "标签筛选"
TAG_FILTER_BAR_HINT = "点击分类展开标签，多选筛选。同分类为或，跨分类为与。"
TAG_FILTER_CLEAR_BUTTON = "清除全部"
TAG_FILTER_NO_CATEGORIES_HINT = "（暂无标签分类，请在标签管理中创建）"
TAG_FILTER_CATEGORY_EMPTY_HINT = "（该分类下无标签）"
TAG_FILTER_NO_RESULT_HINT = "没有找到匹配内容"
TAG_FILTER_CATEGORY_BADGE = " ({count})"  # 折叠态下分类按钮显示的已选标签数徽标

# 视图切换（Stage 5 Task 1）
VIEW_SWITCH_GROUP_LABEL = "视图"
VIEW_SWITCH_LIST = "列表"
VIEW_SWITCH_CARD = "卡片"
VIEW_SWITCH_LIST_TOOLTIP = "切换到详细列表视图（4 列：名称/类型/大小/修改日期）"
VIEW_SWITCH_CARD_TOOLTIP = "切换到大图卡片视图（仅显示封面 + 名称）"
ZOOM_SLIDER_LABEL = "缩放"
ZOOM_SLIDER_TOOLTIP = "选择卡片图标尺寸（仅卡片视图生效）"
# Task 1b 修正：滑块改为下拉框预选尺寸，避免拖动时频繁重绘原图
ZOOM_PRESET_SIZES = [96, 128, 160, 192, 224, 256]
ZOOM_SLIDER_DEFAULT = 160

# 右栏封面预览（Task 1b 修正：统一加载原图，宽度跟随右栏自适应）
COVER_PREVIEW_DEFAULT_WIDTH = 128  # 初始宽度（resize 后跟随右栏）
COVER_PREVIEW_MAX_HEIGHT = 300  # 最大高度（避免超长图占据整个右栏）
COVER_PREVIEW_PLACEHOLDER_HEIGHT = 96  # 无图时占位高度（显示边框）

# CardListModel 卡片名称 ToolTip 中内容单元标记文本
# Stage 5 Task 7 收尾：status 仅 organized/unmarked 两态，unmarked 不显示标记。
CARD_TOOLTIP_CONTENT_UNIT = "内容单元"
CARD_TOOLTIP_SEPARATOR = " | "

# Stage 5 Task 2：列头方向指示符号（Q1=A 文本方案）
SORT_ASC_SYMBOL = "▲"
SORT_DESC_SYMBOL = "▼"

# Stage 5 Task 2：排序下拉框（Q2=A 列表/卡片视图共享）
SORT_FIELD_LABEL = "排序"
SORT_FIELD_TOOLTIP = "选择排序字段（列表/卡片视图共享）"
SORT_FIELD_NAME = "名称"
SORT_FIELD_TYPE = "类型"
SORT_FIELD_SIZE = "大小"
SORT_FIELD_MODIFIED = "修改日期"
# 排序方向按钮
SORT_DIRECTION_ASC_TOOLTIP = "升序（点击切换为降序）"
SORT_DIRECTION_DESC_TOOLTIP = "降序（点击切换为升序）"

# Stage 5 Task 2：前进/后退目录导航
NAV_BACK_TOOLTIP = "后退（上一个目录）"
NAV_FORWARD_TOOLTIP = "前进（下一个目录）"

# Stage 5 Task 2 验收修复：卡片固定尺寸 + 文本 elide
# 卡片网格单元尺寸 = icon_size + 水平/垂直 padding
CARD_GRID_PADDING_H = 24  # 文本左右内边距合计
CARD_GRID_PADDING_V = 32  # 文本区域高度 + 上下内边距
# 文本 elide 宽度 = icon_size - 文本左右 padding
CARD_TEXT_PADDING_H = 8  # 文本两侧 padding 合计

# Stage 5 Task 7：全局搜索
SEARCH_BOX_PLACEHOLDER = "搜索标题、标签、备注…（回车搜索）"
SEARCH_DIALOG_TITLE = "搜索结果"
SEARCH_DIALOG_TITLE_WITH_QUERY = "搜索「{query}」结果（{count} 项）"
SEARCH_DIALOG_EMPTY = "未找到匹配的内容单元"
SEARCH_DIALOG_ERROR = "搜索失败：{error}"
SEARCH_COL_TITLE = "标题"
SEARCH_COL_PATH = "路径"
SEARCH_COL_MATCHED_FIELD = "匹配字段"
SEARCH_COL_TAGS = "标签"
SEARCH_MATCHED_FIELD_TITLE = "标题"
SEARCH_MATCHED_FIELD_TAG = "标签"
SEARCH_MATCHED_FIELD_NOTES = "备注"
SEARCH_JUMP_TOOLTIP = "双击跳转到所在目录"
