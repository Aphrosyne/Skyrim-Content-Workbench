"""开发环境清理脚本。

清理开发过程中产生的临时文件和缓存，保持工作目录整洁。

用法::

    python scripts/clean.py           # 默认：安全清理
    python scripts/clean.py --all     # 深度清理（含 pytest tmp 目录）

安全清理范围：
- 项目内所有 __pycache__/ 目录
- 项目内所有 *.pyc / *.pyo 文件
- .pytest_cache/ 目录
- .ruff_cache/ 目录
- .cache/ 目录
- 项目内 *.egg-info/ 目录
- build/ dist/ 目录（若存在）

深度清理（--all）额外清理：
- pytest-of-<用户名> 临时目录（位于系统 Temp）
  pytest tmp_path 机制产生的测试临时文件，可安全删除

永不会删除的受保护内容：
- src/ tests/ docs/ archive/ 源码与文档
- app.db 数据库
- thumbnails/ exports/ logs/ 应用数据
- local_appdata/ 本地开发运行时数据
- .git/ 版本控制
- .venv/ venv/ 虚拟环境
- 用户 Mod 文件或任何项目外数据
"""

from __future__ import annotations

import argparse
import getpass
import logging
import shutil
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# 项目根目录（scripts/clean.py 的上两级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 安全清理目标：目录
SAFE_CLEAN_DIRS = [
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".cache",
    ".eggs",
    "build",
    "dist",
]

# 安全清理目标：文件名模式
SAFE_CLEAN_PATTERNS = ["*.pyc", "*.pyo"]

# egg-info 目录模式
SAFE_CLEAN_GLOBS = ["*.egg-info"]

# 受保护目录/文件名（永不可删除）
PROTECTED_NAMES = {
    "src",
    "tests",
    "docs",
    "archive",
    "scripts",
    ".git",
    ".venv",
    "venv",
    ".env",
    "LICENSE",
    "README.md",
    "CHANGELOG.md",
    "AGENTS.md",
    "pyproject.toml",
    ".gitignore",
    "app.db",
    "thumbnails",
    "exports",
    "logs",
    "local_appdata",
}

# 应用数据子目录名（用于校验保护逻辑）
APP_DATA_DIR_NAME = "SkyrimContentWorkbench"


def find_safe_targets(root: Path) -> tuple[list[Path], list[Path]]:
    """扫描项目内可安全清理的目录和文件。

    遍历项目目录，识别匹配安全清理模式的目录和文件。
    跳过 .git / .venv 等受保护目录的内部（但 src/tests 下的 __pycache__
    仍会被识别为缓存并删除）。

    Returns:
        (待删目录列表, 待删文件列表)
    """
    dirs_to_delete: list[Path] = []
    files_to_delete: list[Path] = []

    # 需要跳过内部遍历的受保护目录（这些目录的内部内容不可碰）
    # 但 src/tests/docs/archive/scripts 本身可遍历（其下的 __pycache__ 需清理）
    SKIP_TRAVERSE_INTO = {".git", ".venv", "venv", "local_appdata"}

    for path in root.rglob("*"):
        rel_parts = path.relative_to(root).parts
        # 跳过 .git / .venv / local_appdata 等目录的内部
        if any(part in SKIP_TRAVERSE_INTO for part in rel_parts[:-1]):
            continue
        # 跳过这些受保护目录本身
        if path.is_dir() and path.name in SKIP_TRAVERSE_INTO:
            continue

        if path.is_dir():
            if path.name in SAFE_CLEAN_DIRS or any(path.match(glob) for glob in SAFE_CLEAN_GLOBS):
                dirs_to_delete.append(path)
        elif path.is_file() and any(path.match(p) for p in SAFE_CLEAN_PATTERNS):
            files_to_delete.append(path)

    return dirs_to_delete, files_to_delete


def find_pytest_tmp_dirs() -> list[Path]:
    """查找 pytest tmp_path 机制产生的临时目录。

    pytest 在系统 Temp 下创建 pytest-of-<用户名>/pytest-N/ 目录，
    用于 tmp_path fixture。这些目录可安全删除。
    """
    tmp_root = Path(tempfile.gettempdir())
    username = getpass.getuser()
    pytest_tmp_root = tmp_root / f"pytest-of-{username}"
    if not pytest_tmp_root.exists():
        return []
    return [pytest_tmp_root]


def delete_path(path: Path) -> bool:
    """安全删除文件或目录。返回是否成功。"""
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return True
    except OSError as e:
        logger.warning("删除失败：%s (%s)", path, e)
        return False


def is_protected(path: Path) -> bool:
    """检查路径是否属于受保护内容（永不可删除）。

    用于校验清理逻辑不会误删。受保护的是源码文件、文档、配置、应用数据。
    缓存目录（如 __pycache__、.pytest_cache）不受保护，即使位于 src/ 下。
    """
    try:
        rel = path.relative_to(PROJECT_ROOT)
    except ValueError:
        # 不在项目内 → 视为受保护（不应被脚本删除）
        return True

    parts = rel.parts
    if not parts:
        return True

    # 缓存目录及其内容不受保护（优先判断，即使位于 src/ 下）
    # 例如 src/__pycache__/module.pyc 不受保护
    if "__pycache__" in parts:
        return False
    for cache_name in SAFE_CLEAN_DIRS:
        if cache_name in parts:
            return False
    for pattern in SAFE_CLEAN_GLOBS:
        # 检查是否有 *.egg-info 这样的缓存目录在路径中
        for part in parts:
            if Path(part).match(pattern):
                return False

    # 根级受保护文件/目录
    if parts[0] in PROTECTED_NAMES:
        return True

    # src/ tests/ docs/ archive/ scripts/ 下的源码文件受保护
    # 但 __pycache__/*.pyc 已在上面排除
    return parts[0] in {"src", "tests", "docs", "archive", "scripts"}


def clean_safe(root: Path) -> tuple[int, int]:
    """执行安全清理。返回 (删除目录数, 删除文件数)。

    先删散落的 .pyc/.pyo 文件，再删缓存目录（避免目录被 rmtree 后
    再尝试 unlink 其内文件导致 FileNotFoundError）。
    """
    dirs, files = find_safe_targets(root)
    files_deleted = sum(1 for f in files if delete_path(f))
    dirs_deleted = sum(1 for d in dirs if delete_path(d))
    return dirs_deleted, files_deleted


def clean_pytest_tmp() -> int:
    """清理 pytest 临时目录。返回删除的目录数。"""
    pytest_dirs = find_pytest_tmp_dirs()
    return sum(1 for d in pytest_dirs if delete_path(d))


def main(argv: list[str] | None = None) -> int:
    """清理入口。返回退出码。"""
    parser = argparse.ArgumentParser(description="清理开发环境产生的临时文件和缓存")
    parser.add_argument(
        "--all",
        action="store_true",
        help="深度清理：额外清理 pytest tmp_path 临时目录（位于系统 Temp）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅列出待清理内容，不实际删除",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="显示详细清理信息",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    print(f"项目根目录：{PROJECT_ROOT}")
    print()

    # 安全清理
    print("[安全清理]")
    if args.dry_run:
        dirs, files = find_safe_targets(PROJECT_ROOT)
        print(f"  待删目录 ({len(dirs)}):")
        for d in dirs:
            print(f"    {d.relative_to(PROJECT_ROOT)}")
        print(f"  待删文件 ({len(files)}):")
        for f in files:
            print(f"    {f.relative_to(PROJECT_ROOT)}")
        dirs_deleted, files_deleted = 0, 0
    else:
        dirs_deleted, files_deleted = clean_safe(PROJECT_ROOT)
        print(f"  已删除目录：{dirs_deleted}")
        print(f"  已删除文件：{files_deleted}")
    print()

    # 深度清理
    if args.all:
        print("[深度清理]")
        pytest_dirs = find_pytest_tmp_dirs()
        if not pytest_dirs:
            print("  未找到 pytest 临时目录")
        elif args.dry_run:
            print(f"  待删 pytest 临时目录 ({len(pytest_dirs)}):")
            for d in pytest_dirs:
                print(f"    {d}")
            pytest_deleted = 0
        else:
            pytest_deleted = clean_pytest_tmp()
            print(f"  已删除 pytest 临时目录：{pytest_deleted}")
        print()

    # 受保护内容确认
    print("[受保护内容]")
    print("  源码：src/ tests/ docs/ archive/ scripts/")
    print("  应用数据：app.db thumbnails/ exports/ logs/ local_appdata/")
    print("  版本控制：.git/")
    print("  虚拟环境：.venv/ venv/")
    print("  用户 Mod 文件：不受影响")
    print()

    if args.dry_run:
        print("（dry-run 模式，未实际删除任何内容）")
    else:
        print("清理完成。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
