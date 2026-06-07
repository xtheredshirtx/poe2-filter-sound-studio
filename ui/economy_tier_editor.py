"""Per-tier visual style editor for the Economy Tier feature.

Lets the user choose, for each value tier (SS_CHANCE_BASE, SS, S, A, B, C, D, F),
the master colours (text / background / border), font size, the **beacon**
(``PlayEffect`` — the ground light beam) and the **beacon light** (``MinimapIcon``
— the minimap marker), then save it as a named preset. Presets live in the user's
config dir next to the shipped default and appear in the Economy Tier dialog's
Template dropdown.

The editor only ever produces the six visual directives; it can never add a sound
directive. Saved presets are schema- and token-validated before they replace the
preset file (handled by ``visual_template_loader.save_user_template``).
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox

import customtkinter as ctk

from economy_tier.directive_value_validator import MINIMAP_SHAPES, NAMED_COLORS
from economy_tier.economy_tier_data import TIER_ORDER
from economy_tier.errors import TemplateError
from economy_tier.visual_template_loader import (
    Template,
    TierStyle,
    delete_user_template,
    save_user_template,
)
from ui.dialogs import ColorPickerDialog

_NONE = "None"
_BEAM_COLORS = [_NONE, *NAMED_COLORS]
_MM_SIZES = [_NONE, "0", "1", "2"]

# Fallback style for a tier the starting template doesn't define.
_DEFAULT = TierStyle(
    text_color=(255, 255, 255, 255),
    bg_color=(20, 20, 20, 200),
    border_color=(120, 120, 120, 255),
    font_size=35,
)


def open_tier_style_editor(app, controller, on_saved: Callable[[str], None] | None = None) -> None:
    """Open the editor seeded from the controller's current template."""
    _TierStyleEditor(app, controller, on_saved)


class _TierStyleEditor:
    def __init__(self, app, controller, on_saved=None):
        self.app = app
        self.controller = controller
        self.on_saved = on_saved
        self.pal = app.theme_manager.current()
        start = controller.template()
        self.start_name = start.name
        self.is_user_start = controller.templates.is_user(start.name)

        # Working state per tier: a plain dict we mutate as the user edits.
        self.state: dict[str, dict] = {}
        for tier in TIER_ORDER:
            self.state[tier] = self._style_to_state(start.tiers.get(tier) or _DEFAULT)

        self.dlg = ctk.CTkToplevel(app.root)
        wrapper = ctk.CTkFrame(self.dlg, fg_color=self.pal.panel)
        wrapper.pack(fill="both", expand=True, padx=12, pady=12)

        ctk.CTkLabel(wrapper, text="Edit Tier Styles", font=("Segoe UI Semibold", 14)).pack(
            anchor="w"
        )
        ctk.CTkLabel(
            wrapper,
            text=(
                "Set how each value tier looks. 'Beam' is the ground PlayEffect; "
                "'Minimap' is the map marker. Click a colour swatch to change it. "
                "Sounds are never affected. Save as a named preset to use it."
            ),
            text_color=self.pal.text_muted,
            wraplength=940,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        # Name row.
        name_row = ctk.CTkFrame(wrapper, fg_color="transparent")
        name_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(name_row, text="Preset name:").pack(side="left", padx=(0, 6))
        self.name_var = tk.StringVar(
            value=self.start_name if self.is_user_start else f"{self.start_name} (copy)"
        )
        ctk.CTkEntry(name_row, textvariable=self.name_var, width=320).pack(side="left")

        self._build_grid(wrapper)
        self._build_buttons(wrapper)

        app._setup_dialog(
            self.dlg,
            title="Edit Tier Styles",
            default_size=(1040, 760),
            min_size=(900, 600),
        )

    # ---------------- state helpers ----------------

    @staticmethod
    def _style_to_state(style: TierStyle) -> dict:
        d = _DEFAULT
        return {
            "text": list(style.text_color or d.text_color),
            "bg": list(style.bg_color or d.bg_color),
            "border": list(style.border_color or d.border_color),
            "font": str(style.font_size if style.font_size is not None else d.font_size),
            "beam_color": style.play_effect[0] if style.play_effect else _NONE,
            "beam_temp": bool(style.play_effect[1]) if style.play_effect else True,
            "mm_size": str(style.minimap[0]) if style.minimap else _NONE,
            "mm_color": style.minimap[1] if style.minimap else "Red",
            "mm_shape": style.minimap[2] if style.minimap else "Circle",
        }

    # ---------------- grid ----------------

    def _build_grid(self, parent):
        frame = ctk.CTkScrollableFrame(parent, fg_color=self.pal.panel_alt, height=460)
        frame.pack(fill="both", expand=True, pady=4)

        headers = [
            "Tier",
            "Text",
            "Background",
            "Border",
            "Font",
            "Beam (PlayEffect)",
            "Temp",
            "Minimap size/colour/shape",
            "Preview",
        ]
        for col, text in enumerate(headers):
            ctk.CTkLabel(frame, text=text, font=("Segoe UI Semibold", 10)).grid(
                row=0, column=col, padx=4, pady=(2, 6), sticky="w"
            )

        self.widgets: dict[str, dict] = {}
        for r, tier in enumerate(TIER_ORDER, start=1):
            st = self.state[tier]
            w: dict = {}
            ctk.CTkLabel(frame, text=tier, font=("Segoe UI Semibold", 10)).grid(
                row=r, column=0, padx=4, pady=3, sticky="w"
            )

            w["text"] = self._color_swatch(frame, tier, "text", st["text"])
            w["text"].grid(row=r, column=1, padx=3, pady=3)
            w["bg"] = self._color_swatch(frame, tier, "bg", st["bg"])
            w["bg"].grid(row=r, column=2, padx=3, pady=3)
            w["border"] = self._color_swatch(frame, tier, "border", st["border"])
            w["border"].grid(row=r, column=3, padx=3, pady=3)

            font_var = tk.StringVar(value=st["font"])
            font_var.trace_add("write", lambda *_a, t=tier: self._on_font(t))
            w["font_var"] = font_var
            ctk.CTkEntry(frame, textvariable=font_var, width=48).grid(
                row=r, column=4, padx=3, pady=3
            )

            beam_var = tk.StringVar(value=st["beam_color"])
            w["beam_var"] = beam_var
            ctk.CTkOptionMenu(
                frame,
                values=_BEAM_COLORS,
                variable=beam_var,
                width=100,
                command=lambda _v, t=tier: self._on_change(t),
            ).grid(row=r, column=5, padx=3, pady=3)

            temp_var = tk.BooleanVar(value=st["beam_temp"])
            w["temp_var"] = temp_var
            ctk.CTkCheckBox(
                frame,
                text="",
                variable=temp_var,
                width=20,
                command=lambda t=tier: self._on_change(t),
            ).grid(row=r, column=6, padx=3, pady=3)

            mm_frame = ctk.CTkFrame(frame, fg_color="transparent")
            mm_frame.grid(row=r, column=7, padx=3, pady=3, sticky="w")
            size_var = tk.StringVar(value=st["mm_size"])
            mmcol_var = tk.StringVar(value=st["mm_color"])
            shape_var = tk.StringVar(value=st["mm_shape"])
            w["mm_size_var"], w["mm_color_var"], w["mm_shape_var"] = (
                size_var,
                mmcol_var,
                shape_var,
            )
            ctk.CTkOptionMenu(
                mm_frame,
                values=_MM_SIZES,
                variable=size_var,
                width=64,
                command=lambda _v, t=tier: self._on_change(t),
            ).pack(side="left", padx=1)
            ctk.CTkOptionMenu(
                mm_frame,
                values=list(NAMED_COLORS),
                variable=mmcol_var,
                width=84,
                command=lambda _v, t=tier: self._on_change(t),
            ).pack(side="left", padx=1)
            ctk.CTkOptionMenu(
                mm_frame,
                values=list(MINIMAP_SHAPES),
                variable=shape_var,
                width=110,
                command=lambda _v, t=tier: self._on_change(t),
            ).pack(side="left", padx=1)

            preview = tk.Label(frame, text=f" {tier} item ", font=("Segoe UI", 10, "bold"))
            preview.grid(row=r, column=8, padx=6, pady=3, sticky="w")
            w["preview"] = preview
            self.widgets[tier] = w
            self._refresh_preview(tier)

    def _color_swatch(self, parent, tier, key, rgba):
        btn = ctk.CTkButton(
            parent,
            text="",
            width=40,
            height=24,
            fg_color=_hex(rgba),
            hover=False,
            command=lambda: self._pick_color(tier, key),
        )
        return btn

    # ---------------- events ----------------

    def _pick_color(self, tier, key):
        def cb(rgba):
            self.state[tier][key] = list(rgba)
            self.widgets[tier][key].configure(fg_color=_hex(rgba))
            self._refresh_preview(tier)

        ColorPickerDialog(
            self.dlg,
            title=f"{tier} — {key} colour",
            initial_color=tuple(self.state[tier][key]),
            callback=cb,
        )

    def _on_font(self, tier):
        self.state[tier]["font"] = self.widgets[tier]["font_var"].get()
        self._refresh_preview(tier)

    def _on_change(self, tier):
        w = self.widgets[tier]
        st = self.state[tier]
        st["beam_color"] = w["beam_var"].get()
        st["beam_temp"] = bool(w["temp_var"].get())
        st["mm_size"] = w["mm_size_var"].get()
        st["mm_color"] = w["mm_color_var"].get()
        st["mm_shape"] = w["mm_shape_var"].get()
        self._refresh_preview(tier)

    def _refresh_preview(self, tier):
        st = self.state[tier]
        try:
            font_px = max(8, min(20, int(st["font"]) // 2))
        except (TypeError, ValueError):
            font_px = 10
        self.widgets[tier]["preview"].configure(
            bg=_hex(st["bg"]),
            fg=_hex(st["text"]),
            highlightthickness=2,
            highlightbackground=_hex(st["border"]),
            font=("Segoe UI", font_px, "bold"),
        )

    # ---------------- save / delete ----------------

    def _build_buttons(self, parent):
        pal = self.pal
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(8, 0))
        ctk.CTkButton(
            row,
            text="Save Preset",
            command=self._save,
            width=160,
            fg_color=pal.accent,
            hover_color=pal.accent_hover,
            text_color=pal.accent_text,
        ).pack(side="right", padx=4)
        if self.is_user_start:
            ctk.CTkButton(
                row,
                text="Delete Preset",
                command=self._delete,
                width=140,
                fg_color="#7a2a2a",
                hover_color="#9a3a3a",
                text_color="#ffffff",
            ).pack(side="right", padx=4)
        ctk.CTkButton(
            row,
            text="Close",
            command=self.dlg.destroy,
            width=110,
            fg_color=pal.panel_alt,
            hover_color=pal.border,
            text_color=pal.text,
        ).pack(side="right", padx=4)

    def _build_template(self, name: str) -> Template:
        tiers: dict[str, TierStyle] = {}
        for tier, st in self.state.items():
            font = int(st["font"])  # may raise ValueError -> caller handles
            beam = None if st["beam_color"] == _NONE else (st["beam_color"], bool(st["beam_temp"]))
            mm = (
                None
                if st["mm_size"] == _NONE
                else (int(st["mm_size"]), st["mm_color"], st["mm_shape"])
            )
            tiers[tier] = TierStyle(
                text_color=tuple(st["text"]),
                bg_color=tuple(st["bg"]),
                border_color=tuple(st["border"]),
                font_size=font,
                play_effect=beam,
                minimap=mm,
            )
        return Template(name=name, description="Custom economy tier preset", tiers=tiers)

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Name required", "Enter a preset name.")
            return
        # Refuse to overwrite a shipped (non-user) template.
        if not self.controller.templates.is_user(name) and name in self.controller.template_names():
            messagebox.showwarning(
                "Built-in template",
                f"'{name}' is a built-in template and can't be overwritten. "
                "Choose a different preset name.",
            )
            return
        if self.controller.templates.is_user(name):
            if not messagebox.askyesno("Overwrite preset", f"Overwrite your preset '{name}'?"):
                return
        try:
            template = self._build_template(name)
        except ValueError:
            messagebox.showerror("Invalid font size", "Font size must be a whole number (1–60).")
            return
        try:
            save_user_template(template)
        except TemplateError as exc:
            messagebox.showerror("Could not save preset", str(exc))
            return

        self.controller.reload_templates(select=name)
        if self.on_saved:
            self.on_saved(name)
        self.app._set_status(f"Saved economy tier preset '{name}'.")
        messagebox.showinfo("Preset saved", f"Saved preset '{name}'. It's now selectable.")

    def _delete(self):
        name = self.start_name
        if not messagebox.askyesno("Delete preset", f"Delete your preset '{name}'?"):
            return
        if delete_user_template(name):
            self.controller.reload_templates()
            if self.on_saved:
                self.on_saved(self.controller.template_name)
            self.app._set_status(f"Deleted economy tier preset '{name}'.")
            self.dlg.destroy()
        else:
            messagebox.showinfo("Nothing deleted", f"No user preset named '{name}'.")


def _hex(rgba) -> str:
    r, g, b = int(rgba[0]), int(rgba[1]), int(rgba[2])
    return f"#{r:02x}{g:02x}{b:02x}"
