"""Rotating file logging under ``%LOCALAPPDATA%\\RebindMe\\logs``. See plan.md §5."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGS_DIRNAME = "logs"
LOG_FILENAME = "rebind-me.log"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 3


def setup_logging(log_dir: Path, level: str = "info", console: bool = False) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("rebind_me")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(
        log_dir / LOG_FILENAME,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        logger.addHandler(stream)

    return logger


__all__ = ["LOGS_DIRNAME", "setup_logging"]
