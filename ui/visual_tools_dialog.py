"""Visual Tools dialog — Emphasize by Tier + Visual Randomizer.

Both modes share the same flow:
  1. Build a `plan` (list of StyleChange) from the currently loaded filter.
  2. Show the user a summary: how many blocks per tier will be restyled,
     a per-tier swatch preview, and a confirm/cancel pair.
  3. On Apply: rewrite the in-memory lines and save through the app's
     standard save_filter_file path (so a normal pre-save backup is made).
"""

from __future__ import annotations

import os
import random
import subprocess
import sys
from typing import List, Optional

import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox

from features.visual_emphasis import (
    EmphasisStyler, RandomizerStyler, StyleChange, ValueTier,
    EMPHASIS_PRESETS, CURATED_PALETTES, apply_changes, tier_summary,
    load_visual_presets, write_default_presets_file,
    default_visual_presets_path,
)


_TIER_LABELS = {
    ValueTier.MYTHIC: "Mythic",
    ValueTier.TOP: "Top",
    ValueTier.HIGH: "High",
    ValueTier.MID: "Mid",
    ValueTier.LOW: "Low",
    ValueTier.JUNK: "Junk",
    ValueTier.HIDDEN: "Hidden (skipped)",
}


def open_visual_tools(app, start_tab: str = "emphasize") -> None:
    """Entry point from main.py. Opens the dialog on the requested tab."""
    if not app.filter_path or not app.lines:
        messagebox.showinfo("No filter", "Load a filter file first.")
        return
    _VisualToolsDialog(app, start_tab=start_tab)


class _VisualToolsDialog:
    def __init__(self, app, start_tab: str = "emphasize"):
        self.app = app
        self.pal = app.theme_manager.current()

        # Where the user-editable JSON lives. Created on first edit.
        app_dir = os.path.dirname(os.path.abspath(
            sys.modules[app.__class__.__module__].__file__))
        self.presets_path = default_visual_presets_path(app_dir)
        self.presets, self.palettes = load_visual_presets(self.presets_path)

        self.dlg = ctk.CTkToplevel(app.root)
        wrapper = ctk.CTkFrame(self.dlg, fg_color=self.pal.panel)
        wrapper.pack(fill="both", expand=True, padx=12, pady=12)

        ctk.CTkLabel(
            wrapper,
            text=f"Filter: {os.path.basename(app.filter_path)}",
            font=("Segoe UI Semibold", 13),
        ).pack(anchor="w")
        ctk.CTkLabel(
            wrapper,
            text=("Both modes touch only visual styling (colors, font, "
                  "PlayEffect, MinimapIcon) inside Show blocks. Hide blocks "
                  "and item conditions are never modified."),
            text_color=self.pal.text_muted, wraplength=860, justify="left",
        ).pack(anchor="w", pady=(0, 8))

        # Shared edit/reload toolbar — affects both tabs.
        edit_bar = ctk.CTkFrame(wrapper, fg_color="transparent")
        edit_bar.pack(fill="x", pady=(0, 6))
        self._presets_label = ctk.CTkLabel(
            edit_bar,
            text=self._presets_label_text(),
            text_color=self.pal.text_muted,
        )
        self._presets_label.pack(side="left", padx=(0, 8))
        ctk.CTkButton(edit_bar, text="📝 Edit Presets File",
                      command=self._open_presets_file, width=180).pack(side="right", padx=4)
        ctk.CTkButton(edit_bar, text="🔄 Reload",
                      command=self._reload_presets, width=110).pack(side="right", padx=4)

        tabs = ctk.CTkTabview(wrapper)
        tabs.pack(fill="both", expand=True)
        self.tab_em = tabs.add("Emphasize by Tier")
        self.tab_rand = tabs.add("Randomize Visuals")

        self._build_emphasize_tab(self.tab_em)
        self._build_randomize_tab(self.tab_rand)

        if start_tab == "randomize":
            tabs.set("Randomize Visuals")
        else:
            tabs.set("Emphasize by Tier")

        app._setup_dialog(self.dlg, title="Visual Tools",
                          default_size=(940, 760), min_size=(820, 600))

    # ---------------- Preset file helpers ----------------

    def _presets_label_text(self) -> str:
        if os.path.isfile(self.presets_path):
            return f"Presets: {self.presets_path}"
        return "Presets: (using built-in defaults — click Edit to create a file)"

    def _open_presets_file(self):
        # Write defaults first if the file doesn't exist, so the user has
        # something to edit instead of staring at a blank file.
        if not os.path.isfile(self.presets_path):
            try:
                write_default_presets_file(self.presets_path)
            except Exception as e:
                messagebox.showerror(
                    "Could not create presets file",
                    f"Tried to write defaults to:\n  {self.presets_path}\n\n{e}",
                )
                return
            self._presets_label.configure(text=self._presets_label_text())
        try:
            if sys.platform == "win32":
                os.startfile(self.presets_path)  # noqa: SIM115
            elif sys.platform == "darwin":
                subprocess.Popen(["open", self.presets_path])
            else:
                subprocess.Popen(["xdg-open", self.presets_path])
        except Exception as e:
            messagebox.showerror("Open failed", str(e))

    def _reload_presets(self):
        self.presets, self.palettes = load_visual_presets(self.presets_path)
        # Re-plan both tabs with the fresh presets/palettes.
        self._em_plan = EmphasisStyler(presets=self.presets).plan(self.app.lines)
        self._repopulate_emphasis_table()
        self._replan_random()
        self.app._set_status("Visual presets reloaded.")

    # ---------------- Emphasize tab ----------------

    def _build_emphasize_tab(self, parent):
        pal = self.pal
        # Plan it once on open so the summary is live.
        self._em_plan = EmphasisStyler(presets=self.presets).plan(self.app.lines)

        ctk.CTkLabel(parent,
                     text="High-tier items (Uniques, Special Currency, etc.) get the loudest "
                          "treatment. Low-tier items dim down. Hide blocks are left alone.",
                     text_color=pal.text_muted, wraplength=860, justify="left",
                     ).pack(anchor="w", pady=(8, 6))

        # Per-tier preview row. The swatch row gets rebuilt on reload so
        # color edits in the JSON show up immediately.
        preview_frame = ctk.CTkFrame(parent, fg_color=pal.panel_alt)
        preview_frame.pack(fill="x", pady=8)
        ctk.CTkLabel(preview_frame, text="Tier presets",
                     font=("Segoe UI Semibold", 11)).pack(anchor="w", padx=8, pady=(6, 2))

        self._em_swatch_row = ctk.CTkFrame(preview_frame, fg_color="transparent")
        self._em_swatch_row.pack(fill="x", padx=4, pady=(0, 6))
        self._populate_emphasis_swatches()

        self._em_total_label = ctk.CTkLabel(
            parent, text="",
            font=("Segoe UI Semibold", 11),
        )
        self._em_total_label.pack(anchor="w", pady=(6, 4))
        self._update_em_total_label()

        # Per-block table.
        tf = ctk.CTkFrame(parent, fg_color=pal.panel_alt)
        tf.pack(fill="both", expand=True, pady=4)
        cols = ("line", "tier", "header")
        self._em_tree = ttk.Treeview(tf, columns=cols, show="headings",
                                      height=12, selectmode="browse")
        self._em_tree.heading("line", text="Line")
        self._em_tree.heading("tier", text="Tier")
        self._em_tree.heading("header", text="Block header")
        self._em_tree.column("line", width=70, anchor="e")
        self._em_tree.column("tier", width=90, anchor="w")
        self._em_tree.column("header", width=720, anchor="w")
        self._em_tree.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        sb = ttk.Scrollbar(tf, orient="vertical", command=self._em_tree.yview)
        self._em_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 4), pady=4)

        self._repopulate_emphasis_table()

        # Buttons
        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.pack(fill="x", pady=(8, 0))
        ctk.CTkButton(btn_row, text="Apply Emphasis",
                      command=self._apply_emphasis, width=200,
                      fg_color=pal.accent, hover_color=pal.accent_hover,
                      text_color=pal.accent_text).pack(side="right", padx=4)
        ctk.CTkButton(btn_row, text="Close", command=self.dlg.destroy, width=120,
                      fg_color=pal.panel_alt, hover_color=pal.border,
                      text_color=pal.text).pack(side="right", padx=4)

    def _apply_emphasis(self):
        if not self._em_plan:
            messagebox.showinfo("Nothing to do",
                                "No restyle-able blocks were found in this filter.")
            return
        n = self._commit_plan(self._em_plan, "Emphasis by tier")
        if n is not None:
            self.dlg.destroy()

    def _populate_emphasis_swatches(self):
        # Clear and redraw.
        for child in self._em_swatch_row.winfo_children():
            child.destroy()
        counts = tier_summary(self._em_plan)
        pal = self.pal
        for tier in (ValueTier.MYTHIC, ValueTier.TOP, ValueTier.HIGH,
                     ValueTier.MID, ValueTier.LOW, ValueTier.JUNK):
            cell = ctk.CTkFrame(self._em_swatch_row, fg_color=pal.panel,
                                corner_radius=8, width=140, height=72)
            cell.pack(side="left", padx=4, pady=4)
            cell.pack_propagate(False)
            style = self.presets.get(tier)
            swatch_color = _rgba_to_hex(style.text_color) if style and style.text_color else "#cccccc"
            bg = _rgba_to_hex(style.bg_color) if style and style.bg_color else pal.panel_alt
            inner = tk.Frame(cell, bg=bg, bd=0)
            inner.pack(fill="both", expand=True, padx=2, pady=2)
            tk.Label(inner, text=_TIER_LABELS[tier],
                     bg=bg, fg=swatch_color,
                     font=("Segoe UI Semibold", 11)).pack(pady=(8, 0))
            tk.Label(inner, text=f"{counts.get(tier, 0)} block(s)",
                     bg=bg, fg=swatch_color,
                     font=("Segoe UI", 9)).pack()

    def _update_em_total_label(self):
        total = sum(tier_summary(self._em_plan).values())
        self._em_total_label.configure(
            text=f"Total blocks to restyle: {total}   (Hide blocks skipped)")

    def _repopulate_emphasis_table(self):
        for i in self._em_tree.get_children():
            self._em_tree.delete(i)
        for c in self._em_plan:
            header = self.app.lines[c.start_idx].rstrip("\n")
            self._em_tree.insert("", "end", values=(
                c.start_idx + 1, _TIER_LABELS[c.tier], _truncate(header, 110),
            ))
        self._populate_emphasis_swatches()
        self._update_em_total_label()

    # ---------------- Randomize tab ----------------

    def _build_randomize_tab(self, parent):
        pal = self.pal

        ctk.CTkLabel(parent,
                     text=("Picks a curated, high-contrast color scheme for every Show block — "
                           "text, border, background, PlayEffect, MinimapIcon. Use a seed to "
                           "reproduce the same look later."),
                     text_color=pal.text_muted, wraplength=860, justify="left",
                     ).pack(anchor="w", pady=(8, 6))

        # Seed input
        seed_row = ctk.CTkFrame(parent, fg_color="transparent")
        seed_row.pack(fill="x", pady=4)
        ctk.CTkLabel(seed_row, text="Random seed:").pack(side="left", padx=(0, 6))
        self._seed_var = tk.StringVar(value=str(random.randint(1, 99_999_999)))
        ctk.CTkEntry(seed_row, textvariable=self._seed_var, width=140).pack(side="left")
        ctk.CTkButton(seed_row, text="🎲 New seed",
                      command=self._new_seed, width=120).pack(side="left", padx=(6, 0))
        ctk.CTkButton(seed_row, text="🔄 Re-plan",
                      command=self._replan_random, width=120).pack(side="left", padx=(6, 0))

        # Palette preview — rebuilt on reload.
        pal_frame = ctk.CTkFrame(parent, fg_color=pal.panel_alt)
        pal_frame.pack(fill="x", pady=8)
        self._rand_pal_header = ctk.CTkLabel(
            pal_frame, text="", font=("Segoe UI Semibold", 11))
        self._rand_pal_header.pack(anchor="w", padx=8, pady=(6, 2))
        self._rand_swatch_row = ctk.CTkFrame(pal_frame, fg_color="transparent")
        self._rand_swatch_row.pack(fill="x", padx=4, pady=(0, 6))
        self._populate_palette_swatches()

        # Per-block table (built once, refreshed by replan).
        tf = ctk.CTkFrame(parent, fg_color=pal.panel_alt)
        tf.pack(fill="both", expand=True, pady=4)
        cols = ("line", "tier", "header")
        self._rand_tree = ttk.Treeview(tf, columns=cols, show="headings",
                                        height=12, selectmode="browse")
        self._rand_tree.heading("line", text="Line")
        self._rand_tree.heading("tier", text="Tier")
        self._rand_tree.heading("header", text="Block header")
        self._rand_tree.column("line", width=70, anchor="e")
        self._rand_tree.column("tier", width=90, anchor="w")
        self._rand_tree.column("header", width=720, anchor="w")
        self._rand_tree.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        sb = ttk.Scrollbar(tf, orient="vertical", command=self._rand_tree.yview)
        self._rand_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 4), pady=4)

        self._rand_plan: List[StyleChange] = []
        self._replan_random()

        # Buttons
        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.pack(fill="x", pady=(8, 0))
        ctk.CTkButton(btn_row, text="Apply Randomization",
                      command=self._apply_random, width=220,
                      fg_color=pal.accent, hover_color=pal.accent_hover,
                      text_color=pal.accent_text).pack(side="right", padx=4)
        ctk.CTkButton(btn_row, text="Close", command=self.dlg.destroy, width=120,
                      fg_color=pal.panel_alt, hover_color=pal.border,
                      text_color=pal.text).pack(side="right", padx=4)

    def _new_seed(self):
        self._seed_var.set(str(random.randint(1, 99_999_999)))
        self._replan_random()

    def _replan_random(self):
        try:
            seed = int(self._seed_var.get())
        except (TypeError, ValueError):
            seed = None
        self._rand_plan = RandomizerStyler(
            seed=seed, palettes=self.palettes,
        ).plan(self.app.lines)
        for i in self._rand_tree.get_children():
            self._rand_tree.delete(i)
        for c in self._rand_plan:
            header = self.app.lines[c.start_idx].rstrip("\n")
            self._rand_tree.insert("", "end", values=(
                c.start_idx + 1, _TIER_LABELS[c.tier], _truncate(header, 110),
            ))
        self._populate_palette_swatches()

    def _populate_palette_swatches(self):
        self._rand_pal_header.configure(
            text=f"Curated palettes available: {len(self.palettes)}")
        for child in self._rand_swatch_row.winfo_children():
            child.destroy()
        for p in self.palettes:
            cell = ctk.CTkFrame(self._rand_swatch_row, fg_color=self.pal.panel,
                                corner_radius=6, width=84, height=44)
            cell.pack(side="left", padx=3, pady=3)
            cell.pack_propagate(False)
            inner = tk.Frame(cell, bg=_rgba_to_hex(p.bg), bd=0)
            inner.pack(fill="both", expand=True, padx=2, pady=2)
            tk.Label(inner, text="ITEM",
                     bg=_rgba_to_hex(p.bg), fg=_rgba_to_hex(p.text),
                     font=("Segoe UI Semibold", 10)).pack(expand=True)

    def _apply_random(self):
        if not self._rand_plan:
            messagebox.showinfo("Nothing to do",
                                "No restyle-able blocks were found in this filter.")
            return
        n = self._commit_plan(self._rand_plan, f"Randomizer (seed {self._seed_var.get()})")
        if n is not None:
            self.dlg.destroy()

    # ---------------- Shared commit path ----------------

    def _commit_plan(self, plan: List[StyleChange], what: str) -> Optional[int]:
        if not messagebox.askyesno(
            "Confirm restyle",
            f"{what} will rewrite {len(plan)} block(s) in:\n  "
            f"{os.path.basename(self.app.filter_path)}\n\n"
            "A backup is saved automatically. Proceed?",
        ):
            return None

        from core.file_operations import save_filter_file
        new_lines = apply_changes(self.app.lines, plan)
        try:
            save_filter_file(
                self.app.filter_path, new_lines,
                create_backup=self.app.settings.create_backups,
                max_backups=self.app.settings.max_backups,
            )
        except Exception as e:
            messagebox.showerror("Save error", str(e))
            return None

        self.app.lines = new_lines
        self.app.refresh_filter_data()
        self.app._set_status(f"{what}: rewrote {len(plan)} block(s), saved with backup.")
        return len(plan)


def _rgba_to_hex(rgba) -> str:
    r, g, b = rgba[0], rgba[1], rgba[2]
    return f"#{r:02x}{g:02x}{b:02x}"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
