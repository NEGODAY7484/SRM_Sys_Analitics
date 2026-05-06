"""Logging configuration for the SRM prototype."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path


def configure_logging(log_dir: Path, *, level: str = "INFO") -> None:
    """Configure console + rotating-file logging.

    Args:
        log_dir: Directory where `srm.log` will be created.
        level: Logging level name (e.g., "DEBUG", "INFO").
    """

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "srm.log"

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    for handler in list(root.handlers):
        root.removeHandler(handler)

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(stream=sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)
