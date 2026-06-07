"""POE2 Item Filter Sound Replacer - Refactored Main Application

This is the refactored version using the new modular architecture.
Maintains full backward compatibility with existing functionality.
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, simpledialog
import os
import shutil
import re
import threading
import sys
import subprocess
import webbrowser
from shutil import which
from datetime import datetime

# Import new core modules
from core.file_operations import load_filter_file, save_filter_file, make_backup, copy_sound_file, get_filter_directory
from core.parser import (
    SOUND_RE_CUSTOM, SOUND_RE_PLAY, SECTION_RE, SUBSECTION_RE,
    TYPE_TAG_RE, TIER_TAG_RE, STYLE_TAG_RE, FilterParser,
)
from core.settings import (
    AppSettings, load_settings, save_settings, settings_path,
    get_poe2_filter_directory,
)
from features.color_editor import ColorManager, ColorClipboard
from features.themes import ThemeManager, BUILTIN_PALETTES, palette_names, get_palette
from ui.dialogs import ColorPickerDialog, ItemPreviewDialog, ConfirmDialog
from core.compatibility import (
    FilterCompatibilityChecker, MigrationRulesEngine, default_rules_path,
)
from ui.compatibility_dialog import show_compatibility_dialog
from ui.visual_tools_dialog import open_visual_tools

# =====================
# Identity (single source of truth for the app's name and version)
# =====================
APP_NAME = "POE2 Filter Sound Studio"
APP_SHORT = "Filter Sound Studio"
APP_VERSION = "2.0.0"
APP_TAGLINE = "Path of Exile 2 item-filter sound and category editor"

# Economy Tier Visual Preset dropdown options (canonical order; see economy_tier
# package). Kept as a literal here so the main window builds even if the optional
# economy_tier dependencies are unavailable; the feature is imported lazily.
ECONOMY_TIER_MODES = [
    "Off",
    "Preview Only",
    "Apply Economy Tier Visuals",
    "Apply Economy Tier Visuals Plus Chance Base Boost",
    "Restore Previous Visuals",
]


def _resolve_icon_path() -> str:
    """Return the absolute path to the bundled app icon, or '' if none exists."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "app.ico"),
        os.path.join(here, "icon.ico"),
        os.path.join(here, "nvo7elUI_400x400 (1).ico"),
        os.path.join(here, "data", "app.ico"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return ""


APP_ICON_PATH = _resolve_icon_path()


# =====================
# FFmpeg auto-detection (portable: no hardcoded paths)
# =====================
def _detect_ffmpeg_dir(user_override: str = "") -> str:
    """Return a directory containing ffmpeg.exe/ffmpeg, or "" if none found.

    Search order:
      1) Explicit path from settings (file or its parent dir)
      2) System PATH (shutil.which)
      3) Bundled ./ffmpeg/ next to this script
    """
    candidates = []
    if user_override:
        if os.path.isfile(user_override):
            candidates.append(os.path.dirname(user_override))
        elif os.path.isdir(user_override):
            candidates.append(user_override)

    found = which("ffmpeg")
    if found:
        candidates.append(os.path.dirname(found))

    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, "ffmpeg"))
    candidates.append(os.path.join(here, "ffmpeg", "bin"))

    for d in candidates:
        if not d:
            continue
        exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        if os.path.isfile(os.path.join(d, exe)):
            return d
    return ""


def _resolve_ffmpeg_paths(user_override: str = ""):
    """Return (ffmpeg_dir, ffmpeg_path, ffprobe_path, ffplay_path). Any field can be ""."""
    d = _detect_ffmpeg_dir(user_override)
    if not d:
        return "", "", "", ""
    suffix = ".exe" if os.name == "nt" else ""
    ffm = os.path.join(d, f"ffmpeg{suffix}")
    ffp = os.path.join(d, f"ffprobe{suffix}")
    ffl = os.path.join(d, f"ffplay{suffix}")
    return (
        d if os.path.isdir(d) else "",
        ffm if os.path.isfile(ffm) else "",
        ffp if os.path.isfile(ffp) else "",
        ffl if os.path.isfile(ffl) else "",
    )

# Optional backends for audio preview
_vlc = None
try:
    import vlc as _vlc
    _vlc = _vlc
except Exception:
    _vlc = None

_pygame = None
try:
    import pygame as _pygame
    _pygame = _pygame
except Exception:
    _pygame = None

_pydub = None
try:
    from pydub import AudioSegment as _AudioSegment
    from pydub.playback import _play_with_simpleaudio as _pydub_play
    _pydub = (_AudioSegment, _pydub_play)
except Exception:
    _pydub = None


def _configure_pydub_ffmpeg(ffmpeg_path: str, ffprobe_path: str) -> None:
    """Late-bind pydub's converter/probe and PATH once we've detected FFmpeg."""
    if not _pydub or not ffmpeg_path:
        return
    AudioSegment, _ = _pydub
    try:
        AudioSegment.converter = ffmpeg_path
        os.environ["FFMPEG_BINARY"] = ffmpeg_path
        if ffprobe_path:
            AudioSegment.ffprobe = ffprobe_path
            os.environ["FFPROBE_BINARY"] = ffprobe_path
        ff_dir = os.path.dirname(ffmpeg_path)
        if ff_dir and ff_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = ff_dir + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass

try:
    from playsound import playsound as _playsound
except Exception:
    _playsound = None

try:
    import winsound  # Windows-only, WAV only
except Exception:
    winsound = None


class FilterSoundEditor:
    def __init__(self, root):
        self.root = root

        # ---------- Settings + theme ----------
        self.settings: AppSettings = load_settings()
        self.theme_manager = ThemeManager()

        # Apply appearance mode + an initial CTk theme BEFORE any widgets are built.
        # The palette colors are then overlaid post-construction via theme_manager.apply().
        try:
            ctk.set_appearance_mode(self.settings.appearance_mode if self.settings.appearance_mode in ("Light", "Dark", "System") else "Dark")
            ctk.set_default_color_theme("dark-blue")
        except Exception:
            pass

        self.root.title(f"{APP_NAME} — v{APP_VERSION}")
        self._apply_window_icon(self.root)
        self._initialize_main_window_geometry()

        # ---------- FFmpeg resolution ----------
        self.ffmpeg_dir, self.ffmpeg_path, self.ffprobe_path, self.ffplay_path = _resolve_ffmpeg_paths(self.settings.ffmpeg_path)
        _configure_pydub_ffmpeg(self.ffmpeg_path, self.ffprobe_path)

        # ---------- Filter state ----------
        self.filter_data = []
        self.filtered_data = []
        self.filter_path = ""
        self.lines = []
        self.bulk_mode = ctk.BooleanVar(value=False)
        self.hide_no_sound_var = ctk.BooleanVar(value=False)
        self.last_changed_path = None
        self.category_var = ctk.StringVar(value="All Categories")
        self._all_categories = ["All Categories"]

        # ---------- Merge tab state ----------
        self.merge_left_path = ""
        self.merge_middle_path = ""

        # ---------- Color editor state ----------
        self.color_clipboard = ColorClipboard()
        self.filter_parser = FilterParser()

        # ---------- Audio preview state ----------
        self._vlc_instance = _vlc.Instance() if _vlc else None
        self._vlc_player = None
        self._pygame_ready = False
        self._pydub_obj = None
        self._ffplay_proc = None

        # ---------- UI ----------
        self._build_menu_bar()
        self.setup_gui()
        self._bind_shortcuts()

        # Apply theme to all built widgets in one pass
        self.theme_manager.apply(self.settings.theme_palette, self.settings.appearance_mode)

        # Persist window geometry on close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Boot: autoload last filter, or offer the POE2 folder
        self.root.after(100, self._post_launch)

    # -------------------- GUI (unchanged) -------------------- #
    def setup_gui(self):
        # Root container
        self.frame = ctk.CTkFrame(master=self.root, corner_radius=12)
        self.frame.pack(fill="both", expand=True, padx=16, pady=16)

        # Tabview
        self.tabs = ctk.CTkTabview(self.frame, corner_radius=12)
        self.tabs.pack(fill="both", expand=True)
        tab_edit = self.tabs.add("Editor")
        tab_merge = self.tabs.add("Merge")

        # ===== Editor tab =====
        # Header
        header = ctk.CTkFrame(tab_edit, corner_radius=12)
        header.pack(fill="x", padx=6, pady=(6, 10))

        title = ctk.CTkLabel(header, text=APP_NAME,
                             font=("Segoe UI Semibold", 20))
        title.pack(side="left", padx=(12, 8), pady=8)

        self.file_label = ctk.CTkLabel(header, text="No file loaded",
                                       font=("Segoe UI", 12))
        self.file_label.pack(side="left", padx=6, pady=8)

        # Top controls
        top_controls = ctk.CTkFrame(tab_edit, corner_radius=12)
        top_controls.pack(fill="x", padx=6, pady=(0, 10))

        self.load_button = ctk.CTkButton(top_controls, text="📂 Load Filter File", command=self.load_filter, width=150)
        self.load_button.pack(side="left", padx=(10, 10), pady=10)

        # Economy Tier Visual Preset: instantly restyle the filter by value tier.
        # Acts as an action trigger -- choosing a mode opens the preview dialog,
        # then the dropdown resets to "Off". Default is "Off" (does nothing).
        self.economy_mode_selector = ctk.CTkOptionMenu(
            top_controls,
            values=ECONOMY_TIER_MODES,
            command=self._on_economy_mode_selected,
            width=270,
        )
        self.economy_mode_selector.set("Off")
        self.economy_mode_selector.pack(side="left", padx=(0, 10), pady=10)

        self.search_box = ctk.CTkEntry(top_controls, height=36,
                                       placeholder_text="Search rarity, sound, id, effect, minimap, class, basetype... (Ctrl+F)")
        self.search_box.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=10)
        self.search_box.bind("<KeyRelease>", self.apply_filter)

        self.hide_no_sound_cb = ctk.CTkCheckBox(top_controls, text="Show only items with sound",
                                                variable=self.hide_no_sound_var,
                                                command=self.apply_filter)
        self.hide_no_sound_cb.pack(side="left", padx=(0, 10), pady=10)

        # Theme picker (live-switching). Replaces the old broken CTk theme dropdown.
        ctk.CTkLabel(top_controls, text="Theme:").pack(side="right", padx=(4, 4), pady=10)
        self.theme_selector = ctk.CTkOptionMenu(
            top_controls,
            values=palette_names(),
            command=self.change_theme,
            width=220,
        )
        self.theme_selector.set(self.settings.theme_palette if self.settings.theme_palette in palette_names() else palette_names()[0])
        self.theme_selector.pack(side="right", padx=(0, 10), pady=10)

        ctk.CTkLabel(top_controls, text="Mode:").pack(side="right", padx=(10, 4), pady=10)
        self.appearance_selector = ctk.CTkOptionMenu(
            top_controls,
            values=["System", "Light", "Dark"],
            command=self.change_appearance_mode,
            width=100,
        )
        self.appearance_selector.set(self.settings.appearance_mode if self.settings.appearance_mode in ("System", "Light", "Dark") else "Dark")
        self.appearance_selector.pack(side="right", padx=(0, 4), pady=10)

        # Data area
        body = ctk.CTkFrame(tab_edit, corner_radius=12)
        body.pack(fill="both", expand=True, padx=6, pady=(0, 10))

        # Split body horizontally: category sidebar (left) + main tree (right)
        sidebar = ctk.CTkFrame(body, corner_radius=12, width=320)
        sidebar.pack(side="left", fill="y", padx=(10, 4), pady=10)
        sidebar.pack_propagate(False)  # keep fixed width

        sidebar_header = ctk.CTkFrame(sidebar, corner_radius=0, fg_color="transparent")
        sidebar_header.pack(fill="x", padx=4, pady=(4, 0))
        ctk.CTkLabel(sidebar_header, text="Categories", font=("Segoe UI Semibold", 13)).pack(side="left", padx=6, pady=4)
        self.sidebar_count_label = ctk.CTkLabel(sidebar_header, text="", font=("Segoe UI", 10))
        self.sidebar_count_label.pack(side="right", padx=6, pady=4)

        cat_tree_container = ctk.CTkFrame(sidebar, corner_radius=8, fg_color="transparent")
        cat_tree_container.pack(fill="both", expand=True, padx=2, pady=4)

        self.cat_tree = ttk.Treeview(cat_tree_container, show="tree", selectmode="browse")
        cat_vsb = ttk.Scrollbar(cat_tree_container, orient="vertical", command=self.cat_tree.yview)
        self.cat_tree.configure(yscroll=cat_vsb.set)
        self.cat_tree.grid(row=0, column=0, sticky="nsew")
        cat_vsb.grid(row=0, column=1, sticky="ns")
        cat_tree_container.grid_rowconfigure(0, weight=1)
        cat_tree_container.grid_columnconfigure(0, weight=1)
        self.cat_tree.bind("<<TreeviewSelect>>", self._on_category_select)
        # Map sidebar iid -> filter predicate (callable e -> bool); rebuilt every load
        self._cat_filters = {}
        self._active_cat_key = "all"

        tree_container = ctk.CTkFrame(body, corner_radius=12)
        tree_container.pack(side="left", fill="both", expand=True, padx=(4, 10), pady=10)

        # ttk styles are applied by ThemeManager.apply() — see end of __init__.

        # Sidebar tree tag colors get overridden by ThemeManager too, but seed defaults
        # so the widget paints something while waiting for the first apply().
        self.cat_tree.tag_configure("group_header", background="#3a3a3a",
                                    foreground="#ffe49a", font=("Segoe UI", 10, "bold"))
        self.cat_tree.tag_configure("smart", foreground="#a4d4ff")
        self.cat_tree.tag_configure("muted", foreground="#888888")

        # Register widgets that we want repainted on every theme switch
        tm = self.theme_manager
        tm.register_widget(self.frame, tm.ROLE_PANEL)
        tm.register_widget(header, tm.ROLE_PANEL)
        tm.register_widget(top_controls, tm.ROLE_PANEL)
        tm.register_widget(body, tm.ROLE_PANEL)
        tm.register_widget(sidebar, tm.ROLE_PANEL_ALT)
        tm.register_widget(sidebar_header, tm.ROLE_PANEL_ALT)
        tm.register_widget(tree_container, tm.ROLE_PANEL_ALT)
        tm.register_widget(self.load_button, tm.ROLE_PRIMARY)
        tm.register_widget(self.search_box, tm.ROLE_ENTRY)
        tm.register_widget(self.hide_no_sound_cb, tm.ROLE_CHECKBOX)
        tm.register_widget(self.economy_mode_selector, tm.ROLE_GHOST)
        tm.register_widget(self.theme_selector, tm.ROLE_GHOST)
        tm.register_widget(self.appearance_selector, tm.ROLE_GHOST)
        tm.register_widget(self.file_label, tm.ROLE_TEXT_MUTED)
        tm.register_widget(self.sidebar_count_label, tm.ROLE_TEXT_MUTED)

        columns = ("category", "rarity", "stype", "sound", "volume", "effect", "minimap", "context")
        self.tree = ttk.Treeview(tree_container, columns=columns, show="headings", selectmode="browse")

        self.tree.heading("category", text="Category")
        self.tree.heading("rarity", text="Rarity")
        self.tree.heading("stype", text="Type")
        self.tree.heading("sound", text="Sound / ID")
        self.tree.heading("volume", text="Vol")
        self.tree.heading("effect", text="Effect")
        self.tree.heading("minimap", text="Minimap")
        self.tree.heading("context", text="Item Context")

        self.tree.column("category", width=200, anchor="w")
        self.tree.column("rarity", width=160, anchor="w")
        self.tree.column("stype", width=90, anchor="w")
        self.tree.column("sound", width=280, anchor="w")
        self.tree.column("volume", width=55, anchor="center")
        self.tree.column("effect", width=140, anchor="w")
        self.tree.column("minimap", width=150, anchor="w")
        self.tree.column("context", width=440, anchor="w")

        vsb = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscroll=vsb.set, xscroll=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)

        # Zebra striping tags (will be overridden by ThemeManager on every theme switch)
        self.tree.tag_configure("oddrow", background="#2f2f2f")
        self.tree.tag_configure("evenrow", background="#292929")

        # Track both Treeviews with the theme manager so tag colors update on theme change
        self.theme_manager.register_treeview_tags(self.tree, {
            "oddrow": "tree_row_odd",
            "evenrow": "tree_row_even",
        })
        self.theme_manager.register_treeview_tags(self.cat_tree, {
            "group_header": "group_header",
            "smart": "smart",
            "muted": "text_muted",
        })

        self.tree.bind("<<TreeviewSelect>>", self.display_context)

        # Context panel
        context_panel = ctk.CTkFrame(body, corner_radius=12)
        context_panel.pack(fill="x", padx=10, pady=(0, 10))
        self.context_label = ctk.CTkLabel(context_panel, text="Item Context: ", wraplength=1200, justify="left")
        self.context_label.pack(anchor="w", padx=10, pady=10)

        # Options bar
        options = ctk.CTkFrame(tab_edit, corner_radius=12)
        options.pack(fill="x", padx=6, pady=6)

        self.bulk_checkbox = ctk.CTkCheckBox(options, text="Bulk replace/add for all matching rows", variable=self.bulk_mode)
        self.bulk_checkbox.pack(side="left", padx=10, pady=10)

        self.replace_button = ctk.CTkButton(options, text="🔁 Replace / Add Sound…", command=self.replace_sound, width=210)
        self.replace_button.pack(side="left", padx=10, pady=10)

        self.volume_button = ctk.CTkButton(options, text="🔊 Change Volume…", command=self.change_volume, width=170)
        self.volume_button.pack(side="left", padx=10, pady=10)

        # Preview controls
        self.preview_changed_button = ctk.CTkButton(options, text="▶ Play Last Change", command=self.preview_last_change, state="disabled", width=170)
        self.preview_changed_button.pack(side="left", padx=10, pady=10)

        self.preview_selected_button = ctk.CTkButton(options, text="▶ Play Selected", command=self.preview_selected, width=150)
        self.preview_selected_button.pack(side="left", padx=10, pady=10)

        self.stop_button = ctk.CTkButton(options, text="⏹ Stop", command=self.stop_preview, width=120)
        self.stop_button.pack(side="left", padx=10, pady=10)

        # Filtered-set bulk operations (acts on whatever the sidebar+search is currently showing)
        bulk_options = ctk.CTkFrame(tab_edit, corner_radius=12)
        bulk_options.pack(fill="x", padx=6, pady=6)
        ctk.CTkLabel(bulk_options, text="On filtered set:", font=("Segoe UI", 11, "bold")).pack(side="left", padx=(10, 6), pady=10)
        self.bulk_replace_filtered_btn = ctk.CTkButton(
            bulk_options, text="🔁 Replace Sound in Visible…",
            command=self.replace_sound_in_filtered, width=220,
        )
        self.bulk_replace_filtered_btn.pack(side="left", padx=5, pady=10)
        self.bulk_volume_filtered_btn = ctk.CTkButton(
            bulk_options, text="🔊 Set Volume on Visible…",
            command=self.set_volume_in_filtered, width=200,
        )
        self.bulk_volume_filtered_btn.pack(side="left", padx=5, pady=10)
        self.bulk_mute_filtered_btn = ctk.CTkButton(
            bulk_options, text="🔇 Mute Visible (comment out)",
            command=self.mute_filtered, width=220, fg_color="#5b3a0c",
        )
        self.bulk_mute_filtered_btn.pack(side="left", padx=5, pady=10)
        self.bulk_unmute_filtered_btn = ctk.CTkButton(
            bulk_options, text="🔈 Un-mute Visible",
            command=self.unmute_filtered, width=170,
        )
        self.bulk_unmute_filtered_btn.pack(side="left", padx=5, pady=10)

        # Prominent shortcuts to sound-health workflows (right-aligned)
        self.verify_sounds_btn = ctk.CTkButton(
            bulk_options, text="🩺 Verify & Fix Sounds…",
            command=self.verify_and_fix_sounds, width=210,
        )
        self.verify_sounds_btn.pack(side="right", padx=10, pady=10)
        self.unique_sounds_btn = ctk.CTkButton(
            bulk_options, text="🎲 Make Sounds Unique…",
            command=self.make_sounds_unique, width=210,
        )
        self.unique_sounds_btn.pack(side="right", padx=4, pady=10)

        # Color editing buttons (new row)
        color_options = ctk.CTkFrame(tab_edit, corner_radius=12)
        color_options.pack(fill="x", padx=6, pady=6)

        ctk.CTkLabel(color_options, text="Color Tools:", font=("Segoe UI", 11, "bold")).pack(side="left", padx=(10, 5), pady=10)

        self.edit_colors_button = ctk.CTkButton(color_options, text="🎨 Edit Colors…", command=self.edit_colors, width=150)
        self.edit_colors_button.pack(side="left", padx=5, pady=10)

        self.copy_colors_button = ctk.CTkButton(color_options, text="🖌 Copy Colors", command=self.copy_colors, width=140)
        self.copy_colors_button.pack(side="left", padx=5, pady=10)

        self.paste_colors_button = ctk.CTkButton(color_options, text="📋 Paste Colors", command=self.paste_colors, width=140, state="disabled")
        self.paste_colors_button.pack(side="left", padx=5, pady=10)

        self.preview_item_button = ctk.CTkButton(color_options, text="👁 Preview Item", command=self.preview_item_colors, width=140)
        self.preview_item_button.pack(side="left", padx=5, pady=10)

        self.remove_colors_button = ctk.CTkButton(color_options, text="🗑 Remove Colors", command=self.remove_colors, width=150, fg_color="darkred")
        self.remove_colors_button.pack(side="left", padx=5, pady=10)

        # ---------- Status bar with health indicator ----------
        status_bar = ctk.CTkFrame(tab_edit, corner_radius=0, fg_color="transparent")
        status_bar.pack(fill="x", padx=8, pady=(4, 4))
        self.status = ctk.CTkLabel(status_bar, text=f"Ready • {APP_NAME} v{APP_VERSION}", anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        # The health indicator is a clickable pill: ✓ when healthy, ⚠ when broken refs, — when idle.
        # Clicking opens Verify & Fix. It updates after every load/refresh and after every save.
        self.health_indicator = ctk.CTkButton(
            status_bar,
            text="—  no filter loaded",
            command=self.verify_and_fix_sounds,
            width=220,
            height=24,
            corner_radius=12,
            font=("Segoe UI", 10, "bold"),
            fg_color="#3a3a3a",
            hover_color="#4a4a4a",
            text_color="#cccccc",
        )
        self.health_indicator.pack(side="right", padx=(8, 0))

        # Register the remaining themed widgets so they repaint on theme change
        for btn in (self.replace_button, self.volume_button,
                    self.preview_changed_button, self.preview_selected_button,
                    self.stop_button, self.bulk_replace_filtered_btn,
                    self.bulk_volume_filtered_btn, self.bulk_unmute_filtered_btn,
                    self.verify_sounds_btn, self.unique_sounds_btn,
                    self.edit_colors_button, self.copy_colors_button,
                    self.paste_colors_button, self.preview_item_button):
            tm.register_widget(btn, tm.ROLE_PRIMARY)
        for btn in (self.bulk_mute_filtered_btn, self.remove_colors_button):
            tm.register_widget(btn, tm.ROLE_DANGER)
        for frame in (options, bulk_options, color_options, context_panel):
            tm.register_widget(frame, tm.ROLE_PANEL_ALT)
        tm.register_widget(self.bulk_checkbox, tm.ROLE_CHECKBOX)
        tm.register_widget(self.context_label, tm.ROLE_TEXT)
        tm.register_widget(self.status, tm.ROLE_TEXT_MUTED)
        tm.register_widget(status_bar, tm.ROLE_PANEL_ALT)

        # ===== Merge tab (Smart Merge) =====
        try:
            from features.smart_merge_ui import enhance_merge_tab
            # Use new smart merge UI
            self.smart_merge_controller = enhance_merge_tab(tab_merge, self._set_status)
        except Exception as e:
            # Fallback to legacy merge if smart merge fails
            print(f"Smart merge not available, using legacy: {e}")
            self._setup_legacy_merge_tab(tab_merge)

    def _bind_shortcuts(self):
        self.root.bind("<Control-f>", lambda e: (self.search_box.focus_set(), "break"))
        self.root.bind("<Control-o>", lambda e: (self.load_filter(), "break"))
        self.root.bind("<Control-s>", lambda e: (self.save_filter(), "break"))
        self.root.bind("<Control-q>", lambda e: (self._on_close(), "break"))
        self.root.bind("<Control-comma>", lambda e: (self.open_settings_dialog(), "break"))
        self.root.bind("<Control-h>", lambda e: (self.verify_and_fix_sounds(), "break"))
        self.root.bind("<Control-u>", lambda e: (self.make_sounds_unique(), "break"))
        self.root.bind("<F1>", lambda e: (self.show_about_dialog(), "break"))
        self.root.bind("<F5>", lambda e: (self._reload_current_filter(), "break"))

    def _set_status(self, text):
        self.status.configure(text=text)
        self.status.update_idletasks()

    def change_theme(self, palette_name):
        """Live-switch the color palette and persist the choice."""
        self.settings.theme_palette = palette_name
        self.theme_manager.apply(palette_name, self.settings.appearance_mode)
        self._persist_settings()
        self._set_status(f"Theme: {palette_name}")

    def change_appearance_mode(self, mode):
        """Light / Dark / System — applies live via CTk."""
        if mode not in ("Light", "Dark", "System"):
            return
        self.settings.appearance_mode = mode
        self.theme_manager.apply(self.settings.theme_palette, mode)
        self._persist_settings()
        self._set_status(f"Appearance: {mode}")

    def _persist_settings(self):
        try:
            save_settings(self.settings)
        except Exception as e:
            print(f"Warning: could not save settings: {e}")

    # ---------------- Window / dialog sizing ---------------- #

    # Sensible main-window minimums — below these the sidebar + toolbar get clipped
    MIN_MAIN_WIDTH = 1180
    MIN_MAIN_HEIGHT = 740
    DEFAULT_MAIN_WIDTH = 1520
    DEFAULT_MAIN_HEIGHT = 920

    @staticmethod
    def _parse_geometry(geom):
        """Parse a 'WxH+X+Y' geometry string, returning (w, h, x, y) or None."""
        if not geom:
            return None
        try:
            size, *pos = geom.replace("+", " +").replace("-", " -").split()
            w_str, h_str = size.split("x")
            w, h = int(w_str), int(h_str)
            x = int(pos[0]) if len(pos) > 0 else 0
            y = int(pos[1]) if len(pos) > 1 else 0
            return w, h, x, y
        except (ValueError, IndexError):
            return None

    def _geometry_is_on_screen(self, geom):
        """Validate that the geometry's window would be visible on some attached monitor.

        Multi-monitor setups can lose a screen, leaving stored geometry off-screen.
        We require the top-left to be within the *virtual* desktop bounds so we don't
        spawn the window where nobody can grab it.
        """
        parsed = self._parse_geometry(geom)
        if not parsed:
            return False
        w, h, x, y = parsed
        # Use root to query screen dimensions (single primary monitor) and allow some slack
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        # Cover multi-monitor by allowing window starts up to one extra screen width in either direction
        if x < -50 or y < -50:
            return False
        if x > screen_w * 2 or y > screen_h * 2:
            return False
        if w < 300 or h < 200 or w > 10000 or h > 10000:
            return False
        return True

    def _initialize_main_window_geometry(self):
        """Restore saved geometry if it's valid for this machine; otherwise center
        a screen-aware default. Always set minsize so layouts can't be broken."""
        self.root.minsize(self.MIN_MAIN_WIDTH, self.MIN_MAIN_HEIGHT)

        saved = self.settings.window_geometry
        if saved and self._geometry_is_on_screen(saved):
            self.root.geometry(saved)
            return

        # No usable saved state — compute a polite default centered on the primary screen
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = min(self.DEFAULT_MAIN_WIDTH, int(sw * 0.85))
        h = min(self.DEFAULT_MAIN_HEIGHT, int(sh * 0.85))
        w = max(w, self.MIN_MAIN_WIDTH)
        h = max(h, self.MIN_MAIN_HEIGHT)
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _apply_window_icon(self, win):
        """Apply the app icon to a window if available. Silent no-op otherwise."""
        if not APP_ICON_PATH:
            return
        try:
            win.iconbitmap(APP_ICON_PATH)
        except Exception:
            # Some platforms or some window states reject iconbitmap (e.g. non-Windows .ico).
            # Try the cross-platform fallback.
            try:
                from tkinter import PhotoImage
                # PhotoImage doesn't read .ico; only try this if it's a PNG/GIF.
                if APP_ICON_PATH.lower().endswith((".png", ".gif")):
                    img = PhotoImage(file=APP_ICON_PATH)
                    win.iconphoto(False, img)
            except Exception:
                pass

    def _setup_dialog(self, dlg, *,
                      default_size=None, min_size=None,
                      title=None, modal=True, allow_resize=True,
                      parent=None):
        """One-stop pro-grade dialog setup.

        - Sizes the dialog to its natural content size (after update_idletasks),
          capped at 90% of the screen.
        - Centers it on the parent window (falls back to screen if parent isn't mapped).
        - Sets a minsize so the user can resize down but never to a broken state.
        - Sets the app icon, makes the dialog transient + grab_set if modal.
        - Binds Escape to close.
        - For nested dialogs (a dialog opened from another dialog), pass parent= so
          the new dialog is transient to its real parent instead of root.

        Call AFTER you've packed/gridded all the dialog's content widgets.
        """
        if title:
            dlg.title(title)
        self._apply_window_icon(dlg)
        center_parent = parent or self.root
        if modal:
            try:
                dlg.transient(center_parent)
                dlg.grab_set()
            except Exception:
                pass

        dlg.update_idletasks()
        nat_w = dlg.winfo_reqwidth()
        nat_h = dlg.winfo_reqheight()

        if default_size:
            req_w, req_h = default_size
        else:
            req_w, req_h = nat_w, nat_h
        # Add a tiny breathing margin so titles + scrollbars aren't pixel-tight
        req_w = max(req_w, nat_w) + 8
        req_h = max(req_h, nat_h) + 8

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = min(req_w, int(sw * 0.92))
        h = min(req_h, int(sh * 0.92))
        if min_size:
            w = max(w, min_size[0])
            h = max(h, min_size[1])

        # Center on the chosen parent (root, or an outer dialog if nested).
        # If the parent isn't mapped, fall back to centering on the primary screen.
        try:
            center_parent.update_idletasks()
            px = center_parent.winfo_rootx()
            py = center_parent.winfo_rooty()
            pw = center_parent.winfo_width()
            ph = center_parent.winfo_height()
            if pw < 100 or ph < 100:
                raise ValueError
            x = px + max(0, (pw - w) // 2)
            y = py + max(0, (ph - h) // 2)
        except Exception:
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2)
        # Keep within screen
        x = min(max(0, x), max(0, sw - w))
        y = min(max(0, y), max(0, sh - h))

        dlg.geometry(f"{w}x{h}+{x}+{y}")
        if min_size:
            dlg.minsize(*min_size)
        else:
            dlg.minsize(min(640, w), min(400, h))
        if not allow_resize:
            dlg.resizable(False, False)

        # Escape closes any dialog set up through this helper
        dlg.bind("<Escape>", lambda _e: dlg.destroy())

    # ---------------- Menu bar ---------------- #
    def _build_menu_bar(self):
        menubar = tk.Menu(self.root)

        # ----- File -----
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Open Filter…", accelerator="Ctrl+O", command=self.load_filter)
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_filter)
        file_menu.add_command(label="Save As…", command=self.save_filter_as)
        file_menu.add_command(label="Reload from disk", accelerator="F5", command=self._reload_current_filter)
        file_menu.add_separator()
        self._recent_menu = tk.Menu(file_menu, tearoff=False)
        file_menu.add_cascade(label="Recent Filters", menu=self._recent_menu)
        self._rebuild_recent_menu()
        file_menu.add_separator()
        file_menu.add_command(label="Open POE2 Filter Folder", command=self.open_poe2_folder)
        file_menu.add_command(label="Open Current Filter Folder", command=self.open_current_filter_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", accelerator="Ctrl+Q", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        # ----- View -----
        view_menu = tk.Menu(menubar, tearoff=False)

        appearance_menu = tk.Menu(view_menu, tearoff=False)
        for mode in ("System", "Light", "Dark"):
            appearance_menu.add_command(label=mode, command=lambda m=mode: self.change_appearance_mode(m))
        view_menu.add_cascade(label="Appearance Mode", menu=appearance_menu)

        theme_menu = tk.Menu(view_menu, tearoff=False)
        for name in palette_names():
            theme_menu.add_command(label=name, command=lambda n=name: self.change_theme(n))
        view_menu.add_cascade(label="Color Theme", menu=theme_menu)

        view_menu.add_separator()
        view_menu.add_command(label="Toggle Show-only-with-sound",
                              command=lambda: (self.hide_no_sound_var.set(not self.hide_no_sound_var.get()), self.apply_filter()))
        menubar.add_cascade(label="View", menu=view_menu)

        # ----- Tools -----
        tools_menu = tk.Menu(menubar, tearoff=False)
        tools_menu.add_command(label="Verify & Fix Sounds…", accelerator="Ctrl+H", command=self.verify_and_fix_sounds)
        tools_menu.add_command(label="Make Sounds Unique…", accelerator="Ctrl+U", command=self.make_sounds_unique)
        tools_menu.add_command(label="Check Filter Compatibility…", command=self.check_filter_compatibility)
        tools_menu.add_separator()
        tools_menu.add_command(label="Emphasize by Tier…", command=self.emphasize_by_tier)
        tools_menu.add_command(label="Randomize Visuals…", command=self.randomize_visuals)
        tools_menu.add_command(label="Economy Tier Visuals…", command=self.open_economy_tier_visuals)
        tools_menu.add_separator()
        tools_menu.add_command(label="Sound File Manager…", command=self.open_sound_manager)
        tools_menu.add_command(label="Filter Statistics…", command=self.show_filter_statistics)
        tools_menu.add_separator()
        tools_menu.add_command(label="Settings…", accelerator="Ctrl+,", command=self.open_settings_dialog)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        # ----- Help -----
        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="POE2 Filter Syntax (web)",
                              command=lambda: webbrowser.open("https://www.pathofexile.com/forum/view-thread/3683711"))
        help_menu.add_command(label="FilterBlade Editor (web)",
                              command=lambda: webbrowser.open("https://www.filterblade.xyz/?game=Poe2"))
        help_menu.add_separator()
        help_menu.add_command(label=f"About {APP_NAME}", accelerator="F1", command=self.show_about_dialog)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

    def _rebuild_recent_menu(self):
        self._recent_menu.delete(0, "end")
        if not self.settings.recent_files:
            self._recent_menu.add_command(label="(empty)", state="disabled")
            return
        for i, p in enumerate(self.settings.recent_files):
            short = p if len(p) < 64 else "…" + p[-60:]
            self._recent_menu.add_command(
                label=f"{i+1}. {short}",
                command=lambda pp=p: self.load_filter_from_recent(pp),
            )
        self._recent_menu.add_separator()
        self._recent_menu.add_command(label="Clear Recent",
                                       command=lambda: (setattr(self.settings, 'recent_files', []),
                                                         self._persist_settings(), self._rebuild_recent_menu()))

    # ---------------- Lifecycle / convenience ---------------- #
    def _on_close(self):
        try:
            self.settings.window_geometry = self.root.winfo_geometry()
            if self.filter_path:
                self.settings.last_filter_path = self.filter_path
            self._persist_settings()
        except Exception:
            pass
        try:
            self.stop_preview()
        except Exception:
            pass
        self.root.destroy()

    def _post_launch(self):
        """Run after the main loop starts: autoload last filter or offer POE2 folder."""
        # Try to autoload last opened filter
        if (self.settings.autoload_last
                and self.settings.last_filter_path
                and os.path.isfile(self.settings.last_filter_path)):
            try:
                self.load_filter_from_recent(self.settings.last_filter_path)
                return
            except Exception:
                pass

        # First-launch / no last file: look for the POE2 folder
        poe2_dir = get_poe2_filter_directory()
        if poe2_dir:
            try:
                filters = [f for f in os.listdir(poe2_dir) if f.lower().endswith(".filter")]
            except OSError:
                filters = []
            if filters:
                if messagebox.askyesno(
                    "POE2 folder detected",
                    f"Found {len(filters)} .filter file(s) in:\n  {poe2_dir}\n\nOpen one now?",
                ):
                    chosen = filedialog.askopenfilename(
                        initialdir=poe2_dir,
                        filetypes=[("Filter Files", "*.filter")],
                    )
                    if chosen:
                        self.load_filter_from_recent(chosen)

    def _reload_current_filter(self):
        if not self.filter_path or not os.path.isfile(self.filter_path):
            self._set_status("Nothing to reload.")
            return
        self.load_filter_from_path(self.filter_path)
        self._set_status(f"Reloaded {os.path.basename(self.filter_path)}")

    def save_filter_as(self):
        if not self.lines:
            messagebox.showinfo("Nothing to save", "Load or build a filter first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".filter",
            filetypes=[("Filter Files", "*.filter")],
            initialfile=os.path.basename(self.filter_path) if self.filter_path else "untitled.filter",
        )
        if not path:
            return
        try:
            save_filter_file(path, self.lines, create_backup=False)
            self.filter_path = path
            self.file_label.configure(text=os.path.basename(path))
            self.settings.add_recent(path)
            self._persist_settings()
            self._rebuild_recent_menu()
            self._set_status(f"Saved as {path}")
        except Exception as e:
            messagebox.showerror("Save error", str(e))

    def load_filter_from_recent(self, path):
        """Load a recent file path without showing a file dialog."""
        if not os.path.isfile(path):
            messagebox.showwarning("Not found", f"This file no longer exists:\n{path}")
            try:
                self.settings.recent_files.remove(path)
                self._persist_settings()
                self._rebuild_recent_menu()
            except ValueError:
                pass
            return
        self.load_filter_from_path(path)
        self.settings.add_recent(path)
        self._persist_settings()
        self._rebuild_recent_menu()

    def open_poe2_folder(self):
        p = get_poe2_filter_directory()
        if not p:
            messagebox.showinfo("POE2 folder", "Couldn't auto-detect the POE2 filter folder on this system.")
            return
        self._open_folder(p)

    def open_current_filter_folder(self):
        if not self.filter_path:
            messagebox.showinfo("No filter", "Load a filter file first.")
            return
        self._open_folder(os.path.dirname(self.filter_path))

    def _open_folder(self, path):
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("Open folder failed", str(e))

    # ---------------- I/O (refactored to use core modules) ---------------- #
    def load_filter(self):
        path = filedialog.askopenfilename(filetypes=[("Filter Files", "*.filter")])
        if not path:
            return

        try:
            self.filter_path = path
            # Use new core.file_operations
            self.lines = load_filter_file(self.filter_path)
            self._snapshot_on_load(self.filter_path)
            self.file_label.configure(text=os.path.basename(self.filter_path))
            self._set_status(f"Loaded: {self.filter_path}")
            self.refresh_filter_data()
        except Exception as e:
            messagebox.showerror("Load Error", f"Failed to load filter:\n{e}")
            self._set_status(f"Error loading file")
            return

        if self.settings.auto_check_compatibility:
            self._run_compatibility_check(auto=True)

    def save_filter(self):
        """Save filter using new modular system with automatic backup."""
        if not self.filter_path:
            return

        try:
            # Use new core.file_operations (includes automatic backup)
            save_filter_file(self.filter_path, self.lines, create_backup=self.settings.create_backups, max_backups=self.settings.max_backups)
            self._set_status("Saved with automatic backup")
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save filter:\n{e}")
            return

        # Verify-on-save: silently scan and update the health indicator.
        # If anything is broken, _update_health_indicator() overwrites the status line
        # with a Ctrl+H hint. No dialog; the user isn't interrupted.
        if self.settings.verify_on_save:
            self._update_health_indicator()

    # ------------- Parsing (using core.parser patterns) --------------- #
    SHOWHIDE = ("Show", "Hide")

    def refresh_filter_data(self):
        """Parse filter file and populate table - uses regex from core.parser."""
        self.filter_data.clear()
        self.filtered_data.clear()
        for row in self.tree.get_children():
            self.tree.delete(row)

        current_block = []
        start_idx = 0
        current_section = "(uncategorized)"
        current_subsection = ""
        block_section = current_section
        block_subsection = current_subsection
        # Preserve document order, store (id, name)
        sections_seen = []          # list of section names in order
        # Map section_name -> list of subsection names (in order)
        subsections_by_section = {}

        for i, raw in enumerate(self.lines):
            stripped = raw.strip()

            sec_m = SECTION_RE.match(stripped)
            if sec_m:
                current_section = sec_m.group(2).strip()
                current_subsection = ""  # reset when new section begins
                if current_section not in sections_seen:
                    sections_seen.append(current_section)
                    subsections_by_section.setdefault(current_section, [])
                continue

            sub_m = SUBSECTION_RE.match(stripped)
            if sub_m:
                current_subsection = sub_m.group(2).strip()
                subsections_by_section.setdefault(current_section, [])
                if current_subsection and current_subsection not in subsections_by_section[current_section]:
                    subsections_by_section[current_section].append(current_subsection)
                continue

            if stripped.startswith(self.SHOWHIDE):
                if current_block:
                    self.process_block(current_block, start_idx, block_section, block_subsection)
                current_block = [stripped]
                start_idx = i
                block_section = current_section
                block_subsection = current_subsection
            else:
                current_block.append(stripped)
        if current_block:
            self.process_block(current_block, start_idx, block_section, block_subsection)

        self.filtered_data = list(self.filter_data)
        self._rebuild_category_tree(sections_seen, subsections_by_section)
        self.populate_tree()
        # Summary status
        with_sound = sum(1 for e in self.filtered_data if e["stype"] != "None")
        no_sound = sum(1 for e in self.filtered_data if e["stype"] == "None")
        self._set_status(
            f"{len(self.filtered_data)} blocks • with sound: {with_sound} • no sound: {no_sound} "
            f"• {len(sections_seen)} sections • {sum(len(v) for v in subsections_by_section.values())} subsections"
        )
        # Refresh the health pill (silent; may overwrite the status if anything is broken)
        self._update_health_indicator()

    def _parse_block_meta(self, block):
        """Parse block metadata."""
        rarity_lines = [l for l in block if l.startswith("Rarity")]
        rarity = ", ".join(rarity_lines) if rarity_lines else "Rarity Unknown"

        keys = (
            "Class", "BaseType", "ItemLevel", "DropLevel", "Sockets", "GemLevel", "HasInfluence",
            "BaseDefencePercentile", "Corrupted", "StackSize", "AreaLevel", "AnyEnchantment", "HasExplicitMod"
        )
        setting_keys = ("SetFontSize", "SetTextColor", "SetBorderColor", "SetBackgroundColor", "PlayEffect", "MinimapIcon")

        context_lines = [l for l in block if l.startswith(keys) or l.startswith(setting_keys)]
        effect_line = next((l for l in block if l.startswith("PlayEffect")), "")
        minimap_line = next((l for l in block if l.startswith("MinimapIcon")), "")

        context = " ; ".join(context_lines)
        return rarity, context, effect_line, minimap_line

    def process_block(self, block, start_idx, category="(uncategorized)", subcategory=""):
        """Process a single block - uses patterns from core.parser."""
        rarity, context, effect_line, minimap_line = self._parse_block_meta(block)
        header_line = block[0] if block else ""
        type_m = TYPE_TAG_RE.search(header_line)
        tier_m = TIER_TAG_RE.search(header_line)
        style_m = STYLE_TAG_RE.search(header_line)
        block_type = type_m.group(1) if type_m else ""
        block_tier = tier_m.group(1) if tier_m else ""
        block_style = style_m.group(1) if style_m else ""

        extra = {
            "category": category,
            "subcategory": subcategory,
            "block_type": block_type,
            "block_tier": block_tier,
            "block_style": block_style,
        }

        found_any = False
        for l in block:
            m_custom = SOUND_RE_CUSTOM.match(l)
            m_play = SOUND_RE_PLAY.match(l)
            if m_custom:
                found_any = True
                comment_prefix, kw, filename, vol = m_custom.groups()
                vol = int(vol) if vol else None
                entry = {
                    **extra,
                    "rarity": rarity,
                    "stype": "Custom",
                    "sound": filename,
                    "volume": vol if vol is not None else "",
                    "effect": effect_line.replace("\t","").strip(),
                    "minimap": minimap_line.replace("\t","").strip(),
                    "context": context,
                    "header": block[0] if block else "",
                    "start_idx": start_idx,
                    "orig_line": l,
                    "commented": bool(comment_prefix),
                    "keyword": kw
                }
                self.filter_data.append(entry)
            elif m_play:
                found_any = True
                comment_prefix, kw, sid, vol = m_play.groups()
                vol = int(vol) if vol else None
                entry = {
                    **extra,
                    "rarity": rarity,
                    "stype": "Play",
                    "sound": sid,
                    "volume": vol if vol is not None else "",
                    "effect": effect_line.replace("\t","").strip(),
                    "minimap": minimap_line.replace("\t","").strip(),
                    "context": context,
                    "header": block[0] if block else "",
                    "start_idx": start_idx,
                    "orig_line": l,
                    "commented": bool(comment_prefix),
                    "keyword": kw
                }
                self.filter_data.append(entry)

        if not found_any:
            # No sound entry
            entry = {
                **extra,
                "rarity": rarity,
                "stype": "None",
                "sound": "No sound",
                "volume": "",
                "effect": effect_line.replace("\t","").strip(),
                "minimap": minimap_line.replace("\t","").strip(),
                "context": context,
                "header": block[0] if block else "",
                "start_idx": start_idx,
                "orig_line": "",
                "commented": False,
                "keyword": ""
            }
            self.filter_data.append(entry)

    # ---------- Helpers to locate/edit blocks ---------- #
    def _block_bounds(self, start_idx):
        """Return (start_idx, end_idx_exclusive) for the block beginning at start_idx."""
        i = start_idx + 1
        while i < len(self.lines):
            t = self.lines[i].strip()
            if t.startswith(self.SHOWHIDE):
                break
            i += 1
        return start_idx, i

    def _detect_indent(self, start_idx, end_idx):
        indent = ""
        for j in range(start_idx + 1, end_idx):
            line = self.lines[j]
            if not line.strip():
                continue
            leading = len(line) - len(line.lstrip(" \t"))
            if leading > 0:
                indent = line[:leading]
                break
        return indent

    # ------------- Table ops ------------- #
    def populate_tree(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        base_list = [e for e in self.filtered_data if not (self.hide_no_sound_var.get() and e["stype"] == "None")]

        for idx, entry in enumerate(base_list):
            volume_display = entry["volume"] if entry["volume"] != "" else ""
            effect_short = entry["effect"].replace("PlayEffect", "").strip()
            minimap_short = entry["minimap"].replace("MinimapIcon", "").strip()
            tag = "oddrow" if idx % 2 else "evenrow"
            self.tree.insert("", "end", values=(
                entry.get("category", ""),
                entry["rarity"],
                entry["stype"],
                entry["sound"],
                volume_display,
                effect_short,
                minimap_short,
                entry["context"]
            ), tags=(tag,))

    # ===== Smart curated groups (logical supersets of sections) =====
    SMART_GROUPS = [
        ("All Currency", [
            "Currency - Exceptions - Leveling Currencies",
            "Currency - Regular Currency Tiering",
            "Currency - SPECIAL",
            "Remaining Currency",
        ]),
        ("All Waystones / Maps", [
            "Waystones",
            "Normal Waystone Progression",
            "Misc Map Like",
            "Misc Map Items",
            "Splinters, Tablets, Fragments",
        ]),
        ("All Gear (Endgame)", [
            "Normal and Magic Items: Endgame",
            "Endgame - Rare - Jewellery",
            "Endgame - Rare - Gear",
            "Untiered Rare Catcher",
            "Rare Item Decorators",
        ]),
        ("All Uniques & Exotics", [
            "Uniques",
            "Exotic Bases",
            "Exceptional Items",
            "IDENTIFIED MODS: RECOMBINATOR MODS",
        ]),
        ("All Sockets / Gems / Jewels", [
            "Socketables - Runes and Soul Cores",
            "Gems and Uncut Gems",
            "Jewels",
            "Relics",
        ]),
        ("All Flasks & Charms", [
            "Endgame Flasks",
            "Endgame Charms",
            "Leveling - Life Mana Flasks",
        ]),
        ("All Leveling", [
            "Leveling - Salvagable",
            "Leveling - Hide outdated leveling flasks",
            "Leveling - Life Mana Flasks",
            "Leveling - Rules",
            "Leveling - Useful magic and normal items",
        ]),
        ("All Hide Rules", [
            "Normal, Magic, Rare Hiding Rules",
            "Hide Layer 1 - Normal and Magic Endgame Gear",
            "Hide Layer 2 - Rare Gear",
            "Endgame - Conditional Hide Layers",
            "Leveling - Hide outdated leveling flasks",
        ]),
    ]

    @staticmethod
    def _count_pair(entries):
        with_sound = sum(1 for e in entries if e.get("stype") != "None")
        return with_sound, len(entries)

    def _rebuild_category_tree(self, sections, subsections_by_section):
        """Populate the sidebar treeview with smart groups + sections + subsections.

        Each tree node stores a key in self._cat_filters mapping to a predicate.
        """
        self.cat_tree.delete(*self.cat_tree.get_children())
        self._cat_filters = {}

        def predicate_for_section(section_name):
            return lambda e, s=section_name: e.get("category") == s

        def predicate_for_subsection(section_name, sub_name):
            return lambda e, s=section_name, x=sub_name: (
                e.get("category") == s and e.get("subcategory") == x
            )

        def predicate_for_group(section_names):
            sset = set(section_names)
            return lambda e, ss=sset: e.get("category") in ss

        # ---------- Root: All Categories ----------
        all_w, all_t = self._count_pair(self.filter_data)
        all_iid = self.cat_tree.insert("", "end", text=f"★  All Categories   ({all_w}/{all_t})", open=True)
        self._cat_filters[all_iid] = ("all", lambda e: True)

        # ---------- Sound state ----------
        sound_header = self.cat_tree.insert("", "end", text="Sound State", tags=("group_header",), open=True)
        self._cat_filters[sound_header] = ("noop", None)
        with_sound_entries = [e for e in self.filter_data if e.get("stype") != "None"]
        without_sound_entries = [e for e in self.filter_data if e.get("stype") == "None"]
        ws_iid = self.cat_tree.insert(sound_header, "end",
                                       text=f"🔊 With Sound   ({len(with_sound_entries)})",
                                       tags=("smart",))
        self._cat_filters[ws_iid] = ("with_sound", lambda e: e.get("stype") != "None")
        wos_iid = self.cat_tree.insert(sound_header, "end",
                                        text=f"🔇 Without Sound   ({len(without_sound_entries)})",
                                        tags=("smart",))
        self._cat_filters[wos_iid] = ("without_sound", lambda e: e.get("stype") == "None")

        # Commented-out sound rules (disabled but present)
        commented = [e for e in self.filter_data if e.get("commented")]
        if commented:
            cm_iid = self.cat_tree.insert(sound_header, "end",
                                           text=f"#  Disabled (commented)   ({len(commented)})",
                                           tags=("smart", "muted"))
            self._cat_filters[cm_iid] = ("commented", lambda e: bool(e.get("commented")))

        # ---------- Smart groups ----------
        smart_header = self.cat_tree.insert("", "end", text="Smart Groups", tags=("group_header",), open=True)
        self._cat_filters[smart_header] = ("noop", None)
        for label, section_list in self.SMART_GROUPS:
            entries = [e for e in self.filter_data if e.get("category") in set(section_list)]
            if not entries:
                continue
            w, t = self._count_pair(entries)
            iid = self.cat_tree.insert(smart_header, "end",
                                        text=f"{label}   ({w}/{t})",
                                        tags=("smart",))
            self._cat_filters[iid] = (f"smart:{label}", predicate_for_group(section_list))

        # ---------- Sections (raw, in document order) with subsections ----------
        sections_header = self.cat_tree.insert("", "end", text="Sections", tags=("group_header",), open=True)
        self._cat_filters[sections_header] = ("noop", None)
        for section_name in sections:
            sec_entries = [e for e in self.filter_data if e.get("category") == section_name]
            if not sec_entries:
                continue
            w, t = self._count_pair(sec_entries)
            sec_iid = self.cat_tree.insert(sections_header, "end",
                                            text=f"{section_name}   ({w}/{t})")
            self._cat_filters[sec_iid] = (f"section:{section_name}", predicate_for_section(section_name))

            # Subsections, if any
            subs = subsections_by_section.get(section_name, [])
            for sub_name in subs:
                sub_entries = [e for e in sec_entries if e.get("subcategory") == sub_name]
                if not sub_entries:
                    continue
                w2, t2 = self._count_pair(sub_entries)
                sub_iid = self.cat_tree.insert(sec_iid, "end",
                                                text=f"↳ {sub_name}   ({w2}/{t2})")
                self._cat_filters[sub_iid] = (
                    f"sub:{section_name}::{sub_name}",
                    predicate_for_subsection(section_name, sub_name),
                )

            # "$type->" breakdown inside the section (only if there are at least 2 distinct types)
            types_in_section = {}
            for e in sec_entries:
                bt = e.get("block_type") or ""
                if not bt:
                    continue
                types_in_section.setdefault(bt, []).append(e)
            if len(types_in_section) >= 2:
                types_header = self.cat_tree.insert(sec_iid, "end",
                                                     text="(by $type->)", tags=("muted",))
                self._cat_filters[types_header] = ("noop", None)
                for bt, ts_entries in sorted(types_in_section.items(), key=lambda kv: (-len(kv[1]), kv[0])):
                    tw, tt = self._count_pair(ts_entries)
                    bt_iid = self.cat_tree.insert(types_header, "end",
                                                   text=f"$type->{bt}   ({tw}/{tt})",
                                                   tags=("muted",))
                    self._cat_filters[bt_iid] = (
                        f"type:{section_name}::{bt}",
                        (lambda e, s=section_name, x=bt:
                            e.get("category") == s and e.get("block_type") == x),
                    )

        # Update sidebar summary
        try:
            self.sidebar_count_label.configure(text=f"{len(sections)} sections")
        except Exception:
            pass

        # Default selection: All
        if all_iid in self._cat_filters:
            self.cat_tree.selection_set(all_iid)
            self.cat_tree.focus(all_iid)
            self._active_cat_key = "all"

    def _on_category_select(self, _event=None):
        sel = self.cat_tree.selection()
        if not sel:
            return
        iid = sel[0]
        entry = self._cat_filters.get(iid)
        if not entry:
            return
        key, pred = entry
        if key == "noop" or pred is None:
            # Header rows aren't filterable; bounce selection back to active row if any
            return
        self._active_cat_key = key
        self.apply_filter()

    def apply_filter(self, event=None):
        keyword = self.search_box.get().lower()

        # Look up the active sidebar predicate
        predicate = lambda e: True
        scope_label = ""
        sel = self.cat_tree.selection() if hasattr(self, "cat_tree") else ()
        if sel:
            entry = self._cat_filters.get(sel[0])
            if entry:
                key, pred = entry
                if pred is not None and key != "noop":
                    predicate = pred
                    raw_label = self.cat_tree.item(sel[0], "text") if sel else ""
                    scope_label = raw_label.split("   (")[0].strip() if raw_label else ""

        self.filtered_data = []
        for entry in self.filter_data:
            if not predicate(entry):
                continue
            hay = " ".join([
                str(entry.get("category","")),
                str(entry.get("subcategory","")),
                str(entry.get("block_type","")),
                str(entry.get("block_tier","")),
                str(entry.get("rarity","")),
                str(entry.get("stype","")),
                str(entry.get("sound","")),
                str(entry.get("volume","")),
                str(entry.get("effect","")),
                str(entry.get("minimap","")),
                str(entry.get("context",""))
            ]).lower()
            if keyword in hay:
                self.filtered_data.append(entry)

        self.populate_tree()
        visible = len(self.tree.get_children())
        w, t = self._count_pair(self.filtered_data)
        scope = f"[{scope_label}] " if scope_label and scope_label != "★  All Categories" else ""
        self._set_status(f"{scope}{visible} visible rows • {w} with sound / {t} total")

    def _get_selected_entry(self):
        selected = self.tree.focus()
        if not selected:
            return None
        values = self.tree.item(selected)["values"]
        category, rarity, stype, sound, volume, effect_short, minimap_short, context = values

        for e in self.filter_data:
            if (
                e.get("category", "") == category and
                e["rarity"] == rarity and
                e["stype"] == stype and
                str(e["sound"]) == str(sound) and
                str(e["volume"]) == (str(volume) if volume != "" else "") and
                e["context"] == context
            ):
                return e
        return None

    def display_context(self, event):
        selected = self.tree.focus()
        if selected:
            values = self.tree.item(selected)["values"]
            category = values[0]
            context = values[7]
            self.context_label.configure(text=f"[{category}]   {context}")

    # -------- Replace / Add / Volume ops (using core.file_operations for file copying) ------- #
    def _update_block_lines(self, start_idx, updater):
        i = start_idx
        while i < len(self.lines):
            stripped = self.lines[i].strip()
            if (stripped.startswith(self.SHOWHIDE)) and i != start_idx:
                break
            new_line = updater(self.lines[i])
            if new_line is not None:
                self.lines[i] = new_line
            i += 1

    def _insert_custom_sound(self, start_idx, filename, volume=300):
        b_start, b_end = self._block_bounds(start_idx)
        indent = self._detect_indent(b_start, b_end)
        new_line = f'{indent}CustomAlertSound "{filename}" {volume}\n'
        self.lines.insert(b_end, new_line)

    def replace_sound(self):
        sel = self._get_selected_entry()
        if not sel:
            messagebox.showwarning("No Selection", "Please select a row first.")
            return

        new_sound_path = filedialog.askopenfilename(filetypes=[("Audio/Video Files", "*.wav *.ogg *.mp3 *.aac *.flac *.m4a *.wmv *.mp4 *.mkv *.webm *.opus")])
        if not new_sound_path:
            return

        new_filename = os.path.basename(new_sound_path)
        dest_dir = os.path.dirname(self.filter_path)

        try:
            # Use new core.file_operations.copy_sound_file
            dest_path = copy_sound_file(new_sound_path, dest_dir)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to copy sound file: {e}")
            return

        # Rest of the logic remains the same
        def add_to_entry(entry):
            if entry["stype"] == "None":
                self._insert_custom_sound(entry["start_idx"], new_filename, volume=300)
                return True
            return False

        def replace_in_entry(entry):
            def updater(line):
                raw = line.rstrip("\n")
                stripped = raw.strip()
                leading = raw[:len(raw) - len(raw.lstrip(" \t"))]

                m_c = SOUND_RE_CUSTOM.match(stripped)
                m_p = SOUND_RE_PLAY.match(stripped)

                if entry["stype"] == "Custom" and m_c:
                    comment_prefix, kw, filename, vol = m_c.groups()
                    if filename == entry["sound"]:
                        vol_part = f" {vol}" if vol else ""
                        prefix = (comment_prefix or "") + kw
                        return f'{leading}{prefix} "{new_filename}"{vol_part}\n'
                elif entry["stype"] == "Play" and m_p:
                    comment_prefix, kw, sid, vol = m_p.groups()
                    if sid == str(entry["sound"]):
                        vol_part = f" {vol}" if vol else ""
                        prefix = (comment_prefix or "")
                        return f'{leading}{prefix}CustomAlertSound "{new_filename}"{vol_part}\n'
                return None

            self._update_block_lines(entry["start_idx"], updater)
            return True

        touched = 0
        if self.bulk_mode.get():
            if sel["stype"] == "None":
                for e in list(self.filter_data):
                    if e["stype"] == "None":
                        add_to_entry(e)
                        touched += 1
            else:
                for e in list(self.filter_data):
                    if str(e["sound"]) == str(sel["sound"]) and e["stype"] == sel["stype"]:
                        replace_in_entry(e)
                        touched += 1
        else:
            if sel["stype"] == "None":
                add_to_entry(sel)
                touched = 1
            else:
                replace_in_entry(sel)
                touched = 1

        if touched == 0:
            messagebox.showinfo("No Changes", "Nothing to update.")
            return

        try:
            self.save_filter()
            self.last_changed_path = dest_path
            self.preview_changed_button.configure(state="normal")
            # (Removed redundant Success popup — status bar now reports: f"Applied sound to {touched} block(s).")
            self._set_status(f"Applied '{new_filename}' to {touched} block(s)")
            self.refresh_filter_data()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update filter: {e}")

    def change_volume(self):
        sel = self._get_selected_entry()
        if not sel:
            messagebox.showwarning("No Selection", "Please select a sound row to change volume.")
            return
        if sel["stype"] == "None":
            messagebox.showinfo("No sound", "This block has no sound yet. Use 'Replace / Add Sound…' to add one first.")
            return

        new_vol = simpledialog.askinteger("Volume", "Enter new volume (0-300):", minvalue=0, maxvalue=300, parent=self.root)
        if new_vol is None:
            return

        def do_update(entry):
            def updater(line):
                raw = line.rstrip("\n")
                stripped = raw.strip()
                leading = raw[:len(raw) - len(raw.lstrip(" \t"))]

                m_c = SOUND_RE_CUSTOM.match(stripped)
                m_p = SOUND_RE_PLAY.match(stripped)

                if entry["stype"] == "Custom" and m_c:
                    comment_prefix, kw, filename, vol = m_c.groups()
                    if filename == entry["sound"]:
                        prefix = (comment_prefix or "") + kw
                        return f'{leading}{prefix} "{filename}" {new_vol}\n'
                elif entry["stype"] == "Play" and m_p:
                    comment_prefix, kw, sid, vol = m_p.groups()
                    if sid == str(entry["sound"]):
                        prefix = (comment_prefix or "") + kw
                        return f'{leading}{prefix} {sid} {new_vol}\n'
                return None

            self._update_block_lines(entry["start_idx"], updater)

        if self.bulk_mode.get():
            for e in self.filter_data:
                if str(e["sound"]) == str(sel["sound"]) and e["stype"] == sel["stype"]:
                    do_update(e)
        else:
            do_update(sel)

        try:
            self.save_filter()
            # (Removed redundant Success popup — status bar now reports: f"Updated volume to {new_vol}.")
            self._set_status(f"Updated volume to {new_vol}")
            self.refresh_filter_data()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update filter: {e}")

    # ================== Filtered-set bulk operations ================== #
    def _filtered_block_iter(self):
        """Yield (start_idx, sample_entry) once per unique block in self.filtered_data, preserving order."""
        seen = set()
        for e in self.filtered_data:
            sidx = e["start_idx"]
            if sidx in seen:
                continue
            seen.add(sidx)
            yield sidx, e

    def replace_sound_in_filtered(self):
        if not self.filter_path:
            messagebox.showwarning("No filter", "Load a filter file first.")
            return
        if not self.filtered_data:
            messagebox.showinfo("Nothing to replace", "The visible set is empty.")
            return

        blocks = list(self._filtered_block_iter())
        with_sound = sum(1 for _, e in blocks if e["stype"] != "None")
        without_sound = len(blocks) - with_sound
        if not messagebox.askyesno(
            "Bulk Replace",
            f"Replace sound on {len(blocks)} visible block(s)?\n"
            f"  • {with_sound} will have their sound replaced\n"
            f"  • {without_sound} have no sound and will have one ADDED",
        ):
            return

        new_sound_path = filedialog.askopenfilename(
            filetypes=[("Audio/Video Files", "*.wav *.ogg *.mp3 *.aac *.flac *.m4a *.wmv *.mp4 *.mkv *.webm *.opus")]
        )
        if not new_sound_path:
            return

        new_filename = os.path.basename(new_sound_path)
        dest_dir = os.path.dirname(self.filter_path)
        try:
            dest_path = copy_sound_file(new_sound_path, dest_dir)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to copy sound file: {e}")
            return

        # Process blocks in descending start_idx so any inserts don't shift earlier indices
        ordered = sorted(blocks, key=lambda be: be[0], reverse=True)
        touched = 0
        for start_idx, sample in ordered:
            b_start, b_end = self._block_bounds(start_idx)
            replaced_any = False
            for i in range(b_start, b_end):
                raw = self.lines[i].rstrip("\n")
                stripped = raw.strip()
                leading = raw[:len(raw) - len(raw.lstrip(" \t"))]
                m_c = SOUND_RE_CUSTOM.match(stripped)
                m_p = SOUND_RE_PLAY.match(stripped)
                if m_c:
                    comment_prefix, kw, _filename, vol = m_c.groups()
                    vol_part = f" {vol}" if vol else " 300"
                    self.lines[i] = f'{leading}{(comment_prefix or "")}{kw} "{new_filename}"{vol_part}\n'
                    replaced_any = True
                elif m_p:
                    comment_prefix, kw, _sid, vol = m_p.groups()
                    vol_part = f" {vol}" if vol else " 300"
                    self.lines[i] = f'{leading}{(comment_prefix or "")}CustomAlertSound "{new_filename}"{vol_part}\n'
                    replaced_any = True
            if not replaced_any:
                self._insert_custom_sound(start_idx, new_filename, volume=300)
            touched += 1

        try:
            self.save_filter()
            self.last_changed_path = dest_path
            self.preview_changed_button.configure(state="normal")
            self._set_status(f"Bulk-applied '{new_filename}' to {touched} block(s)")
            # (Removed redundant Success popup — status bar now reports: f"Replaced sound in {touched} block(s).")
            self.refresh_filter_data()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update filter: {e}")

    def set_volume_in_filtered(self):
        if not self.filter_path or not self.filtered_data:
            messagebox.showinfo("Nothing to update", "No visible rows.")
            return
        eligible = [e for e in self.filtered_data if e["stype"] != "None"]
        if not eligible:
            messagebox.showinfo("No sound rows", "None of the visible rows have a sound.")
            return

        new_vol = simpledialog.askinteger(
            "Volume",
            f"Set volume on {len(eligible)} visible sound row(s) (0-300):",
            minvalue=0, maxvalue=300, parent=self.root,
        )
        if new_vol is None:
            return

        targets = {(e["start_idx"], str(e["sound"]), e["stype"]) for e in eligible}
        target_starts = sorted({e["start_idx"] for e in eligible})
        touched = 0
        for start_idx in target_starts:
            b_start, b_end = self._block_bounds(start_idx)
            for i in range(b_start, b_end):
                raw = self.lines[i].rstrip("\n")
                stripped = raw.strip()
                leading = raw[:len(raw) - len(raw.lstrip(" \t"))]
                m_c = SOUND_RE_CUSTOM.match(stripped)
                m_p = SOUND_RE_PLAY.match(stripped)
                if m_c:
                    comment_prefix, kw, filename, _vol = m_c.groups()
                    if (start_idx, filename, "Custom") in targets:
                        self.lines[i] = f'{leading}{(comment_prefix or "")}{kw} "{filename}" {new_vol}\n'
                        touched += 1
                elif m_p:
                    comment_prefix, kw, sid, _vol = m_p.groups()
                    if (start_idx, str(sid), "Play") in targets:
                        self.lines[i] = f'{leading}{(comment_prefix or "")}{kw} {sid} {new_vol}\n'
                        touched += 1
        try:
            self.save_filter()
            self._set_status(f"Set volume {new_vol} on {touched} sound line(s)")
            # (Removed redundant Success popup — status bar now reports: f"Updated volume on {touched} row(s).")
            self.refresh_filter_data()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update filter: {e}")

    def _toggle_mute_filtered(self, mute):
        if not self.filter_path or not self.filtered_data:
            messagebox.showinfo("Nothing to update", "No visible rows.")
            return
        if mute:
            eligible = [e for e in self.filtered_data if e["stype"] != "None" and not e.get("commented")]
            verb, infinitive = "Mute", "comment out"
        else:
            eligible = [e for e in self.filtered_data if e["stype"] != "None" and e.get("commented")]
            verb, infinitive = "Un-mute", "uncomment"
        if not eligible:
            messagebox.showinfo(f"Nothing to {verb.lower()}", f"No eligible rows to {infinitive} in the visible set.")
            return
        if not messagebox.askyesno(
            f"Bulk {verb}",
            f"{verb} {len(eligible)} visible sound row(s)?",
        ):
            return

        targets = {(e["start_idx"], str(e["sound"]), e["stype"]) for e in eligible}
        target_starts = sorted({e["start_idx"] for e in eligible})
        touched = 0
        for start_idx in target_starts:
            b_start, b_end = self._block_bounds(start_idx)
            for i in range(b_start, b_end):
                raw = self.lines[i].rstrip("\n")
                stripped = raw.strip()
                leading = raw[:len(raw) - len(raw.lstrip(" \t"))]
                already_commented = stripped.startswith("#")
                if mute and already_commented:
                    continue
                if not mute and not already_commented:
                    continue
                m_c = SOUND_RE_CUSTOM.match(stripped)
                m_p = SOUND_RE_PLAY.match(stripped)
                if m_c:
                    key = (start_idx, m_c.group(3), "Custom")
                elif m_p:
                    key = (start_idx, m_p.group(3), "Play")
                else:
                    continue
                if key not in targets:
                    continue
                if mute:
                    self.lines[i] = f'{leading}# {stripped}\n'
                else:
                    uncommented = re.sub(r'^#\s*', '', stripped)
                    self.lines[i] = f'{leading}{uncommented}\n'
                touched += 1
        try:
            self.save_filter()
            self._set_status(f"{verb}d {touched} sound line(s)")
            # (Removed redundant Success popup — status bar now reports: f"{verb}d {touched} row(s).")
            self.refresh_filter_data()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update filter: {e}")

    def mute_filtered(self):
        self._toggle_mute_filtered(mute=True)

    def unmute_filtered(self):
        self._toggle_mute_filtered(mute=False)

    # ------------- Preview helpers (unchanged) ------------- #
    def _play_async(self, func, *args, **kwargs):
        th = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
        th.start()

    def stop_preview(self):
        try:
            if self._vlc_player:
                self._vlc_player.stop()
        except Exception:
            pass
        try:
            if _pygame and self._pygame_ready and _pygame.mixer.get_init():
                _pygame.mixer.music.stop()
        except Exception:
            pass
        try:
            if self._pydub_obj:
                self._pydub_obj.stop()
                self._pydub_obj = None
        except Exception:
            pass
        try:
            if self._ffplay_proc and self._ffplay_proc.poll() is None:
                self._ffplay_proc.terminate()
                self._ffplay_proc = None
        except Exception:
            pass
        if winsound:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
        self._set_status("Stopped")

    def _play_with_vlc(self, path):
        try:
            if not self._vlc_instance:
                return False
            if self._vlc_player:
                self._vlc_player.stop()
            self._vlc_player = self._vlc_instance.media_player_new()
            media = self._vlc_instance.media_new(path)
            self._vlc_player.set_media(media)
            self._vlc_player.play()
            self._set_status(f"Playing with VLC: {os.path.basename(path)}")
            return True
        except Exception:
            return False

    def _init_pygame(self):
        if not _pygame or self._pygame_ready:
            return
        try:
            if not _pygame.get_init():
                _pygame.init()
            if not _pygame.mixer.get_init():
                _pygame.mixer.init()
            self._pygame_ready = True
        except Exception:
            self._pygame_ready = False

    def _play_with_pygame(self, path):
        try:
            self._init_pygame()
            if not self._pygame_ready:
                return False
            _pygame.mixer.music.load(path)
            _pygame.mixer.music.play()
            self._set_status(f"Playing with pygame: {os.path.basename(path)}")
            return True
        except Exception:
            return False

    def _play_with_pydub(self, path):
        try:
            if not _pydub:
                return False
            AudioSegment, pydub_play = _pydub
            seg = AudioSegment.from_file(path)
            self._pydub_obj = pydub_play(seg)
            self._set_status(f"Playing with pydub: {os.path.basename(path)}")
            return True
        except Exception:
            return False

    def _play_with_playsound(self, path):
        if not _playsound:
            return False
        self._set_status(f"Playing with playsound: {os.path.basename(path)}")
        self._play_async(_playsound, path, True)
        return True

    def _play_with_ffplay(self, path):
        exe = self.ffplay_path if (self.ffplay_path and os.path.isfile(self.ffplay_path)) else None
        if not exe:
            exe = which("ffplay")
        if not exe and self.ffmpeg_dir:
            candidate = os.path.join(self.ffmpeg_dir, "ffplay.exe" if os.name == "nt" else "ffplay")
            if os.path.isfile(candidate):
                exe = candidate
        if not exe:
            return False
        try:
            creationflags = 0
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self._ffplay_proc = subprocess.Popen(
                [exe, "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                startupinfo=startupinfo, creationflags=creationflags
            )
            self._set_status(f"Playing with ffplay: {os.path.basename(path)}")
            return True
        except Exception:
            return False

    def _play_with_winsound(self, path):
        if not winsound:
            return False
        ext = os.path.splitext(path)[1].lower()
        if ext != ".wav":
            return False
        try:
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            self._set_status(f"Playing with winsound: {os.path.basename(path)}")
            return True
        except Exception:
            return False

    def _play_with_os_startfile(self, path):
        try:
            if os.name == "nt":
                os.startfile(path)
                self._set_status(f"Opened in default player: {os.path.basename(path)}")
                return True
            else:
                opener = which("xdg-open") or which("open")
                if opener:
                    subprocess.Popen([opener, path])
                    self._set_status(f"Opened in default player: {os.path.basename(path)}")
                    return True
        except Exception:
            return False
        return False

    def _play_file(self, path):
        if not os.path.isfile(path):
            messagebox.showwarning("Preview", f"File not found:\n{path}")
            return
        tried = [
            ("VLC", self._play_with_vlc),
            ("pygame", self._play_with_pygame),
            ("pydub", self._play_with_pydub),
            ("playsound", self._play_with_playsound),
            ("ffplay", self._play_with_ffplay),
            ("system", self._play_with_os_startfile),
            ("winsound", self._play_with_winsound),
        ]
        for name, fn in tried:
            ok = fn(path)
            if ok:
                return
        messagebox.showinfo(
            "Preview unsupported",
            "Could not find a backend to preview this file.\n"
            "Tip: install one of these for best results:\n"
            "  - python-vlc (requires VLC installed)\n"
            "  - pygame\n"
            "  - pydub + simpleaudio (+ ffmpeg)\n"
            "  - playsound\n"
            "  - or ensure ffplay (FFmpeg) is available"
        )

    def preview_last_change(self):
        if not self.last_changed_path:
            messagebox.showinfo("Preview", "No recent change to preview yet.")
            return
        self._play_file(self.last_changed_path)

    def preview_selected(self):
        sel = self._get_selected_entry()
        if not sel:
            messagebox.showwarning("No Selection", "Please select a row first.")
            return
        if sel["stype"] != "Custom":
            messagebox.showinfo("Preview", "Preview is only available for CustomAlertSound entries.")
            return
        base = os.path.dirname(self.filter_path) if self.filter_path else os.getcwd()
        candidate = os.path.join(base, str(sel["sound"]))
        self._play_file(candidate)

    # ===================== Legacy Merge tab logic =====================
    def _setup_legacy_merge_tab(self, tab_merge):
        """Setup legacy merge UI as fallback."""
        merge_wrap = ctk.CTkFrame(tab_merge, corner_radius=12)
        merge_wrap.pack(fill="both", expand=True, padx=10, pady=10)

        row1 = ctk.CTkFrame(merge_wrap)
        row1.pack(fill="x", pady=(0, 8))
        self.merge_left_btn = ctk.CTkButton(row1, text="📂 Load LEFT filter", width=180, command=self._merge_load_left)
        self.merge_left_btn.pack(side="left", padx=(0, 8))
        self.merge_left_label = ctk.CTkLabel(row1, text="No file selected")
        self.merge_left_label.pack(side="left")

        row2 = ctk.CTkFrame(merge_wrap)
        row2.pack(fill="x", pady=(0, 12))
        self.merge_mid_btn = ctk.CTkButton(row2, text="📂 Load MIDDLE filter", width=180, command=self._merge_load_middle)
        self.merge_mid_btn.pack(side="left", padx=(0, 8))
        self.merge_mid_label = ctk.CTkLabel(row2, text="No file selected")
        self.merge_mid_label.pack(side="left")

        self.merge_go_btn = ctk.CTkButton(merge_wrap, text="🔧 Merge LEFT with MIDDLE sounds…", width=300, command=self._merge_and_save)
        self.merge_go_btn.pack(pady=(4, 8))

        self.merge_info = ctk.CTkLabel(merge_wrap, text="Load both files to enable merge (Legacy exact-match mode).", justify="left")
        self.merge_info.pack(anchor="w")

    def _merge_load_left(self):
        path = filedialog.askopenfilename(filetypes=[("Filter Files", "*.filter")])
        if not path:
            return
        self.merge_left_path = path
        self.merge_left_label.configure(text=os.path.basename(path))
        self._update_merge_info()

    def _merge_load_middle(self):
        path = filedialog.askopenfilename(filetypes=[("Filter Files", "*.filter")])
        if not path:
            return
        self.merge_middle_path = path
        self.merge_mid_label.configure(text=os.path.basename(path))
        self._update_merge_info()

    def _update_merge_info(self):
        if not (self.merge_left_path and self.merge_middle_path):
            self.merge_info.configure(text="Load both files to enable merge.")
            return
        try:
            with open(self.merge_left_path, "r", encoding="utf-8", errors="ignore") as f:
                left_lines = f.readlines()
            with open(self.merge_middle_path, "r", encoding="utf-8", errors="ignore") as f:
                mid_lines = f.readlines()
            left_blocks = self._collect_blocks(left_lines)
            mid_blocks = self._collect_blocks(mid_lines)
            shared = len(set(left_blocks.keys()) & set(mid_blocks.keys()))
            self.merge_info.configure(
                text=f"Ready. LEFT blocks: {len(left_blocks)} • MIDDLE blocks: {len(mid_blocks)} • Shared: {shared}"
            )
        except Exception as e:
            self.merge_info.configure(text=f"Error reading files: {e}")

    def _collect_blocks(self, lines):
        blocks = {}
        i = 0
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith(self.SHOWHIDE):
                start = i
                i += 1
                body_lines = []
                while i < len(lines) and not lines[i].strip().startswith(self.SHOWHIDE):
                    body_lines.append(lines[i])
                    i += 1
                end = i
                header = stripped
                sig = self._block_signature(header, [l.strip() for l in body_lines])
                snd_lines = []
                snd_idx_rel = []
                for idx_rel, bl in enumerate(body_lines):
                    s = bl.strip()
                    if SOUND_RE_CUSTOM.match(s) or SOUND_RE_PLAY.match(s):
                        snd_lines.append(bl)
                        snd_idx_rel.append(idx_rel)
                blocks[sig] = {
                    "start": start,
                    "end": end,
                    "header": header,
                    "body": body_lines,
                    "sound_lines": snd_lines,
                    "sound_idx_rel": snd_idx_rel,
                }
            else:
                i += 1
        return blocks

    def _block_signature(self, header, body_stripped_lines):
        keys = (
            "Class", "BaseType", "ItemLevel", "DropLevel", "Sockets", "GemLevel", "HasInfluence",
            "BaseDefencePercentile", "Corrupted", "StackSize", "AreaLevel", "AnyEnchantment", "HasExplicitMod",
            "Rarity"
        )
        setting_keys = ("SetFontSize", "SetTextColor", "SetBorderColor", "SetBackgroundColor", "PlayEffect", "MinimapIcon")
        ctx = []
        for s in body_stripped_lines:
            if s.startswith(keys) or s.startswith(setting_keys):
                ctx.append(s)
        sig = header + " || " + " ; ".join(ctx)
        return sig

    def _merge_and_save(self):
        if not (self.merge_left_path and self.merge_middle_path):
            messagebox.showwarning("Merge", "Please load both LEFT and MIDDLE filter files.")
            return
        try:
            with open(self.merge_left_path, "r", encoding="utf-8", errors="ignore") as f:
                left_lines = f.readlines()
            with open(self.merge_middle_path, "r", encoding="utf-8", errors="ignore") as f:
                mid_lines = f.readlines()

            left_blocks = self._collect_blocks(left_lines)
            mid_blocks = self._collect_blocks(mid_lines)

            merged = list(left_lines)
            delta = 0
            replaced_blocks = 0

            for sig, lb in left_blocks.items():
                if sig not in mid_blocks:
                    continue
                mb = mid_blocks[sig]
                if not mb["sound_lines"]:
                    continue

                start = lb["start"] + delta
                end = lb["end"] + delta
                block_body = merged[start+1:end]

                current_snd_idx = []
                for idx_rel, line in enumerate(block_body):
                    s = line.strip()
                    if SOUND_RE_CUSTOM.match(s) or SOUND_RE_PLAY.match(s):
                        current_snd_idx.append(idx_rel)

                for idx_rel in reversed(current_snd_idx):
                    abs_idx = start + 1 + idx_rel
                    merged.pop(abs_idx)
                    end -= 1
                    delta -= 1

                if current_snd_idx:
                    insert_at = start + 1 + min(current_snd_idx)
                else:
                    insert_at = end

                indent = ""
                for ln in merged[start+1:end]:
                    if ln.strip():
                        leading = len(ln) - len(ln.lstrip(" \t"))
                        if leading > 0:
                            indent = ln[:leading]
                            break

                to_insert = []
                for raw in mb["sound_lines"]:
                    s = raw.rstrip("\n")
                    if s.lstrip() == s:
                        to_insert.append(f"{indent}{s}\n")
                    else:
                        to_insert.append(s + "\n")

                for idx, line in enumerate(to_insert):
                    merged.insert(insert_at + idx, line)
                    end += 1
                    delta += 1

                replaced_blocks += 1

            left_base = os.path.splitext(os.path.basename(self.merge_left_path))[0]
            mid_base = os.path.splitext(os.path.basename(self.merge_middle_path))[0]
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            default_name = f"merged_{left_base}__{mid_base}_{ts}.filter"
            save_path = filedialog.asksaveasfilename(
                defaultextension=".filter",
                initialfile=default_name,
                filetypes=[("Filter Files", "*.filter")]
            )
            if not save_path:
                return

            with open(save_path, "w", encoding="utf-8") as out:
                out.writelines(merged)

            messagebox.showinfo("Merge complete", f"Merged file saved.\nBlocks updated: {replaced_blocks}\n\n{save_path}")
            self._set_status(f"Merge completed • blocks updated: {replaced_blocks}")
        except Exception as e:
            messagebox.showerror("Merge error", f"Unable to merge:\n{e}")

    # ==================== Color Editing Methods (Phase 2) ==================== #

    def _get_selected_block(self):
        """Get the currently selected FilterBlock object."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("No selection", "Please select a row first.")
            return None

        iid = selection[0]

        # Get the index of the selected item in the treeview
        try:
            idx = self.tree.index(iid)
        except Exception as e:
            messagebox.showerror("Error", f"Could not get selection index: {e}")
            return None

        if idx >= len(self.filtered_data):
            messagebox.showerror("Error", "Invalid selection.")
            return None

        # Parse the current filter to get FilterBlock objects
        blocks = self.filter_parser.parse_file(self.lines)

        # Find the corresponding block using start_idx from filtered_data
        row_data = self.filtered_data[idx]
        start_idx = row_data.get("start_idx", -1)

        if start_idx >= 0:
            # Find block by start_idx (most reliable)
            for block in blocks:
                if block.start_idx == start_idx:
                    return block

        # Fallback: match by rarity and context
        rarity = row_data.get("rarity", "")
        context = row_data.get("context", "")

        for block in blocks:
            block_context = " ".join(block.context_lines[:3])  # Compare first 3 context lines
            if block.rarity == rarity and context.startswith(block_context[:50]):
                return block

        messagebox.showerror("Error", "Could not find matching block.")
        return None

    def edit_colors(self):
        """Open color editor dialog for selected block."""
        if not self.filter_path or not self.lines:
            messagebox.showwarning("No filter loaded", "Please load a filter file first.")
            return

        block = self._get_selected_block()
        if not block:
            return

        # Create a submenu to choose which color to edit
        menu_window = ctk.CTkToplevel(self.root)

        frame = ctk.CTkFrame(menu_window)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(frame, text="Select color to edit:",
                     font=("Segoe UI Semibold", 14)).pack(pady=(0, 15))

        # Get current colors
        current_colors = ColorManager.get_colors(block)

        def edit_text_color():
            dialog = ColorPickerDialog(
                self.root,
                title="Edit Text Color",
                initial_color=current_colors.text_color,
                callback=lambda color: self._apply_color(block, "text", color)
            )
            menu_window.destroy()

        def edit_border_color():
            dialog = ColorPickerDialog(
                self.root,
                title="Edit Border Color",
                initial_color=current_colors.border_color,
                callback=lambda color: self._apply_color(block, "border", color)
            )
            menu_window.destroy()

        def edit_background_color():
            dialog = ColorPickerDialog(
                self.root,
                title="Edit Background Color",
                initial_color=current_colors.bg_color,
                callback=lambda color: self._apply_color(block, "background", color)
            )
            menu_window.destroy()

        ctk.CTkButton(frame, text="📝 Text Color", command=edit_text_color, width=250).pack(pady=5)
        ctk.CTkButton(frame, text="🔲 Border Color", command=edit_border_color, width=250).pack(pady=5)
        ctk.CTkButton(frame, text="🎨 Background Color", command=edit_background_color, width=250).pack(pady=5)
        ctk.CTkButton(frame, text="Cancel", command=menu_window.destroy, width=250, fg_color="gray").pack(pady=(15, 0))

        self._setup_dialog(menu_window, title="Edit Colors",
                           default_size=(380, 300), min_size=(340, 270),
                           allow_resize=False)

    def _apply_color(self, block, color_type, rgba):
        """Apply a color to a block and save the filter."""
        try:
            if color_type == "text":
                ColorManager.apply_text_color(self.lines, block, *rgba)
            elif color_type == "border":
                ColorManager.apply_border_color(self.lines, block, *rgba)
            elif color_type == "background":
                ColorManager.apply_background_color(self.lines, block, *rgba)

            # Save the file
            save_filter_file(self.filter_path, self.lines, create_backup=self.settings.create_backups, max_backups=self.settings.max_backups)

            # Reload the filter to reflect changes
            self.load_filter_from_path(self.filter_path)

            self._set_status(f"Color updated: {color_type} = RGBA{rgba}")
            # (Removed redundant Success popup — status bar now reports: f"{color_type.capitalize()} color updated successfully!")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to apply color:\n{e}")

    def copy_colors(self):
        """Copy colors from selected block to clipboard."""
        block = self._get_selected_block()
        if not block:
            return

        self.color_clipboard.copy_from_block(block)

        if self.color_clipboard.has_colors():
            self.paste_colors_button.configure(state="normal")
            self._set_status("Colors copied to clipboard")
            # (Removed redundant Success popup — status bar now reports: "Colors copied! Use 'Paste Colors' to apply to another block.")
        else:
            messagebox.showwarning("No colors", "Selected block has no colors to copy.")

    def paste_colors(self):
        """Paste colors from clipboard to selected block."""
        if not self.color_clipboard.has_colors():
            messagebox.showwarning("Clipboard empty", "No colors in clipboard. Use 'Copy Colors' first.")
            return

        block = self._get_selected_block()
        if not block:
            return

        try:
            self.color_clipboard.paste_to_block(block, self.lines)

            # Save the file
            save_filter_file(self.filter_path, self.lines, create_backup=self.settings.create_backups, max_backups=self.settings.max_backups)

            # Reload the filter
            self.load_filter_from_path(self.filter_path)

            self._set_status("Colors pasted successfully")
            # (Removed redundant Success popup — status bar now reports: "Colors pasted to selected block!")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to paste colors:\n{e}")

    def preview_item_colors(self):
        """Show preview of how the item will appear in-game."""
        block = self._get_selected_block()
        if not block:
            return

        try:
            ItemPreviewDialog(self.root, block)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to show preview:\n{e}")

    def remove_colors(self):
        """Remove all colors from selected block."""
        block = self._get_selected_block()
        if not block:
            return

        dialog = ConfirmDialog(
            self.root,
            title="Confirm Removal",
            message="Remove all colors (text, border, background) from this block?",
            confirm_text="Remove",
            cancel_text="Cancel"
        )

        if dialog.get_result():
            try:
                ColorManager.remove_text_color(self.lines, block)
                ColorManager.remove_border_color(self.lines, block)
                ColorManager.remove_background_color(self.lines, block)

                # Save the file
                save_filter_file(self.filter_path, self.lines, create_backup=self.settings.create_backups, max_backups=self.settings.max_backups)

                # Reload the filter
                self.load_filter_from_path(self.filter_path)

                self._set_status("All colors removed from block")
                # (Removed redundant Success popup — status bar now reports: "All colors removed from selected block!")

            except Exception as e:
                messagebox.showerror("Error", f"Failed to remove colors:\n{e}")

    def load_filter_from_path(self, path):
        """Helper method to reload filter from a specific path."""
        self.filter_path = path
        self.lines = load_filter_file(path)
        self._snapshot_on_load(path)
        self.refresh_filter_data()
        self.file_label.configure(text=os.path.basename(path))
        # Bookkeeping for cross-machine state
        self.settings.add_recent(path)
        self.settings.last_filter_path = path
        self._persist_settings()
        try:
            self._rebuild_recent_menu()
        except Exception:
            pass
        if self.settings.auto_check_compatibility:
            self._run_compatibility_check(auto=True)

    def _snapshot_on_load(self, path: str) -> None:
        """Drop a pristine copy of the just-loaded file into its `_backups/`
        folder so the user always has the original state before any auto-fix
        or save touches it.

        Backups are deduplicated by content — repeatedly reloading the same
        file won't fill the folder with identical copies.
        """
        if not self.settings.auto_backup_on_load:
            return
        if not path or not os.path.isfile(path):
            return
        try:
            make_backup(
                path,
                max_keep=self.settings.max_backups,
                label="load",
                skip_if_identical=True,
            )
        except Exception as e:
            # Snapshot failure should never block loading — log to status only.
            self._set_status(f"On-load backup skipped: {e}")

    # ============================================================
    # Filter Compatibility Check
    # ============================================================
    def check_filter_compatibility(self):
        """Tools menu entry — manually re-run the compatibility check."""
        if not self.filter_path or not self.lines:
            messagebox.showinfo("No filter", "Load a filter file first.")
            return
        self._run_compatibility_check(auto=False)

    def emphasize_by_tier(self):
        """Tools menu entry — open Visual Tools on the Emphasize tab."""
        open_visual_tools(self, start_tab="emphasize")

    def randomize_visuals(self):
        """Tools menu entry — open Visual Tools on the Randomize tab."""
        open_visual_tools(self, start_tab="randomize")

    def open_economy_tier_visuals(self, start_mode=None):
        """Open the Economy Tier Visual Preset dialog.

        Imported lazily so the app still launches if the feature's optional
        dependencies (e.g. jsonschema) are missing — the user just gets a clear
        message instead of a startup crash.
        """
        try:
            from ui.economy_tier_ui import open_economy_tier_tools
        except Exception as e:  # pragma: no cover - import guard
            messagebox.showerror(
                "Economy Tier Visuals",
                f"This feature could not be loaded:\n{e}\n\n"
                "Install requirements (pip install -r requirements.txt) and retry.",
            )
            return
        open_economy_tier_tools(self, start_mode=start_mode)

    def _on_economy_mode_selected(self, value):
        """Main-window dropdown handler. Opens the dialog on the chosen mode,
        then resets to 'Off' so the dropdown behaves as an action trigger."""
        try:
            self.economy_mode_selector.set("Off")
        except Exception:
            pass
        if not value or value == "Off":
            return
        self.open_economy_tier_visuals(start_mode=value)

    def _run_compatibility_check(self, auto: bool = False) -> None:
        """Scan the current filter for unknown commands, deprecated syntax,
        and migration-rule matches. Offers to auto-apply fixes.

        When ``auto`` is True (post-load), a clean filter stays silent —
        we don't pop a dialog just to say "all good". The status bar reports it.
        Manual invocations always show a result.
        """
        app_dir = os.path.dirname(os.path.abspath(__file__))
        rules_path = default_rules_path(app_dir)
        engine = MigrationRulesEngine.load(rules_path)
        checker = FilterCompatibilityChecker(engine)
        report = checker.check(self.lines)

        if report.is_clean:
            msg = "Compatibility: ✓ no issues found."
            self._set_status(msg)
            if not auto:
                messagebox.showinfo(
                    "Filter Compatibility",
                    "All commands are recognized and no migration rules match.\n\n"
                    f"Rules file: {rules_path}",
                )
            return

        new_lines, applied = show_compatibility_dialog(self, self.lines, report, checker)
        if applied <= 0:
            self._set_status(
                f"Compatibility: {len(report.issues)} issue(s) — none applied."
            )
            return

        # Commit the fixes to disk via the standard save path (gets backup + atomic write).
        self.lines = new_lines
        try:
            save_filter_file(
                self.filter_path, self.lines,
                create_backup=self.settings.create_backups,
                max_backups=self.settings.max_backups,
            )
        except Exception as e:
            messagebox.showerror("Save Error",
                                  f"Applied {applied} fix(es) in memory but couldn't save:\n{e}")
            return

        # Reparse so the editor reflects the rewritten file.
        self.refresh_filter_data()
        self._set_status(
            f"Compatibility: applied {applied} fix(es), saved with backup."
        )

    # ============================================================
    # Settings dialog
    # ============================================================
    def open_settings_dialog(self):
        dlg = ctk.CTkToplevel(self.root)
        pal = self.theme_manager.current()
        frame = ctk.CTkFrame(dlg, fg_color=pal.panel)
        frame.pack(fill="both", expand=True, padx=16, pady=16)

        # --- Theme group ---
        ctk.CTkLabel(frame, text="Appearance", font=("Segoe UI Semibold", 13)).pack(anchor="w", pady=(4, 2))
        row = ctk.CTkFrame(frame, fg_color="transparent"); row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text="Theme:").pack(side="left", padx=(0, 8))
        theme_var = ctk.StringVar(value=self.settings.theme_palette)
        ctk.CTkOptionMenu(row, values=palette_names(), variable=theme_var, width=260).pack(side="left")

        row = ctk.CTkFrame(frame, fg_color="transparent"); row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text="Appearance Mode:").pack(side="left", padx=(0, 8))
        mode_var = ctk.StringVar(value=self.settings.appearance_mode)
        ctk.CTkOptionMenu(row, values=["System", "Light", "Dark"], variable=mode_var, width=140).pack(side="left")

        # --- Audio group ---
        ctk.CTkLabel(frame, text="Audio", font=("Segoe UI Semibold", 13)).pack(anchor="w", pady=(16, 2))
        row = ctk.CTkFrame(frame, fg_color="transparent"); row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text="FFmpeg path (optional):").pack(side="left", padx=(0, 8))
        ffmpeg_var = ctk.StringVar(value=self.settings.ffmpeg_path)
        ffmpeg_entry = ctk.CTkEntry(row, textvariable=ffmpeg_var, width=380)
        ffmpeg_entry.pack(side="left")
        def _browse_ffmpeg():
            p = filedialog.askopenfilename(
                title="Locate ffmpeg",
                filetypes=[("ffmpeg", "ffmpeg.exe ffmpeg")] if os.name == "nt" else [("ffmpeg", "ffmpeg")],
            )
            if p:
                ffmpeg_var.set(p)
        ctk.CTkButton(row, text="Browse…", width=80, command=_browse_ffmpeg).pack(side="left", padx=(6, 0))

        detect_label = ctk.CTkLabel(frame,
            text=f"Currently detected: {self.ffmpeg_path or '(not found — audio preview will still try VLC/pygame/winsound)'}",
            font=("Segoe UI", 9), text_color=pal.text_muted, wraplength=580, justify="left",
        )
        detect_label.pack(anchor="w", pady=(2, 4))

        row = ctk.CTkFrame(frame, fg_color="transparent"); row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text="Default volume for new sounds:").pack(side="left", padx=(0, 8))
        vol_var = ctk.StringVar(value=str(self.settings.default_volume))
        ctk.CTkEntry(row, textvariable=vol_var, width=80).pack(side="left")
        ctk.CTkLabel(row, text="(0-300)", text_color=pal.text_muted).pack(side="left", padx=(6, 0))

        # --- File handling group ---
        ctk.CTkLabel(frame, text="File Handling", font=("Segoe UI Semibold", 13)).pack(anchor="w", pady=(16, 2))
        autoload_var = ctk.BooleanVar(value=self.settings.autoload_last)
        ctk.CTkCheckBox(frame, text="Re-open the last filter on startup", variable=autoload_var).pack(anchor="w", pady=2)
        backup_var = ctk.BooleanVar(value=self.settings.create_backups)
        ctk.CTkCheckBox(frame, text="Create timestamped backups on every save", variable=backup_var).pack(anchor="w", pady=2)
        load_backup_var = ctk.BooleanVar(value=self.settings.auto_backup_on_load)
        ctk.CTkCheckBox(
            frame,
            text="Snapshot the original on load (deduplicated — won't pile up reloads of the same file)",
            variable=load_backup_var,
        ).pack(anchor="w", pady=2)

        row = ctk.CTkFrame(frame, fg_color="transparent"); row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text="Keep at most:").pack(side="left", padx=(0, 8))
        max_backup_var = ctk.StringVar(value=str(self.settings.max_backups))
        ctk.CTkEntry(row, textvariable=max_backup_var, width=80).pack(side="left")
        ctk.CTkLabel(row, text="backups per filter (older ones are removed).").pack(side="left", padx=(6, 0))

        # --- Filter health group ---
        ctk.CTkLabel(frame, text="Filter Health", font=("Segoe UI Semibold", 13)).pack(anchor="w", pady=(16, 2))
        verify_var = ctk.BooleanVar(value=self.settings.verify_on_save)
        ctk.CTkCheckBox(
            frame,
            text="Verify on save (silently scan for missing sound files after every save and on load)",
            variable=verify_var,
        ).pack(anchor="w", pady=2)
        ctk.CTkLabel(
            frame,
            text="The status bar shows a ✓ when healthy and a ⚠ pill when sound references are missing. Click the pill, press Ctrl+H, or use Tools → Verify & Fix Sounds to repair.",
            font=("Segoe UI", 9), text_color=pal.text_muted, wraplength=580, justify="left",
        ).pack(anchor="w", pady=(0, 4))

        compat_var = ctk.BooleanVar(value=self.settings.auto_check_compatibility)
        ctk.CTkCheckBox(
            frame,
            text="Check filter compatibility on load (unknown commands, deprecated syntax, migration rules)",
            variable=compat_var,
        ).pack(anchor="w", pady=2)
        ctk.CTkLabel(
            frame,
            text="When a loaded filter contains anything unrecognized or anything matched by a rule in data/migration_rules.json, a dialog offers to auto-fix it. Disable to only run via Tools → Check Filter Compatibility.",
            font=("Segoe UI", 9), text_color=pal.text_muted, wraplength=580, justify="left",
        ).pack(anchor="w", pady=(0, 4))

        # --- Footer: settings file location + buttons ---
        ctk.CTkLabel(frame, text=f"Settings file: {settings_path()}",
                     font=("Segoe UI", 9), text_color=pal.text_muted).pack(anchor="w", pady=(16, 4))

        btn_row = ctk.CTkFrame(frame, fg_color="transparent"); btn_row.pack(fill="x", pady=(8, 0))
        def _save_and_close():
            try:
                new_vol = max(0, min(300, int(vol_var.get())))
            except ValueError:
                new_vol = self.settings.default_volume
            try:
                new_max_backups = max(1, min(500, int(max_backup_var.get())))
            except ValueError:
                new_max_backups = self.settings.max_backups
            new_ffmpeg = ffmpeg_var.get().strip()

            self.settings.theme_palette = theme_var.get()
            self.settings.appearance_mode = mode_var.get()
            self.settings.ffmpeg_path = new_ffmpeg
            self.settings.default_volume = new_vol
            self.settings.autoload_last = autoload_var.get()
            self.settings.create_backups = backup_var.get()
            self.settings.auto_backup_on_load = load_backup_var.get()
            self.settings.max_backups = new_max_backups
            self.settings.verify_on_save = verify_var.get()
            self.settings.auto_check_compatibility = compat_var.get()
            self._persist_settings()

            # Re-resolve FFmpeg and re-apply theme
            self.ffmpeg_dir, self.ffmpeg_path, self.ffprobe_path, self.ffplay_path = _resolve_ffmpeg_paths(new_ffmpeg)
            _configure_pydub_ffmpeg(self.ffmpeg_path, self.ffprobe_path)
            self.theme_manager.apply(self.settings.theme_palette, self.settings.appearance_mode)
            self.theme_selector.set(self.settings.theme_palette)
            self.appearance_selector.set(self.settings.appearance_mode)
            # Re-run the health scan so the indicator reflects the new on/off state
            self._update_health_indicator()
            self._set_status("Settings saved.")
            dlg.destroy()
        ctk.CTkButton(btn_row, text="Save", command=_save_and_close, width=120).pack(side="right", padx=4)
        ctk.CTkButton(btn_row, text="Cancel", command=dlg.destroy, width=120,
                      fg_color=pal.panel_alt, hover_color=pal.border, text_color=pal.text).pack(side="right", padx=4)

        self._setup_dialog(dlg, title="Settings",
                           default_size=(720, 640), min_size=(620, 540))

    # ============================================================
    # About dialog
    # ============================================================
    def show_about_dialog(self):
        dlg = ctk.CTkToplevel(self.root)
        pal = self.theme_manager.current()
        f = ctk.CTkFrame(dlg, fg_color=pal.panel); f.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(f, text=APP_NAME, font=("Segoe UI Semibold", 18)).pack(anchor="w")
        ctk.CTkLabel(f, text=f"Version {APP_VERSION}", text_color=pal.text_muted).pack(anchor="w", pady=(0, 8))
        ctk.CTkLabel(f, text=APP_TAGLINE, text_color=pal.text_muted).pack(anchor="w", pady=(0, 8))
        ctk.CTkLabel(f,
            text="Edit, organize, and audition sounds in Path of Exile 2 item filters.\n"
                 "Supports CustomAlertSound, PlayAlertSound and PlayAlertSoundPositional rules,\n"
                 "section-aware categorization, and bulk operations on the visible set.",
            justify="left", wraplength=520).pack(anchor="w", pady=4)

        ctk.CTkLabel(f, text="Audio backends detected:", font=("Segoe UI Semibold", 11)).pack(anchor="w", pady=(12, 2))
        backends = [
            ("FFmpeg", bool(self.ffmpeg_path)),
            ("ffplay", bool(self.ffplay_path)),
            ("VLC (python-vlc)", _vlc is not None),
            ("pygame", _pygame is not None),
            ("pydub", _pydub is not None),
            ("playsound", _playsound is not None),
            ("winsound", winsound is not None),
        ]
        for name, ok in backends:
            mark = "✓" if ok else "✗"
            color = pal.smart_fg if ok else pal.text_muted
            ctk.CTkLabel(f, text=f"  {mark}  {name}", text_color=color).pack(anchor="w")

        ctk.CTkLabel(f, text="Settings stored at:", font=("Segoe UI Semibold", 11)).pack(anchor="w", pady=(12, 2))
        ctk.CTkLabel(f, text=settings_path(), text_color=pal.text_muted, wraplength=480, justify="left").pack(anchor="w")

        link_row = ctk.CTkFrame(f, fg_color="transparent"); link_row.pack(fill="x", pady=(12, 0))
        ctk.CTkButton(link_row, text="Open FilterBlade",
                      command=lambda: webbrowser.open("https://www.filterblade.xyz/?game=Poe2"), width=160).pack(side="left", padx=4)
        ctk.CTkButton(link_row, text="POE2 Filter Syntax",
                      command=lambda: webbrowser.open("https://www.pathofexile.com/forum/view-thread/3683711"), width=160).pack(side="left", padx=4)
        ctk.CTkButton(link_row, text="Close", command=dlg.destroy, width=100,
                      fg_color=pal.panel_alt, hover_color=pal.border, text_color=pal.text).pack(side="right", padx=4)

        self._setup_dialog(dlg, title=f"About — {APP_NAME}",
                           default_size=(580, 520), min_size=(520, 460),
                           allow_resize=False)

    # ============================================================
    # Sound File Manager
    # ============================================================
    def open_sound_manager(self):
        if not self.filter_path:
            messagebox.showinfo("No filter", "Load a filter file first.")
            return
        folder = os.path.dirname(self.filter_path)

        # Collect referenced and on-disk sound files
        referenced = {}  # filename -> count
        for e in self.filter_data:
            if e.get("stype") == "Custom":
                referenced[e["sound"]] = referenced.get(e["sound"], 0) + 1

        audio_exts = {".mp3", ".wav", ".ogg", ".aac", ".flac", ".m4a", ".opus"}
        try:
            on_disk = {
                f for f in os.listdir(folder)
                if os.path.splitext(f)[1].lower() in audio_exts
            }
        except OSError:
            on_disk = set()

        missing = sorted(set(referenced) - on_disk)
        orphan = sorted(on_disk - set(referenced))
        present = sorted(set(referenced) & on_disk)

        dlg = ctk.CTkToplevel(self.root)
        pal = self.theme_manager.current()
        f = ctk.CTkFrame(dlg, fg_color=pal.panel); f.pack(fill="both", expand=True, padx=12, pady=12)

        ctk.CTkLabel(f, text=f"Folder: {folder}", text_color=pal.text_muted).pack(anchor="w", pady=(0, 8))

        summary = (f"{len(referenced)} referenced  •  {len(present)} present on disk  "
                   f"•  {len(missing)} missing  •  {len(orphan)} orphan (not referenced)")
        ctk.CTkLabel(f, text=summary, font=("Segoe UI Semibold", 12)).pack(anchor="w", pady=(0, 8))

        # Tabs: Missing / Orphan / Referenced
        tabs = ctk.CTkTabview(f); tabs.pack(fill="both", expand=True)
        tab_missing = tabs.add(f"Missing ({len(missing)})")
        tab_orphan = tabs.add(f"Orphan ({len(orphan)})")
        tab_ref = tabs.add(f"Referenced ({len(referenced)})")

        def _make_listbox(parent, items, formatter):
            list_frame = ctk.CTkFrame(parent, fg_color=pal.panel_alt)
            list_frame.pack(fill="both", expand=True, padx=4, pady=4)
            lb = tk.Listbox(list_frame, bg=pal.tree_bg, fg=pal.tree_fg,
                            selectbackground=pal.tree_sel_bg, selectforeground=pal.tree_sel_fg,
                            font=("Segoe UI", 10), activestyle="none")
            sb = ttk.Scrollbar(list_frame, orient="vertical", command=lb.yview)
            lb.configure(yscrollcommand=sb.set)
            lb.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            for it in items:
                lb.insert("end", formatter(it))
            return lb

        _make_listbox(tab_missing, missing,
                      lambda fn: f"  ✗  {fn}    (used {referenced[fn]}× in filter)")
        orphan_lb = _make_listbox(tab_orphan, orphan, lambda fn: f"  •  {fn}")
        _make_listbox(tab_ref, sorted(referenced.items(), key=lambda kv: (-kv[1], kv[0])),
                      lambda kv: f"  {kv[1]:>3}×   {kv[0]}")

        actions = ctk.CTkFrame(f, fg_color="transparent"); actions.pack(fill="x", pady=(8, 0))

        def _delete_selected_orphans():
            sel = orphan_lb.curselection()
            if not sel:
                messagebox.showinfo("Nothing selected", "Select orphan files to delete first.")
                return
            files = [orphan[i] for i in sel]
            if not messagebox.askyesno("Delete files",
                                        f"Permanently delete {len(files)} orphan audio file(s) from\n{folder}?"):
                return
            errors = []
            for fn in files:
                try:
                    os.remove(os.path.join(folder, fn))
                except OSError as e:
                    errors.append(f"{fn}: {e}")
            if errors:
                messagebox.showwarning("Some deletions failed", "\n".join(errors))
            dlg.destroy()
            self.open_sound_manager()  # re-open with refreshed state

        ctk.CTkButton(actions, text="Open Folder", width=130,
                      command=lambda: self._open_folder(folder)).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="Delete Selected Orphans",
                      command=_delete_selected_orphans, width=200,
                      fg_color=pal.danger, hover_color=pal.danger_hover).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="Close", command=dlg.destroy, width=100,
                      fg_color=pal.panel_alt, hover_color=pal.border, text_color=pal.text).pack(side="right", padx=4)

        self._setup_dialog(dlg, title="Sound File Manager",
                           default_size=(840, 620), min_size=(720, 500))

    # ============================================================
    # Verify & Fix Sounds — heal broken sound references, archive orphans
    # ============================================================
    AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".aac", ".flac", ".m4a", ".opus"}
    OLD_SOUNDS_FOLDER = "old sound files"

    @staticmethod
    def _norm_name(name):
        """Filename comparison key — case-insensitive on Windows, case-sensitive elsewhere."""
        return name.lower() if sys.platform == "win32" else name

    def _scan_sound_health(self):
        """Return (folder, referenced_counts, on_disk, missing, present, orphan).

        - referenced_counts: dict{filename: count of blocks referencing it} (CustomAlertSound only)
        - on_disk: set of audio files found in the filter's folder (top-level only)
        - missing: filenames referenced by filter but absent from folder
        - present: filenames referenced AND on disk (the "proven good" pool)
        - orphan: audio files on disk that no rule references
        """
        folder = os.path.dirname(self.filter_path) if self.filter_path else ""
        referenced_counts = {}
        for e in self.filter_data:
            if e.get("stype") == "Custom":
                referenced_counts[e["sound"]] = referenced_counts.get(e["sound"], 0) + 1

        try:
            on_disk = {
                f for f in os.listdir(folder)
                if os.path.splitext(f)[1].lower() in self.AUDIO_EXTS
                and os.path.isfile(os.path.join(folder, f))
            }
        except (OSError, FileNotFoundError):
            on_disk = set()

        disk_norm = {self._norm_name(f): f for f in on_disk}
        ref_norm = {self._norm_name(r): r for r in referenced_counts}

        missing = sorted(referenced_counts[r] and r for r in referenced_counts if self._norm_name(r) not in disk_norm)
        missing = [r for r in referenced_counts if self._norm_name(r) not in disk_norm]
        missing.sort()

        present = sorted(r for r in referenced_counts if self._norm_name(r) in disk_norm)
        orphan = sorted(f for f in on_disk if self._norm_name(f) not in ref_norm)

        return folder, referenced_counts, on_disk, missing, present, orphan

    def _update_health_indicator(self):
        """Refresh the always-visible health pill in the status bar.

        Called after every load/refresh and after every successful save. Silent —
        never opens dialogs or interrupts the user. The pill is clickable to
        invoke verify_and_fix_sounds() when the user actually wants to act.
        """
        # Defensive: the indicator may not exist yet during early UI construction
        if not hasattr(self, "health_indicator"):
            return

        if not self.filter_path or not self.filter_data:
            self.health_indicator.configure(
                text="—  no filter loaded",
                fg_color="#3a3a3a", hover_color="#4a4a4a", text_color="#cccccc",
            )
            return

        if not self.settings.verify_on_save:
            self.health_indicator.configure(
                text="health checks off",
                fg_color="#3a3a3a", hover_color="#4a4a4a", text_color="#a0a0a0",
            )
            return

        try:
            _folder, _ref, _disk, missing, _present, orphan = self._scan_sound_health()
        except Exception:
            self.health_indicator.configure(
                text="health: scan failed",
                fg_color="#5a3a0c", hover_color="#7a4a10", text_color="#ffffff",
            )
            return

        if missing:
            n_blocks = sum(1 for e in self.filter_data
                           if e.get("stype") == "Custom"
                           and self._norm_name(e.get("sound", "")) in {self._norm_name(m) for m in missing})
            pill = f"⚠  {len(missing)} missing sound(s)  •  {n_blocks} block(s)"
            self.health_indicator.configure(
                text=pill,
                fg_color="#7a3030", hover_color="#9a3a3a", text_color="#ffffff",
            )
            # Also reflect in the status bar so it's visible at a glance
            self._set_status(
                f"⚠ Filter references {len(missing)} missing sound file(s) — Ctrl+H to fix"
            )
        elif orphan:
            self.health_indicator.configure(
                text=f"✓ healthy  •  {len(orphan)} orphan(s)",
                fg_color="#2d6e3e", hover_color="#358148", text_color="#ffffff",
            )
        else:
            self.health_indicator.configure(
                text="✓ healthy",
                fg_color="#2d6e3e", hover_color="#358148", text_color="#ffffff",
            )

    def verify_and_fix_sounds(self):
        if not self.filter_path:
            messagebox.showinfo("No filter", "Load a filter file first.")
            return

        folder, ref_counts, on_disk, missing, present, orphan = self._scan_sound_health()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("Folder missing", f"Could not access the filter's folder:\n{folder}")
            return

        # ---- Healthy filter shortcut ----
        if not missing and not orphan:
            messagebox.showinfo(
                "All good",
                "✓ Filter passes — every referenced sound file exists in the folder, "
                "and there are no orphan audio files to archive.",
            )
            return

        # ---- Build substitute pool (consistent per missing filename) ----
        # Prefer "proven good" sounds (referenced AND on disk).
        # Fall back to any audio file on disk if the proven set is empty.
        proven_pool = sorted(present)
        fallback_pool = sorted(on_disk)
        pool = proven_pool if proven_pool else fallback_pool

        if missing and not pool:
            messagebox.showerror(
                "No substitutes available",
                f"The filter references {len(missing)} missing sound file(s), but the folder\n"
                f"  {folder}\ncontains no audio files at all to substitute with.\n\n"
                "Drop at least one sound file into the folder, then run this again.",
            )
            return

        import random
        # Initial randomized plan: missing -> substitute (deterministic per filename within a session)
        def make_random_plan(p):
            return {fn: random.choice(p) for fn in missing}

        plan = make_random_plan(pool) if missing else {}
        self._open_verify_fix_dialog(folder, ref_counts, missing, orphan, pool, plan)

    def _open_verify_fix_dialog(self, folder, ref_counts, missing, orphan, pool, plan):
        pal = self.theme_manager.current()
        dlg = ctk.CTkToplevel(self.root)
        main = ctk.CTkFrame(dlg, fg_color=pal.panel)
        main.pack(fill="both", expand=True, padx=12, pady=12)

        # ----- Header summary -----
        ctk.CTkLabel(
            main,
            text=f"Filter: {os.path.basename(self.filter_path)}",
            font=("Segoe UI Semibold", 13),
        ).pack(anchor="w")
        ctk.CTkLabel(main, text=f"Folder: {folder}", text_color=pal.text_muted).pack(anchor="w", pady=(0, 8))

        affected_blocks = sum(ref_counts.get(m, 0) for m in missing)
        summary = (
            f"✗ Missing: {len(missing)} unique reference(s)  ({affected_blocks} block(s))   "
            f"📦 Orphan files: {len(orphan)}   "
            f"🎲 Substitute pool: {len(pool)} sound(s)"
        )
        ctk.CTkLabel(main, text=summary, font=("Segoe UI Semibold", 12)).pack(anchor="w", pady=(0, 8))

        # ----- Missing -> Substitute table -----
        if missing:
            ctk.CTkLabel(
                main, text="Missing references → planned substitute",
                font=("Segoe UI Semibold", 11),
            ).pack(anchor="w", pady=(8, 2))

            mf = ctk.CTkFrame(main, fg_color=pal.panel_alt)
            mf.pack(fill="both", expand=True, pady=4)
            cols = ("missing", "arrow", "substitute", "count")
            miss_tree = ttk.Treeview(mf, columns=cols, show="headings", height=8, selectmode="browse")
            miss_tree.heading("missing", text="Missing sound (referenced by filter)")
            miss_tree.heading("arrow", text="")
            miss_tree.heading("substitute", text="Will be replaced with (in folder)")
            miss_tree.heading("count", text="Blocks")
            miss_tree.column("missing", width=320, anchor="w")
            miss_tree.column("arrow", width=24, anchor="center")
            miss_tree.column("substitute", width=320, anchor="w")
            miss_tree.column("count", width=70, anchor="center")
            miss_tree.pack(side="left", fill="both", expand=True, padx=4, pady=4)
            miss_sb = ttk.Scrollbar(mf, orient="vertical", command=miss_tree.yview)
            miss_tree.configure(yscrollcommand=miss_sb.set)
            miss_sb.pack(side="right", fill="y", padx=(0, 4), pady=4)

            def repopulate_missing():
                for i in miss_tree.get_children():
                    miss_tree.delete(i)
                for fn in missing:
                    miss_tree.insert("", "end", iid=fn,
                                     values=(fn, "→", plan.get(fn, ""), ref_counts.get(fn, 0)))

            def on_double_click(_evt):
                sel = miss_tree.focus()
                if not sel:
                    return
                self._open_substitute_picker(dlg, sel, pool, plan, repopulate_missing)

            miss_tree.bind("<Double-1>", on_double_click)
            repopulate_missing()

            ctl = ctk.CTkFrame(main, fg_color="transparent")
            ctl.pack(fill="x")
            def reroll():
                import random
                for fn in missing:
                    plan[fn] = random.choice(pool)
                repopulate_missing()
            ctk.CTkButton(ctl, text="🎲 Randomize Again", command=reroll, width=180).pack(side="left", padx=4)
            ctk.CTkLabel(ctl, text="(Double-click a row to choose a specific substitute.)",
                         text_color=pal.text_muted).pack(side="left", padx=8)

        # ----- Orphan archive list -----
        if orphan:
            ctk.CTkLabel(
                main,
                text=f"Orphan audio files → will be moved to “{self.OLD_SOUNDS_FOLDER}/”",
                font=("Segoe UI Semibold", 11),
            ).pack(anchor="w", pady=(12, 2))
            of = ctk.CTkFrame(main, fg_color=pal.panel_alt)
            of.pack(fill="both", expand=True, pady=4)
            orphan_lb = tk.Listbox(
                of, height=6, font=("Segoe UI", 10),
                bg=pal.tree_bg, fg=pal.tree_fg,
                selectbackground=pal.tree_sel_bg, selectforeground=pal.tree_sel_fg,
                activestyle="none",
            )
            for f in orphan:
                orphan_lb.insert("end", f"  • {f}")
            o_sb = ttk.Scrollbar(of, orient="vertical", command=orphan_lb.yview)
            orphan_lb.configure(yscrollcommand=o_sb.set)
            orphan_lb.pack(side="left", fill="both", expand=True, padx=4, pady=4)
            o_sb.pack(side="right", fill="y", padx=(0, 4), pady=4)

        # ----- Options -----
        opts = ctk.CTkFrame(main, fg_color="transparent")
        opts.pack(fill="x", pady=(10, 0))
        fix_var = ctk.BooleanVar(value=bool(missing))
        move_var = ctk.BooleanVar(value=bool(orphan))
        if missing:
            ctk.CTkCheckBox(
                opts,
                text="Replace missing references with substitutes (rewrites the filter)",
                variable=fix_var,
            ).pack(anchor="w", pady=2)
        if orphan:
            ctk.CTkCheckBox(
                opts,
                text=f"Move orphan files to “{self.OLD_SOUNDS_FOLDER}/” (creates folder if needed)",
                variable=move_var,
            ).pack(anchor="w", pady=2)

        # ----- Buttons -----
        btn_row = ctk.CTkFrame(main, fg_color="transparent")
        btn_row.pack(fill="x", pady=(12, 0))

        def apply():
            substitutions = plan if (missing and fix_var.get()) else {}
            orphans_to_move = list(orphan) if (orphan and move_var.get()) else []
            # Don't archive any file we're using as a substitute
            substitute_files = {self._norm_name(v) for v in substitutions.values()}
            orphans_to_move = [o for o in orphans_to_move if self._norm_name(o) not in substitute_files]
            try:
                summary_text = self._apply_verify_fix(folder, substitutions, orphans_to_move)
            except Exception as e:
                messagebox.showerror("Apply failed", f"{e}")
                return
            dlg.destroy()
            messagebox.showinfo("Done", summary_text)
            # Reload to pick up the changed file (also rebuilds the sidebar counts)
            if self.filter_path and os.path.isfile(self.filter_path):
                self.load_filter_from_path(self.filter_path)

        ctk.CTkButton(
            btn_row, text="Cancel", command=dlg.destroy, width=120,
            fg_color=pal.panel_alt, hover_color=pal.border, text_color=pal.text,
        ).pack(side="right", padx=4)
        ctk.CTkButton(
            btn_row, text="Apply Changes", command=apply, width=180,
            fg_color=pal.accent, hover_color=pal.accent_hover, text_color=pal.accent_text,
        ).pack(side="right", padx=4)

        self._setup_dialog(dlg, title="Verify & Fix Filter Sounds",
                           default_size=(960, 720), min_size=(800, 600))

    def _open_substitute_picker(self, parent, missing_name, pool, plan, on_pick):
        """Small modal to override the substitute for a single missing filename."""
        pal = self.theme_manager.current()
        picker = ctk.CTkToplevel(parent)

        ctk.CTkLabel(picker, text=f"Choose a substitute for:\n{missing_name}",
                     wraplength=420, justify="left").pack(anchor="w", padx=12, pady=(12, 6))

        frame = ctk.CTkFrame(picker, fg_color=pal.panel_alt)
        frame.pack(fill="both", expand=True, padx=12, pady=4)
        lb = tk.Listbox(frame, font=("Segoe UI", 10),
                        bg=pal.tree_bg, fg=pal.tree_fg,
                        selectbackground=pal.tree_sel_bg, selectforeground=pal.tree_sel_fg,
                        activestyle="none")
        sb = ttk.Scrollbar(frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        for s in pool:
            lb.insert("end", s)
        # Pre-select current choice
        current = plan.get(missing_name)
        if current in pool:
            idx = pool.index(current)
            lb.selection_set(idx)
            lb.see(idx)
        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        btns = ctk.CTkFrame(picker, fg_color="transparent")
        btns.pack(fill="x", padx=12, pady=8)
        def confirm():
            sel = lb.curselection()
            if sel:
                plan[missing_name] = pool[sel[0]]
                on_pick()
            picker.destroy()
        ctk.CTkButton(btns, text="Cancel", command=picker.destroy, width=100,
                      fg_color=pal.panel_alt, hover_color=pal.border, text_color=pal.text).pack(side="right", padx=4)
        ctk.CTkButton(btns, text="Use This Sound", command=confirm, width=160,
                      fg_color=pal.accent, hover_color=pal.accent_hover, text_color=pal.accent_text).pack(side="right", padx=4)

        self._setup_dialog(picker, title=f"Substitute for {missing_name}",
                           default_size=(520, 480), min_size=(420, 380),
                           parent=parent)

    def _apply_verify_fix(self, folder, substitutions, orphans_to_move):
        """Apply the substitution plan and orphan archive plan. Returns a human-readable summary."""
        blocks_changed = 0
        files_moved = 0
        files_skipped = []

        # ----- 1) Rewrite missing references in self.lines -----
        if substitutions:
            sub_norm = {self._norm_name(k): v for k, v in substitutions.items()}
            for i, line in enumerate(self.lines):
                raw = line.rstrip("\n")
                stripped = raw.strip()
                leading = raw[:len(raw) - len(raw.lstrip(" \t"))]
                m_c = SOUND_RE_CUSTOM.match(stripped)
                if not m_c:
                    continue
                comment_prefix, kw, filename, vol = m_c.groups()
                key = self._norm_name(filename)
                if key not in sub_norm:
                    continue
                new_filename = sub_norm[key]
                vol_part = f" {vol}" if vol else f" {self.settings.default_volume}"
                self.lines[i] = f'{leading}{(comment_prefix or "")}{kw} "{new_filename}"{vol_part}\n'
                blocks_changed += 1

            save_filter_file(
                self.filter_path, self.lines,
                create_backup=self.settings.create_backups,
                max_backups=self.settings.max_backups,
            )

        # ----- 2) Move orphans to "old sound files/" subfolder -----
        if orphans_to_move:
            target_dir = os.path.join(folder, self.OLD_SOUNDS_FOLDER)
            try:
                os.makedirs(target_dir, exist_ok=True)
            except OSError as e:
                raise RuntimeError(f"Could not create {target_dir!r}: {e}")

            for fn in orphans_to_move:
                src = os.path.join(folder, fn)
                dst = os.path.join(target_dir, fn)
                if os.path.normpath(src) == os.path.normpath(dst):
                    continue
                if os.path.exists(dst):
                    # Don't overwrite an existing archived copy — suffix with timestamp.
                    base, ext = os.path.splitext(fn)
                    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                    dst = os.path.join(target_dir, f"{base}_{ts}{ext}")
                try:
                    shutil.move(src, dst)
                    files_moved += 1
                except OSError as e:
                    files_skipped.append(f"{fn}: {e}")

        # ----- Summary string -----
        parts = []
        if blocks_changed:
            parts.append(f"• Replaced sound reference on {blocks_changed} block(s) in the filter.")
        if files_moved:
            parts.append(f"• Archived {files_moved} orphan file(s) to “{self.OLD_SOUNDS_FOLDER}/”.")
        if files_skipped:
            preview = "\n      ".join(files_skipped[:5])
            more = f"\n      …and {len(files_skipped) - 5} more" if len(files_skipped) > 5 else ""
            parts.append(f"• Could not move {len(files_skipped)} file(s):\n      {preview}{more}")
        if not parts:
            parts.append("No changes were applied.")
        return "\n".join(parts)

    # ============================================================
    # Make Sounds Unique — de-duplicate sound assignments across blocks
    # ============================================================
    def make_sounds_unique(self):
        """Randomize sounds across the current filtered set to reduce duplication."""
        if not self.filter_path:
            messagebox.showinfo("No filter", "Load a filter file first.")
            return

        # Working set = currently visible CustomAlertSound rows (sidebar + search applied).
        # We deliberately scope to filtered_data so users can target e.g. just Uniques.
        # Commented (disabled) rules are excluded since changing them does nothing in-game.
        working = [
            e for e in self.filtered_data
            if e.get("stype") == "Custom" and not e.get("commented")
        ]
        if not working:
            messagebox.showinfo(
                "Nothing to randomize",
                "No active CustomAlertSound rules are visible right now.\n\n"
                "Tip: click 'All Categories' in the sidebar (or pick a section like 'Uniques') "
                "to widen the working set, then run this again.",
            )
            return

        folder = os.path.dirname(self.filter_path)
        pool = self._collect_sound_pool(folder)
        if not pool:
            if messagebox.askyesno(
                "No sound files",
                f"There are no audio files in:\n  {folder}\n\n"
                "Open the folder so you can add some?",
            ):
                self._open_folder(folder)
            return

        from collections import Counter
        current_usage = Counter(e["sound"] for e in working)
        self._open_make_unique_dialog(folder, working, pool, current_usage)

    def _collect_sound_pool(self, folder):
        """Audio files in the top level of `folder` (excludes 'old sound files/' implicitly)."""
        try:
            return sorted(
                f for f in os.listdir(folder)
                if os.path.splitext(f)[1].lower() in self.AUDIO_EXTS
                and os.path.isfile(os.path.join(folder, f))
            )
        except OSError:
            return []

    def _open_make_unique_dialog(self, folder, working, pool, current_usage):
        pal = self.theme_manager.current()
        dlg = ctk.CTkToplevel(self.root)
        main = ctk.CTkFrame(dlg, fg_color=pal.panel)
        main.pack(fill="both", expand=True, padx=12, pady=12)

        block_count = len(working)
        unique_now = len(current_usage)
        pool_size = len(pool)
        can_all_unique = pool_size >= block_count
        # ceil(N/P): the maximum duplication you can guarantee with the balanced strategy
        balanced_cap = (block_count + pool_size - 1) // pool_size if pool_size else 0

        # ----- Header -----
        ctk.CTkLabel(main, text="Make Sounds Unique",
                     font=("Segoe UI Semibold", 16)).pack(anchor="w")
        ctk.CTkLabel(
            main,
            text="Reassigns sounds across the currently visible CustomAlertSound rules "
                 "(respects the sidebar + search filter).",
            text_color=pal.text_muted, wraplength=720, justify="left",
        ).pack(anchor="w", pady=(0, 6))

        # ----- Stats strip -----
        stats = ctk.CTkFrame(main, fg_color=pal.panel_alt)
        stats.pack(fill="x", pady=(4, 8))
        def stat(parent, big, label, color=None):
            box = ctk.CTkFrame(parent, fg_color="transparent")
            box.pack(side="left", padx=16, pady=8)
            ctk.CTkLabel(box, text=str(big),
                         font=("Segoe UI Semibold", 18),
                         text_color=color or pal.text).pack(anchor="w")
            ctk.CTkLabel(box, text=label, text_color=pal.text_muted).pack(anchor="w")
        stat(stats, block_count, "blocks in working set")
        stat(stats, unique_now, "unique sounds used now")
        pool_color = pal.smart_fg if can_all_unique else "#f0a020"
        stat(stats, pool_size, "audio files in pool", color=pool_color)
        ctk.CTkButton(
            stats, text="Refresh Pool", width=120,
            command=lambda: (dlg.destroy(), self.make_sounds_unique()),
            fg_color=pal.panel_alt, hover_color=pal.border, text_color=pal.text,
        ).pack(side="right", padx=12, pady=8)

        # ----- Duplicate list -----
        dup_items = [(s, c) for s, c in current_usage.most_common() if c > 1]
        if dup_items:
            ctk.CTkLabel(
                main,
                text=f"Currently duplicated ({len(dup_items)} file(s) used >1 time):",
                font=("Segoe UI Semibold", 11),
            ).pack(anchor="w", pady=(4, 2))
            dup_frame = ctk.CTkFrame(main, fg_color=pal.panel_alt)
            dup_frame.pack(fill="x", pady=(0, 6))
            for s, c in dup_items[:10]:
                ctk.CTkLabel(dup_frame, text=f"  {c:>4}×   {s}",
                             text_color=pal.text_muted, font=("Consolas", 10)).pack(anchor="w", padx=8)
            if len(dup_items) > 10:
                ctk.CTkLabel(dup_frame, text=f"  ... and {len(dup_items) - 10} more",
                             text_color=pal.text_muted).pack(anchor="w", padx=8)
        else:
            ctk.CTkLabel(
                main,
                text="✓ The working set already has no duplicated sounds.",
                font=("Segoe UI Semibold", 12), text_color=pal.smart_fg,
            ).pack(anchor="w", pady=(4, 4))

        # ----- Shortfall warning + add-files prompt -----
        if not can_all_unique:
            warn = ctk.CTkFrame(main, fg_color="#5b3a0c")
            warn.pack(fill="x", pady=8)
            ctk.CTkLabel(
                warn,
                text="⚠ Not enough sound files to give every block a unique sound.",
                font=("Segoe UI Semibold", 11), text_color="#ffffff",
            ).pack(anchor="w", padx=10, pady=(8, 2))
            ctk.CTkLabel(
                warn,
                text=(f"You have {block_count} blocks but only {pool_size} sound file(s) in:\n"
                      f"  {folder}\n\n"
                      f"Shortfall: {block_count - pool_size} sound(s).\n\n"
                      f"You can either:\n"
                      f"  • Add more audio files to the folder, then click 'Refresh Pool' above, or\n"
                      f"  • Pick 'Minimize duplication' below — each sound is then used at most "
                      f"{balanced_cap} time(s) instead of the current max of {max(current_usage.values()) if current_usage else 0}."),
                justify="left", text_color="#ffffff", wraplength=720,
            ).pack(anchor="w", padx=10, pady=(0, 4))
            row = ctk.CTkFrame(warn, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=(0, 8))
            ctk.CTkButton(row, text="Open Sound Folder", width=160,
                          command=lambda: self._open_folder(folder),
                          fg_color=pal.accent, hover_color=pal.accent_hover,
                          text_color=pal.accent_text).pack(side="left")

        # ----- Strategy radios -----
        strategy_var = ctk.StringVar(value="unique" if can_all_unique else "balanced")
        sframe = ctk.CTkFrame(main, fg_color="transparent")
        sframe.pack(fill="x", pady=(8, 4))
        ctk.CTkLabel(sframe, text="Strategy:", font=("Segoe UI Semibold", 11)).pack(anchor="w")
        ctk.CTkRadioButton(
            sframe,
            text=f"Every block unique (1:1 assignment) — needs {block_count} sounds, "
                 f"you have {pool_size}" + ("  ✓" if can_all_unique else "  ✗ disabled"),
            variable=strategy_var, value="unique", state=("normal" if can_all_unique else "disabled"),
        ).pack(anchor="w", padx=14, pady=2)
        ctk.CTkRadioButton(
            sframe,
            text=f"Minimize duplication (each sound used ≤ {balanced_cap} time(s), evenly distributed)",
            variable=strategy_var, value="balanced",
        ).pack(anchor="w", padx=14, pady=2)
        ctk.CTkRadioButton(
            sframe,
            text="Pure random (each block independently — duplicates allowed)",
            variable=strategy_var, value="random",
        ).pack(anchor="w", padx=14, pady=2)

        # ----- Action buttons -----
        btn_row = ctk.CTkFrame(main, fg_color="transparent")
        btn_row.pack(fill="x", pady=(12, 0))

        def apply():
            strategy = strategy_var.get()
            assignment = self._compute_unique_assignment(working, pool, strategy)
            n_changed = self._apply_sound_assignment(assignment)
            if n_changed == 0:
                dlg.destroy()
                messagebox.showinfo("No changes", "Random assignment happened to match the existing sounds — nothing was written.")
                return
            try:
                save_filter_file(
                    self.filter_path, self.lines,
                    create_backup=self.settings.create_backups,
                    max_backups=self.settings.max_backups,
                )
            except Exception as e:
                messagebox.showerror("Save error", str(e))
                return
            dlg.destroy()
            messagebox.showinfo(
                "Done",
                f"Reassigned sound on {n_changed} block(s)\n"
                f"Strategy: {strategy}\n"
                f"Pool size: {len(pool)} file(s)",
            )
            # Reload so the table, sidebar counts, and health indicator all refresh
            self.load_filter_from_path(self.filter_path)

        ctk.CTkButton(btn_row, text="Cancel", command=dlg.destroy, width=120,
                      fg_color=pal.panel_alt, hover_color=pal.border, text_color=pal.text).pack(side="right", padx=4)
        ctk.CTkButton(btn_row, text="Apply", command=apply, width=140,
                      fg_color=pal.accent, hover_color=pal.accent_hover, text_color=pal.accent_text).pack(side="right", padx=4)

        self._setup_dialog(dlg, title="Make Sounds Unique",
                           default_size=(840, 740), min_size=(720, 620))

    def _compute_unique_assignment(self, working, pool, strategy):
        """Build the (entry -> new_sound) plan for the chosen strategy.

        Returns a list of (entry, new_sound_filename) tuples covering every entry in
        `working`. Blocks are shuffled first so any forced duplication (balanced /
        random) is spread across the filter, not clustered in one section.
        """
        import random
        block_count = len(working)
        if block_count == 0:
            return []

        shuffled_blocks = list(working)
        random.shuffle(shuffled_blocks)

        if strategy == "unique" and len(pool) < block_count:
            # Defensive fallback — UI prevents picking this when pool is short
            strategy = "balanced"

        if strategy == "unique":
            sounds = random.sample(pool, block_count)
        elif strategy == "balanced":
            shuffled_pool = list(pool)
            random.shuffle(shuffled_pool)
            # Round-robin so each pool item is used floor(N/P) or ceil(N/P) times
            sounds = [shuffled_pool[i % len(shuffled_pool)] for i in range(block_count)]
            random.shuffle(sounds)  # break the round-robin pattern
        else:  # "random"
            sounds = [random.choice(pool) for _ in range(block_count)]

        return list(zip(shuffled_blocks, sounds))

    def _apply_sound_assignment(self, assignment):
        """Write the (entry -> new_sound) plan into self.lines.

        Each entry is one CustomAlertSound line in the file (an entry's start_idx is
        the block's Show/Hide line, but the matched line might be any line in the
        block). We rescan the block bounds and update the FIRST line whose original
        filename matches entry["sound"] — guarantees per-entry one-line semantics
        even when a block has multiple sound lines.
        """
        n_changed = 0
        for entry, new_sound in assignment:
            if not new_sound or new_sound == entry["sound"]:
                continue
            b_start, b_end = self._block_bounds(entry["start_idx"])
            for i in range(b_start, b_end):
                raw = self.lines[i].rstrip("\n")
                stripped = raw.strip()
                leading = raw[:len(raw) - len(raw.lstrip(" \t"))]
                m_c = SOUND_RE_CUSTOM.match(stripped)
                if not m_c:
                    continue
                comment_prefix, kw, filename, vol = m_c.groups()
                if comment_prefix:
                    continue  # skip commented-out lines
                if filename != entry["sound"]:
                    continue
                vol_part = f" {vol}" if vol else f" {self.settings.default_volume}"
                self.lines[i] = f'{leading}{kw} "{new_sound}"{vol_part}\n'
                n_changed += 1
                break
        return n_changed

    # ============================================================
    # Filter Statistics
    # ============================================================
    def show_filter_statistics(self):
        if not self.filter_data:
            messagebox.showinfo("No data", "Load a filter file first.")
            return
        from collections import Counter
        total = len(self.filter_data)
        with_sound = sum(1 for e in self.filter_data if e.get("stype") != "None")
        custom_sound = sum(1 for e in self.filter_data if e.get("stype") == "Custom")
        play_sound = sum(1 for e in self.filter_data if e.get("stype") == "Play")
        commented = sum(1 for e in self.filter_data if e.get("commented"))
        show_blocks = sum(1 for e in self.filter_data if e.get("header", "").startswith("Show"))
        hide_blocks = sum(1 for e in self.filter_data if e.get("header", "").startswith("Hide"))
        with_effect = sum(1 for e in self.filter_data if e.get("effect"))
        with_minimap = sum(1 for e in self.filter_data if e.get("minimap"))

        section_counts = Counter(e.get("category", "") for e in self.filter_data)
        top_sections = section_counts.most_common(15)

        sound_counts = Counter(e.get("sound") for e in self.filter_data if e.get("stype") == "Custom")
        top_sounds = sound_counts.most_common(10)

        dlg = ctk.CTkToplevel(self.root)
        pal = self.theme_manager.current()
        f = ctk.CTkFrame(dlg, fg_color=pal.panel); f.pack(fill="both", expand=True, padx=14, pady=14)

        def line(text, bold=False, muted=False):
            ctk.CTkLabel(f, text=text,
                         font=("Segoe UI Semibold", 12) if bold else ("Segoe UI", 11),
                         text_color=pal.text_muted if muted else pal.text,
                         justify="left", anchor="w").pack(anchor="w", pady=1, fill="x")

        line(os.path.basename(self.filter_path or "(unsaved)"), bold=True)
        line(f"{total} blocks  •  {show_blocks} Show  •  {hide_blocks} Hide", muted=True)
        line("")
        line("Sound", bold=True)
        line(f"  With sound:     {with_sound}")
        line(f"  Without sound:  {total - with_sound}")
        line(f"  CustomAlertSound:  {custom_sound}")
        line(f"  PlayAlertSound:    {play_sound}")
        line(f"  Disabled (commented): {commented}")
        line("")
        line("Visual", bold=True)
        line(f"  With PlayEffect:  {with_effect}")
        line(f"  With MinimapIcon: {with_minimap}")
        line("")
        line("Top sections by block count", bold=True)
        for name, n in top_sections:
            line(f"  {n:>4}   {name or '(uncategorized)'}", muted=True)
        line("")
        if top_sounds:
            line("Most-used sound files", bold=True)
            for fn, n in top_sounds:
                line(f"  {n:>4}×   {fn}", muted=True)

        ctk.CTkButton(f, text="Close", command=dlg.destroy, width=100,
                      fg_color=pal.panel_alt, hover_color=pal.border, text_color=pal.text).pack(side="right", pady=(8, 0))

        self._setup_dialog(dlg, title="Filter Statistics",
                           default_size=(700, 680), min_size=(580, 520))


if __name__ == '__main__':
    root = ctk.CTk()
    # Apply the chosen icon to the root window too (some platforms set the taskbar icon from this).
    try:
        if APP_ICON_PATH:
            root.iconbitmap(APP_ICON_PATH)
    except Exception:
        pass
    app = FilterSoundEditor(root)
    root.mainloop()
