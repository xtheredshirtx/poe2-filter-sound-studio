"""
Color Editor Module - Manage filter block colors
Provides ColorManager for applying, getting, and validating colors on filter blocks.
"""

from typing import Tuple, Optional, List
from core.data_models import FilterBlock, ColorData
import re


class ColorManager:
    """Manages color operations on filter blocks."""

    @staticmethod
    def validate_rgba(r: int, g: int, b: int, a: int = 255) -> bool:
        """Validate RGBA values are in valid range (0-255)."""
        return all(0 <= val <= 255 for val in [r, g, b, a])

    @staticmethod
    def format_color_line(color_type: str, r: int, g: int, b: int, a: int = 255, indent: str = "    ") -> str:
        """
        Format a color line for insertion into a filter.

        Args:
            color_type: "text", "border", or "background"
            r, g, b, a: RGBA values (0-255)
            indent: Indentation string (default 4 spaces)

        Returns:
            Formatted color line
        """
        type_map = {
            "text": "SetTextColor",
            "border": "SetBorderColor",
            "background": "SetBackgroundColor"
        }

        if color_type not in type_map:
            raise ValueError(f"Invalid color_type: {color_type}")

        command = type_map[color_type]

        # Only include alpha if it's not 255 (fully opaque)
        if a == 255:
            return f"{indent}{command} {r} {g} {b}\n"
        else:
            return f"{indent}{command} {r} {g} {b} {a}\n"

    @staticmethod
    def detect_indent(lines: List[str], start_idx: int, end_idx: int) -> str:
        """
        Detect the indentation style used in a block.

        Args:
            lines: Filter file lines
            start_idx: Block start index
            end_idx: Block end index (exclusive)

        Returns:
            Indentation string (e.g., "    " or "\t")
        """
        # Look for any indented line in the block
        for i in range(start_idx + 1, end_idx):
            line = lines[i]
            if line and line[0] in (' ', '\t'):
                # Extract leading whitespace
                match = re.match(r'^(\s+)', line)
                if match:
                    return match.group(1)

        # Default to 4 spaces if no indentation found
        return "    "

    @staticmethod
    def apply_text_color(lines: List[str], block: FilterBlock, r: int, g: int, b: int, a: int = 255) -> List[str]:
        """
        Apply text color to a filter block.

        Args:
            lines: Filter file lines (will be modified)
            block: FilterBlock to modify
            r, g, b, a: RGBA values

        Returns:
            Modified lines list
        """
        if not ColorManager.validate_rgba(r, g, b, a):
            raise ValueError(f"Invalid RGBA values: {r}, {g}, {b}, {a}")

        indent = ColorManager.detect_indent(lines, block.start_idx, block.end_idx)
        new_color_line = ColorManager.format_color_line("text", r, g, b, a, indent)

        # Find existing SetTextColor line
        text_line_idx = None
        for i in range(block.start_idx + 1, block.end_idx):
            if re.match(r'^\s*SetTextColor\s+', lines[i], re.IGNORECASE):
                text_line_idx = i
                break

        if text_line_idx is not None:
            # Replace existing line
            lines[text_line_idx] = new_color_line
        else:
            # Insert before the end of the block
            lines.insert(block.end_idx, new_color_line)
            # Update block end_idx since we inserted a line
            block.end_idx += 1

        return lines

    @staticmethod
    def apply_border_color(lines: List[str], block: FilterBlock, r: int, g: int, b: int, a: int = 255) -> List[str]:
        """Apply border color to a filter block."""
        if not ColorManager.validate_rgba(r, g, b, a):
            raise ValueError(f"Invalid RGBA values: {r}, {g}, {b}, {a}")

        indent = ColorManager.detect_indent(lines, block.start_idx, block.end_idx)
        new_color_line = ColorManager.format_color_line("border", r, g, b, a, indent)

        # Find existing SetBorderColor line
        border_line_idx = None
        for i in range(block.start_idx + 1, block.end_idx):
            if re.match(r'^\s*SetBorderColor\s+', lines[i], re.IGNORECASE):
                border_line_idx = i
                break

        if border_line_idx is not None:
            lines[border_line_idx] = new_color_line
        else:
            lines.insert(block.end_idx, new_color_line)
            block.end_idx += 1

        return lines

    @staticmethod
    def apply_background_color(lines: List[str], block: FilterBlock, r: int, g: int, b: int, a: int = 255) -> List[str]:
        """Apply background color to a filter block."""
        if not ColorManager.validate_rgba(r, g, b, a):
            raise ValueError(f"Invalid RGBA values: {r}, {g}, {b}, {a}")

        indent = ColorManager.detect_indent(lines, block.start_idx, block.end_idx)
        new_color_line = ColorManager.format_color_line("background", r, g, b, a, indent)

        # Find existing SetBackgroundColor line
        bg_line_idx = None
        for i in range(block.start_idx + 1, block.end_idx):
            if re.match(r'^\s*SetBackgroundColor\s+', lines[i], re.IGNORECASE):
                bg_line_idx = i
                break

        if bg_line_idx is not None:
            lines[bg_line_idx] = new_color_line
        else:
            lines.insert(block.end_idx, new_color_line)
            block.end_idx += 1

        return lines

    @staticmethod
    def apply_all_colors(lines: List[str], block: FilterBlock,
                        text_rgba: Optional[Tuple[int, int, int, int]] = None,
                        border_rgba: Optional[Tuple[int, int, int, int]] = None,
                        bg_rgba: Optional[Tuple[int, int, int, int]] = None) -> List[str]:
        """
        Apply multiple colors at once to a filter block.

        Args:
            lines: Filter file lines
            block: FilterBlock to modify
            text_rgba: (r, g, b, a) for text color, or None to skip
            border_rgba: (r, g, b, a) for border color, or None to skip
            bg_rgba: (r, g, b, a) for background color, or None to skip

        Returns:
            Modified lines list
        """
        if text_rgba:
            ColorManager.apply_text_color(lines, block, *text_rgba)

        if border_rgba:
            ColorManager.apply_border_color(lines, block, *border_rgba)

        if bg_rgba:
            ColorManager.apply_background_color(lines, block, *bg_rgba)

        return lines

    @staticmethod
    def get_colors(block: FilterBlock) -> ColorData:
        """
        Extract current colors from a filter block.

        Args:
            block: FilterBlock to read colors from

        Returns:
            ColorData with current colors (may have None values if colors not set)
        """
        if block.color_data:
            return block.color_data
        else:
            # Return empty ColorData if no colors set
            return ColorData()

    @staticmethod
    def remove_text_color(lines: List[str], block: FilterBlock) -> List[str]:
        """Remove SetTextColor line from a block."""
        for i in range(block.start_idx + 1, block.end_idx):
            if re.match(r'^\s*SetTextColor\s+', lines[i], re.IGNORECASE):
                del lines[i]
                block.end_idx -= 1
                break
        return lines

    @staticmethod
    def remove_border_color(lines: List[str], block: FilterBlock) -> List[str]:
        """Remove SetBorderColor line from a block."""
        for i in range(block.start_idx + 1, block.end_idx):
            if re.match(r'^\s*SetBorderColor\s+', lines[i], re.IGNORECASE):
                del lines[i]
                block.end_idx -= 1
                break
        return lines

    @staticmethod
    def remove_background_color(lines: List[str], block: FilterBlock) -> List[str]:
        """Remove SetBackgroundColor line from a block."""
        for i in range(block.start_idx + 1, block.end_idx):
            if re.match(r'^\s*SetBackgroundColor\s+', lines[i], re.IGNORECASE):
                del lines[i]
                block.end_idx -= 1
                break
        return lines

    @staticmethod
    def copy_colors(source_block: FilterBlock, target_block: FilterBlock, lines: List[str]) -> List[str]:
        """
        Copy all colors from source block to target block.

        Args:
            source_block: Block to copy colors from
            target_block: Block to apply colors to
            lines: Filter file lines

        Returns:
            Modified lines list
        """
        source_colors = ColorManager.get_colors(source_block)

        if source_colors.text_color:
            ColorManager.apply_text_color(lines, target_block, *source_colors.text_color)

        if source_colors.border_color:
            ColorManager.apply_border_color(lines, target_block, *source_colors.border_color)

        if source_colors.bg_color:
            ColorManager.apply_background_color(lines, target_block, *source_colors.bg_color)

        return lines

    @staticmethod
    def has_any_color(block: FilterBlock) -> bool:
        """Check if a block has any color set."""
        if not block.color_data:
            return False
        return any([
            block.color_data.text_color,
            block.color_data.border_color,
            block.color_data.bg_color
        ])

    @staticmethod
    def rgb_to_hex(r: int, g: int, b: int) -> str:
        """Convert RGB to hex color string (e.g., '#FF0000')."""
        return f"#{r:02X}{g:02X}{b:02X}"

    @staticmethod
    def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
        """
        Convert hex color string to RGB tuple.

        Args:
            hex_color: Hex string like '#FF0000' or 'FF0000'

        Returns:
            (r, g, b) tuple
        """
        hex_color = hex_color.lstrip('#')
        if len(hex_color) != 6:
            raise ValueError(f"Invalid hex color: {hex_color}")

        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)

        return (r, g, b)


class ColorClipboard:
    """Clipboard for copying/pasting colors between blocks."""

    def __init__(self):
        self.text_color: Optional[Tuple[int, int, int, int]] = None
        self.border_color: Optional[Tuple[int, int, int, int]] = None
        self.bg_color: Optional[Tuple[int, int, int, int]] = None

    def copy_from_block(self, block: FilterBlock):
        """Copy colors from a block to clipboard."""
        colors = ColorManager.get_colors(block)
        self.text_color = colors.text_color
        self.border_color = colors.border_color
        self.bg_color = colors.bg_color

    def paste_to_block(self, block: FilterBlock, lines: List[str]) -> List[str]:
        """Paste clipboard colors to a block."""
        return ColorManager.apply_all_colors(
            lines, block,
            text_rgba=self.text_color,
            border_rgba=self.border_color,
            bg_rgba=self.bg_color
        )

    def has_colors(self) -> bool:
        """Check if clipboard has any colors."""
        return any([self.text_color, self.border_color, self.bg_color])

    def clear(self):
        """Clear clipboard."""
        self.text_color = None
        self.border_color = None
        self.bg_color = None
