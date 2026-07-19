"""应用服务层包。

包含领域服务的应用层封装：ManagedRootService / StagingService / ContentService /
FolderTreeService / ScanService / ModGroupService / AssemblyService /
QuickInsertService / TagService（Stage 4 Task 1 起）。

约束：
- Application 层协调 UI 与领域逻辑，不包含领域规则（领域规则在 Domain 层实体校验中）。
- 所有 Repository 异常在 application 层包装为 ApplicationError 子类，
  供 UI 友好提示。
- UI 不直接访问 Repository 或文件系统写操作，通过 Application Service 调用。
"""
