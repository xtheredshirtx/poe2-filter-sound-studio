"""Per-tier sound assigner.

Pick a value tier (SS_CHANCE_BASE … F), see how many blocks the filter has in
that tier, and set ONE sound file for all of them at once (or clear it). This is
a user-initiated sound change — the only place the economy-tier feature touches
sound — so it always makes a backup and only edits sound lines.

It reuses the economy-tier classifier (via ``EconomyTierController.tier_block_starts``)
to know which blocks are in each tier, and the host app's
``apply_custom_sound_to_blocks`` / ``remove_sound_from_blocks`` to do the edit.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from economy_tier.controller import EconomyTierController, Mode
from economy_tier.economy_tier_data import TIER_ORDER

_AUDIO_TYPES = [
    (
        "Audio/Video Files",
        "*.wav *.ogg *.mp3 *.aac *.flac *.m4a *.wmv *.mp4 *.mkv *.webm *.opus",
    ),
    ("All files", "*.*"),
]

_MODES = [Mode.APPLY.value, Mode.APPLY_CHANCE.value]
_CONF = ["low", "medium", "high"]

_TIER_HINT = {
    "SS_CHANCE_BASE": "chance bases (Apply+Chance mode)",
    "SS": "chase / ultra-valuable",
    "S": "very valuable",
    "A": "good endgame",
    "B": "moderate",
    "C": "low but useful",
    "D": "very low",
    "F": "trash / quiet",
}


def open_tier_sound_dialog(app) -> None:
    """Entry point from the Sounds menu."""
    if not getattr(app, "filter_path", "") or not getattr(app, "lines", None):
        messagebox.showinfo("No filter", "Load a filter file first.")
        return
    try:
        controller = EconomyTierController(app.filter_path, app.lines)
    except Exception as exc:  # pragma: no cover - defensive
        messagebox.showerror("Tier Sounds", f"Could not start feature:\n{exc}")
        return
    if not controller.available:
        messagebox.showwarning(
            "Tier Sounds unavailable",
            f"{controller.disabled_reason}\n\nThe rest of the app is unaffected.",
        )
        return
    _TierSoundDialog(app, controller)


class _TierSoundDialog:
    def __init__(self, app, controller: EconomyTierController):
        self.app = app
        self.controller = controller
        self.pal = app.theme_manager.current()

        self.dlg = ctk.CTkToplevel(app.root)
        wrapper = ctk.CTkFrame(self.dlg, fg_color=self.pal.panel)
        wrapper.pack(fill="both", expand=True, padx=12, pady=12)

        ctk.CTkLabel(wrapper, text="Set Tier Sounds", font=("Segoe UI Semibold", 14)).pack(
            anchor="w"
        )
        ctk.CTkLabel(
            wrapper,
            text=(
                "Pick a tier and choose one sound for every item in it. A backup is "
                "always made first, and only the drop-sound is changed — colours and "
                "conditions are left alone."
            ),
            text_color=self.pal.text_muted,
            wraplength=820,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        # Mode + confidence selectors (which blocks count as each tier).
        row = ctk.CTkFrame(wrapper, fg_color=self.pal.panel_alt)
        row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(row, text="Mode:").pack(side="left", padx=(8, 4), pady=8)
        self.mode_var = tk.StringVar(value=Mode.APPLY.value)
        ctk.CTkOptionMenu(
            row,
            values=_MODES,
            variable=self.mode_var,
            command=lambda _v: self._refresh(),
            width=320,
        ).pack(side="left", padx=4, pady=8)
        ctk.CTkLabel(row, text="Min confidence:").pack(side="left", padx=(16, 4), pady=8)
        self.conf_var = tk.StringVar(value="medium")
        ctk.CTkOptionMenu(
            row,
            values=_CONF,
            variable=self.conf_var,
            command=lambda _v: self._refresh(),
            width=110,
        ).pack(side="left", padx=4, pady=8)

        # Per-tier rows.
        body = ctk.CTkFrame(wrapper, fg_color=self.pal.panel_alt)
        body.pack(fill="both", expand=True, pady=4)
        self._count_labels: dict[str, ctk.CTkLabel] = {}
        for tier in TIER_ORDER:
            cell = ctk.CTkFrame(body, fg_color="transparent")
            cell.pack(fill="x", padx=6, pady=3)
            ctk.CTkLabel(
                cell,
                text=tier,
                width=130,
                anchor="w",
                font=("Segoe UI Semibold", 12),
            ).pack(side="left")
            ctk.CTkLabel(
                cell,
                text=_TIER_HINT.get(tier, ""),
                width=210,
                anchor="w",
                text_color=self.pal.text_muted,
            ).pack(side="left")
            count_lbl = ctk.CTkLabel(cell, text="… blocks", width=110, anchor="w")
            count_lbl.pack(side="left")
            self._count_labels[tier] = count_lbl
            ctk.CTkButton(
                cell,
                text="🔊 Set Sound…",
                width=130,
                command=lambda t=tier: self._set_sound(t),
            ).pack(side="left", padx=4)
            ctk.CTkButton(
                cell,
                text="Remove",
                width=90,
                fg_color=self.pal.panel_alt,
                hover_color=self.pal.border,
                text_color=self.pal.text,
                command=lambda t=tier: self._remove_sound(t),
            ).pack(side="left", padx=4)

        btns = ctk.CTkFrame(wrapper, fg_color="transparent")
        btns.pack(fill="x", pady=(8, 0))
        ctk.CTkButton(
            btns,
            text="Refresh",
            command=self._refresh,
            width=120,
            fg_color=self.pal.panel_alt,
            hover_color=self.pal.border,
            text_color=self.pal.text,
        ).pack(side="right", padx=4)
        ctk.CTkButton(
            btns,
            text="Close",
            command=self.dlg.destroy,
            width=110,
            fg_color=self.pal.panel_alt,
            hover_color=self.pal.border,
            text_color=self.pal.text,
        ).pack(side="right", padx=4)

        self._mapping: dict[str, list[int]] = {}
        self._refresh()
        app._setup_dialog(
            self.dlg, title="Set Tier Sounds", default_size=(820, 560), min_size=(720, 460)
        )

    # ---------------- helpers ----------------

    def _mode(self) -> Mode:
        try:
            return Mode(self.mode_var.get())
        except ValueError:
            return Mode.APPLY

    def _refresh(self):
        """Recompute the tier -> blocks map from the CURRENT file and update counts."""
        text = "".join(self.app.lines)
        try:
            self._mapping = self.controller.tier_block_starts(
                text, self._mode(), self.conf_var.get()
            )
        except Exception as exc:  # pragma: no cover - defensive
            messagebox.showerror("Tier Sounds", str(exc))
            return
        for tier, lbl in self._count_labels.items():
            n = len(self._mapping.get(tier, []))
            lbl.configure(text=f"{n} block(s)")

    def _set_sound(self, tier: str):
        starts = self._mapping.get(tier, [])
        if not starts:
            messagebox.showinfo("No blocks", f"No blocks are classified as tier {tier}.")
            return
        path = filedialog.askopenfilename(
            title=f"Choose a sound for tier {tier}", filetypes=_AUDIO_TYPES
        )
        if not path:
            return
        if not messagebox.askyesno(
            "Set tier sound",
            f"Set '{os.path.basename(path)}' as the sound for all {len(starts)} "
            f"tier-{tier} block(s)?\n\nA backup is made first.",
        ):
            return
        try:
            n = self.app.apply_custom_sound_to_blocks(starts, path)
        except Exception as exc:
            messagebox.showerror("Could not set sound", str(exc))
            return
        self.app._set_status(f"Tier {tier}: set sound on {n} block(s) (backup made).")
        self._refresh()

    def _remove_sound(self, tier: str):
        starts = self._mapping.get(tier, [])
        if not starts:
            messagebox.showinfo("No blocks", f"No blocks are classified as tier {tier}.")
            return
        if not messagebox.askyesno(
            "Remove tier sound",
            f"Remove the drop-sound from all {len(starts)} tier-{tier} block(s)?",
        ):
            return
        try:
            n = self.app.remove_sound_from_blocks(starts)
        except Exception as exc:
            messagebox.showerror("Could not remove sound", str(exc))
            return
        self.app._set_status(f"Tier {tier}: removed sound from {n} block(s) (backup made).")
        self._refresh()
