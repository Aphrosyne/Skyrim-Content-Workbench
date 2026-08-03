---
name: scw-verify-finish
description: SCW（Skyrim Content Workbench）项目的提交前验证与收尾流程：运行 ruff check、ruff format --check、pytest，将改动交给用户手动验收，通过后按约定拆分提交并推送。当用户说"验证并提交""跑测试""收尾"，或编码类流程（如 scw-stage）进入验证收尾阶段时使用。
---

# SCW 验证与收尾（Verify & Finish）

SCW 项目编码改动提交前的验证与收尾 SOP，供编码类任务收尾，也可单独触发。

## 流程（按顺序执行）

1. **验证**：按 [references/verify.md](references/verify.md) 运行 `ruff check`、`ruff format --check`、`pytest`。
2. **失败处理**：任一验证失败先修复并重跑，不得带失败提交。
3. **验收门**：按 [references/acceptance.md](references/acceptance.md) 的模板给出改动摘要与测试结果，等待用户手动验收。
   - 验收不通过：回到修改，循环直至通过。
   - 验收通过：继续。
4. **提交**：按 [references/commit.md](references/commit.md) 检查改动范围、拆分 commit、填写信息并提交。
5. **推送确认**：提交完成后询问用户是否推送；得到明确确认后 `git push`。
6. **收尾说明**：报告提交范围、测试结果与后续建议。

## 硬性规则

- 未获用户明确验收通过，不得提交或推送。
- 推送必须获得用户单独明确确认。
- 不提交与当前任务无关的改动，不夹带无关重构。
- 推送前确认当前分支与改动范围。
