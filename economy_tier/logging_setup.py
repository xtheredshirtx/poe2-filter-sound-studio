"""Feature-scoped logging for the Economy Tier feature (A.8).

A single named logger (``economy_tier``) with a rotating file handler in the
per-user data dir. The handler is attached once and is idempotent, so importing
and configuring repeatedly is safe. Uses the stdlib ``logging`` module, never
``print``.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from economy_tier.resources import log_dir

LOGGER_NAME = "economy_tier"

_MAX_BYTES = 512 * 1024
_BACKUP_COUNT = 3


def get_logger() -> logging.Logger:
    """Return the feature logger, configuring its file handler exactly once."""
    logger = logging.getLogger(LOGGER_NAME)
    if getattr(logger, "_economy_tier_configured", False):
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    try:
        log_path = os.path.join(log_dir(), "economy_tier.log")
        handler: logging.Handler = RotatingFileHandler(
            log_path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
    except OSError:
        # Never let logging setup break the feature; fall back to a null sink.
        handler = logging.NullHandler()

    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    # Mark as configured so we don't stack handlers on re-import.
    logger._economy_tier_configured = True  # type: ignore[attr-defined]
    return logger


__all__ = ["get_logger", "LOGGER_NAME"]
