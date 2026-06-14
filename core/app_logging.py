"""Application-wide debug + error logging.

Writes a rolling log file the user can hand to an LLM (or to me) whenever
something misbehaves. By design:

  - Lives outside the repo entirely (under %APPDATA%/POE2FilterSoundEditor/),
    so it can never accidentally get committed.
  - Rotates automatically (5 MB cap × 3 backups) so it never fills the disk.
  - Captures uncaught Python exceptions AND Tkinter callback errors — the
    two places things normally die silently.
  - Mirrors WARNING/ERROR records to stderr so devs running from a terminal
    still see them inline.

Use:

    from core.app_logging import init_logging, get_log_path, get_logger
    init_logging()
    log = get_logger(__name__)
    log.info("filter loaded: %s", path)

Anything that should land in the bug-report log goes through `get_logger`.
Bare `print()` calls in older code are gradually being replaced.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import platform
import sys
from typing import Optional

from core.settings import _user_config_dir  # reuse the same APPDATA folder

_LOG_FILENAME = "app_debug.log"
_LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_LOG_BACKUP_COUNT = 3
_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-7s | %(name)s:%(lineno)d | %(message)s"
)

_INITIALIZED = False


def get_log_path() -> str:
    """Absolute path to the active debug log."""
    return os.path.join(_user_config_dir(), _LOG_FILENAME)


def get_logger(name: str) -> logging.Logger:
    """Module-scoped logger. Safe to call before init_logging()."""
    return logging.getLogger(name)


def init_logging(level: int = logging.INFO,
                  stderr_level: int = logging.WARNING) -> str:
    """Configure root logging. Idempotent — safe to call more than once.

    Returns the path of the active log file so the caller can surface it
    in the UI ("Open Debug Log").
    """
    global _INITIALIZED
    log_path = get_log_path()

    if _INITIALIZED:
        return log_path

    root = logging.getLogger()
    root.setLevel(min(level, stderr_level))

    # Rotating file handler — the canonical bug-report sink.
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(file_handler)
    except OSError as e:
        # If we can't open the log file, fall through with stderr only —
        # logging must never block app startup.
        print(f"[logging] could not open {log_path}: {e}", file=sys.stderr)

    # Stderr handler — visible when running from a console / debugger.
    stderr_handler = logging.StreamHandler(stream=sys.stderr)
    stderr_handler.setLevel(stderr_level)
    stderr_handler.setFormatter(logging.Formatter(
        "[%(levelname)s] %(name)s: %(message)s"
    ))
    root.addHandler(stderr_handler)

    _install_exception_hooks(root)

    log = root.getChild("app_logging")
    log.info("=" * 72)
    log.info("session start | Python %s | platform %s",
             platform.python_version(), platform.platform())
    log.info("log file: %s", log_path)

    _INITIALIZED = True
    return log_path


def _install_exception_hooks(root: logging.Logger) -> None:
    """Capture exceptions that Python or Tk would otherwise swallow silently."""
    log = root.getChild("uncaught")

    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log.exception("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = _hook

    # Tkinter swallows callback exceptions by default — patch the class so
    # every Tk root we create reports through our logger.
    try:
        import tkinter as tk

        def _tk_report(self, exc, val, tb):
            log.exception("Tk callback exception",
                          exc_info=(exc, val, tb))

        tk.Tk.report_callback_exception = _tk_report
    except Exception as e:  # noqa: BLE001 — defensive: never block startup
        log.warning("Could not patch Tk exception hook: %s", e)


def log_section(title: str) -> None:
    """Drop a visual separator into the log — useful before/after big ops."""
    log = logging.getLogger("section")
    log.info("--- %s ---", title)


def shutdown() -> None:
    """Flush + close handlers on app exit. Idempotent."""
    logging.shutdown()
