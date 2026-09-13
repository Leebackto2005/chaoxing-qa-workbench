"""Logging setup for console and UTF-8 file output."""

from __future__ import annotations

import logging


def configure_logger(settings) -> logging.Logger:
    logger = logging.getLogger("shuake")
    logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
    logger.propagate = False
    if logger.handlers:
        return logger

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = logging.FileHandler(settings.log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(console)
    logger.addHandler(file_handler)
    return logger
