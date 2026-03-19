"""ORACLE logging configuration."""

from __future__ import annotations

import logging
from pathlib import Path


def setup_logger(
    name: str = "oracle",
    log_file: Path | None = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """Configure and return a logger."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        fmt = logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)
        logger.addHandler(console_handler)

        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(fmt)
            logger.addHandler(file_handler)

    return logger
