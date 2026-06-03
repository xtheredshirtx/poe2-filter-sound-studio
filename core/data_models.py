"""Data models for POE2 Item Filter components.

This module defines the core data structures used throughout the application:
- FilterBlock: Represents a complete Show/Hide block from a filter file
- ColorData: Parsed RGBA color information
- SimilarityMatch: Potential matches between old and new season filters
- ColorTemplate: Reusable color schemes
"""

from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime


@dataclass
class ColorData:
    """Parsed color information from a filter block.

    Stores RGBA colors (0-255 for each component) and preserves original
    filter lines for accurate reconstruction.
    """
    text_color: Optional[Tuple[int, int, int, int]] = None    # RGBA
    border_color: Optional[Tuple[int, int, int, int]] = None  # RGBA
    bg_color: Optional[Tuple[int, int, int, int]] = None      # RGBA

    # Original lines from filter file (for preservation during edits)
    text_line: str = ""
    border_line: str = ""
    bg_line: str = ""

    def has_any_color(self) -> bool:
        """Check if any color is defined."""
        return any([self.text_color, self.border_color, self.bg_color])

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "text_color": list(self.text_color) if self.text_color else None,
            "border_color": list(self.border_color) if self.border_color else None,
            "bg_color": list(self.bg_color) if self.bg_color else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ColorData':
        """Create ColorData from dictionary."""
        return cls(
            text_color=tuple(data["text_color"]) if data.get("text_color") else None,
            border_color=tuple(data["border_color"]) if data.get("border_color") else None,
            bg_color=tuple(data["bg_color"]) if data.get("bg_color") else None,
        )


@dataclass
class FilterBlock:
    """Represents a single Show/Hide block in a POE2 filter file.

    Contains all parsed information about a filter block including criteria,
    sounds, colors, and visual effects.
    """
    # Block identification
    header: str                      # "Show" or "Hide"
    start_idx: int                   # Line index in original file
    end_idx: int                     # Exclusive end index

    # Filter criteria
    rarity: str                      # e.g., "Rarity Unique"
    class_values: List[str] = field(default_factory=list)      # ["Ring", "Amulet"]
    basetype_values: List[str] = field(default_factory=list)   # ["Leather Belt"]
    context_lines: List[str] = field(default_factory=list)     # Other criteria lines

    # Audio
    sound_lines: List[str] = field(default_factory=list)       # CustomAlertSound/PlayAlertSound

    # Visual
    color_data: Optional[ColorData] = None
    effect: str = ""                 # PlayEffect line
    minimap: str = ""                # MinimapIcon line

    # Original data (for backward compatibility with existing code)
    orig_data: Optional[Dict[str, Any]] = None

    def get_signature(self) -> str:
        """Generate a signature for block matching.

        Used by smart merge to identify similar blocks across season updates.
        """
        parts = [self.header, self.rarity]
        if self.class_values:
            parts.extend(sorted(self.class_values))
        if self.basetype_values:
            parts.extend(sorted(self.basetype_values))
        return " || ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "header": self.header,
            "start_idx": self.start_idx,
            "end_idx": self.end_idx,
            "rarity": self.rarity,
            "class_values": self.class_values,
            "basetype_values": self.basetype_values,
            "context_lines": self.context_lines,
            "sound_lines": self.sound_lines,
            "color_data": self.color_data.to_dict() if self.color_data else None,
            "effect": self.effect,
            "minimap": self.minimap,
        }


@dataclass
class SimilarityMatch:
    """Represents a potential match between old and new season filter blocks.

    Used by smart merge feature to suggest sound/color transfers between
    filter versions.
    """
    old_block: FilterBlock
    new_block: FilterBlock
    confidence: float                              # 0.0 to 1.0
    score_breakdown: Dict[str, float]              # Component scores
    match_type: str                                # "exact", "high", "medium", "low"
    user_approved: Optional[bool] = None           # None=pending, True/False=decided
    manual_mapping: bool = False                   # User manually created this match

    def get_confidence_percentage(self) -> int:
        """Get confidence as percentage (0-100)."""
        return int(self.confidence * 100)

    def get_status_icon(self) -> str:
        """Get status icon for UI display."""
        if self.user_approved is True:
            return "✓"
        elif self.user_approved is False:
            return "✗"
        elif self.manual_mapping:
            return "👤"
        else:
            return "?"

    def get_transfer_summary(self) -> str:
        """Get summary of what will be transferred."""
        transfers = []

        if self.old_block.sound_lines:
            transfers.append("Sound")

        if self.old_block.color_data and self.old_block.color_data.has_any_color():
            transfers.append("Colors")

        if self.old_block.effect:
            transfers.append("Effect")

        if self.old_block.minimap:
            transfers.append("Minimap")

        return " + ".join(transfers) if transfers else "(nothing to transfer)"


@dataclass
class ColorTemplate:
    """Reusable color scheme for bulk application.

    Allows users to save and reuse favorite color combinations across
    different items and filters.
    """
    name: str
    description: str
    text_color: Tuple[int, int, int, int]      # RGBA
    border_color: Tuple[int, int, int, int]    # RGBA
    bg_color: Tuple[int, int, int, int]        # RGBA
    tags: List[str] = field(default_factory=list)
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    author: str = "user"

    def as_color_data(self) -> ColorData:
        """Convert template to ColorData for application."""
        return ColorData(
            text_color=self.text_color,
            border_color=self.border_color,
            bg_color=self.bg_color
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "text_color": list(self.text_color),
            "border_color": list(self.border_color),
            "bg_color": list(self.bg_color),
            "tags": self.tags,
            "created": self.created,
            "author": self.author,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ColorTemplate':
        """Create ColorTemplate from dictionary."""
        return cls(
            name=data["name"],
            description=data["description"],
            text_color=tuple(data["text_color"]),
            border_color=tuple(data["border_color"]),
            bg_color=tuple(data["bg_color"]),
            tags=data.get("tags", []),
            created=data.get("created", datetime.now().isoformat()),
            author=data.get("author", "user"),
        )


# Default color templates
DEFAULT_TEMPLATES = [
    ColorTemplate(
        name="Unique Items - Gold",
        description="Bright gold scheme for unique items",
        text_color=(255, 255, 0, 255),
        border_color=(180, 90, 45, 255),
        bg_color=(30, 20, 0, 200),
        tags=["unique", "gold", "default"],
    ),
    ColorTemplate(
        name="Currency - Green",
        description="Vibrant green for currency items",
        text_color=(0, 255, 100, 255),
        border_color=(0, 200, 80, 255),
        bg_color=(0, 20, 10, 180),
        tags=["currency", "green", "default"],
    ),
    ColorTemplate(
        name="Rare Items - Blue Electric",
        description="Electric blue scheme for rare items",
        text_color=(100, 200, 255, 255),
        border_color=(50, 100, 255, 255),
        bg_color=(0, 10, 30, 200),
        tags=["rare", "blue", "default"],
    ),
    ColorTemplate(
        name="Maps - Purple Glow",
        description="Purple glowing scheme for maps",
        text_color=(200, 100, 255, 255),
        border_color=(150, 50, 200, 255),
        bg_color=(20, 0, 30, 200),
        tags=["maps", "purple", "default"],
    ),
]
