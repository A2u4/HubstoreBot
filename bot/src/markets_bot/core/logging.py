"""Logging setup: colored-free console output plus a rotating file per bot identity."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

FORMAT = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"


def setup_logging(identity: str, level: str, log_dir: Path) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(FORMAT, "%H:%M:%S"))
    root.addHandler(console)

    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / f"{identity}.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(FORMAT, "%Y-%m-%d %H:%M:%S"))
    root.addHandler(file_handler)

    # discord.py is chatty at INFO for every gateway event.
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.INFO)
    # Never log SQL: statements can contain message content and user IDs.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
