# 验证命令（SCW）

先设置输出编码（避免中文输出乱码），再执行验证：

    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $env:PYTHONIOENCODING = "utf-8"

在项目根目录执行，使用项目虚拟环境：

    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m ruff format --check src tests
    .venv\Scripts\python.exe -m pytest -q --tb=short

失败处理：

- `ruff check` 报错：修复后重跑，直到通过。
- `ruff format --check` 报错：先运行 `ruff format src tests` 修复，再重跑检查。
- `pytest` 失败：先运行相关测试定位失败用例并修复，修复后重跑相关测试；提交前必须运行完整 `pytest -q --tb=short` 确认全绿。
- 全量 pytest 每个任务只跑一次（提交前），修复循环中不要重复全量；仅新增/修改相关模块时，可先用 `-k` 或指定测试文件缩小范围。

全量失败时先判断是否与本任务相关：

- 本任务引入 → 修复后重跑相关测试，再跑全量。
- 疑似既有问题（与本次改动无关）→ 用干净检出或暂存改动复现确认；确认是既有问题后，记录到 `docs/workflow-test-issues.md`（含复现方式与干净基线证据），如实告知用户，不因既有问题阻塞本任务提交。
