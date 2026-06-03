"""Persistent user settings for the POE2 Filter Sound Editor.

Stored as JSON in an OS-correct user-config directory so that the app is
portable: copy the executable / folder to another PC and the user's prefs
are remembered, while the app finds its data per-user (not next to the .exe).

Windows:  %APPDATA%/POE2FilterSoundEditor/settings.json
macOS:    ~/Library/Application Support/POE2FilterSoundEditor/settings.json
Linux:    $XDG_CONFIG_HOME or ~/.config/POE2FilterSoundEditor/settings.json
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict, field
from typing import List, Optional

APP_NAME = "POE2FilterSoundEditor"


def _user_config_dir() -> str:
    """Return the per-user, per-app config directory, creating it if missing."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def settings_path() -> str:
    return os.path.join(_user_config_dir(), "settings.json")


@dataclass
class AppSettings:
    # Theme
    theme_palette: str = "Default Dark"
    appearance_mode: str = "Dark"  # "Dark" | "Light" | "System"

    # Audio
    ffmpeg_path: str = ""          # Empty -> auto-detect at runtime
    default_volume: int = 300
    audio_backend_order: List[str] = field(
        default_factory=lambda: ["VLC", "pygame", "pydub", "playsound", "ffplay", "system", "winsound"]
    )

    # File handling
    recent_files: List[str] = field(default_factory=list)
    last_filter_path: str = ""
    autoload_last: bool = True
    create_backups: bool = True
    max_backups: int = 20
    # On every successful load, snapshot the file (in its on-disk state) into
    # the same `<name>_backups/` folder so the user has a pristine reference
    # before any tool — auto-compatibility-fix, manual edit, save — touches it.
    # Snapshots are deduplicated: reloading an unchanged file won't pile up copies.
    auto_backup_on_load: bool = True

    # Filter health
    verify_on_save: bool = True
    # Run the compatibility check (unknown commands, migration rules, value validation)
    # automatically every time a filter is loaded. If False, the user can still
    # launch it manually from Tools menu.
    auto_check_compatibility: bool = True

    # UI
    window_geometry: str = ""        # e.g. "1520x920+120+80"
    sidebar_width: int = 320
    show_sidebar: bool = True

    # ------------ Helpers ------------

    def add_recent(self, path: str, limit: int = 10) -> None:
        if not path:
            return
        path = os.path.normpath(path)
        # Move to front, deduplicate, cap length
        try:
            self.recent_files.remove(path)
        except ValueError:
            pass
        self.recent_files.insert(0, path)
        self.recent_files = self.recent_files[:limit]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppSettings":
        # Filter out unknown keys so old/newer schemas don't crash.
        valid = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in (data or {}).items() if k in valid}
        return cls(**clean)


def load_settings() -> AppSettings:
    path = settings_path()
    if not os.path.isfile(path):
        return AppSettings()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return AppSettings.from_dict(data)
    except (OSError, json.JSONDecodeError):
        # Corrupted file — back it up and return defaults
        try:
            os.replace(path, path + ".corrupt")
        except OSError:
            pass
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    path = settings_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings.to_dict(), f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def get_poe2_filter_directory() -> Optional[str]:
    """Best-effort lookup of the standard POE2 filter folder on this OS."""
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        userprofile = os.environ.get("USERPROFILE", home)
        candidates = [
            os.path.join(userprofile, "OneDrive", "Documents", "My Games", "Path of Exile 2"),
            os.path.join(userprofile, "Documents", "My Games", "Path of Exile 2"),
            os.path.join(home, "Documents", "My Games", "Path of Exile 2"),
        ]
    elif sys.platform == "darwin":
        candidates = [
            os.path.join(home, "Library", "Application Support", "Path of Exile 2"),
            os.path.join(home, "Documents", "My Games", "Path of Exile 2"),
        ]
    else:
        candidates = [
            os.path.join(home, ".local", "share", "Path of Exile 2"),
            os.path.join(home, "Documents", "My Games", "Path of Exile 2"),
        ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return None
