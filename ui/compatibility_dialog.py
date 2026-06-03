"""UI for the Filter Compatibility Check.

Surfaces the results of `core.compatibility.FilterCompatibilityChecker` after
a filter is loaded: lists each issue, lets the user pick which auto-fixes to
apply, and (on Apply) rewrites the in-memory lines.

Designed to plug into the existing `FilterSoundEditor` app — call
`show_compatibility_dialog(app, lines, report)` and it handles theming,
dialog sizing, and write-back via the app's standard save path.
"""

from __future__ import annotations

import os
import sys
import subprocess
from typing import List, Optional, Tuple

import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox

from core.compatibility import (
    CompatibilityReport, CompatibilityIssue, FilterCompatibilityChecker,
    KIND_UNKNOWN, KIND_RENAME, KIND_DEPRECATED, KIND_BAD_RGB,
    KIND_BAD_VOLUME, KIND_ORPHAN_ACTION, KIND_REPLACE, KIND_REMOVE,
)


_KIND_LABELS = {
    KIND_UNKNOWN: "Unknown",
    KIND_RENAME: "Rename",
    KIND_DEPRECATED: "Deprecated",
    KIND_BAD_RGB: "Bad RGB",
    KIND_BAD_VOLUME: "Bad volume",
    KIND_ORPHAN_ACTION: "Orphan",
    KIND_REPLACE: "Replace",
    KIND_REMOVE: "Remove line",
}


def show_compatibility_dialog(app, lines: List[str],
                               report: CompatibilityReport,
                               checker: FilterCompatibilityChecker
                               ) -> Tuple[List[str], int]:
    """Open the modal dialog, return (possibly-updated lines, count applied).

    If the user cancels or the report is clean, returns (lines, 0).
    """
    if report.is_clean:
        # Nothing to surface — caller decides whether to even show "all good" UI.
        return lines, 0

    dlg = _CompatibilityDialog(app, lines, report, checker)
    app.root.wait_window(dlg.dlg)
    return dlg.result_lines, dlg.applied_count


class _CompatibilityDialog:
    def __init__(self, app, lines: List[str], report: CompatibilityReport,
                 checker: FilterCompatibilityChecker):
        self.app = app
        self.lines = lines
        self.report = report
        self.checker = checker

        # Final result the caller picks up after wait_window returns.
        self.result_lines: List[str] = lines
        self.applied_count: int = 0

        # Per-issue "should we apply this fix?" — keyed by index in report.issues
        self._apply_flags: dict[int, tk.BooleanVar] = {}

        pal = app.theme_manager.current()
        self.pal = pal

        self.dlg = ctk.CTkToplevel(app.root)
        main = ctk.CTkFrame(self.dlg, fg_color=pal.panel)
        main.pack(fill="both", expand=True, padx=12, pady=12)

        # ----- Header -----
        ctk.CTkLabel(
            main,
            text=f"Filter: {os.path.basename(app.filter_path) if app.filter_path else '(unsaved)'}",
            font=("Segoe UI Semibold", 13),
        ).pack(anchor="w")

        rules_label = report.rules_file or "(no rules file)"
        ctk.CTkLabel(
            main, text=f"Rules: {rules_label}",
            text_color=pal.text_muted,
        ).pack(anchor="w", pady=(0, 8))

        summary_bits = []
        kinds = report.by_kind()
        for k, n in kinds.items():
            summary_bits.append(f"{_KIND_LABELS.get(k, k)}: {n}")
        summary_text = (
            f"Found {len(report.issues)} issue(s) — "
            f"{report.auto_fixable_count} auto-fixable, "
            f"{report.manual_count} needs your attention.   "
            + "   ".join(summary_bits)
        )
        ctk.CTkLabel(main, text=summary_text,
                     font=("Segoe UI Semibold", 12)).pack(anchor="w", pady=(0, 8))

        # ----- Issue table -----
        tf = ctk.CTkFrame(main, fg_color=pal.panel_alt)
        tf.pack(fill="both", expand=True, pady=4)

        cols = ("apply", "line", "kind", "current", "suggested", "message")
        tree = ttk.Treeview(tf, columns=cols, show="headings",
                            height=14, selectmode="browse")
        tree.heading("apply", text="Fix?")
        tree.heading("line", text="Line")
        tree.heading("kind", text="Issue")
        tree.heading("current", text="Current")
        tree.heading("suggested", text="Suggested")
        tree.heading("message", text="Details")
        tree.column("apply", width=50, anchor="center")
        tree.column("line", width=60, anchor="e")
        tree.column("kind", width=110, anchor="w")
        tree.column("current", width=260, anchor="w")
        tree.column("suggested", width=260, anchor="w")
        tree.column("message", width=320, anchor="w")
        tree.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        sb = ttk.Scrollbar(tf, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 4), pady=4)
        self.tree = tree

        for i, issue in enumerate(report.issues):
            var = tk.BooleanVar(value=issue.auto_fixable)
            self._apply_flags[i] = var
            tree.insert("", "end", iid=str(i), values=(
                ("✓" if issue.auto_fixable else "—"),
                issue.line_no + 1,
                _KIND_LABELS.get(issue.kind, issue.kind),
                _truncate(issue.display_line, 80),
                _truncate(issue.display_new_line, 80) if issue.auto_fixable else "(manual)",
                issue.message,
            ))

        tree.bind("<Double-1>", self._on_double_click)
        tree.bind("<space>", self._on_space_toggle)

        # Hint
        ctk.CTkLabel(
            main,
            text="Double-click or press Space to toggle a fix. "
                 "Manual issues show '(manual)' — fix them yourself or add a migration rule.",
            text_color=pal.text_muted,
        ).pack(anchor="w", pady=(2, 6))

        # ----- Bulk toggles -----
        toggles = ctk.CTkFrame(main, fg_color="transparent")
        toggles.pack(fill="x", pady=(0, 4))
        ctk.CTkButton(toggles, text="Select all fixable",
                      command=self._select_all_fixable, width=160).pack(side="left", padx=4)
        ctk.CTkButton(toggles, text="Deselect all",
                      command=self._deselect_all, width=140).pack(side="left", padx=4)
        ctk.CTkButton(toggles, text="📝 Edit Rules File",
                      command=self._open_rules_file, width=160).pack(side="right", padx=4)

        # ----- Buttons -----
        btn_row = ctk.CTkFrame(main, fg_color="transparent")
        btn_row.pack(fill="x", pady=(10, 0))
        ctk.CTkButton(
            btn_row, text="Skip", command=self._on_cancel, width=120,
            fg_color=pal.panel_alt, hover_color=pal.border, text_color=pal.text,
        ).pack(side="right", padx=4)
        self.apply_btn = ctk.CTkButton(
            btn_row, text="Apply Fixes", command=self._on_apply, width=180,
            fg_color=pal.accent, hover_color=pal.accent_hover, text_color=pal.accent_text,
        )
        self.apply_btn.pack(side="right", padx=4)

        app._setup_dialog(self.dlg, title="Filter Compatibility Check",
                          default_size=(1100, 720), min_size=(900, 560))

    # ---------- handlers ----------

    def _on_double_click(self, _evt):
        sel = self.tree.focus()
        if not sel:
            return
        self._toggle_row(int(sel))

    def _on_space_toggle(self, _evt):
        sel = self.tree.focus()
        if sel:
            self._toggle_row(int(sel))
        return "break"

    def _toggle_row(self, idx: int):
        issue = self.report.issues[idx]
        if not issue.auto_fixable:
            messagebox.showinfo(
                "Manual fix only",
                f"This issue isn't auto-fixable:\n\n  {issue.display_line}\n\n"
                f"{issue.message}",
            )
            return
        var = self._apply_flags[idx]
        var.set(not var.get())
        self.tree.set(str(idx), "apply", "✓" if var.get() else "○")

    def _select_all_fixable(self):
        for i, issue in enumerate(self.report.issues):
            if issue.auto_fixable:
                self._apply_flags[i].set(True)
                self.tree.set(str(i), "apply", "✓")

    def _deselect_all(self):
        for i, issue in enumerate(self.report.issues):
            if issue.auto_fixable:
                self._apply_flags[i].set(False)
                self.tree.set(str(i), "apply", "○")

    def _open_rules_file(self):
        path = self.report.rules_file
        if not path or not os.path.isfile(path):
            messagebox.showinfo(
                "No rules file",
                "There's no migration_rules.json yet. Create one at:\n  "
                f"{path or '(unknown path)'}\n\n"
                "See the _rule_schema in the seed file for the format.",
            )
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa: SIM115
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("Open failed", str(e))

    def _on_cancel(self):
        self.result_lines = self.lines
        self.applied_count = 0
        self.dlg.destroy()

    def _on_apply(self):
        selected = [
            self.report.issues[i] for i, v in self._apply_flags.items()
            if v.get() and self.report.issues[i].auto_fixable
        ]
        if not selected:
            self._on_cancel()
            return
        new_lines, applied = self.checker.apply_fixes(self.lines, selected)
        self.result_lines = new_lines
        self.applied_count = applied
        self.dlg.destroy()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
