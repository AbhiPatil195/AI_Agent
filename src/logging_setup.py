from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from paths import OUT, ensure_dirs


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    ensure_dirs()
    log_dir = OUT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    logger = logging.getLogger("agent_app")
    if logger.handlers:
        return logger
    logger.setLevel(level)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
    fh = RotatingFileHandler(str(log_file), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def install_global_excepthook(logger: Optional[logging.Logger] = None) -> None:
    log = logger or setup_logging()

    def _hook(exc_type, exc, tb):
        log.exception("Unhandled exception", exc_info=(exc_type, exc, tb))
        print("An error occurred; see logs in src/output/logs/app.log")

    import sys

    sys.excepthook = _hook

