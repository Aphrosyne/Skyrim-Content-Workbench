r"""基础日志配置。

日志写入 %LOCALAPPDATA%\SkyrimModWorkbench\logs\app.log，UTF-8，滚动。
所有异常应转换为用户可理解的错误信息，并保留技术日志（见 AGENTS.md 开发方式）。
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.app_paths import get_logs_dir

LOG_FILE_NAME = "app.log"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 3


def setup_logging(level: int = logging.INFO) -> Path:
    """初始化根日志器，写入 logs/app.log。返回日志文件路径。

    多次调用不会重复添加 handler。
    """
    logs_dir = get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / LOG_FILE_NAME

    handler = RotatingFileHandler(
        log_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT))

    root = logging.getLogger()
    # 避免重复添加同一文件的 handler
    already_attached = any(
        isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", "") == str(log_path)
        for h in root.handlers
    )
    if not already_attached:
        root.addHandler(handler)
    root.setLevel(level)
    return log_path
