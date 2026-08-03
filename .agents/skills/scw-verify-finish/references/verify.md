# 验证命令（SCW）

在项目根目录执行，使用项目虚拟环境：

    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m ruff format --check src tests
    .venv\Scripts\python.exe -m pytest -q --tb=short

失败处理：

- `ruff check` 报错：修复后重跑，直到通过。
- `ruff format --check` 报错：先运行 `ruff format src tests` 修复，再重跑检查。
- `pytest` 失败：先运行相关测试定位失败用例并修复，修复后重跑相关测试；提交前必须运行完整 `pytest -q --tb=short` 确认全绿。
- 全量 pytest 每个任务只跑一次（提交前），修复循环中不要重复全量；仅新增/修改相关模块时，可先用 `-k` 或指定测试文件缩小范围。
