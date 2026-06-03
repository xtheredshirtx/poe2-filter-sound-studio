"""Smart Merge UI Integration for main application.

This module provides the UI components and logic for the smart merge feature,
designed to integrate with the existing CustomTkinter application.
"""

import customtkinter as ctk
from tkinter import filedialog, messagebox, ttk
import os
from datetime import datetime
from typing import List, Optional

from core.file_operations import load_filter_file
from core.parser import FilterParser
from features.smart_merge import (
    SimilarityScorer, MatchFinder, MigrationExecutor,
    parse_blocks_from_lines, create_match_summary
)


class SmartMergeController:
    """Controller for smart merge functionality.

    Handles the logic for loading filters, finding matches, and executing migration.
    """

    def __init__(self):
        self.old_filter_path = ""
        self.new_filter_path = ""
        self.old_lines = []
        self.new_lines = []
        self.old_blocks = []
        self.new_blocks = []
        self.matches = []

        self.scorer = SimilarityScorer()
        self.finder = MatchFinder(self.scorer)
        self.executor = MigrationExecutor()

    def load_old_filter(self, path: str) -> bool:
        """Load old season filter.

        Returns:
            True if successful, False otherwise
        """
        try:
            self.old_filter_path = path
            self.old_lines = load_filter_file(path)
            self.old_blocks = parse_blocks_from_lines(self.old_lines)
            return True
        except Exception as e:
            print(f"Error loading old filter: {e}")
            return False

    def load_new_filter(self, path: str) -> bool:
        """Load new season filter.

        Returns:
            True if successful, False otherwise
        """
        try:
            self.new_filter_path = path
            self.new_lines = load_filter_file(path)
            self.new_blocks = parse_blocks_from_lines(self.new_lines)
            return True
        except Exception as e:
            print(f"Error loading new filter: {e}")
            return False

    def find_matches(self, min_confidence: float = 0.5) -> int:
        """Find matches between loaded filters.

        Args:
            min_confidence: Minimum similarity threshold (0.0 to 1.0)

        Returns:
            Number of matches found
        """
        if not self.old_blocks or not self.new_blocks:
            return 0

        self.matches = self.finder.find_matches(
            self.old_blocks,
            self.new_blocks,
            min_confidence=min_confidence
        )

        return len(self.matches)

    def auto_approve_high_confidence(self, threshold: float = 0.9) -> int:
        """Automatically approve matches above threshold.

        Args:
            threshold: Confidence threshold (0.0 to 1.0)

        Returns:
            Number of matches approved
        """
        count = 0
        for match in self.matches:
            if match.confidence >= threshold and match.user_approved is None:
                match.user_approved = True
                count += 1
        return count

    def execute_merge(self) -> Optional[List[str]]:
        """Execute migration with approved matches.

        Returns:
            Merged filter lines, or None if error
        """
        try:
            merged_lines = self.executor.execute_migration(
                self.new_lines,
                self.matches,
                transfer_sounds=True,
                transfer_colors=False  # Future feature
            )
            return merged_lines
        except Exception as e:
            print(f"Error executing merge: {e}")
            return None

    def get_match_summary(self) -> str:
        """Get summary of current matches.

        Returns:
            Multi-line summary string
        """
        return create_match_summary(self.matches)

    def get_match_by_index(self, index: int):
        """Get match by index in matches list."""
        if 0 <= index < len(self.matches):
            return self.matches[index]
        return None


def enhance_merge_tab(merge_tab_frame, status_callback):
    """Enhance existing merge tab with smart merge functionality.

    This function adds smart merge UI elements to the existing merge tab.

    Args:
        merge_tab_frame: The CTkFrame for the merge tab
        status_callback: Function to call with status updates
    """
    controller = SmartMergeController()

    # State variables
    old_path_var = {"path": ""}
    new_path_var = {"path": ""}

    def set_status(text):
        """Update status via callback."""
        if status_callback:
            status_callback(text)

    def load_old():
        """Load old season filter."""
        path = filedialog.askopenfilename(
            title="Load Old Season Filter",
            filetypes=[("Filter Files", "*.filter")]
        )
        if not path:
            return

        if controller.load_old_filter(path):
            old_path_var["path"] = path
            old_label.configure(text=f"✓ {os.path.basename(path)}")
            set_status(f"Loaded old filter: {len(controller.old_blocks)} blocks")
            update_info()
        else:
            messagebox.showerror("Error", "Failed to load old filter")

    def load_new():
        """Load new season filter."""
        path = filedialog.askopenfilename(
            title="Load New Season Filter",
            filetypes=[("Filter Files", "*.filter")]
        )
        if not path:
            return

        if controller.load_new_filter(path):
            new_path_var["path"] = path
            new_label.configure(text=f"✓ {os.path.basename(path)}")
            set_status(f"Loaded new filter: {len(controller.new_blocks)} blocks")
            update_info()
        else:
            messagebox.showerror("Error", "Failed to load new filter")

    def find_matches():
        """Find matches between filters."""
        if not controller.old_blocks or not controller.new_blocks:
            messagebox.showwarning("Warning", "Please load both filters first")
            return

        set_status("Finding matches...")

        # Get minimum confidence from slider
        min_conf = confidence_slider.get() / 100.0

        count = controller.find_matches(min_confidence=min_conf)

        set_status(f"Found {count} potential matches")
        update_matches_table()
        update_info()

    def auto_approve():
        """Auto-approve high confidence matches."""
        if not controller.matches:
            messagebox.showwarning("Warning", "Find matches first")
            return

        count = controller.auto_approve_high_confidence(threshold=0.9)
        messagebox.showinfo("Auto-Approve", f"Approved {count} high-confidence matches (90%+)")
        update_matches_table()

    def execute():
        """Execute the migration."""
        if not controller.matches:
            messagebox.showwarning("Warning", "Find matches first")
            return

        approved_count = sum(1 for m in controller.matches if m.user_approved is True)
        if approved_count == 0:
            messagebox.showwarning("Warning", "No matches approved. Please review and approve matches.")
            return

        # Confirm
        result = messagebox.askyesno(
            "Execute Migration",
            f"Transfer sounds from {approved_count} approved matches to new filter?\n\n"
            f"This will create a new merged filter file."
        )

        if not result:
            return

        set_status("Executing migration...")

        merged_lines = controller.execute_merge()
        if not merged_lines:
            messagebox.showerror("Error", "Migration failed")
            return

        # Save merged filter
        old_base = os.path.splitext(os.path.basename(controller.old_filter_path))[0]
        new_base = os.path.splitext(os.path.basename(controller.new_filter_path))[0]
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        default_name = f"migrated_{old_base}_to_{new_base}_{ts}.filter"

        save_path = filedialog.asksaveasfilename(
            title="Save Migrated Filter",
            defaultextension=".filter",
            initialfile=default_name,
            filetypes=[("Filter Files", "*.filter")]
        )

        if not save_path:
            return

        try:
            with open(save_path, "w", encoding="utf-8") as f:
                f.writelines(merged_lines)

            messagebox.showinfo(
                "Migration Complete!",
                f"Successfully migrated {approved_count} sound customizations!\n\n"
                f"Saved to:\n{save_path}"
            )
            set_status(f"Migration complete • {approved_count} sounds transferred")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to save file:\n{e}")

    def update_info():
        """Update info label."""
        if not controller.old_blocks or not controller.new_blocks:
            info_label.configure(text="Load both filters to begin")
            return

        old_with_sounds = sum(1 for b in controller.old_blocks if b.sound_lines)

        if controller.matches:
            stats = controller.finder.get_statistics(controller.matches)
            info_text = (
                f"Old filter: {len(controller.old_blocks)} blocks ({old_with_sounds} with sounds)\n"
                f"New filter: {len(controller.new_blocks)} blocks\n"
                f"Matches found: {stats['total']} "
                f"(Exact: {stats['exact']}, High: {stats['high']}, Medium: {stats['medium']}, Low: {stats['low']})\n"
                f"Status: {stats['approved']} approved, {stats['rejected']} rejected, {stats['pending']} pending"
            )
        else:
            info_text = (
                f"Old filter: {len(controller.old_blocks)} blocks ({old_with_sounds} with sounds)\n"
                f"New filter: {len(controller.new_blocks)} blocks\n"
                f"Click 'Find Matches' to analyze"
            )

        info_label.configure(text=info_text)

    def update_matches_table():
        """Update matches table."""
        # Clear existing
        for item in matches_tree.get_children():
            matches_tree.delete(item)

        # Populate
        for idx, match in enumerate(controller.matches):
            status_icon = match.get_status_icon()
            confidence_pct = match.get_confidence_percentage()
            old_desc = f"{match.old_block.rarity} | {', '.join(match.old_block.class_values[:2])}"
            new_desc = f"{match.new_block.rarity} | {', '.join(match.new_block.class_values[:2])}"
            transfer = match.get_transfer_summary()

            # Color code by match type
            tag = match.match_type

            matches_tree.insert("", "end", values=(
                status_icon,
                f"{confidence_pct}%",
                match.match_type,
                old_desc,
                new_desc,
                transfer
            ), tags=(tag,))

    def on_match_select(event):
        """Handle match selection."""
        selection = matches_tree.selection()
        if not selection:
            return

        # Get selected index
        item = selection[0]
        idx = matches_tree.index(item)

        match = controller.get_match_by_index(idx)
        if not match:
            return

        # Show detailed info in text box
        breakdown = "\n".join([
            f"Confidence: {match.get_confidence_percentage()}% ({match.match_type})",
            f"",
            f"Score Breakdown:",
            f"  Rarity:   {match.score_breakdown.get('rarity', 0):.3f}",
            f"  Class:    {match.score_breakdown.get('class', 0):.3f}",
            f"  BaseType: {match.score_breakdown.get('basetype', 0):.3f}",
            f"  Context:  {match.score_breakdown.get('context', 0):.3f}",
            f"  Header:   {match.score_breakdown.get('header', 0):.3f}",
            f"",
            f"Old Block:",
            f"  {match.old_block.header}",
            f"  {match.old_block.rarity}",
            f"  Classes: {', '.join(match.old_block.class_values) if match.old_block.class_values else '(none)'}",
            f"  Sounds: {len(match.old_block.sound_lines)}",
            f"",
            f"New Block:",
            f"  {match.new_block.header}",
            f"  {match.new_block.rarity}",
            f"  Classes: {', '.join(match.new_block.class_values) if match.new_block.class_values else '(none)'}",
            f"  Sounds: {len(match.new_block.sound_lines)}",
        ])

        detail_text.delete("1.0", "end")
        detail_text.insert("1.0", breakdown)

    def approve_selected():
        """Approve selected match."""
        selection = matches_tree.selection()
        if not selection:
            return

        idx = matches_tree.index(selection[0])
        match = controller.get_match_by_index(idx)
        if match:
            match.user_approved = True
            update_matches_table()
            update_info()

    def reject_selected():
        """Reject selected match."""
        selection = matches_tree.selection()
        if not selection:
            return

        idx = matches_tree.index(selection[0])
        match = controller.get_match_by_index(idx)
        if match:
            match.user_approved = False
            update_matches_table()
            update_info()

    # Build UI
    main_container = ctk.CTkFrame(merge_tab_frame)
    main_container.pack(fill="both", expand=True, padx=10, pady=10)

    # Title
    title = ctk.CTkLabel(main_container, text="🔀 Smart Season Migration",
                        font=("Segoe UI", 18, "bold"))
    title.pack(pady=(0, 10))

    # File selection
    file_frame = ctk.CTkFrame(main_container)
    file_frame.pack(fill="x", pady=(0, 10))

    # Old filter
    old_row = ctk.CTkFrame(file_frame)
    old_row.pack(fill="x", pady=5)
    ctk.CTkButton(old_row, text="📂 Old Season Filter", width=180,
                 command=load_old).pack(side="left", padx=(10, 10))
    old_label = ctk.CTkLabel(old_row, text="No file loaded")
    old_label.pack(side="left")

    # New filter
    new_row = ctk.CTkFrame(file_frame)
    new_row.pack(fill="x", pady=5)
    ctk.CTkButton(new_row, text="📂 New Season Filter", width=180,
                 command=load_new).pack(side="left", padx=(10, 10))
    new_label = ctk.CTkLabel(new_row, text="No file loaded")
    new_label.pack(side="left")

    # Controls
    control_frame = ctk.CTkFrame(main_container)
    control_frame.pack(fill="x", pady=(0, 10))

    # Confidence slider
    slider_frame = ctk.CTkFrame(control_frame)
    slider_frame.pack(side="left", padx=10, pady=10)
    ctk.CTkLabel(slider_frame, text="Min Confidence:").pack(side="left", padx=(0, 5))
    confidence_slider = ctk.CTkSlider(slider_frame, from_=0, to=100, number_of_steps=20)
    confidence_slider.set(50)  # Default 50%
    confidence_slider.pack(side="left", padx=5)
    conf_label = ctk.CTkLabel(slider_frame, text="50%")
    conf_label.pack(side="left", padx=(5, 0))

    def update_conf_label(value):
        conf_label.configure(text=f"{int(value)}%")

    confidence_slider.configure(command=update_conf_label)

    # Buttons
    ctk.CTkButton(control_frame, text="🔍 Find Matches", width=140,
                 command=find_matches).pack(side="left", padx=5, pady=10)
    ctk.CTkButton(control_frame, text="✓ Auto-Approve 90%+", width=160,
                 command=auto_approve).pack(side="left", padx=5, pady=10)
    ctk.CTkButton(control_frame, text="🚀 Execute Migration", width=160,
                 command=execute, fg_color="green", hover_color="darkgreen").pack(side="left", padx=5, pady=10)

    # Info
    info_label = ctk.CTkLabel(main_container, text="Load both filters to begin",
                             justify="left", anchor="w")
    info_label.pack(fill="x", padx=10, pady=(0, 10))

    # Matches table
    table_frame = ctk.CTkFrame(main_container)
    table_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    # Style
    style = ttk.Style()
    style.configure("Matches.Treeview", rowheight=25)

    columns = ("status", "conf", "type", "old", "new", "transfer")
    matches_tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                               selectmode="browse", style="Matches.Treeview")

    matches_tree.heading("status", text="")
    matches_tree.heading("conf", text="Conf")
    matches_tree.heading("type", text="Type")
    matches_tree.heading("old", text="Old Block")
    matches_tree.heading("new", text="New Block")
    matches_tree.heading("transfer", text="Will Transfer")

    matches_tree.column("status", width=30)
    matches_tree.column("conf", width=60)
    matches_tree.column("type", width=80)
    matches_tree.column("old", width=250)
    matches_tree.column("new", width=250)
    matches_tree.column("transfer", width=150)

    # Color tags
    matches_tree.tag_configure("exact", background="#2d4a2d")
    matches_tree.tag_configure("high", background="#3a4a2d")
    matches_tree.tag_configure("medium", background="#4a4a2d")
    matches_tree.tag_configure("low", background="#4a2d2d")

    vsb = ttk.Scrollbar(table_frame, orient="vertical", command=matches_tree.yview)
    matches_tree.configure(yscroll=vsb.set)

    matches_tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")

    table_frame.grid_rowconfigure(0, weight=1)
    table_frame.grid_columnconfigure(0, weight=1)

    matches_tree.bind("<<TreeviewSelect>>", on_match_select)

    # Action buttons
    action_frame = ctk.CTkFrame(main_container)
    action_frame.pack(fill="x", pady=(0, 10))

    ctk.CTkButton(action_frame, text="✓ Approve Selected", width=140,
                 command=approve_selected).pack(side="left", padx=10)
    ctk.CTkButton(action_frame, text="✗ Reject Selected", width=140,
                 command=reject_selected).pack(side="left", padx=10)

    # Detail panel
    detail_frame = ctk.CTkFrame(main_container)
    detail_frame.pack(fill="x", pady=(0, 10))

    ctk.CTkLabel(detail_frame, text="Match Details:",
                font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=10, pady=(5, 0))

    detail_text = ctk.CTkTextbox(detail_frame, height=150, wrap="none")
    detail_text.pack(fill="x", padx=10, pady=5)

    return controller
