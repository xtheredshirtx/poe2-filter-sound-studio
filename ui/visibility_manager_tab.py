"""Item Visibility tab — beginner-friendly Show/Hide management.

This tab lists every Show/Hide block in the currently loaded filter and lets the
user flip each one between "Shown in game" and "Hidden in game" without editing
filter text by hand. Toggles are staged in memory; nothing is written until the
user reviews and applies them. Applying always takes a backup first and only
ever rewrites the single Show/Hide word on each changed block.

The heavy lifting lives in :mod:`features.visibility_manager`; this module is
purely the CustomTkinter/ttk presentation layer, wired to the main app so other
tabs refresh after an apply.
"""

from __future__ import annotations

import logging
import os
import tkinter as tk
from tkinter import ttk, messagebox

import customtkinter as ctk

from features.visibility_manager import (
    VisibilityManager, VisibilityBlockView, SMART_GROUPS, smart_group_for,
)

log = logging.getLogger(__name__)


_INTRO_TEXT = (
    "This tab changes whether filter blocks use Show or Hide. It does not delete "
    "rules, sounds, colors, effects, or minimap icons."
)


class _Tooltip:
    """Tiny hover tooltip for CTk/tk widgets (CTk has none built in)."""

    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self._tip = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _e=None):
        if self._tip or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 16
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except Exception:
            return
        self._tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw, text=self.text, justify="left", background="#23262b",
            foreground="#e9e9e9", relief="solid", borderwidth=1,
            font=("Segoe UI", 9), wraplength=340, padx=8, pady=5,
        ).pack()

    def _hide(self, _e=None):
        if self._tip:
            self._tip.destroy()
            self._tip = None


class VisibilityManagerTab:
    """Controller + view for the Item Visibility tab."""

    # Treeview columns (id -> heading label).
    COLUMNS = [
        ("pending", "Δ"),
        ("current", "Now"),
        ("desired", "Will be"),
        ("risk", "Risk"),
        ("category", "Section"),
        ("subsection", "Subsection"),
        ("rarity", "Rarity"),
        ("klass", "Class"),
        ("base", "BaseType"),
        ("levels", "Levels"),
        ("stack", "Stack"),
        ("sound", "Sound"),
        ("fx", "Effect / Minimap"),
        ("context", "Item context"),
    ]

    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.manager = VisibilityManager()

        # iid -> VisibilityBlockView for the rows currently in the tree.
        self._row_by_iid: dict[str, VisibilityBlockView] = {}
        self._menu = None

        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        tm = self.app.theme_manager

        root = ctk.CTkFrame(self.parent, corner_radius=12)
        root.pack(fill="both", expand=True, padx=6, pady=6)
        tm.register_widget(root, tm.ROLE_PANEL)

        # ---- Intro note ----
        note = ctk.CTkLabel(
            root, text="🛈  " + _INTRO_TEXT, anchor="w", justify="left",
            font=("Segoe UI", 11), wraplength=1200,
        )
        note.pack(fill="x", padx=12, pady=(10, 4))
        tm.register_widget(note, tm.ROLE_TEXT_MUTED)

        # ---- Top control bar ----
        controls = ctk.CTkFrame(root, corner_radius=10)
        controls.pack(fill="x", padx=10, pady=(2, 6))
        tm.register_widget(controls, tm.ROLE_PANEL_ALT)

        row1 = ctk.CTkFrame(controls, fg_color="transparent")
        row1.pack(fill="x", padx=8, pady=(8, 2))

        ctk.CTkLabel(row1, text="Search", font=("Segoe UI Semibold", 10)).pack(side="left", padx=(2, 4))
        self.search_box = ctk.CTkEntry(
            row1, height=32, width=240,
            placeholder_text="Search base, class, section…",
        )
        self.search_box.pack(side="left", padx=(0, 10))
        self.search_box.bind("<KeyRelease>", lambda _e: self._populate())
        tm.register_widget(self.search_box, tm.ROLE_ENTRY)

        ctk.CTkLabel(row1, text="Visibility", font=("Segoe UI Semibold", 10)).pack(side="left", padx=(2, 4))
        self.vis_filter = ctk.CTkOptionMenu(
            row1, width=160, command=lambda _v: self._populate(),
            values=["All", "Currently Shown", "Currently Hidden"],
        )
        self.vis_filter.set("All")
        self.vis_filter.pack(side="left", padx=(0, 10))
        tm.register_widget(self.vis_filter, tm.ROLE_GHOST)

        ctk.CTkLabel(row1, text="Section", font=("Segoe UI Semibold", 10)).pack(side="left", padx=(2, 4))
        self.cat_filter = ctk.CTkOptionMenu(
            row1, width=200, command=lambda _v: self._populate(), values=["All sections"],
        )
        self.cat_filter.set("All sections")
        self.cat_filter.pack(side="left", padx=(0, 10))
        tm.register_widget(self.cat_filter, tm.ROLE_GHOST)

        ctk.CTkLabel(row1, text="Group", font=("Segoe UI Semibold", 10)).pack(side="left", padx=(2, 4))
        self.group_filter = ctk.CTkOptionMenu(
            row1, width=190, command=lambda _v: self._populate(),
            values=["All groups"] + SMART_GROUPS,
        )
        self.group_filter.set("All groups")
        self.group_filter.pack(side="left", padx=(0, 10))
        tm.register_widget(self.group_filter, tm.ROLE_GHOST)

        self.refresh_btn = ctk.CTkButton(row1, text="↻ Refresh", width=100, command=self.refresh)
        self.refresh_btn.pack(side="right", padx=(6, 2))
        tm.register_widget(self.refresh_btn, tm.ROLE_GHOST)
        _Tooltip(self.refresh_btn, "Reload the list from the current filter, discarding pending toggles.")

        # ---- Row 2: bulk + apply actions ----
        row2 = ctk.CTkFrame(controls, fg_color="transparent")
        row2.pack(fill="x", padx=8, pady=(2, 8))

        ctk.CTkLabel(row2, text="Selection", font=("Segoe UI Semibold", 10)).pack(side="left", padx=(2, 4))
        self.sel_all_btn = ctk.CTkButton(row2, text="Select visible", width=110, command=self._select_all_visible)
        self.sel_all_btn.pack(side="left", padx=2)
        self.clear_sel_btn = ctk.CTkButton(row2, text="Clear", width=70, command=self._clear_selection)
        self.clear_sel_btn.pack(side="left", padx=2)

        self.set_show_btn = ctk.CTkButton(
            row2, text="👁 Set to Shown", width=130,
            command=lambda: self._set_target_visibility("Show"))
        self.set_show_btn.pack(side="left", padx=(12, 2))
        self.set_hide_btn = ctk.CTkButton(
            row2, text="🚫 Set to Hidden", width=130, fg_color="#5b3a0c",
            command=lambda: self._set_target_visibility("Hide"))
        self.set_hide_btn.pack(side="left", padx=2)
        self.reset_btn = ctk.CTkButton(
            row2, text="↺ Reset", width=90,
            command=self._reset_target)
        self.reset_btn.pack(side="left", padx=2)
        _Tooltip(self.set_show_btn, "Mark the selected rows (or all visible rows) to be Shown.")
        _Tooltip(self.set_hide_btn, "Mark the selected rows (or all visible rows) to be Hidden.")
        _Tooltip(self.reset_btn, "Undo pending toggles on the selected/visible rows.")

        self.apply_btn = ctk.CTkButton(
            row2, text="✔ Apply Changes…", width=150, command=self._apply_clicked)
        self.apply_btn.pack(side="right", padx=2)
        self.revert_btn = ctk.CTkButton(
            row2, text="Revert Unsaved", width=130, command=self._revert_all)
        self.revert_btn.pack(side="right", padx=2)
        _Tooltip(self.apply_btn, "Review and write all pending Show/Hide changes to the filter (a backup is made first).")
        _Tooltip(self.revert_btn, "Discard every pending toggle and return all rows to their saved state.")

        for b in (self.sel_all_btn, self.clear_sel_btn, self.reset_btn,
                  self.apply_btn, self.set_show_btn):
            tm.register_widget(b, tm.ROLE_PRIMARY)
        tm.register_widget(self.set_hide_btn, tm.ROLE_DANGER)
        tm.register_widget(self.revert_btn, tm.ROLE_GHOST)

        # ---- Table ----
        table_wrap = ctk.CTkFrame(root, corner_radius=10)
        table_wrap.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        tm.register_widget(table_wrap, tm.ROLE_PANEL_ALT)

        col_ids = [c[0] for c in self.COLUMNS]
        self.tree = ttk.Treeview(table_wrap, columns=col_ids, show="headings", selectmode="extended")
        for cid, label in self.COLUMNS:
            self.tree.heading(cid, text=label)
        widths = {
            "pending": 32, "current": 60, "desired": 70, "risk": 70,
            "category": 170, "subsection": 140, "rarity": 110, "klass": 150,
            "base": 200, "levels": 120, "stack": 70, "sound": 150,
            "fx": 150, "context": 320,
        }
        anchors = {"pending": "center", "current": "center", "desired": "center", "risk": "center"}
        for cid, _ in self.COLUMNS:
            self.tree.column(cid, width=widths.get(cid, 120), anchor=anchors.get(cid, "w"))

        vsb = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscroll=vsb.set, xscroll=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_wrap.grid_rowconfigure(0, weight=1)
        table_wrap.grid_columnconfigure(0, weight=1)

        # Zebra + state tags. Zebra is theme-managed; the state tags use fixed
        # accent colors that read on both light and dark backgrounds.
        self.tree.tag_configure("oddrow", background="#2f2f2f")
        self.tree.tag_configure("evenrow", background="#292929")
        self.tree.tag_configure("pending", foreground="#ffd166", font=("Segoe UI", 9, "bold"))
        self.tree.tag_configure("risk_high", foreground="#ff7b7b")
        self.tree.tag_configure("risk_med", foreground="#ffc36b")
        tm.register_treeview_tags(self.tree, {
            "oddrow": "tree_row_odd",
            "evenrow": "tree_row_even",
        })

        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_status())
        self.tree.bind("<Control-a>", self._select_all_visible)
        self.tree.bind("<Control-A>", self._select_all_visible)

        # ---- Status line ----
        self.status = ctk.CTkLabel(root, text="No filter loaded.", anchor="w", font=("Segoe UI", 11))
        self.status.pack(fill="x", padx=12, pady=(0, 8))
        tm.register_widget(self.status, tm.ROLE_TEXT_MUTED)

    # ------------------------------------------------------------ data flow
    def refresh(self):
        """Rebuild the view from the app's currently loaded filter."""
        self.manager.load_from_lines(self.app.lines, self.app.filter_path)
        self._rebuild_category_choices()
        self._populate()

    def _rebuild_category_choices(self):
        sections = []
        seen = set()
        for v in self.manager.blocks:
            if v.category not in seen:
                seen.add(v.category)
                sections.append(v.category)
        values = ["All sections"] + sections
        self.cat_filter.configure(values=values)
        if self.cat_filter.get() not in values:
            self.cat_filter.set("All sections")

    def _visible_views(self) -> list[VisibilityBlockView]:
        """Apply the current search + dropdown filters to the parsed blocks."""
        kw = self.search_box.get().strip().lower()
        vis = self.vis_filter.get()
        cat = self.cat_filter.get()
        grp = self.group_filter.get()

        out = []
        for v in self.manager.blocks:
            if vis == "Currently Shown" and v.current_visibility != "Show":
                continue
            if vis == "Currently Hidden" and v.current_visibility != "Hide":
                continue
            if cat != "All sections" and v.category != cat:
                continue
            if grp != "All groups" and smart_group_for(v) != grp:
                continue
            if kw:
                hay = " ".join([
                    v.category, v.subsection, v.rarity, " ".join(v.classes),
                    " ".join(v.base_types), v.item_level, v.stack_size,
                    v.sound_summary, v.context_summary,
                ]).lower()
                if kw not in hay:
                    continue
            out.append(v)
        return out

    def _populate(self):
        self.tree.delete(*self.tree.get_children())
        self._row_by_iid.clear()
        for idx, v in enumerate(self._visible_views()):
            iid = f"v{v.start_line}"
            self.tree.insert("", "end", iid=iid, values=self._row_values(v),
                             tags=self._row_tags(v, idx))
            self._row_by_iid[iid] = v
        self._update_status()

    def _row_values(self, v: VisibilityBlockView):
        pending = "●" if v.has_pending_change else ""
        base = ", ".join(v.base_types[:3]) + (f" +{len(v.base_types) - 3}" if len(v.base_types) > 3 else "")
        klass = ", ".join(v.classes[:3]) + (f" +{len(v.classes) - 3}" if len(v.classes) > 3 else "")
        fx = "; ".join(p for p in (
            (f"FX {v.effect_summary}" if v.effect_summary else ""),
            (f"Map {v.minimap_summary}" if v.minimap_summary else ""),
        ) if p)
        return (
            pending,
            "Show" if v.current_visibility == "Show" else "Hide",
            v.desired_visibility,
            v.risk_level,
            v.category,
            v.subsection,
            v.rarity,
            klass,
            base,
            v.item_level,
            v.stack_size,
            v.sound_summary,
            fx,
            v.context_summary,
        )

    def _row_tags(self, v: VisibilityBlockView, idx: int):
        tags = ["oddrow" if idx % 2 else "evenrow"]
        if v.risk_level == "High":
            tags.append("risk_high")
        elif v.risk_level == "Medium":
            tags.append("risk_med")
        if v.has_pending_change:
            tags.append("pending")
        return tuple(tags)

    def _refresh_row(self, v: VisibilityBlockView):
        iid = f"v{v.start_line}"
        if self.tree.exists(iid):
            # Preserve zebra parity by reading the row's current index.
            idx = self.tree.index(iid)
            self.tree.item(iid, values=self._row_values(v), tags=self._row_tags(v, idx))

    # ------------------------------------------------------------ selection
    def _selected_views(self) -> list[VisibilityBlockView]:
        return [self._row_by_iid[i] for i in self.tree.selection() if i in self._row_by_iid]

    def _target_views(self) -> list[VisibilityBlockView]:
        """Bulk-op scope: the explicit selection if any, else all visible rows."""
        sel = self._selected_views()
        return sel if sel else list(self._row_by_iid.values())

    def _select_all_visible(self, _e=None):
        kids = self.tree.get_children()
        if kids:
            self.tree.selection_set(kids)
        return "break"

    def _clear_selection(self):
        self.tree.selection_remove(self.tree.selection())

    # ------------------------------------------------------------ toggles
    def _set_target_visibility(self, word: str):
        views = self._target_views()
        if not views:
            return
        for v in views:
            self.manager.set_desired(v, word)
            self._refresh_row(v)
        self._update_status()

    def _reset_target(self):
        for v in self._target_views():
            self.manager.reset(v)
            self._refresh_row(v)
        self._update_status()

    def _revert_all(self):
        if not self.manager.has_pending():
            self._set_status("Nothing to revert.")
            return
        self.manager.revert_all()
        self._populate()
        self._set_status("Reverted all pending changes.")

    # ------------------------------------------------------------ context menu
    def _on_right_click(self, event):
        row = self.tree.identify_row(event.y)
        if row and row not in self.tree.selection():
            self.tree.selection_set(row)
            self.tree.focus(row)
        if self._menu is None:
            self._menu = self._build_menu()
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()

    def _build_menu(self):
        m = tk.Menu(self.tree, tearoff=False)
        m.add_command(label="Set to Shown", command=lambda: self._ctx_set("Show"))
        m.add_command(label="Set to Hidden", command=lambda: self._ctx_set("Hide"))
        m.add_command(label="Reset to current", command=self._ctx_reset)
        m.add_separator()
        m.add_command(label="Preview raw block…", command=self._ctx_preview)
        return m

    def _ctx_targets(self) -> list[VisibilityBlockView]:
        sel = self._selected_views()
        if sel:
            return sel
        f = self.tree.focus()
        v = self._row_by_iid.get(f)
        return [v] if v else []

    def _ctx_set(self, word: str):
        for v in self._ctx_targets():
            self.manager.set_desired(v, word)
            self._refresh_row(v)
        self._update_status()

    def _ctx_reset(self):
        for v in self._ctx_targets():
            self.manager.reset(v)
            self._refresh_row(v)
        self._update_status()

    def _ctx_preview(self):
        targets = self._ctx_targets()
        if targets:
            self._show_raw_block(targets[0])

    def _on_double_click(self, _event):
        v = self._row_by_iid.get(self.tree.focus())
        if v:
            self._show_raw_block(v)

    # ------------------------------------------------------------ status
    def _update_status(self):
        total = len(self.manager.blocks)
        visible = len(self._row_by_iid)
        pending = len(self.manager.pending_views())
        selected = len(self.tree.selection())
        self._set_status(
            f"{visible} of {total} blocks shown • {selected} selected • "
            f"{pending} pending change(s)"
        )

    def _set_status(self, text: str):
        try:
            self.status.configure(text=text)
        except Exception:
            pass

    # ------------------------------------------------------------ dialogs
    def _show_raw_block(self, v: VisibilityBlockView):
        """Read-only modal showing the block exactly, with the header highlighted."""
        dlg = ctk.CTkToplevel(self.app.root)
        wrap = ctk.CTkFrame(dlg, corner_radius=10)
        wrap.pack(fill="both", expand=True, padx=12, pady=12)

        new_word = v.desired_visibility
        head = (f"Block at line {v.start_line + 1} • Section: {v.category}"
                + (f" › {v.subsection}" if v.subsection else ""))
        ctk.CTkLabel(wrap, text=head, font=("Segoe UI Semibold", 12),
                     anchor="w", justify="left").pack(fill="x", padx=4, pady=(2, 2))
        change_note = (
            f"First line will change:  {v.current_visibility}  →  {new_word}"
            if v.has_pending_change else
            f"Currently: {v.current_visibility}  (no pending change)"
        )
        ctk.CTkLabel(wrap, text=change_note, font=("Segoe UI", 11),
                     anchor="w", justify="left").pack(fill="x", padx=4, pady=(0, 6))

        txt = tk.Text(wrap, wrap="none", height=min(24, max(6, len(v.raw_lines) + 1)),
                      font=("Consolas", 10), background="#1e1e1e",
                      foreground="#e9e9e9", insertbackground="#e9e9e9",
                      relief="flat", padx=10, pady=8)
        txt.pack(fill="both", expand=True, padx=4, pady=4)
        for line in v.raw_lines:
            txt.insert("end", line if line.endswith("\n") else line + "\n")
        # Highlight the header line that the apply would touch.
        txt.tag_configure("header", background="#3a3a12", foreground="#ffe49a")
        txt.tag_add("header", "1.0", "1.end")
        txt.configure(state="disabled")

        btns = ctk.CTkFrame(wrap, fg_color="transparent")
        btns.pack(fill="x", padx=4, pady=(4, 2))
        ctk.CTkButton(btns, text="Close", width=100, command=dlg.destroy).pack(side="right")

        self.app._setup_dialog(dlg, title="Raw block preview",
                               default_size=(720, 460), min_size=(520, 320))

    def _apply_clicked(self):
        changes = self.manager.pending_changes()
        if not changes:
            messagebox.showinfo("Nothing to apply",
                                "No pending Show/Hide changes. Toggle some rows first.")
            return
        if not self.app.filter_path or not os.path.isfile(self.app.filter_path):
            messagebox.showwarning(
                "No saved filter",
                "Save the filter to disk first — visibility changes write to the file.")
            return
        self._show_review_dialog(changes)

    def _show_review_dialog(self, changes):
        """Combined preview + confirmation: planned-changes table and a warning
        summary, with a single explicit Apply button. Cancel aborts."""
        to_hide = sum(1 for c in changes if c.new_visibility == "Hide")
        to_show = sum(1 for c in changes if c.new_visibility == "Show")
        high_risk = [c for c in changes if c.risk_level == "High" and c.new_visibility == "Hide"]

        dlg = ctk.CTkToplevel(self.app.root)
        wrap = ctk.CTkFrame(dlg, corner_radius=10)
        wrap.pack(fill="both", expand=True, padx=12, pady=12)

        ctk.CTkLabel(wrap, text="Review visibility changes",
                     font=("Segoe UI Semibold", 15), anchor="w").pack(fill="x", padx=6, pady=(2, 6))

        # Summary + warnings banner
        backup_dir = self._expected_backup_dir()
        summary_lines = [
            f"• {to_hide} block(s) will change  Show → Hide",
            f"• {to_show} block(s) will change  Hide → Show",
            f"• {len(high_risk)} high-risk block(s) among them",
            f"• Filter file:  {self.app.filter_path}",
            f"• A backup will be created in:  {backup_dir}",
        ]
        summary = ctk.CTkLabel(wrap, text="\n".join(summary_lines), anchor="w",
                               justify="left", font=("Segoe UI", 11))
        summary.pack(fill="x", padx=6, pady=(0, 6))

        warn_msgs = self._build_warnings(changes, to_hide, high_risk)
        if warn_msgs:
            warn = ctk.CTkLabel(
                wrap, text="⚠  " + "\n⚠  ".join(warn_msgs), anchor="w",
                justify="left", font=("Segoe UI Semibold", 11), text_color="#ffb454")
            warn.pack(fill="x", padx=6, pady=(0, 8))

        # Planned-changes table
        table_wrap = ctk.CTkFrame(wrap, corner_radius=8)
        table_wrap.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        cols = ("line", "category", "summary", "from", "to", "risk")
        labels = ("Line", "Section", "Item", "From", "To", "Risk")
        tv = ttk.Treeview(table_wrap, columns=cols, show="headings", height=10)
        for c, l in zip(cols, labels):
            tv.heading(c, text=l)
        tv.column("line", width=55, anchor="center")
        tv.column("category", width=180, anchor="w")
        tv.column("summary", width=300, anchor="w")
        tv.column("from", width=60, anchor="center")
        tv.column("to", width=60, anchor="center")
        tv.column("risk", width=70, anchor="center")
        tv.tag_configure("risk_high", foreground="#ff7b7b")
        tv.tag_configure("risk_med", foreground="#ffc36b")
        vsb = ttk.Scrollbar(table_wrap, orient="vertical", command=tv.yview)
        tv.configure(yscroll=vsb.set)
        tv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        table_wrap.grid_rowconfigure(0, weight=1)
        table_wrap.grid_columnconfigure(0, weight=1)
        for c in changes:
            cat = next((v.category for v in self.manager.blocks if v.start_line == c.start_line), "")
            tag = "risk_high" if c.risk_level == "High" else ("risk_med" if c.risk_level == "Medium" else "")
            tv.insert("", "end", values=(
                c.start_line + 1, cat, c.summary, c.old_visibility, c.new_visibility, c.risk_level,
            ), tags=(tag,) if tag else ())

        # Buttons
        btns = ctk.CTkFrame(wrap, fg_color="transparent")
        btns.pack(fill="x", padx=6, pady=(2, 2))
        ctk.CTkButton(btns, text="Cancel", width=110, command=dlg.destroy,
                      fg_color="gray35").pack(side="right", padx=4)

        def _do_apply():
            dlg.destroy()
            self._do_apply()

        ctk.CTkButton(btns, text=f"Apply {len(changes)} change(s)", width=170,
                      command=_do_apply).pack(side="right", padx=4)

        self.app._setup_dialog(dlg, title="Review visibility changes",
                               default_size=(820, 560), min_size=(640, 420))

    def _build_warnings(self, changes, to_hide, high_risk):
        msgs = []
        if high_risk:
            kinds = sorted({r for c in high_risk for r in c.risk_reasons})[:4]
            msgs.append(
                f"You are hiding {len(high_risk)} high-risk block(s) "
                f"({'; '.join(kinds)}). Double-check these.")
        if to_hide >= 15:
            msgs.append(f"You are hiding {to_hide} blocks at once.")
        return msgs

    def _expected_backup_dir(self) -> str:
        try:
            base = os.path.basename(self.app.filter_path)
            name, _ = os.path.splitext(base)
            return os.path.join(os.path.dirname(self.app.filter_path), f"{name}_backups")
        except Exception:
            return "(filter folder)"

    def _do_apply(self):
        create_backup = getattr(self.app.settings, "create_backups", True)
        max_backups = getattr(self.app.settings, "max_backups", None)
        result = self.manager.apply(create_backup=create_backup, max_backups=max_backups)

        if not result.ok:
            messagebox.showerror(
                "Apply failed",
                "Some changes could not be applied:\n\n" + "\n".join(result.errors))

        # Resync everything: the manager already rebuilt; refresh the app's other
        # tabs and our own table.
        try:
            self.app.refresh_filter_data()
        except Exception:
            log.exception("Visibility apply: app refresh failed")
            self.refresh()

        msg = (f"Applied {result.applied} change(s): "
               f"{result.to_hide} hidden, {result.to_show} shown")
        if result.backup_path:
            msg += f" • backup: {os.path.basename(result.backup_path)}"
        if result.skipped:
            msg += f" • {result.skipped} skipped"
        self._set_status(msg)
        try:
            self.app._set_status(msg)
        except Exception:
            pass
