# Changelog

本项目遵循 [SemVer 2.0.0](https://semver.org/lang/zh-CN/) 语义化版本控制。

在 1.0.0 之前，0.MINOR.PATCH 中的 MINOR 用于标记里程碑推进（roadmap 阶段/Task），PATCH 用于同里程碑内的修复与小幅调整。任何可能影响用户数据或破坏已有功能的变化都会使 MINOR 递增。

## [Unreleased]

尚未发布的改动。开发期间此节用于汇总已完成但未标注版本标签的提交。

## [0.50.12] - 2026-08-04

**内容单元标记可配置（UI合理性21）**：
  - 新增 `ContentUnitMarkerConfig`（QSettings 键 `marker/*`）：行首徽章字符/开关、
    色条颜色/开关；`reserved_width` 按启用组合自动派生
    （仅色条 5 / 仅图标 18 / 双启用 23）；"至少启用一个"校验
  - 新增 `ContentUnitMarkerDialog`（顶部菜单「视图 → 内容单元标记设置…」）：
    字符输入（单个 Unicode 字符校验）、色条 QColorDialog（完整 hex）、恢复默认、
    确定后立即生效；验收反馈：字符/颜色在对应标记未启用时也可预填编辑
  - `ContentUnitStripeDelegate` 改配置驱动：徽章位图缓存按字符键控，
    色条/徽章/预留宽度全部走配置；MainWindow 仅接线
  - 默认配置：只启用紫色色条（#B39DDB），🔗 预填但不启用
  （[content_unit_marker_config.py](src/app/content_unit_marker_config.py) /
  [content_unit_marker_dialog.py](src/app/content_unit_marker_dialog.py) /
  [content_unit_delegate.py](src/app/content_unit_delegate.py) /
  [main_menu_bar.py](src/app/main_menu_bar.py) / [main_window.py](src/app/main_window.py)）

## [0.50.11] - 2026-08-04

**内容单元标记改版：行首 🔗 徽章 + 左侧色条（UI合理性13）**：
  - 名称前 `--` 文本标记改为**行首位图徽章**：🔗 不再拼进 DisplayRole 文本
    （emoji 字体回退抬高行高度量——实测 "armor" 15.23px vs "🔗 armor" 15.98px，
    垂直居中导致文字下移约 1px），改为名称列 delegate 在预留区绘制缓存位图
  - 新增左侧淡紫色色条（3px，`#B39DDB`）辅助区分；所有行内容统一右移
    预留宽度（色条+徽章+间距），有/无标记行的图标与文字对齐
  - 拆离：色条/徽章绘制抽为 `ContentUnitStripeDelegate`（名称列专用，
    含可测试的几何/颜色纯函数），MainWindow 仅一行接线
  - 已知瑕疵（用户确认不修）：默认 19px 行高下 16px 图标底部偶发 1px 裁切
  （[content_unit_delegate.py](src/app/content_unit_delegate.py) /
  [file_list_model.py](src/app/file_list_model.py) /
  [ui_constants.py](src/app/ui_constants.py) / [main_window.py](src/app/main_window.py)）

## [0.50.10] - 2026-08-04

**列表封面区分/筛选 + 导航记忆 + 标签反选（UI合理性5 / 操作便捷性5 / 操作便捷性7 / UI合理性16）**：
  - UI合理性5：文件夹类内容单元有封面 → 列表视图复用现有 256 封面缓存缩放到 64×64
    作为图标（只读查询，不产生新缓存、无圆角）；无缓存回退标准文件夹图标
  - 操作便捷性5：「只看有封面」切换按钮（中栏标题栏，按下筛选、不持久化），
    与标签筛选 AND 组合
  - 操作便捷性7：双击进入目录后，后退/前进恢复该目录最后一次选中（含多选，
    按路径匹配并滚动到首个恢复行）
  - UI合理性16：标签筛选三态（未选 → 已选 ✓加粗+白色描边 → 已排除 −删除线+降饱和，
    第三次取消）；三态样式统一 2px 边框 + 预留加粗宽度消除跳动（去 ✓/− 文字前缀）；
    反选标签进入排除筛选（正选 AND 结果中剔除，可多个反选并存）；
    分类徽标改为「分类名 N」并预留两位数字宽度
  - 拆离：内容筛选组合逻辑抽为 `ContentFilter.filter_entries`（纯函数）；
    选中记忆抽为 `SelectionMemory`（记录/按路径恢复/滚动）；
    封面图标缩放下移 `ThumbnailCoordinator.get_cover_icon`；MainWindow 仅接线
  （[file_list_model.py](src/app/file_list_model.py) /
  [thumbnail_coordinator.py](src/app/thumbnail_coordinator.py) /
  [main_window.py](src/app/main_window.py) /
  [tag_filter.py](src/app/tag_filter.py) /
  [tag_colors.py](src/app/tag_colors.py) /
  [content_filter.py](src/app/content_filter.py) /
  [selection_memory.py](src/app/selection_memory.py)）

## [0.50.9] - 2026-08-03

**分类颜色统一 + 批量打标签重构（BugFix2 / UI合理性12）**：
  - BugFix2：新增共享颜色 helper `tag_colors`（hue → QColor / 样式表 hex / 色块图标），
    选色改为**预选色表**（24 色相块，点击即选，所见即所得）替换 QColorDialog——
    修复"快速颜色与实际颜色不一致"根因（原仅存 hue + 固定 S/L 重建）；
    分类色接入标签管理树、元数据面板预选标签/chip、标签筛选栏、批量打标签
    （背景/边框统一分类色，文字色按相对亮度自动黑/白，暗色模式友好）
  - UI合理性12：批量打标签重构——预选标签按分类分组（组头可折叠）+ 搜索过滤框
    （输入即过滤）；chip 区改 FlowLayout 按钮；删除「（未添加标签）」空提示；
    删除独立标签输入框（仅保留搜索框）
  - 验收反馈：分类组头不着色（避免颜色杂乱）；标签按钮背景/边框统一分类色 +
    自动黑/白文字色；标签管理对话框关闭后元数据面板即时刷新当前单元标签
    （`refresh_tags` 不触碰表单字段，保留未保存的来源/备注编辑）
  - 文件列表四列改 Interactive 固定默认宽度（320/60/80/150，Explorer 风格右侧留白
    供框选），滚动条出现/消失不再导致列横移跳动；修复末行下方空白区起框（从下往上
    拉）选不中（操作合理性4）
  - 修复分割线固化：Windows 注册表字符串列表兼容（原校验只接受 int 导致恢复回退
    默认）+ 拖动分隔线实时保存（closeEvent 兜底）
  - 中栏文件列表四列宽度接入固化：保存/恢复 + 拖动即保存（layout/header/file_list），
    「重置布局」实时恢复默认宽度
  （[tag_colors.py](src/app/tag_colors.py) /
  [color_picker_dialog.py](src/app/color_picker_dialog.py) /
  [batch_tag_dialog.py](src/app/batch_tag_dialog.py) /
  [metadata_panel.py](src/app/metadata_panel.py) /
  [tag_filter.py](src/app/tag_filter.py) /
  [tag_manager_dialog.py](src/app/tag_manager_dialog.py)）

## [0.50.8] - 2026-08-03

**分割线状态持久化/重置 + 顶部菜单栏（UI合理性2/3）**：
  - 分割线（主三栏 / 右栏 / 操作历史列宽）保存/恢复/重置抽成独立 helper
    `SplitterStateHelper`（QSettings 持久化，键 `layout/*`），MainWindow 仅接线，
    首次 showEvent 恢复（避免窗口未布局时 setSizes 被零宽缩放清零）
  - 顶部菜单栏抽成独立 view `MainMenuBar`（「视图」：列表/卡片切换、重置布局、
    快捷键设置占位；「工具」：标签管理/操作历史），MainWindow 只连接信号
  - 默认比例：主栏 220/480/324（中栏加宽）；文件列表名称列 Stretch、
    类型/大小/修改日期默认 60/80/150；操作历史列 Interactive 可拖动 +
    默认 180/340/90 并持久化
  - 「重置布局」恢复默认并清除操作历史列宽存档（模态对话框下次打开生效）
  （[splitter_state.py](src/app/splitter_state.py) /
  [main_menu_bar.py](src/app/main_menu_bar.py) /
  [main_window.py](src/app/main_window.py) /
  [operation_history_dialog.py](src/app/operation_history_dialog.py) /
  [ui_constants.py](src/app/ui_constants.py)）

**移除未使用的 contain 缩略图渲染模式（清理）**：生成器与应用侧不再支持
  `mode="contain"`（宽高比缩放 + 透明填充 + 圆角）——该模式自卡片缩略图缓存
  接入（UI合理性17）起已无任何调用方与测试依赖；`generate_thumbnail` /
  `ThumbnailService.generate` 统一为方形居中裁剪，删除圆角/透明填充辅助代码
  与对应测试
  （[thumbnail_generator.py](src/infrastructure/thumbnail_generator.py) /
  [thumbnail_service.py](src/application/thumbnail_service.py) /
  [test_thumbnail_generator.py](tests/test_thumbnail_generator.py)）

## [0.50.7] - 2026-08-03

**元数据面板图片直接预览（操作合理性2）**：中栏单选图片文件时，
  右栏元数据面板直接显示原图预览（无缓存、不写数据库，复用封面预览的
  原图加载路径）：
  - 未标记图片文件 → 面板切换为「图片预览」视图（标题/文件名/路径 + 原图，
    隐藏编辑表单）；损坏/不支持图片显示占位边框，不崩溃
  - 已标记图片文件单元无封面 → 封面预览区直接显示文件本身；手动设置封面后
    封面优先（行为不变）
  - 图片识别复用 `ContentService.is_image_file`（扩展名集合与封面候选一致，
    未新增重复列表）
  - 布局：面板底部 stretch 吸收剩余空间，元素（含图片预览）自动靠顶，消除
    元素间空行；已有标签区默认高度恢复为常量值 240，并在其下方新增鼠标
    拖动条（60~240 可调、内部滚动，`_PresetScrollArea` 可变 sizeHint，
    空间不足时仍可压缩到下限）
  （[metadata_panel.py](src/app/metadata_panel.py) /
  [metadata_view.py](src/app/metadata_view.py) /
  [main_window.py](src/app/main_window.py) /
  [content_service.py](src/application/content_service.py)）

## [0.50.6] - 2026-08-03

**title 停用 + 重命名栏（UI合理性14）**：保留 content_unit.title 列但停止使用，
  UI 去掉标题输入框，创建/搜索/重命名不再读写 title；原标题栏改为「重命名」栏位
  （显示真实文件名，回车直接重命名，不走元数据「保存」按钮）：
  - MetadataPanel 重命名栏回车 → `rename_requested` 信号 → MainWindow 执行
    FileOperationService.rename（复用冲突/非法名处理、operation_history、
    目录树/中栏刷新）；重命名成功后不重载表单（未保存的来源/备注编辑保留）
  - 创建（标记/扫描/Mod 组）不再写 title；`update_metadata` 移除 title 参数；
    重命名/移动不再维护 title
  - 搜索改为按真实文件名（basename）匹配，优先级 名称 > 标签 > 备注；
    搜索结果列「标题」→「名称」（[models.py](src/domain/models.py) /
    [search.py](src/infrastructure/repositories/search.py) /
    [metadata_panel.py](src/app/metadata_panel.py) /
    [main_window.py](src/app/main_window.py)）
  - 遗留别名清除：新增 [clear_legacy_titles.py](scripts/clear_legacy_titles.py)
    （默认 dry-run、幂等，`UPDATE title = NULL WHERE title != 文件名`），
    真实库 4 条遗留别名已清除
  - schema 不动（CURRENT_SCHEMA_VERSION 仍 13）；删除 title 列的 schema 升级
    另立 issue（待数据导出/导入机制就绪）

## [0.50.5] - 2026-08-03

**内容单元标记前置缩写（UI合理性13）**：列表视图标记由名称后的 ` [内容单元]` 改为
  名称前的 `--`（双短横线，验收反馈逐次调整），长文件名截断时标记不再被遮挡；
  卡片视图保持 Q6:B 决策不变（名称不含标记，ToolTip 承载状态）
  （[ui_constants.py](src/app/ui_constants.py) / [file_list_model.py](src/app/file_list_model.py)）

**卡片视图启用 256px 缩略图缓存（UI合理性17）**：恢复 ThumbnailCoordinator
  生成链路到卡片视图（Stage 5 Task 1b 曾改为直接加载原图，多内容下全尺寸解码
  导致卡顿）：
  - 生成器新增 `mode="cover"` 方形居中裁剪模式（生成器默认 contain 不变），
    缩略图生成服务（ThumbnailService.generate）默认使用 cover，
    与卡片 Task 2 验收视觉（方形居中裁剪、无圆角/透明条）一致
    （[thumbnail_generator.py](src/infrastructure/thumbnail_generator.py)）
  - CardListModel 恢复缩略图 provider：缓存命中同步返回、未命中显示固定尺寸
    占位图标（icon_size × icon_size，占地与缩略图一致，避免首次批量生成缓存时
    布局抖动），后台生成完成后按行刷新（[card_list_model.py](src/app/card_list_model.py)）
  - MainWindow 恢复 `_card_thumbnail_provider` 接线（256 档），缓存失效/GC 复用
    既有 Service 链路（[main_window.py](src/app/main_window.py)）

## [0.50.4] - 2026-08-03

全量 pytest 原生崩溃修复（测试稳定性1）。

**修复**

- **MetadataPanel 清理按钮时先断开信号，消除 deleteLater 引用环原生崩溃（测试稳定性1）**：
  chip / 预设 / 最近标签按钮的 clicked/toggled lambda 闭包引用面板，deleteLater 后面板
  包装器回收时，事件循环处理 DeferredDelete 会在按钮析构途中触发面板二次删除
  （PySide6 6.11.1 + Python 3.14，Windows access violation / Abort；全量 pytest 在
  `test_thumbnail_coordinator.py` 处原生崩溃）。新增 `_disconnect_button_signals` /
  `_disconnect_flow_buttons`，全部清理路径（`_remove_tag_chip` / `clear_panel` /
  `_load_tags_for_unit` / `_refresh_recent_list` / `_clear_preset_groups`）先断开再
  deleteLater（[metadata_panel.py](src/app/metadata_panel.py)）
- **TagFilterBar rebuild 同类防御**：分类/标签按钮重建删除前先断开 clicked 连接
  （[tag_filter.py](src/app/tag_filter.py)）

**测试**：新增 2 个回归测试（旧 chip 信号已断开 + DeferredDelete 处理不崩溃）；
全量 pytest 恢复稳定通过；ruff check + format 全绿。

## [0.50.3] - 2026-08-03

封面设置即时保存（操作便捷性6）。

- **封面选择/清除即时落库**：元数据面板「设置封面」对话框点「确定」后立即调用
  `ContentService.update_metadata` 写入 `cover_path` 并提交事务，不再等待「保存」
  按钮；「清除封面」同样立即清空（[metadata_view.py](src/app/metadata_view.py) /
  [metadata_panel.py](src/app/metadata_panel.py)）
- 封面保存不重载元数据表单：未保存的标题/来源/备注编辑保留，等「保存」按钮统一提交；
  保存按钮语义不变（仅负责标题/来源/备注，封面已即时保存）
- 新增 `cover_saved` 信号链路：面板 → MetadataView → MainWindow 刷新中栏
  （封面图标/缩略图变化）+ 状态栏「封面已保存」（[main_window.py](src/app/main_window.py)）

**测试**：面板层覆盖立即落库/提交回调/信号/清除/未保存编辑保留/失败路径，
MainWindow 层覆盖对话框确定后数据库已更新；ruff check + format 全绿。

## [0.50.2] - 2026-08-02

UI 术语调整（UI合理性1）。

- **装配面板更名为「文件夹预览」**：面板语义已是"文件夹内容透视"（绑定当前/
  钉住文件夹 → 显示内容 → 双击进入 / 右键操作 / 拖入添加），"装配面板"与实际
  功能不符。仅改显示名（[ui_constants.py](src/app/ui_constants.py)），代码标识符
  （Assembly*/assembly_*）保留 legacy 命名，待 UX 重构 Task 8 统一改名
  （登记于 TD-L30）。

## [0.50.1] - 2026-08-02

数据一致性与移动流程修复（数据库问题1 / BugFix1 / Bug紧急修复2）。

**修复**

- **重命名/移动后的数据库残留（数据库问题1）**：
  - 文件重命名/移动不再产生重复内容单元：`FileOperationService` 文件分支原地
    更新 content_unit 行（path/path_key + 默认标题跟随，用户自定义标题保留）；
    目标位于已标记文件夹内时按 spec §5.4 取消该文件标记（删除行）
  - 扫描时清理当前 root 下文件已不存在的 content_unit 行（级联
    content_unit_tag / thumbnail_cache；root 本身不存在时跳过，防误删）——
    既有脏库在下次扫描后自愈
  - 新增 `ContentUnitRepository.get_by_path_key`（归一化路径查询）
- **批量移动报"移动失败"但内容实际已移动（Bug紧急修复2）**：
  - 根因：`FolderCacheSyncHelper.on_folder_moved` 只删单行，移动带子目录缓存的
    目录时触发 FOREIGN KEY constraint failed，DB 回滚后旧路径 content_unit 行
    被扫描清理误删（丢失内容单元标记）
  - 修复：`on_folder_moved` 改为整棵子树迁移（新路径行父先子后插入、前缀重写、
    父链重建；旧行先子后父删除），目录树移动后即时反映完整子树
- **Ctrl+Q 目录树不刷新（BugFix1）**：Ctrl+Q 改为目录树聚焦时移动树选中节点
  （新增 `_tree_selected_path`，与 Ctrl+M 树版本对称），否则移动中栏选中；
  移动后统一刷新目录树

**测试**：相关测试 207 项通过（数据库问题1 回归 / 扫描 / 文件操作 / folder_cache
同步 / 移动到与快捷键等 9 个测试文件）；ruff check + format 全绿。
（按用户要求本轮仅跑相关子集，未跑全量。）

## [0.50.0] - 2026-08-02

标签系统体验优化 + 元数据/装配面板样式修复（UI合理性8 / UI合理性7 / 操作便捷性4）。

**新增功能**

- **预选标签按分类分组 + 可折叠（UI合理性8 + UI合理性7）**：元数据面板预选区域
  按 TagCategory 垂直分组（分组标题按钮可折叠，默认展开，组内按名称排序）；
  组内标签为 FlowLayout 按钮流（新增 [flow_layout.py](src/app/flow_layout.py)，
  基于 Qt 官方示例），替代 QListWidget 流式平铺——分组头与标签不再混排，
  空列表不再出现无法交互的矩形；最近使用区域无记录时整体隐藏
- **最近使用标签（UI合理性8）**：新增 [recent_tags.py](src/app/recent_tags.py)，
  记录最近 10 个成功添加的标签（QSettings 持久化）；元数据面板「最近使用」区域
  点击直接添加；右键内容单元 → 「添加最近标签 ▸」子菜单，点击立即 attach + 提交
- **标签即时保存（操作便捷性4）**：chip 添加/移除、预选点击、最近标签点击立即
  attach/detach + 提交（TransactionScope.commit）；「保存」按钮仅负责
  标题/来源/备注/封面（推翻 2026-07-19 决策 1 的标签部分，用户确认 2026-08-02）
- **元数据面板布局与样式修复（UI合理性8 验收反馈）**：
  - 高度参数提取为 ui_constants 常量（METADATA_PANEL_TAG_LIST_HEIGHT /
    METADATA_PANEL_PRESET_SCROLL_HEIGHT / METADATA_PANEL_NOTES_EDIT_HEIGHT，
    可手动调整）；chip 区改为单行、释放垂直空间
  - 删除「无标签」提示（_tags_empty_hint）
  - 预设标签区高度策略修复：改为「Expanding + 上限常量」并移除面板底部 stretch，
    使 PRESET_SCROLL_HEIGHT 真正生效；小窗口下自动压缩到 60px，
    来源 URL / 备注不再被遮挡
  - chip 区由 QListWidget 改为 FlowLayout 按钮（与「最近使用/已有标签」按钮同款
    浅灰描边），修复 QListWidget 流式模式下的标签偏移/裁切与无边框问题
  - 区域样式统一：chip / 最近使用 / 已有标签背景统一为系统 palette Base 深灰
    （与左栏目录树内部矩形一致）+ 4px 圆角（PANEL_REGION_STYLE_TEMPLATE，
    同色边框使圆角生效、视觉无边框线）
  - 装配面板改为与左栏目录树同构的三层结构：1px 浅色外边框 → 窗体底色 →
    内部灰色圆角列表矩形

**测试**：1313 passed, 4 skipped（新增 RecentTags / 分组折叠 / 最近标签 /
即时保存持久化 / 右键子菜单等 14 项；原保存期标签失败测试改写为即时路径）；
ruff check + format 全绿。

## [0.49.0] - 2026-08-02

工作流便捷性优化（实际工作流测试反馈第一批）：最近移动目标 + 3 项小修。

**新增功能**

- **最近移动目标（操作便捷性3，方案1）**：
  - 新增 [recent_move_targets.py](src/app/recent_move_targets.py)：记录最近 5 个成功
    移动目标（QSettings 持久化，make_path_key 去重置顶）
  - 右键菜单「移动到...」后新增「移动到最近目录 ▸」子菜单（简化路径显示，点击直接移动）
  - Ctrl+Q 快捷键：中栏选中条目 → 直接移动到最近目标（默认快捷键暂定，后续自定义快捷键菜单开放配置）
  - MoveToDialog 顶部「最近目标」快捷按钮 + 打开时默认展开/选中最近目标（替代源父目录定位）
- **删除确认提示文件数（操作合理性3）**：删除文件夹时确认文案追加
  「（文件夹内含 N 个文件）」；空目录删除更安心

**修复 / 优化**

- UI合理性6：重命名弹窗宽度约为默认的 3/2
- UI合理性5：列表大小列按 B / KB / MB / GB / TB 自动缩写（排序仍按原始字节值）

**测试**：1299 passed, 4 skipped（新增 RecentMoveTargets / MoveToDialog 最近目标 /
Ctrl+Q / 右键子菜单 / 大小列格式化 / 删除文件数提示等 16 项）；ruff check + format 全绿。

## [0.48.1] - 2026-08-02

紧急修复：标签管理菜单无法打开（`AttributeError: 'MainWindow' object has no attribute '_commit_callback'`）。

- **原因**：UX 重构 Task 7 Commit 1 将 `_commit` / `_rollback` 回调迁入
  `TransactionScope` 时，遗漏了 `_on_tag_manager_clicked` 对 `TagManagerDialog`
  的 commit / rollback 回调注入，仍引用已移除的 `self._commit_callback` / `self._rollback_callback`。
- **修复**：`TagManagerDialog` 构造改为注入 `self._transaction_scope.commit` /
  `self._transaction_scope.rollback`（`main_window.py`），事务边界统一走 TransactionScope。
- **测试**：全量 1283 passed, 4 skipped；ruff check + format 全绿。

## [0.48.0] - 2026-08-01

UX 重构 Phase 2 Task 7：MainWindow 拆分（Commit 1 控制器拆分 + Commit 2 技术债与 FileListView 统一）。

**Commit 1：控制器拆分**

- 新增 [transaction_scope.py](src/app/transaction_scope.py)：`_commit` / `_rollback` /
  `_handle_service_error` 事务逻辑封装（TD-M31），MainWindow 委托调用
- 新增 [scan_controller.py](src/app/scan_controller.py)：扫描线程生命周期 + TD-H4/H5
  sender 竞态校验迁入；TD-M13 进度信号接线（scan_progress → 状态栏）；新增
  [test_scan_controller.py](tests/test_scan_controller.py)（TD-M26 起点）
- 新增 [assembly_controller.py](src/app/assembly_controller.py)：装配面板绑定 / 钉住 /
  跟随中栏 / 受影响刷新逻辑迁出
- 新增 [metadata_view.py](src/app/metadata_view.py)：元数据加载 / 保存提交 / 封面选择
  编排迁出（面板信号改由视图接管）
- MainWindow 保留薄委托与文件操作编排，行为不变

**Commit 2：技术债 + FileListView 统一**

- TD-H10：`FileOperationService` 从 `infrastructure/` 迁移到 `application/`
  （消除 infrastructure → application 反向依赖）
- TD-L25：`FolderCacheSyncHelper` 新增 `delete_folder_subtree(path)` 语义化方法，
  `_sync_on_delete` 不再访问私有 `_repo`
- TD-M35：`rename` 跨盘统一抛 `CrossDriveError`（与 `move` 一致）
- TD-M36：移除 `AssemblyListModel`，装配面板复用 `FileListModel(single_column=True)`

**测试**：1283 passed, 4 skipped（新增 test_scan_controller.py；装配面板 model 测试
改用 FileListModel 单列模式），ruff check + format 全绿。

## [0.47.0] - 2026-08-01

UX 重构 Phase 2 Task 6：数据库与死代码清理（回归纯 DELETE 模式）。schema_version v12 → v13。

**新增功能**

- **纯 DELETE 模式落地**：content_unit 移除 `is_marked` 字段（schema v13 迁移：
  清理历史 is_marked=0 记录及级联关联 → 重建表移除列与索引）。标记 = 记录存在，
  取消标记 = 删除记录（`ContentService.unmark_content_unit` 改为 DELETE，
  级联清理 content_unit_tag / thumbnail_cache 记录）。Domain / Repository /
  Search / Scan / FileOperation 全链路移除 `is_marked`
- **移除受管理根目录同步清理扫描记录**（open-questions §6）：
  `ManagedRootService.remove_root` 注入 FolderCacheRepository / ContentUnitRepository
  + UnitOfWork，清理被移除根路径前缀下的 folder_cache（按深度降序）与 content_unit
  （级联 tag / thumbnail）；重叠守卫：仍属于其他剩余根目录的记录不清理
- **旧目录检测代码移除**（open-questions §7）：`app_paths` 删除
  `_log_legacy_appdata_hint_if_exists` 及对应测试；`%LOCALAPPDATA%` 路径回退保留
- **移除受管理根目录确认文案更新**：说明会清理该目录下的扫描记录（目录树缓存与
  内容单元元数据），并明确不删除磁盘文件

**修复 / 清理**

- TD-L31：删除 ui_constants 无人引用的缩略图死常量（THUMBNAIL_SIZE / FORMAT / FILENAME_TEMPLATE）
- TD-L32：删除 AssemblyService.remove_file 死方法及对应测试
- TD-L33：清理"浏览/整理模式"过时注释（main_window / search_dialog / tag_filter /
  metadata_panel / folder_tree_model / assembly_service / domain.models）

**测试**

- 新增：migrations v12→v13（清理 + 列移除 + 幂等）、remove_root 清理（深层/重叠守卫）、
  unmark 删除记录与级联、search 无过滤条件、remark 新语义
- 移除：is_marked 相关用例（domain 校验 / search 过滤 / 旧目录提示 4 项 /
  remove_file 3 项等）
- 全量回归：1279 tests passed, 4 skipped，ruff check + format 全通过

---

## [0.46.0] - 2026-08-01

UX 重构 Phase 2 Task 5：交互细节优化 + 验收修复

统一右键菜单规范、抑制 QMessageBox 系统提示音、修复撤销循环 bug、操作历史显示优化、刷新按钮与 F5、状态栏统一、路径简化显示、空状态提示。基于验收反馈修复 6 项问题：系统提示音抑制、中栏右键粘贴、copy 操作文案、撤销循环、路径简化应用到全场景、相对路径包含根目录名。schema_version 维持 v12，无数据库迁移。

**新增功能**

- **右键菜单统一**：新增「打开」（Q1=B，已标记内容单元也支持打开）、「钉住此文件夹」「取消钉住」（Q2=C，中栏/目录树/装配面板均支持）；中栏右键文件/文件夹新增「粘贴」项（粘贴到当前中栏目录，剪贴板空时灰显）
- **QMessageBox 系统提示音抑制**：新增 [message_box_helper.py](src/app/message_box_helper.py)，patch QMessageBox 静态方法使用 `setIcon(NoIcon)` + `setIconPixmap` 抑制 Windows 系统提示音，保留视觉图标；MainWindow.__init__ 调用一次（Q3=C + Q7=A）
- **刷新按钮与 F5**：中栏标题栏新增刷新按钮 + F5 快捷键（Q5=B + Q6=A），仅刷新当前目录和目录树对应节点，不触发全量扫描，同步刷新装配面板
- **状态栏统一**：使用 Qt 标准 QStatusBar（Q7=A），移除左侧扫描状态 QGroupBox，消除布局抖动
- **路径简化显示**：新增 [path_display.py](src/app/path_display.py)（Q8=B），左栏目录详情、右栏元数据面板、操作历史 Tooltip 均应用简化路径；相对路径**包含根目录名**（验收修正：`D:\testPath\A\B\C` → `A\B\C`），外部路径加 `[外部]` 前缀
- **空状态提示**（Q9=A）：搜索无结果 → "没有找到匹配内容"；目录为空 → "该目录为空"
- [ui_constants.py](src/app/ui_constants.py) 新增文案：MENU_OPEN / MENU_PIN_FOLDER / MENU_UNPIN_FOLDER / REFRESH_BUTTON / HISTORY_DESC_COPY / HISTORY_OP_LABELS 等

**修复**

- **撤销循环 bug 修复**（Q4=B）：FileOperationService.move/rename 新增 `record_history: bool = True` 参数；UndoService._undo_rename/_undo_move 调用时传 `record_history=False`，避免撤销时产生新的可撤销记录导致无限循环
- **操作历史显示优化**（Q3=C + Q10=B）：移除描述列改用 Tooltip；过滤已撤销记录；删除操作灰色显示但保留可追溯性；操作类型中文化（HISTORY_OP_LABELS 映射）；新增 copy 分支文案（原显示"未知操作：copy"）
- **中栏右键粘贴**：原仅空白区域右键支持粘贴，现文件/文件夹右键也支持（粘贴到当前中栏目录）
- **路径简化全场景应用**：原仅操作历史 Tooltip 应用简化路径，现左栏目录详情、右栏元数据面板均应用
- **相对路径包含根目录名**：原规则不含根目录名（`A\B\C` → `B\C`），验收修正为含根目录名（`A\B\C`）

**设计要点**

- **QMessageBox 提示音抑制**：通过 `setIcon(QMessageBox.Icon.NoIcon)` 避免 Windows MessageBeep 触发，`setIconPixmap` 手动设置图标 pixmap 保留视觉图标；patch 应用在 MainWindow.__init__，幂等
- **撤销循环修复策略**：采用 `record_history=False` 参数方案而非删除新记录，保持 FileOperationService 的同步逻辑（folder_cache + ContentUnit.path）完整执行，仅跳过 operation_history 写入
- **路径简化规则**：使用 PurePath 跨平台比较，匹配最长根目录（处理嵌套根目录）；路径就是根目录本身时返回根目录名；外部路径加 `[外部]` 前缀保留可追溯性
- **MetadataPanel 路径简化注入**：MetadataPanel 新增 `set_managed_root_service` 方法，MainWindow 创建面板后注入

**测试**

- 新增 [test_path_display.py](tests/test_path_display.py)：路径简化 8 个测试用例（含根目录名、外部路径、嵌套根目录、多根目录、中文路径、空路径、根目录本身、service 封装）
- 新增右键菜单粘贴、钉住/取消钉住相关测试用例
- 全量回归：1288 tests passed, 4 skipped，ruff check + format 全通过

---

## [0.45.0] - 2026-08-01

UX 重构 Phase 1 Task 4：「添加到钉住文件夹」+ 基础拖拽（快速插入移除）+ 验收修复

移除「快速插入」功能及其服务，由「添加到钉住文件夹」菜单项和中栏/装配面板拖拽替代。装配面板作为 drop target 仅在钉住状态下接受文件/文件夹拖入。同步落地 3 项基于验收反馈的修复：钉住文件夹内操作后装配面板同步刷新、重命名后中栏内容消失的系统性修复、程序启动时多个小窗口闪过。schema_version 维持 v12，无数据库迁移。

**移除功能**

- **快速插入服务**：[quick_insert_service.py](src/application/quick_insert_service.py) 删除，[test_quick_insert_service.py](tests/test_quick_insert_service.py) 删除
- [main.py](src/app/main.py) / [application/__init__.py](src/application/__init__.py) 移除 `QuickInsertService` 导入与实例化
- [main_window.py](src/app/main_window.py) 移除 `quick_insert_service` 注入与相关调用

**新增功能**

- **「添加到钉住文件夹」菜单项**：中栏右键文件/文件夹 → 「添加到钉住文件夹」（仅装配面板钉住时可见）→ 复用 `_perform_move_to` 移动到钉住文件夹，统一冲突解决流程
- **装配面板 drop target**：[assembly_panel.py](src/app/assembly_panel.py) 实现 `dragEnterEvent`/`dragMoveEvent`/`dropEvent`，仅钉住状态下接受文件/文件夹拖入（与右键添加行为一致），通过 `on_drop_files` 回调委托 MainWindow
- **中栏内拖拽**：[file_list_model.py](src/app/file_list_model.py) / [card_list_model.py](src/app/card_list_model.py) 实现 `mimeData` 返回含本地文件 URL 的 `QMimeData`，支持拖出到装配面板或资源管理器
- **拖拽到文件夹**：中栏内拖拽文件到同目录的文件夹 = 「移入该文件夹」（`_on_drop_to_folder`），含自子目录检测与冲突解决
- **`_perform_move_to` 扩展**：新增 `refresh_assembly` 参数，拖入装配面板时无条件刷新装配面板；拖入中栏被钉住文件夹时通过 `_refresh_assembly_if_affected` 同步刷新
- [ui_constants.py](src/app/ui_constants.py) 新增文案：MENU_ADD_TO_PINNED / ASSEMBLY_DROP_NOT_PINNED 等

**修复（基于验收反馈）**

- **修复 1：钉住文件夹内操作后装配面板同步刷新**：新增 `_refresh_assembly_if_affected(*affected_dirs)` 辅助方法，在重命名/删除/新建文件夹/粘贴/移动等文件操作后检查受影响目录是否与装配面板钉住文件夹匹配，匹配则调用 `refresh_current`。覆盖「双击进入被钉住文件夹后进行任何操作」场景，含 5 个测试用例（rename/delete/new_folder/paste/move_to）
- **修复 2：重命名后中栏内容消失（系统性修复）**：新增 `_restore_middle_after_tree_refresh(dir_path)` 方法统一处理 `_refresh_tree` 后的中栏恢复。`_refresh_tree` 会清空 `content_list_model` 且 `restore_expanded_paths` 恢复选中节点不触发 `selectionChanged` 信号，导致中栏空白。新方法通过 `find_index_by_path` 恢复目录树选中 + 直接调用 `_refresh_content_list` 刷新中栏（不依赖信号），替代原 `_refresh_content_list_after_file_op` 在重命名路径的调用
- **修复 3：程序启动时多个小窗口闪过**：所有容器组件（`QWidget`/`QSplitter`）创建时显式传入 `self` 作为父对象，避免短暂成为顶级窗口

**设计要点**

- **拖拽范围控制**：装配面板仅在钉住时接受 drop（A4 决策），避免误操作；中栏内拖拽接受文件和文件夹（与右键添加行为一致）
- **冲突解决复用**：「添加到钉住文件夹」/拖拽到装配面板/拖拽到文件夹均复用 `_perform_move_to` + `ConflictResolutionDialog`，统一重命名/跳过/覆盖询问
- **自子目录检测**：拖拽到文件夹时拒绝「拖入自身」和「父目录拖入子目录」（`SelfSubdirectoryError`）
- **装配面板同步刷新触发点**：所有文件操作（重命名/删除/新建/粘贴/移动）在操作完成后调用 `_refresh_assembly_if_affected`，比较 `make_path_key` 归一化路径，避免大小写/分隔符差异

**测试**

- 新增 Task 4 测试用例：添加到钉住文件夹（单文件/多文件/冲突对话框/覆盖/中文文件名）、装配面板拖拽（拒绝未钉住/接受文件/接受文件夹/混合/冲突/移动文件/移动文件夹）、中栏拖拽到文件夹（内部/冲突/自子目录拒绝/父到子拒绝）、拖到钉住文件夹后刷新装配面板、FileListModel/CardListModel mimeData
- 新增修复 1 测试用例 5 个：钉住文件夹内 rename/delete/new_folder/paste/move_to 后装配面板同步刷新
- 全量回归：1279 tests passed, 4 skipped（Windows 权限相关），ruff check + format 全通过

---

## [0.44.0] - 2026-07-31

UX 重构 Phase 1 Task 3：装配面板 📌 钉住功能

为装配面板添加 📌 钉住/取消钉住切换能力。钉住后中栏的选中/导航操作不再改变装配面板绑定，方便用户固定当前透视的文件夹进行持续整理。取消钉住后立即跟随中栏当前选中。钉住对象路径不存在时自动解除钉住并清空面板。schema_version 维持 v12，无数据库迁移。

**新增功能**

- **📌 钉住按钮**：[assembly_panel.py](src/app/assembly_panel.py) 标题栏右侧新增 📌 按钮（B3 决策：钉住时切换图标 📌 → 📍）
- **钉住状态短路**：`bind_mod_group`/`bind_folder` 在钉住状态下短路不切换绑定（A1/A2 决策）
- **取消钉住跟随中栏**：[main_window.py](src/app/main_window.py) `_on_assembly_pin_changed(False)` → `_follow_middle_selection_after_unpin` 立即跟随中栏当前选中（B4 决策）
- **创建 Mod 组不自动绑定**（B1）：钉住状态下 `_on_create_mod_group` 不调用 `_bind_assembly_panel`
- **路径不存在自动解除**（A4/B6）：`refresh_current` 检测钉住对象路径不存在时调用 `force_unpin_and_clear`
- **移动整个透视文件夹后强制解除**（A4）：`_on_assembly_file_op` 的 move_to 分支检测文件夹移动后调用 `force_unpin_and_clear`
- [ui_constants.py](src/app/ui_constants.py) 新增文案：ASSEMBLY_PIN_BUTTON_UNPINNED/PINNED、ASSEMBLY_PIN_TOOLTIP_UNPINNED/PINNED

**设计要点**

- **钉住状态不持久化**（A3）：程序重启后清空钉住状态，与现有装配面板绑定行为一致
- **未绑定时 📌 按钮禁用**（A5）：`bind_mod_group`/`bind_folder` 解绑时 `_pin_button.setEnabled(False)`
- **钉住状态下文件操作仍可用**（B2）：钉住仅阻止 bind_* 切换，不影响 refresh_current 和 on_file_op 回调
- **回调委托模式**：`AssemblyPanel` 通过 `on_pin_changed(pinned: bool)` 回调通知 MainWindow，MainWindow 在取消钉住时主动调用 `_follow_middle_selection_after_unpin` 跟随中栏
- **force_unpin_and_clear vs unpin**：`unpin()` 仅清除钉住标志保留当前绑定内容（用户主动取消钉住，由 MainWindow 跟随中栏）；`force_unpin_and_clear()` 同时清空绑定（路径不存在或移动自身等异常情况）

**测试**

- 新增 11 个 Task 3 钉住功能测试用例：A5 未绑定禁用 / 绑定后启用 / A1 单击不切换 / A2 双击不切换 / B4 跟随中栏 / B4 无选中清空 / A3 不持久化 / B2 文件操作可用 / A4/B6 路径不存在自动解除 / A4 移动自身解除 / B3 按钮图标切换
- 全量回归：1262 tests passed, 4 skipped（Windows 权限相关），ruff check + format 全通过

---

## [0.43.0] - 2026-07-31

UX 重构 Phase 1 Task 2：装配面板迁移到右栏 + 文件操作继承

装配面板从中间区分割区域迁移到右栏下方（与元数据面板上下分布，可拖拽调整比例），并扩展为"文件夹透视器"语义：单击任意文件夹内容单元即可绑定装配面板透视其内部文件，不限于已标记内容单元。装配面板右键菜单完整继承中栏文件操作（重命名/复制/剪切/粘贴/移动到/删除/复制路径），图片额外支持「重命名为文件夹名」，空白处支持「移动到...」整体迁移透视文件夹。schema_version 维持 v12，无数据库迁移。

**新增功能**

- **布局重构**：[main_window.py](src/app/main_window.py) 移除中栏 `_middle_splitter`，新建右栏 `_right_splitter`（元数据上 + 装配下，初始比例 3:2），装配面板固定在右栏下方
- **单击绑定（A1-1）**：单击文件夹内容单元 → 装配面板绑定；单击其他 → 解绑；双击文件夹 → 进入目录（与现有行为一致）
- **装配面板透视器语义**：扩展为可透视任意文件夹（不限于内容单元），新增 `AssemblyService.list_folder_files(path)` + `AssemblyPanel.bind_folder(path)` + `MainWindow._bind_assembly_folder`
- **关闭按钮移除（B1-1）**：装配面板固定在右栏，`_close_button` / `_on_close_clicked` / `on_panel_closed` 回调 / `_on_assembly_closed` 一并清理
- **「加入装配」菜单项移除（B2-2）**：`_on_assembly_add_file` / `MENU_ADD_TO_ASSEMBLY` / `ASSEMBLY_ADD_FILE_OK/FAILED` 清理，Task 4 由「添加到钉住文件夹」替代
- **装配面板右键菜单继承中栏操作**：重命名/复制/剪切/粘贴/移动到/删除/复制路径（通过 `on_file_op(action, entries)` 回调委托 MainWindow 复用现有逻辑）
- **图片右键「重命名为文件夹名」**：新增 `AssemblyService.rename_as_cover_by_path(folder_path, image_path)`，支持非内容单元文件夹
- **空白处右键「移动到...」**：移动整个透视文件夹，移动成功后解绑装配面板（A3-1）
- **空白处右键「粘贴」**：粘贴到当前透视文件夹（修复 3）
- [ui_constants.py](src/app/ui_constants.py) 新增文案：ASSEMBLY_MENU_MOVE_FOLDER

**修复（基于验收反馈）**

- **修复 1：装配面板重命名不再误入文件夹**：抽取 `_rename_entry_core(entry, refresh_middle)` 核心方法，装配面板调用时 `refresh_middle=False`，避免中栏被刷新到文件父目录（错误进入文件夹）。中栏调用仍保持 `refresh_middle=True`
- **修复 2：重命名弹窗初始选区忽略后缀**：新增自定义 `_show_rename_dialog` 替换原 `QInputDialog.getText`，通过 `Path.suffix` 计算选区长度，初始选中文件名部分（不含扩展名）。`preview.jpg` 只选中 `preview`，避免误改后缀。`.gitignore` 等以点开头的文件 suffix 为整个名称时全选
- **修复 3：装配面板空白处支持粘贴**：`_show_empty_area_menu` 新增「粘贴」菜单项，粘贴到当前透视文件夹

**设计要点**

- **装配面板语义扩展**：从"仅 Mod 组内容单元"扩展为"任意文件夹透视器"，单击非内容单元文件夹也能透视其内部文件，封面重命名功能通过 `rename_as_cover_by_path` 支持任意文件夹
- **信号循环防护**：`_bind_assembly_panel` → `bind_mod_group` → `_refresh_file_list` 仅刷新装配面板内部 model，不反向修改 content_view 选区
- **文件操作委托**：装配面板通过 `on_file_op(action, entries)` 回调委托 MainWindow，复用中栏现有文件操作逻辑（重命名/复制/剪切/粘贴/移动到/删除/复制路径），避免逻辑重复
- **重命名对话框选区**：QInputDialog.getText 不支持设置初始选区，改用自定义 QDialog + QLineEdit.setSelection 实现忽略后缀的选区
- **重命名刷新策略**：通过 `refresh_middle` 参数控制是否刷新中栏，装配面板重命名只刷新装配面板自身（`refresh_current`），中栏重命名保持原有刷新父目录行为

**测试**

- 新增 `AssemblyService.list_folder_files` 单元测试 5 个用例：列出文件 / 子目录 / 排序 / 非目录返回空 / 不存在路径返回空
- 新增 `AssemblyService.rename_as_cover_by_path` 单元测试 5 个用例：按文件夹名重命名 / 多图后缀 / 非图片异常 / 路径不在文件夹内 / 已重命名幂等
- 新增装配面板文件操作集成测试 8 个用例：装配面板在右栏 splitter / 单击文件夹绑定 / 单击非内容单元文件夹透视 / 非内容单元文件夹图片重命名 / 文件操作（delete/copy_path/copy+paste）
- 适配重命名对话框变更：`test_main_window_file_ops_task3a.py` / `test_main_window_shortcuts.py` 重命名测试从 mock `QInputDialog.getText` 改为 mock `MainWindow._show_rename_dialog`
- 全量回归：1252 tests passed, 4 skipped（Windows 权限相关），ruff check + format 全通过

---

## [0.42.0] - 2026-07-31

UX 重构 Phase 1 Task 1：移除双模式切换

从双模式工作区（浏览/整理）收敛为单面板 + 可钉住装配面板的统一工作区。删除顶部模式切换按钮、暂存区功能及相关数据库表，"创建 Mod 组"从整理模式独有变为统一面板中栏右键通用功能。schema_version v11 → v12 迁移（删除 staging_area 表）。本次为 Workspace 架构重构的奠基版本，后续 Task 2-7 在此基础上展开。

**移除功能（破坏性变更）**

- **模式切换**：删除 [mode_manager.py](src/app/mode_manager.py) / `AppMode` 枚举 / 顶部 [浏览|整理] 切换按钮 / 整理模式状态变量，删除 `MainWindow._on_mode_changed` / `_apply_mode` / `_refresh_for_mode` 等模式相关方法
- **暂存区功能**：删除 `StagingArea` 实体 / `StagingService` / `StagingAreaRepository` / `staging_area` 表，删除目录树右键"标记为暂存区"/"取消暂存区标记"功能
  - [staging_service.py](src/application/staging_service.py) 删除
  - [staging_area.py](src/infrastructure/repositories/staging_area.py) 删除
  - [db.py](src/infrastructure/db.py) `CURRENT_SCHEMA_VERSION` 11 → 12
  - [migrations.py](src/infrastructure/migrations.py) 新增 `migrate_v11_to_v12`：DROP TABLE staging_area
  - [folder_tree_service.py](src/application/folder_tree_service.py) 移除暂存区标记查询，目录树不再显示 `[S]` 标记
  - [errors.py](src/application/errors.py) 删除 `StagingAreaNotFoundError` / `StagingAreaAlreadyExistsError`
- **快速插入按钮**：保持隐藏（C2 决策），Task 4 正式移除 `QuickInsertService`
- **死代码清理**：`ContentService.list_staging_entries` / `MainWindow._refresh_staging_content_list` 已删除

**新增功能**

- **多选创建 Mod 组**：`ContentUnitCreationService.create_content_unit_from_files` 批量接口（D1 调整：原 D1「逐个调用 + 容错」因文件夹已存在 ConflictError 不可行，改为一次建文件夹 + 逐个移入 + 容错汇总）
- **装配面板始终可见**：未绑定时显示空状态占位「无固定内容」（原 Task 2 的部分行为提前）
- 装配面板「移除文件」功能已在 Commit 3 移除（L2 提前，原计划 Task 4），UI/回调/常量一并清理

**设计要点**

- **数据模型原则**：标记 = 数据库有记录，取消标记 = DELETE 记录。不引入 `status` 列或 `is_marked` 字段表达"曾经标记过"语义。schema v11 遗留的 `is_marked` 字段在 Task 6 中一并清理
- **Mod 组 = 文件夹内容单元**：不引入 `ModGroup` 实体，"创建 Mod 组"是 UI 操作（建文件夹 + 移入文件 + 标记为内容单元）
- **多选创建 Mod 组容错**：`create_content_unit_from_files` 一次建文件夹 + 逐个移入 + 容错汇总，避免逐个调用 + 容错时因文件夹已存在 ConflictError 不可行的问题

**测试**

- 删除 `test_mode_manager.py` / `test_main_window_mode.py` / `test_main_window_quick_insert.py` / `test_main_window_staging_list.py` / `test_staging_service.py` / `test_staging_area_repository.py` / `test_content_service.py`（暂存区相关测试）
- 适配 `test_main_window_assembly.py` / `test_main_window_context_menu_task3.py` / `test_main_window_metadata.py` / `test_main_window_tag_filter.py` / `test_main_window_view_switch.py`：移除模式相关测试用例
- 新增 `test_migrations.py` v11→v12 迁移测试
- 新增多选创建 Mod 组测试

---

## [0.41.0] - 2026-07-31

Stage 5 完成后全面 Code Review 修复版本

Stage 5 全部完成后进行的阶段性审查修复。目标：找出架构/设计/代码质量问题，清理技术债，区分"现在修复"与"进入后续版本"，为下一阶段开发建立基础。完整审查报告见 [docs/stage5-code-review.md](docs/stage5-code-review.md)。本版本落地 8 个批次的修复，所有 Stage 5 Code Review 范围内的问题已处理完毕。

**批次 1：文档与注释修正（H1 / H2 / H3 / M9）**

- **H1 文档同步**：[architecture.md](docs/architecture.md) 从 schema v6 更新到 v11，补充 v7-v11 迁移说明、staging_area 表、thumbnail_cache 复合主键描述
- **H2 注释矛盾修正**：[search_service.py](src/application/search_service.py) Q2=A → Q2=B 注释修正，与实际实现一致
- **H3 语义说明**：[undo_service.py](src/application/undo_service.py) undo 记录 source_path 语义说明（后随 D4 决策一并消除）
- **M9 docstring 修正**：[logging_setup.py](src/app/logging_setup.py) 路径名 `SkyrimModWorkbench` → `SkyrimContentWorkbench`，补充数据目录解析优先级

**批次 2：死代码清理（M1 / M2 / M3）**

- **M1**：[file_classify.py](src/infrastructure/file_classify.py) 删除 `AssetHint` / `classify_by_extension` / `IMAGE_EXTENSIONS` 及对应测试，保留 `ARCHIVE_EXTENSIONS` 和 `get_extension`
- **M2**：[errors.py](src/application/errors.py) 删除从未被使用的 `ScanError` 类
- **M3**：[conftest.py](tests/conftest.py) 删除无引用的 `sample_mod_tree` fixture

**批次 3：测试修正（M4 / M5 / M6）**

- **M4**：删除误导性测试 `test_delete_commits_without_explicit_commit` / `test_remove_root_persists_without_explicit_commit`（虚假保障，与设计契约冲突）
- **M5**：[test_content_service.py](tests/test_content_service.py) 删除局部 `db_connection` fixture 遮蔽，统一使用 conftest
- **M6**：[test_managed_root_service.py](tests/test_managed_root_service.py) 删除 `__import__("sqlite3").Row` hack（随 M4 一并删除）

**批次 4：类型与 API 修正（M7 / M8 / M14）**

- **M7**：[folder_tree_service.py](src/application/folder_tree_service.py) `fc_root_map: dict[str, object]` → `dict[str, FolderCache]`，移除 `# type: ignore`
- **M8**：[folder_cache.py](src/infrastructure/repositories/folder_cache.py) `upsert_mtime` 移除冗余 `path` 参数，签名改为 `upsert_mtime(mtime, folder_id)`，同步更新 3 处调用方
- **M14**：[scan_service.py](src/application/scan_service.py) 删除 `ScanSummary.success` 属性（恒返回 True 具误导性），docstring 说明调用方应使用 `has_errors`

**批次 5：Domain 校验 + 事务边界（M10 / M11 / M13）**

- **M10 事务边界**：[db.py](src/infrastructure/db.py) init_db 在 v0 基线 INSERT 后添加显式 `conn.commit()`，与 docstring 契约一致
- **M11 冗余状态**：[main_window.py](src/app/main_window.py) 删除 `_on_scan_started` 中冗余的 `STATUS_SCANNING` 设置
- **M13 Domain 校验**：[models.py](src/domain/models.py) `ContentUnit.content_type` 新增 `VALID_CONTENT_TYPES` 取值范围校验，与 `OperationHistory.operation_type` 校验对齐

**批次 6：D1 ModGroupService 代码层重命名**

- **D1 决策落地（决策 A）**：代码层重命名，UI 文本保留 "Mod 组"
  - `ModGroupService` → `ContentUnitCreationService`（[content_unit_creation_service.py](src/application/content_unit_creation_service.py)）
  - `create_mod_group` → `create_content_unit_from_file`
  - 错误类 `ModGroupSourceNotInStagingError` / `InvalidModGroupNameError` → `SourceNotInStagingError` / `InvalidContentUnitNameError`
  - 同步更新 [main.py](src/app/main.py) / [main_window.py](src/app/main_window.py) / [assembly_service.py](src/application/assembly_service.py) / [unit_of_work.py](src/infrastructure/unit_of_work.py) / [file_operation_service.py](src/infrastructure/file_operation_service.py) / [folder_cache_sync_helper.py](src/infrastructure/folder_cache_sync_helper.py) 等
  - 测试文件名和 `TestCreateModGroup` 类名保留（代码层重命名，UI 术语保留）

**批次 7：schema v11 迁移（D2/D3 + D4 + H5 + M12）**

- **D2/D3 决策落地（决策 B + C）**：ContentUnit.status → is_marked: bool（破坏性 schema 迁移）
  - content_unit 表移除 `status` 列，新增 `is_marked INTEGER NOT NULL DEFAULT 1 CHECK(is_marked IN (0, 1))`
  - 数据迁移：`status='organized'` → `is_marked=1`，`status='unmarked'` → `is_marked=0`
  - Domain 层 `ContentUnit` / `SearchResult` 字段 `status: str` → `is_marked: bool`，`__post_init__` 增加 bool 类型校验
  - Repository / Service / UI 全链路改用 `is_marked`，消除 "organized" 字面歧义
- **D4 决策落地（决策 A，用户修正）**：撤销操作不再写入 operation_history
  - `UndoService.undo()` 不再创建新 OperationHistory 记录，仅调用 `_repo.mark_undone(history.id, self._now())` 标记原记录
  - 迁移函数清理历史 `operation_type='undo'` 记录
  - H3 问题（source_path 存 ID 而非路径）随之消失，无需新增 `original_op_id` 列
- **H5 + TD-H9**：content_unit 表新增 `path_key TEXT NOT NULL UNIQUE` 列
  - 与 managed_root / staging_area 模式一致，DB 层强制路径归一化唯一
  - 迁移时回填 `path_key = make_path_key(path)`，ContentUnitRepository.create / update 自动计算 path_key
- **M12 冗余索引清理**：删除 5 个对 UNIQUE/复合主键的冗余索引
  - `idx_managed_root_path_key` / `idx_content_unit_path` / `idx_folder_cache_path` / `idx_staging_area_path_key` / `idx_content_unit_tag_cu`
  - 新增有效索引：`idx_content_unit_is_marked`
- [db.py](src/infrastructure/db.py) `CURRENT_SCHEMA_VERSION` 10 → 11
- [migrations.py](src/infrastructure/migrations.py) 新增 `migrate_v10_to_v11`

**批次 8：文档更新**

- [technical-debt.md](docs/technical-debt.md) 标记已修复项（TD-H9 / TD-H11 / TD-L6 / TD-L10 / TD-L11 / TD-L12 / TD-L15 / TD-L17 / TD-L22 / TD-M1 / TD-M3 / TD-M4 / TD-M18 / TD-M19 / TD-M20），新增技术债（TD-H12 / TD-M31-M35 / TD-L23-L29），更新处理优先级建议
- [open-questions.md](docs/open-questions.md) 关闭 Q1 / Q2 / Q7，更新 Q3-Q6 现状，新增 D1-D5 决策记录
- 新增 [stage5-code-review.md](docs/stage5-code-review.md) 完整 Code Review 报告

**架构改进**

- **schema v11 统一迁移**：将 H5（path_key 列）、D2/D3（status → is_marked）、D4（撤销不记录）、M12（冗余索引清理）四项 schema 变更一次性落地，避免分散迁移成本
- **概念清晰化**：ContentUnit 从字符串状态（organized/unmarked）简化为布尔语义（is_marked），消除字面歧义
- **路径归一化 DB 层强制**：content_unit 新增 path_key UNIQUE 约束，与 managed_root / staging_area 模式一致，消除应用层兜底的不完全保障
- **撤销链路简化**：撤销操作不再写入新记录，仅标记原记录 `undone_at`，UI 通过该字段判断灰色状态

**延期处理（归入后续版本）**

- **UI 重构版本**（用户决策：单独开分支）：TD-M21 + TD-M31（MainWindow God Object 拆分）、TD-H10（FileOperationService 分层迁移）、TD-M26（MainWindow 集成测试）、TD-M35（异常类型统一）、UI 重构清单 8 项
- **数据一致性版本**（Stage 6 前）：TD-H12（文件操作事务不一致补偿）、TD-M32（undo 安全校验快照）、TD-M33（mark_undone 重复撤销）
- **性能优化版本**：TD-H3（UI 冻结）、TD-M28（N+1 查询）

**测试**

- 全量回归：1341 passed, 5 skipped（5 个 skip 为 Windows 权限相关，与本次改动无关）
- ruff check + format 全通过

---

## [0.40.0] - 2026-07-30

Stage 5 Task 7：全局搜索 + ContentUnit.status 简化

完成全局搜索功能（Q2=B 仅搜索 organized 状态），并借此机会清理 ContentUnit.status 字段：将从未被生产代码写入的 `organized`（"已整理"语义）和 `missing` 取值废弃，将原 `unorganized`（"已标记"语义）重命名为更直观的 `organized`，最终 status 仅保留两态。schema_version v9 → v10 迁移。

**新增功能**

- 新增 [SearchService](src/application/search_service.py) / [SearchRepository](src/infrastructure/repositories/search.py)：跨表 LIKE 查询（content_unit.title + tag.name + content_unit.notes），支持中文 UTF-8，Q7=B matched_field 优先级排序（title > tag > notes）
- 新增 [SearchDialog](src/app/search_dialog.py)：搜索结果列表对话框，双击跳转到对应内容单元所在目录并选中
  - 整理模式下双击不跳转，仅在状态栏静默提示 3 秒（避免打断整理流程）
- [MainWindow](src/app/main_window.py) 集成搜索入口：
  - 顶部工具栏搜索框（固定宽度 360px，避免输入内容导致宽度变化）
  - Ctrl+F 快捷键聚焦搜索框
  - 搜索结果双击跳转：浏览模式下选中目录树节点 + 选中中栏条目
- 目录树右键新增「折叠全部」入口：搜索跳转会展开大量节点，此入口用于快速收起（保留根节点展开）
- [ui_constants.py](src/app/ui_constants.py) 新增文案：MENU_COLLAPSE_ALL / SEARCH_ORGANIZE_MODE_NO_JUMP / 搜索对话框相关文案

**ContentUnit.status 简化（破坏性变更）**

- **背景**：调查发现 `organized`（"已整理"语义）和 `missing`（"路径丢失"语义）两个取值从未被任何生产代码写入，仅 UI 和搜索查询布线，属于半实现/未实现状态。spec 已删除 rating 和 status 字段，但 status 因 `unmarked` 承载核心业务逻辑（取消标记后阻止扫描器重建）而保留。
- **方案**：将原 `unorganized`（"已标记"语义）重命名为 `organized`，删除旧 `organized` 和 `missing` 取值。最终两态：
  - `organized`：当前标记为内容单元
  - `unmarked`：用户已取消标记（保留记录以阻止扫描器重新创建）
- [migrations.py](src/infrastructure/migrations.py) 新增 `migrate_v9_to_v10`：UPDATE 现有 status='unorganized' → 'organized'（幂等，无匹配记录时不影响任何行）
- [db.py](src/infrastructure/db.py) `CURRENT_SCHEMA_VERSION` 9 → 10
- [domain/models.py](src/domain/models.py) `ContentUnit.status` 默认值 `unorganized` → `organized`
- [content_service.py](src/application/content_service.py) / [scan_service.py](src/application/scan_service.py) 所有 `status="unorganized"` → `status="organized"`
- [search.py](src/infrastructure/repositories/search.py) WHERE 条件简化为 `cu.status = 'organized'`（原 `IN ('unorganized', 'organized')`）
- UI 简化：
  - [file_list_model.py](src/app/file_list_model.py) 名称列统一显示 `[内容单元]` 标记（移除 organized ✓ 区分）
  - [main_window.py](src/app/main_window.py) 元数据面板移除"整理状态"行（仅一态显示无意义）
  - [card_list_model.py](src/app/card_list_model.py) 卡片 ToolTip 显示固定"内容单元"文案（移除状态值显示）
- [ui_constants.py](src/app/ui_constants.py) 清理：移除 `CONTENT_UNIT_MARKER_ORGANIZED` / `CONTENT_UNIT_MARKER_UNORGANIZED` / `METADATA_STATUS_LABEL` / `METADATA_STATUS_UNORGANIZED` / `METADATA_STATUS_ORGANIZED` / `CARD_TOOLTIP_CONTENT_UNIT_STATUS`，新增统一常量 `CONTENT_UNIT_MARKER` / `CARD_TOOLTIP_CONTENT_UNIT`

**设计要点**

- **搜索范围 Q2=B**：仅搜索 organized 状态，排除 unmarked。理由：unmarked 是用户显式取消标记（不再是内容单元），搜索这些记录对用户无意义。用户若需搜索历史已取消标记的路径，可借助外部工具。
- **搜索框固定宽度**：使用 `setFixedWidth(360)` 而非 `setMaximumWidth`，避免输入内容或清除按钮导致宽度变化。
- **整理模式静默提示**：弹窗会打断整理流程，改为状态栏 3 秒提示。
- **目录树折叠全部**：保留根节点展开状态，避免完全收起后无法看到受管理根列表。

**测试**

- 新增 [test_search_repository.py](tests/test_search_repository.py) 24 个用例：基础搜索 / 中文搜索 / 标签搜索 / 状态过滤（organized 被搜索 / unmarked 被排除）/ 排序 / 通配符转义 / 大小写不敏感
- 新增 [test_search_service.py](tests/test_search_service.py) 11 个用例：空关键词 / 短关键词 / 正常搜索 / 异常处理
- 新增 [test_search_dialog.py](tests/test_search_dialog.py) 13 个用例：初始状态 / 搜索结果展示 / 双击跳转 / 整理模式静默提示 / 中文路径
- 适配 [test_main_window_staging.py](tests/test_main_window_staging.py) `test_context_menu_noop_without_staging_service`：原调用 `_on_tree_context_menu` 触发模态 `QMenu.exec`（Shiboken C++ 内置方法无法被 monkeypatch 拦截，导致 180s 超时），改为直接验证 `_collapse_all_tree()`，测试耗时从 180s 降至 0.6s
- 全局替换 `unorganized` → `organized`，重写 `TestStatusFilter` 仅测 organized/unmarked 两态
- 全量回归：1338 passed, 5 skipped, ruff check + format 全通过

---

## [0.39.0] - 2026-07-30

Stage 5 Task 5：「移动到...」快捷对话框

为 Task 3a/3b 的文件操作补齐「选中条目 → 选择目标目录 → 批量移动」的快捷对话框入口，支持中栏 + 目录树双入口及 Ctrl+M 快捷键。schema_version 维持 9，无数据库迁移。

**新增功能**

- 新增 [MoveToDialog](src/app/move_to_dialog.py)：内嵌独立 FolderTreeModel 的目录选择对话框
  - 顶部提示移动条目数量（Q1=A 多选支持）
  - 中间 QTreeView 惰性加载目录树，显示暂存区标记 `[S]`（Q8=A）
  - 底部路径回显 + 确定/取消按钮，确定按钮初始禁用，选中合法目标后启用
  - R1：选中源自身或子目录时确定按钮禁用 + 提示「不能移动到自身或子目录，请选择其他目录」
  - R2：对话框创建独立 FolderTreeModel 实例，不共享主窗口 model
  - Q6=B：不提供「新建文件夹」入口
  - Q7=A：默认展开源所在目录的父目录并选中
  - 程序化测试接口：`select_target_by_path` / `click_ok_button` / `click_cancel_button` / `is_ok_button_enabled` / `selected_target_path` / `src_count`
- [MainWindow](src/app/main_window.py) 集成「移动到...」入口：
  - 中栏右键菜单添加「移动到...」项（Q4=A 中栏 + 目录树均添加）
  - 目录树右键菜单添加「移动到...」项
  - 注册 Ctrl+M 快捷键（Q3=B 中栏 + 目录树 WidgetShortcut 上下文）
  - `_on_move_to` / `_on_move_to_tree`：收集源路径 + 默认展开路径，弹出对话框
  - `_perform_move_to`：复用 ConflictResolutionService 检测冲突 → ConflictResolutionDialog 用户决策 → FileOperationService.move 执行（跨盘剪切拒绝、源自身/子目录阻止、覆盖模式传递 overwrite 参数）
  - Q9=A：对话框本身即确认，无二次确认弹窗
- [ui_constants.py](src/app/ui_constants.py) 新增文案：MENU_MOVE_TO / SHORTCUT_MOVE_TO_* / MOVE_TO_DIALOG_*

**设计要点**

- **对话框只收集选择，不执行文件操作**：MoveToDialog 仅返回目标路径，由 MainWindow 调用 FileOperationService.move 执行，符合 UI 层不直接操作文件系统的约束
- **复用 ConflictResolutionService**：与 Task 3b 的粘贴流程共用冲突检测/解决逻辑，保持行为一致
- **源自身/子目录校验**：使用 make_path_key 归一化比较（AGENTS 规则 9），尾部加分隔符前缀判断避免 `D:/abc` 误匹配 `D:/abcd`
- **独立 FolderTreeModel 实例**：避免对话框刷新影响主窗口目录树状态
- **快捷键上下文分离**：Ctrl+M 仅需 FileOperationService，与 Ctrl+C/X/V（需 ClipboardService）独立 gating

**测试**

- 新增 [test_move_to_dialog.py](tests/test_move_to_dialog.py) 18 个用例：初始状态 / 选中目标 / 源自身子目录校验 / 确定取消按钮 / 默认展开 / 独立 model 实例
- 新增 [test_main_window_move_to.py](tests/test_main_window_move_to.py) 13 个用例：Ctrl+M 中栏（无选中/移动文件/取消/多选） / Ctrl+M 目录树（移动目录/无选中） / 冲突解决（覆盖/取消） / 快捷键注册（注入/未注入 FileOperationService） / 右键菜单包含项 / 移动后 UI 刷新
- 全量回归：1293 passed, 5 skipped, ruff check + format 全通过

---

## [0.38.0] - 2026-07-30

Stage 5 Task 3b：应用内文件复制/剪切/粘贴 + 冲突解决 + 操作历史自动清理

为 Task 3a 已实现的文件操作补齐**复制/剪切/粘贴**能力，配套冲突解决对话框，并引入操作历史上限保护避免数据库膨胀。schema_version v8 → v9 迁移。

**新增功能**

- Schema v9 迁移：operation_history.operation_type CHECK 约束扩展包含 `'copy'`，支持复制操作历史记录。SQLite 不支持直接修改 CHECK 约束，采用重建表方式迁移，旧数据全部保留
- 新增 [ClipboardService](src/application/clipboard_service.py)：应用内剪贴板（Q3=A 不与系统剪贴板混用，Q6=A 不持久化，实例变量保存状态，关闭即清空）
  - `set_copy(paths)` / `set_cut(paths)`：设置复制/剪切状态，覆盖旧状态
  - `get()`：返回当前 ClipboardEntry 或 None
  - `is_cut(path)` / `cut_paths()`：查询剪切状态（用于 UI 半透明高亮）
  - `clear()`：清空剪贴板
- 新增 [ConflictResolutionService](src/application/conflict_resolution_service.py)：粘贴冲突检测与解决
  - `scan_conflicts(src_paths, dst_dir, operation)`：扫描目标目录已有同名文件，生成 ConflictItem 列表（含 suggested_dst 重命名建议，Windows 风格 `file (1).ext` 递增）
  - `resolve(conflicts, decisions)`：根据用户决策（覆盖/跳过/重命名）生成 ResolvedAction 列表，覆盖时 `overwrite=True` 由调用方先删除目标
  - 跨盘剪切检测：`is_cross_drive` 标记（Q7=B 跨盘剪切拒绝提示，跨盘复制允许）
- 新增 [ConflictResolutionDialog](src/app/conflict_resolution_dialog.py)：冲突解决 UI
  - QTableWidget 展示冲突列表（源文件名 / 处理方式单选 / 重命名预览）
  - 默认「重命名」（最安全选项）；支持「应用到全部」一键统一所有行决策
- 扩展 [FileOperationService](src/infrastructure/file_operation_service.py)：
  - 新增 `copy(src, dst, *, overwrite=False)` 方法：复制文件/目录，跨盘复制允许（不退化），can_undo=False（Q4=A 不可撤销）
  - `move()` / `copy()` 新增 `overwrite` keyword-only 参数：为 True 时调用 `_remove_target_for_overwrite()` 先删除目标 + 同步元数据（folder_cache + ContentUnit），再执行移动/复制
  - 新增 `_remove_target_for_overwrite()`：覆盖前直接删除目标（不进回收站，不写 delete 历史），同步失败 best-effort 记日志不中断
  - 新增 `_sync_on_copy()`：目录复制同步 folder_cache（on_folder_created）+ 复制 ContentUnit（新 id + 新 path，Q10=A 元数据保留）
  - **操作历史自动清理**：`__init__` 新增 `max_history_records: int = 1000` 参数；新增 `_create_history()` 辅助方法，**写入前**预清理到 `limit-1`（为新记录腾位，避免新记录被误删），仅删除 `can_undo=0 或 undone_at IS NOT NULL` 的记录（保留可撤销记录供用户撤销）
  - 所有 `self._repo.create(history)` 替换为 `self._create_history(history)`
- 扩展 [OperationHistoryRepository](src/infrastructure/repositories/operation_history.py)：
  - 新增 `count()`：返回 operation_history 总记录数
  - 新增 `delete_oldest_exceeding(limit, *, preserve_can_undo=True)`：删除超出上限的最旧记录，preserve_can_undo=True 时保留可撤销记录（can_undo=1 且 undone_at IS NULL）
- [MainWindow](src/app/main_window.py) 集成剪贴板 + 冲突解决 + 快捷键 + 右键菜单：
  - 注入 ClipboardService
  - **快捷键**：中栏和目录树均注册 Ctrl+C/X/V（WidgetShortcut 上下文，用户补充需求：目录树支持全部快捷键）；目录树补齐 F2/Delete
  - **右键菜单**：中栏和目录树右键菜单添加「复制」「剪切」「粘贴」「删除」项；粘贴项根据剪贴板状态动态启用/禁用
  - **半透明渲染**：FileListModel / CardListModel 新增 `set_cut_paths()` 方法，剪切条目以 50% 透明度（alpha=128）渲染（Q12=A）
  - **粘贴流程**：`_perform_paste()` 调用 ConflictResolutionService 检测冲突 → ConflictResolutionDialog 用户决策 → FileOperationService 执行 copy/move（传递 overwrite 参数）
- [ui_constants.py](src/app/ui_constants.py) 新增剪贴板 / 冲突解决文案：SHORTCUT_COPIED / SHORTCUT_CUT / SHORTCUT_PASTED / SHORTCUT_PASTE_EMPTY / SHORTCUT_PASTE_PARTIAL / SHORTCUT_PASTE_CROSS_DRIVE_CUT / SHORTCUT_PASTE_SRC_NOT_FOUND / SHORTCUT_PASTE_FAILED / CONFLICT_DIALOG_* / MENU_COPY / MENU_CUT / MENU_PASTE

**设计要点**

- **应用内剪贴板（Q3=A）**：状态保存在 ClipboardService 实例变量中，不与系统剪贴板混用，关闭即清空，避免误粘贴外部内容到 Mod 目录
- **冲突解决流程分离**：scan_conflicts（检测）→ ConflictResolutionDialog（用户决策）→ resolve（生成 ResolvedAction）→ FileOperationService 执行，逻辑清晰可测试
- **覆盖前先删除**：ConflictResolutionDialog 选「覆盖」时，resolve 返回 `overwrite=True`，FileOperationService 先删除目标 + 同步元数据，再执行 copy/move。避免直接调用 copy/move 因 `dst.exists()` 抛 ConflictError
- **操作历史预清理策略**：写入新记录前先清理到 `limit-1`，为新记录腾位；仅删除不可撤销/已撤销记录，保留可撤销记录供用户撤销
- **目录树与中栏功能统一（用户补充）**：目录树支持全部快捷键（F2/Delete/Ctrl+C/X/V）及右键菜单（复制/剪切/粘贴/删除），复用 `_perform_paste` 等核心方法
- **快捷键上下文分离**：F2/Delete 仅需 FileOperationService；Ctrl+C/X/V 需 FileOperationService + ClipboardService，独立 gating 避免互相阻塞

**测试**

- 新增 [test_clipboard_service.py](tests/test_clipboard_service.py) 13 个用例：set_copy/set_cut 覆盖 / get / is_cut / cut_paths / clear / 输入不变性 / now_provider 注入
- 新增 [test_conflict_resolution_service.py](tests/test_conflict_resolution_service.py) 18 个用例：scan_conflicts（无冲突/有冲突/多源/跨盘检测） / resolve（覆盖/跳过/重命名/数量不匹配/非法决策） / _suggest_rename 递增 / has_conflict / has_cross_drive_cut
- 新增 [test_conflict_resolution_dialog.py](tests/test_conflict_resolution_dialog.py) 8 个用例：默认重命名 / 多冲突 / 空列表 / 应用到全部 / 中文文件名 / 预览列 / 单选切换 / unchecked 忽略
- 新增 [test_operation_history_cleanup.py](tests/test_operation_history_cleanup.py) 14 个用例：count / delete_oldest_exceeding（未超限/超限/保留可撤销/不区分删除/已撤销可清理/0关闭/负数） / FileOperationService 自动清理（超限触发/0关闭/保留可撤销）
- 扩展 [test_file_operation_service.py](tests/test_file_operation_service.py) TestCopy 类 8 个用例 + TestCopyAutoSync 4 个用例 + TestCopyWithoutSync 1 用例 + copy overwrite 3 用例 + move overwrite 2 用例
- 扩展 [test_main_window_shortcuts.py](tests/test_main_window_shortcuts.py) 替换 Ctrl+C/X/V 占位测试为真实功能测试 12 用例 + 目录树全快捷键测试
- 扩展 [test_migrations.py](tests/test_migrations.py) v8→v9 迁移测试 4 用例 + 修正 v0→current 版本断言
- 全量回归：1262 passed, 5 skipped, ruff check + format 全通过

---

## [0.37.0] - 2026-07-30

Stage 5 Task 4：键盘快捷键

为 Task 3a 已实现的文件操作（new_folder / rename / delete）和 Task 6 的 undo 框架补齐键盘入口，提升高频操作效率。schema_version 维持 8，无数据库迁移。

> Ctrl+C / Ctrl+X / Ctrl+V 当前为静默占位（Q4: C），真实剪贴板逻辑在 Task 3b 接入。

**新增功能**

- [MainWindow](src/app/main_window.py) 新增 `_setup_shortcuts` 方法注册快捷键：
  - **F2（中栏）**：重命名选中条目，Q1=A 多选取第一个；WidgetShortcut 上下文，仅中栏聚焦生效
  - **F2（目录树）**：重命名选中目录树节点（用户补充需求：目录树也需要重命名快捷键，其他快捷键暂不在目录树生效防止误操作）；WidgetShortcut 上下文
  - **Delete（中栏）**：删除选中条目（移至回收站）；WidgetShortcut 上下文
  - **Ctrl+Z（窗口级）**：撤销最近一条可撤销操作；WindowShortcut 上下文，任意位置聚焦均可触发
  - **Ctrl+A（中栏）**：全选；WidgetShortcut 上下文
  - **Ctrl+C / Ctrl+X / Ctrl+V（中栏）**：静默占位（Q4=C），Task 3b 接入真实逻辑；WidgetShortcut 上下文
- 新增处理函数：
  - `_on_shortcut_rename_content`：F2 中栏重命名，多选取第一个
  - `_on_shortcut_rename_tree`：F2 目录树重命名，从目录树节点构造 FileEntry 复用 `_on_rename_entry`
  - `_on_shortcut_delete`：Delete 删除，复用 `_on_delete_entries`
  - `_on_shortcut_select_all`：Ctrl+A 全选
  - `_on_shortcut_undo`：Ctrl+Z 撤销，Q2=A 二次确认弹窗；Q3=B 跳过 delete/undo/已撤销记录，取第一条可撤销的
- 快捷键注册条件（避免误操作）：
  - F2 / Delete / 目录树 F2 仅在注入 FileOperationService 时注册
  - Ctrl+Z 仅在注入 UndoService 时注册
  - Ctrl+A / Ctrl+C/X/V 始终注册
- [ui_constants.py](src/app/ui_constants.py) 新增快捷键文案：SHORTCUT_NO_SELECTION / SHORTCUT_NO_UNDOABLE / SHORTCUT_UNDO_SUCCESS / SHORTCUT_UNDO_FAILED / SHORTCUT_UNDO_SAFETY_FAILED / SHORTCUT_UNDO_NOT_ALLOWED / SHORTCUT_UNDO_CONFIRM_TITLE / SHORTCUT_UNDO_CONFIRM_TEXT

**设计要点**

- **Q5=A WidgetShortcut 上下文**：中栏快捷键仅在中栏聚焦时触发，目录树快捷键仅在目录树聚焦时触发，避免误操作；Ctrl+Z 例外使用 WindowShortcut，因为撤销是全局操作
- **Q3=B 跳过 delete/已撤销/undo 记录**：Ctrl+Z 遍历 `list_recent(100)` 取第一条 `can_undo=True and undone_at IS NULL and operation_type != 'undo'` 的记录，避免撤销 delete（实际撤销由回收站提供）和无限循环
- **Q2=A 二次确认**：执行撤销前弹出 `QMessageBox.question` 显示操作描述，用户确认才执行
- **目录树 F2 复用 `_on_rename_entry`**：构造 FileEntry（is_dir=True, modified_at 占位为 1970-01-01T00:00:00Z），与中栏 F2 走同一逻辑链路
- **未注入对应 Service 时快捷键不注册**：测试中显式断言未注入 FileOperationService 时 `_shortcut_rename` / `_shortcut_rename_tree` / `_shortcut_delete` 不存在；未注入 UndoService 时 `_shortcut_undo` 不存在

**测试**

- 新增 [test_main_window_shortcuts.py](tests/test_main_window_shortcuts.py) 18 个用例：
  - F2 中栏重命名（单选 / 多选取第一个 / 无选中状态栏提示）
  - F2 目录树重命名（成功 / 无选中状态栏提示）
  - Delete 删除（单选 / 无选中状态栏提示）
  - Ctrl+Z 撤销（有可撤销 + 二次确认 / 无可撤销状态栏提示 / 跳过 delete 记录 / 二次确认取消）
  - Ctrl+A 全选
  - Ctrl+C/X/V 占位验证（快捷键已注册）
  - 快捷键注册条件验证（注入 / 未注入 FileOperationService / UndoService）
- 全量回归：1183 passed, 5 skipped, ruff check + format 全通过

---

## [0.36.0] - 2026-07-30

Stage 5 Task 6：操作历史与撤销框架

为 Stage 5 Task 3a 已实现的文件操作（new_folder / rename / delete）以及更早的 move 操作补齐**撤销框架**，并提供查看操作历史的 UI 入口。schema_version v7 → v8 迁移。

**新增功能**

- Schema v8 迁移：operation_history 表新增 `undone_at TEXT NULL` 列（NULL 表示未撤销，非 NULL 为撤销时间戳）；operation_type CHECK 约束扩展为包含 `'undo'`。SQLite 不支持直接修改 CHECK 约束，采用重建表方式迁移。旧数据全部保留，undone_at 默认 NULL
- 扩展 [OperationHistoryRepository](src/infrastructure/repositories/operation_history.py)：
  - 新增 `list_recent(limit=100)`：按 created_at 降序返回最近 N 条记录（最新在上），限制查询条数避免全表加载
  - 新增 `mark_undone(history_id, undone_at)`：标记原操作为已撤销，写入 undone_at 时间戳。已撤销的记录再次 mark_undone 抛 ConstraintViolationError
  - `_row_to_model` 兼容 v7 旧 schema（无 undone_at 列时返回 None）
- 新增 [UndoService](src/application/undo_service.py)：
  - `undo(history) -> OperationHistory`：撤销一条记录，返回新写入的 undo 记录
  - 前置校验：can_undo / operation_type（delete/undo 拒绝）/ undone_at（不可重复撤销）
  - 安全校验（Q5=A）：路径存在 + size/mtime 校验。new_folder 校验空目录；rename/move 校验 target 存在 + source 不存在（避免覆盖外部创建的文件）
  - 反向操作分派：new_folder → 删除空文件夹（rmdir）；rename → 反向 rename（通过 FileOperationService.rename）；move → 反向 move（通过 FileOperationService.move）
  - 同步：new_folder 撤销后通过 FolderCacheSyncHelper.on_folder_deleted 删除 folder_cache 节点；rename/move 撤销由 FileOperationService 内部同步逻辑处理
  - 写 undo 记录：operation_type='undo'，source_path 指向原 history.id（形成审计链），can_undo=False（避免无限循环撤销），undone_at 必为 None
  - 标记原记录：mark_undone 写入时间戳
- 新增 [errors.py](src/application/errors.py) 撤销异常：`UndoError`（基础）/ `UndoNotAllowedError`（delete/undo/can_undo=False）/ `UndoSafetyError`（含 reason 字段）/ `UndoAlreadyUndoneError`
- 新增 [OperationHistoryDialog](src/app/operation_history_dialog.py)：
  - QTableWidget 4 列（时间 / 操作 / 描述 / 状态），按 created_at 降序（最新在上）
  - can_undo=False 的行整行灰色，撤销按钮禁用
  - 已撤销的行（undone_at 非空）显示「已撤销」标记，整行灰色
  - 底部按钮：刷新 / 撤销选中 / 关闭
  - Q7=A：撤销前二次确认弹窗
  - 撤销成功后通过 callback 通知 MainWindow 刷新中栏/目录树
- [MainWindow](src/app/main_window.py) 顶部工具栏新增「操作历史」按钮（注入 UndoService 时显示）；`_on_operation_history_clicked` 打开对话框，exec() 返回后 commit + 刷新 UI
- [Domain models](src/domain/models.py) OperationHistory 新增 `undone_at` 字段 + `operation_type='undo'` 校验：undo 记录的 can_undo 必为 False、target_path 必为 None、undone_at 必为 None

**设计要点**

- **undo 不直接复用普通文件操作方法后简单取反**（用户补充要求 #2）：UndoService 内部通过 `_SafetyCheckResult` dataclass 明确记录原始操作类型、操作前状态（source_size/source_mtime）、操作后状态（target_size/target_mtime）、安全检查结果（ok + reason）
- **undo 记录不可再撤销**（避免无限循环）：operation_type='undo' 的 can_undo 必为 False，`_check_undo_allowed` 前置拦截
- **跨会话撤销**（Q2=A）：operation_history 持久化设计，重启应用后历史记录仍可查询、仍可撤销状态安全的操作
- **事务边界**：UndoService 不自提交，由 MainWindow 在 dialog.exec() 返回后 commit；失败时 rollback

**测试**

- 新增 [test_undo_service.py](tests/test_undo_service.py) 25 个用例：
  - 正常 undo（new_folder / rename / move 三种类型）
  - 文件被外部修改后的 undo 阻止（源/目标不存在）
  - 文件不存在后的 undo 阻止（target 已删除）
  - 多次 undo（连续撤销不同记录）
  - 重启应用后历史恢复（重新构造 UndoService 后仍能撤销）
  - undo 自身不会进入可无限 undo 循环（undo 记录不可再撤销）
  - delete / undo 操作拒绝撤销
  - 已撤销操作重复撤销
  - new_folder 非空时撤销阻止（Q4=A）
  - folder_cache + ContentUnit.path 同步
  - list_recent 查询（降序 + limit + 含已撤销记录）
  - OperationHistory 数据模型 v8 校验
  - mark_undone 仓储方法
- 更新 [test_migrations.py](tests/test_migrations.py)：v8 迁移测试 + schema 版本断言更新为 8
- 全量回归：1165 passed, 5 skipped, ruff check + format 全通过

---

## [0.35.0] - 2026-07-30

Stage 5 Task 3a：新建文件夹 + 重命名 + 删除（移至回收站）

> 原 Task 3 拆分的第一部分，覆盖最基础的文件 CRUD。为 Task 6 undo 框架做铺垫。
> schema_version 维持 7，无数据库迁移。

**新增功能**

- 新增 [windows_recycle_bin.py](src/infrastructure/windows_recycle_bin.py)：ctypes 封装 `SHFileOperationW` 实现 Windows 回收站操作（Q1: B，不引入 send2trash 第三方依赖）。批量路径一次性提交给 SHFileOperation，使用 `FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI` 标志。仅 Windows 平台可用，非 Windows 抛 `RecycleBinError`。
- 扩展 [FileOperationService](src/infrastructure/file_operation_service.py)：
  - `new_folder`：已存在的最小实现（Stage 3 Task 3），本次确认注入 helper 后自动同步 folder_cache
  - 新增 `rename(old_path, new_name)`：真实重命名 + 同步 folder_cache + ContentUnit.path 前缀重写 + 写 operation_history
  - 新增 `delete_to_recycle_bin(paths) -> (histories, sync_errors)`：批量移至回收站 + 同步 folder_cache（删除目录及子节点）+ 删除关联 ContentUnit + 写 operation_history
- [ui_constants.py](src/app/ui_constants.py) 新增菜单项与对话框文案：MENU_NEW_FOLDER / MENU_RENAME / MENU_DELETE / 删除确认对话框 / 部分成功提示 / 操作成功状态栏文案
- [main_window.py](src/app/main_window.py)：
  - 新增 `_refresh_content_list_after_file_op(dir_path)`：文件操作后 `_refresh_tree` 会 reset tree 模型，浏览模式下 selectionModel 可能暂时失效，此方法用保存的 dir_path 直接刷新列表
  - 新增 `_on_new_folder_for_entry` / `_on_new_folder_in_dir`：右键条目新建文件夹（在父目录下创建）+ 目录树右键菜单新增「新建文件夹」项（在选中节点目录下创建）
  - 新增 `_on_rename_entry`：右键重命名 + 对话框 + 同名校验 + 调用 service.rename + 刷新
  - 新增 `_on_delete_entries`：右键删除 + 确认对话框（单条/多条文案）+ 调用 service.delete_to_recycle_bin + 部分成功弹窗
  - `_on_tree_context_menu` 新增「新建文件夹」项（注入 FileOperationService 时显示，加分隔符）

**设计要点**

- **rename 校验顺序**（测试中发现并修复）：必须先校验 `.` / `..` 再校验尾随空格/点（strip 之前），最后校验非法字符。否则 strip 后尾随空格已被去除，校验失效。
- **delete_to_recycle_bin 返回 (histories, sync_errors) 元组**（Q1=A）：SHFileOperation 失败时抛 FileOperationError（文件未删除，可 rollback）；同步失败时返回 sync_errors（文件已删除，需 commit 保留历史）。调用方先 commit 保留历史，再展示同步错误。
- **目录树右键菜单「新建文件夹」**：Stage 5 Task 3a 验收 A 部分发现缺失，修复后注入 FileOperationService 时显示，行为与中栏右键入口一致。

**测试**

- 新增 [test_windows_recycle_bin.py](tests/test_windows_recycle_bin.py)：单文件/目录/批量删除、非 Windows 平台异常路径跳过
- 扩展 [test_file_operation_service.py](tests/test_file_operation_service.py)：rename（含校验、同名跳过、跨盘、中文路径、自动同步 folder_cache + ContentUnit.path）/ delete_to_recycle_bin（单条/批量/空列表/不存在跳过）
- 新增 [test_main_window_file_ops_task3a.py](tests/test_main_window_file_ops_task3a.py)：菜单项显示规则、新建文件夹（中栏 + 目录树右键 + 取消 + 空名 + 重名 + 中文路径 + 刷新）、重命名（成功 + 取消 + 同名跳过 + 非法名称 + 刷新）、删除（单条 + 批量 + 取消 + ContentUnit 同步 + 整理模式）

全量回归：1140 passed, 5 skipped, ruff check + format 全通过。

---

## [0.34.0] - 2026-07-29

Stage 5 Task 2：排序 UI + 前进/后退目录导航 + 验收修复

在 Task 1b 双档缓存架构基础上完成排序 UI 补齐与目录导航，含两轮验收修复。schema_version 维持 7，无数据库迁移。

### Task 2：排序 UI + 前进/后退目录导航

**排序 UI**（在阶段 3 Task 2 已有 `FileListModel.set_sort_key` 基础上补齐）：
- `FileListModel.headerData` 当前排序列追加 ▲/▼ 方向指示（Q1=A 文本方案）
- `set_sort_key` 发射 `headerDataChanged` 刷新列头显示
- 视图切换栏新增排序字段下拉框 + 升降序方向按钮（Q2=A 列表/卡片视图共享）
- 列头点击与下拉框双向同步

**前进/后退目录导航**（用户验收时新增需求，类似资源管理器）：
- 视图切换栏左侧新增 ←/→ 按钮
- 维护浏览历史栈（back_stack + forward_stack + current_nav_path）
- 仅浏览模式记录历史，整理模式不记录
- 相邻相同路径去重，进入新目录清空前进栈（标准浏览器行为）
- 历史导航触发的切换不再入栈，避免循环

**测试**：新增 10 个测试（列头方向指示 3 + 排序下拉框同步 4 + 前进后退导航 4）。全量回归：1065 passed, 3 skipped, ruff check + format 全通过。

### Task 2 验收修复：排序/卡片/批量取消 6 项问题

**问题 1：排序下拉框"名称"需两次点击**
- 根因：`currentIndexChanged` 在索引未变化时不触发信号
- 修复：改用 `activated` 信号（仅用户交互触发，程序化 setCurrentIndex 不触发）

**问题 2：排序方向按钮蓝色高亮**
- 根因：`setCheckable(True)` 的 checked 状态有蓝色背景
- 修复：移除 checkable，方向由文本 ▲/▼ 表达；`setFocusPolicy(NoFocus)` 去除焦点高亮

**问题 3：卡片模式文件名过长撑大卡片**
- 修复：`CardListModel._elide_name` 用 `QFontMetrics.elidedText` 截断长文件名
- `_card_view.setGridSize` 固定网格单元尺寸 + `setUniformItemSizes(True)` + `setWordWrap(False)`

**问题 4：卡片预览图比例影响卡片形状**
- 修复：`CardListModel._crop_to_square` 居中裁剪为 icon_size × icon_size 方形（Q1=A）
- 用 `KeepAspectRatioByExpanding` 填满后居中 crop，横竖图统一外框

**问题 5：批量取消内容单元标记缺失**
- 新增 `_on_batch_unmark_content_unit` handler，容错策略与批量标记一致
- 多选且至少一个已标记时显示菜单项（Q2:A）

**问题 6：右键菜单命名统一**
- `取消标记` → `取消内容单元标记`
- `把每个文件标记为内容单元` → `批量标记为内容单元`（Q3:A）
- 新增 `批量取消内容单元标记`

**测试**：新增 11 个测试。全量回归：1076 passed, 3 skipped, ruff check + format 全通过。

### Task 2 验收修复 2：排序最终方案 + UI 稳定性

> 第二轮验收修复，解决排序下拉框随机失效、右栏跳动、列表无框选等遗留问题。

**问题 1：排序下拉框随机需要两次点击**（核心修复）
- 根因：`currentIndexChanged + activated` 双信号 + deduplication 在 Qt popup 关闭顺序不确定时存在边界失效
- 修复：回归单 `activated` 信号方案，移除 `_sort_field_processing` / `_sort_field_last_index` 状态
- "选当前项重新触发排序"无产品意义，不予支持
- 依赖 `FileListModel.set_sort_key` 内部幂等保护作为重复调用兜底

**问题 2：排序下拉框 popup 当前项蓝色高亮**
- 修复：通过 stylesheet 取消 `QComboBox::item:selected` 蓝色背景，hover 保留浅色提示
  ```css
  QComboBox::item:selected { background: transparent; color: black; }
  QComboBox::item:hover { background: #e0e0e0; }
  ```

**问题 3：右栏元数据路径撑大右栏宽度**（根因）
- 根因：`metadata_panel._path_value.setWordWrap(True)` 与 `_cover_value.setWordWrap(True)` 导致长路径换行撑大 QSplitter
- 修复：新增 `_ElidedLabel` 类（`QSizePolicy.Ignored` + `ElideMiddle` + `ToolTip` 显示完整文本）
- `_path_value` 与 `_cover_value` 改用 `_ElidedLabel`，与左栏目录树路径省略策略一致
- `cover_path_text()` / `_get_form_cover_path()` 改用 `fullText()` 读取完整文本（避免 elide 后的省略形式）

**问题 4：列表视图无 rubber band 框选**
- 根因：`QTableView` 不支持 `setSelectionRectVisible`（仅 QListView 有）
- 修复：新增 `_RubberBandTableView` 子类，自定义 `mousePress/Drag/Release` + `QRubberBand` 实现框选
- 空白区域左键拖动 → 启动 rubber band + 选中范围内所有行（`ClearAndSelect | Rows`）
- 卡片视图显式 `setSelectionRectVisible(True)`（IconMode 默认启用，显式表达一致性）

**测试**：新增 3 个测试（列表视图类型检查、卡片视图 rubber band、全字段切换回归）。全量回归：1080 passed, 3 skipped, ruff check + format 全通过。

### 修复：卡片→列表视图切换选中状态丢失（Task 1b 回归修复）

**问题**：v0.33.0 Task 1b 验收时漏测卡片→列表方向。原实现 `_switch_view` 中 `target_sm.select(idx, SelectionFlag.Select)` 仅选中 `(row, 0)` 单元格，QTableView 多列场景下 `selectedRows()` 返回空（需要整行被选中才算），导致从卡片视图选中切回列表视图时选中丢失。列表→卡片方向因 QListView 单列而侥幸通过。

**根因**：`QItemSelectionModel.select()` 在 `SelectRows` 行为下，程序化选中需要显式附加 `Rows` flag 才能选中整行；仅 `Select` 只选中单元格。

**修复**：[main_window.py](src/app/main_window.py) `_switch_view` 中 `target_sm.select()` 改用 `SelectionFlag.Select | SelectionFlag.Rows`，确保 QTableView / QListView 均整行选中。

**测试**：新增 `test_selection_preserved_card_to_list`（tests/test_main_window_view_switch.py），覆盖卡片→列表方向选中保持。全量回归：1055 passed, 3 skipped, ruff 全通过。

---

## [0.33.0] - 2026-07-29

Stage 5 Task 1b：大图卡片 / 详细列表切换 + 在资源管理器中打开

在 Task 1a 双档缓存架构基础上完成 UI 适配：列表视图改用 Qt 标准图标（移除封面缩略图），新增卡片视图（QListView IconMode）通过 CardListModel 代理 FileListModel 共享数据源（Q6:B），缩放滑块 128~512 支持双击输入，右栏封面预览扩大至 256×256，右键菜单新增「在资源管理器中打开」。

**新增功能**

- 新增 [CardListModel](src/app/card_list_model.py)：轻量代理 model，委托 FileListModel 共享同一份 FileEntry 列表（Q6:B 复用），切换视图不丢失数据。按 icon_size 动态选择缓存档位（≤256 用 256 档，>256 用 512 档），内置 QPixmap 内存缓存避免 data() 高频调用重复缩放
- 新增 `ZoomSlider`（[main_window.py](src/app/main_window.py)）：继承 QSlider，双击弹出 QInputDialog 输入具体数值（128~512），弥补滑块步进不够精细的问题
- 卡片视图缩放滑块范围 128~512（默认 256），通过 QSettings 持久化（Stage 5 Task 1 Q1=A）
- 视图切换 QStackedWidget：QTableView（列表）/ QListView IconMode（卡片）自由切换，选中状态跨视图保持（用 entry.path 匹配，Q4=A）
- 右键菜单「在资源管理器中打开」：调用 `explorer /select,` 定位到文件并选中，中文路径通过 list 形式传参自动处理

**改动**

- [file_list_model.py](src/app/file_list_model.py) `icon_for` 重构：移除缩略图查询逻辑，列表视图始终返回 Qt 标准文件/文件夹图标（Task 1a 决策：64×64 对列表视图无视觉价值）
- [metadata_panel.py](src/app/metadata_panel.py) 封面预览尺寸 120×120 → 256×256，利用 512 档缓存缩小显示，质量优于直接用 256 档
- [main_window.py](src/app/main_window.py) `_init_thumbnail_coordinator`：provider 注入目标从 FileListModel 改为 CardListModel（支持 size 参数）
- [ui_constants.py](src/app/ui_constants.py) 滑块范围 96~256 → 128~512，新增双击输入对话框常量

**架构决策**

- CardListModel 独立注入支持 size 参数的 provider，与 FileListModel 解耦：列表视图不再查询缩略图，卡片视图按 icon_size 选择档位，两者职责清晰
- 卡片名称不含 [内容单元] 标记（Q6:B）：卡片空间有限，完整信息通过 ToolTip 承载（路径 + 内容单元状态）
- 512 档按需生成：滑块拖到 >256 时才查询/生成 512 档，避免全覆盖的磁盘膨胀

**测试**

- 新增 3 个测试文件：`test_card_list_model.py`（11 个）、`test_main_window_view_switch.py`（12 个）、`test_main_window_open_in_explorer.py`（6 个）
- 更新 3 个测试文件适配新行为：`test_file_list_model_thumbnail.py`（列表视图标准图标）、`test_main_window_thumbnail.py`（CardListModel provider 注入）、`test_main_window_content.py`
- 全量回归：1053 passed, 3 skipped, ruff check + format 全通过

---

## [0.32.0] - 2026-07-29

Stage 5 Task 1a：缩略图缓存架构改造（双档 WebP 缓存，为 Task 1b 卡片视图做准备）

将单档 64×64 PNG 缓存升级为双档 256/512 WebP 缓存，支持 lazy generation 和按需生成。schema v6 → v7 迁移。**本 Task 仅改造缓存架构，UI 适配在 Task 1b 完成。**

**新增功能**

- Schema v7 迁移：`thumbnail_cache` 表新增 `size` 列，主键改为 `(content_unit_id, size)` 复合主键。SQLite 不支持 ALTER PRIMARY KEY，采用重建表方式迁移。旧 64 档记录保留（size=64），由 GC 清理无对应 content_unit 的记录
- 缓存格式从 PNG 改为 WebP (quality=90)：磁盘占用从 ~2.8GB/10k 降到 ~950MB/10k，节省约 65%。Qt6 和 Pillow 均原生支持
- 缓存文件命名：`{content_unit_id}_{size}.webp`（如 `u1_256.webp`、`u1_512.webp`）
- `ThumbnailService.get_cache` / `generate` 支持 size 参数，可查询/生成指定档位缓存
- `ThumbnailService.invalidate` 清理指定 unit 的所有档位文件与记录，同时兼容清理旧 v6 命名 `{id}.png`
- `ThumbnailCoordinator.request_thumbnail` 支持 size 参数，pending 集合改为 `(unit_id, size)` 元组去重，允许同一 unit 不同档位并行生成
- `ThumbnailWorker` 信号改为 `(unit_id, size, status)`，默认 size 256

**架构决策**

- 取消 64 档封面缓存：64×64 对 Mod 资源浏览无视觉价值，列表视图将改用分类/状态 icon（Task 1b）
- 256 档：标记内容单元/设置封面时生成，支撑卡片视图 128~256 显示范围
- 512 档：点击卡片时按需生成，支撑右栏 MetadataPanel 大封面预览（Task 1b）和卡片视图 257~512 显示范围
- 512 档未命中时临时用 256 档放大显示，后台生成 512 后替换

**测试**

- 新增 12 个测试：复合主键共存、多档 generate、不同 size 不去重、旧 PNG 清理、WebP 格式验证等
- 更新 6 个测试文件适配新 API（get_by_id_and_size、size 参数、信号签名变化）
- 全量回归：1054 passed, 3 skipped, ruff check + format 全通过

**不在本 Task 范围**

- 列表视图移除封面缩略图、改用分类/状态 icon → Task 1b
- 卡片视图滑块 128~512 + 双击输入 → Task 1b
- 右栏 MetadataPanel 大封面预览 → Task 1b
- 在资源管理器中打开 → Task 1b

---

## [0.31.0] - 2026-07-29

Stage 5 Task 0.5：数据目录路径抽象与隔离（独立前置任务，不纳入 Task 1）

将应用数据目录从 `%LOCALAPPDATA%\SkyrimContentWorkbench\` 迁移到项目根目录 `data/`，为开发环境提供独立数据目录，避免污染系统 AppData。**程序不执行任何自动迁移、复制、删除操作**——若检测到旧目录，仅输出日志提示用户手动迁移，数据安全由用户掌控。schema_version 维持 6，无数据库迁移。

**新增功能**

- [app_paths.py](src/app/app_paths.py) 重构 `get_app_data_root`：路径决策优先级为 `SCW_DATA_DIR 环境变量 > 项目根 data/（开发环境，通过向上查找 pyproject.toml 判定）> %LOCALAPPDATA%\SkyrimContentWorkbench\（Windows 回退）> ~/.skyrimmodworkbench/（非 Windows 回退）`
- [app_paths.py](src/app/app_paths.py) 新增 `_find_project_root`：从本文件向上查找最多 5 层，定位含 `pyproject.toml` 的项目根
- [app_paths.py](src/app/app_paths.py) 新增 `_log_legacy_appdata_hint_if_exists`：检测到旧 `%LOCALAPPDATA%\SkyrimContentWorkbench\` 有数据且新目录无 `app.db` 时，输出日志提示用户手动复制 `app.db`、`thumbnails/`、`exports/`、`logs/` 到新目录。**不执行任何文件操作**（用户决策：程序不动数据）
- [main.py](src/app/main.py) 通过 `ensure_app_directories()` 在启动时创建目录结构（入口未变，仅内部实现变化）

**安全约束**

- 程序只负责创建新目录，不执行任何迁移、复制、移动、删除操作
- 旧目录检测仅触发日志提示，不读取或复制旧目录内容
- 测试 fixture 通过 `SCW_DATA_DIR` 环境变量严格隔离测试数据目录，避免污染项目 `data/`

**配置变更**

- 新增环境变量 `SCW_DATA_DIR`：显式指定应用数据目录路径（生产环境用）
- 新增 [.gitignore](.gitignore) 规则 `/data/`：忽略项目根运行时数据目录
- 保留未来生产环境通过 `SCW_DATA_DIR` 切换到 AppData 的能力

**测试**

- 新增 [tests/test_app_paths.py](tests/test_app_paths.py) 15 个测试：路径优先级（4）+ 项目根定位（2）+ 目录创建与幂等（2）+ 旧目录仅提示不动数据（4）+ 中文/空格路径与一致性（3）
- 修复 [tests/conftest.py](tests/conftest.py) `temp_app_data` fixture：改用 `SCW_DATA_DIR` 隔离测试数据目录，避免测试写入项目 `data/` 污染
- 全量回归：1048 passed, 3 skipped, ruff check + format 全通过

**文档**

- 更新 [docs/roadmap.md](docs/roadmap.md) Stage 5 部分：新增 Task 0.5 章节，标记完成
- 更新 [docs/spec.md](docs/spec.md) 应用数据目录路径说明（如适用）

---

## [0.30.2] - 2026-07-29

Stage 5 Task 0 扩展：手动触发的快速设置封面功能

为 Stage 5 Task 1（大图卡片视图）做铺垫，实现标记文件夹内容单元时自动录入封面，以及右键快速设置封面入口。放弃原方案 D（扫描时自动录入封面，依赖同名匹配，语义复杂），改用纯手动触发方案：仅在用户显式标记文件夹或主动右键「快速设置封面」时触发，不扫描、不匹配、不覆盖已有手动封面。schema_version 维持 6，无数据库迁移。

**新增功能**

- [content_service.py](src/application/content_service.py) `mark_as_content_unit` 标记文件夹后自动调用 `_auto_set_cover_for_folder_unit`：扫描目录顶层图片（jpg/png/webp/gif/bmp），取文件名升序第一张设为 `cover_path`，触发缩略图后台生成。无图静默跳过，已有封面不覆盖。
- [content_service.py](src/application/content_service.py) 新增 `quick_set_cover(unit_id)` 方法：右键入口复用同一逻辑，仅对文件夹内容单元生效，压缩包单元返回 False。
- [main_window.py](src/app/main_window.py) 文件列表右键菜单新增「快速设置封面」项，单选已标记内容单元时显示；压缩包内容单元灰显（`enabled=False`）。抽取 `_build_content_menu_actions` 方法便于测试。
- [ui_constants.py](src/app/ui_constants.py) 新增 `MENU_QUICK_SET_COVER` 等 4 个常量。

**测试**

- 新增 2 个测试文件：`tests/test_content_service_quick_set_cover.py`（8 个用例）+ `tests/test_main_window_quick_set_cover_menu.py`（5 个用例）
- 修复 6 个回归测试：
  - `test_main_window_assembly.py`：`_FakeMenuAction` 补 `setEnabled` no-op（生产代码新增 `act.setEnabled(enabled)` 调用）
  - `test_main_window_metadata.py`：两个内嵌 `FakeMenu.addAction` 返回带 `setEnabled` 的 `_FakeAction`
  - `test_metadata_panel.py`：`unit_with_tags` fixture 创建单元时触发自动录入封面，调整 `cover_path_text()` 断言为 `"cover.jpg"`
- 全量回归：1007 passed, 3 skipped, ruff check + format 全通过

**文档**

- 更新 [docs/roadmap.md](docs/roadmap.md) Task 1 章节：补充「依赖本 Task 0 扩展的自动录入封面已就绪」的备注

---

## [0.30.1] - 2026-07-29

Stage 5 Task 0：前置技术债修复

为 Stage 5 undo 与文件操作功能做基础，修复三项技术债。schema_version 维持 6，无数据库迁移。Stage 5 Task 顺序确认为：Task 0 → Task 1 → Task 2 → Task 3a → Task 6 → Task 4 → Task 3b → Task 5 → Task 3c → Task 7（原 Task 3 拆分为 3a/3b/3c，原 Task 6 提前到 Task 3a 之后）。

**修复**

- **TD-H1**：[models.py](src/domain/models.py) `OperationHistory.__post_init__` 增加 operation_type 与 target_path 一致性校验。move/rename/new_folder 要求 target_path 非空；delete 要求 target_path 为 None。避免 undo 链路数据不一致。
- **TD-L19**：`OperationHistory` delete 操作的 can_undo 必须为 False（delete 不可撤销，回收站已支持还原）。move/rename/new_folder 的 can_undo 校验留待 Task 6 实现 undo 时配合运行时安全检查一并落地。
- **TD-M11**：[main_window.py](src/app/main_window.py) `_commit` 失败时通过 `QMessageBox.critical` 提示用户，标题与消息来自新增的 `ui_constants.DB_COMMIT_FAILED_TITLE` / `DB_COMMIT_FAILED_MESSAGE`。同时保留 `logger.exception` 记录技术细节。

**Stage 5 Task 拆分与顺序调整**

- 原 Task 3 拆分为 Task 3a（新建文件夹 + 重命名 + 删除）/ 3b（复制/剪切/粘贴 + 任意目录间移动）/ 3c（路径丢失检测），原因：原 Task 3 含 6+ 独立子功能，体量过大违反"小而可审查"原则。
- 原 Task 6（操作历史与撤销）提前到 Task 3a 之后，原因：undo 框架是 Task 3b/5 的依赖，提前实现避免后期补写 operation_history。

**Stage 5 已确认的设计决策（用户 2026-07-29 确认）**

- Q1: B — Windows 回收站采用 ctypes SHFileOperation，不引入 send2trash
- Q2: A — 全局搜索使用 LIKE，不引入 FTS5
- Q3: A — 应用内剪贴板，不与系统剪贴板混用
- Q4: A — 操作历史采用 QDialog 弹出
- Q5: 路径丢失仅扫描时检测 + 状态栏提示 + 新增 "missing" status
- Q6: B — 大图卡片视图复用 FileListModel，避免数据源同步问题
- Q7: C — undo 不安全状态在列表标注 + 弹窗提示
- Q8: C — MainWindow 边开发边小规模拆分，不单独开启重构 Task

**测试**

- 新增 9 个测试：`tests/test_domain_models.py` 6 个 OperationHistory 校验测试 + `tests/test_main_window_commit_error.py` 3 个 _commit 失败 UI 反馈测试
- 修复 2 个既有测试：`test_create_delete_without_target` 补 `can_undo=False`；`test_can_undo_false` 补 `target_path`
- 全量回归：991 passed, 3 skipped, ruff check + format 全通过

**文档**

- 更新 [docs/roadmap.md](docs/roadmap.md) Stage 5 部分：标记 Task 0 完成，Task 顺序调整为确认后顺序，记录 Task 拆分原因与设计决策
- 更新 [docs/technical-debt.md](docs/technical-debt.md)：标记 TD-H1 / TD-L19 / TD-M11 已修复

---

## [0.27.0] - 2026-07-29

开发环境清理脚本

新增 `scripts/clean.py`，清理开发过程中产生的临时文件和缓存，保持工作目录整洁。schema_version 维持 6，无数据库迁移。

**新增文件**

- `scripts/clean.py` — 清理脚本主体
- `scripts/README.md` — 清理脚本文档
- `tests/test_clean.py` — 33 个单元测试

**清理范围**

- 安全清理（默认）：`__pycache__/`、`.pytest_cache/`、`.ruff_cache/`、`.cache/`、`build/`、`dist/`、`*.egg-info/`、`*.pyc`、`*.pyo`
- 深度清理（`--all`）：额外清理 `%TEMP%\pytest-of-<用户名>\`（pytest tmp_path 机制产生的临时文件）

**命令行参数**

- `python scripts/clean.py` — 安全清理
- `python scripts/clean.py --all` — 深度清理
- `python scripts/clean.py --dry-run` — 仅查看待清理内容，不实际删除
- `python scripts/clean.py --verbose` — 显示详细清理信息

**受保护内容（永不被删除）**

- 源码与文档：`src/`、`tests/`、`docs/`、`archive/`、`scripts/`
- 应用数据：`app.db`、`thumbnails/`、`exports/`、`logs/`、`local_appdata/`
- 版本控制：`.git/`
- 虚拟环境：`.venv/`、`venv/`
- 项目外数据：用户 Mod 文件不受影响

**测试**

- 新增 33 个测试覆盖 find_safe_targets / is_protected / clean_safe / find_pytest_tmp_dirs / main --dry-run
- 全量回归：982 passed, 3 skipped, ruff check + format 全通过
- 更新 `.gitignore` 显式添加 `*.pyo`

---

## [0.26.1] - 2026-07-29

Stage 4.5 验收回归修复

修复 Stage 4.5 手动验收发现的 3 个回归问题。schema_version 维持 6，无数据库迁移。

**问题 1：缩略图刷新异常（1A + 1B）**

- **根因**: `MainWindow._on_metadata_saved` 无条件调用 `thumbnail_coordinator.invalidate()`，与 Stage 4.5 M4 修复（Service 层条件性 invalidate）叠加，产生未提交的 DELETE 事务，阻塞后台 worker 写入
- **修复**: 删除 UI 层的无条件 invalidate 调用，由 `ContentService.update_metadata` 在事务内条件性处理（仅 cover_path 变化时）
- **影响文件**: [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py)

**问题 2：取消标记不持久化**

- **根因**: `_on_unmark_content_unit` 误以为 `unmark_content_unit` 使用 UoW 自动提交，实际它是单步写方法未走 UoW，handler 必须显式提交
- **修复**: 在 `_on_unmark_content_unit` 中添加 `self._commit()`，修正注释
- **影响文件**: [main_window.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/main_window.py)

**问题 3：外部删除文件后扫描异常（database is locked）**

- **根因**: 问题 1B 的未提交事务 + Stage 4.5 TD-H2 的 ScanWorker 长事务叠加，写锁冲突导致 5 秒超时
- **修复**: `get_connection` 添加 `timeout` 参数（默认 5.0s），ScanWorker/ThumbnailWorker 传 `timeout=30.0`，容忍主线程偶发长事务
- **影响文件**: [db.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/db.py)、[scan_worker.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/scan_worker.py)、[thumbnail_worker.py](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/app/thumbnail_worker.py)

**测试调整**

- `test_main_window_thumbnail.py`：原测试 `test_metadata_saved_calls_coordinator_invalidate` 验证旧行为（UI 层调用 invalidate），改为 `test_metadata_saved_does_not_call_coordinator_invalidate` 验证新行为（UI 层不调用）
- 全量回归：949 passed, 3 skipped, ruff check + format 全通过

---

## [0.26.0] - 2026-07-28

阶段 4.5：技术债清理（Stage 5 前置修复）

Stage 4 Code Review 后的技术债清理，处理影响 Stage 5 稳定性的高优先级问题，为 undo/redo、文件操作等功能建立基础。schema_version 维持 6，无数据库迁移。

**用户确认的设计决策（D1-D7）**

- D1: A — 子项删除失败抛 `ContentUnitCascadeError`，中止父 ContentUnit 创建
- D2: A — `ContentService` 注入 `ThumbnailService`，业务层负责 thumbnail invalidate
- D3: B — Service 内部使用 `UnitOfWork` 管理多步写事务，调用方不负责业务事务控制
- D4: A — TD-H2（ScanService 事务边界）纳入本次修复
- D5: B — `FileOperationService` 分层归属暂不调整，H5 延后到 Stage 5（登记为 TD-H10）
- D6: A — Task 0.3 纳入 Stage 4.5，处理 H4 + TD-M22 + TD-L18
- D7: C — M14「最近常用置顶」登记为技术债（TD-M30），暂不实现

**Task 0.1：缩略图生命周期一致性修复（H1 + H2 + H3 + M4 + M19）**

- H1：`ContentUnitRepository.delete` 级联清理 `thumbnail_cache`，避免 FK 违约
- H2：`mark_as_content_unit` 子项删除失败抛 `ContentUnitCascadeError`，不再静默吞异常
- H3：`ThumbnailCoordinator` pending 集合精确清理（`_on_worker_ready` / `_on_worker_failed` 移除 unit_id），允许同一 unit 重新入队
- M4：`ContentService` 注入 `ThumbnailService`，`update_metadata` 修改 `cover_path` 时主动 invalidate 缩略图缓存
- M19：修正假测试 `test_get_cache_hit_returns_path`（补 assert + 动态 mtime），新增 mtime 失效路径测试

**Task 0.2：事务边界整理（H6 + H7 + M18 + TD-H2）**

- 新建 [UnitOfWork](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/application/unit_of_work.py)：封装 SQLite 连接的 commit/rollback，支持嵌套事务（仅最外层实际提交/回滚，内层仅调整深度计数）
- H6：Service 多步写方法（`TagService.delete_category` / `batch_attach_tags` / `import_from_json` / `ContentService.mark_as_content_unit` / `ModGroupService.create_mod_group` / `QuickInsertService.quick_insert`）改用 UoW 管理事务
- H7：MainWindow handler 统一 rollback 模板（`_handle_service_error`）
- M18：补 MetadataPanel 标签 attach 失败路径测试
- TD-H2：ScanService `_persist_scan_result` 在 UoW 事务内执行多步写，任一失败整体回滚

**Task 0.3：文件移动同步（H4 + TD-M22 + TD-L18）**

- 新建 [FolderCacheSyncHelper](file:///c:/AphrosyneData/Skyrim-Content-Workbench/src/infrastructure/folder_cache_sync_helper.py)：集中 folder_cache 同步逻辑，提供 `on_folder_created` / `on_folder_moved` / `on_folder_deleted` / `update_folder_mtime` 语义化方法
- H4：`FileOperationService.move` / `new_folder` 注入 helper + ContentUnitRepository，自动同步 folder_cache + ContentUnit.path，消除调用方手动同步的隐式契约
- TD-M22：`ModGroupService` / `QuickInsertService` / `AssemblyService` 移除重复的 folder_cache 同步逻辑（`_resolve_parent_id_by_path` / `_delete_folder_cache_by_path` / `_create_folder_cache_for_new_path` / `_update_parent_mtime` / `_sync_folder_mtime`），统一由 `FileOperationService` 内部 helper 自动同步
- TD-L18：`FolderCacheSyncHelper` 明确区分两类契约——单字段 mtime 更新为 best-effort（失败仅记日志），多步同步失败抛 `FileOperationError`
- 修复 `FolderCacheSyncHelper.on_folder_moved` 异常包装问题：多步同步失败时抛出 `FileOperationError`，由上层 UoW 回滚

**测试覆盖**

- 新增 `test_unit_of_work.py`：UnitOfWork 嵌套事务 commit/rollback 行为
- 新增 `test_folder_cache_sync_helper.py`：helper 核心功能 + 错误处理
- 扩展 `test_file_operation_service.py`：H4 自动同步 folder_cache + ContentUnit.path 回归测试
- 扩展 `test_content_service.py`：H2 ContentUnitCascadeError + M4 缩略图失效
- 扩展 `test_thumbnail_coordinator.py`：H3 pending 精确清理 + 重新入队
- 扩展 `test_scan_service.py`：TD-H2 事务边界回滚
- 修正 3 个 MainWindow 集成测试 fixture（`test_main_window_quick_insert.py` / `test_main_window_assembly.py` / `test_main_window_context_menu_task3.py`）：注入 FolderCacheSyncHelper + ContentUnitRepository 到 FileOperationService
- 修正假测试 `test_get_cache_hit_returns_path`（M19）
- 全量回归：949 passed, 3 skipped, ruff check + format 全通过

**技术债登记**

- 新登记：TD-H9（path UNIQUE 绕过 make_path_key）、TD-H10（FileOperationService 分层）、TD-M28（N+1 查询）、TD-M29（测试组织）、TD-L21（UI 硬编码颜色）、TD-M30（M14 最近常用置顶）
- 已修复：TD-H2（ScanService 事务边界）、TD-M22（folder_cache 同步 helper）、TD-L18（mtime 策略统一）
- 详见 [technical-debt.md](docs/technical-debt.md)

## [0.25.0] - 2026-07-27

阶段 4 Task 4：封面预览

为内容单元在文件列表中显示封面缩略图，新增缩略图缓存系统与后台生成调度。schema_version 维持 6，无数据库迁移（`thumbnail_cache` 表已在 schema v3/v4 中创建）。

**用户确认的设计决策（Q1-Q9）**

- Q1: C — 缩略图尺寸可配置（默认 64×64，验收时判断大小是否合适）
- Q2: C — 应用圆角边框（Pillow 绘制圆角遮罩，半径 = size × 0.18）
- Q3: A — 缩略图源图 = ContentUnit.path + cover_path（无 cover_path 不生成）
- Q4: A — 缓存有效性 = content_unit_id + source_size + source_modified_at + 文件存在
- Q5: A — 缓存未命中直接投递后台生成，无前置状态查询
- Q6: A — 单 worker + FIFO 队列（避免并发与 SQLite 锁）
- Q7: A — 同一 unit_id 在途时去重（不重复投递）
- Q8: B — 启动时执行 GC：清理无对应 content_unit 的缓存记录 + 目录中无 DB 记录的 PNG 文件
- Q9: A — UI 层（FileListModel）通过注入的 thumbnail_provider 回调获取 QPixmap，不直接调用 infrastructure

**Application 层新增**

- `ThumbnailService`：
  - `get_cache(unit_id, source_path) -> Path | None`：缓存命中同步返回 Path
  - `generate(unit_id, source_path) -> str`：生成缩略图 + 写入缓存记录，返回 status（ok/missing/corrupt/unsupported/error）
  - `invalidate(unit_id)`：删除缓存记录与文件
  - `cleanup_orphans() -> int`：GC 清理孤立缓存（Q8:B）

**Infrastructure 层新增**

- `thumbnail_generator.py`：`generate_thumbnail(source_path, cache_path, size)`，Pillow 只读加载 + 保持宽高比缩放 + 应用圆角遮罩 + 写入 PNG
- `repositories/thumbnail_cache.py`：`ThumbnailCacheRepository` 提供 upsert / get_by_id / delete / list_all / list_by_unit_ids

**UI 层新增组件**

- `app/thumbnail_worker.py`：`ThumbnailWorker(QObject)`，在 QThread 中创建独立 SQLite 连接调用 `ThumbnailService.generate`，发射 `thumbnail_ready(unit_id, status)` / `thumbnail_failed(unit_id, error)`
- `app/thumbnail_coordinator.py`：`ThumbnailCoordinator(QObject)`，管理 FIFO 队列 + 去重 set + 单 worker 调度，提供 `request_thumbnail` / `invalidate` / `shutdown` 接口
- `FileListModel` 新增 `set_thumbnail_provider(provider)` / `notify_thumbnail_ready(unit_id)`，DecorationRole 调用 provider 获取 QPixmap

**MainWindow 集成调整**

- 构造注入 `thumbnail_coordinator` 参数（可选，未注入时退化为标准图标）
- `_init_thumbnail_coordinator`：启动 coordinator + 注入 provider 到 FileListModel
- `_thumbnail_provider`：缓存命中同步返回 QPixmap，未命中投递后台生成
- `_on_thumbnail_ready`：调用 `FileListModel.notify_thumbnail_ready` 刷新对应行
- `_on_metadata_saved`：保存元数据后调用 `coordinator.invalidate` 失效旧缓存（封面变更场景）
- `closeEvent`：调用 `coordinator.shutdown()` 等待后台线程退出（避免 Windows STATUS_STACK_BUFFER_OVERRUN 崩溃）
- `app/main.py`：启动时创建 ThumbnailService 并执行 `cleanup_orphans()`（GC，Q8:B）

**测试覆盖**

- `test_thumbnail_generator.py`：11 项 — 生成成功、圆角应用、覆盖写入、源图不存在/不支持/损坏、各种格式（JPG/PNG/WEBP/GIF/BMP/TIFF/ICO）、源图签名
- `test_thumbnail_cache_repository.py`：9 项 — CRUD、批量查询、空输入处理
- `test_thumbnail_service.py`：14 项 — 缓存命中/未命中、各种异常状态记录、invalidate、GC 清理孤立记录/文件、保留有效缓存
- `test_thumbnail_coordinator.py`：8 项 — 缓存命中/未命中、去重、invalidate、shutdown、thumbnail_ready 信号、可配置尺寸
- `test_file_list_model_thumbnail.py`：8 项 — DecorationRole 注入、provider 调用、notify_thumbnail_ready 触发刷新、未注入 provider 退化为标准图标
- `test_main_window_thumbnail.py`：4 项 — coordinator 未注入降级、注入初始化 provider、closeEvent 调用 shutdown、metadata_saved 触发 invalidate

**已知未实现项**

- 浏览模式下大图卡片展示封面（roadmap Task 4 验收项之一）：本轮仅实现列表小图标，大图卡片延后到下一阶段

## [0.24.0] - 2026-07-27

阶段 4 Task 3：标签筛选

浏览模式下中栏顶部新增标签筛选栏，支持多分类多选标签实时筛选内容单元。schema_version 维持 6，无数据库迁移。

**用户确认的设计决策（Q1-Q8）**

- Q1: B — 筛选激活时非内容单元条目全部隐藏，列表变成纯结果集
- Q2: A — 分类互斥展开（同时只展开一个分类）
- Q3: A — 切换目录树节点时筛选状态保留，自动应用于新目录
- Q4: A — 同分类 OR，跨分类 AND
- Q5: A — 默认全部折叠
- Q6: A — 筛选激活时保留元数据面板交互（不清空不隐藏，用户可继续查看选中条目的元数据）
- Q7: A — 选中标签使用边框高亮（不显示已选总数总览）
- Q8: A — 仅基础筛选，不做标签计数徽标

**Application 层新增**

- `TagService.list_content_unit_ids_by_tags(tag_ids)`: 多标签 OR 取并集，返回 `set[unit_id]`
- `TagService.filter_unit_ids_by_category_and(tag_ids)`: 按 category_id 分组 → 每个分类 OR 取并集 → 跨分类 AND 取交集

**UI 层新增组件**

- `TagFilterBar(QWidget)`：浏览模式下中栏顶部嵌入，分类按钮互斥展开 + 标签按钮多选边框高亮 + 「清除全部」按钮
- 折叠态下分类按钮显示已选数徽标「分类名 (N)」
- 无分类时控件隐藏（与 TagService 未注入降级一致）
- `ui_constants.py` 新增常量：TAG_FILTER_BAR_TITLE / TAG_FILTER_BAR_HINT / TAG_FILTER_CLEAR_BUTTON / TAG_FILTER_NO_RESULT_HINT 等

**MainWindow 集成调整**

- `_setup_ui`：注入 TagService 时创建 TagFilterBar 嵌入中栏顶部，连接 `on_filter_changed` 信号
- `_refresh_content_list`：增加 `_apply_tag_filter` 过滤，筛选激活时仅保留匹配的 content_unit 条目
- `_on_tag_filter_changed`：筛选激活时保留 MetadataPanel 可见性（Q6: A 修正：不清空不隐藏），刷新中栏
- `_on_content_selection_changed`：筛选激活时仍响应单击加载 MetadataPanel（Q6: A 修正）
- `_on_mode_changed`：整理模式隐藏 TagFilterBar；切回浏览模式恢复，已选标签保留
- `_on_tag_manager_clicked`：标签管理对话框关闭后调用 `_refresh_tag_filter_bar()`，自动剔除已删除的已选标签并重新筛选

**测试覆盖**

- `test_tag_service.py` 新增 `TestListContentUnitIdsByTags`（4 项）+ `TestFilterUnitIdsByCategoryAnd`（6 项）
- `test_tag_filter.py` 新建，覆盖 16 项：初始状态、分类展开/折叠、互斥、标签多选 toggle、信号发射、清除按钮、折叠保留已选、徽标、refresh_categories 保留/剔除、空分类提示
- `test_main_window_tag_filter.py` 新建，覆盖 11 项：创建条件、模式显隐、筛选激活行为、空结果提示、目录切换保留、MetadataPanel 保留加载（Q6: A）

## [0.23.1] - 2026-07-25

阶段 4 Task 2：验收修正（单击加载 + 预选标签 + 回车不关闭窗口 + 整理模式右栏方案 B）

Stage 4 Task 2 手动验收发现的 4 项问题修正。schema_version 维持 6，无数据库迁移。所有修正均围绕交互体验与设计一致性，不涉及数据结构变化。

**用户确认的设计修正**

- **问题 1（MetadataPanel 单击加载）**：原双击为主要入口不符合产品交互。修正为单击内容单元即加载 MetadataPanel（spec §7.2 主要交互入口）；双击行为兼容保留；单击非内容单元按设计清空元数据面板。`_on_content_selection_changed` 早已实现此逻辑，本轮修正确认其生效并补齐测试。
- **问题 2（预选标签区域）**：标签输入框下方新增预选标签列表，显示所有已有标签（排除已在 chip 列表中的），单击即可快速添加到 chip。同时应用到 `MetadataPanel` 与 `BatchTagDialog`。
- **问题 3（BatchTagDialog 回车行为）**：原回车触发默认按钮导致窗口关闭、立即执行添加，无法连续添加多个标签。通过 `setAutoDefault(False)` 禁用 `_ok_button` / `_cancel_button` 的自动默认行为，回车仅触发输入框 `returnPressed` 信号，把标签加入 dialog 内的 chip 列表，不关闭窗口、不立即执行。最终点击「应用」按钮才执行批量添加。`CoverPickerDialog` 同步修正。
- **问题 4（整理模式右栏设计修正为方案 B）**：原决策 4/8 整理模式完全隐藏右栏，但实测后右侧空白，无法释放空间。用户决策改为方案 B：保留 MetadataPanel，让用户在装配同时编辑元数据，避免创建完内容单元后切回浏览模式才能编辑元数据的多余步骤。`_on_mode_changed` 移除隐藏逻辑。

**UI 层新增组件**

- MetadataPanel / BatchTagDialog 预选标签区域：`QListWidget` LeftToRight + Wrapping，单击添加到 chip，添加后从预选列表移除，chip 移除后回归预选列表。空状态显示 `METADATA_PANEL_PRESET_TAGS_EMPTY_HINT` / `BATCH_TAG_DIALOG_PRESET_TAGS_EMPTY_HINT`。

**MainWindow 集成调整**

- `_on_mode_changed` 移除整理模式隐藏右栏逻辑（原 `_metadata_group.setVisible(False)`），两种模式下右栏均可见。
- `_on_content_selection_changed` 单击加载逻辑保持不变（已实现，本轮补齐测试）。

**UI 常量**

- 新增 4 个常量：`METADATA_PANEL_PRESET_TAGS_LABEL` / `METADATA_PANEL_PRESET_TAGS_EMPTY_HINT` / `BATCH_TAG_DIALOG_PRESET_TAGS_LABEL` / `BATCH_TAG_DIALOG_PRESET_TAGS_EMPTY_HINT`。

**测试覆盖**

新增 16 项测试：

- `tests/test_metadata_panel.py`（追加 6 项）：预选列表初始空 / load_unit 填充并排除 chip / 单击添加 / chip 移除回归 / clear_panel 清空 / 全部 chip 排除。
- `tests/test_batch_tag_dialog.py`（追加 6 项）：预选列表初始填充 / 排除已加 chip / 单击添加 / chip 移除回归 / 全部 chip 排除 / 回车不关闭窗口（单次 + 多次）/ 仅「应用」按钮触发 accept。
- `tests/test_main_window_metadata.py`（追加 2 项 + 替换 2 项）：单击内容单元加载 / 单击非内容单元清空；删除 `test_organize_mode_hides_metadata_panel` / `test_browse_mode_restores_metadata_panel`，替换为 `test_organize_mode_keeps_metadata_panel_visible` / `test_organize_to_browse_keeps_metadata_panel_visible`。

#### Added

- [src/app/metadata_panel.py](src/app/metadata_panel.py)：新增预选标签区域（`_preset_label` / `_preset_list` / `_preset_empty_hint`）+ `_on_preset_tag_clicked` / `_refresh_preset_list` 方法 + `preset_tag_names()` / `click_preset_tag()` 测试辅助接口。
- [src/app/batch_tag_dialog.py](src/app/batch_tag_dialog.py)：同上新增预选标签区域。
- [src/app/ui_constants.py](src/app/ui_constants.py)：新增 4 个预选标签相关常量。
- [tests/test_metadata_panel.py](tests/test_metadata_panel.py)：追加 6 项预选标签测试。
- [tests/test_batch_tag_dialog.py](tests/test_batch_tag_dialog.py)：追加 6 项预选标签 + 3 项回车行为测试。
- [tests/test_main_window_metadata.py](tests/test_main_window_metadata.py)：追加 2 项单击加载测试 + 替换 2 项整理模式测试。

#### Changed

- [src/app/metadata_panel.py](src/app/metadata_panel.py)：`load_unit` / `clear_panel` / `_on_tag_input_return` / `_on_tag_clicked` 调用 `_refresh_preset_list`；`_set_form_enabled` 启用/禁用新增的 `_preset_list`。
- [src/app/batch_tag_dialog.py](src/app/batch_tag_dialog.py)：`_on_tag_input_return` / `_on_tag_clicked` 调用 `_refresh_preset_list`；`_ok_button` / `_cancel_button` 调用 `setAutoDefault(False)`。
- [src/app/cover_picker_dialog.py](src/app/cover_picker_dialog.py)：按钮调用 `setAutoDefault(False)`（同步修正，避免回车关闭）。
- [src/app/main_window.py](src/app/main_window.py)：`_on_mode_changed` 移除整理模式隐藏右栏逻辑（决策 4/8 推翻，方案 B）；`is_metadata_panel_visible()` docstring 更新；模块 docstring 移除"双击内容单元时显示"的旧描述。
- [docs/architecture.md](docs/architecture.md)：§3.1 调整整理模式右栏描述；§4.3 元数据保存流程更新为「单击加载」。
- [docs/roadmap.md](docs/roadmap.md)：Task 2 验收项 + 决策修正记录。

## [0.23.0] - 2026-07-19

阶段 4 Task 2：元数据编辑

Stage 4 第二项功能开发。实现 spec §4.1 / §5.1 / §7.2 / §9 / §10 定义的元数据编辑 + 打标签 + 批量打标签 + 封面选择能力。schema_version 维持 6，无数据库迁移。合并原 roadmap 中 Task 2「元数据编辑」和「打标签」为单个 Task 一次性做完（设计决策：同一个右栏面板操作）。

**用户确认的 8 项设计决策**

1. 元数据保存策略：显式「保存」按钮（不做自动保存）。
2. 封面自动候选：CoverPickerDialog 默认选中第一张图片。
3. N 网 URL 自动合成：本 Task 不实现，留待后续。
4. 整理模式右栏：完全隐藏 MetadataPanel。
5. 标签自动补全匹配：前缀匹配（LIKE 'prefix%' ESCAPE）。
6. 标签输入交互形式：chip 列表 + 独立输入框（QListWidget LeftToRight + Wrapping）。
7. 现有测试接口：保留 `metadata_text()` / `metadata_full_text()` 兼容方法。
8. 整理模式右栏具体显示：完全隐藏（不显示任何替代内容）。

**Application 层扩展**

- `ContentService.update_metadata(unit_id, title, source_url, notes, cover_path)`：统一更新元数据 + 封面路径。
  - 字段校验：title 最大 200 字符、source_url 最大 2000 字符。
  - cover_path 语义：None=不改、""=清空、非空字符串=设置具体路径。
  - cover_path 校验：拒绝绝对路径和 `..`，必须为相对内容单元路径的相对路径，存储时统一转换为 POSIX 风格分隔符。
- `ContentService.list_cover_candidates(unit_path)`：返回内容单元目录下所有支持格式的图片文件路径列表。
  - 支持格式：jpg/jpeg/png/webp/gif/bmp/tif/tiff/ico。
- `TagService.search_tags(prefix)` / `TagService.search_tags_by_name(prefix)`：前缀匹配查询标签（用于自动补全）。
- `TagService.list_tags_by_content_unit(unit_id)` / `TagService.list_tag_ids_by_content_unit(unit_id)`：查询内容单元已关联的标签。
- `TagService.set_content_unit_tags(unit_id, tag_ids)`：diff 计算（to_add / to_remove）+ 事务内 attach / detach。
- `TagService.batch_attach_tags(unit_ids, tag_ids)` / `TagService.batch_detach_tags(unit_ids, tag_ids)`：批量打标签 / 批量移除标签。
- 异常分层：新增 `InvalidMetadataError` / `CoverImageNotFoundError`（ApplicationError 子类）。

**Infrastructure 层扩展**

- `TagRepository.search_by_name_prefix(prefix)`：LIKE 'prefix%' ESCAPE 查询，`_like_escape` 函数处理 `\` / `%` / `_` 特殊字符。
- `ContentUnitTagRepository.list_tag_rows_by_content_unit(unit_id)`：返回完整 Tag 行（含 category_id）供 service 层构造 Tag 对象。

**UI 层新增组件**

- `MetadataPanel`（[src/app/metadata_panel.py](src/app/metadata_panel.py)）：右栏元数据编辑表单。
  - 字段：标题（QLineEdit）/ 标签（chip 列表 + 独立输入框 + QCompleter 自动补全）/ 来源 URL（QLineEdit）/ 备注（QTextEdit）/ 封面预览 + 设置/清除按钮。
  - chip 列表：QListWidget with Flow LeftToRight + Wrapping，单击移除。
  - 信号：`on_saved(ContentUnit)` / `on_pick_cover_requested(unit_id)`。
  - 事务边界：Service 不自提交，由 MainWindow 在 `on_saved` 信号回调中 commit。
  - 测试辅助接口：`current_unit()` / `is_form_enabled()` / `tag_chips()` / `tag_input_text()` / `set_tag_input_text()` / `submit_tag_input()` / `click_chip()` / `click_save_button()` / `click_pick_cover_button()` / `set_cover_path(rel_path)` / `clear_panel()` 等。

- `BatchTagDialog`（[src/app/batch_tag_dialog.py](src/app/batch_tag_dialog.py)）：批量打标签对话框。
  - 输入：TagService + content_unit_ids 列表。
  - 操作模式：添加 / 移除（RadioButton 切换）。
  - chip 列表 + 独立输入框 + QCompleter 自动补全（与 MetadataPanel 一致）。
  - 应用后调用 `batch_attach_tags` / `batch_detach_tags`，返回 `result_messages` 列表。
  - 测试辅助接口：`target_count()` / `current_mode()` / `set_mode()` / `tag_chips()` / `submit_tag_input()` / `click_chip()` / `click_apply_button()` / `result_messages()` 等。

- `CoverPickerDialog`（[src/app/cover_picker_dialog.py](src/app/cover_picker_dialog.py)）：封面选择对话框。
  - 输入：candidates 列表 + unit_path + current_cover（无 service 依赖）。
  - UI：QListWidget IconMode + Wrap，120x120 缩略图。
  - 默认选中第一张，或当前封面（若提供且在候选列表中）。
  - 返回：选中图片的 POSIX 风格相对路径。
  - 测试辅助接口：`candidate_count()` / `current_selection_row()` / `click_item(index)` / `click_ok_button()` / `click_cancel_button()` / `is_ok_button_enabled()` 等。

**MainWindow 集成**

- 右栏改造：注入 `tag_service` 时创建 MetadataPanel 并替换原 `_metadata_label`；未注入时保持原 QLabel 行为（兼容旧测试）。
- `_update_metadata`：兼容旧测试缓存 `_metadata_full_text`，同时若有 MetadataPanel 则加载 unit 到 panel。
- 新增信号处理：`_on_metadata_saved`（保存后 commit + 刷新 + 状态栏提示）/ `_on_pick_cover_requested`（弹出 CoverPickerDialog + 设置封面路径）。
- 新增批量打标签：`_on_batch_tag` 处理右键菜单动作，弹出 BatchTagDialog，应用后 commit + 刷新 + 状态栏显示结果消息。
- 批量打标签菜单项：在 `_on_content_context_menu` 中，多选且至少一个内容单元 + 注入了 TagService 时显示。
- 整理模式完全隐藏右栏：`_on_mode_changed` 中 `_metadata_group.setVisible(False)`（设计决策 4 / 8）。
- 新增测试接口：`is_metadata_panel_visible()` / `metadata_panel()`。

**UI 常量**

- 新增 ~50 个常量：`METADATA_PANEL_*`（保存按钮 / 设置封面 / 标签输入 / 提示等）/ `BATCH_TAG_DIALOG_*`（标题 / 输入 / 操作模式 / 结果消息等）/ `COVER_PICKER_DIALOG_*`（标题 / 提示 / 空候选等）。
- 新增 `MENU_BATCH_TAG = "批量打标签"` 右键菜单项。

**测试覆盖**

新增 4 个 UI 测试文件（79 项）+ 在已有 service / repository 测试文件中新增 45 项：
- `tests/test_metadata_panel.py`（新建）：25 项（构造 / load_unit / 标签 chip 增删 / 自动补全 / 保存 / 封面 / 异常 / 兼容接口）。
- `tests/test_batch_tag_dialog.py`（新建）：25 项（初始状态 / 模式切换 / chip 增删 / 自动补全 / 应用 add / 应用 remove / 空标签警告 / 幂等性 / 中文标签）。
- `tests/test_cover_picker_dialog.py`（新建）：15 项（初始状态 / 默认选中第一张 / 当前封面 / 切换选择 / 确定/取消 / 空候选 / 中文文件名 / POSIX 风格路径）。
- `tests/test_main_window_metadata.py`（新建）：14 项（MetadataPanel 创建条件 / 双击加载 / 保存元数据 / 设置封面 / 整理模式隐藏 / 批量打标签 / 兼容性）。
- `tests/test_content_service.py`（追加）：19 项新测试（update_metadata 字段校验 / cover_path 校验 / list_cover_candidates）。
- `tests/test_tag_service.py`（追加）：19 项新测试（search / list_tags_by_content_unit / set_content_unit_tags diff / batch_attach / batch_detach）。
- `tests/test_tag_repository.py`（追加）：5 项新测试（search_by_name_prefix + 特殊字符转义）。
- `tests/test_content_unit_tag_repository.py`（追加）：2 项新测试（list_tag_rows_by_content_unit）。

**测试结果**：659 passed → 799 passed（+140），3 skipped。

#### Added

- [src/app/metadata_panel.py](src/app/metadata_panel.py)：新建 MetadataPanel。
- [src/app/batch_tag_dialog.py](src/app/batch_tag_dialog.py)：新建 BatchTagDialog。
- [src/app/cover_picker_dialog.py](src/app/cover_picker_dialog.py)：新建 CoverPickerDialog。
- [tests/test_metadata_panel.py](tests/test_metadata_panel.py)：25 项测试。
- [tests/test_batch_tag_dialog.py](tests/test_batch_tag_dialog.py)：25 项测试。
- [tests/test_cover_picker_dialog.py](tests/test_cover_picker_dialog.py)：15 项测试。
- [tests/test_main_window_metadata.py](tests/test_main_window_metadata.py)：14 项测试。
- [src/app/ui_constants.py](src/app/ui_constants.py)：新增 ~50 个 MetadataPanel / BatchTagDialog / CoverPickerDialog 相关常量 + `MENU_BATCH_TAG`。

#### Changed

- [src/application/content_service.py](src/application/content_service.py)：新增 `update_metadata` / `_validate_cover_path` / `list_cover_candidates` 方法。
- [src/application/tag_service.py](src/application/tag_service.py)：新增 6 个方法（search_tags / search_tags_by_name / list_tags_by_content_unit / list_tag_ids_by_content_unit / set_content_unit_tags / batch_attach_tags / batch_detach_tags）。
- [src/application/errors.py](src/application/errors.py)：新增 `InvalidMetadataError` / `CoverImageNotFoundError`。
- [src/infrastructure/repositories/tag.py](src/infrastructure/repositories/tag.py)：新增 `search_by_name_prefix` + `_like_escape`。
- [src/infrastructure/repositories/content_unit_tag.py](src/infrastructure/repositories/content_unit_tag.py)：新增 `list_tag_rows_by_content_unit`。
- [src/app/main_window.py](src/app/main_window.py)：右栏条件性创建 MetadataPanel + 信号处理 + 批量打标签菜单 + 整理模式隐藏右栏 + 测试辅助接口。
- [docs/architecture.md](docs/architecture.md)：§3.1 / §3.2 / §4.1 / §4.3 更新（MetadataPanel / BatchTagDialog / CoverPickerDialog 组件职责、TagService/ContentService 新方法、元数据保存/封面选择/批量打标签数据流）。
- [docs/roadmap.md](docs/roadmap.md)：Stage 4 Task 2 验收项打勾。

## [0.22.0] - 2026-07-18

阶段 4 Task 1：标签分类管理 + JSON 导入导出

Stage 4 第一项功能开发。实现 spec §10 / §4.2-4.4 定义的标签系统：TagCategory + Tag + ContentUnitTag 三表结构 + TagService 应用层 + TagManagerDialog UI 对话框 + 预置标签库自动加载 + JSON 导入导出。

**Schema v5 → v6 迁移**

- 移除 `content_unit.rating` 列（用户决策 13.2：私人数据库用不上 rating 字段）。
- `tag_category.name` 加 UNIQUE 约束（通过 `idx_tag_category_name_unique` 索引实现）。
- `tag (name, category_id)` 加 UNIQUE 约束（通过 `idx_tag_name_category_unique` 索引实现，同分类下不重名，不同分类可重名）。
- 迁移幂等：`rating` 列已不存在时跳过 DROP；UNIQUE 索引用 `CREATE UNIQUE INDEX IF NOT EXISTS`。
- `CURRENT_SCHEMA_VERSION` 从 5 升至 6。

**新增 Domain / Repository**

- `TagCategory` dataclass：id / name / color_hue（spec §4.2）。
- `Tag` dataclass：id / name / category_id（spec §4.3）。
- `TagCategoryRepository`：create / get_by_id / get_by_name / list_all / update / delete（不自提交，FK 违约包装为 RepositoryError）。
- `TagRepository`：create / get_by_id / get_by_name_in_category / list_all / list_by_category / list_by_ids / update / delete。
- `ContentUnitTagRepository`：attach（INSERT OR IGNORE 幂等）/ detach / detach_all_by_content_unit / detach_all_by_tag / detach_all_by_category（子查询级联）/ list_tag_ids_by_content_unit / list_content_unit_ids_by_tag / count_by_tag / count_by_category / is_attached。

**新增 Application 层 TagService**

- TagCategory CRUD：create_category / get_category / list_categories / rename_category / update_category_color / delete_category（级联清理：content_unit_tag → tag → category）。
- Tag CRUD：create_tag / get_tag / list_tags_by_category / list_all_tags / rename_tag / move_tag_to_category / delete_tag（级联清理 content_unit_tag）。
- list_categories_with_tags：一次性返回所有分类及其下标签（供 UI 加载）。
- JSON 导入（import_from_json）：schema_version 校验、合并跳过策略（同名分类整体跳过，不同名分类正常创建）、同分类下同名标签跳过、事务原子性（失败时由调用方 rollback）。
- JSON 导出（export_to_json）：ensure_ascii=False 保留中文。
- 预置库加载（load_default_tags_if_empty）：仅当 tag_category 表为空时加载，失败不阻塞应用启动（D3）。
- 异常分层：RepositoryError / ConstraintViolationError → ApplicationError 子类（DuplicateTagCategoryNameError / DuplicateTagNameError / TagCategoryNotFoundError / TagNotFoundError / InvalidTagJsonError）。

**新增 UI TagManagerDialog**

- QTreeWidget 树形展示（分类为顶级节点，标签为子节点），自动展开。
- 工具栏按钮：新增分类 / 重命名分类 / 改颜色 / 删除分类 / 新增标签 / 重命名标签 / 移动标签 / 删除标签 / 导入 JSON / 导出 JSON。
- 色块图标：QColor.fromHsl 转 16x16 QPixmap。
- 空状态提示：无分类时显示提示文字。
- 事务边界：Dialog 持有 commit_callback 引用，每次操作后立即提交（F6）。
- 异常处理：service 抛 ApplicationError 时弹 QMessageBox.critical 提示用户。

**预置标签库（src/app/resources/default_tags.json）**

5 个分类 + 23 个标签（依据 spec §10.1 / roadmap Stage 4 Task 1）：
- 服装护甲（H=210，蓝色系）：重甲、轻甲、法袍、现代、幻想、裸露、内衣、泳装、饰品、杂项、合集（11 个）
- 武器（H=30，橙色系）：单手剑、双手剑、弓、法杖（4 个）
- 作者（H=120，绿色系）：（空，用户自行添加）
- 来源（H=0）：N 网、L 网、韩网、群友分享、私货（5 个）
- 状态（H=280）：已测试、已汉化、待测试（3 个）

**集成到 MainWindow 与 main.py**

- MainWindow 顶部栏新增「标签管理」按钮（在快速插入按钮后），点击打开 TagManagerDialog。
- MainWindow 构造新增 `tag_service: TagService | None = None` 参数，未注入时按钮隐藏。
- MainWindow 移除 rating 显示（metadata_full_text 不再含评分行）。
- main.py 启动序列新增：构造 TagService → 加载预置标签库（失败不阻塞启动）→ 注入 MainWindow。

**文档同步**

- `docs/architecture.md` §4.1 / §4.2 / §6.1 / §6.4 / §10 / §11.1 / §12 更新：schema v4 → v6、TagService 依赖关系、表结构新增 UNIQUE 约束、移除 rating 列说明。

**测试覆盖**

新增 5 个测试文件，共 109 项测试：
- `tests/test_tag_category_repository.py`：15 项（CRUD / UNIQUE 约束 / 中文 / 不自提交 / FK 违约）。
- `tests/test_tag_repository.py`：20 项（CRUD / (name, category_id) UNIQUE / 跨分类同名 / FK 违约）。
- `tests/test_content_unit_tag_repository.py`：14 项（attach 幂等 / 多种 detach / list / count / is_attached）。
- `tests/test_tag_service.py`：42 项（TagCategory CRUD / Tag CRUD / 级联删除 / JSON 导入导出 / 预置库加载 / 异常分层）。
- `tests/test_tag_manager_dialog.py`：18 项（构造 / _refresh_tree / 选中逻辑 / 增删改操作 / 异常提示）。

**测试调整**

- `tests/test_domain_models.py`：移除 3 项 rating 专属测试（`test_rating_below_range_raises` / `test_rating_above_range_raises` / `test_rating_none_allowed`）；另 2 项测试移除 rating 断言但保留测试本身。
- `tests/test_content_unit_repository.py`：`test_update_fields` 改用 notes 字段验证更新（rating 不再可用）。
- `tests/test_migrations.py`：新增 v5→v6 迁移测试 6 项（DROP rating / UNIQUE 索引 / 约束生效 / 数据保留 / 幂等 / rating 已不存在时幂等）。
- `tests/test_main_window_content.py`：移除 `assert "评分" in metadata` 断言。

**测试结果**：546 passed → 659 passed（+113），3 skipped。

#### Added

- [src/domain/models.py](src/domain/models.py)：新增 `TagCategory` / `Tag` dataclass；移除 `ContentUnit.rating` 字段及校验。
- [src/infrastructure/repositories/tag_category.py](src/infrastructure/repositories/tag_category.py)：新建 TagCategoryRepository。
- [src/infrastructure/repositories/tag.py](src/infrastructure/repositories/tag.py)：新建 TagRepository。
- [src/infrastructure/repositories/content_unit_tag.py](src/infrastructure/repositories/content_unit_tag.py)：新建 ContentUnitTagRepository。
- [src/application/tag_service.py](src/application/tag_service.py)：新建 TagService。
- [src/application/errors.py](src/application/errors.py)：新增 5 个错误类（TagCategoryNotFoundError / TagNotFoundError / DuplicateTagCategoryNameError / DuplicateTagNameError / InvalidTagJsonError）。
- [src/app/resources/default_tags.json](src/app/resources/default_tags.json)：预置标签库（5 分类 + 19 标签）。
- [src/app/tag_manager_dialog.py](src/app/tag_manager_dialog.py)：新建 TagManagerDialog。
- [src/app/ui_constants.py](src/app/ui_constants.py)：新增 ~40 个标签管理相关常量；移除 METADATA_RATING_LABEL / METADATA_RATING_EMPTY。

#### Changed

- [src/infrastructure/db.py](src/infrastructure/db.py)：`CURRENT_SCHEMA_VERSION` 5 → 6。
- [src/infrastructure/migrations.py](src/infrastructure/migrations.py)：新增 `migrate_v5_to_v6`（DROP rating + UNIQUE 索引），MIGRATIONS 列表新增 `(6, migrate_v5_to_v6)`。
- [src/infrastructure/repositories/content_unit.py](src/infrastructure/repositories/content_unit.py)：create / update / _row_to_model 移除 rating 字段读写。
- [src/application/quick_insert_service.py](src/application/quick_insert_service.py)：移除 `rating=unit.rating` 传递。
- [src/application/__init__.py](src/application/__init__.py)：更新 docstring 列出 TagService。
- [src/app/main_window.py](src/app/main_window.py)：顶部栏新增「标签管理」按钮 + `_on_tag_manager_clicked` 方法；构造新增 `tag_service` 参数；移除 `_update_metadata` 中的 rating 显示；docstring 修正。
- [src/app/main.py](src/app/main.py)：启动序列新增加载预置标签库 + 注入 TagService。
- [docs/architecture.md](docs/architecture.md)：§4.1 / §4.2 / §6.1 / §6.4 / §10 / §11.1 / §12 更新。

## [0.21.0] - 2026-07-18

阶段 4 Task 0：技术债清理（TD-M25 + TD-L20）

Stage 4 功能开发前的前置清理，不新增功能，不修改业务行为。完成 Technical Debt 第四批修复。

**修复 1（TD-M25）：收窄 application 层 `except Exception`**

- **背景**：多处 `except Exception: # noqa: BLE001` 会吞掉 `TypeError` / `AttributeError` / `KeyError` 等编程错误，让 bug 以"日志里一条 traceback + 用户看到功能异常"的形式存在，而不是"快速失败暴露问题"。Stage 4 加标签 / 评分功能时，dataclass 字段拼错导致的 `TypeError` 会被静默吞掉，极难定位。
- **修复**：application 层 service（content_service / scan_service / quick_insert_service / mod_group_service / assembly_service）中的 14 处 `except Exception` 收窄为具体异常类型：
  - 数据库相关：`(RepositoryError, sqlite3.Error)`
  - 文件系统相关：附加 `OSError`
  - 应用层错误（service 间调用）：附加 `ApplicationError` / `FileOperationError`
  - UI 边界 / Qt worker / QAbstractItemModel 边界保留宽捕获（防止进程崩溃，合理的防御性编程）。
- 编程错误（`TypeError` / `AttributeError` 等）现在会在开发期直接冒泡暴露。

**修复 2（TD-L20）：删除旧 `list_by_path_prefix` 方法**

- **背景**：TD-H7（v0.20.1）修复新增 `list_by_path_prefix_normalized`，但旧的 `list_by_path_prefix`（LIKE + ESCAPE，分隔符分歧下 broken）保留为 deprecated。旧方法若被新代码误用会重现分隔符分歧 bug。
- **修复**：确认 v0.20.1 后生产代码已全部迁移到 `list_by_path_prefix_normalized`，无外部调用。删除：
  - `ContentUnitRepository.list_by_path_prefix` 方法（content_unit.py）
  - `TestListByPathPrefix` 测试类（test_content_unit_repository.py，4 项测试）
  - `test_separator_divergence_old_method_returns_empty` 对照测试（test_content_service.py，1 项）
  - test_content_unit_repository.py 中 `from pathlib import Path` 不再需要，已删除。
  - 各 service 的 docstring 中"原 list_by_path_prefix broken"表述更新为"原方法已删除，统一使用 normalized 接口"。

**测试调整**

- `tests/test_quick_insert_service.py`：`_FlakyFolderCacheRepository.create` 的 `RuntimeError` 改为 `RepositoryError`，更准确地模拟生产环境异常，避免 TD-M25 收窄后被错误地视为编程错误冒泡。

**测试结果**：551 passed → 546 passed（-5：TD-L20 移除对照测试 5 项），3 skipped。

#### Changed

- [src/application/content_service.py](src/application/content_service.py)：3 处 `except Exception` 收窄为 `(RepositoryError, sqlite3.Error)`；docstring 中 `list_by_path_prefix` 表述更新为 normalized 接口。
- [src/application/scan_service.py](src/application/scan_service.py)：2 处 `except Exception` 收窄为 `(RepositoryError, sqlite3.Error)`。
- [src/application/quick_insert_service.py](src/application/quick_insert_service.py)：4 处 `except Exception` 收窄为 `(RepositoryError, sqlite3.Error)`；docstring 表述更新。
- [src/application/mod_group_service.py](src/application/mod_group_service.py)：4 处 `except Exception` 收窄为 `(RepositoryError, sqlite3.Error, OSError, ApplicationError, FileOperationError)`。
- [src/application/assembly_service.py](src/application/assembly_service.py)：1 处 `except Exception` 收窄为 `(RepositoryError, sqlite3.Error, OSError)`。
- [src/infrastructure/repositories/content_unit.py](src/infrastructure/repositories/content_unit.py)：删除 `list_by_path_prefix` 方法。
- [tests/test_content_unit_repository.py](tests/test_content_unit_repository.py)：删除 `TestListByPathPrefix` 测试类（4 项），移除未使用的 `from pathlib import Path`。
- [tests/test_content_service.py](tests/test_content_service.py)：删除 `test_separator_divergence_old_method_returns_empty` 对照测试（1 项）。
- [tests/test_quick_insert_service.py](tests/test_quick_insert_service.py)：`_FlakyFolderCacheRepository.create` 异常类型改为 `RepositoryError`。
- [docs/technical-debt.md](docs/technical-debt.md)：标记 TD-M25 / TD-L20 为已修复，新增第四批已修复批次说明，更新处理优先级建议。

## [0.20.1] - 2026-07-17

阶段 3 收尾：Code Review High 级修复 + UI 状态保持修复

Stage 3 正式 Code Review 后的收尾修复，不新增功能。修复两个阻塞 Stage 4 启动的 High 级技术债（TD-H7 / TD-H8），以及用户验收发现的浏览模式 UI 状态保持 bug。完成 Technical Debt 第三批整理。

**修复 1（TD-H7，H1）：路径前缀查询收敛为 normalized 接口**

- **根因更正**：原 TD-H7 描述"LIKE 翻倍导致 Windows 反斜杠路径下 broken"在机制上不准确。经实测验证：原 `list_by_path_prefix` 用 `LIKE ... ESCAPE '\'`，`\\` 在模式中匹配单个字面反斜杠，因此**同分隔符路径下（Windows 均反斜杠）实际能正常工作**。真正的失败场景是**分隔符分歧**——当数据库存储的路径与查询路径分隔符不一致时（如 FileScanner 存正斜杠、service 传反斜杠），LIKE 无法匹配，子路径记录被漏掉。
- **影响**：`ContentService.mark_as_content_unit` 的子项取消逻辑（spec §5.4）在分隔符分歧下静默失效；`list_staging_entries` 批量预查漏掉子项；`list_by_directory` / `list_direct_children` 同样受影响。
- **修复**：新增 `ContentUnitRepository.list_by_path_prefix_normalized`，用 `make_path_key` 归一化后做字符串前缀比较，跨平台一致。`ContentService` 所有调用点（`list_by_directory` / `list_direct_children` / `mark_as_content_unit` / `list_staging_entries`）及 `QuickInsertService._cleanup_stale_content_units` 统一切换到新接口，消除 service 层散落的 `list_all + make_path_key` 绕行方案。原 `list_by_path_prefix` 标记 deprecated 保留（TD-L20 跟踪删除）。

**修复 2（TD-H8，H2）：folder_cache 同步事务一致性**

- **根因**：`QuickInsertService._sync_folder_cache` 和 `ModGroupService.create_mod_group` 步骤 1b 用 `except Exception: logger.exception(...)` 吞掉 folder_cache 同步中的所有异常，但同步内部包含多步写操作（删除旧 → 插入新 → 更新父 mtime）。一旦中间步骤失败、异常被外层吞掉，MainWindow 随后调用 `_commit` 会把"删除旧记录成功 + 插入新记录失败"的部分提交态持久化进数据库，导致目录树出现静默缺节点，且无错误提示给用户。
- **修复**：
  - `QuickInsertService._sync_folder_cache` 不再吞异常，任一步失败立即抛出 `FileOperationError`，由上层（MainWindow `_on_quick_insert_clicked`）捕获后调用 `_rollback` 回滚整个事务。
  - `ModGroupService.create_mod_group` 步骤 1b 同样改为抛出异常，并在抛出前调用 `_try_cleanup_empty_folder` 清理已创建的空文件夹。
  - MainWindow 已有的 `except FileOperationError: self._rollback()` 分支无需修改即可正确处理新行为。

**修复 3：浏览模式双击导航 UI 状态保持**

- **现象**：浏览模式下双击中栏文件夹进入子目录（如 `Stash/MyMod1`），右键标记 `source.7z` 为内容单元后，中栏刷新时"退回"到父目录 `Stash` 的内容显示。
- **根因**：`_on_entry_activated` 双击文件夹导航时只刷新中栏，**没有同步 `tree_view.selectionModel()`**。后续 `_refresh_content_list_for_current_mode`（标记内容单元后调用）、`_refresh_content_list_after_scan`（扫描完成后）、`_refresh_content_for_current_tree_selection`（切回浏览模式时）都依赖 `tree_view.selectionModel()` 推断"当前浏览目录"，因此会误用陈旧的父目录节点。MainWindow 没有显式的"当前浏览目录"状态变量，而是隐式依赖 `tree_view.selectionModel()`——这个隐式契约被双击导航逻辑违反。
- **修复**：
  - `FolderTreeModel` 新增 `find_index_by_path(view, target_path) -> QModelIndex`：按 `real_path` 递归查找节点，过程中触发 `fetchMore` 加载未展开的子节点，用 `make_path_key` 归一化比较（AGENTS 规则 9）。
  - `_on_entry_activated` 双击文件夹时，先调用 `find_index_by_path` 找到目标节点的 QModelIndex；找到则 `setCurrentIndex` 同步目录树选中（触发 `_on_tree_selection_changed` 完成中栏刷新 + 详情区更新）；未找到则记 warning 日志并回退到原手动刷新逻辑（保底处理未扫描根目录的子项等边界场景）。

**Technical Debt 第三批整理（Stage 3 Code Review 2026-07-17 确认暂缓）**

新增 10 项 TD（TD-M21 ~ TD-M27、TD-L18 ~ TD-L20），均含编号、背景、影响范围、推荐修复方案、建议修复阶段。重点项：
- TD-M21（MainWindow God Object 趋势，1570 行 / 76 方法，Stage 4 中期拆分）
- TD-M22（folder_cache 同步辅助逻辑在多 Service 中重复，Stage 5 前收敛）
- TD-M25（多处 except Exception 吞掉编程错误，Stage 4 中期收窄）
- TD-L20（旧 `list_by_path_prefix` deprecated 保留待删除，Stage 4 中期）

截至 v0.20.1，**无阻塞 Stage 4 启动的 High 级别技术债**。

#### Changed

- [src/infrastructure/repositories/content_unit.py](src/infrastructure/repositories/content_unit.py)：新增 `list_by_path_prefix_normalized` 方法；原 `list_by_path_prefix` 标记 deprecated。
- [src/application/content_service.py](src/application/content_service.py)：4 处调用点（`list_by_directory` / `list_direct_children` / `mark_as_content_unit` 子项取消 / `list_staging_entries` 批量预查）统一切换到 `list_by_path_prefix_normalized`。
- [src/application/quick_insert_service.py](src/application/quick_insert_service.py)：`_cleanup_stale_content_units` 改用新接口（移除 service 层散落的 `list_all + make_path_key` 绕行方案）；`_sync_folder_cache` 不再吞异常；`quick_insert` 调用 `_sync_folder_cache` 处用 try/except 包裹，失败时包装为 `FileOperationError` 抛出。
- [src/application/mod_group_service.py](src/application/mod_group_service.py)：`create_mod_group` 步骤 1b folder_cache 写入失败时改为抛 `FileOperationError`，并在抛出前调用 `_try_cleanup_empty_folder` 清理已创建的空文件夹。
- [src/app/folder_tree_model.py](src/app/folder_tree_model.py)：新增 `find_index_by_path` / `_find_index_recursive` 方法。
- [src/app/main_window.py](src/app/main_window.py)：`_on_entry_activated` 双击文件夹导航时同步目录树选中节点。

#### Tests

- 测试数量变化：541 passed → 551 passed（+10）。
- [tests/test_content_service.py](tests/test_content_service.py) 新增 `TestListByPathPrefixNormalized` 共 5 项：分隔符分歧下返回子项 / 对照测试（原方法在分隔符分歧下返回空）/ 同分隔符返回子项 / 兄弟目录排除 / `mark_as_content_unit` 子项取消分隔符分歧场景。
- [tests/test_quick_insert_service.py](tests/test_quick_insert_service.py) 新增 2 项 H2 失败场景测试：`test_quick_insert_sync_folder_cache_failure_rolls_back_transaction` / `test_mod_group_create_folder_cache_failure_rolls_back`，用 `_FlakyFolderCacheRepository` 模拟插入失败，验证事务回滚 + 数据库一致性。
- [tests/test_main_window_content.py](tests/test_main_window_content.py) 新增 3 项 UI 状态保持测试：`test_double_click_folder_syncs_tree_selection` / `test_mark_content_unit_after_double_click_keeps_current_dir`（核心回归）/ `test_find_index_by_path_returns_invalid_for_unknown_path`。

#### Docs

- [docs/technical-debt.md](docs/technical-debt.md)：标记 TD-H7 / TD-H8 为已修复（v0.20.1）；新增第三批 TD（TD-M21 ~ TD-M27、TD-L18 ~ TD-L20）；重写"处理优先级建议"章节为 6 档优先级清单。

## [0.20.0] - 2026-07-17

阶段 3 Task 5：快速插入

实现整理模式下的「快速插入」功能：将当前装配面板绑定的 Mod 组文件夹整体移动到目录树中选中的目标分类目录。完成阶段 3 全部 Task。

**设计决策（2026-07-17 用户确认）：**
- **取消拖拽方案**：原 roadmap 中"拖拽到目录树节点触发文件移动"和"目录树内拖拽重新分类"取消，与 Task 4 拖拽取消决策一致。仅保留「快速插入」按钮入口。
- **冲突处理范围**：Task 5 保持现有"冲突即拒绝"模式（ConflictError + 弹窗提示），覆盖/跳过/重命名选项留待阶段 5 通用冲突处理统一实现（AGENTS 规则 2：不覆盖）。
- **跨盘移动**：当前阶段直接拒绝并提示，不执行跨盘 move（Windows 跨盘 move 退化为 copy+delete，风险较高）。

**目录树刷新统一机制（2026-07-17 用户验收后修复）：**
- 首轮验收发现快速插入后目标目录不刷新（需重新扫描才显示新节点）。
- 根因：QuickInsertService 只清理旧路径 folder_cache，未在目标目录下插入新节点。
- 修复：QuickInsertService._sync_folder_cache 现在执行完整同步——删除旧节点 + 插入新节点（parent_id 关联目标目录）+ 更新目标目录 mtime，与 ModGroupService.create_mod_group 步骤 1b 模式一致。
- 统一机制确认：所有涉及真实文件夹移动/创建/删除的服务（ModGroupService / QuickInsertService）负责完整同步 folder_cache；UI 层只需调用一次 `_refresh_tree()` 即可立即刷新目录树，无需重新扫描。AssemblyService.add_file / remove_file 移动的是文件（非文件夹），folder_cache 只记录目录，因此只需更新 mtime（已正确实现）。

**UNIQUE 约束冲突 + database is locked 根因修复（2026-07-17 第二轮验收后）：**
- 第二轮验收发现两个阻塞问题：
  1. 快速插入报 `UNIQUE constraint failed: content_unit.path`，文件已移动但数据库更新失败，文件系统与数据库状态不一致。
  2. 快速插入失败后扫描报 `database is locked`，事务未正确释放。
- **根因分析**（非目录树刷新逻辑直接引入，但被其暴露）：
  1. **`list_by_path_prefix` 的 SQL LIKE 转义在 Windows 下 broken**：`os.sep = "\\"`，`replace("\\", "\\\\")` 让每个反斜杠翻倍，LIKE 模式期望路径中两个连续反斜杠，无法匹配子路径。原测试用 POSIX 路径（`/mods/armor`）掩盖了此 bug。
  2. **操作顺序错误 + 事务回滚副作用**：原顺序 `move → cleanup → update`，若 `update` 失败，`main_window` 调用 `rollback` 会回滚 `cleanup` 的 delete，旧记录"复活"，下次重试 `update` 仍 UNIQUE 冲突 → 死循环。
  3. **事务边界设计缺失**：`QuickInsertService` 没有事务管理，失败后事务挂起，SQLite 持有写锁。
- **修复方案**：
  1. **重写 `_cleanup_stale_content_units`**：用 `list_all + make_path_key` 归一化比较，不依赖 SQL LIKE（符合 AGENTS 规则 9）。清理范围：dst_folder 自身 + 其所有子路径。
  2. **调整 `quick_insert` 顺序**：`cleanup → move → update → sync`。cleanup 在 move 之前，此时文件系统状态干净，若 cleanup 失败可安全 rollback；move 成功后，update 时数据库已无 UNIQUE 冲突记录。
  3. **保留 `main_window` 的 rollback**：作为事务边界最后手段，释放写锁。若 update 失败（非 UNIQUE 原因），文件已移动但数据库回滚，状态不一致但不会死循环（下次重试 move 会因源不存在而失败，提示用户手动修复）。
- **新增测试**：
  - `test_quick_insert_cleans_stale_content_unit_with_path_normalization`：验证尾随分隔符差异（make_path_key 归一化后相同）的旧记录也能被清理。
  - `test_quick_insert_cleanup_before_move_allows_safe_rollback`：验证 move 失败后 rollback 不死循环，第二次 quick_insert 可正常执行。
- 测试数量变化：537 passed → 541 passed（+4：QuickInsertService 新增 4 项根因修复测试）。

#### Added

- **QuickInsertService**：[src/application/quick_insert_service.py](src/application/quick_insert_service.py) 新增快速插入服务。`quick_insert(unit_id, target_dir)` 调用 `FileOperationService.move` 执行移动（含跨盘/子目录/冲突检测），更新 `ContentUnit.path`，清理旧路径 `folder_cache` 记录。
- **MainWindow 快速插入按钮**：[src/app/main_window.py](src/app/main_window.py) 顶部模式栏右侧新增「快速插入」按钮。
  - 可用条件：整理模式 + 装配面板已绑定 Mod 组 + 目录树选中目标目录 + 目标与源不同 + 目标不是源子目录。
  - 点击后弹出确认对话框（显示源路径 → 目标路径），用户确认后执行移动。
  - 成功后 UI 刷新：解绑装配面板 + 刷新目录树 + 刷新暂存区列表 + 状态栏提示。
  - 错误处理：ConflictError / CrossDriveError / SelfSubdirectoryError 各自转为用户可读提示。
- **UI 文案常量**：[src/app/ui_constants.py](src/app/ui_constants.py) 新增快速插入相关常量（按钮文本 / tooltip / 确认对话框 / 状态栏提示 / 错误提示）。
- **依赖注入**：[src/app/main.py](src/app/main.py) 注入 QuickInsertService 到 MainWindow。

#### Tests

- 测试数量变化：519 passed → 541 passed（+22：QuickInsertService 12 项单元测试 + MainWindow 10 项集成测试）。
- [tests/test_quick_insert_service.py](tests/test_quick_insert_service.py) 新增 12 项单元测试：快速插入成功 / operation_history 记录 / folder_cache 完整同步 / 冲突 / 子目录阻止 / 跨盘 / ContentUnit 不存在 / 中文路径 / 旧记录清理（目标路径自身）/ 旧记录清理（子路径）/ 路径归一化清理 / cleanup-before-move 安全回滚。
- [tests/test_main_window_quick_insert.py](tests/test_main_window_quick_insert.py) 新增 10 项集成测试：按钮显隐（浏览/整理模式）/ 按钮禁用（无绑定/无目标/目标为源父目录）/ 按钮启用（绑定 + 目标）/ 快速插入成功 + UI 刷新 / 取消确认不移动 / 冲突提示 / 子目录阻止提示 / 中文路径。
- [tests/test_main_window_assembly.py](tests/test_main_window_assembly.py) fixture 注入 QuickInsertService（不影响现有测试）。

#### Docs

- [docs/spec.md](docs/spec.md) §6.1 移动安全规则更新（冲突/跨盘当前阶段策略）；§7.3 整理模式新增「快速插入」按钮详细说明（可用条件 / 交互 / 底层 / UI 刷新 / 取消拖拽方案）。
- [docs/roadmap.md](docs/roadmap.md) Task 5 标记为 ✅，验收项全部勾选，新增设计决策记录。

## [0.19.1] - 2026-07-17

阶段 3 Task 4：装配面板交互调整

用户手动验收后提出两项设计调整：取消拖拽加入装配方案、Mod 组切换改为双击触发。仅修改交互方式，底层业务逻辑（AssemblyService）不变。

**设计决策（2026-07-17 用户确认）：**
- **取消拖拽加入装配**：Qt ListView 默认拖拽反馈不理想，改为整理模式下中栏文件列表右键菜单「加入装配」。条件：整理模式 + 单选 + 文件（非目录）+ 装配面板已绑定 Mod 组。点击后调用原有 `_on_assembly_add_file`，文件真实移动、列表刷新、operation_history 记录、状态栏提示均保持不变。
- **Mod 组切换改为双击**：原单击中栏 Mod 组文件夹立即切换装配面板容易误触。改为单击仅选中 + 显示元数据（不切换绑定），双击才绑定装配面板到该 Mod 组。目录树行为不变。

#### Changed

- **AssemblyPanel**：[src/app/assembly_panel.py](src/app/assembly_panel.py) 移除全部拖拽相关代码（`create_drag_mime_data` / `DragSourceTableView` / `dragEnterEvent` / `dragMoveEvent` / `dropEvent` / `on_file_added` 回调参数 / `QMimeData` 导入）；文件列表 `setAcceptDrops(False)` + `setDragDropMode(NoDragDrop)`；空提示文案更新为引导用户右键「加入装配」或双击选中 Mod 组。
- **MainWindow**：[src/app/main_window.py](src/app/main_window.py)
  - `_content_view` 从 `DragSourceTableView` 改回 `QTableView`，`setDragDropMode(NoDragDrop)`（所有模式一致）。
  - AssemblyPanel 构造移除 `on_file_added` 回调。
  - `_on_content_context_menu` 新增「加入装配」菜单项（条件：整理模式 + 单选 + 文件非目录 + 装配面板已绑定 Mod 组）。
  - `_on_entry_activated` 新增整理模式双击 Mod 组文件夹 → `_bind_assembly_panel` 分支。
  - `_on_content_selection_changed` 移除装配面板绑定逻辑（单击不再切换绑定）。
  - `_on_mode_changed` 移除拖拽模式切换（不再设置 `DragOnly` / `NoDragDrop`）。
  - 移除测试接口 `content_view_drag_enabled()`。
- **UI 文案常量**：[src/app/ui_constants.py](src/app/ui_constants.py) 新增 `MENU_ADD_TO_ASSEMBLY = "加入装配"`；`ASSEMBLY_PANEL_EMPTY` / `ASSEMBLY_PANEL_NO_FILES` 文案更新；移除 `ASSEMBLY_DRAG_MIME_TYPE`。

#### Tests

- 测试数量变化：523 passed → 519 passed（-7 拖拽测试 +4 新交互测试 = -3 净变化；3 skipped 不变）。
- [tests/test_assembly_panel.py](tests/test_assembly_panel.py) 移除 5 项拖拽测试（`test_create_drag_mime_data` / `test_create_drag_mime_data_chinese_path` / `test_panel_drop_event_invokes_callback` / `test_panel_drop_event_no_binding_ignored` / `test_drag_source_table_view_instantiation`）。
- [tests/test_main_window_assembly.py](tests/test_main_window_assembly.py) 移除 2 项拖拽测试（`test_assembly_panel_drag_disabled_in_browse_mode` / `test_assembly_panel_drag_enabled_in_organize_mode`）；新增 4 项：双击 Mod 组绑定 / 单击 Mod 组不绑定 / 右键菜单「加入装配」移动文件 / 未绑定 Mod 组时菜单不显示「加入装配」。新增 `_patch_qmenu` 辅助函数（在模块命名空间替换 `QMenu` 类，因 PySide6 `QMenu.exec` 为 C++ 实现无法通过 `monkeypatch.setattr(QMenu, "exec", ...)` 在实例方法层级替换）。

#### Docs

- [docs/spec.md](docs/spec.md) §5.2 整理模式流程图：拖入 → 右键「加入装配」；§7.3 整理模式新增交互方式（单击不切换 / 双击绑定）；§7.4 装配面板：拖入 → 右键菜单；§7.5 右键菜单表：暂存区文件新增「加入装配」。
- [docs/roadmap.md](docs/roadmap.md) Task 4 验收项更新：拖拽项替换为右键菜单项 + 新增双击/单击切换验收项。

## [0.19.0] - 2026-07-16

阶段 3 Task 4：装配面板

新增装配面板（AssemblyPanel）+ 装配服务（AssemblyService），实现整理模式下从暂存区拖入附加文件到 Mod 组、移除已加入文件回暂存区根目录、右键图片手动重命名为 Mod 组同名（不破坏用户已有命名）。schema_version 维持 5。

**设计决策（2026-07-16 用户确认）：**
- **不自动重命名图片**：自动整理阶段不修改任何文件名（`add_file` 保留原文件名），避免破坏用户已整理好的命名。仅提供手动「重命名为与 Mod 组同名」操作。
- **移除文件统一移回暂存区根目录**：不保留原子目录结构（spec §7.4）。
- **装配面板绑定当前选中 Mod 组**：整理模式下切换不同 Mod 组时同步刷新装配面板内容。
- **浏览模式不显示装配面板**：装配功能仅存在于整理模式。
- **手动重命名规则**：单张 `{Mod组名}.{扩展名}`；多张 `{Mod组名}_2`、`{Mod组名}_3`……后缀；命名冲突走现有 `ConflictError` 流程（弹窗提示，不覆盖，AGENTS 规则 2）。

#### Added

- **AssemblyService**：[src/application/assembly_service.py](src/application/assembly_service.py) 新建，装配面板业务逻辑。
  - `list_mod_group_files(unit_id) -> list[FileEntry]`：读取 Mod 组文件夹内容（Path.iterdir + stat），不关联 content_unit。
  - `add_file(unit_id, src_path) -> FileEntry`：从暂存区拖入文件到 Mod 组文件夹（真实移动，保留原文件名）；目标冲突抛 `ConflictError`。
  - `remove_file(unit_id, filename, staging_path) -> Path`：从 Mod 组移除文件，统一移回暂存区根目录（不保留原子目录结构）；冲突抛 `ConflictError`。
  - `rename_as_cover(unit_id, image_path) -> Path`：手动重命名图片为 Mod 组同名。单张 `{mod_name}.ext`；多张 `_2`、`_3` 后缀（已在文件夹内的同名图片自动跳过）；image_path 必须在 Mod 组文件夹内且为支持的图片格式（spec §9 扩展名集合），否则抛 `InvalidContentUnitPathError`。
  - `_sync_folder_mtime(folder_path)`：装配操作后同步 `folder_cache.last_scanned_mtime`（与 ModGroupService 一致，避免下次增量扫描重复处理）；写入失败不阻塞主流程。
- **AssemblyPanel**：[src/app/assembly_panel.py](src/app/assembly_panel.py) 新建，QWidget 装配面板 UI 组件。
  - `AssemblyListModel`：QAbstractListModel 单列实现，支持 `DisplayRole`/`ToolTipRole`/`UserRole`/`DecorationRole`。
  - `AssemblyPanel`：显示 Mod 组文件列表 + 移除按钮 + 关闭按钮；支持拖拽接收（mime type `application/x-scw-assembly-file`）；右键菜单提供「重命名为与 Mod 组同名」（仅图片）、「移除」、「复制路径」。
  - `bind_mod_group(unit, staging_path)` / `refresh_current()` / `current_unit()` / `current_unit_id()`：绑定/刷新/查询当前 Mod 组。
  - `create_drag_mime_data(src_path) -> QMimeData`：构造拖拽数据（携带源文件路径 UTF-8 字符串）。
  - `DragSourceTableView`：QTableView 子类，重写 `startDrag` 支持拖拽文件到装配面板。
- **MainWindow 集成**：[src/app/main_window.py](src/app/main_window.py) 中栏改为 `QSplitter(Vertical)` 上下分割（文件列表 + 装配面板）；`_content_view` 从 `QTableView` 改为 `DragSourceTableView`。
  - `__init__` 新增 `assembly_service: AssemblyService | None = None` 注入参数。
  - 新增 4 个回调方法：`_on_assembly_add_file` / `_on_assembly_remove_file` / `_on_assembly_rename_cover` / `_on_assembly_closed`。
  - 新增 2 个绑定辅助方法：`_bind_assembly_panel` / `_maybe_bind_assembly_panel_for_tree_node`。
  - `_on_create_mod_group` 完成后自动绑定装配面板；`_on_content_selection_changed` / `_on_tree_selection_changed` 在整理模式下选中 Mod 组文件夹时同步绑定；`_on_mode_changed` 切换拖拽模式（浏览 `NoDragDrop` / 整理 `DragOnly`）+ 装配面板显隐。
  - 测试接口：`assembly_panel_visible()`（使用 `not isHidden()` 而非 `isVisible()`，避免测试环境主窗口未 show() 时始终返回 False）/ `assembly_panel_current_unit_id()` / `assembly_panel_entry_count()` / `content_view_drag_enabled()`。
- **UI 文案常量**：[src/app/ui_constants.py](src/app/ui_constants.py) 新增装配面板相关文案 18 项（`ASSEMBLY_PANEL_TITLE` / `ASSEMBLY_PANEL_HINT` / `ASSEMBLY_PANEL_EMPTY` / `ASSEMBLY_PANEL_NO_FILES` / `ASSEMBLY_PANEL_REMOVE_BUTTON` / `ASSEMBLY_PANEL_CLOSE_BUTTON` / `ASSEMBLY_MENU_RENAME_COVER` / `ASSEMBLY_MENU_REMOVE` / `ASSEMBLY_MENU_COPY_PATH` / `ASSEMBLY_ADD_FILE_OK` / `ASSEMBLY_ADD_FILE_FAILED` / `ASSEMBLY_REMOVE_FILE_OK` / `ASSEMBLY_REMOVE_FILE_FAILED` / `ASSEMBLY_RENAME_COVER_OK` / `ASSEMBLY_RENAME_COVER_FAILED` / `ASSEMBLY_NOT_IMAGE_HINT` / `ASSEMBLY_NO_SELECTION` / `ASSEMBLY_DRAG_MIME_TYPE`）。

#### Changed

- **main.py 依赖注入**：[src/app/main.py](src/app/main.py) 构造 `AssemblyService`（共用 `FileOperationService` + 新建 `ContentUnitRepository` + `FolderCacheRepository`），传入 MainWindow。
- **MainWindow 中栏布局**：[src/app/main_window.py](src/app/main_window.py) 中栏从单一 `QGroupBox` 改为 `QSplitter(Vertical)` 上下分割：上半部分文件列表，下半部分装配面板（默认隐藏，整理模式 + 选中 Mod 组时显示）。初始拉伸比例 3:1。
- **MainWindow 拖拽模式**：`_content_view` 默认 `NoDragDrop`（浏览模式）；整理模式切换为 `DragOnly`，支持拖拽文件到装配面板。

#### Tests

- 测试数量变化：439 passed → 523 passed（+84 新测试；3 skipped 均为 Windows 符号链接权限不足，与代码无关）。
- [tests/test_assembly_service.py](tests/test_assembly_service.py)（新文件，23 项）——`list_mod_group_files`（空/非空/中文/不存在/非目录）；`add_file`（成功/写历史/同步 mtime/目标冲突/源不存在/中文路径/保留原名）；`remove_file`（成功/移回暂存区根目录/写历史/目标冲突/源不存在）；`rename_as_cover`（单张/多张 `_2`、`_3`/幂等返回/非图片拒绝/不在 Mod 组内拒绝/冲突）；`_sync_folder_mtime`（folder_cache_repo=None 跳过/写入失败不阻塞）。
- [tests/test_assembly_panel.py](tests/test_assembly_panel.py)（新文件，20 项）——`AssemblyListModel`（初始空/refresh/data roles/清空旧条目）；`AssemblyPanel`（初始状态/bind/refresh/current_unit/无选中移除禁用）；拖拽 mime 数据构造与解析；`DragSourceTableView` 实例化；右键菜单回调路径；回调注入路径。
- [tests/test_main_window_assembly.py](tests/test_main_window_assembly.py)（新文件，19 项）——装配面板显隐（浏览隐藏/浏览拖拽禁用/整理拖拽启用/整理无 Mod 组隐藏/切回浏览隐藏）；创建 Mod 组后自动绑定 + 切换 Mod 组刷新；`add_file` 回调（成功 + 冲突）；`remove_file` 回调（成功 + 冲突）；`rename_as_cover` 回调（单张/多张 `_2`/非图片拒绝）；`closed` 回调；选中 Mod 组绑定（中栏 + 目录树）；浏览模式不绑定；中文 Mod 组。

#### Docs

- [docs/spec.md](docs/spec.md) §7.4：装配面板描述与实现一致——明确「不自动重命名图片」原则；手动重命名冲突处理改为「弹窗提示冲突，不覆盖」（原描述「覆盖/跳过/重命名」与 AGENTS 规则 2 冲突，覆盖/跳过/重命名选项留待阶段 5 通用冲突处理统一实现）。
- [docs/roadmap.md](docs/roadmap.md) Task 4 验收项全部 ✅。

## [0.18.2] - 2026-07-16

修复（阶段 3 Task 3 验收修复）

- **目录树刷新逻辑修复**：
  - **创建 Mod 组后新文件夹不可见**：`ModGroupService._resolve_parent_id_by_path` 改用 `make_path_key` 归一化路径比较（与 `ScanService._resolve_parent_id` 一致），避免 `staging_path` 字符串与 `folder_cache.path` 存储字符串的大小写/分隔符差异导致 `parent_id=None`（孤儿节点），新文件夹无法在目录树显示。
  - **创建 Mod 组后 folder_cache 未写入（生产环境）**：`main.py` 构造 `ModGroupService` 时未传入 `FolderCacheRepository`，导致 `self._folder_cache_repo is None`，创建 Mod 组时跳过了 folder_cache 写入。修复后 `main.py` 注入 `FolderCacheRepository`，创建 Mod 组后目录树立即显示新文件夹（无需重新扫描）。
  - **已删除目录残留清理**：`FileScanner.ScanResult` 新增 `all_visited_dirs` 字段（扫描过程中实际访问到的所有目录，含增量扫描跳过的目录）；`ScanService._cleanup_deleted_folders` 对比 `all_visited_dirs` 集合与 `folder_cache` 记录，清理已删除目录的残留记录。待删除记录按路径深度降序排序（子目录先于父目录），避免 `folder_cache.parent_id` 外键约束导致删除失败。只清理当前扫描 root 前缀下的记录，不误删其他 root。
- **双击内容单元文件夹进入目录**：`MainWindow._on_entry_activated` 判断顺序调整——浏览模式下双击文件夹优先进入该目录（无论是否内容单元），先于 `content_unit` 判断。文件夹的元数据通过单击选中查看（`_on_content_selection_changed`）。文件类型内容单元（压缩包）双击仍显示元数据。
- **扫描后保持目录树展开/选中状态**：`FolderTreeModel` 新增 `save_expanded_paths` / `save_selected_path` / `restore_expanded_paths` 方法；`MainWindow._refresh_tree` 刷新前保存展开节点 `real_path` 集合与选中节点路径，刷新后递归 `fetchMore` + `setExpanded` + `setCurrentIndex` 恢复。避免每次扫描/创建 Mod 组后目录树全部折叠。

## [0.18.1] - 2026-07-15

修复（阶段 3 Task 3 验收修复）

- **Nexus 命名规则适配**：`extract_mod_name` 新增 Nexus Mods 下载文件名识别（`Mod名称-数字ID-版本号-时间戳`），如 `Alt-Tab Fix-148466-1-0-0-1745430887.zip` → `Alt-Tab Fix`。非 Nexus 命名回退到通用版本号剔除。
- **目录树刷新**：`ModGroupService` 新增可选依赖 `FolderCacheRepository`，创建 Mod 组文件夹后同步写入 `folder_cache` 表，目录树立即可见新文件夹。
- **整理模式列表优化**：`list_staging_entries` 过滤已标记为内容单元的文件夹的子项（spec §7.3 暂存区列表显示"零散文件"，已收纳的子文件不显示）。
- **浏览模式双击文件夹进入目录**：双击非内容单元文件夹 → 中栏切换到该目录内容（等价于目录树切换）。
- **单击显示元数据**：单击选中内容单元 → 右侧立即显示元数据（详情面板交互方式，符合资源管理器/IDE/DAM 软件习惯）。

## [0.18.0] - 2026-07-14

阶段 3 Task 3：创建 Mod 组 + 手动修正。新增 `FileOperationService`（简化版 `new_folder` + `move`）、`OperationHistoryRepository`、`ModGroupService`，扩展 `ContentService` 写方法（`create_content_unit` / `mark_as_content_unit` / `unmark_content_unit`）。MainWindow 文件列表右键菜单支持「创建 Mod 组」「标记/取消标记」「批量标记」；`_content_view` 从 `SingleSelection` 改为 `ExtendedSelection` 支持多选。schema_version 维持 5。

### Added

- **OperationHistoryRepository**：[src/infrastructure/repositories/operation_history.py](src/infrastructure/repositories/operation_history.py) 新建，CRUD 模式参照 `staging_area.py`。
  - `create(history) -> OperationHistory`：`can_undo` 字段做 `bool ↔ int` 转换。
  - `get_by_id` / `list_all`（按 created_at 升序）/ `delete`。
  - 写操作不自提交，由 application 层控制事务边界。
- **FileOperationService（简化版）**：[src/infrastructure/file_operation_service.py](src/infrastructure/file_operation_service.py) 新建，Task 3 范围内最小实现 `new_folder` + `move`（`rename` / `delete` / `undo` 留待阶段 5）。
  - `new_folder(folder_path) -> OperationHistory`：父目录存在性检查 + 不覆盖（`ConflictError`）+ 写 `operation_history`（type=`new_folder`，source=父目录，target=新文件夹）。
  - `move(src, dst) -> OperationHistory`：源/目标存在性检查 + 不覆盖 + 跨盘检测（`CrossDriveError`）+ 自目录检测（`SelfSubdirectoryError`）+ `shutil.move` 保留元数据 + 写 `operation_history`（type=`move`）。
  - 写历史在文件操作成功后；失败不写历史。不自提交。
  - 注入 `now_provider` / `uuid_provider` 便于测试。
- **ModGroupService**：[src/application/mod_group_service.py](src/application/mod_group_service.py) 新建，业务编排（不破坏 `StagingService` 纯标记定位）。
  - `extract_mod_name(filename) -> str`：正则剔除末尾版本号（`\s*v?\d+(\.\d+)+( SE|LE|SSE|AE)?`），不剔除下划线分隔。示例：`BDOR Black Knight 1.0.7z` → `BDOR Black Knight`；`SkyUI 5.1 SE.zip` → `SkyUI`；`寒霜之心 1.0.7z` → `寒霜之心`。
  - `create_mod_group(source_file, staging_path, name=None) -> ContentUnit`：校验源在暂存区下 → `new_folder` → `move`（失败回滚空文件夹）→ `create_content_unit`（status=`unorganized`）。
- **ContentService 写方法**：[src/application/content_service.py](src/application/content_service.py) 模块从「只查询」扩展为「查询 + 元数据写入」（不触发文件操作）。
  - `create_content_unit(path, title=None, content_type="mod", status="unorganized") -> ContentUnit`。
  - `mark_as_content_unit(path) -> ContentUnit`：spec §5.4 关键规则——标记文件夹时取消子项标记（`list_by_path_prefix` 找子项，逐个 `delete`）；已标记返回现有。
  - `unmark_content_unit(unit_id) -> None`：删除 ContentUnit，**不删真实文件**。
  - `get_by_path(path) -> ContentUnit | None`：薄委托到 repository。
  - 注入 `now_provider` / `uuid_provider` 便于测试。
- **Application 层错误类型**：[src/application/errors.py](src/application/errors.py) 新增 7 个：
  - `FileOperationError`（基类）/ `ConflictError` / `CrossDriveError` / `SelfSubdirectoryError` / `SourceNotFoundError`
  - `ContentUnitNotFoundError` / `InvalidContentUnitPathError`
  - `ModGroupSourceNotInStagingError` / `InvalidModGroupNameError`
- **UI 文案常量**：[src/app/ui_constants.py](src/app/ui_constants.py) 新增 18 项：
  - 菜单项：`MENU_CREATE_MOD_GROUP` / `MENU_MARK_CONTENT_UNIT` / `MENU_UNMARK_CONTENT_UNIT` / `MENU_BATCH_MARK_CONTENT_UNIT`
  - 对话框：`CREATE_MOD_GROUP_DIALOG_TITLE` / `_LABEL` / `_OPTION_PURE` / `_OPTION_FULL` / `_DEFAULT_OK` / `_FAILED`
  - 状态提示：`MARK_CONTENT_UNIT_OK` / `UNMARK_CONTENT_UNIT_OK` / `BATCH_MARK_CONTENT_UNIT_OK` + 对应 `_FAILED`

### Changed

- **ContentUnitRepository.delete 级联清理**：[src/infrastructure/repositories/content_unit.py](src/infrastructure/repositories/content_unit.py) `delete` 方法在事务内先 `DELETE FROM content_unit_tag WHERE content_unit_id = ?`，再 `DELETE FROM content_unit WHERE id = ?`，避免 FK 违约（schema 未声明 `ON DELETE CASCADE`）。`thumbnail_cache` 留待阶段 4 Task 5 处理。
- **MainWindow 文件列表右键菜单**：[src/app/main_window.py](src/app/main_window.py)
  - `_content_view` 从 `SingleSelection` 改为 `ExtendedSelection` 支持多选。
  - `_on_content_context_menu` 重构：根据选中条目数 + 模式 + `entry.content_unit` 动态构造菜单：
    - **创建 Mod 组**：仅整理模式 + 单选文件 + 注入了 `ModGroupService` 时显示。
    - **标记为内容单元 / 取消标记**：单选时根据 `entry.content_unit is None` 切换。
    - **把每个文件标记为内容单元**：多选时显示（仅未标记项）。
    - **复制路径**：始终显示。
  - 新增 6 个方法：`_on_create_mod_group` / `_show_create_mod_group_dialog`（`QDialog` + `QComboBox` 可编辑，预填纯 Mod 名 / 完整原名两种选项）/ `_on_mark_content_unit` / `_on_unmark_content_unit` / `_on_batch_mark_content_unit` / `_refresh_content_list_for_current_mode`。
  - `__init__` 新增 `mod_group_service: ModGroupService | None = None` 注入参数。
- **main.py 依赖注入**：[src/app/main.py](src/app/main.py) 构造 `OperationHistoryRepository` + `FileOperationService` + `ModGroupService`，传入 MainWindow。

### Tests

- 测试数量变化：383 passed → 439 passed（+56 新测试；3 skipped 均为 Windows 符号链接权限不足，与代码无关）。
- [tests/test_operation_history_repository.py](tests/test_operation_history_repository.py)（新文件，约 8 项）——CRUD / 4 种 operation_type / target_path 可空 / can_undo bool↔int / 不自提交。
- [tests/test_file_operation_service.py](tests/test_file_operation_service.py)（新文件，17 项）——new_folder 创建/父目录不存在/目标已存在/写历史/中文路径；move 移动文件/移动目录/源不存在/目标已存在/自目录检测/目标父目录不存在/保留内容/写历史/中文路径/不影响无关文件；跨盘模拟（monkeypatch Path.stat）；不自提交。
- [tests/test_mod_group_service.py](tests/test_mod_group_service.py)（新文件，18 项）——文件名提取 8 种格式（含中文、多扩展名）；create_mod_group 完整流程 / 写 2 条历史 / 同名冲突 / move 失败回滚空文件夹 / 中文名 / 源不在暂存区 / 空名称 / 仅空白名称 / 显式名称覆盖提取 / 源文件内容保留。
- [tests/test_content_service.py](tests/test_content_service.py)：扩展 12 项——`TestCreateContentUnit`（基本创建/默认 status/重复 path 抛异常/中文路径）、`TestMarkAsContentUnit`（标记文件/标记文件夹取消子项/已标记返回现有/路径不存在）、`TestUnmarkContentUnit`（删除记录/级联清理 content_unit_tag/不删真实文件/不存在抛异常）。
- [tests/test_main_window_context_menu_task3.py](tests/test_main_window_context_menu_task3.py)（新文件，9 项）——ExtendedSelection 启用 / 标记后列表刷新 / 取消标记后列表刷新 / 创建 Mod 组完整流程（文件夹创建 + 文件移动 + ContentUnit 创建 + 2 条历史）/ 对话框取消不操作 / 同名冲突弹错误 / 批量标记 2 个文件 / 中文文件名 Mod 组。

### 安全限制

- 文件操作通过 `FileOperationService`，UI 不直接调用 `shutil` / `Path.rename`（AGENTS 规则 3）。
- 不覆盖已有文件/目录（`ConflictError`，AGENTS 规则 2）。
- 跨盘移动检测（`CrossDriveError`）+ 自目录移动检测（`SelfSubdirectoryError`）。
- `unmark_content_unit` 仅删除 DB 记录，不删真实文件。
- `mark_as_content_unit` 标记文件夹时取消子项标记（spec §5.4），避免父子同时标记。
- 创建 Mod 组失败回滚：`move` 失败时清理已创建的空文件夹（仅当为空时）。
- 操作历史写入在文件操作成功后；失败不写历史。不自提交。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 64 files already formatted
- `python -m pytest` → 439 passed, 3 skipped

### Documentation

- 更新 [docs/roadmap.md](docs/roadmap.md)：阶段 3 Task 3 验收项全部 `[ ]` → `[x]`，标题加 ✅ 标记。

## [0.17.0] - 2026-07-14

阶段 3 Task 2：暂存区文件列表。整理模式中栏改为加载暂存区 `[S]` 节点的递归文件列表（含子目录），FileListModel 从单列 `QAbstractListModel` 重构为 4 列 `QAbstractTableModel` 支持列头排序。schema_version 维持 5。仅只读访问文件系统，不修改用户文件。

### Added

- **暂存区递归列表服务**：[src/application/content_service.py](src/application/content_service.py) 新增 `list_staging_entries(staging_path) -> list[FileEntry]`。
  - 使用 `Path.rglob("*")` 递归遍历暂存区下所有文件和文件夹（与 `list_directory_entries` 的单层 `Path.iterdir` 区分）。
  - 批量预查 content_unit：一次 `list_by_path_prefix` 取回所有相关 unit，构建 `path_key → ContentUnit` 映射，避免 N 次 DB 查询。
  - 路径不存在/非目录返回空列表；递归读取失败记日志返回空；`OSError` 不崩溃。
  - 跳过符号链接（避免循环）。
  - 排序：文件夹在前，名称不区分大小写升序（与 `list_directory_entries` 一致，作为初始顺序；用户列头排序在 UI 层应用）。
  - 辅助方法 `_build_entry_with_map(child, unit_map)` 提取条目构造逻辑，与 `list_directory_entries` 共享结构。
- **UI 文案常量**：[src/app/ui_constants.py](src/app/ui_constants.py) 新增：
  - `FILE_LIST_COLUMN_HEADERS = ("名称", "类型", "大小", "修改日期")`：4 列表头。
  - `COL_TYPE_FOLDER = "文件夹"` / `COL_TYPE_FILE = "文件"`：类型列对无扩展名文件的回退文案。
  - `STAGING_LIST_NO_STAGING_SELECTED = "整理模式：请在目录树中选中一个暂存区 [S] 节点。"`：非 [S] 节点提示。
  - `STAGING_LIST_PATH_INVALID = "暂存区路径不存在或为空：{path}"`：路径无效提示模板。

### Changed

- **FileListModel 重构为 TableModel**：[src/app/file_list_model.py](src/app/file_list_model.py) 从 `QAbstractListModel`（单列）升级为 `QAbstractTableModel`（4 列）。
  - 列常量：`COL_NAME=0, COL_TYPE=1, COL_SIZE=2, COL_MODIFIED=3, COLUMN_COUNT=4`。
  - 排序键常量：`SORT_NAME, SORT_TYPE, SORT_SIZE, SORT_MODIFIED`。
  - `data()` 按列返回：
    - 名称列：`name` + 内容单元标记（沿用 `[内容单元 ✓]` / `[内容单元]`）；`ToolTipRole` 返回完整路径；`DecorationRole` 返回文件夹/文件图标（缓存复用）。
    - 类型列：文件夹 → `"文件夹"`；文件 → 扩展名小写（无扩展名回退 `"文件"`）。
    - 大小列：文件 → 字符串形式的字节数；文件夹 → 空字符串。
    - 修改日期列：ISO 8601 UTC 原值。
    - `UserRole`：任意列均返回 `FileEntry` 对象。
  - `headerData()` 水平方向返回 `FILE_LIST_COLUMN_HEADERS[section]`；垂直/越界/非 DisplayRole 返回 None。
  - 新增 `set_sort_key(sort_key, ascending)` 方法 + `current_sort_key()` / `is_sort_ascending()` 测试接口。
  - **两步稳定排序**（修复降序时文件夹跑到最前的 bug）：
    ```python
    def _apply_sort(self) -> None:
        # 1. 按值排序（受 ascending 影响）
        self._entries.sort(
            key=lambda e: _sort_value_key(e, self._sort_key),
            reverse=not self._sort_ascending,
        )
        # 2. 稳定排序调整文件夹位置（不受 ascending 影响）
        if self._sort_key in (SORT_NAME, SORT_TYPE):
            self._entries.sort(key=lambda e: not e.is_dir)
        else:
            self._entries.sort(key=lambda e: e.is_dir)
    ```
    第一步按值升/降序，第二步稳定排序把文件夹固定在最前（名称/类型列）或最后（大小/日期列）。Python `sort` 稳定，第二步不破坏第一步的相对顺序。
  - 默认排序：`SORT_NAME` + `ascending=True`。`refresh(entries)` 复制传入列表后立即应用当前排序。
- **MainWindow 中栏从 QListView 改为 QTableView**：[src/app/main_window.py](src/app/main_window.py)
  - 导入变更：移除 `QListView`，新增 `QAbstractItemView, QHeaderView, QTableView`。
  - `_content_view` 配置：`SelectRows` / `NoEditTriggers` / 隐藏垂直表头 / 水平表头 `HighlightSections=False` / `StretchLastSection=False` / 名称列 `Stretch` / `SectionsClickable=True`。
  - 新增 `_on_content_header_clicked(column)`：同列点击翻转升降序，不同列切换排序键默认升序。调用 `set_sort_key` 后立即刷新视图。
  - 新增 `_refresh_staging_content_list(staging_path)`：调用 `list_staging_entries` 加载递归列表；路径不存在时中栏清空 + 显示 `STAGING_LIST_PATH_INVALID` 友好提示。
- **整理模式新语义**：[src/app/main_window.py](src/app/main_window.py)
  - **旧行为**：整理模式中栏冻结为切换前所在目录的单层文件列表。
  - **新行为**：整理模式只加载 `[S]` 节点的递归列表；非 `[S]` 节点 → 中栏清空 + 显示 `STAGING_LIST_NO_STAGING_SELECTED` 提示。
  - `_on_tree_selection_changed` 整理模式分支：`is_staging=True` → 调用 `_refresh_staging_content_list`；否则只更新目标提示，中栏保持空。
  - `_on_mode_changed` 重构：调用 `_enter_organize_mode()` 替代 `_freeze_workarea_for_organize()`。
  - 新增 `_enter_organize_mode()`：当前选中节点为 `[S]` → 加载递归列表；非 `[S]` 或无选中 → 中栏清空 + 显示提示。
  - `_update_organize_hint` 更新：无工作区时显示 "请选中 [S] 节点" + 可选目标提示（如有选中节点）。
  - `_refresh_content_list_after_scan` 更新：整理模式下调 `_refresh_staging_content_list`（仅当存在 `[S]` 工作区时刷新，否则保持空）。

### Tests

- 测试数量变化：338 passed, 2 skipped → 383 passed, 3 skipped（+45 新测试；3 skipped 均为 Windows 符号链接权限不足，与代码无关）。
- [tests/test_content_service.py](tests/test_content_service.py)：新增 `TestListStagingEntries` 类（11 项）——递归遍历含子目录文件 / 批量 content_unit 关联（避免 N 次查询）/ 单层 vs 递归区别 / 中文路径 / 中文文件名 / 排序（文件夹优先 + 名称升序）/ 符号链接跳过 / 路径不存在返回空 / 非目录返回空 / FileEntry 实例字段验证 / path_key 归一化匹配。
- [tests/test_file_list_model.py](tests/test_file_list_model.py)：完全重写适配 TableModel（约 38 项）——
  - 空 model（rowCount / columnCount / data 返回 None）。
  - refresh（加载 / 重置 / 复制列表 / 应用当前排序）。
  - headerData（水平 4 列 / 垂直 None / 越界 None / 非 DisplayRole None）。
  - DisplayRole（名称无标记 / 未整理标记 / 已整理标记 / 类型文件夹 / 类型文件带扩展名 / 类型文件无扩展名 / 类型大写扩展名转小写 / 大小文件 / 大小文件夹空 / 修改日期 / 中文名）。
  - ToolTipRole（名称列返回路径 / 其他列 None）。
  - UserRole（任意列返回 FileEntry）。
  - DecorationRole（文件夹图标 / 文件图标 / 仅名称列）。
  - 排序（默认名称升序 / 名称升降序 / 类型升降序 / 大小升降序 / 日期升降序 / 同列翻转 / 不同列切换 / 无效键忽略 / refresh 应用排序）。
- [tests/test_main_window_staging_list.py](tests/test_main_window_staging_list.py)（新文件，9 项）——整理模式选中 `[S]` 节点显示递归列表 / 非 `[S]` 节点显示提示 / 切回浏览模式恢复单层列表 / 列头点击切换排序 / 列头同列翻转升降序 / 中文路径暂存区 / 扫描完成刷新暂存区列表 / 路径不存在友好提示 / 未选中节点切换到整理模式显示提示。
- [tests/test_main_window_mode.py](tests/test_main_window_mode.py)：更新 6 项测试适配新整理模式语义——
  - `test_switch_to_organize_freezes_content` → 中栏清空（非 [S] 节点）。
  - `test_organize_mode_tree_click_does_not_refresh_content` → 中栏仍为空。
  - `test_organize_mode_shows_target_hint` → 目标提示含 Weapons。
  - `test_switch_back_to_browse_refreshes_content` → 中栏先空后刷新为 Weapons 节点内容。
  - `test_scan_finished_refreshes_content_list_in_organize` → 无 [S] 工作区时不刷新（中栏保持空）。
  - `test_organize_no_workarea_hint` → 提示 "暂存区 [S]" 或 "请选中"。

### 安全限制

- 暂存区列表数据源为文件系统（`Path.rglob` / `is_dir` / `is_symlink` / `stat`），仅只读，不修改用户文件。
- 跳过符号链接，避免循环遍历。
- 路径不存在 / 非目录 / 递归读取失败均返回空列表或友好提示，不崩溃。
- 列头排序纯内存操作，不访问文件系统或数据库。
- UI 不直接调用文件写 API（AGENTS 规则 3）；整理模式新语义不触发任何文件操作。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 58 files already formatted
- `python -m pytest` → 383 passed, 3 skipped

### Documentation

- 更新 [docs/roadmap.md](docs/roadmap.md)：阶段 3 Task 2 验收项全部 `[ ]` → `[x]`，标题加 ✅ 标记。

## [0.16.0] - 2026-07-14

阶段 3 Task 1：暂存区标记与管理。schema_version 从 4 升级至 5（新增 `staging_area` 表）。仅写应用数据库，不修改用户文件。

### Added

- **Schema v5 迁移**：[src/infrastructure/migrations.py](src/infrastructure/migrations.py) 新增 `migrate_v4_to_v5`，创建 `staging_area` 表（id / real_path / path_key / display_name / created_at / updated_at）+ `idx_staging_area_path_key` 索引；`CURRENT_SCHEMA_VERSION` 由 4 升至 5。
- **领域模型**：[src/domain/models.py](src/domain/models.py) 新增 `StagingArea` dataclass（含字段非空校验）。
- **Repository**：[src/infrastructure/repositories/staging_area.py](src/infrastructure/repositories/staging_area.py)（新文件）`StagingAreaRepository` 提供 CRUD（create / get_by_id / get_by_path_key / list_all / delete），不自提交，`IntegrityError` 转 `ConstraintViolationError`。
- **Application 服务**：[src/application/staging_service.py](src/application/staging_service.py)（新文件）`StagingService` 实现：
  - `mark_staging`：只读校验路径合法性（Path.exists / Path.is_dir）后写入配置；含祖先+子树双向嵌套检查（基于 `os.sep` 边界的字符串前缀比较，避免 `a/b` 误判为 `a/bc` 的祖先）。
  - `unmark_staging`：仅删除 `staging_area` 记录，不修改用户文件。
  - `list_staging` / `get_staging` / `is_staging` / `get_staging_path_keys`：查询接口。
- **Application 错误类型**：[src/application/errors.py](src/application/errors.py) 新增 `StagingAreaNotFoundError` / `DuplicateStagingAreaError` / `StagingAreaNestingError`。
- **目录树集成**：[src/application/folder_tree_service.py](src/application/folder_tree_service.py) `TreeNode` 新增 `is_staging: bool = False` 字段；`FolderTreeService.__init__` 新增可选 `staging_service` 参数；内部维护 `_staging_keys_cache: set[str] | None` 惰性缓存，`refresh_staging_cache()` 在标记/取消后增量更新，所有 7 处 TreeNode 构造点均填充 `is_staging`。
- **UI 右键菜单**：[src/app/main_window.py](src/app/main_window.py) 目录树启用 `CustomContextMenu` 策略，`_on_tree_context_menu` 根据节点 `is_staging` 显示"标记为暂存区"或"取消暂存区标记"：
  - 标记流程：`mark_staging` → `_commit()` → `refresh_staging_cache()` → `_tree_model.refresh()`，状态栏提示"已标记为暂存区"。
  - 取消流程：通过 `list_staging()` 查找匹配 `real_path` 的记录 ID → `unmark_staging` → commit → refresh。
  - 错误处理：`DuplicateStagingAreaError` / `StagingAreaNestingError` / `StagingAreaNotFoundError` 弹中文 QMessageBox 提示；其他异常记日志后弹错误对话框。
- **UI 显示**：[src/app/folder_tree_model.py](src/app/folder_tree_model.py) `data()` 在 `is_staging=True` 时为 display_name 添加 `[S] ` 前缀；[src/app/ui_constants.py](src/app/ui_constants.py) 新增 `TREE_STAGING_HINT` / `MENU_MARK_STAGING` / `MENU_UNMARK_STAGING` 常量。
- **入口注入**：[src/app/main.py](src/app/main.py) 构造 `StagingService` 实例，同时注入 `FolderTreeService`（用于目录树 `[S]` 显示）与 `MainWindow`（用于右键菜单）。

### Tests

- 测试数量变化：292 passed, 2 skipped → 338 passed, 2 skipped（+46 新测试）。
- [tests/test_staging_area_repository.py](tests/test_staging_area_repository.py)（新文件，11 项）：CRUD、中文路径、唯一约束、排序、持久化、显式 commit。
- [tests/test_staging_service.py](tests/test_staging_service.py)（新文件，20 项）：标记/取消/查询/嵌套检查（祖先+子树双向）/中文路径/不修改文件/重启持久化/不自提交。
- [tests/test_folder_tree_service.py](tests/test_folder_tree_service.py)：新增 `TestStagingMark` 类（6 项），覆盖根节点/子节点标记、未标记、取消后刷新、get_node 反映标记、无 StagingService 默认 False。
- [tests/test_main_window_staging.py](tests/test_main_window_staging.py)（新文件，8 项）：右键标记/取消、`[S]` 前缀显示、未注入 StagingService 时菜单 noop、嵌套拒绝弹 QMessageBox、重启后保留、中文路径、取消未标记节点提示、DB 持久化。
- [tests/test_migrations.py](tests/test_migrations.py)：更新断言为 schema v5；新增 `test_migrate_v4_to_v5_idempotent`；原 `test_init_db_migrates_v3_db_to_v4` 重命名为 `test_init_db_migrates_v3_db_to_v5`。

### Documentation

- 更新 [docs/roadmap.md](docs/roadmap.md)：阶段 3 Task 1 验收项全部 `[ ]` → `[x]`，标题加 ✅ 标记。

## [0.15.1] - 2026-07-14

Code Review 第二批修复：修复进入阶段 3 前的 3 项高优先级技术债。schema_version 维持 4。

### Fixed

- **TD-H4 + TD-H5**：[src/app/main_window.py](src/app/main_window.py) `_on_thread_finished` 修复扫描线程竞态条件。
  - 原实现盲目清除 `self._worker`/`self._thread` 引用，当用户在扫描完成后立即触发新扫描时，旧线程退出会误清除指向新扫描线程的引用，导致 closeEvent 无法等待新线程退出（Qt 析构运行中 QThread 可致崩溃）。
  - 修复：用 `sender()` 校验退出的线程是否为当前 `self._thread`，仅匹配时才清除引用。
- **TD-H6**：[src/infrastructure/repositories/content_unit.py](src/infrastructure/repositories/content_unit.py) `list_by_path_prefix` 修复 SQL LIKE 通配符未转义问题。
  - 原实现将 `prefix` 直接拼入 LIKE 模式，未转义 `%` 和 `_`。Mod 目录名中 `_` 极常见（如 `my_mods`、`SkyUI_5.1`），`_` 在 LIKE 中匹配任意单字符会导致错误路径被返回。
  - 修复：转义 `prefix + sep` 中的 `%`、`_`、`\`，使用 `ESCAPE '\\'` 子句。

### Tests

- 测试数量变化：292 passed, 2 skipped（+6 新测试）。
- [tests/test_content_unit_repository.py](tests/test_content_unit_repository.py)：新增 2 项测试验证 `_` 和 `%` 不被误认为 LIKE 通配符。
- [tests/test_main_window_scan_thread.py](tests/test_main_window_scan_thread.py)（新文件）：4 项测试覆盖线程引用管理——直接调用不清除非 None 引用、sender 匹配时正常清除、旧线程退出不误清除新线程引用、closeEvent 线程安全。

### Documentation

- 更新 [docs/technical-debt.md](docs/technical-debt.md)：标记 TD-H4/H5/H6 为已修复，更新处理优先级建议。

## [0.15.0] - 2026-07-14

Code Review 第一批修复：删除方向 C 重构后的遗留死代码，修复路径归一化与事务一致性问题。schema_version 维持 4。未在本轮修复的问题已记录至 [docs/technical-debt.md](docs/technical-debt.md)。

### Removed（死代码清理）

- 删除缩略图子系统死代码（C1 + C2 + H6）：
  - `src/application/thumbnail_coordinator.py`（导入不存在的 FileAsset/FileAssetRepository）
  - `src/infrastructure/thumbnail_generator.py`（使用旧版 asset_id 体系）
  - `src/infrastructure/repositories/thumbnail_cache.py`（SQL 使用 asset_id 列但 schema v4 已改名）
  - `src/app/thumbnail_worker.py`（引用不存在的 FileAssetRepository）
  - `src/infrastructure/file_operation_service.py`（旧版四步状态机死代码）
  - `tests/test_thumbnail_cache.py` / `tests/test_thumbnail_generator.py` / `tests/test_thumbnail_coordinator.py`（整模块 skip 且内容过时）
- 删除 `src/infrastructure/file_scanner.py` 中的死代码字段（M8）：
  - `ScannedFolderEntry.is_content_unit_candidate`
  - `ScanResult.content_unit_candidates`
  - `_scan_dir` 中对应的 `is_content_unit_candidate=False` 赋值

### Fixed（路径归一化与事务一致性）

- **C3**：[src/application/content_service.py](src/application/content_service.py) `list_by_directory` 中 `Path.resolve()` 改为 `make_path_key()`，与项目约定的路径归一化策略一致。
- **C4**：[src/application/scan_service.py](src/application/scan_service.py) + [src/infrastructure/file_scanner.py](src/infrastructure/file_scanner.py) 路径字典键/集合元素统一使用 `make_path_key()` 归一化，替代原始路径字符串。
- **H2**：[src/application/managed_root_service.py](src/application/managed_root_service.py) `add_root` 捕获 `ConstraintViolationError` 转为 `DuplicateManagedRootError`，修复 TOCTOU 竞态（原实现先查后插，并发场景下可绕过去重）。
- **H5**：[src/infrastructure/repositories/managed_root.py](src/infrastructure/repositories/managed_root.py) `create()` / `delete()` 移除 `self._conn.commit()`，改为不自提交，由 application 层通过 `commit_callback` 控制事务边界。
- **M12**：[src/infrastructure/db.py](src/infrastructure/db.py) `get_connection` 设置 `conn.row_factory = sqlite3.Row`，使查询结果可按列名访问，与所有 Repository 的 `_row_to_model` 实现一致。

### Tests

- 测试数量变化：286 passed, 2 skipped（删除 3 个被 skip 的缩略图测试文件减少 3 个 skipped；删除 `test_old_candidates_field_empty` 减少 1 个 passed）。
- [tests/test_file_scanner.py](tests/test_file_scanner.py)：`mtime_map` 键改为 `make_path_key(e.path)` 与 FileScanner 内部查询一致；删除 `test_old_candidates_field_empty`。
- [tests/test_managed_root_repository.py](tests/test_managed_root_repository.py)：`test_create_commits_transaction_without_explicit_commit` 重写为 `test_create_requires_explicit_commit`，验证不自提交 + 显式 commit 后跨连接可见。
- [tests/test_managed_root_service.py](tests/test_managed_root_service.py)：`test_add_root_persists_without_explicit_commit` 重写为 `test_add_root_requires_explicit_commit`，添加显式 `conn1.commit()`。

### Documentation

- 新增 [docs/technical-debt.md](docs/technical-debt.md)：记录 Code Review 中未在本轮修复的 6 个 High + 20 个 Medium + 17 个 Low 级别问题，按优先级分类并给出修复建议。

## [0.14.0] - 2026-07-13

对应 [docs/roadmap.md](docs/roadmap.md) 阶段 2 Task 5（双模式切换 + 扫描联动）完成。schema_version 维持 4。

**新增功能**：
- 顶部 `[浏览 | 整理]` 模式切换按钮（默认浏览模式，互斥分组）。
- 整理模式：中栏内容冻结为切换前所在目录的文件列表（工作区），目录树点击节点只高亮目标并显示"目标：xxx"提示，不刷新中栏。
- 浏览模式：目录树点击节点 → 中栏刷新该目录文件列表（Task 4 既有行为）。
- 扫描联动：扫描完成后自动刷新当前中栏文件列表，使新扫描出的压缩包文件立即显示 `[内容单元]` 标记（浏览模式刷新当前选中节点，整理模式刷新冻结的工作区）。
- 整理模式下 `_refresh_tree` 不清空中栏内容（保留冻结的工作区）。

**设计约束**：
- 暂存区完整功能（标记/取消/持久化/目录树 [S] 标记）属阶段 3 Task 1，本 Task 只实现模式切换框架 + 扫描联动。
- 整理模式中栏"冻结"语义为保留切换前所在目录的文件列表，作为简化工作区。
- 切回浏览模式时中栏恢复跟随目录树当前选中节点刷新。
- 整理模式下右栏元数据面板保留当前行为（双击内容单元显示元数据），不因模式切换清空。

### Added

- [src/domain/models.py](src/domain/models.py)：新增 `AppMode(StrEnum)` 枚举（browse / organize），纯领域枚举无数据库知识。
- [src/app/mode_manager.py](src/app/mode_manager.py)（新文件）：`ModeManager(QObject)` 封装当前模式状态，提供 `mode_changed` 信号；相同模式重复设置不 emit 信号。
- [src/app/ui_constants.py](src/app/ui_constants.py)：新增模式切换相关常量（`MODE_SWITCH_GROUP_TITLE` / `MODE_BROWSE` / `MODE_ORGANIZE` / `MODE_BROWSE_HINT` / `MODE_ORGANIZE_HINT` / `MODE_ORGANIZE_WORKAREA_HINT` / `MODE_ORGANIZE_TARGET_HINT` / `MODE_ORGANIZE_NO_WORKAREA`）。

### Changed

- [src/app/main_window.py](src/app/main_window.py)：
  - 顶部新增模式切换栏（QHBoxLayout + QButtonGroup 互斥），主布局改为顶部栏 + 三栏 splitter。
  - 中栏顶部新增 `_mode_hint_label` 显示当前模式提示与目标路径。
  - `__init__` 新增 `ModeManager`、`_organize_workarea_path`、`_organize_target_path` 字段。
  - `_on_tree_selection_changed` 新增模式分支：浏览模式刷新中栏 + 清空元数据；整理模式只更新目标路径提示，不刷新中栏。
  - `_refresh_tree` 在整理模式下不清空中栏文件列表（保留冻结的工作区）。
  - `_on_scan_finished` 扫描完成后调用 `_refresh_content_list_after_scan` 刷新当前中栏文件列表。
  - 新增 `_on_mode_changed` / `_freeze_workarea_for_organize` / `_update_organize_hint` / `_refresh_content_for_current_tree_selection` / `_refresh_content_list_after_scan` 方法。
  - 新增测试接口：`current_mode()` / `mode_hint_text()` / `mode_hint_full_text()` / `organize_workarea_path()`。
  - **UI 一致性修复**：统一所有路径显示策略为 Elide + Tooltip。
    - `_mode_hint_label` 关闭自动换行（`setWordWrap(False)`）+ PlainText，走统一 Elide 流程。
    - `_elide_label_lines` 识别"目标："前缀，对值部分 ElideMiddle（与"路径："/"完整路径："一致）。
    - 详情区、元数据面板、模式提示三个标签均设置 Tooltip 显示完整原文，便于鼠标悬停查看。
    - 拆分 `_elide_single_line` 方法，提取单行 Elide 逻辑。
    - `_ELIDE_PATH_PREFIXES` 类常量统一管理路径前缀列表。

### Tests

- 单元测试 14 项新增（总计 287 passed, 5 skipped），覆盖：
  - `tests/test_mode_manager.py`（5 项，新文件）：初始模式 / 切换到 organize / 切换回 browse / 相同模式不 emit / 信号正确发射。
  - `tests/test_main_window_mode.py`（9 项，新文件）：初始模式为 browse / 切换到整理模式冻结中栏 / 整理模式点击目录树不刷新中栏 / 整理模式显示目标提示 / 切回浏览模式刷新中栏 / 扫描完成刷新中栏（浏览模式）/ 扫描完成刷新工作区（整理模式）/ 未选中节点切换到整理模式显示提示 / 长目标路径 Elide + Tooltip。

### 安全限制

- 模式切换纯 UI 状态变更，不访问数据库或文件系统。
- 扫描联动中的文件列表刷新通过 `ContentService.list_directory_entries` 只读访问文件系统，不修改用户文件。
- 整理模式下目录树点击节点只更新 UI 高亮与提示文本，不触发任何文件操作。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 59 files already formatted
- `python -m pytest` → 287 passed, 5 skipped

## [0.13.0] - 2026-07-13

对应 [docs/roadmap.md](docs/roadmap.md) 阶段 2 Task 4（文件列表 + 内容单元显示）完成。schema_version 维持 4。

**2026-07-13 设计修正**：中间列表从"仅显示内容单元"改为"显示目录下所有文件，内容单元只是标记"。
内容单元不是可见性门槛，未标记的文件也正常可见可操作（spec §5.1 关键设计）。

**2026-07-13 扫描规则修正（spec §5.4）**：内容单元识别规则从"含压缩包的文件夹"改为"压缩包文件本身"。
- 压缩包文件路径作为 `ContentUnit.path`（不再是文件夹路径）。
- `ContentUnit.title` 为压缩包文件名（含扩展名）。
- 文件夹不自动标记为内容单元（手动标记属阶段 3 Task 3）。
- 递归所有子目录，不再因识别到压缩包而停止递归。
- 双击非内容单元（文件或文件夹）不响应（spec §5.1 L205），移除 `os.startfile` 调用。

**2026-07-13 性能修复**：`FileListModel` 图标缓存优化，解决文件列表 hover 高亮延迟。
- 根因：`QStyle.standardIcon()` 无内部缓存，Qt 在 hover/paint/selection 高频事件中反复调用 `data(DecorationRole)` 导致每次重新渲染图标像素图。
- 修复：在 Model `__init__` 中预创建 `QIcon` 实例并缓存，`_icon_for` 直接返回缓存（懒加载，QApplication 未就绪时跳过）。

### Added

- Domain 数据类 `FileEntry` [src/domain/models.py](src/domain/models.py)：
  - 描述目录条目（文件或文件夹）+ 可选的 `ContentUnit` 关联。
  - 字段：name / path / is_dir / modified_at（ISO 8601 UTC）/ size（文件夹为 None）/ content_unit（未标记时为 None）。
- 内容单元查询服务扩展 [src/application/content_service.py](src/application/content_service.py)：
  - 新增 `ContentService.list_directory_entries(dir_path)`：从文件系统读取目录下所有条目（`Path.iterdir` / `is_dir` / `stat`，只读），按 path 精确匹配 `content_unit` 表填充关联。
  - 排序：文件夹在前，名称不区分大小写升序。
  - 跳过符号链接（避免循环）。目录不存在/读取失败返回空列表（记日志）。
  - 保留原有 `list_by_directory` / `list_direct_children` / `get_by_id`。
- 文件列表 Qt Model [src/app/file_list_model.py](src/app/file_list_model.py)（新文件，替代旧 `content_unit_list_model.py`）：
  - `FileListModel(QAbstractListModel)`：展示 `FileEntry` 列表。
  - DisplayRole：name + 内容单元标记（`[内容单元 ✓]` if organized / `[内容单元]` if unorganized / 无标记 if 非内容单元）。
  - ToolTipRole：完整路径。UserRole：`FileEntry` 对象。DecorationRole：Qt 内置标准图标（`QStyle.SP_DirIcon` 文件夹 / `SP_FileIcon` 文件）。
  - `refresh(entries)` 重置列表。测试接口：`entry_at(row)` / `entry_count()`。
- UI 文案常量 [src/app/ui_constants.py](src/app/ui_constants.py)：
  - 新增文件列表项标记：CONTENT_UNIT_MARKER_ORGANIZED / CONTENT_UNIT_MARKER_UNORGANIZED。
  - 新增右键菜单常量：CONTEXT_MENU_COPY_PATH / CONTEXT_MENU_COPY_PATH_OK。
  - 新增元数据面板常量：METADATA_NOT_CONTENT_UNIT（双击非内容单元文件时显示）。
  - CONTENT_LIST_GROUP_TITLE 从"内容单元列表"改为"文件列表"；CONTENT_LIST_EMPTY_HINT 调整为"该目录为空或无可见文件。"

### Changed

- [src/app/main_window.py](src/app/main_window.py)：
  - 三栏布局与 spec §7.1 一致：
    - 左栏：受管理根目录 + 扫描控制 + 扫描状态 + 目录树 + 选中目录详情。
    - 中栏：文件列表（QListView + FileListModel，数据源为文件系统，content_unit 表仅作标记）。
    - 右栏：元数据面板（QLabel，只读显示）。
  - 构造签名：`content_service: ContentService` 参数保留。
  - `_on_tree_selection_changed`：选中目录树节点时调用 `ContentService.list_directory_entries` 刷新文件列表，同时清空元数据面板。
  - `_on_entry_activated`（替代 `_on_content_unit_activated`）：双击行为分支：
    - 内容单元 → 右栏显示元数据（8 字段只读：标题/路径/类型/来源 URL/评分/整理状态/备注/创建时间）。
    - 非内容单元（文件或文件夹）→ 不响应，右栏保持现状（spec §5.1 L205）。移除 `os.startfile` 调用。
  - 新增右键菜单（`customContextMenuRequested`）：本 Task 仅实现"复制路径"（决策问题 2），重命名/删除属阶段 5 Task 3。
  - 新增 Elide 路径文本（决策问题 4）：
    - 详情区路径标签 + 元数据面板路径字段启用 ElideMiddle。
    - QLabel 关闭自动换行 + PlainText 格式，缓存原文供 `resizeEvent` 重算。
    - `_set_detail_text` / `_set_metadata_text` 缓存原文并触发 Elide；`resizeEvent` 调用 `_apply_elide`。
  - 测试接口：`entry_count()` / `entry_at(row)` / `metadata_text()` / `metadata_full_text()` / `detail_full_text()`。
- [src/app/main.py](src/app/main.py)：构造 `ContentService(ContentUnitRepository(conn))` 注入 `MainWindow`（无变化，沿用）。
- [src/infrastructure/file_scanner.py](src/infrastructure/file_scanner.py)（扫描规则修正 spec §5.4）：
  - `ScanResult` 新增 `archive_candidates: list[str]` 字段，记录压缩包文件完整路径。
  - `ScannedFolderEntry.is_content_unit_candidate` 恒为 False（向后兼容保留）。
  - `_scan_dir` 遍历文件时，压缩包文件路径记入 `result.archive_candidates`。
  - 移除"识别后停止递归"逻辑：无条件递归所有子目录（含压缩包所在目录的子目录）。
- [src/application/scan_service.py](src/application/scan_service.py)（扫描规则修正 spec §5.4）：
  - `_persist_scan_result` 从 `result.archive_candidates` 读取压缩包路径，创建 `ContentUnit`：
    - `path` = 压缩包文件路径；`title` = 文件名（含扩展名）；`content_type` = "mod"；`status` = "unorganized"。
    - 仅插入新候选（已存在 path 跳过，避免重复）。
    - 单个创建失败不中断整体流程，记入 `summary.errors`。
- [src/app/file_list_model.py](src/app/file_list_model.py)（性能修复）：
  - 新增 `_dir_icon` / `_file_icon` / `_icons_initialized` 缓存字段。
  - 新增 `_ensure_icons()` 懒加载方法：QApplication/style 未就绪时跳过，下次调用再尝试。
  - `_icon_for(entry)` 改为直接返回缓存的 `QIcon` 实例，避免 hover/paint 高频事件中反复调用 `QStyle.standardIcon()`。

### Removed

- 删除 [src/app/content_unit_list_model.py](src/app/content_unit_list_model.py)（旧文件，由 `file_list_model.py` 替代）。
- 删除 [tests/test_content_unit_list_model.py](tests/test_content_unit_list_model.py)（旧测试）。

### Tests

- 单元测试 60 项新增/重写（总计 273 passed, 5 skipped），覆盖：
  - `test_file_list_model.py`（20 项，新文件）：
    - 空 model / refresh 加载 / refresh 重置 / refresh 复制列表；
    - DisplayRole（非内容单元无标记 / 未整理标记 / 已整理标记 / 中文文件名）；
    - ToolTipRole（路径 / 中文路径）/ UserRole（FileEntry 对象）；
    - DecorationRole（文件夹图标 / 文件图标）；
    - 无效 index（QModelIndex / 越界 / 负数行）；
    - entry_at（合法 / 越界）/ rowCount（带 parent index）。
  - `test_content_service.py` 新增 TestListDirectoryEntries（11 项）：
    - 空目录 / 不存在路径 / 非目录 / 列出所有文件和文件夹 / 文件夹排前 / 基本字段 / 文件夹 size 为 None；
    - 内容单元关联（压缩包文件路径）/ 非内容单元 content_unit 为 None / 中文文件名 / 返回 FileEntry 实例 / 符号链接跳过。
  - `test_main_window_content.py`（13 项，重写）：
    - 初始状态 / 选中节点刷新列表 / 含非内容单元文件 / 压缩包文件是内容单元 / 子目录中压缩包是内容单元 / 双击内容单元显示元数据；
    - 双击非内容单元文件不响应 / 双击非内容单元文件夹不响应（同目录内测试，避免切换目录清空元数据）；
    - 切换节点清空 / 未扫描根不崩溃 / 中文文件名 / 右键复制路径 / Elide 长路径。
  - `test_file_scanner.py`（重写，13 项）：递归所有子目录 / 压缩包文件记入 archive_candidates / 文件夹不在候选中 / 旧字段为空 / 递归含压缩包目录的子目录 / 中文路径 / 中文压缩包名 / 根不存在 / 根非目录 / 空根 + 增量扫描（3）+ 符号链接。
  - `test_scan_service.py`（重写，11 项）：全量扫描持久化 folder_cache / 持久化压缩包候选为 ContentUnit.path / 默认 status / title 含扩展名 + 增量扫描（2）+ 错误（2）+ scan_by_path + 重复扫描（2）。
  - `tests/conftest.py` 新增全局 `qapp` fixture（session 级，所有 Qt 测试复用）。

### 安全限制

- 文件列表数据源为文件系统（`Path.iterdir` / `is_dir` / `is_file` / `stat`），仅只读，不修改用户文件。
- 跳过符号链接，避免循环遍历。
- 目录读取失败返回空列表，不崩溃。
- 右键菜单"复制路径"只写入剪贴板，不访问文件系统。
- UI 不直接调用文件写 API（AGENTS 规则 3）；双击非内容单元不响应，不调用 `os.startfile` 或任何外部程序（spec §5.1 L205）。
- 扫描器严格只读：仅使用 `Path.iterdir` / `is_dir` / `is_file` / `is_symlink` / `stat`，不修改用户文件。
- 单目录扫描失败不中断整体流程，记入 `ScanResult.errors`。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 56 files already formatted
- `python -m pytest` → 273 passed, 5 skipped

## [0.12.0] - 2026-07-12

对应 [docs/roadmap.md](docs/roadmap.md) 阶段 2 Task 3（目录树浏览）完成。schema_version 维持 4。

### Added

- 只读目录树查询服务 [src/application/folder_tree_service.py](src/application/folder_tree_service.py)（新文件）：
  - `TreeNode` dataclass：node_id / display_name / real_path / category / is_managed_root / managed_root_id / folder_cache_id / parent_id。
  - category 取值：`managed_root`（已扫描根目录）/ `unscanned_root`（未扫描根目录）/ `folder`（普通子目录）。
  - 节点 ID 约定：`"mr:<managed_root_id>"` / `"fc:<folder_cache_id>"`。
  - `FolderTreeService.list_root_nodes()`：合并 ManagedRoot 与 FolderCache 根节点，已扫描→managed_root，未扫描→unscanned_root。
  - `FolderTreeService.list_children(node_id)`：按 node_id 前缀分发（mr:→managed_root 子节点，fc:→folder_cache 子节点）。
  - `FolderTreeService.get_node(node_id)` / `count_children(node_id)` / `has_scan_data(managed_root_id)`。
  - 关联逻辑（决策问题 1 选项 B）：对 FolderCache.path 调用 make_path_key 归一化后与 ManagedRoot.path_key 比较，不改 schema。
  - 不访问文件系统；不写数据库。
- Qt 目录树 model [src/app/folder_tree_model.py](src/app/folder_tree_model.py)（新文件）：
  - `FolderTreeModel(QAbstractItemModel)`：采用 Qt 推荐的内部节点对象 + 对象引用 internalPointer 的标准实现。
  - `_Node` 内部类持有 TreeNode、父节点引用、子节点列表、loaded 标记、row_in_parent 行号。
  - 惰性加载（canFetchMore / fetchMore），`fetchMore` 直接使用 View 传入的 parent。
  - `parent()` O(1) 直接访问（通过 _Node.parent 引用 + row_in_parent 缓存）。
  - 数据源严格为 FolderTreeService（即 SQLite folder_cache 表），不重新扫描文件系统。
  - 未扫描根目录 display 追加「（未扫描）」提示。
  - 选中节点可通过 node_at / node_id_at 接口获取。
  - refresh() 重置所有缓存并重新加载根节点。
- UI 文案常量 [src/app/ui_constants.py](src/app/ui_constants.py)：
  - 新增目录树区域常量：TREE_GROUP_TITLE / TREE_EMPTY_HINT / TREE_UNSCANNED_HINT。
  - 新增详情区常量：DETAIL_GROUP_TITLE / DETAIL_NAME_LABEL / DETAIL_PATH_LABEL / DETAIL_IS_ROOT_LABEL / DETAIL_TYPE_LABEL / DETAIL_CHILD_COUNT_LABEL / DETAIL_TYPE_MANAGED_ROOT / DETAIL_TYPE_UNSCANNED_ROOT / DETAIL_TYPE_FOLDER / DETAIL_NOT_SELECTED。
  - 移除旧占位常量 PLACEHOLDER_CONTENT_TITLE / PLACEHOLDER_CONTENT_HINT。

### Changed

- [src/app/main_window.py](src/app/main_window.py)：
  - 构造签名新增 `folder_tree_service: FolderTreeService` 参数。
  - 右栏占位替换为目录树（QTreeView + FolderTreeModel）+ 选中目录详情（QLabel）。
  - 详情区显示 5 字段：目录名称 / 完整路径 / 是否受管理根目录 / 类型 / 直接子目录数（决策问题 4 选项 A）。
  - `_refresh_tree()`：扫描完成/根目录变更后刷新目录树模型。
  - `_on_tree_selection_changed`：选中节点更新详情区。
  - 添加/移除根目录后调用 `_refresh_tree()`。
  - `_on_scan_finished` 扫描完成后调用 `_refresh_tree()`。
- [src/app/main.py](src/app/main.py)：
  - 构造 `FolderTreeService(ManagedRootRepository(conn), FolderCacheRepository(conn))` 注入 MainWindow。

### Fixed

- **FolderTreeModel 架构重构**：初版实现采用字符串 node_id 作为 internalPointer，`parent()` 通过 service 反查 + 线性扫描实现，存在性能与稳定性缺陷。手动验收时连续暴露三个问题：
  1. `hasChildren` 未重写 → QTreeView 不显示展开箭头，根节点无法展开。
  2. `internalPointer()` 在 PySide6 某些调用路径返回非字符串非 None 对象 → `_loaded` 集合 `in` 操作触发 `TypeError: unhashable type`。
  3. `_fetch` 通过 `_find_index_by_node_id` 重新创建 parent index 调用 `beginInsertRows` → Qt C++ 层 persistent index 机制访问无效内存导致 segfault，展开二级节点时闪退且无 Python 异常输出。
  局部补丁修复无效后，按 Qt 官方推荐架构重构为 `_Node` 内部类 + 对象引用 internalPointer 的标准实现：
  - `parent()` 由 O(深度)+反查 变为 O(1) 直接访问。
  - `fetchMore` 直接使用 View 传入的 parent，满足 persistent index 机制对 index 对象身份的要求。
  - 缓存状态集中在 _Node 对象内（children + loaded），消除多处缓存不一致风险。
  - 删除 `_find_index_by_node_id` / `_children_cache` / `_loaded` 等旧实现。

### Tests

- 单元测试 44 项新增（总计 214 passed, 3 skipped），覆盖：
  - `test_folder_tree_service.py`（22 项）：
    - TestListRootNodes（5）：空数据 / 未扫描根 / 已扫描根 / 中文目录名 / 多根目录 / 重复扫描不重复。
    - TestListChildren（6）：空根节点 / 多层层级 / mr: 前缀分发 / fc: 前缀分发 / 无效 node_id / 未扫描根返回空。
    - TestGetNode（4）：managed_root / folder / 无效 ID / 未扫描根。
    - TestCountChildren（3）：直接子目录数 / 孙节点不计入 / 无效 node_id 返回 0。
    - 持久化验证：重新连接数据库后树可加载。
    - TreeNode category 校验：拒绝非法值 / 接受所有合法值。
  - `test_folder_tree_model.py`（22 项，重构后）：
    - 基础测试（10）：空 model / 未扫描顶层节点 / fetchMore 惰性加载 / 父子关系 / 深层访问 / node_at / node_id_at / refresh 重置 / 无效 index / 中文显示名。
    - hasChildren 测试（5）：未扫描根 / 已扫描根未 fetch / 叶子节点 fetch 后 / 已加载父节点 / 空 model。
    - 旧版缺陷回归测试（7）：
      - `test_fetch_does_not_recurse_when_connected_to_view`：连接真实 QTreeView 后 fetchMore 不触发 RecursionError。
      - `test_fetch_empty_children_does_not_emit_rows_inserted`：空子节点不发 rowsInserted 信号。
      - `test_row_count_handles_invalid_index_without_crash`：rowCount 对无效 QModelIndex 不崩溃。
      - `test_index_handles_invalid_parent_without_crash`：index 对无效 parent 不崩溃。
      - `test_has_children_handles_invalid_index_without_crash`：hasChildren 对无效 QModelIndex 不崩溃。
      - `test_deep_expansion_does_not_crash`：**核心回归测试**——Root/L1/L2/L3 逐级展开 + parent 链验证，连接真实 QTreeView，验证 Qt C++ 层 persistent index 机制在多层 fetchMore 下不崩溃。
      - `test_view_loads_root_children_without_crash`：连接真实 QTreeView 后显式 fetchMore 加载根子节点不崩溃。

### 安全限制

- 目录树数据源严格为 SQLite folder_cache 表，不重新扫描文件系统。
- FolderTreeService 只读：不访问文件系统，不写数据库。
- FolderTreeModel 惰性加载：仅在展开节点时查询子节点，避免一次性加载全树。
- 错误隔离：查询异常捕获并降级为空子树，不崩溃。
- UI 不直接访问 Repository 或文件系统（AGENTS 规则 3）。
- 路径归一化使用 make_path_key（normcase + normpath），支持中文路径。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 51 files already formatted
- `python -m pytest` → 214 passed, 3 skipped
- `python -m app.main` → 主窗口正常启动，可添加目录、扫描、浏览目录树（含深层逐级展开）、选中节点查看详情（人工验收通过）

### Not in Scope

- 内容单元列表与浏览模式（Task 4）。
- 双模式切换（Task 5）。
- 缩略图适配新 schema（Task 4+）。
- 文件操作服务适配新 schema（阶段 3）。

## [0.11.0] - 2026-07-12

对应 [docs/roadmap.md](docs/roadmap.md) 阶段 2 Task 2（方向 C 重建：新扫描器 + Domain/Repository/Service/UI 适配）完成。schema_version 维持 4（Task 1 已建立）。

### Added

- Domain 层重写 [src/domain/models.py](src/domain/models.py)：
  - 移除全部旧实体（ModItem / FileAsset / FolderNode / OperationLog / AssetKind / FileRole / OperationStatus / ConflictPolicy / OperationType）。
  - 新增 `ContentUnit`（id / path / title / content_type / source_url / rating / cover_image / status / notes / created_at / updated_at；status ∈ {unorganized, organized}；rating ∈ [0,5] 或 None）。
  - 新增 `TagCategory`（id / name / color_hue ∈ [0,360]）。
  - 新增 `Tag`（id / name / category_id）。
  - 新增 `OperationHistory`（id / operation_type ∈ {move,delete,rename,new_folder} / source_path / target_path / created_at / can_undo）；`VALID_OPERATION_TYPES` 为 ClassVar 避免被 dataclass 视为实例字段。
  - 新增 `FolderCache`（id / path / parent_id / last_scanned_mtime / managed_root_id）；parent_id 可自引用（根节点）。
  - 保留 `ManagedRoot`（未改动）。
- ContentUnitRepository [src/infrastructure/repositories/content_unit.py](src/infrastructure/repositories/content_unit.py)（新文件）：
  - CRUD：create / get_by_id / get_by_path / list_by_path_prefix / list_all / update / delete。
  - path 唯一约束冲突抛 `ConstraintViolationError`。
  - `_row_to_model` 使用 `row["column"]` 索引（需 row_factory = sqlite3.Row）。
- FolderCacheRepository [src/infrastructure/repositories/folder_cache.py](src/infrastructure/repositories/folder_cache.py)（新文件）：
  - CRUD：create / get_by_id / get_by_path / list_by_parent / list_all / upsert_mtime / delete / delete_by_path。
  - path 唯一约束冲突抛 `ConstraintViolationError`。
  - upsert_mtime：已存在则更新 mtime，不存在抛 `NotFoundError`。
- 文件系统扫描器重写 [src/infrastructure/file_scanner.py](src/infrastructure/file_scanner.py)：
  - `ScanError` / `ScannedFolderEntry` / `ScanResult` 数据类。
  - `FileScanner.scan_full(root)`：全量递归扫描。
  - `FileScanner.scan_incremental(root, folder_mtime_map)`：增量扫描，mtime 未变目录跳过记录但仍递归子目录（子目录 mtime 可能独立变化）。
  - 内容单元识别规则（spec §5.4）：文件夹内含压缩包 → 候选 ContentUnit，识别后停止递归子目录。
  - 只读：仅使用 `Path.iterdir` / `is_dir` / `is_file` / `is_symlink` / `stat`，不修改用户文件。
  - 符号链接不跟随（避免循环）。
  - mtime 相等判定使用差值绝对值 < 0.001 秒（避免浮点精度问题）。
  - 单目录扫描失败不中断整体流程，记入 `ScanResult.errors`。
- 扫描编排服务 [src/application/scan_service.py](src/application/scan_service.py)（新文件）：
  - `ScanSummary` dataclass：root_id / root_path / scanned_dirs / content_units_found / skipped_unchanged / errors。
  - `ScanService.scan_root(root_id, incremental=True)`：读取 ManagedRoot，构建 folder_mtime_map（增量），调用 FileScanner，持久化结果。
  - `ScanService.scan_root_by_path(real_path)`：直接按路径全量扫描。
  - 持久化：folder_cache upsert（更新 mtime 或新建）；content_unit create（path 已存在则跳过，避免重复）。
  - root_id 不存在抛 `ManagedRootNotFoundError`；根路径不存在抛 `ScanError`。
- Application 层错误更新 [src/application/errors.py](src/application/errors.py)：
  - 移除 `ModItemNotFoundError` / `FileAssetNotFoundError` / `MemberLimitError` / `DuplicateMemberError`。
  - 新增 `ScanError`。
- ScanWorker 重写 [src/app/scan_worker.py](src/app/scan_worker.py)：
  - 构造签名：`ScanWorker(db_path, root_id, incremental=True)`。
  - 在自身线程创建独立 SQLite 连接（row_factory = sqlite3.Row）。
  - 信号：scan_started / scan_finished(ScanSummary) / scan_failed(str)。
  - 捕获所有异常转为 scan_failed 信号。
- 主窗口最小修复 [src/app/main_window.py](src/app/main_window.py)：
  - 构造签名：`MainWindow(managed_root_service, db_path, commit_callback=None)`。
  - 左栏：受管理根目录列表 + 添加/移除按钮 + 增量扫描按钮 + 全量重扫按钮 + 扫描状态。
  - 右栏：内容区占位（Task 3+ 实现目录树、内容单元列表、详情面板）。
  - 移除全部旧 UI 组件（素材池、ModItem 列表、详情面板、目录树、缩略图、成员表格）。
  - 扫描期间禁用所有扫描入口与根目录操作按钮。
  - closeEvent 等待后台线程退出。
- 应用入口简化 [src/app/main.py](src/app/main.py)：
  - 仅构造 ManagedRootService 注入 MainWindow。
  - 移除 ModAssemblyService / FolderTreeService / ThumbnailCoordinator 等旧依赖。
- UI 文案更新 [src/app/ui_constants.py](src/app/ui_constants.py)：
  - APP_TITLE 改为 "Skyrim Content Workbench"。
  - 新增 SCAN_BUTTON_FULL / SCAN_BUTTON_SCANNING。
  - format_summary 改名 format_scan_summary，参数调整为 scanned_dirs / content_units_found / skipped_unchanged / errors。
  - 移除旧 Task 3/4 相关常量（素材池、ModItem 列表、详情编辑、成员表格、角色名）。

### Changed

- [src/domain/models.py](src/domain/models.py)：完全重写（见 Added）。
- [src/infrastructure/file_scanner.py](src/infrastructure/file_scanner.py)：完全重写（见 Added）。
- [src/app/scan_worker.py](src/app/scan_worker.py)：完全重写（见 Added）。
- [src/app/main_window.py](src/app/main_window.py)：完全重写为最小可启动版本（见 Added）。
- [src/app/main.py](src/app/main.py)：简化为仅注入 ManagedRootService。
- [src/app/ui_constants.py](src/app/ui_constants.py)：重写文案常量（见 Added）。
- [src/application/errors.py](src/application/errors.py)：移除旧错误，新增 ScanError。

### Removed

- 删除旧 Domain 实体（ModItem / FileAsset / FolderNode / OperationLog 及相关 enum）。
- 删除旧 Repository 模块：
  - `src/infrastructure/repositories/mod_item.py`
  - `src/infrastructure/repositories/file_asset.py`
  - `src/infrastructure/repositories/folder_node.py`
  - `src/infrastructure/repositories/operation_log.py`
- 删除旧 Application Service：
  - `src/application/scan_workflow_service.py`
  - `src/application/mod_assembly_service.py`
  - `src/application/folder_tree_service.py`
- 删除旧 UI model：
  - `src/app/pool_model.py`
  - `src/app/folder_tree_model.py`
- 删除旧测试文件：
  - `tests/test_scan_workflow_service.py`

### Preserved（保留但未在 main.py 引用，Task 3+ 重新接入）

- `src/application/thumbnail_coordinator.py`：保留文件，移除 main.py 引用（决策 1）。
- `src/app/thumbnail_worker.py`：保留文件，移除 main.py 引用。
- `src/infrastructure/thumbnail_generator.py`：保留文件，测试仍 skip。
- `src/infrastructure/file_operation_service.py`：保留文件，移除 main.py 引用（决策 2）。
- `src/infrastructure/repositories/thumbnail_cache.py`：保留文件，测试仍 skip。

### Skipped（测试仍 module-level skip，Task 3+ 重新启用）

- `tests/test_folder_tree_model.py`：Task 3 重写目录树后启用。
- `tests/test_folder_tree_service.py`：Task 3 重写目录树后启用。
- `tests/test_thumbnail_coordinator.py`：Task 4+ 适配新 schema 后启用。
- `tests/test_thumbnail_generator.py`：Task 4+ 适配新 schema 后启用。
- `tests/test_thumbnail_cache.py`：Task 4+ 适配新 schema 后启用。

### Tests

- 单元测试 92 项新增/重写（总计 170 passed, 5 skipped），覆盖：
  - `test_domain_models.py`（完全重写，33 项）：ContentUnit（10）/ TagCategory（6）/ Tag（4）/ OperationHistory（5）/ FolderCache（4）/ ManagedRoot（4）。
  - `test_content_unit_repository.py`（新文件，16 项）：create+get_by_id / get_by_path / 中文路径 / path 唯一约束 / id 重复 / list_by_path_prefix / list_all / update / delete。
  - `test_folder_cache_repository.py`（新文件，16 项）：create+get_by_id / get_by_path / 中文路径 / path 唯一约束 / list_by_parent / list_all / upsert_mtime / parent 自引用 / delete。
  - `test_file_scanner.py`（完全重写，11 项）：全量扫描（7：扫描所有子目录、识别内容单元候选、不递归内容单元、中文路径、根不存在、根非目录、空根）+ 增量扫描（3：未变跳过、变更重扫、无缓存全扫）+ 符号链接（1，Windows 权限不足 skip）。
  - `test_scan_service.py`（新文件，11 项）：全量扫描（4：持久化 folder_cache、持久化 content_unit、默认 status、标题为目录名）+ 增量扫描（2：跳过未变、重扫变更）+ 错误（2：root 不存在、路径不存在）+ scan_by_path（1）+ 重复扫描（2：无重复 content_unit、无重复 folder_cache）。
  - `test_scan_worker.py`（完全重写，4 项）：scan_finished 回传 summary / 持久化到 DB / 不存在 root 触发 scan_failed / 增量扫描跳过未变目录。

### 安全限制

- 扫描器严格只读：不移动、不删除、不重命名、不修改、不读取文件内容（仅 iterdir / is_dir / is_file / stat）。
- 符号链接不跟随（避免循环）。
- 单目录扫描失败不中断整体流程。
- ScanWorker 在后台线程创建独立 SQLite 连接，不冻结 UI。
- 扫描期间禁用所有扫描入口与根目录操作按钮。
- UI 不直接访问 Repository 或文件系统（AGENTS 规则 3）。
- 路径、日志、数据库文本编码为 UTF-8。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 49 files already formatted
- `python -m pytest` → 170 passed, 5 skipped

### Not in Scope

- 目录树浏览 UI（Task 3）。
- 内容单元列表与浏览模式（Task 4）。
- 双模式切换（Task 5）。
- 缩略图适配新 schema（Task 4+）。
- 文件操作服务适配新 schema（阶段 3）。
- `thumbnail_coordinator` / `file_operation_service` / `thumbnail_worker` 保留源文件但未接入 main.py，Task 3+ 重新启用。

## [0.10.0] - 2026-07-12

对应 [docs/roadmap.md](docs/roadmap.md) 阶段 2 Task 1（方向 C 重建：新数据库 Schema + 迁移）完成。schema_version 由 3 升至 4。

### Added

- Schema v4 迁移 [src/infrastructure/migrations.py](src/infrastructure/migrations.py)：
  - 新增 `migrate_v3_to_v4(conn)`：方向 C 重建——建立 ContentUnit 体系，移除旧表，重建 thumbnail_cache。
  - 新建 6 张表：`content_unit` / `tag_category` / `tag` / `content_unit_tag` / `operation_history` / `folder_cache`（均 IF NOT EXISTS，幂等）。
  - 新建 8 个索引（content_unit status/path、tag category_id、content_unit_tag 双向、operation_history created_at、folder_cache parent/path）。
  - 重建 `thumbnail_cache`：列名 `asset_id` → `content_unit_id`，FK 由 `file_asset(id)` 改为 `content_unit(id)`（drop + create）。
  - 移除旧表：`operation_log` / `file_asset` / `mod_item` / `folder_node`（drop 顺序遵循 FK 依赖）。
  - 保留 `managed_root` 表与数据不受影响。
  - `CURRENT_SCHEMA_VERSION` 升至 4（[src/infrastructure/db.py](src/infrastructure/db.py)）。
- 应用数据目录改名 [src/app/app_paths.py](src/app/app_paths.py)：
  - `APP_DATA_DIR_NAME` 由 `SkyrimModWorkbench` 改为 `SkyrimContentWorkbench`。
  - docstring 同步更新。
- 单元测试 10 项新增（v4 迁移覆盖）+ 既有测试调整：
  - `test_migrate_v3_to_v4_creates_new_tables`：6 张新表 + 8 个索引。
  - `test_migrate_v3_to_v4_drops_old_tables`：mod_item/file_asset/folder_node/operation_log 移除。
  - `test_migrate_v3_to_v4_idempotent`：连续两次调用幂等。
  - `test_migrate_v3_to_v4_preserves_managed_root_data`：managed_root 数据保留。
  - `test_migrate_v3_to_v4_thumbnail_cache_uses_content_unit_id`：列名 + FK 验证。
  - `test_migrate_v3_to_v4_check_constraints`：operation_type/status CHECK 约束。
  - `test_migrate_v3_to_v4_unicode_support`：中文路径与标签。
  - `test_migrate_v3_to_v4_folder_cache_self_reference_ok`：parent_id 自引用。
  - `test_init_db_migrates_v3_db_to_v4`：完整 v3→v4 升级场景（含 managed_root 中文路径数据保留）。
  - `test_current_schema_version_is_four`：版本断言。
  - 调整：`test_migrations_sorted_by_target` 增加 v4 断言；`test_init_db_migrates_from_v0_to_current` 增加 v4 表存在性断言。

### Changed

- [src/infrastructure/db.py](src/infrastructure/db.py)：`CURRENT_SCHEMA_VERSION` 由 3 升至 4。
- [src/infrastructure/migrations.py](src/infrastructure/migrations.py)：`MIGRATIONS` 注册表新增 v3→v4 迁移。
- [src/app/app_paths.py](src/app/app_paths.py)：`APP_DATA_DIR_NAME` 改为 `SkyrimContentWorkbench`。
- [tests/test_db.py](tests/test_db.py)：`test_init_db_creates_business_tables` 改为断言 v4 新表存在且旧表已移除；`test_init_db_upgrades_from_v0_baseline` 改为断言 `content_unit` 表；`test_init_db_with_v1_db_skips_migration` 重命名为 `test_init_db_at_current_version_skips_migration`。
- [tests/test_app_paths.py](tests/test_app_paths.py)：新增 `APP_DATA_DIR_NAME == "SkyrimContentWorkbench"` 断言。
- [tests/conftest.py](tests/conftest.py)：`temp_app_data` fixture 注释更新为 `SkyrimContentWorkbench`。
- [tests/test_managed_root_repository.py](tests/test_managed_root_repository.py)：`test_delete_preserves_folder_node_and_file_asset` 重写为 `test_delete_preserves_content_unit_and_folder_cache`（引用 v4 新表）。
- [tests/test_managed_root_service.py](tests/test_managed_root_service.py)：`test_add_root_does_not_modify_target_directory` 与 `test_remove_root_does_not_clean_scan_records` 改为引用 `content_unit` / `folder_cache` 表。
- [docs/roadmap.md](docs/roadmap.md)：标记阶段 2 Task 1 完成；更新验收清单。

### Removed

- 删除 9 个纯废弃模块测试文件（依赖已移除的旧表/旧服务，Task 2+ 不再保留）：
  - `tests/test_mod_item_repository.py`
  - `tests/test_file_asset_repository.py`
  - `tests/test_folder_node_repository.py`
  - `tests/test_operation_log_repository.py`
  - `tests/test_mod_assembly_service.py`
  - `tests/test_pool_model.py`
  - `tests/test_main_window.py`
  - `tests/test_file_operation_service.py`
  - `tests/test_thumbnail_ui.py`

### Skipped

- 标记 9 个重写模块测试文件为 module-level skip（Task 2+ 重写后重新启用）：
  - `tests/test_domain_models.py`：domain.models 将在 Task 2 重写为 ContentUnit 等新实体。
  - `tests/test_file_scanner.py` / `test_scan_worker.py` / `test_scan_workflow_service.py`：扫描器将在 Task 2 重写。
  - `tests/test_folder_tree_model.py` / `test_folder_tree_service.py`：目录树将在 Task 3 重写。
  - `tests/test_thumbnail_coordinator.py` / `test_thumbnail_generator.py` / `test_thumbnail_cache.py`：缩略图模块将在 Task 4+ 适配新 schema。

### 安全限制

- 迁移函数仅执行 DDL（CREATE/DROP），不读取或修改用户文件。
- `managed_root` 用户配置数据在迁移中保留；其余旧业务表数据不迁移（roadmap 明确，用户已知）。
- 应用数据目录改名后，旧目录 `%LOCALAPPDATA%\SkyrimModWorkbench\` 下的 app.db 与缩略图缓存不再使用（用户手动删除）。
- 不联网；不读写压缩包内容；不修改用户原始图片。

### Not in Scope

- Domain 模型重写（ContentUnit / Tag / TagCategory 等 dataclass）——Task 2。
- 新 Repository / Service / UI 实现——Task 2+。
- 旧 Repository / Service / UI 源文件删除——Task 2（本次仅处理测试文件）。
- 新扫描器实现——Task 2。
- `python -m app.main` 在 Task 1 完成后仍会失败（因 main.py 仍依赖废弃 Service），属预期，Task 2+ 修复。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 53 files already formatted
- `python -m pytest` → 77 passed, 9 skipped in 2.23s

## [0.9.0] - 2026-07-11

对应 [docs/roadmap.md](docs/roadmap.md) 阶段 2 Task 4（本地缩略图缓存与 ModItem 预览图展示）完成。schema_version 由 2 升至 3。

### Added

- Schema v3 迁移 [src/infrastructure/migrations.py](src/infrastructure/migrations.py)：
  - 新增 `migrate_v2_to_v3(conn)`：创建 `thumbnail_cache` 表（`asset_id` PK / `source_size_bytes` / `source_modified_at` / `cache_filename` / `status` CHECK / `error_message` / `generated_at` / FK→file_asset）；幂等。
  - `CURRENT_SCHEMA_VERSION` 升至 3（[src/infrastructure/db.py](src/infrastructure/db.py)）。
- Repository [src/infrastructure/repositories/thumbnail_cache.py](src/infrastructure/repositories/thumbnail_cache.py)（新文件）：
  - `ThumbnailCacheRecord` dataclass + `ThumbnailCacheRepository`（get_by_asset_id / upsert / delete）。
- 缩略图生成器 [src/infrastructure/thumbnail_generator.py](src/infrastructure/thumbnail_generator.py)（新文件）：
  - `ThumbnailStatus(StrEnum)`：`ok` / `missing` / `corrupt` / `unsupported` / `error`。
  - `ThumbnailGenerator`：延迟导入 Pillow 只读加载源图，生成缩略图写入 `cache_dir`；所有错误转为 ThumbnailResult 返回，不抛异常。
  - 支持格式：JPG/JPEG/PNG/WEBP/GIF/BMP/TIF/TIFF/ICO。
  - `cache_dir` property。
- Application 协调层 [src/application/thumbnail_coordinator.py](src/application/thumbnail_coordinator.py)（新文件）：
  - `ThumbnailInfo` DTO + `ThumbnailCoordinator`：`get_thumbnail_info` / `generate_thumbnail` / `get_cover_thumbnail_info`。
  - 缓存有效性检查（source_size + source_modified_at 匹配）。
  - `cache_dir` property。
- UI 后台 worker [src/app/thumbnail_worker.py](src/app/thumbnail_worker.py)（新文件）：
  - `ThumbnailWorker(QObject)`：在 `run()` 内创建独立 SQLite 连接 + ThumbnailCoordinator，逐个生成缩略图；信号 `thumbnail_ready(str, object)` + `finished()`。
- UI 升级 [src/app/main_window.py](src/app/main_window.py)：
  - 构造签名新增 `thumbnail_coordinator` 参数。
  - 成员表格从 5 列扩展为 6 列（新增封面列）；preview 成员可"设为封面"，非 preview 被拒绝。
  - 详情区新增封面预览 QGroupBox + QLabel。
  - `_request_thumbnail` / `_on_thumbnail_ready` / `_refresh_cover_icons` / `_on_set_cover` / `_load_cover_preview`。
  - `closeEvent` 等待缩略图线程退出。
- UI model [src/app/pool_model.py](src/app/pool_model.py)：
  - `ModItemListModel` 升级：`refresh()` 查询成员数；`data()` 支持 `Qt.DecorationRole`；`set_cover_icon` 方法。
- UI 文案 [src/app/ui_constants.py](src/app/ui_constants.py)：新增封面与缩略图相关常量。
- 应用入口 [src/app/main.py](src/app/main.py)：构造 `ThumbnailCoordinator` 注入 `MainWindow`。
- 依赖 [pyproject.toml](pyproject.toml)：新增 `Pillow>=10.0` 正式运行依赖。
- 单元测试 43 项新增（总计 335 passed, 2 skipped），覆盖：
  - `test_thumbnail_generator.py`（12 项，新文件）：PNG/WEBP/JPG 生成、缓存目录隔离、源文件不变性、中文路径、缺失文件、损坏图片、不支持格式、缩略图尺寸、缓存路径一致性。
  - `test_thumbnail_cache.py`（9 项，新文件）：表存在、schema 版本=3、v3 迁移幂等、upsert+get、upsert 覆盖、get 缺失、delete、delete 幂等、CHECK 约束。
  - `test_thumbnail_coordinator.py`（14 项，新文件）：无缓存记录、asset 不存在、有效缓存、size/mtime 过期、生成成功/缺失/损坏/不支持、源文件不变、中文路径、get_cover_thumbnail_info、缓存命中。
  - `test_thumbnail_ui.py`（9 项，新文件）：ThumbnailWorker 异步生成、设为封面更新成员表、非 preview 被拒绝、列表显示成员数、列表支持封面图标、封面预览 QLabel 存在、成员表格 6 列、设为封面后预览显示、不阻塞主线程。
  - `test_migrations.py`（+1 项，调整 2 项）：MIGRATIONS 含 v3、CURRENT_SCHEMA_VERSION==3、init_db 从 v0 迁移到当前版本、幂等。

### Changed

- [src/infrastructure/db.py](src/infrastructure/db.py)：`CURRENT_SCHEMA_VERSION` 由 2 升至 3。
- [src/infrastructure/migrations.py](src/infrastructure/migrations.py)：`MIGRATIONS` 注册表新增 v2→v3 迁移。
- [src/app/main_window.py](src/app/main_window.py)：构造签名新增 `thumbnail_coordinator`；成员表格 6 列；新增封面预览区与缩略图后台生成逻辑。
- [src/app/pool_model.py](src/app/pool_model.py)：`ModItemListModel` 升级（成员数显示、DecorationRole、set_cover_icon）。
- [src/app/main.py](src/app/main.py)：构造 `ThumbnailCoordinator` 注入 `MainWindow`。
- [src/app/ui_constants.py](src/app/ui_constants.py)：新增封面与缩略图相关常量。
- [pyproject.toml](pyproject.toml)：新增 `Pillow>=10.0` 运行依赖。
- [tests/test_migrations.py](tests/test_migrations.py)：测试名与断言更新为 v3。
- [docs/spec.md](docs/spec.md)：更新 §10 预览图（阶段 2 Task 4 已实现范围）。
- [docs/architecture.md](docs/architecture.md)：更新 §8 缩略图架构（分层、缓存策略、安全约束）。
- [docs/roadmap.md](docs/roadmap.md)：标记 Task 4 完成；更新验收清单。
- [docs/progress.md](docs/progress.md)：新增 Task 4 完成内容；更新验收清单。
- [docs/open-questions.md](docs/open-questions.md)：Q5（缓存失效策略）已关闭、Q13（缩略图命名）已关闭。

### 安全限制

- 只读访问用户原图；不修改、不转换、不压缩、不覆盖。
- 缩略图仅写入 `%LOCALAPPDATA%\SkyrimModWorkbench\thumbnails\`，不写入用户 Mod 目录。
- 不联网；不调用 `FileOperationService`；不读取或解压用户压缩包内容。
- 失败时显示安全占位状态，不尝试"修复"用户文件。
- 缩略图生成在后台线程执行，worker 在自身线程内创建独立 SQLite 连接，不卡死 UI。

### 待确认项

- 关闭 [open-questions.md Q5](docs/open-questions.md)：缩略图缓存失效策略（asset_id + source_size + source_modified_at）。
- 关闭 [open-questions.md Q13](docs/open-questions.md)：缩略图命名（`{asset_id}.png` + thumbnail_cache 表）。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 62 files already formatted
- `python -m pytest` → 335 passed, 2 skipped in 9.97s
- `python -m app.main` → 主窗口正常启动，可设封面、查看缩略图（人工验证步骤见下方）

### 人工验证步骤

1. 扫描含中文路径图片的测试根目录。
2. 将图片关联为 preview 成员。
3. 在成员表格点击"设为封面"。
4. 卡片列表与详情区显示封面缩略图。
5. 重启应用，确认缓存可复用。
6. 修改测试图片后重新打开/刷新，确认缓存失效后重建。
7. 确认原图未变化。

### Not in Scope

未实现：预览图墙、Nexus URL 导入预览图、OCR、图像识别、搜索、AI JSON、拖拽移动、文件监听、增量扫描、压缩包内容解析、自动分组、AI 建议。
本任务不修改 `FileOperationService` 的行为；不修改 `FileScanner` 同步签名。

## [0.6.2] - 2026-07-11

对应阶段 2 Task 1 遗漏补完：移除受管理根目录配置。Task 1 验收标准要求"可移除根目录配置；移除配置不删除、不移动、不修改该目录及其中任何用户文件"，但原实现主动跳过了该项。本次作为 Task 1 遗漏的最小补完。

### Added

- `ManagedRootRepository.delete(root_id)`：按 ID 删除 `managed_root` 记录，实体不存在抛 `NotFoundError`，写操作自提交（与 `create` 一致）。
- `ManagedRootService.remove_root(root_id)`：先校验存在性（抛 `ManagedRootNotFoundError`），再调用 `repo.delete`。
- `MainWindow._on_remove_root()`：左栏「移除选中目录」按钮，弹出确认对话框，用户确认后调用 `service.remove_root` 并刷新列表。
- 按钮状态联动：`_on_selection_changed` / `_begin_scanning` / `_end_scanning` 同步禁用/恢复移除按钮；扫描期间禁用。
- `MainWindow.is_remove_button_enabled()`：测试接口。
- UI 文案：`REMOVE_ROOT_BUTTON` / `REMOVE_ROOT_CONFIRM_TITLE` / `REMOVE_ROOT_CONFIRM_TEXT` / `ERR_REMOVE_ROOT_FAILED`。

### Changed

- [src/application/managed_root_service.py](src/application/managed_root_service.py)：移除模块注释中"本任务不实现删除根目录配置"说明，改为说明移除配置不清理扫描记录。
- [src/infrastructure/repositories/managed_root.py](src/infrastructure/repositories/managed_root.py)：新增 `NotFoundError` 导入。

### Tests

- `test_managed_root_repository.py`（+5 项）：delete 删除记录、delete 自提交、delete 不存在抛 NotFoundError、delete 不影响其他根目录、delete 保留 folder_node/file_asset。
- `test_managed_root_service.py`（+5 项）：remove_root 删除配置、remove_root 不存在抛错、remove_root 保留真实目录与文件（mtime/size 不变）、remove_root 不清理扫描记录、remove_root 自提交。
- `test_main_window.py`（+6 项）：移除按钮无选择禁用、选中启用、初始禁用、确认后从列表消失且真实目录保留、取消确认保留列表、移除后真实目录文件不变、扫描期间禁用。
- 总计 291 passed, 2 skipped（原 266 项，新增 25 项）。

### Constraints

- 仅删除 `managed_root` 记录，不删除、不移动、不修改任何用户文件。
- 不清理 `folder_node` / `file_asset` 扫描记录（清理策略待确认，见 docs/phase-2-plan.md 任务 1 范围外内容）。
- 不修改数据库 schema，不引入新的设计或决策。

## [0.8.1] - 2026-07-11

对应阶段 2 Task 3 缺口修复（素材池布局调整、显示字段补全、新建自动关联、按钮状态联动）。

### Fixed

- **布局调整**：目录树从中栏移至左栏（与受管理根目录列表、扫描状态、目录详情同栏）。中栏改为素材池 + ModItem 列表 + 新建/关联按钮。右栏改为 ModItem 详情编辑 + 成员表格。修复前目录树占据中栏主要空间，素材池可视区域过小。
- **素材池显示字段补全**：`UnassociatedPoolModel._format_display` 从仅显示 `📁 filename` 改为 `📁 filename  (类型)  完整路径`，满足"文件名、类型、完整路径"三项可见字段要求。
- **新建 Mod 条目自动关联**：`_on_new_mod()` 创建 ModItem 后自动将素材池中选中的素材以 `UNKNOWN` 角色关联到新条目。修复前创建 ModItem 后不关联任何素材，用户需额外手动关联。
- **新建按钮状态联动**：新增 `_update_new_mod_button()` 和 `_on_pool_selection_changed()`。「新建 Mod 条目」按钮在素材池无选择时禁用；素材池选择变化时同步更新「新建」和「关联」按钮状态。修复前「新建」按钮始终启用。

### Added

- `test_pool_model_display_includes_type_and_path`：文件型素材显示包含类型和完整路径。
- `test_pool_model_display_folder_includes_type_and_path`：文件夹型素材显示包含类型和完整路径。
- `test_main_window_new_mod_button_disabled_without_pool_selection`：素材池无选择时「新建」按钮禁用，选中后启用。
- `test_main_window_new_mod_auto_associates_selected_assets`：新建 ModItem 自动关联选中素材。
- `test_main_window_pool_display_shows_full_path`：素材池显示文本包含完整路径。

### Changed

- [src/app/main_window.py](src/app/main_window.py)：`_setup_ui` 重构三栏布局；新增 `_update_new_mod_button` / `_on_pool_selection_changed`；`_on_new_mod` 增加自动关联逻辑；`_refresh_pool` 增加新建按钮状态更新。
- [src/app/pool_model.py](src/app/pool_model.py)：`_format_display` 增加类型和完整路径。
- [docs/spec.md](docs/spec.md)：更新 §8 UI 结构描述。
- [docs/architecture.md](docs/architecture.md)：更新 §2.4 写入链路与边界约定。
- [docs/progress.md](docs/progress.md)：新增 Task 3 缺口修复内容。

## [0.8.0] - 2026-07-11

对应 [docs/roadmap.md](docs/roadmap.md) 阶段 2 Task 3（未归类素材池与人工 Mod 条目组装）完成。

### Added

- Application 层查询入口 [src/application/mod_assembly_service.py](src/application/mod_assembly_service.py)：
  - `list_unassociated_assets()`：委托 `FileAssetRepository.list_unassociated()`，返回 `mod_item_id` 为 `NULL` 的 `FileAsset` 列表，供 UI 素材池展示。不复制关联规则到 UI；`ROLE_LIMITS` 仍为唯一规则源。
- UI model [src/app/pool_model.py](src/app/pool_model.py)（新文件）：
  - `UnassociatedPoolModel(QAbstractListModel)`：包装未关联 `FileAsset` 列表，显示 `📁 filename` / `📄 filename`，tooltip 显示完整路径；`refresh()` 重置；多选支持。
  - `ModItemListModel(QAbstractListModel)`：包装 `ModItem` 列表，显示 `display_name` 或"(未命名)"；`refresh()` 重置。
  - `ROLE_DISPLAY_NAMES` / `ROLE_ORDER`：角色中文显示名与下拉顺序，集中定义；角色数量限制仍由 `ModAssemblyService.ROLE_LIMITS` 强制，UI 不复制规则。
  - 错误隔离：捕获查询异常，记录日志并降级为空列表。
  - 测试接口：`asset_at` / `asset_id_at` / `asset_count` / `mod_item_at` / `mod_item_id_at` / `item_count`。
- UI 文本常量 [src/app/ui_constants.py](src/app/ui_constants.py)：新增素材池、ModItem 列表、详情编辑、成员表格、角色中文名、操作按钮与错误提示常量。
- 主窗口重写 [src/app/main_window.py](src/app/main_window.py)：
  - 构造签名新增 `mod_assembly_service` 参数。
  - 中栏：素材池 `QListView`（ExtendedSelection）+ ModItem 列表 `QListView`（SingleSelection）+ 新建 Mod 条目按钮 + 关联到选中条目按钮。
  - 右栏：ModItem 详情编辑表单（显示名称 QLineEdit / 说明 QTextEdit / 来源链接 QLineEdit / 标签 QLineEdit + 保存元数据按钮）+ 成员表格 `QTableWidget`（文件名/类型/角色下拉 QComboBox/路径/移除按钮 QPushButton）。
  - `_on_new_mod()`：QInputDialog 输入名称创建 ModItem，刷新列表并选中新条目。
  - `_on_associate()`：多选素材以 `UNKNOWN` 角色关联到当前 ModItem，展示错误。
  - `_on_role_changed(asset_id)`：通过 `self.sender()` 获取 QComboBox，调用 `set_member_role`；展示 `MemberLimitError` / `DuplicateMemberError`。
  - `_on_remove_member(asset_id)`：调用 `remove_member`，刷新成员表和素材池。
  - `_on_save_metadata()`：保存名称/说明/URL/标签（中文逗号分隔标签）。
  - 扫描完成/失败后调用 `_refresh_pool()`，新扫描的未关联素材进入素材池。
  - 测试接口：`pool_count()` / `mod_list_count()` / `mod_detail_name()` / `members_table_row_count()`。
- 应用入口 [src/app/main.py](src/app/main.py)：构造 `ModAssemblyService` 注入 `MainWindow`。
- 单元测试 22 项新增（总计 266 passed, 2 skipped），覆盖：
  - `test_mod_assembly_service.py`（+3 项）：`list_unassociated_assets` 基础（3 未关联 + 2 已关联）、中文名素材、文件夹型素材。
  - `test_pool_model.py`（13 项，新文件）：素材池空/显示未关联/关联后消失/解除后重现/中文文件名/文件夹类型/文件 tooltip；ModItem 列表空/显示条目/未命名显示/创建后刷新/中文标签 tooltip。
  - `test_main_window.py`（+6 项）：素材池初始空、扫描后显示未关联素材、创建 ModItem 并关联、移除成员回到素材池、元数据保存持久化、无选择时关联保护。

### Changed

- [src/app/main_window.py](src/app/main_window.py)：构造签名新增 `mod_assembly_service` 参数；中栏新增素材池与 ModItem 列表；右栏新增 ModItem 详情编辑与成员表格。
- [src/app/main.py](src/app/main.py)：构造 `ModAssemblyService` 注入 `MainWindow`。
- [src/app/ui_constants.py](src/app/ui_constants.py)：新增素材池、ModItem 列表、详情编辑、成员表格、角色中文名与错误提示常量。
- [tests/test_main_window.py](tests/test_main_window.py)：适配新构造签名（注入 `ModAssemblyService`），扩展 6 项 Task 3 测试。
- [docs/spec.md](docs/spec.md)：新增 §5.5 未归类素材池与人工 Mod 条目组装（15 条行为规范）；更新 §8 UI 结构反映 Task 3 实现。
- [docs/architecture.md](docs/architecture.md)：新增 §2.4 素材池与 Mod 组装 UI model/view 边界（写入链路、边界约定）；更新 §3 application 层职责；扩展 §11 测试策略。
- [docs/roadmap.md](docs/roadmap.md)：标记 Task 3 完成；更新验收清单。
- [docs/open-questions.md](docs/open-questions.md)：更新 Q11 实现现状（不关闭未决部分）；Q19 保持不变。
- [docs/progress.md](docs/progress.md)：新增 Task 3 完成内容；更新验收清单。

### Fixed（阶段 2 Task 2 验收修复，自 v0.7.0 起）

- **目录树启动崩溃（无限递归）**：`FolderTreeModel._fetch` 在
  [src/app/folder_tree_model.py](src/app/folder_tree_model.py) 中调用
  `beginInsertRows` **之后**才设置 `_loaded` 标记与 `_children_cache`。
  `beginInsertRows` 同步触发 view 查询 `rowCount`，而 `rowCount` 检查
  `_loaded` 未设置又调用 `_fetch`，形成无限递归直至 `RecursionError`。
  当 `%LOCALAPPDATA%\SkyrimModWorkbench\app.db` 中已有 Task 1 验收时
  残留的扫描数据时，启动即崩溃。修复（`_fetch` 方法）：
  - 开头加 `if parent_node_id in self._loaded: return` 重入保护；
  - `_children_cache` 与 `_loaded` 赋值移到 `beginInsertRows` **之前**；
  - 空子节点跳过 `beginInsertRows`/`endInsertRows`（避免
    `beginInsertRows(idx, 0, 0)` 误报"插入 1 行"）。
- **扫描结果未持久化导致目录树始终"未扫描"**：
  `ScanWorker.run` 在 [src/app/scan_worker.py](src/app/scan_worker.py) 中
  调用 `service.scan_root` 后直接 `conn.close()`，未调用 `conn.commit()`。
  而 `persist_scan_result` 与 `FolderNodeRepository.create` /
  `FileAssetRepository.create` 均不自提交事务（与 `ManagedRootRepository.create`
  不同），导致扫描结果在连接关闭时被 SQLite 回滚。修复：
  在 `scan_root` 返回后、`scan_finished.emit` 前调用 `conn.commit()`。
  不修改 `ScanWorkflowService`、Repository 接口或事务策略。
- **技术债记录**：`rowCount` 中的副作用（未加载时调用 `_fetch`）记录为
  open question Q21，本次不调整加载策略，仅缓解递归。
  `persist_scan_result` 不自提交仍为已知遗留问题（v0.6.0 起记录），
  本次仅在 `ScanWorker` 层补提交，不统一 Repository 写操作提交策略。
- `test_fetch_does_not_recurse_when_connected_to_view`：model 连接真实
  `QTreeView` 后 `fetchMore` 不触发 `RecursionError`（[tests/test_folder_tree_model.py](tests/test_folder_tree_model.py)）。
- `test_fetch_empty_children_does_not_emit_rows_inserted`：空子节点
  不发 `rowsInserted` 信号（[tests/test_folder_tree_model.py](tests/test_folder_tree_model.py)）。
- `test_fetch_sets_loaded_before_begin_insert_rows`：通过
  `rowsAboutToBeInserted` 信号中查询 `rowCount` 验证 `_loaded` 顺序，
  确保重入不递归（[tests/test_folder_tree_model.py](tests/test_folder_tree_model.py)）。
- `test_scan_worker_persists_results_to_db`：扫描完成后用独立连接验证
  `folder_node` 与 `file_asset` 表非空，确保事务已提交（[tests/test_scan_worker.py](tests/test_scan_worker.py)）。
- `test_main_window_tree_refresh_after_scan`：扫描完成后新增验证根节点
  不再显示"未扫描"且可展开有子节点（[tests/test_main_window.py](tests/test_main_window.py)）。
  修复前该测试仅验证 `tree_root_count() == 1`，漏掉了数据未持久化的场景。

### 安全限制

- 本任务严格只读用户文件：不调用 `FileOperationService` 的任何方法。
- 关联/移除成员只写应用数据库 `file_asset` 表（`mod_item_id` / `role` 字段），不移动、不复制、不删除、不重命名任何用户文件。
- 不生成缩略图、不读取图片内容、不把用户文件复制进应用数据目录。
- 素材池数据源严格为 SQLite `file_asset` 表；不在 UI 线程重新扫描文件系统。
- UI 不直接访问 SQLite connection 或 Repository；所有写操作通过 `ModAssemblyService`。
- 路径、日志、数据库文本编码为 UTF-8。

### 待确认项

- 本任务未触及新的 open question。
- Q11（未归类素材如何移出素材池）：更新实现现状（`UnassociatedPoolModel` 列出未关联素材，不实现忽略/删除/移出机制），长期处置策略保留未决。
- Q19（成员角色数量限制）：保持不变（`MAIN_MOD≤1`、`README≤1`，其他不限），UI 直接展示服务层返回的错误。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 54 files already formatted
- `python -m pytest` → 266 passed, 2 skipped in 8.64s
- `python -m app.main` → 主窗口正常启动，三栏布局，可添加目录、扫描、浏览目录树、选中节点查看详情、素材池多选、创建 ModItem、关联素材、编辑角色、移除成员、编辑元数据（人工验证步骤见下方）

### 人工验证步骤

1. 运行 `python -m app.main`，主窗口显示三栏布局：左栏「受管理根目录」+ 按钮、中栏「目录树」+ 素材池 + ModItem 列表 + 按钮、右栏「扫描状态」+ 目录详情 + ModItem 详情编辑 + 成员表格。
2. 添加并扫描一个包含本体压缩包、汉化压缩包、图片和说明文件的测试目录。
3. 扫描完成后，中栏素材池应显示所有未关联素材（文件 📄 / 文件夹 📁），tooltip 显示完整路径。
4. 在素材池多选素材，点击「新建 Mod 条目」，输入名称后创建；新条目自动选中并出现在 ModItem 列表中。
5. 选中素材后点击「关联到选中条目」，素材从素材池消失，出现在右栏成员表格。
6. 在成员表格中通过角色下拉框为每个成员指定角色（本体/汉化/预览图/说明/可选文件/未知）；角色超限时展示错误。
7. 在右栏 ModItem 详情编辑表单中填写显示名称、说明、来源链接、标签（中文逗号分隔），点击「保存元数据」。
8. 关闭应用后重新运行，确认关联、角色、标签、描述仍存在。
9. 在成员表格中点击某成员的「移除」按钮，该素材回到素材池；真实文件未被移动或删除。
10. 中文文件名、中文显示名、中文标签全程正确显示。

### Not in Scope

未实现：封面设置 UI、缩略图生成与图片预览、搜索、AI JSON 导入导出、拖拽移动、真实文件移动、批量下载批次、ModItem.status、忽略/删除/移出素材池机制、压缩包内容解析、自动分组、AI 建议。
本任务不修改 `FileOperationService` 的行为；不修改 `FileScanner` 同步签名；不修改数据库 schema（沿用 v2）。

## [0.7.0] - 2026-07-09

对应 [docs/roadmap.md](docs/roadmap.md) 阶段 2 Task 2（只读目录树视图）完成。

### Added

- Repository 查询扩展 [src/infrastructure/repositories/folder_node.py](src/infrastructure/repositories/folder_node.py)：
  - `list_all()`：返回全部 FolderNode，按 `real_path` 排序。
  - `get_by_path_key(path_key)`：按 `path_key` 查询，用于 `ManagedRoot` 与 `FolderNode` 关联。
  - `count_children(parent_id)`：返回直接子目录数量（不含文件、不含孙节点）。
- Application 层只读目录树查询服务 [src/application/folder_tree_service.py](src/application/folder_tree_service.py)：
  - `TreeNode` dataclass：node_id / display_name / real_path / category（`managed_root` / `unscanned_root` / `folder`）/ is_managed_root / managed_root_id / folder_node_id / parent_id。
  - `FolderTreeService`：`list_root_nodes()` 合并 `ManagedRoot` 配置与 `FolderNode` 扫描根；`list_children(node_id)` 按 node_id 前缀（`mr:` / `fn:`）分发查询；`get_node(node_id)` / `count_children(node_id)` / `has_scan_data(managed_root_id)`。
  - `ManagedRoot` 与 `FolderNode` 通过 `path_key` 关联（`get_by_path_key`），不在 UI 层散落字符串匹配。
  - `display_name` 回退：`FolderNode.display_name` 为 None 时用 `PurePath(real_path).name`。
  - 不访问文件系统、不写数据库、不调用 `FileOperationService`。
- Qt 目录树 model [src/app/folder_tree_model.py](src/app/folder_tree_model.py)：
  - `FolderTreeModel(QAbstractItemModel)`：惰性加载（`canFetchMore` / `fetchMore`），`refresh()` 重置顶层。
  - 节点内部 ID：`"mr:<managed_root_id>"` / `"fn:<folder_node_id>"`，通过 `internalPointer` 往返。
  - 错误隔离：捕获查询异常，记录日志并降级为空子树，不让整个树崩溃。
  - 测试接口：`node_at(index)` / `node_id_at(index)` / `root_node_count()`。
- UI 文本常量 [src/app/ui_constants.py](src/app/ui_constants.py)：新增目录树与详情区常量（TREE_GROUP_TITLE / TREE_EMPTY_HINT / TREE_UNSCANNED_HINT / DETAIL_*）。
- 主窗口重写 [src/app/main_window.py](src/app/main_window.py)：
  - 构造签名新增 `folder_tree_service` 参数。
  - 三栏 QSplitter 布局：左栏根目录列表+按钮；中栏目录树（QTreeView，headerHidden / NoEditTriggers / NoDragDrop）+素材池占位；右栏扫描状态+选中目录详情。
  - `_refresh_tree()`：扫描完成/根目录变更后刷新 `FolderTreeModel`，更新空状态提示。
  - `_on_tree_selection_changed` → `_update_detail`：选中节点显示目录名称/完整真实路径/是否受管理根目录/类型/直接子目录数量；未扫描根目录追加"（未扫描）"提示。
  - 测试接口：`detail_text()` / `tree_root_count()`。
- 应用入口 [src/app/main.py](src/app/main.py)：构造 `FolderTreeService` 注入 `MainWindow`。
- 单元测试 34 项新增（总计 241 passed, 2 skipped），覆盖：
  - folder_node_repository（+4 项）：list_all 排序与空表、get_by_path_key 中文路径、count_children 直接子目录数与孙节点不计入。
  - folder_tree_service（16 项）：空数据、未扫描根显示为 unscanned_root、已扫描根显示为 managed_root、中文目录名、空目录、多层层级 parent_id 链、多根目录、重复扫描不重复、重叠根去重（子根显示为 unscanned_root）、get_node managed_root/folder/无效 ID、list_children 无效 ID、count_children 无效 ID、TreeNode category 校验、重新连接数据库后树可加载。
  - folder_tree_model（11 项）：空 model、顶层节点、惰性加载 fetchMore、父子关系 parent()、深层 index 链访问、node_at 返回 TreeNode、node_id_at、refresh 重置、无效 index 返回 None、中文显示名。
  - main_window（+4 项）：包含树视图、未扫描根目录显示提示、选中节点后详情区更新、扫描完成后树刷新。

### Fixed（阶段 2 Task 1 验收修复，自 v0.6.0 起）

- **根目录配置未持久化**：`ManagedRootRepository.create` 未调用 `conn.commit()`，应用关闭后数据丢失，重启后已添加的根目录不可见。修复：`create` 在 INSERT 成功后自提交事务（[src/infrastructure/repositories/managed_root.py](src/infrastructure/repositories/managed_root.py)）。
- **扫描完成进程 CTD**：`MainWindow._end_scanning` 在 `thread.quit()` 生效前清空 `self._thread` 引用，QThread 在 `Running` 状态被析构导致 `QThread: Destroyed while thread is still running`，扫描完成后约 3 秒内进程崩溃。修复（[src/app/main_window.py](src/app/main_window.py)）：
  - `_end_scanning` 不再清空 `_worker` / `_thread` 引用；新增 `_on_thread_finished`（由 `thread.finished` 信号触发）负责清空，确保 QThread 在 `Finished` 状态下被析构。
  - 调整信号连接顺序：先连 `thread.quit`，再连 UI 处理槽，确保 quit 先入队。
  - 新增 `MainWindow.closeEvent`：扫描中关窗时调用 `thread.quit()` + `wait(5000)` 等待线程退出，避免同类 CTD。
- `test_create_commits_transaction_without_explicit_commit`：验证 repo 自提交（[tests/test_managed_root_repository.py](tests/test_managed_root_repository.py)）。
- `test_add_root_persists_without_explicit_commit`：验证 service 自提交（[tests/test_managed_root_service.py](tests/test_managed_root_service.py)）。
- `test_main_window_scan_completes_without_crash`：扫描完成线程安全退出回归测试（[tests/test_main_window.py](tests/test_main_window.py)）。
- `test_main_window_close_event_safe_when_idle`：closeEvent 空闲路径测试（[tests/test_main_window.py](tests/test_main_window.py)）。

### Changed

- [src/app/main_window.py](src/app/main_window.py)：从单栏根目录/扫描区域重写为三栏布局（左栏根目录列表+按钮、中栏目录树+素材池占位、右栏扫描状态+详情区）；构造签名新增 `folder_tree_service`。
- [src/app/main.py](src/app/main.py)：构造 `FolderTreeService` 注入 `MainWindow`。
- [src/app/ui_constants.py](src/app/ui_constants.py)：新增目录树与详情区常量。
- [src/infrastructure/repositories/folder_node.py](src/infrastructure/repositories/folder_node.py)：新增 `list_all` / `get_by_path_key` / `count_children` 只读查询方法。
- [tests/test_folder_node_repository.py](tests/test_folder_node_repository.py)：扩展 4 项新查询方法测试。
- [tests/test_main_window.py](tests/test_main_window.py)：适配新构造签名，扩展 4 项目录树测试。

### 安全限制

- 本任务严格只读：不调用 `FileOperationService.execute_move` / `execute_undo` 或任何文件写 API。
- 目录树数据源严格为 SQLite `FolderNode`；不在 UI 线程临时递归真实文件系统。
- `FolderTreeService` / `FolderTreeModel` / Repository 查询均不调用 `Path.rename` / `unlink` / `shutil` / `FileOperationService.execute_*`。
- 不重新扫描真实目录来填充树；不修改用户文件或目录；不将目录树缓存写回用户目录。
- 路径、日志、数据库文本编码为 UTF-8。

### 待确认项

- 本任务未触及新的 open question；Q3（移动入口）保持未决（本任务不实现移动入口）。
- 重叠根目录展示策略已在本任务中确定为：子根因 `path_key` 已被父根扫描覆盖时显示为"未扫描"虚拟节点（spec §5.4 第 9 条、architecture §2.3）。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 52 files already formatted
- `python -m pytest` → 241 passed, 2 skipped in 7.28s
- `python -m app.main` → 主窗口正常启动，三栏布局，可添加目录、扫描、浏览目录树、选中节点查看详情（人工验证步骤见下方）

### 人工验证步骤

1. 运行 `python -m app.main`，主窗口显示三栏布局：左栏「受管理根目录」+ 按钮、中栏「目录树」+ 素材池占位、右栏「扫描状态」+ 详情区。
2. 点击「添加目录」，选择一个含中英文目录与空目录的测试根目录，目录应出现在左侧列表。
3. 选中根目录，点击「扫描选中目录」，扫描完成后中栏目录树应显示根目录及其子目录。
4. 展开树节点，确认空目录正常显示，中文目录名正确。
5. 选中深层目录，右栏详情区应显示目录名称、完整路径、是否为根、类型、子目录数量。
6. 关闭应用后重新运行，目录树应从已持久化的扫描数据加载，无需重新扫描。
7. 添加一个新根目录但不扫描，树中应显示该根目录为"未扫描"。

### Not in Scope

未实现：拖拽移动、右键文件操作、文件系统写入、文件监听、自动刷新、搜索、缩略图、ModItem 卡片、AI JSON、未关联素材池数据展示、ModItem 列表、移动预演/确认/撤销 UI、删除根目录配置、目录树缓存写回用户目录。
本任务不修改 `FileOperationService` 的行为；不修改 `FileScanner` 同步签名；不改变 `path_key` 语义。

## [0.6.0] - 2026-07-07

对应 [docs/roadmap.md](docs/roadmap.md) 阶段 2 Task 1（工作台骨架与根目录扫描）完成。schema_version 由 1 升至 2。

### Added

- Schema v2 迁移 [src/infrastructure/migrations.py](src/infrastructure/migrations.py)：
  - 新增 `migrate_v1_to_v2(conn)`：创建 `managed_root` 表（`id` / `real_path` / `path_key` UNIQUE / `display_name` / `created_at` / `updated_at`）+ 索引 `idx_managed_root_path_key`。
  - `MIGRATIONS` 注册表新增 `(2, migrate_v1_to_v2)`；迁移函数幂等（CREATE TABLE IF NOT EXISTS）。
  - `CURRENT_SCHEMA_VERSION` 升至 2（[src/infrastructure/db.py](src/infrastructure/db.py)）。
  - v1→v2 迁移不修改既有业务表，不丢失已有数据。
- 领域模型 [src/domain/models.py](src/domain/models.py)：新增 `ManagedRoot` dataclass（spec §6.5），`__post_init__` 校验必填字段。
- Repository [src/infrastructure/repositories/managed_root.py](src/infrastructure/repositories/managed_root.py)：
  `ManagedRootRepository`（create / get_by_id / get_by_path_key / list_all）。
  不访问文件系统；real_path 仅作为字符串存储；path_key 唯一约束冲突抛 `ConstraintViolationError`。
- Application 层错误 [src/application/errors.py](src/application/errors.py)：
  新增 `ManagedRootNotFoundError` / `DuplicateManagedRootError` / `InvalidRootPathError`。
- 受管理根目录服务 [src/application/managed_root_service.py](src/application/managed_root_service.py)：
  - `ManagedRootService.add_root(real_path)`：只读校验路径存在+是目录（`Path.exists` / `Path.is_dir`），path_key 去重，display_name=目录名。
  - `list_roots()` / `get_root(root_id)`。
  - 不扫描、不移动、不复制、不修改该目录或其中任何用户文件。
  - 可注入 `now_provider` / `uuid_provider`。
- 扫描工作流服务 [src/application/scan_workflow_service.py](src/application/scan_workflow_service.py)：
  - `ScanSummary` dataclass：root_id / root_path / scanned_folders / scanned_files / persisted_folders / persisted_files / skipped_folders / skipped_files / error_count / errors；`is_success` property。
  - `ScanWorkflowService.scan_root(root_id)` / `scan_root_by_path(real_path)`：读取 ManagedRoot，调用 `FileScanner.scan()` + `persist_scan_result()`，返回 `ScanSummary`。
  - 不修改 `FileScanner` 同步签名；不访问 UI；仅写应用数据库。
  - 根目录不存在/非目录时返回含错误的 `ScanSummary`（error_count > 0），不抛异常。
- Qt 后台扫描 worker [src/app/scan_worker.py](src/app/scan_worker.py)：
  - `ScanWorker(QObject)`：信号 `scan_started` / `scan_progress(str)` / `scan_finished(ScanSummary)` / `scan_failed(str)`。
  - `run()` 在 worker 所在线程内创建独立 SQLite 连接（`get_connection(db_path)`），不与主线程连接共享。
  - 捕获所有异常转为 `scan_failed` 信号，不向调用线程抛出。
  - 本任务不提供取消机制（Q18 未决部分）。
- UI 文本常量 [src/app/ui_constants.py](src/app/ui_constants.py)：
  集中定义窗口标题、按钮文本、状态文本、错误消息、占位区提示、`format_summary()` 函数。
- 主窗口重写 [src/app/main_window.py](src/app/main_window.py)：
  - `MainWindow(managed_root_service, db_path, parent=None)` 构造注入，便于测试。
  - 布局：QSplitter 水平分割——左侧「受管理根目录」区域（QListWidget + 添加目录按钮 + 扫描选中目录按钮），右侧扫描状态区域 + 三占位 GroupBox（目录树/素材池/详情，本任务不实现数据展示）。
  - 添加目录：`QFileDialog.getExistingDirectory` 选择目录，调用 `ManagedRootService.add_root()`；重复路径 / 路径不存在 / 路径非目录均展示用户可读错误。
  - 扫描：选中根目录后点击按钮，创建 `QThread` + `ScanWorker` 后台执行；扫描期间禁用「扫描选中目录」与「添加目录」按钮，显示「扫描中…」状态。
  - 扫描完成：展示摘要（扫描目录数/文件数/持久化目录数/文件数/错误数）；若有错误展示前 5 条错误摘要（路径与原因）。
  - 扫描失败：展示用户可读错误信息。
  - 测试接口：`status_text()` / `root_count()` / `is_scan_button_enabled()`。
- 应用入口 [src/app/main.py](src/app/main.py)：构造主线程 SQLite 连接，构造 `ManagedRootService` 注入 `MainWindow`；退出时关闭连接。
- 单元测试 38 项新增（总计 203 项），覆盖：
  - managed_root_repository（7 项）：创建与读取、中文路径、path_key 查询、path_key 唯一约束、list_all 排序、重启后读取、不存在 id 返回 None。
  - managed_root_service（10 项）：添加合法目录、中文路径、拒绝不存在路径、拒绝非目录路径、拒绝重复、不修改目标目录、list_roots 空/非空、get_root 存在/不存在。
  - scan_workflow_service（7 项）：成功结果回传、持久化验证、scan_root_by_path、缺失目录错误回传、未知 root_id 抛错、scan_root_by_path 未知路径抛错、ScanSummary.is_success 逻辑。
  - scan_worker（4 项）：成功 scan_finished 信号回传、缺失目录错误摘要回传、未知 root_id scan_failed 信号、worker 创建独立连接（主线程连接关闭后仍可扫描）。
  - migrations（10 项，原 3 项扩展）：CURRENT_SCHEMA_VERSION=2、v1→v2 创建 managed_root 表与索引、列结构、幂等、path_key 唯一约束、init_db 从 v0 迁移到 v2、init_db 在 v2 上幂等。
  - main_window（5 项，原 1 项重写）：构造与初始状态、已保存根目录显示、无选择时扫描按钮禁用、选中后启用、状态文本可读。

### Changed

- [src/infrastructure/db.py](src/infrastructure/db.py)：`CURRENT_SCHEMA_VERSION` 由 1 升至 2。
- [src/infrastructure/migrations.py](src/infrastructure/migrations.py)：`MIGRATIONS` 注册表新增 v1→v2 迁移。
- [src/domain/models.py](src/domain/models.py)：末尾新增 `ManagedRoot` dataclass。
- [src/app/main_window.py](src/app/main_window.py)：从空窗口重写为带根目录配置与扫描区域的工作台骨架；构造签名变更（需注入 `ManagedRootService` + `db_path`）。
- [src/app/main.py](src/app/main.py)：构造 `ManagedRootService` 并注入 `MainWindow`。
- [tests/test_main_window.py](tests/test_main_window.py)：适配新构造签名，扩展为 5 项测试。
- [tests/test_migrations.py](tests/test_migrations.py)：扩展为覆盖 v1→v2 迁移。

### 安全限制

- 本任务不调用 `FileOperationService.execute_move` / `execute_undo` 或任何文件写 API。
- 扫描仅使用只读文件系统 API（`Path.iterdir` / `is_dir(follow_symlinks=False)` / `stat(follow_symlinks=False)` / `suffix`）。
- 添加根目录配置仅写应用数据库 `managed_root` 表；不移动、不复制、不修改该目录。
- 不将用户 Mod 文件复制进应用数据目录。
- 日志写入 `%LOCALAPPDATA%\SkyrimModWorkbench\logs\app.log`，不写入用户目录。
- 路径、日志、数据库文本编码为 UTF-8。

### 待确认项

- 关闭 [open-questions.md Q18](docs/open-questions.md) 扫描并发与取消模型（阶段 2 部分决策：Qt 后台线程包裹同步扫描器，不提供取消；取消机制保留未决）。
- ManagedRoot 与 FolderNode.is_managed_root 的关系已在架构文档明确（D1 决策）：ManagedRoot 是用户配置，FolderNode.is_managed_root 是扫描结果标记；移除 ManagedRoot 不自动清理 FolderNode（清理策略待确认）。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 48 files already formatted
- `python -m pytest` → 203 passed, 2 skipped in 114.80s
- `python -m app.main` → 主窗口正常启动，可添加目录、扫描、查看结果（人工验证步骤见下方）

### 人工验证步骤

1. 运行 `python -m app.main`，主窗口应显示非空白布局：左侧「受管理根目录」区域，右侧「扫描状态」+ 三占位区。
2. 点击「添加目录」，选择一个本地目录，目录应出现在左侧列表。
3. 关闭应用后重新运行，已保存的根目录应仍在列表中。
4. 选中根目录，点击「扫描选中目录」，状态应显示「正在扫描…」，扫描期间按钮禁用。
5. 扫描完成后，状态区域应显示扫描目录数/文件数/持久化数/错误数。
6. 选择一个不存在的目录路径配置（需通过手动修改 DB 或先配置后删除目录），扫描应显示错误摘要。
7. 验证扫描前后用户文件未被修改（mtime/size 不变）。

### Not in Scope

未实现：删除根目录配置、目录树数据展示、素材池、ModItem 列表与详情、移动预演/确认/撤销 UI、搜索、AI JSON、缩略图、文件监听、增量扫描、取消扫描、压缩包内容解析。
本任务不修改 `FileScanner` 同步签名；不调用 `FileOperationService` 的任何方法。

## [0.5.0] - 2026-07-07

对应 [docs/roadmap.md](docs/roadmap.md) Task 5（安全移动预演与执行服务）完成。阶段 1（安全数据与文件操作基础）全部验收通过。

### Added

- 统一文件操作服务 [src/infrastructure/file_operation_service.py](src/infrastructure/file_operation_service.py)：
  唯一允许修改用户文件位置的模块（arch §6）。
  - `FileOperationService` 协调 ModItem / FileAsset / FolderNode / OperationLog 四个 Repository。
  - `plan_move(mod_item_id, target_folder_id) -> MovePlan`：生成移动预演并持久化
    `OperationLog(status=PLANNED)`。预演检查每个成员的源存在性、目标目录存在性、
    目标重名（B3：重名即阻止）、目标目录可写性、目标是否为源自身或子目录（spec §7.7）、
    是否跨盘。`can_execute` 仅在全部成员可执行时为 True。
  - `execute_move(plan_id) -> OperationResult`：校验 status=planned → 更新为 confirmed
    → 同盘 `Path.rename`（spec §7.8 原子）/ 跨盘 `shutil.copy2 + Path.unlink`
    （spec §7.9）→ 单成员失败不中断其他成员（spec §7.12）→ status=completed/failed
    + 写 undo_payload（Q14）。
  - `plan_undo(operation_id) -> UndoPlan`：B1 不安全即整体阻止；B2 跨盘撤销校验
    目标文件 size + mtime 与 undo_payload 记录一致。
  - `execute_undo(undo_plan_id) -> OperationResult`：先调用 plan_undo 重新验证
    （B1），不安全则直接返回失败；安全则反向移动 + status=undone。
  - 数据类：`MovePlan` / `MovePlanEntry` / `UndoPlan` / `UndoPlanEntry` / `OperationResult`。
  - `undo_payload` JSON 结构（Q14 由本任务定义）：
    `{version:1, members:[{asset_id, src_path, dst_path, size_bytes, mtime_iso}]}`。
  - 可注入 `now_provider` / `uuid_provider`，便于测试。
  - 执行后更新 FileAsset.real_path / path_key / modified_at 以反映新位置。
- 单元测试 23 项新增（总计 165 项），覆盖：
  - plan_move：正常、源缺失阻止、目标重名阻止、目标目录不存在阻止、
    子目录非法阻止、空 ModItem、ModItem 不存在、OperationLog 持久化为 planned。
  - execute_move：同盘单成员、同盘多成员、部分成员失败不中断、
    拒绝非 planned 状态、中文路径往返、undo_payload 记录 size+mtime、
    不删除用户文件（spec §7.13）。
  - plan_undo：正常、原目标文件缺失阻止、原源路径已占用阻止、
    size 不一致阻止（B2）、mtime 不一致阻止（B2）、非 completed/failed 拒绝。
  - execute_undo：正常往返、拒绝不安全撤销（B1）。
  - 完整场景：move + undo 往返验证文件回到原位。

### 安全限制

- UI 层不直接调用 shutil / Path.rename（AGENTS 规则 3）。
- 所有移动必须先 plan_move 生成预演并持久化为 planned（AGENTS 规则 4）。
- 所有移动支持撤销预演与安全撤销执行（AGENTS 规则 5）。
- 重名即阻止，不覆盖（B3）。
- 禁止移到源自身或子目录（spec §7.7）。
- 不删除用户文件（spec §7.13）；不修改文件内容（spec §7.14）。
- 撤销前强制重新验证文件状态（B1）；跨盘撤销校验 size+mtime（B2）。

### 无法原子回滚的情况

- 跨盘移动采用 copy2+unlink，原文件已删除；撤销为反向 copy2+unlink，
  依赖 undo_payload 中记录的 size+mtime 校验目标文件未被外部改动（B2）。
- 部分成员失败时已成功成员不自动回滚（Q20，决策里程碑=阶段 2）；
  OperationLog.status=failed，用户可手动执行 plan_undo + execute_undo。

### 待确认项

- 新增 [open-questions.md Q20](docs/open-questions.md#L171-L184)：部分失败时的回滚策略。
- 关闭 Q14（undo_payload 结构由本任务定义）。
- 关闭 Q16（OperationType 仅 {move, undo}，Task 5 未引入新值）。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 39 files already formatted
- `python -m pytest tests/test_file_operation_service.py -v` → 23 passed
- `python -m pytest` → 165 passed, 2 skipped

### Not in Scope

未实现：UI、application 层文件操作编排（Task 4 已实现的 ModAssemblyService
不含文件操作）、根目录配置持久化、缩略图、搜索索引、AI JSON、压缩包内容解析。
本服务不修改 OperationStatus 枚举（未引入 UNDO_BLOCKED/partial 等新值）；
不修改数据库 schema（沿用 Task 2 的 v1）。

## [0.4.0] - 2026-07-07

对应 [docs/roadmap.md](docs/roadmap.md) Task 4（Mod 条目组装服务）完成。

### Added

- Application 层错误 [src/application/errors.py](src/application/errors.py)：
  `ApplicationError`、`ModItemNotFoundError`、`FileAssetNotFoundError`、
  `MemberLimitError`、`DuplicateMemberError`。
- Mod 条目组装服务 [src/application/mod_assembly_service.py](src/application/mod_assembly_service.py)：
  - `ModAssemblyService` 协调 ModItemRepository 与 FileAssetRepository。
  - `create_mod_item`：创建空 ModItem（无成员）。
  - `add_member`：将 FileAsset 关联到 ModItem，设置角色；检查重复关联与角色数量限制。
  - `set_member_role`：更新已关联成员的角色。
  - `set_cover`：设置封面，要求成员为 PREVIEW 角色。
  - `get_mod_item` / `get_members` / `get_mod_item_with_members` / `list_mod_items`：查询接口。
  - `update_mod_item`：更新可编辑字段（display_name/description/source_url/category_folder_id/tags）。
  - `remove_member`：解除关联（mod_item_id=None, role=UNKNOWN）；若被移除的是 cover 同步清除。
  - `ROLE_LIMITS`：MAIN_MOD≤1、README≤1；其他角色不限制（Q19）。
  - 不自动推断成员关系（AGENTS 规则 7）；不访问文件系统；
    不实现 ModItem.status（Q1）、FileAsset.batch_id（Q2）、候选生成（Q10）。
- 单元测试 32 项新增（总计 144 项），覆盖：
  - 创建空 ModItem、带中文字段的 ModItem。
  - 关联单成员、多成员（本体+汉化+预览图，roadmap 验收场景）。
  - 重复关联 → DuplicateMemberError；MAIN_MOD/README 超限 → MemberLimitError；
    TRANSLATION/PREVIEW 不限制。
  - set_member_role：更新角色、改为 MAIN_MOD 时超限、同角色 noop。
  - set_cover：正常设置、非 PREVIEW 拒绝、未关联拒绝。
  - 查询：get_mod_item_not_found、get_members_not_found、
    get_mod_item_with_members、list_mod_items、空成员列表。
  - update_mod_item：全字段、部分字段、中文往返、not_found、tags 非 set 拒绝。
  - remove_member：解除关联、清除 cover、未关联拒绝、解除后重新关联。
  - 完整场景：本体+汉化+预览图+封面+中文显示名。

### 待确认项

- 新增 [open-questions.md Q19](docs/open-questions.md#L159-L169)：成员角色数量限制。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 37 files already formatted
- `python -m pytest` → 142 passed, 2 skipped in 2.80s

### Not in Scope

未实现：UI、文件移动、预演、撤销（Task 5）、OperationLog 写入（Task 5）、
搜索索引、缩略图、AI JSON、候选生成、删除 ModItem 或 FileAsset。
Service 不访问文件系统，仅通过 Repository 读写 SQLite。

## [0.3.0] - 2026-07-07

对应 [docs/roadmap.md](docs/roadmap.md) Task 3（只读扫描器）完成。

### Added

- 扩展名分类 [src/infrastructure/file_classify.py](src/infrastructure/file_classify.py)：
  `AssetHint` 枚举（IMAGE/ARCHIVE/OTHER）；`IMAGE_EXTENSIONS` 与 `ARCHIVE_EXTENSIONS` 集合；
  `get_extension(filename)` 与 `classify_by_extension(filename)`。
  分类结果仅扫描器内部使用，不持久化到 FileAsset 表。
- 只读扫描器 [src/infrastructure/file_scanner.py](src/infrastructure/file_scanner.py)：
  - `FileScanner.scan(root)` / `scan_many(roots)` 递归扫描，返回 `ScanResult`。
  - `ScanResult` 含 `folders`、`files`（`ScannedFileEntry` 列表）与 `errors`（`ScanError` 列表）。
  - `persist_scan_result(scan_result, folder_repo, file_repo)` 将扫描结果通过 Repository 写入 DB，
    处理 path_key 去重（A3 重叠根目录）、父子关系、is_managed_root 标记。
  - 仅使用只读文件系统 API（`Path.iterdir` / `is_dir(follow_symlinks=False)` / `stat(follow_symlinks=False)` / `suffix`），
    不移动、不重命名、不删除、不修改、不打开（读取内容）任何用户文件。
  - 符号链接与 junction 不跟随，按文件处理。
  - 异常（PermissionError / OSError / stat 失败）记入 `ScanError`，不中断整次扫描。
  - 支持中文路径；mtime 转 ISO 8601 UTC。
  - `now_provider` / `uuid_provider` 可注入，便于测试。
- 测试 fixture [tests/conftest.py](tests/conftest.py)：新增 `sample_mod_tree`（混合中英文目录与文件）。
- 单元测试 37 项新增（总计 112 项），覆盖：
  - file_classify：扩展名识别、大小写、多扩展名、中文文件名、点号边界。
  - file_scanner：空目录、样本树、中英文目录/文件名、图片/压缩包分类、文件大小、文件夹 size=0、
    modified_at ISO 格式、扩展名小写、根不存在、根为文件、权限不足（POSIX skip）、
    符号链接不跟随（Windows skip）、scan_many 独立根。
  - persist_scan_result：写入 FolderNode/FileAsset、根 is_managed_root、父子关系、
    字段完整、中文路径往返、重叠根去重、幂等、多受管理根。
  - 只读保证：扫描前后文件 mtime/size/内容一致；扫描不创建/删除文件。

### Skipped

- 2 项测试在 Windows 平台被 skip：`test_scan_permission_denied_directory`（chmod 000 在 Windows 不可靠）、
  `test_scan_symlink_not_followed`（创建符号链接需管理员权限或开发者模式）。
  逻辑已实现，可在 POSIX 平台或具备权限的 Windows 环境验证。

### 待确认项

- 新增 [open-questions.md Q17](docs/open-questions.md#L140-L148)：增量扫描与变更检测策略。
- 新增 [open-questions.md Q18](docs/open-questions.md#L150-L157)：扫描并发与取消模型。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 34 files already formatted
- `python -m pytest` → 110 passed, 2 skipped in 1.74s

### Not in Scope

未实现：UI、application 层编排（Task 4）、Mod 条目组装（Task 4）、文件移动（Task 5）、
搜索索引、缩略图、AI JSON、压缩包内容解析、文件哈希去重、文件监听、
根目录配置持久化、扫描进度回调与取消、增量扫描。
扫描器不读取文件内容，仅按扩展名识别图片/压缩包。

## [0.2.0] - 2026-07-07

对应 [docs/roadmap.md](docs/roadmap.md) Task 2（数据库 Schema 与领域模型）完成。schema_version 由 0 升至 1。

### Added

- 领域模型 [src/domain/models.py](src/domain/models.py)：ModItem、FileAsset、FolderNode、OperationLog dataclass；AssetKind、FileRole、OperationStatus、ConflictPolicy、OperationType enum；`__post_init__` 轻量校验。
- 路径工具 [src/infrastructure/path_utils.py](src/infrastructure/path_utils.py)：`make_path_key(path)` 实现 A2 决策（normcase + normpath），用于路径比较与唯一约束。不访问文件系统。
- 迁移机制 [src/infrastructure/migrations.py](src/infrastructure/migrations.py)：`MIGRATIONS` 注册表与 `migrate_v0_to_v1`。迁移函数幂等（CREATE TABLE IF NOT EXISTS），不写 schema_version。
- 数据库初始化升级 [src/infrastructure/db.py](src/infrastructure/db.py)：`CURRENT_SCHEMA_VERSION` 升至 1；`init_db` 改为「确保 schema_version 表 → 写入 v0 基线（若空） → 按 target 升序应用 pending 迁移 → 每步迁移独立事务后写入新版本号」。
- Repository 层 [src/infrastructure/repositories/](src/infrastructure/repositories/)：
  - `errors.py`：RepositoryError、NotFoundError、ConstraintViolationError。
  - `mod_item.py`：ModItemRepository（create / get_by_id / list_all / update；tags 序列化为 JSON 数组）。
  - `file_asset.py`：FileAssetRepository（create / get_by_id / list_by_mod_item / list_unassociated / update）。
  - `folder_node.py`：FolderNodeRepository（create / get_by_id / list_by_parent / list_managed_roots / update；is_managed_root 存为 0/1）。
  - `operation_log.py`：OperationLogRepository（create / get_by_id / list_by_status / update；list 字段序列化为 JSON 数组）。
- Schema v1（4 张业务表 + 4 个索引 + CHECK 约束）：
  - `mod_item`：依据 spec §6.1，不引入 status 列（open-questions.md Q1）。
  - `file_asset`：依据 spec §6.2，不引入 batch_id 列（Q2）；path_key UNIQUE；asset_kind/role CHECK。
  - `folder_node`：依据 spec §6.3；path_key UNIQUE；is_managed_root CHECK(0,1)；parent_id 自引用 FK。
  - `operation_log`：依据 spec §6.4；status CHECK；conflict_policy CHECK 仅 'ask'（B3）；operation_type 不加 CHECK（Q16）；undo_payload 为 TEXT，结构由 Task 5 定义（Q14）。
- 测试 fixture [tests/conftest.py](tests/conftest.py)：新增 `db_path` 与 `db_connection` fixture（基于 temp_app_data，使用 Row 工厂）。
- 单元测试 67 项新增（总计 73 项），覆盖：
  - path_utils：normpath、normcase、中文路径、幂等、驱动器大小写（A2）。
  - 领域模型：必填字段、enum 类型、负 size、非 set tags、非 list asset_ids。
  - migrations：MIGRATIONS 排序、migrate_v0_to_v1 幂等、CHECK 约束生效。
  - db：fresh DB → v1、v0 → v1 升级、v1 DB 跳过迁移、外键启用、Row 工厂。
  - ModItemRepository：CRUD、中文标签往返、空 tags 序列化为 '[]'、update not found。
  - FileAssetRepository：CRUD、path_key 唯一约束、多成员关联、未关联素材、中文路径、folder kind、空扩展名。
  - FolderNodeRepository：CRUD、父子关系、list_managed_roots、中文 real_path、update not found。
  - OperationLogRepository：CRUD、状态枚举、B3 conflict_policy 拒绝 'overwrite'、undo_payload JSON、中文错误消息、UNDO 操作类型、空 list 字段。

### Changed

- [tests/test_db.py](tests/test_db.py)：扩展为覆盖 v0→v1 升级、幂等、业务表存在、外键启用、Row 工厂。
- [tests/conftest.py](tests/conftest.py)：新增 db_path 与 db_connection fixture。

### 待确认项

- 新增 [open-questions.md Q16](docs/open-questions.md#L129-L138)：OperationType 完整值集。Task 2 代码层定义 {move, undo}，DB 不加 CHECK，预计 Task 5 决策。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 30 files already formatted
- `python -m pytest` → 73 passed in 34.77s

### Not in Scope

未实现：UI、扫描器、文件移动、AI JSON、搜索、缩略图、application 层服务、文件操作预演与撤销。所有 Repository 仅读写应用自身 SQLite DB，不访问用户文件系统。

## [0.1.0] - 2026-07-07

首个可运行骨架版本。对应 [docs/roadmap.md](docs/roadmap.md) 阶段 0（项目初始化）完成。

### Added

- Python 3.12+ 项目骨架，采用 PySide6、SQLite、pytest、ruff。
- 分层目录结构：`src/app`、`src/domain`、`src/infrastructure`、`src/application`、`tests`、`docs`。
- 应用入口 [src/app/main.py](src/app/main.py)，启动顺序：应用数据目录 → 日志 → 数据库 → Qt 事件循环。
- 应用数据目录初始化 [src/app/app_paths.py](src/app/app_paths.py)，位于 `%LOCALAPPDATA%\SkyrimModWorkbench\`，含 `thumbnails\`、`exports\`、`logs\` 子目录。
- 基础日志 [src/app/logging_setup.py](src/app/logging_setup.py)，RotatingFileHandler，UTF-8，写入 `logs\app.log`。
- 空主窗口 [src/app/main_window.py](src/app/main_window.py)，占位 1024×720。
- SQLite 初始化 [src/infrastructure/db.py](src/infrastructure/db.py)，启用外键与 WAL；创建 `schema_version` 表，初始版本 0；幂等可重复调用。
- 测试 fixture [tests/conftest.py](tests/conftest.py)，`temp_app_data` 将 LOCALAPPDATA 指向临时目录，确保不写入真实用户目录。
- 单元测试 6 项，覆盖应用数据目录创建、数据库初始化与幂等、MainWindow 构造。
- 项目配置 [pyproject.toml](pyproject.toml)：依赖、ruff（line-length=100, target py312）、pytest（pythonpath=src）。
- 待确认问题清单 [docs/open-questions.md](docs/open-questions.md)，记录 15 项未决策事项及其兼容性约束。

### 工程决定

- PySide6 版本约束定为 `>=6.8,<7`。文档未固定版本；在 Python 3.14 环境下 pip 选取 6.11.1。

### Verification

- `ruff check src tests` → All checks passed!
- `ruff format --check src tests` → 14 files already formatted
- `python -m pytest` → 6 passed
- 手动运行 `python -m app.main`，主窗口正常启动，控制台无错误。

### Not in Scope

本版本严格限定于 roadmap 阶段 0。未实现：领域模型、文件扫描、文件移动、Repository CRUD、UI 内容（三栏布局/目录树/卡片）、搜索、AI JSON、缩略图、打包。
