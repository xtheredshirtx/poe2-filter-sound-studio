"""
UI Dialogs Module - Color picker, item preview, and other dialogs
"""

import customtkinter as ctk
from tkinter import colorchooser
from typing import Optional, Tuple, Callable
from core.data_models import FilterBlock, ColorData


class ColorPickerDialog(ctk.CTkToplevel):
    """Dialog for picking RGBA colors with live preview."""

    def __init__(self, parent, title: str = "Pick Color",
                 initial_color: Optional[Tuple[int, int, int, int]] = None,
                 callback: Optional[Callable[[Tuple[int, int, int, int]], None]] = None):
        """
        Initialize color picker dialog.

        Args:
            parent: Parent window
            title: Dialog title
            initial_color: Initial RGBA color (r, g, b, a) or None for white
            callback: Function to call with selected color (r, g, b, a)
        """
        super().__init__(parent)
        self.title(title)
        self.geometry("450x350")
        self.resizable(False, False)

        # Make modal
        self.transient(parent)
        self.grab_set()

        self.callback = callback
        self.selected_color: Optional[Tuple[int, int, int, int]] = None

        # Initialize with default or provided color
        if initial_color:
            self.r, self.g, self.b, self.a = initial_color
        else:
            self.r, self.g, self.b, self.a = 255, 255, 255, 255

        self._build_ui()
        self._update_preview()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (self.winfo_width() // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")

    def _build_ui(self):
        """Build the dialog UI."""
        # Main container
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Color preview
        preview_label = ctk.CTkLabel(main_frame, text="Preview", font=("Arial", 12, "bold"))
        preview_label.pack(pady=(0, 5))

        self.preview_frame = ctk.CTkFrame(main_frame, width=400, height=80, corner_radius=8)
        self.preview_frame.pack(pady=(0, 20))
        self.preview_frame.pack_propagate(False)

        self.preview_text = ctk.CTkLabel(
            self.preview_frame,
            text="Sample Item Text",
            font=("Arial", 16, "bold")
        )
        self.preview_text.place(relx=0.5, rely=0.5, anchor="center")

        # RGB Color Picker Button
        rgb_frame = ctk.CTkFrame(main_frame)
        rgb_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(rgb_frame, text="RGB Color:", width=100, anchor="w").pack(side="left", padx=(0, 10))

        self.rgb_button = ctk.CTkButton(
            rgb_frame,
            text=f"RGB({self.r}, {self.g}, {self.b})",
            command=self._pick_rgb_color,
            width=200
        )
        self.rgb_button.pack(side="left")

        # Alpha Slider
        alpha_frame = ctk.CTkFrame(main_frame)
        alpha_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(alpha_frame, text="Opacity (Alpha):", width=100, anchor="w").pack(side="left", padx=(0, 10))

        self.alpha_slider = ctk.CTkSlider(
            alpha_frame,
            from_=0,
            to=255,
            number_of_steps=255,
            command=self._on_alpha_change,
            width=200
        )
        self.alpha_slider.set(self.a)
        self.alpha_slider.pack(side="left", padx=(0, 10))

        self.alpha_label = ctk.CTkLabel(alpha_frame, text=f"{self.a}", width=40)
        self.alpha_label.pack(side="left")

        # Current color values display
        values_frame = ctk.CTkFrame(main_frame)
        values_frame.pack(fill="x", pady=(10, 20))

        self.values_label = ctk.CTkLabel(
            values_frame,
            text=f"RGBA: ({self.r}, {self.g}, {self.b}, {self.a})",
            font=("Courier", 11)
        )
        self.values_label.pack()

        # Buttons
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill="x")

        ctk.CTkButton(
            button_frame,
            text="Cancel",
            command=self._on_cancel,
            width=100,
            fg_color="gray"
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            button_frame,
            text="Apply",
            command=self._on_apply,
            width=100
        ).pack(side="right", padx=5)

    def _pick_rgb_color(self):
        """Open tkinter color chooser for RGB selection."""
        # Convert current RGB to hex for initial color
        initial_hex = f"#{self.r:02X}{self.g:02X}{self.b:02X}"

        # Open color chooser
        color = colorchooser.askcolor(
            color=initial_hex,
            title="Choose RGB Color",
            parent=self
        )

        if color[0]:  # User selected a color
            self.r, self.g, self.b = int(color[0][0]), int(color[0][1]), int(color[0][2])
            self._update_preview()

    def _on_alpha_change(self, value):
        """Handle alpha slider change."""
        self.a = int(value)
        self._update_preview()

    def _update_preview(self):
        """Update the preview display with current color."""
        # Update RGB button text
        self.rgb_button.configure(text=f"RGB({self.r}, {self.g}, {self.b})")

        # Update alpha label
        self.alpha_label.configure(text=f"{self.a}")

        # Update values display
        self.values_label.configure(text=f"RGBA: ({self.r}, {self.g}, {self.b}, {self.a})")

        # Update preview background (simulate transparency over dark background)
        # Calculate blended color assuming dark background (30, 30, 30)
        bg_r, bg_g, bg_b = 30, 30, 30
        alpha_ratio = self.a / 255.0
        blended_r = int(self.r * alpha_ratio + bg_r * (1 - alpha_ratio))
        blended_g = int(self.g * alpha_ratio + bg_g * (1 - alpha_ratio))
        blended_b = int(self.b * alpha_ratio + bg_b * (1 - alpha_ratio))

        preview_hex = f"#{blended_r:02X}{blended_g:02X}{blended_b:02X}"
        self.preview_frame.configure(fg_color=preview_hex)

        # Set text color to contrast (white if dark, black if light)
        luminance = (0.299 * blended_r + 0.587 * blended_g + 0.114 * blended_b)
        text_color = "white" if luminance < 128 else "black"
        self.preview_text.configure(text_color=text_color)

    def _on_apply(self):
        """Apply the selected color."""
        self.selected_color = (self.r, self.g, self.b, self.a)
        if self.callback:
            self.callback(self.selected_color)
        self.destroy()

    def _on_cancel(self):
        """Cancel color selection."""
        self.selected_color = None
        self.destroy()

    def get_color(self) -> Optional[Tuple[int, int, int, int]]:
        """Get the selected color (blocking call)."""
        self.wait_window()
        return self.selected_color


class ItemPreviewDialog(ctk.CTkToplevel):
    """Dialog showing a simulated POE2 item with applied colors."""

    def __init__(self, parent, block: FilterBlock, title: str = "Item Preview"):
        """
        Initialize item preview dialog.

        Args:
            parent: Parent window
            block: FilterBlock to preview
            title: Dialog title
        """
        super().__init__(parent)
        self.title(title)
        self.geometry("500x400")
        self.resizable(False, False)

        self.transient(parent)
        self.grab_set()

        self.block = block
        self._build_ui()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (self.winfo_width() // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")

    def _build_ui(self):
        """Build the preview UI."""
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Title
        title_label = ctk.CTkLabel(
            main_frame,
            text="POE2 Item Preview",
            font=("Arial", 16, "bold")
        )
        title_label.pack(pady=(0, 10))

        # Description
        desc_label = ctk.CTkLabel(
            main_frame,
            text="This is how the item will appear in-game with your colors:",
            font=("Arial", 11)
        )
        desc_label.pack(pady=(0, 20))

        # Preview container (simulated game background)
        preview_container = ctk.CTkFrame(main_frame, fg_color="#1a1a1a", corner_radius=8)
        preview_container.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        # Item box with border
        colors = self.block.color_data if self.block.color_data else ColorData()

        # Get colors or use defaults
        text_rgba = colors.text_color or (200, 200, 200, 255)
        border_rgba = colors.border_color or (100, 100, 100, 255)
        bg_rgba = colors.bg_color or (0, 0, 0, 180)

        # Blend background with game background
        bg_alpha = bg_rgba[3] / 255.0
        bg_blended_r = int(bg_rgba[0] * bg_alpha + 26 * (1 - bg_alpha))
        bg_blended_g = int(bg_rgba[1] * bg_alpha + 26 * (1 - bg_alpha))
        bg_blended_b = int(bg_rgba[2] * bg_alpha + 26 * (1 - bg_alpha))
        bg_hex = f"#{bg_blended_r:02X}{bg_blended_g:02X}{bg_blended_b:02X}"

        # Blend border
        border_alpha = border_rgba[3] / 255.0
        border_blended_r = int(border_rgba[0] * border_alpha + 26 * (1 - border_alpha))
        border_blended_g = int(border_rgba[1] * border_alpha + 26 * (1 - border_alpha))
        border_blended_b = int(border_rgba[2] * border_alpha + 26 * (1 - border_alpha))
        border_hex = f"#{border_blended_r:02X}{border_blended_g:02X}{border_blended_b:02X}"

        # Create item frame with border simulation
        item_border_frame = ctk.CTkFrame(
            preview_container,
            fg_color=border_hex,
            corner_radius=4
        )
        item_border_frame.place(relx=0.5, rely=0.5, anchor="center")

        item_frame = ctk.CTkFrame(
            item_border_frame,
            fg_color=bg_hex,
            width=300,
            height=150,
            corner_radius=2
        )
        item_frame.pack(padx=3, pady=3)
        item_frame.pack_propagate(False)

        # Blend text color
        text_alpha = text_rgba[3] / 255.0
        text_blended_r = int(text_rgba[0] * text_alpha + bg_blended_r * (1 - text_alpha))
        text_blended_g = int(text_rgba[1] * text_alpha + bg_blended_g * (1 - text_alpha))
        text_blended_b = int(text_rgba[2] * text_alpha + bg_blended_b * (1 - text_alpha))
        text_hex = f"#{text_blended_r:02X}{text_blended_g:02X}{text_blended_b:02X}"

        # Item name (use rarity or class info)
        item_name = self.block.rarity or "Sample Item"
        if self.block.class_values:
            item_name = self.block.class_values[0]

        item_label = ctk.CTkLabel(
            item_frame,
            text=item_name,
            font=("Arial", 18, "bold"),
            text_color=text_hex
        )
        item_label.place(relx=0.5, rely=0.5, anchor="center")

        # Color info
        info_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        info_frame.pack(fill="x")

        info_text = f"Text: RGBA{text_rgba}\nBorder: RGBA{border_rgba}\nBackground: RGBA{bg_rgba}"
        ctk.CTkLabel(
            info_frame,
            text=info_text,
            font=("Courier", 10),
            justify="left"
        ).pack(pady=5)

        # Close button
        ctk.CTkButton(
            main_frame,
            text="Close",
            command=self.destroy,
            width=100
        ).pack(pady=(10, 0))


class ConfirmDialog(ctk.CTkToplevel):
    """Simple confirmation dialog."""

    def __init__(self, parent, title: str, message: str, confirm_text: str = "Confirm", cancel_text: str = "Cancel"):
        """
        Initialize confirmation dialog.

        Args:
            parent: Parent window
            title: Dialog title
            message: Message to display
            confirm_text: Text for confirm button
            cancel_text: Text for cancel button
        """
        super().__init__(parent)
        self.title(title)
        self.geometry("400x200")
        self.resizable(False, False)

        self.transient(parent)
        self.grab_set()

        self.result = False

        # Main frame
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Message
        message_label = ctk.CTkLabel(
            main_frame,
            text=message,
            font=("Arial", 12),
            wraplength=350,
            justify="center"
        )
        message_label.pack(expand=True, pady=20)

        # Buttons
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkButton(
            button_frame,
            text=cancel_text,
            command=self._on_cancel,
            width=120,
            fg_color="gray"
        ).pack(side="left", padx=10, expand=True)

        ctk.CTkButton(
            button_frame,
            text=confirm_text,
            command=self._on_confirm,
            width=120
        ).pack(side="right", padx=10, expand=True)

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (self.winfo_width() // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")

    def _on_confirm(self):
        """Handle confirm button."""
        self.result = True
        self.destroy()

    def _on_cancel(self):
        """Handle cancel button."""
        self.result = False
        self.destroy()

    def get_result(self) -> bool:
        """Get the dialog result (blocking call)."""
        self.wait_window()
        return self.result
