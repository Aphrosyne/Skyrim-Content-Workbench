# 架构设计

## 1. 技术选型

第一版采用：

* Python 3.12+
* PySide6
* SQLite + FTS5
* Pillow
* pytest
* ruff
* PyInstaller 或 Nuitka，用于后续 Windows 打包

选择理由：

* PySide6 适合 Windows 桌面文件管理交互，包括目录树、卡片视图、右键菜单、多选和拖放。
* SQLite 是本地单文件数据库，无需服务端。
* Python 对 UTF-8、中文路径和快速迭代友好。
* 第一版不需要前后端分离、Web 服务、云端 API 或桌面 WebView。

## 2. 分层原则

UI 层不得包含业务规则或文件系统写操作。

```text
PySide6 UI
    ↓ 调用
Application Services
    ↓ 调用
Domain Logic
    ↓ 调用
Infrastructure
    ├─ SQLite Repository
    ├─ File Scanner
    ├─ File Operation Service
    ├─ Thumbnail Service
    └─ JSON Import/Export Service
```

## 3. 模块职责

### ui/

负责：

* 主窗口
* 三栏布局
* 目录树
* 素材池和 Mod 卡片
* 详情编辑
* 预演确认对话框
* 操作日志与撤销入口

不得负责：

* 拼接真实目标路径
* 直接移动文件
* 直接写 SQL
* 直接解析 AI JSON

### domain/

负责：

* ModItem、FileAsset、FolderNode、OperationLog 等领域模型
* 成员角色规则
* 移动预演规则
* 冲突规则
* 撤销可行性规则
* AI 建议应用规则

### infrastructure/

负责：

* SQLite 数据库连接、迁移和 Repository
* 文件扫描
* 路径标准化
* 文件移动、复制、存在性检查和权限检查
* 缩略图生成与缓存
* JSON 导入导出

### application/

负责：

* 协调 UI 与领域逻辑
* 执行扫描
* 创建 Mod 条目
* 关联成员
* 生成移动预演
* 执行确认后的移动
* 导出和导入 AI 建议
* 更新搜索索引

## 4. 数据存储

应用数据应位于：

```text
%LOCALAPPDATA%\SkyrimModWorkbench\
  app.db
  thumbnails\
  exports\
  logs\
```

用户 Mod 文件不应被复制到应用数据目录。唯一例外是缩略图缓存。

数据库损坏不应影响用户原始 Mod 文件；重新扫描后应能重建基础索引。

## 5. 路径与 Unicode

* 所有路径使用 pathlib.Path。
* 不得以字节串方式处理 Windows 路径。
* SQLite TEXT 字段保存 Unicode。
* JSON 文件使用 UTF-8。
* UI 必须完整显示中文、英文、日文和混合路径。
* 路径比较必须经过标准化；不得仅依赖字符串大小写比较。
* 待确认：Windows 下路径大小写规范化策略。

## 6. 文件操作服务

文件操作服务是唯一允许修改用户文件位置的模块。

接口示例：

```text
plan_move(mod_item_id, target_folder_id) -> MovePlan
execute_move(plan_id) -> OperationResult
plan_undo(operation_id) -> UndoPlan
execute_undo(undo_plan_id) -> OperationResult
```

MovePlan 必须包含：

* 操作 ID
* 成员文件列表
* 每个成员的源路径和目标路径
* 重名冲突
* 缺失文件
* 跨盘标记
* 可写性检查
* 阻止原因
* 可执行状态

执行前，MovePlan 必须持久化为 `planned` 状态。用户确认后才变为 `confirmed` 并执行。

## 7. 搜索架构

使用 SQLite FTS5 建立本地搜索索引。

索引字段：

* display_name
* description
* filename
* real_path
* source_url
* tags
* category_display_path

第一版搜索不要求复杂语法；普通关键词搜索即可。

## 8. 缩略图架构

* 原图保持不变。
* 缩略图以 `asset_id` 或内容标识命名。
* 缩略图缓存可随时删除并重建。
* 卡片优先加载缩略图，不直接加载大图。
* 待确认：缩略图缓存失效策略。

## 9. AI JSON 架构

* 所有 JSON 文件都必须有 `schema_version`。
* 导入前必须校验字段、类型、ID 是否存在。
* AI 返回的路径字段不得被信任。
* AI 只能引用已导出的 `asset_id`、`mod_item_id`、`folder_id`。
* AI 不得提供 shell 命令、任意文件路径或删除指令。
* 分类移动必须由本地 `folder_id` 映射到真实路径。

## 10. 测试策略

必须优先测试：

* 扫描中文路径。
* 创建 Mod 条目和关联成员。
* 同盘移动预演。
* 重名冲突预演。
* 目标目录为源目录子目录时的阻止。
* 部分成员缺失时的阻止。
* 操作日志写入。
* 撤销预演。
* AI JSON 非法字段拒绝。
* 数据库重启后数据恢复。