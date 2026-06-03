"""Palette-based theming for the POE2 Filter Sound Editor.

CTk's built-in `set_default_color_theme()` only takes effect for *future*
widgets, which is why the original app's theme switch appeared broken — only
the first selection ever applied.

This module replaces that with a Palette object that drives BOTH the ttk
Treeview style AND every CTk widget we care about, applied live by walking
the widget tree on theme change.

Add a new theme by appending a Palette to BUILTIN_PALETTES.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import customtkinter as ctk
from tkinter import ttk


@dataclass(frozen=True)
class Palette:
    name: str
    # Background layers (outermost -> innermost)
    bg: str
    panel: str
    panel_alt: str
    # Treeview
    tree_bg: str
    tree_fg: str
    tree_row_even: str
    tree_row_odd: str
    tree_sel_bg: str
    tree_sel_fg: str
    tree_heading_bg: str
    tree_heading_fg: str
    # Accent (used for primary buttons, selection rings)
    accent: str
    accent_hover: str
    accent_text: str
    # Misc
    text: str
    text_muted: str
    border: str
    danger: str         # for destructive buttons
    danger_hover: str
    # Sidebar categories
    group_header_bg: str
    group_header_fg: str
    smart_fg: str
    # Implicit: is_dark drives Light/Dark appearance choice
    is_dark: bool


# =====================================================================
# Built-in palettes
# =====================================================================
# Note: when adding, follow the existing structure exactly so the
# ThemeManager can apply each Palette without special-casing.

BUILTIN_PALETTES: List[Palette] = [
    Palette(
        name="Default Dark",
        bg="#1e1e1e", panel="#262626", panel_alt="#2f2f2f",
        tree_bg="#2b2b2b", tree_fg="#ffffff",
        tree_row_even="#292929", tree_row_odd="#2f2f2f",
        tree_sel_bg="#4a6fa5", tree_sel_fg="#ffffff",
        tree_heading_bg="#3a3a3a", tree_heading_fg="#ffffff",
        accent="#3b8ed0", accent_hover="#36719f", accent_text="#ffffff",
        text="#e9e9e9", text_muted="#9a9a9a",
        border="#3a3a3a", danger="#8a3030", danger_hover="#a23636",
        group_header_bg="#3a3a3a", group_header_fg="#ffe49a", smart_fg="#a4d4ff",
        is_dark=True,
    ),
    Palette(
        name="Default Light",
        bg="#f4f4f4", panel="#ffffff", panel_alt="#e9e9e9",
        tree_bg="#ffffff", tree_fg="#1a1a1a",
        tree_row_even="#ffffff", tree_row_odd="#f3f3f3",
        tree_sel_bg="#3a78c2", tree_sel_fg="#ffffff",
        tree_heading_bg="#dedede", tree_heading_fg="#1a1a1a",
        accent="#3b8ed0", accent_hover="#2e6fa3", accent_text="#ffffff",
        text="#1a1a1a", text_muted="#666666",
        border="#cfcfcf", danger="#c93a3a", danger_hover="#a82c2c",
        group_header_bg="#dedede", group_header_fg="#5a3b00", smart_fg="#1a5fa8",
        is_dark=False,
    ),
    # ---- PoE2-class themed dark palettes ----
    Palette(
        name="PoE2 — Witch (Necro Purple)",
        bg="#170a1f", panel="#1f1230", panel_alt="#28163b",
        tree_bg="#1c0f29", tree_fg="#eadcff",
        tree_row_even="#1a0e26", tree_row_odd="#22142e",
        tree_sel_bg="#6c3fb5", tree_sel_fg="#ffffff",
        tree_heading_bg="#2a1542", tree_heading_fg="#d3b8ff",
        accent="#8b5cf6", accent_hover="#7245d4", accent_text="#ffffff",
        text="#eadcff", text_muted="#9b86c0",
        border="#3a1f5a", danger="#7d2929", danger_hover="#a83838",
        group_header_bg="#2a1542", group_header_fg="#ffd6a0", smart_fg="#d3b8ff",
        is_dark=True,
    ),
    Palette(
        name="PoE2 — Mercenary (Crimson)",
        bg="#160a0a", panel="#22100f", panel_alt="#2e1716",
        tree_bg="#1f0e0d", tree_fg="#ffe1d6",
        tree_row_even="#1d0c0b", tree_row_odd="#251111",
        tree_sel_bg="#b03434", tree_sel_fg="#ffffff",
        tree_heading_bg="#3a1716", tree_heading_fg="#ffb39d",
        accent="#d94545", accent_hover="#b53636", accent_text="#ffffff",
        text="#ffe1d6", text_muted="#c79285",
        border="#4a1c1b", danger="#6f1818", danger_hover="#902020",
        group_header_bg="#3a1716", group_header_fg="#ffd6a0", smart_fg="#ffb39d",
        is_dark=True,
    ),
    Palette(
        name="PoE2 — Sorceress (Ice)",
        bg="#0a151f", panel="#102233", panel_alt="#15304a",
        tree_bg="#0e1f30", tree_fg="#d8ecff",
        tree_row_even="#0c1d2d", tree_row_odd="#122538",
        tree_sel_bg="#2f7fcf", tree_sel_fg="#ffffff",
        tree_heading_bg="#173554", tree_heading_fg="#9fd0ff",
        accent="#4aa3ff", accent_hover="#3784d8", accent_text="#0a1828",
        text="#d8ecff", text_muted="#7ea4c5",
        border="#1f4670", danger="#7d2929", danger_hover="#a13434",
        group_header_bg="#173554", group_header_fg="#ffe49a", smart_fg="#9fd0ff",
        is_dark=True,
    ),
    Palette(
        name="PoE2 — Monk (Jade)",
        bg="#0c1714", panel="#11211c", panel_alt="#162d26",
        tree_bg="#0e1d18", tree_fg="#d6f0e2",
        tree_row_even="#0c1b16", tree_row_odd="#10221c",
        tree_sel_bg="#2f9a6a", tree_sel_fg="#ffffff",
        tree_heading_bg="#16352a", tree_heading_fg="#a9e2c2",
        accent="#3fb583", accent_hover="#319269", accent_text="#06170f",
        text="#d6f0e2", text_muted="#7ea696",
        border="#1f4937", danger="#7d2929", danger_hover="#a13434",
        group_header_bg="#16352a", group_header_fg="#ffe49a", smart_fg="#a9e2c2",
        is_dark=True,
    ),
    Palette(
        name="PoE2 — Druid (Forest)",
        bg="#13130a", panel="#1d1d11", panel_alt="#272716",
        tree_bg="#1a1a0e", tree_fg="#e9e4cd",
        tree_row_even="#18180d", tree_row_odd="#1f1f12",
        tree_sel_bg="#7a8a3c", tree_sel_fg="#ffffff",
        tree_heading_bg="#2c2c16", tree_heading_fg="#dcd49a",
        accent="#9aae46", accent_hover="#778833", accent_text="#181808",
        text="#e9e4cd", text_muted="#a8a07c",
        border="#3a3a1b", danger="#7d4a29", danger_hover="#a16434",
        group_header_bg="#2c2c16", group_header_fg="#ffd6a0", smart_fg="#dcd49a",
        is_dark=True,
    ),
    Palette(
        name="PoE2 — Warrior (Bronze)",
        bg="#1a120a", panel="#241910", panel_alt="#312317",
        tree_bg="#1f1610", tree_fg="#ffe6c8",
        tree_row_even="#1d1410", tree_row_odd="#241914",
        tree_sel_bg="#a06b2b", tree_sel_fg="#ffffff",
        tree_heading_bg="#3a2716", tree_heading_fg="#ffcf94",
        accent="#c98a3c", accent_hover="#a36e2e", accent_text="#1a0e04",
        text="#ffe6c8", text_muted="#bf9974",
        border="#4a3220", danger="#7d2929", danger_hover="#a13434",
        group_header_bg="#3a2716", group_header_fg="#ffcf94", smart_fg="#ffcf94",
        is_dark=True,
    ),
    Palette(
        name="PoE2 — Huntress (Steel)",
        bg="#11161c", panel="#192029", panel_alt="#222c38",
        tree_bg="#141a22", tree_fg="#e2eaf4",
        tree_row_even="#121822", tree_row_odd="#181f29",
        tree_sel_bg="#5a7ba0", tree_sel_fg="#ffffff",
        tree_heading_bg="#212a36", tree_heading_fg="#b6cae0",
        accent="#7a9fcb", accent_hover="#5e7faa", accent_text="#0d1218",
        text="#e2eaf4", text_muted="#8da3ba",
        border="#2c3848", danger="#7d2929", danger_hover="#a13434",
        group_header_bg="#212a36", group_header_fg="#ffe49a", smart_fg="#b6cae0",
        is_dark=True,
    ),
    # ---- Designer palettes ----
    Palette(
        name="Solarized Dark",
        bg="#002b36", panel="#073642", panel_alt="#0a4250",
        tree_bg="#022832", tree_fg="#eee8d5",
        tree_row_even="#022832", tree_row_odd="#03323e",
        tree_sel_bg="#268bd2", tree_sel_fg="#ffffff",
        tree_heading_bg="#073642", tree_heading_fg="#93a1a1",
        accent="#268bd2", accent_hover="#1f6fa8", accent_text="#ffffff",
        text="#eee8d5", text_muted="#93a1a1",
        border="#0a4250", danger="#dc322f", danger_hover="#b3201d",
        group_header_bg="#073642", group_header_fg="#b58900", smart_fg="#2aa198",
        is_dark=True,
    ),
    Palette(
        name="Nord",
        bg="#2e3440", panel="#3b4252", panel_alt="#434c5e",
        tree_bg="#2e3440", tree_fg="#eceff4",
        tree_row_even="#2e3440", tree_row_odd="#343a48",
        tree_sel_bg="#5e81ac", tree_sel_fg="#ffffff",
        tree_heading_bg="#3b4252", tree_heading_fg="#d8dee9",
        accent="#88c0d0", accent_hover="#6fa6b8", accent_text="#2e3440",
        text="#eceff4", text_muted="#a3b0c2",
        border="#4c566a", danger="#bf616a", danger_hover="#9b4d54",
        group_header_bg="#3b4252", group_header_fg="#ebcb8b", smart_fg="#a3be8c",
        is_dark=True,
    ),
    Palette(
        name="Dracula",
        bg="#282a36", panel="#1f2129", panel_alt="#343746",
        tree_bg="#282a36", tree_fg="#f8f8f2",
        tree_row_even="#282a36", tree_row_odd="#2f313e",
        tree_sel_bg="#bd93f9", tree_sel_fg="#282a36",
        tree_heading_bg="#44475a", tree_heading_fg="#f8f8f2",
        accent="#ff79c6", accent_hover="#e066b0", accent_text="#282a36",
        text="#f8f8f2", text_muted="#9ea0b1",
        border="#44475a", danger="#ff5555", danger_hover="#d04545",
        group_header_bg="#44475a", group_header_fg="#f1fa8c", smart_fg="#8be9fd",
        is_dark=True,
    ),
    Palette(
        name="Cyberpunk Neon",
        bg="#0a0f1e", panel="#101729", panel_alt="#172238",
        tree_bg="#0c1322", tree_fg="#e7f0ff",
        tree_row_even="#0c1322", tree_row_odd="#10192a",
        tree_sel_bg="#ff2bd6", tree_sel_fg="#0a0f1e",
        tree_heading_bg="#17243d", tree_heading_fg="#0ff5d0",
        accent="#0ff5d0", accent_hover="#0bc7a9", accent_text="#0a0f1e",
        text="#e7f0ff", text_muted="#7a8aa8",
        border="#1f2c4a", danger="#ff2bd6", danger_hover="#cc23ab",
        group_header_bg="#17243d", group_header_fg="#fff66e", smart_fg="#0ff5d0",
        is_dark=True,
    ),
    Palette(
        name="High Contrast",
        bg="#000000", panel="#0a0a0a", panel_alt="#141414",
        tree_bg="#000000", tree_fg="#ffffff",
        tree_row_even="#000000", tree_row_odd="#0e0e0e",
        tree_sel_bg="#ffd700", tree_sel_fg="#000000",
        tree_heading_bg="#1a1a1a", tree_heading_fg="#ffffff",
        accent="#ffd700", accent_hover="#cda500", accent_text="#000000",
        text="#ffffff", text_muted="#bdbdbd",
        border="#3a3a3a", danger="#ff3030", danger_hover="#cc2222",
        group_header_bg="#1a1a1a", group_header_fg="#ffd700", smart_fg="#00ffff",
        is_dark=True,
    ),
]


def palette_names() -> List[str]:
    return [p.name for p in BUILTIN_PALETTES]


def get_palette(name: str) -> Palette:
    for p in BUILTIN_PALETTES:
        if p.name == name:
            return p
    return BUILTIN_PALETTES[0]


# =====================================================================
# ThemeManager
# =====================================================================

class ThemeManager:
    """Applies a Palette to ttk.Style and every CTk widget that registers with it.

    Usage:
        tm = ThemeManager()
        tm.register_widget(my_button, role="primary")  # roles drive what gets recolored
        tm.apply("Default Dark", appearance_mode="Dark")
    """

    # CTk widget "roles" we know how to style
    ROLE_PRIMARY = "primary"     # main accent buttons
    ROLE_DANGER = "danger"       # destructive buttons
    ROLE_GHOST = "ghost"         # neutral buttons / option menus
    ROLE_PANEL = "panel"         # CTkFrame outer container
    ROLE_PANEL_ALT = "panel_alt" # nested CTkFrame
    ROLE_TEXT = "text"           # CTkLabel / muted text
    ROLE_TEXT_MUTED = "text_muted"
    ROLE_ENTRY = "entry"         # CTkEntry
    ROLE_CHECKBOX = "checkbox"   # CTkCheckBox

    def __init__(self):
        self._registry: List[Tuple[object, str]] = []
        self._tree_tags: List[Tuple[object, Dict[str, str]]] = []
        self._current: Palette = BUILTIN_PALETTES[0]
        self._style: ttk.Style = ttk.Style()

    # ----- registration -----

    def register_widget(self, widget, role: str = ROLE_PANEL) -> None:
        self._registry.append((widget, role))

    def register_treeview_tags(self, tree, tag_role_map: Dict[str, str]) -> None:
        """Track a ttk.Treeview so its tag colors update on theme change.

        tag_role_map: {"oddrow": "tree_row_odd", "evenrow": "tree_row_even",
                       "group_header": "group_header", "smart": "smart", "muted": "text_muted"}
        """
        self._tree_tags.append((tree, tag_role_map))

    def current(self) -> Palette:
        return self._current

    # ----- application -----

    def apply(self, palette_name: str, appearance_mode: str = "Dark") -> Palette:
        pal = get_palette(palette_name)
        self._current = pal

        # 1) CTk appearance mode (light/dark). System honours OS setting.
        mode = appearance_mode if appearance_mode in ("Light", "Dark", "System") else ("Dark" if pal.is_dark else "Light")
        try:
            ctk.set_appearance_mode(mode)
        except Exception:
            pass

        # 2) ttk Treeview style
        try:
            self._style.theme_use("clam")
        except Exception:
            pass

        self._style.configure(
            "Treeview",
            background=pal.tree_bg,
            foreground=pal.tree_fg,
            fieldbackground=pal.tree_bg,
            rowheight=28,
            bordercolor=pal.border,
            font=("Segoe UI", 10),
        )
        self._style.configure(
            "Treeview.Heading",
            background=pal.tree_heading_bg,
            foreground=pal.tree_heading_fg,
            font=("Segoe UI", 10, "bold"),
        )
        self._style.map(
            "Treeview",
            background=[("selected", pal.tree_sel_bg)],
            foreground=[("selected", pal.tree_sel_fg)],
        )

        # 3) Walk every registered CTk widget and reconfigure
        for widget, role in list(self._registry):
            try:
                self._apply_to_widget(widget, role, pal)
            except Exception:
                # Widget may have been destroyed
                pass

        # 4) Treeview tag colors
        for tree, mapping in list(self._tree_tags):
            for tag, role in mapping.items():
                try:
                    if role == "tree_row_even":
                        tree.tag_configure(tag, background=pal.tree_row_even, foreground=pal.tree_fg)
                    elif role == "tree_row_odd":
                        tree.tag_configure(tag, background=pal.tree_row_odd, foreground=pal.tree_fg)
                    elif role == "group_header":
                        tree.tag_configure(tag, background=pal.group_header_bg,
                                           foreground=pal.group_header_fg,
                                           font=("Segoe UI", 10, "bold"))
                    elif role == "smart":
                        tree.tag_configure(tag, foreground=pal.smart_fg)
                    elif role == "text_muted":
                        tree.tag_configure(tag, foreground=pal.text_muted)
                except Exception:
                    pass

        return pal

    def _apply_to_widget(self, widget, role: str, pal: Palette) -> None:
        cls = type(widget).__name__

        if role == self.ROLE_PRIMARY and cls == "CTkButton":
            widget.configure(fg_color=pal.accent, hover_color=pal.accent_hover, text_color=pal.accent_text)
        elif role == self.ROLE_DANGER and cls == "CTkButton":
            widget.configure(fg_color=pal.danger, hover_color=pal.danger_hover, text_color="#ffffff")
        elif role == self.ROLE_GHOST and cls in ("CTkButton", "CTkOptionMenu"):
            widget.configure(fg_color=pal.panel_alt, hover_color=pal.border, text_color=pal.text)
        elif role == self.ROLE_PANEL and cls in ("CTkFrame", "CTk"):
            widget.configure(fg_color=pal.panel)
        elif role == self.ROLE_PANEL_ALT and cls == "CTkFrame":
            widget.configure(fg_color=pal.panel_alt)
        elif role == self.ROLE_TEXT and cls == "CTkLabel":
            widget.configure(text_color=pal.text)
        elif role == self.ROLE_TEXT_MUTED and cls == "CTkLabel":
            widget.configure(text_color=pal.text_muted)
        elif role == self.ROLE_ENTRY and cls == "CTkEntry":
            widget.configure(fg_color=pal.tree_bg, text_color=pal.tree_fg, border_color=pal.border)
        elif role == self.ROLE_CHECKBOX and cls == "CTkCheckBox":
            widget.configure(fg_color=pal.accent, hover_color=pal.accent_hover, text_color=pal.text)
