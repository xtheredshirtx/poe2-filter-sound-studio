"""In-app editor for one tier's styling and block membership.

Opens when the user clicks a tier swatch in the Visual Tools dialog. Lets them:

  - Pick text / border / background colors via the existing ColorPickerDialog
  - Set font size, PlayEffect, MinimapIcon for the tier
  - See every block currently in this tier (after applying user overrides)
  - Reassign any block to a different tier

All edits land in the per-filter sidecar via core.user_overrides.save_overrides,
so they survive app restarts and re-loads of the same filter.
"""

from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional, Tuple

import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox

from features.visual_emphasis import (
    BlockStyle, ValueTier,
    EMPHASIS_PRESETS, POE2_NAMED_COLORS, POE2_MINIMAP_SHAPES,
    EmphasisStyler, StyleChange, classify_block, iter_blocks,
)
from core.user_overrides import (
    UserOverrides, BlockOverride, block_signature, save_overrides,
    friendly_block_name,
)
from ui.dialogs import ColorPickerDialog


_TIER_LABELS = {
    ValueTier.MYTHIC: "Mythic",
    ValueTier.TOP: "Top",
    ValueTier.HIGH: "High",
    ValueTier.MID: "Mid",
    ValueTier.LOW: "Low",
    ValueTier.JUNK: "Junk",
}

# Tiers the user can move a block to (HIDDEN is special — we don't expose it).
_REASSIGN_TIERS = (
    ValueTier.MYTHIC, ValueTier.TOP, ValueTier.HIGH,
    ValueTier.MID, ValueTier.LOW, ValueTier.JUNK,
)

_NONE_LABEL = "(none)"


def open_tier_detail(app, tier: ValueTier, plan: List[StyleChange],
                     presets: Dict[ValueTier, BlockStyle],
                     overrides: UserOverrides,
                     on_close: Callable[[], None]) -> None:
    """Entry point from the Visual Tools dialog."""
    _TierDetailDialog(app, tier, plan, presets, overrides, on_close)


class _TierDetailDialog:
    def __init__(self, app, tier: ValueTier, plan: List[StyleChange],
                 presets: Dict[ValueTier, BlockStyle],
                 overrides: UserOverrides,
                 on_close: Callable[[], None]):
        self.app = app
        self.tier = tier
        self.plan = plan
        self.presets = presets
        self.overrides = overrides
        self.on_close_cb = on_close
        self.pal = app.theme_manager.current()

        # The style we're editing — copy-on-open so Cancel really cancels.
        existing = overrides.tier_presets.get(tier) or presets.get(tier) or BlockStyle()
        self.draft_style = self._clone_style(existing)

        self.dlg = ctk.CTkToplevel(app.root)
        main = ctk.CTkFrame(self.dlg, fg_color=self.pal.panel)
        main.pack(fill="both", expand=True, padx=12, pady=12)

        self._build_header(main)
        self._build_preview_and_editor(main)
        self._build_block_list(main)
        self._build_footer(main)

        app._setup_dialog(
            self.dlg,
            title=f"Tier: {_TIER_LABELS[tier]}",
            default_size=(960, 800), min_size=(840, 660),
        )

    # ---------------- Layout ----------------

    def _build_header(self, parent):
        pal = self.pal
        in_tier = [c for c in self.plan if c.tier == self.tier]
        with_override = sum(1 for c in in_tier if c.has_override)
        ctk.CTkLabel(
            parent,
            text=f"{_TIER_LABELS[self.tier]} tier — {len(in_tier)} block(s), "
                 f"{with_override} with overrides",
            font=("Segoe UI Semibold", 14),
        ).pack(anchor="w")
        ctk.CTkLabel(
            parent,
            text=("Edit how items in this tier look when they drop. "
                  "Changes apply to every block in this tier unless a "
                  "specific block has its own per-block override."),
            text_color=pal.text_muted, wraplength=900, justify="left",
        ).pack(anchor="w", pady=(0, 8))

    def _build_preview_and_editor(self, parent):
        pal = self.pal

        # ----- Layout: preview on the left, editor on the right -----
        container = ctk.CTkFrame(parent, fg_color=pal.panel_alt)
        container.pack(fill="x", pady=(0, 8))

        left = ctk.CTkFrame(container, fg_color="transparent")
        left.pack(side="left", fill="y", padx=8, pady=8)

        ctk.CTkLabel(left, text="Preview",
                     font=("Segoe UI Semibold", 11)).pack(anchor="w")

        # Use a raw tk.Frame for the preview so we can drive its bg colour
        # directly without CTk theme interference.
        self._preview_outer = tk.Frame(left, bd=2, relief="solid", width=320, height=120)
        self._preview_outer.pack(pady=(4, 0))
        self._preview_outer.pack_propagate(False)
        self._preview_inner = tk.Frame(self._preview_outer, bd=0)
        self._preview_inner.pack(fill="both", expand=True)
        self._preview_label = tk.Label(
            self._preview_inner, text="Mirror of Kalandra",
            font=("Segoe UI Semibold", 14),
        )
        self._preview_label.pack(expand=True)
        self._preview_extra = tk.Label(
            self._preview_inner, text="",
            font=("Segoe UI", 9),
        )
        self._preview_extra.pack(side="bottom", fill="x")

        # ----- Editor (right) -----
        right = ctk.CTkFrame(container, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(8, 8), pady=8)

        ctk.CTkLabel(right, text="Style",
                     font=("Segoe UI Semibold", 11)).pack(anchor="w")

        # Color rows.
        self._build_color_row(right, "Text color", "text_color")
        self._build_color_row(right, "Border color", "border_color")
        self._build_color_row(right, "Background", "bg_color")

        # Font size.
        font_row = ctk.CTkFrame(right, fg_color="transparent")
        font_row.pack(fill="x", pady=4)
        ctk.CTkLabel(font_row, text="Font size:", width=110, anchor="w").pack(side="left")
        self._font_var = tk.IntVar(value=self.draft_style.font_size or 34)
        self._font_value_label = ctk.CTkLabel(font_row, text=str(self._font_var.get()), width=40)
        font_slider = ctk.CTkSlider(
            font_row, from_=18, to=45, number_of_steps=27,
            command=self._on_font_change,
        )
        font_slider.set(self._font_var.get())
        font_slider.pack(side="left", fill="x", expand=True, padx=(6, 6))
        self._font_value_label.pack(side="left")

        # PlayEffect.
        effect_row = ctk.CTkFrame(right, fg_color="transparent")
        effect_row.pack(fill="x", pady=4)
        ctk.CTkLabel(effect_row, text="PlayEffect:", width=110, anchor="w").pack(side="left")
        effect_color = self.draft_style.play_effect[0] if self.draft_style.play_effect else _NONE_LABEL
        is_temp = self.draft_style.play_effect[1] if self.draft_style.play_effect else False
        self._effect_var = tk.StringVar(value=effect_color)
        ctk.CTkOptionMenu(
            effect_row, values=[_NONE_LABEL] + list(POE2_NAMED_COLORS),
            variable=self._effect_var, command=lambda _v: self._on_style_field_change(),
            width=120,
        ).pack(side="left", padx=(4, 8))
        self._temp_var = tk.BooleanVar(value=is_temp)
        ctk.CTkCheckBox(
            effect_row, text="Temp (only while map is open)",
            variable=self._temp_var,
            command=self._on_style_field_change,
        ).pack(side="left")

        # MinimapIcon.
        map_row = ctk.CTkFrame(right, fg_color="transparent")
        map_row.pack(fill="x", pady=4)
        ctk.CTkLabel(map_row, text="MinimapIcon:", width=110, anchor="w").pack(side="left")
        map_size, map_color, map_shape = ("0", _NONE_LABEL, _NONE_LABEL)
        if self.draft_style.minimap:
            sz, c, sh = self.draft_style.minimap
            map_size, map_color, map_shape = str(sz), c, sh
        self._map_size_var = tk.StringVar(value=map_size)
        self._map_color_var = tk.StringVar(value=map_color)
        self._map_shape_var = tk.StringVar(value=map_shape)
        ctk.CTkOptionMenu(map_row, values=["0", "1", "2"],
                          variable=self._map_size_var,
                          command=lambda _v: self._on_style_field_change(),
                          width=60).pack(side="left", padx=(4, 4))
        ctk.CTkOptionMenu(map_row, values=[_NONE_LABEL] + list(POE2_NAMED_COLORS),
                          variable=self._map_color_var,
                          command=lambda _v: self._on_style_field_change(),
                          width=110).pack(side="left", padx=(0, 4))
        ctk.CTkOptionMenu(map_row, values=[_NONE_LABEL] + list(POE2_MINIMAP_SHAPES),
                          variable=self._map_shape_var,
                          command=lambda _v: self._on_style_field_change(),
                          width=140).pack(side="left")

        # Quick actions.
        actions = ctk.CTkFrame(right, fg_color="transparent")
        actions.pack(fill="x", pady=(8, 0))
        ctk.CTkButton(actions, text="Reset to default",
                      command=self._reset_to_default, width=160,
                      fg_color=pal.panel_alt, hover_color=pal.border,
                      text_color=pal.text).pack(side="left", padx=4)
        if self.tier in self.overrides.tier_presets:
            ctk.CTkButton(actions, text="Remove tier override",
                          command=self._remove_tier_override, width=200,
                          fg_color=pal.panel_alt, hover_color=pal.border,
                          text_color=pal.text).pack(side="left", padx=4)

        self._refresh_preview()
        self._refresh_color_swatches()

    def _build_color_row(self, parent, label_text: str, attr: str):
        pal = self.pal
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text=f"{label_text}:", width=110, anchor="w").pack(side="left")

        swatch = tk.Frame(row, width=28, height=22, bd=1, relief="solid")
        swatch.pack(side="left", padx=(4, 6))
        swatch.pack_propagate(False)

        value_label = ctk.CTkLabel(row, text="(none)",
                                   text_color=pal.text_muted, width=160, anchor="w")
        value_label.pack(side="left")

        ctk.CTkButton(row, text="Pick…",
                      command=lambda a=attr: self._pick_color(a),
                      width=70).pack(side="left", padx=(4, 0))
        ctk.CTkButton(row, text="Clear",
                      command=lambda a=attr: self._clear_color(a),
                      width=70,
                      fg_color=pal.panel_alt, hover_color=pal.border,
                      text_color=pal.text).pack(side="left", padx=(4, 0))

        # Stash widgets for refresh.
        if not hasattr(self, "_color_widgets"):
            self._color_widgets = {}
        self._color_widgets[attr] = (swatch, value_label)

    def _build_block_list(self, parent):
        pal = self.pal

        # ----- Header row: title + search -----
        header_row = ctk.CTkFrame(parent, fg_color="transparent")
        header_row.pack(fill="x", pady=(8, 2))
        self._list_title = ctk.CTkLabel(
            header_row,
            text=f"Items in {_TIER_LABELS[self.tier]} tier",
            font=("Segoe UI Semibold", 11),
        )
        self._list_title.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(header_row, text="Search:",
                     text_color=pal.text_muted).pack(side="left", padx=(4, 4))
        self._search_var = tk.StringVar()
        search_entry = ctk.CTkEntry(
            header_row, textvariable=self._search_var, width=260,
            placeholder_text="e.g. 'divine', 'belt', 'unique', 'waystone'",
        )
        search_entry.pack(side="left")
        self._search_var.trace_add("write", lambda *_: self._refresh_block_list())
        ctk.CTkButton(header_row, text="Clear",
                      command=lambda: self._search_var.set(""),
                      width=70,
                      fg_color=pal.panel_alt, hover_color=pal.border,
                      text_color=pal.text).pack(side="left", padx=(4, 0))
        self._search_hint = ctk.CTkLabel(
            header_row,
            text="(empty = this tier only · typed = searches every tier)",
            text_color=pal.text_muted, font=("Segoe UI", 9),
        )
        self._search_hint.pack(side="left", padx=(8, 0))

        tf = ctk.CTkFrame(parent, fg_color=pal.panel_alt)
        tf.pack(fill="both", expand=True, pady=4)
        cols = ("item", "tier", "from", "line")
        self._block_tree = ttk.Treeview(
            tf, columns=cols, show="headings",
            height=10, selectmode="browse",
        )
        self._block_tree.heading("item", text="Item")
        self._block_tree.heading("tier", text="Tier")
        self._block_tree.heading("from", text="Note")
        self._block_tree.heading("line", text="Line")
        self._block_tree.column("item", width=520, anchor="w")
        self._block_tree.column("tier", width=90, anchor="w")
        self._block_tree.column("from", width=120, anchor="w")
        self._block_tree.column("line", width=60, anchor="e")
        self._block_tree.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        sb = ttk.Scrollbar(tf, orient="vertical", command=self._block_tree.yview)
        self._block_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 4), pady=4)

        # Context menu for reassigning. Same menu opens via right-click and
        # the "Move selected to…" button so users find it however they look.
        self._reassign_menu = tk.Menu(self._block_tree, tearoff=False)
        for t in _REASSIGN_TIERS:
            self._reassign_menu.add_command(
                label=f"Move to {_TIER_LABELS[t]}",
                command=lambda dest=t: self._reassign_selected(dest),
            )
        self._reassign_menu.add_separator()
        self._reassign_menu.add_command(
            label="Reset to heuristic tier",
            command=lambda: self._reassign_selected(None),
        )

        self._block_tree.bind("<Button-3>", self._on_block_right_click)
        self._block_tree.bind("<Double-1>", self._on_block_double_click)

        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.pack(fill="x", pady=(2, 0))
        ctk.CTkButton(btn_row, text="Move selected to…",
                      command=self._open_reassign_menu_for_selected,
                      width=180).pack(side="left", padx=4)
        self._count_label = ctk.CTkLabel(btn_row, text="",
                                          text_color=pal.text_muted)
        self._count_label.pack(side="left", padx=(8, 0))

        # Keyed by tree iid (= str(line_no)) -> (signature, base_tier).
        self._block_meta: Dict[str, Tuple[str, ValueTier]] = {}
        # Cache friendly names once — they don't change between searches.
        self._friendly_cache: Dict[int, str] = {}
        self._refresh_block_list()

    def _build_footer(self, parent):
        pal = self.pal
        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.pack(fill="x", pady=(10, 0))

        ctk.CTkButton(
            btn_row, text="Close", command=self._on_cancel, width=120,
            fg_color=pal.panel_alt, hover_color=pal.border, text_color=pal.text,
        ).pack(side="right", padx=4)
        ctk.CTkButton(
            btn_row, text="Save tier styling",
            command=self._save_and_close, width=180,
            fg_color=pal.accent, hover_color=pal.accent_hover,
            text_color=pal.accent_text,
        ).pack(side="right", padx=4)

    # ---------------- Style editing ----------------

    def _pick_color(self, attr: str):
        initial = getattr(self.draft_style, attr) or (255, 255, 255, 255)

        def on_picked(rgba):
            setattr(self.draft_style, attr, rgba)
            self._refresh_color_swatches()
            self._refresh_preview()

        ColorPickerDialog(self.dlg, title=f"Pick {attr.replace('_', ' ')}",
                          initial_color=initial, callback=on_picked)

    def _clear_color(self, attr: str):
        setattr(self.draft_style, attr, None)
        self._refresh_color_swatches()
        self._refresh_preview()

    def _on_font_change(self, value):
        v = int(float(value))
        self._font_var.set(v)
        self._font_value_label.configure(text=str(v))
        self.draft_style.font_size = v
        self._refresh_preview()

    def _on_style_field_change(self):
        # PlayEffect.
        eff = self._effect_var.get()
        if eff == _NONE_LABEL:
            self.draft_style.play_effect = None
        else:
            self.draft_style.play_effect = (eff, bool(self._temp_var.get()))

        # MinimapIcon. If any of the three is "(none)" we treat the whole thing
        # as unset — POE2 needs all three to be a valid icon.
        color = self._map_color_var.get()
        shape = self._map_shape_var.get()
        if color == _NONE_LABEL or shape == _NONE_LABEL:
            self.draft_style.minimap = None
        else:
            try:
                size = int(self._map_size_var.get())
            except ValueError:
                size = 1
            self.draft_style.minimap = (size, color, shape)

        self._refresh_preview()

    def _reset_to_default(self):
        default = EMPHASIS_PRESETS.get(self.tier) or BlockStyle()
        self.draft_style = self._clone_style(default)
        # Re-sync the widgets the slider/options own.
        self._font_var.set(self.draft_style.font_size or 34)
        self._font_value_label.configure(text=str(self._font_var.get()))
        eff = self.draft_style.play_effect
        self._effect_var.set(eff[0] if eff else _NONE_LABEL)
        self._temp_var.set(bool(eff[1]) if eff else False)
        mi = self.draft_style.minimap
        self._map_size_var.set(str(mi[0]) if mi else "0")
        self._map_color_var.set(mi[1] if mi else _NONE_LABEL)
        self._map_shape_var.set(mi[2] if mi else _NONE_LABEL)
        self._refresh_color_swatches()
        self._refresh_preview()

    def _remove_tier_override(self):
        if self.tier in self.overrides.tier_presets:
            del self.overrides.tier_presets[self.tier]
            save_overrides(self.app.filter_path, self.overrides)
            self.app._set_status(f"Removed {_TIER_LABELS[self.tier]} tier override.")
            self._reset_to_default()

    # ---------------- Preview rendering ----------------

    def _refresh_color_swatches(self):
        for attr, (swatch, label) in self._color_widgets.items():
            rgba = getattr(self.draft_style, attr)
            if rgba:
                hex_color = _rgba_to_hex(rgba)
                swatch.configure(bg=hex_color)
                label.configure(text=f"{rgba[0]}, {rgba[1]}, {rgba[2]}  (a={rgba[3]})")
            else:
                swatch.configure(bg=self.pal.panel)
                label.configure(text="(unset — won't be written)")

    def _refresh_preview(self):
        s = self.draft_style
        bg = _rgba_to_hex(s.bg_color) if s.bg_color else "#1e1e1e"
        text_color = _rgba_to_hex(s.text_color) if s.text_color else "#cccccc"
        border = _rgba_to_hex(s.border_color) if s.border_color else "#444444"
        font_size = max(10, min(28, (s.font_size or 34) // 2))

        # The outer frame paints the border colour; inner is bg.
        self._preview_outer.configure(bg=border)
        self._preview_inner.configure(bg=bg)
        self._preview_label.configure(
            bg=bg, fg=text_color,
            font=("Segoe UI Semibold", font_size),
        )
        extras = []
        if s.play_effect:
            extras.append(f"PlayEffect {s.play_effect[0]}"
                          + (" Temp" if s.play_effect[1] else ""))
        if s.minimap:
            sz, c, sh = s.minimap
            extras.append(f"Minimap {sz} {c} {sh}")
        self._preview_extra.configure(
            text="  ·  ".join(extras),
            bg=bg, fg=text_color,
        )

    # ---------------- Block list + reassignment ----------------

    def _refresh_block_list(self):
        for i in self._block_tree.get_children():
            self._block_tree.delete(i)
        self._block_meta.clear()

        query = self._search_var.get().strip().lower() if hasattr(self, "_search_var") else ""
        in_search = bool(query)

        if in_search:
            self._list_title.configure(
                text=f"Search results across all tiers (matching '{query}')",
            )
        else:
            self._list_title.configure(
                text=f"Items in {_TIER_LABELS[self.tier]} tier",
            )

        shown = 0
        total_pool = 0
        for c in self.plan:
            # In search mode, look across every tier; otherwise only this one.
            if not in_search and c.tier != self.tier:
                continue
            total_pool += 1

            name = self._friendly_for(c.start_idx, c.end_idx)
            if in_search and query not in name.lower():
                # Also try matching the raw header so $type-> tags are findable.
                raw_header = self.app.lines[c.start_idx].rstrip("\n").lower()
                if query not in raw_header:
                    continue

            iid = str(c.start_idx)
            from_label = ""
            if c.base_tier is not None and c.base_tier != c.tier:
                from_label = f"was {_TIER_LABELS.get(c.base_tier, '?')}"
            self._block_tree.insert(
                "", "end", iid=iid,
                values=(
                    _truncate(name, 110),
                    _TIER_LABELS.get(c.tier, "?"),
                    from_label,
                    c.start_idx + 1,
                ),
            )
            self._block_meta[iid] = (c.signature, c.base_tier or c.tier)
            shown += 1

        if in_search:
            self._count_label.configure(
                text=f"{shown} match(es) out of {total_pool} items across all tiers"
            )
        else:
            self._count_label.configure(
                text=f"{shown} block(s) in this tier"
            )

    def _friendly_for(self, start_idx: int, end_idx: int) -> str:
        """Memoize friendly_block_name per block — cheap during typing."""
        cached = self._friendly_cache.get(start_idx)
        if cached is not None:
            return cached
        block_lines = self.app.lines[start_idx:end_idx]
        name = friendly_block_name(block_lines)
        self._friendly_cache[start_idx] = name
        return name

    def _on_block_right_click(self, evt):
        row = self._block_tree.identify_row(evt.y)
        if row:
            self._block_tree.selection_set(row)
            self._block_tree.focus(row)
            try:
                self._reassign_menu.tk_popup(evt.x_root, evt.y_root)
            finally:
                self._reassign_menu.grab_release()

    def _on_block_double_click(self, _evt):
        sel = self._block_tree.focus()
        if not sel:
            return
        # Position the menu under the row, roughly.
        x = self._block_tree.winfo_rootx() + 100
        y = self._block_tree.winfo_rooty() + 100
        self._reassign_menu.tk_popup(x, y)

    def _open_reassign_menu_for_selected(self):
        sel = self._block_tree.focus()
        if not sel:
            messagebox.showinfo("No block selected",
                                "Click a block in the list first.")
            return
        x = self._block_tree.winfo_rootx() + 60
        y = self._block_tree.winfo_rooty() + 60
        self._reassign_menu.tk_popup(x, y)

    def _reassign_selected(self, dest_tier: Optional[ValueTier]):
        sel = self._block_tree.focus()
        if not sel:
            return
        sig, base_tier = self._block_meta.get(sel, ("", None))
        if not sig:
            return
        existing = self.overrides.block_overrides.get(sig)
        if dest_tier is None:
            # Reset: drop the tier override; keep style override if any.
            if existing and existing.style is None:
                del self.overrides.block_overrides[sig]
            elif existing:
                existing.tier = None
            effective_tier = base_tier
        else:
            if existing:
                existing.tier = dest_tier
            else:
                self.overrides.block_overrides[sig] = BlockOverride(tier=dest_tier)
            effective_tier = dest_tier
        save_overrides(self.app.filter_path, self.overrides)

        # Keep the in-memory plan in sync so the list reflects the new tier
        # without a full re-plan. The signature lookup is exact.
        try:
            start_idx = int(sel)
        except ValueError:
            start_idx = -1
        for c in self.plan:
            if c.start_idx == start_idx:
                c.tier = effective_tier or c.tier
                c.has_override = (effective_tier is not None)
                break

        friendly = self._friendly_for(start_idx, start_idx + 1) if start_idx >= 0 else sig[:60]
        self.app._set_status(
            f"{friendly}  ->  {_TIER_LABELS.get(dest_tier, 'default')}"
        )
        # Re-render: in search mode the row stays (different tier column);
        # outside search mode the row disappears from this tier's list.
        self._refresh_block_list()

    # ---------------- Save / close ----------------

    def _save_and_close(self):
        # Persist the tier preset if it differs from the code default; otherwise
        # drop it so the user can get the default back automatically next time
        # we tweak the code defaults.
        default = EMPHASIS_PRESETS.get(self.tier)
        if default is not None and _styles_equal(self.draft_style, default):
            self.overrides.tier_presets.pop(self.tier, None)
        else:
            self.overrides.tier_presets[self.tier] = self.draft_style
        save_overrides(self.app.filter_path, self.overrides)
        self.app._set_status(f"Saved {_TIER_LABELS[self.tier]} tier styling.")
        self.dlg.destroy()
        self.on_close_cb()

    def _on_cancel(self):
        self.dlg.destroy()
        self.on_close_cb()

    @staticmethod
    def _clone_style(style: BlockStyle) -> BlockStyle:
        return BlockStyle(
            text_color=style.text_color,
            border_color=style.border_color,
            bg_color=style.bg_color,
            font_size=style.font_size,
            play_effect=style.play_effect,
            minimap=style.minimap,
        )


def _styles_equal(a: BlockStyle, b: BlockStyle) -> bool:
    return (
        a.text_color == b.text_color
        and a.border_color == b.border_color
        and a.bg_color == b.bg_color
        and a.font_size == b.font_size
        and a.play_effect == b.play_effect
        and a.minimap == b.minimap
    )


def _rgba_to_hex(rgba) -> str:
    return f"#{rgba[0]:02x}{rgba[1]:02x}{rgba[2]:02x}"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
