"""Path resolution for the Economy Tier feature.

Two kinds of location:

* **Bundled, read-only data** (the tier seed, default templates, JSON schemas).
  In a normal source checkout these live in the project tree. In a PyInstaller
  one-file build they are unpacked to ``sys._MEIPASS``. :func:`resource_path`
  resolves both.
* **Per-user, writable state** (user template overrides, op-history, logs).
  These live in the same per-user config dir the rest of the app already uses
  (``core.settings``), so prefs travel with the user, not the .exe.
"""

from __future__ import annotations

import os
import sys

# Reuse the app's existing per-user config dir so this feature stores its
# state next to settings.json instead of inventing a new location.
from core.settings import _user_config_dir


def _project_root() -> str:
    """Directory that contains the ``data/`` and ``economy_tier/`` trees.

    Source layout: this file is ``<root>/economy_tier/resources.py``.
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*relative: str) -> str:
    """Resolve a bundled read-only resource by path parts relative to the root.

    Works both from source and from a frozen PyInstaller build (``_MEIPASS``).
    Example: ``resource_path("data", "economy_tiers", "poe2_0_5_tiers.json")``.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = os.path.join(meipass, *relative)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(_project_root(), *relative)


def tier_data_path() -> str:
    """Path to the shipped economy tier seed file."""
    return resource_path("data", "economy_tiers", "poe2_0_5_tiers.json")


def templates_path() -> str:
    """Path to the shipped economy visual templates file."""
    return resource_path("data", "color_templates", "economy_tier_templates.json")


def schema_path(name: str) -> str:
    """Path to a shipped JSON Schema (e.g. ``"tiers"``, ``"templates"``)."""
    return resource_path("economy_tier", "schemas", f"{name}.schema.json")


def user_data_dir() -> str:
    """Per-user, writable directory for this feature's state. Created if absent."""
    path = os.path.join(_user_config_dir(), "economy_tier")
    os.makedirs(path, exist_ok=True)
    return path


def op_history_path() -> str:
    """Path to the persisted operation-history file (writable, per-user)."""
    return os.path.join(user_data_dir(), "op_history.json")


def log_dir() -> str:
    """Per-user directory for this feature's rotating log file."""
    path = os.path.join(user_data_dir(), "logs")
    os.makedirs(path, exist_ok=True)
    return path


def user_templates_path() -> str:
    """Optional per-user template override file (writable)."""
    return os.path.join(user_data_dir(), "economy_tier_templates.json")


__all__ = [
    "resource_path",
    "tier_data_path",
    "templates_path",
    "schema_path",
    "user_data_dir",
    "op_history_path",
    "log_dir",
    "user_templates_path",
]
