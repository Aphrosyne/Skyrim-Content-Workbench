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
TREE_ARCHIVE_ROOT_HINT = "〔归档〕"
TREE_ARCHIVE_ROOT_TOOLTIP = "归档根目录"

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
# UI合理性12（2026-08-03）：标记前置 + 缩写为 --（双短横线，验收反馈逐次调整），
# 长文件名截断时标记不被遮挡。
# UI合理性13（2026-08-04）：-- 改为 🔗（链节图标，用户选型 B），
# 显示模板固定为「标记 + 空格 + 名称」，避免图标与名字贴太近。
CONTENT_UNIT_MARKER = "🔗"

# 内容单元行左侧淡紫色色条（UI合理性13 方案 C，辅助区分）
CONTENT_UNIT_STRIPE_COLOR = "#B39DDB"
CONTENT_UNIT_STRIPE_WIDTH = 3
# 行首 🔗 徽章（UI合理性13 方案 B，2026-08-04）：
# 🔗 不拼进名称文本（emoji 字体回退会抬高行高度量，导致文字垂直偏移约 1px），
# 改为 delegate 在预留区绘制位图徽章。
CONTENT_UNIT_BADGE_SIZE = 14
CONTENT_UNIT_BADGE_LEADING_GAP = 2  # 色条 → 徽章
CONTENT_UNIT_BADGE_TRAILING_GAP = 4  # 徽章 → 图标
# 预留区总宽由 ContentUnitMarkerConfig.reserved_width 按启用组合自动派生
# （UI合理性21：仅色条 5 / 仅图标 18 / 双启用 23）。

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
# 操作便捷性8（2026-08-04）：N 网网址
MENU_AUTOFILL_URL = "自动填入网址"
MENU_OPEN_URL = "打开网址"
# 操作便捷性9（2026-08-04）：快速浏览器搜索
MENU_BROWSER_SEARCH = "浏览器搜索"
MENU_OPEN_IN_EXPLORER = "在资源管理器中打开"
MENU_OPEN_IN_EXPLORER_FAILED = "无法打开资源管理器"
# UX 重构 Phase 2 Task 5：右键「打开」项（行为与双击一致）
MENU_OPEN = "打开"
MENU_COLLAPSE_ALL = "折叠全部"

# 操作便捷性2（2026-08-04）：中栏内部拖拽目标高亮颜色
DROP_TARGET_HIGHLIGHT_COLOR = "#3D7EFF"

# 输入控件右键菜单（中文化，2026-08-04 验收反馈）
INPUT_MENU_COPY = "复制"
INPUT_MENU_CUT = "剪切"
INPUT_MENU_PASTE = "粘贴"
INPUT_MENU_SELECT_ALL = "全选"

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

# 操作便捷性1（2026-08-04）：剥离（提取内容）
MENU_STRIP_FOLDER = "提取内容"
STRIP_CONFIRM_TITLE = "确认提取内容"
STRIP_CONFIRM_TEXT = (
    "将把「{name}」内的 {count} 个条目提取到上级目录「{parent}」。\n"
    "提取完成后该文件夹（已为空）将移至回收站。\n"
    "此操作不可撤销。\n是否继续？"
)
STRIP_FAILED = "提取内容失败"
STRIP_OK = "已提取 {n} 个条目到上级目录"
STRIP_PARTIAL = "提取内容完成：成功 {ok} 项，失败 {fail} 项"

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
# 操作便捷性1（2026-08-04）：剥离（提取内容）
HISTORY_DESC_STRIP = "提取内容：{source} → {target}（不可撤销）"
HISTORY_DESC_UNKNOWN = "未知操作：{op}"
# 操作类型中文名映射（操作历史对话框操作列显示）
HISTORY_OP_LABELS = {
    "new_folder": "新建文件夹",
    "rename": "重命名",
    "move": "移动",
    "delete": "删除",
    "copy": "复制",
    "strip": "提取内容",
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

# 功能增加1（2026-08-04）：归档
MENU_ARCHIVE_QUICK = "快速归档"
MENU_ARCHIVE_TO = "归档到…"
MENU_MARK_ARCHIVE_ROOT = "标记为归档根目录"
MENU_UNMARK_ARCHIVE_ROOT = "取消归档根目录标记"
MENU_GENERATE_ARCHIVE_MANIFEST = "生成归档内容清单"
ARCHIVE_OK = "已归档 {n} 项到 {dir_name}"
ARCHIVE_PARTIAL = "部分归档失败：成功 {ok} 项，失败 {fail} 项"
ARCHIVE_FAILED = "归档失败"
ARCHIVE_NO_SELECTION = "未选中任何条目"
ARCHIVE_NO_LAST_TARGET = "暂无上次归档位置，请先使用「归档到…」选择一次目标"
ARCHIVE_MARKED = "已标记为归档根目录"
ARCHIVE_MARKED_WITH_CLEANUP = "已标记为归档根目录，并清理其下 {n} 条内容单元标记"
ARCHIVE_UNMARKED = "已取消归档根目录标记"
ARCHIVE_MANIFEST_OK = "已生成归档内容清单：{path}"
ARCHIVE_MANIFEST_FAILED = "生成归档内容清单失败：{error}"

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
# 操作合理性5（2026-08-04）：创建 Mod 组继承源单元元数据
CREATE_MOD_GROUP_INHERITED_HINT = "（已继承来源/备注/标签）"

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
# UI合理性13：原标题栏改为重命名用途（回车保存，不走元数据保存按钮）
METADATA_RENAME_LABEL = "重命名"
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
METADATA_PANEL_COVER_SAVED = "封面已保存"
METADATA_PANEL_SAVE_FAILED = "保存失败"
METADATA_PANEL_TAG_NOT_FOUND = "标签「{name}」不存在，请先在标签管理中创建。"
METADATA_PANEL_COVER_NONE = "（未设置）"
METADATA_PANEL_RENAME_PLACEHOLDER = "输入新名称后回车重命名"
METADATA_PANEL_RENAME_TOOLTIP = "输入新名称后回车直接重命名文件/文件夹，不经过「保存」按钮"
METADATA_PANEL_SOURCE_URL_PLACEHOLDER = "https://www.nexusmods.com/..."
METADATA_PANEL_NOTES_PLACEHOLDER = "备注…"
METADATA_PANEL_TAGS_LABEL = "标签"
METADATA_PANEL_COVER_LABEL = "封面"
METADATA_PANEL_COVER_PREVIEW_PLACEHOLDER = "（无预览）"
# 操作合理性2（2026-08-03）：元数据面板图片预览（未标记图片文件，直接显示原图）
METADATA_PANEL_IMAGE_PREVIEW_TITLE = "图片预览"
METADATA_PANEL_INVALID_TAG_NAME = "标签名称不能为空或仅含空白。"
METADATA_PANEL_DUPLICATE_TAG = "标签「{name}」已添加。"
METADATA_PANEL_TAG_REMOVED = "已移除标签「{name}」"
METADATA_PANEL_TAG_LIST_HEIGHT = 28  # 标签 chip 区单行高度（可手动调整）
METADATA_PANEL_PRESET_SCROLL_HEIGHT = 240  # 已有标签区高度（可手动调整）
METADATA_PANEL_PRESET_SCROLL_MIN_HEIGHT = 60  # 已有标签区高度拖动下限（操作合理性2，2026-08-03）
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

# BatchTagDialog 批量打标签对话框（Stage 4 Task 2）
BATCH_TAG_DIALOG_TITLE = "批量打标签"
BATCH_TAG_DIALOG_TARGET_HINT = "目标内容单元数：{count}"
BATCH_TAG_DIALOG_PRESET_TAGS_LABEL = "已有标签（点击快速添加）"
BATCH_TAG_DIALOG_PRESET_TAGS_EMPTY_HINT = "（暂无可用标签，可在标签管理中创建）"
BATCH_TAG_DIALOG_TAGS_LABEL = "本次操作的标签"
BATCH_TAG_DIALOG_CHIP_AREA_HEIGHT = 84  # chip 区高度（UI合理性12 重构）
BATCH_TAG_DIALOG_SEARCH_PLACEHOLDER = "搜索标签…（输入即过滤）"
BATCH_TAG_DIALOG_SEARCH_TOOLTIP = "按名称过滤预选标签，点击快速添加"
BATCH_TAG_DIALOG_CHIP_REMOVE_TOOLTIP = "点击移除该标签"
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
TAG_COLOR_SLIDER_LABEL = "色相："
TAG_COLOR_DIALOG_OK = "确定"
TAG_COLOR_DIALOG_CANCEL = "取消"

# 分类色填充样式模板（BugFix2 验收反馈，2026-08-03）：{color} 为分类色 hex，
# {text} 为按分类色相对亮度自动选择的黑/白文字色；背景与边框统一分类色。
TAG_BUTTON_FILLED_STYLE = (
    "QPushButton {{ background: {color}; border: 1px solid {color}; color: {text}; "
    "border-radius: 4px; padding: 2px 8px; }}"
)

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
TAG_FILTER_BAR_HINT = "点击分类展开标签：单击选中，再点反选（排除），第三次取消。"
TAG_FILTER_CLEAR_BUTTON = "清除全部"
TAG_FILTER_EXCLUDED_TOOLTIP = "反选：筛选除该标签外的全部内容"
TAG_FILTER_NO_CATEGORIES_HINT = "（暂无标签分类，请在标签管理中创建）"
TAG_FILTER_CATEGORY_EMPTY_HINT = "（该分类下无标签）"
TAG_FILTER_NO_RESULT_HINT = "没有找到匹配内容"
TAG_FILTER_CATEGORY_BADGE = " {count}"  # 折叠态下分类按钮显示的已选标签数徽标（无括号，防过宽）
TAG_FILTER_CATEGORY_BADGE_RESERVE = " 99"  # 徽标宽度预留（空格 + 两位数字，防按钮宽度跳动）

# 封面筛选（操作便捷性5，2026-08-03）：切换按钮，不持久化
COVER_FILTER_BUTTON = "只看有封面"
COVER_FILTER_TOOLTIP = "按下后仅显示已设置封面的内容单元"

# 视图切换（Stage 5 Task 1）
VIEW_SWITCH_GROUP_LABEL = "视图"
VIEW_SWITCH_LIST = "列表"
VIEW_SWITCH_CARD = "卡片"
VIEW_SWITCH_LIST_TOOLTIP = "切换到详细列表视图（4 列：名称/类型/大小/修改日期）"
VIEW_SWITCH_CARD_TOOLTIP = "切换到大图卡片视图（仅显示封面 + 名称）"
ZOOM_SLIDER_LABEL = "缩放"
ZOOM_SLIDER_TOOLTIP = "选择图标尺寸（列表/卡片视图各自生效）"
# Task 1b 修正：滑块改为下拉框预选尺寸，避免拖动时频繁重绘原图
ZOOM_PRESET_SIZES = [96, 128, 160, 192, 224, 256]
ZOOM_SLIDER_DEFAULT = 160
# UI合理性19（2026-08-04）：列表视图图标尺寸档位（六档，与卡片模式同数量；
# 默认 16 保持紧凑）。行高 = 图标尺寸 + LIST_ROW_PADDING_V。
# 验收反馈（2026-08-04）：档位调整为 16/20/24/28/32/36。
LIST_ICON_PRESET_SIZES = [16, 20, 24, 28, 32, 36]
LIST_ICON_DEFAULT = 16
LIST_ROW_PADDING_V = 8

# 文件类型图标颜色（UI合理性4 验收反馈，2026-08-04）
# 键对应 file_type_icons 的类型键（folder/archive/image/document）。
# 默认值；运行时可通过「视图 → 文件类型图标颜色…」自定义（QSettings 持久化）。
FILE_TYPE_ICON_COLORS = {
    "folder": "#f6e03b",  # 文件夹（黄）
    "archive": "#72e9a1",  # 压缩包（浅绿，用户验收后调整值）
    "image": "#8ab8e6",  # 图片（浅蓝）
    "document": "#ffffff",  # 其他文档（白；若切浅色主题可能看不清，可改为主题文字色）
}

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
SORT_FIELD_TOOLTIP = "选择排序字段与升降序（列表/卡片视图共享）"
SORT_FIELD_NAME = "名称"
SORT_FIELD_TYPE = "类型"
SORT_FIELD_SIZE = "大小"
SORT_FIELD_MODIFIED = "修改日期"
# BugFix3（2026-08-04）：下拉框内升降序项（资源管理器式）
SORT_DIRECTION_ASC_LABEL = "升序 ▲"
SORT_DIRECTION_DESC_LABEL = "降序 ▼"

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
# UI合理性13：搜索范围由标题改为文件名
SEARCH_BOX_PLACEHOLDER = "搜索名称、标签、备注…（回车搜索）"
SEARCH_DIALOG_TITLE = "搜索结果"
SEARCH_DIALOG_TITLE_WITH_QUERY = "搜索「{query}」结果（{count} 项）"
SEARCH_DIALOG_EMPTY = "未找到匹配的内容单元"
SEARCH_DIALOG_ERROR = "搜索失败：{error}"
SEARCH_COL_NAME = "名称"
SEARCH_COL_PATH = "路径"
SEARCH_COL_MATCHED_FIELD = "匹配字段"
SEARCH_COL_TAGS = "标签"
SEARCH_MATCHED_FIELD_NAME = "名称"
SEARCH_MATCHED_FIELD_TAG = "标签"
SEARCH_MATCHED_FIELD_NOTES = "备注"
SEARCH_JUMP_TOOLTIP = "双击跳转到所在目录"

# === QSettings 配置键（UI合理性2/3，2026-08-03 从 main_window 迁移至此） ===
QSETTINGS_KEY_ZOOM = "view/card_icon_size"
QSETTINGS_KEY_LIST_ICON_SIZE = "view/list_icon_size"
QSETTINGS_KEY_VIEW_MODE = "view/current_mode"  # "list" | "card"
QSETTINGS_KEY_SPLITTER_MAIN = "layout/splitter/main"
QSETTINGS_KEY_SPLITTER_RIGHT = "layout/splitter/right"
QSETTINGS_KEY_HEADER_FILE_LIST = "layout/header/file_list"
QSETTINGS_KEY_HEADER_OPERATION_HISTORY = "layout/header/operation_history"
# 内容单元标记配置（UI合理性21，2026-08-04）
QSETTINGS_KEY_MARKER_ICON_ENABLED = "marker/icon_enabled"
QSETTINGS_KEY_MARKER_ICON_GLYPH = "marker/icon_glyph"
QSETTINGS_KEY_MARKER_STRIPE_ENABLED = "marker/stripe_enabled"
QSETTINGS_KEY_MARKER_STRIPE_COLOR = "marker/stripe_color"
# 网址与搜索配置（操作便捷性8/9，2026-08-04）
QSETTINGS_KEY_URL_NEXUS_PREFIX = "url/nexus_url_prefix"
QSETTINGS_KEY_URL_SEARCH_ENGINE = "url/search_engine_url"
QSETTINGS_KEY_URL_SEARCH_PREFIX = "url/search_prefix"
# 归档设置（功能增加1，2026-08-04）
QSETTINGS_KEY_ARCHIVE_ROOT = "archive/root_path"
QSETTINGS_KEY_ARCHIVE_LAST_TARGET = "archive/last_target"
# 右键功能开关配置（设计合理性1，2026-08-04）
QSETTINGS_KEY_FEATURE_TOGGLE_PREFIX = "context_menu"
# 快捷键配置（2026-08-04，设计合理性1 附带）
QSETTINGS_KEY_SHORTCUT_PREFIX = "shortcut"
# === 布局默认值（UI合理性2/3，2026-08-03） ===
# 所有分割线/列宽默认值集中在此，用户可手动调整后重启生效。
# 注意：文件列表中"名称"列使用 Stretch 模式（自动吸收剩余宽度），
# 调整宽度请改其余三列的默认值（类型/大小/修改日期）。
LAYOUT_MAIN_SPLITTER_DEFAULT_SIZES = (220, 480, 324)  # 左栏 / 中栏 / 右栏
LAYOUT_RIGHT_SPLITTER_DEFAULT_SIZES = (625, 125)  # 元数据 / 装配面板（保持既有行为）
LAYOUT_OPERATION_HISTORY_COLUMN_WIDTHS = (180, 340, 90)  # 时间 / 操作 / 状态
FILE_LIST_COLUMN_WIDTHS = (
    320,
    60,
    80,
    150,
)  # 名称 / 类型 / 大小 / 修改日期（固定宽度，右侧留白供框选）

# === 顶部菜单栏（UI合理性3，2026-08-03） ===
MENU_BAR_VIEW = "视图"
MENU_BAR_TOOLS = "工具"
MENU_BAR_HELP = "帮助"
MENU_VIEW_LIST = "列表视图"
MENU_VIEW_CARD = "卡片视图"
MENU_VIEW_RESET_LAYOUT = "重置布局"
MENU_VIEW_CONTENT_UNIT_MARKER = "内容单元标记设置…"
MENU_VIEW_FILE_TYPE_ICON_COLORS = "文件类型图标颜色…"
MENU_VIEW_URL_SETTINGS = "网址与搜索设置…"
MENU_TOOLS_SETTINGS = "设置…"
MENU_TOOLS_TAG_MANAGER = "标签管理…"
MENU_TOOLS_OPERATION_HISTORY = "操作历史…"
LAYOUT_RESET_STATUS = "布局已重置为默认比例"

# === 开源资产致谢对话框（UI合理性4 资产引用，2026-08-04） ===
MENU_HELP_ASSET_CREDITS = "开源资产致谢…"
ASSET_CREDITS_DIALOG_TITLE = "开源资产致谢"
ASSET_CREDITS_HEADING = "本软件使用以下开源资产："
ASSET_CREDITS_ICON_PACK_NAME = "game-icon-pack"
ASSET_CREDITS_ICON_PACK_AUTHOR = "作者：Nieobie"
ASSET_CREDITS_ICON_PACK_SOURCE = "来源："
ASSET_CREDITS_ICON_PACK_SOURCE_URL = "https://github.com/Nieobie/game-icon-pack"
ASSET_CREDITS_ICON_PACK_LICENSE = "许可协议：CC0-1.0（公有领域）"
ASSET_CREDITS_ICON_PACK_LICENSE_URL = "https://github.com/Nieobie/game-icon-pack#CC0-1.0-1-ov-file"
ASSET_CREDITS_ICON_PACK_LOCAL = "本地归档：assets/third-party/game-icon-pack-v1.4-svg-zh/"
ASSET_CREDITS_THANKS = "感谢作者的无偿共享，让本软件得以呈现更清晰的图标。"
ASSET_CREDITS_CLOSE = "关闭"

# === 网址与搜索设置对话框（操作便捷性8/9，2026-08-04） ===
URL_SETTINGS_DIALOG_TITLE = "网址与搜索设置"
URL_SETTINGS_NEXUS_PREFIX_LABEL = "N 网网址前缀："
URL_SETTINGS_SEARCH_ENGINE_LABEL = "搜索引擎网址（无需 ?q= 参数）："
URL_SETTINGS_SEARCH_PREFIX_LABEL = "搜索前缀："
URL_SETTINGS_RESET = "恢复默认"
URL_SETTINGS_DEFAULT_NEXUS_PREFIX = "https://www.nexusmods.com/skyrimspecialedition/mods/"
URL_SETTINGS_DEFAULT_SEARCH_ENGINE = "https://www.bing.com/search"
URL_SETTINGS_DEFAULT_SEARCH_PREFIX = "skyrim "

# === 右键功能开关（设计合理性1，2026-08-04） ===
# group id -> 分组标题（配置界面分组显示）
FEATURE_TOGGLE_GROUPS = {
    "content_unit": "内容单元",
    "network": "网络与搜索",
    "archive": "归档",
    "file_ops": "文件操作",
    "view": "视图与其他",
}
# feature id -> 中文标签（菜单项文本一致）
FEATURE_TOGGLE_LABELS = {
    "create_mod_group": "创建 Mod 组",
    "mark_content_unit": "标记/取消标记内容单元（含批量）",
    "batch_tag": "批量打标签",
    "recent_tag": "添加最近标签",
    "autofill_url": "自动填入网址",
    "open_url": "打开网址",
    "browser_search": "浏览器搜索",
    "archive_quick": "快速归档",
    "archive_to": "归档到…",
    "mark_archive": "标记/取消归档根目录",
    "generate_manifest": "生成归档内容清单",
    "open": "打开",
    "new_folder": "新建文件夹",
    "rename": "重命名",
    "delete": "删除",
    "copy": "复制",
    "cut": "剪切",
    "paste": "粘贴",
    "move_to": "移动到…",
    "move_to_recent": "移动到最近目录",
    "strip": "提取内容",
    "add_to_pinned": "添加到钉住文件夹",
    "pin_folder": "钉住/取消钉住此文件夹",
    "open_in_explorer": "在资源管理器中打开",
    "copy_path": "复制路径",
    "collapse_all": "折叠全部",
}
# feature id -> group id
FEATURE_TOGGLE_GROUP_MAP = {
    "create_mod_group": "content_unit",
    "mark_content_unit": "content_unit",
    "batch_tag": "content_unit",
    "recent_tag": "content_unit",
    "autofill_url": "network",
    "open_url": "network",
    "browser_search": "network",
    "archive_quick": "archive",
    "archive_to": "archive",
    "mark_archive": "archive",
    "generate_manifest": "archive",
    "open": "file_ops",
    "new_folder": "file_ops",
    "rename": "file_ops",
    "delete": "file_ops",
    "copy": "file_ops",
    "cut": "file_ops",
    "paste": "file_ops",
    "move_to": "file_ops",
    "move_to_recent": "file_ops",
    "strip": "file_ops",
    "add_to_pinned": "view",
    "pin_folder": "view",
    "open_in_explorer": "view",
    "copy_path": "view",
    "collapse_all": "view",
}

# === 快捷键条目（2026-08-04，设计合理性1 附带） ===
# id -> 中文标签 / 默认按键 / 适用范围
SHORTCUT_LABELS = {
    "select_all": "全选（中栏）",
    "undo": "撤销",
    "rename": "重命名",
    "delete": "删除",
    "copy": "复制",
    "cut": "剪切",
    "paste": "粘贴",
    "move_to": "移动到…",
    "move_to_latest": "移动到最近目录",
    "archive_quick": "快速归档",
    "refresh": "刷新当前目录",
    "toggle_pin": "钉住/取消钉住文件夹预览",
}
SHORTCUT_DEFAULT_KEYS = {
    "select_all": "Ctrl+A",
    "undo": "Ctrl+Z",
    "rename": "F2",
    "delete": "Del",
    "copy": "Ctrl+C",
    "cut": "Ctrl+X",
    "paste": "Ctrl+V",
    "move_to": "Ctrl+M",
    "move_to_latest": "Ctrl+Q",
    "archive_quick": "Ctrl+W",
    "refresh": "F5",
    "toggle_pin": "Ctrl+P",
}
SHORTCUT_SCOPES = {
    "select_all": "中栏",
    "undo": "全局",
    "rename": "中栏 / 目录树 / 文件夹预览",
    "delete": "中栏 / 目录树 / 文件夹预览",
    "copy": "中栏 / 目录树 / 文件夹预览",
    "cut": "中栏 / 目录树 / 文件夹预览",
    "paste": "中栏 / 目录树 / 文件夹预览",
    "move_to": "中栏 / 目录树 / 文件夹预览",
    "move_to_latest": "中栏 / 目录树 / 文件夹预览",
    "archive_quick": "全局",
    "refresh": "全局",
    "toggle_pin": "全局",
}

# === 设置对话框（设计合理性1 + 快捷键配置，2026-08-04） ===
SETTINGS_DIALOG_TITLE = "设置"
SETTINGS_TAB_FEATURES = "右键功能"
SETTINGS_TAB_SHORTCUTS = "快捷键"
SETTINGS_FEATURES_HINT = "关闭后对应右键菜单项不再显示（立即生效）。"
SETTINGS_FEATURES_RESET = "全部启用"
SETTINGS_SHORTCUTS_HINT = "点击按键输入框后按下新组合；清空输入框 = 禁用该快捷键。"
SETTINGS_SHORTCUTS_COL_FEATURE = "功能"
SETTINGS_SHORTCUTS_COL_KEY = "快捷键"
SETTINGS_SHORTCUTS_COL_SCOPE = "适用范围"
SETTINGS_SHORTCUTS_RESET = "恢复默认"
SETTINGS_SHORTCUTS_CONFLICT_TOOLTIP = "该快捷键已同时分配给：{others}"
SETTINGS_SHORTCUTS_CONFLICT_BG = "#f8d7da"
SETTINGS_APPLIED = "设置已保存并生效"

# === 内容单元标记设置对话框（UI合理性21，2026-08-04） ===
MARKER_CONFIG_DIALOG_TITLE = "内容单元标记设置"
MARKER_CONFIG_ICON_ENABLED = "启用行首图标标记"
MARKER_CONFIG_ICON_LABEL = "标记字符（单个字符）"
MARKER_CONFIG_STRIPE_ENABLED = "启用左侧色条"
MARKER_CONFIG_STRIPE_LABEL = "色条颜色"
MARKER_CONFIG_RESET = "恢复默认"
MARKER_CONFIG_NEED_ONE = "图标标记和左侧色条至少要启用一个。"
MARKER_CONFIG_GLYPH_INVALID = "标记字符必须是单个字符。"

# === 文件类型图标颜色设置对话框（UI合理性4 二期，2026-08-04） ===
FILE_TYPE_ICON_COLORS_DIALOG_TITLE = "文件类型图标颜色"
FILE_TYPE_ICON_COLORS_HINT = "为不同文件类型图标选择颜色："
FILE_TYPE_ICON_COLORS_LABELS = {
    "folder": "文件夹",
    "archive": "压缩包",
    "image": "图标",
    "document": "其他文档",
}
FILE_TYPE_ICON_COLORS_RESET = "恢复默认"
QSETTINGS_KEY_ICON_COLOR_FOLDER = "icon_color/folder"
QSETTINGS_KEY_ICON_COLOR_ARCHIVE = "icon_color/archive"
QSETTINGS_KEY_ICON_COLOR_IMAGE = "icon_color/image"
QSETTINGS_KEY_ICON_COLOR_DOCUMENT = "icon_color/document"
