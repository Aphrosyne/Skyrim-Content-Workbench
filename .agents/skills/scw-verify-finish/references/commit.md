# 提交与推送约定（SCW）

- 一个 Task 对应一次有明确边界的改动；改动较大时按逻辑拆分多个 commit。
- commit message 使用中文，说明改动目的；按仓库习惯可带任务/阶段标识（如 "UX 重构 Phase X Task N Commit M"），有版本号时以 `(vX.Y.Z)` 结尾。
- 涉及行为变化时按需在 CHANGELOG.md 追加条目。
- 问题清单完成标记：`### <条目名> ✅ 已修复（vX.Y.Z，日期）` + 一行实现摘要；版本号递增按 CHANGELOG.md 顶部的 SemVer 约定（PATCH = 同里程碑内修复/小幅调整；MINOR = 里程碑/Task 或影响用户数据/破坏性变更）。
- 提交前用 `git status` / `git diff` 检查改动范围，确保无无关文件。
- 推送必须等待用户明确确认（见 SKILL.md 流程第 5 步）；推送前确认当前分支正确；推送失败先处理冲突，不得强制覆盖。
- 提交内容不含易过期信息的硬编码（版本号、Task 号等）。
- Codex 桌面 app 指令：提交成功后输出 `::git-commit{cwd="<项目根>"}`；推送成功后输出 `::git-push{cwd="<项目根>" branch="<分支名>"}`（各占一行）。
