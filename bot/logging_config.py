"""
Logging configuration for the trading bot.

Sets up structured, dual-destination logging:
  - RotatingFileHandler → logs/trading_bot.log  (DEBUG+, max 5 MB × 5 backups)
  - StreamHandler       → stdout                 (configurable level, default INFO)

Usage
-----
    from bot.logging_config import setup_logging
    setup_logging(log_level="DEBUG")
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "trading_bot.log"

# File rotation: 5 MB per file, keep 5 backups
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5

_LOG_FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FMT = "%Y-%m-%dT%H:%M:%S"


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """
    Configure and return the root logger.

    Parameters
    ----------
    log_level : str
        Console log level ('DEBUG' | 'INFO' | 'WARNING' | 'ERROR').
        The file handler always logs at DEBUG regardless of this value.

    Returns
    -------
    logging.Logger
        The configured root logger (subsequent ``getLogger()`` calls will
        inherit these handlers automatically).
    """
    LOG_DIR.mkdir(exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Guard: never add duplicate handlers (e.g. when called twice in tests)
    if root.handlers:
        return root

    formatter = logging.Formatter(fmt=_LOG_FMT, datefmt=_DATE_FMT)

    # ── File handler (DEBUG+, rotating) ──────────────────────────────────
    fh = RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    root.addHandler(fh)

    # ── Console handler (configurable level) ─────────────────────────────
    console_level = getattr(logging, log_level.upper(), logging.INFO)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(console_level)
    ch.setFormatter(formatter)
    root.addHandler(ch)

    root.info(
        "Logging initialised | file=%s console_level=%s",
        LOG_FILE,
        log_level.upper(),
    )
    return root
