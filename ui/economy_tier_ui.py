"""Economy Tier Visual Preset dialog.

Surfaces the feature with a mode dropdown (canonical A.11 order), optional
visual-transfer checkboxes (with the two locked safety options shown disabled),
a minimum-confidence selector, a staleness banner, and a full preview diff. It
talks only to :class:`economy_tier.controller.EconomyTierController`; all the
parsing, classifying, patching, validation, backup and history live there.

``Preview Only`` never writes. ``Apply…`` writes after the preview is shown.
``Restore Previous Visuals`` reverts the last economy-tier operation.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk

from economy_tier.controller import EconomyTierController, Mode, PreviewModel
from economy_tier.errors import EconomyTierError
from economy_tier.filter_visual_patcher import TransferOptions

# Modes offered inside the dialog (Off only makes sense for the main dropdown).
_DIALOG_MODES = [
    Mode.PREVIEW.value,
    Mode.APPLY.value,
    Mode.APPLY_CHANCE.value,
    Mode.RESTORE.value,
]

_CONF_LABELS = ["low", "medium", "high"]


def open_economy_tier_tools(app, start_mode: str | None = None) -> None:
    """Entry point from main.py. Opens the dialog (optionally on a given mode)."""
    if not getattr(app, "filter_path", "") or not getattr(app, "lines", None):
        messagebox.showinfo("No filter", "Load a filter file first.")
        return
    try:
        controller = EconomyTierController(app.filter_path, app.lines)
    except Exception as exc:  # defensive: never crash the host app
        messagebox.showerror("Economy Tier Visuals", f"Could not start feature:\n{exc}")
        return
    if not controller.available:
        messagebox.showwarning(
            "Economy Tier Visuals unavailable",
            f"{controller.disabled_reason}\n\n"
            "The rest of the app is unaffected. Fix the data/template file and reopen.",
        )
        return
    _EconomyTierDialog(app, controller, start_mode=start_mode)


class _EconomyTierDialog:
    def __init__(self, app, controller: EconomyTierController, start_mode=None):
        self.app = app
        self.controller = controller
        self.settings = getattr(app, "settings", None)
        self.pal = app.theme_manager.current()
        # Honour a persisted default template if it exists in this file.
        if self.settings is not None:
            pref = getattr(self.settings, "economy_tier_default_template", "")
            if pref and pref in controller.template_names():
                controller.template_name = pref

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
            text=(
                "Restyles every block by economy value tier (SS→F). The same tier "
                "looks identical across item categories. Sound directives are never "
                "touched; a backup is always made before saving."
            ),
            text_color=self.pal.text_muted,
            wraplength=900,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))

        # Staleness banner (non-blocking).
        stale = controller.staleness_message()
        if stale:
            ctk.CTkLabel(
                wrapper,
                text="⚠ " + stale,
                text_color="#e0b020",
                wraplength=900,
                justify="left",
            ).pack(anchor="w", pady=(0, 6))

        self._build_controls(wrapper)
        self._build_preview_area(wrapper)
        self._build_buttons(wrapper)

        # Initial mode + first preview.
        if start_mode in _DIALOG_MODES:
            self.mode_var.set(start_mode)
        self._refresh_preview()

        app._setup_dialog(
            self.dlg, title="Economy Tier Visuals", default_size=(980, 800), min_size=(860, 640)
        )

    # ---------------- controls ----------------

    def _build_controls(self, parent):
        pal = self.pal
        row = ctk.CTkFrame(parent, fg_color=pal.panel_alt)
        row.pack(fill="x", pady=(2, 6))

        ctk.CTkLabel(row, text="Mode:").grid(row=0, column=0, padx=(8, 4), pady=8, sticky="w")
        self.mode_var = tk.StringVar(value=Mode.PREVIEW.value)
        ctk.CTkOptionMenu(
            row,
            values=_DIALOG_MODES,
            variable=self.mode_var,
            command=lambda _v: self._refresh_preview(),
            width=320,
        ).grid(row=0, column=1, padx=4, pady=8, sticky="w")

        ctk.CTkLabel(row, text="Template:").grid(row=0, column=2, padx=(16, 4), pady=8, sticky="w")
        self.template_var = tk.StringVar(value=self.controller.template_name or "")
        ctk.CTkOptionMenu(
            row,
            values=self.controller.template_names() or [""],
            variable=self.template_var,
            command=self._on_template,
            width=240,
        ).grid(row=0, column=3, padx=4, pady=8, sticky="w")

        ctk.CTkLabel(row, text="Min confidence:").grid(
            row=0, column=4, padx=(16, 4), pady=8, sticky="w"
        )
        self.conf_var = tk.StringVar(value=self._pref("economy_tier_min_confidence", "medium"))
        ctk.CTkOptionMenu(
            row,
            values=_CONF_LABELS,
            variable=self.conf_var,
            command=lambda _v: self._refresh_preview(),
            width=120,
        ).grid(row=0, column=5, padx=4, pady=8, sticky="w")

        # Transfer checkboxes.
        toggles = ctk.CTkFrame(parent, fg_color=pal.panel_alt)
        toggles.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(toggles, text="Transfer:", font=("Segoe UI Semibold", 11)).pack(
            side="left", padx=(8, 8), pady=6
        )

        self.t_text = tk.BooleanVar(value=self._pref("economy_tier_apply_text", True))
        self.t_bg = tk.BooleanVar(value=self._pref("economy_tier_apply_bg", True))
        self.t_border = tk.BooleanVar(value=self._pref("economy_tier_apply_border", True))
        self.t_font = tk.BooleanVar(value=self._pref("economy_tier_apply_font", True))
        self.t_effect = tk.BooleanVar(value=self._pref("economy_tier_apply_effect", True))
        self.t_minimap = tk.BooleanVar(value=self._pref("economy_tier_apply_minimap", True))
        for text, var in (
            ("Text colour", self.t_text),
            ("Background", self.t_bg),
            ("Border", self.t_border),
            ("Font size", self.t_font),
            ("PlayEffect", self.t_effect),
            ("MinimapIcon", self.t_minimap),
        ):
            ctk.CTkCheckBox(
                toggles,
                text=text,
                variable=var,
                command=self._refresh_preview,
                width=20,
            ).pack(side="left", padx=6, pady=6)

        # Locked safety options (shown checked + disabled).
        locked = ctk.CTkFrame(parent, fg_color="transparent")
        locked.pack(fill="x", pady=(0, 4))
        for text in ("🔒 Preserve existing sounds", "🔒 Create backup before save"):
            cb = ctk.CTkCheckBox(locked, text=text)
            cb.select()
            cb.configure(state="disabled")
            cb.pack(side="left", padx=(8, 12), pady=2)

    def _pref(self, attr: str, default):
        if self.settings is None:
            return default
        return getattr(self.settings, attr, default)

    def _persist_prefs(self):
        """Save the user's transfer/confidence/template choices for next time."""
        if self.settings is None:
            return
        s = self.settings
        s.economy_tier_min_confidence = self.conf_var.get()
        s.economy_tier_default_template = self.template_var.get()
        s.economy_tier_apply_text = self.t_text.get()
        s.economy_tier_apply_bg = self.t_bg.get()
        s.economy_tier_apply_border = self.t_border.get()
        s.economy_tier_apply_font = self.t_font.get()
        s.economy_tier_apply_effect = self.t_effect.get()
        s.economy_tier_apply_minimap = self.t_minimap.get()
        persist = getattr(self.app, "_persist_settings", None)
        if callable(persist):
            try:
                persist()
            except Exception:
                pass

    def _transfer(self) -> TransferOptions:
        return TransferOptions(
            apply_text=self.t_text.get(),
            apply_bg=self.t_bg.get(),
            apply_border=self.t_border.get(),
            apply_font=self.t_font.get(),
            apply_effect=self.t_effect.get(),
            apply_minimap=self.t_minimap.get(),
        )

    def _on_template(self, value):
        self.controller.template_name = value
        self._refresh_preview()

    # ---------------- preview area ----------------

    def _build_preview_area(self, parent):
        pal = self.pal
        self.summary_label = ctk.CTkLabel(parent, text="", justify="left", font=("Segoe UI", 11))
        self.summary_label.pack(anchor="w", pady=(4, 2))

        self.warn_label = ctk.CTkLabel(
            parent, text="", justify="left", text_color="#e0a0a0", wraplength=900
        )
        self.warn_label.pack(anchor="w", pady=(0, 2))

        tf = ctk.CTkFrame(parent, fg_color=pal.panel_alt)
        tf.pack(fill="both", expand=True, pady=4)
        cols = ("line", "tier", "conf", "reason", "old", "new", "sound")
        self.tree = ttk.Treeview(tf, columns=cols, show="headings", height=14, selectmode="browse")
        headers = {
            "line": ("Lines", 80),
            "tier": ("Tier", 110),
            "conf": ("Conf", 70),
            "reason": ("Reason", 230),
            "old": ("Old visuals", 120),
            "new": ("New visuals", 120),
            "sound": ("Sounds kept", 90),
        }
        for c, (txt, w) in headers.items():
            self.tree.heading(c, text=txt)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 4), pady=4)

    def _refresh_preview(self):
        try:
            mode = Mode(self.mode_var.get())
        except ValueError:
            mode = Mode.PREVIEW

        if mode == Mode.RESTORE:
            self._render_restore_preview()
            return

        try:
            pv: PreviewModel = self.controller.build_preview(
                mode, self._transfer(), self.conf_var.get()
            )
        except EconomyTierError as exc:
            self.summary_label.configure(text=f"Cannot preview: {exc}")
            return

        self.summary_label.configure(
            text=(
                f"Blocks scanned {pv.total_blocks}  •  to change {pv.changed}  •  "
                f"already-styled/unchanged {pv.unchanged}  •  skipped hidden {pv.skipped_hidden}  •  "
                f"skipped sound-only {pv.skipped_sound_only}  •  unknown {pv.unknown}\n"
                f"Tiers: {self._fmt_tiers(pv.tier_counts)}  •  "
                f"chance promotions {pv.chance_promotions}  •  "
                f"low-confidence shown (not written) {pv.low_confidence_shown}\n"
                f"Run fingerprint {pv.fingerprint}"
            )
        )
        warn = list(pv.warnings)
        if pv.validation is None:
            warn.append("structural validation did not pass — Apply is blocked")
        self.warn_label.configure(text=("⚠ " + " | ".join(warn)) if warn else "")

        for i in self.tree.get_children():
            self.tree.delete(i)
        for p in pv.patches:
            self.tree.insert(
                "",
                "end",
                values=(
                    f"{p.start_line}-{p.end_line}",
                    p.tier,
                    "",
                    _truncate(p.reason, 60),
                    f"{len(p.old_visuals)} line(s)",
                    f"{len(p.new_visuals)} line(s)",
                    f"{len(p.sounds_preserved)}",
                ),
            )
        self._last_preview = pv

    def _render_restore_preview(self):
        if self.controller.has_restorable():
            self.summary_label.configure(
                text=(
                    "Restore Previous Visuals will revert the last economy-tier "
                    "operation on this file. A backup of the current state is made first."
                )
            )
            self.warn_label.configure(text="")
        else:
            self.summary_label.configure(
                text="No previous economy-tier operation to restore for this file."
            )
            self.warn_label.configure(text="")
        for i in self.tree.get_children():
            self.tree.delete(i)

    @staticmethod
    def _fmt_tiers(counts: dict) -> str:
        if not counts:
            return "(none)"
        order = ["SS_CHANCE_BASE", "SS", "S", "A", "B", "C", "D", "F"]
        return ", ".join(f"{t}:{counts[t]}" for t in order if t in counts)

    # ---------------- buttons ----------------

    def _build_buttons(self, parent):
        pal = self.pal
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(8, 0))
        ctk.CTkButton(
            row,
            text="Run Selected Mode",
            command=self._run,
            width=200,
            fg_color=pal.accent,
            hover_color=pal.accent_hover,
            text_color=pal.accent_text,
        ).pack(side="right", padx=4)
        ctk.CTkButton(
            row,
            text="Refresh Preview",
            command=self._refresh_preview,
            width=150,
            fg_color=pal.panel_alt,
            hover_color=pal.border,
            text_color=pal.text,
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

    def _run(self):
        try:
            mode = Mode(self.mode_var.get())
        except ValueError:
            return

        self._persist_prefs()

        if mode == Mode.PREVIEW:
            self._refresh_preview()
            self.app._set_status("Economy tier preview refreshed (nothing written).")
            return

        if mode == Mode.RESTORE:
            if not messagebox.askyesno(
                "Restore Previous Visuals",
                "Revert the last economy-tier operation on this file? "
                "A backup of the current state is made first.",
            ):
                return
            res = self.controller.restore()
        else:
            if not messagebox.askyesno(
                "Apply Economy Tier Visuals",
                f"{mode.value}\n\nApply to {os.path.basename(self.app.filter_path)}? "
                "A verified backup is created first and sound directives are preserved.",
            ):
                return
            res = self.controller.apply(mode, self._transfer(), self.conf_var.get())

        if not res.ok:
            messagebox.showerror("Economy Tier Visuals", res.message)
            self.app._set_status(res.message)
            return

        # Adopt the new content into the host app.
        if res.new_lines:
            self.app.lines = res.new_lines
            self.app.refresh_filter_data()
        msg = res.message
        if res.backup_path:
            msg += f"  (backup: {os.path.basename(res.backup_path)})"
        self.app._set_status(msg)
        messagebox.showinfo("Economy Tier Visuals", msg)
        self._refresh_preview()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
