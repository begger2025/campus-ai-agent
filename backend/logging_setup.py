"""应用日志配置：控制台 + data/logs/app.log 轮转文件。

后端此前没有任何 Python logging（"日志"只有手写的 system_logs 表），
排障只能靠 uvicorn 默认输出。这里统一挂在 "campus" logger 下，
业务代码用 logging.getLogger("campus.<module>") 获取。
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "logs"
LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def setup_logging() -> logging.Logger:
    """幂等：重复调用不会叠加 handler。"""

    logger = logging.getLogger("campus")
    if logger.handlers:
        return logger

    level_name = (os.getenv("LOG_LEVEL") or "INFO").upper()
    logger.setLevel(getattr(logging, level_name, logging.INFO))
    formatter = logging.Formatter(LOG_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_DIR / "app.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        logger.warning("无法创建日志目录 %s，仅输出到控制台", LOG_DIR)

    return logger
