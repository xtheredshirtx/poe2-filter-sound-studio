"""Filter parsing module for POE2 item filters.

This module handles all parsing of .filter files, including:
- Sound commands (CustomAlertSound, PlayAlertSound)
- Color commands (SetTextColor, SetBorderColor, SetBackgroundColor)
- Filter blocks (Show/Hide sections)
- Item criteria (Rarity, Class, BaseType, etc.)
"""

import re
from typing import List, Optional, Tuple, Dict, Any
from core.data_models import FilterBlock, ColorData


# ==================== Regex Patterns ====================

# Sound patterns
SOUND_RE_CUSTOM = re.compile(
    r'^(#\s*)?(CustomAlertSound|CustomAlertSoundOptional)\s+"([^"]+)"\s*(\d+)?',
    re.IGNORECASE
)

SOUND_RE_PLAY = re.compile(
    r'^(#\s*)?(PlayAlertSoundPositional|PlayAlertSound)\s+(\S+)(?:\s+(\d+))?',
    re.IGNORECASE
)

# Color patterns
COLOR_PATTERNS = {
    "text": re.compile(
        r'^(\s*)(SetTextColor)\s+(\d+)\s+(\d+)\s+(\d+)(?:\s+(\d+))?',
        re.IGNORECASE
    ),
    "border": re.compile(
        r'^(\s*)(SetBorderColor)\s+(\d+)\s+(\d+)\s+(\d+)(?:\s+(\d+))?',
        re.IGNORECASE
    ),
    "background": re.compile(
        r'^(\s*)(SetBackgroundColor)\s+(\d+)\s+(\d+)\s+(\d+)(?:\s+(\d+))?',
        re.IGNORECASE
    ),
}

# Block header pattern
SHOWHIDE_PATTERN = re.compile(r'^(Show|Hide)\s*', re.IGNORECASE)

# Section header: matches the filter's "# [[NNNN]] Title" markers (NeverSink/FilterBlade convention)
SECTION_RE = re.compile(r'^#\s*\[\[(\d+)\]\]\s*(.+?)\s*$')

# Subsection header: matches "#   [NNNN] Title" (single brackets, indented). Will NOT match SECTION_RE lines
# because \[\d+\] requires a digit immediately after the bracket; SECTION_RE has "[[" so the inner char is "[".
SUBSECTION_RE = re.compile(r'^#\s+\[(\d+)\]\s+(.+?)\s*$')

# FilterBlade-style block tags found inside the Show/Hide line's trailing comment, e.g.:
#   Show # %D7 $type->gold $tier->stack3 !gold_pilehuge
TYPE_TAG_RE = re.compile(r'\$type->(\S+)')
TIER_TAG_RE = re.compile(r'\$tier->(\S+)')
STYLE_TAG_RE = re.compile(r'!(\S+)')

# Item criteria patterns
CLASS_PATTERN = re.compile(r'^Class\s+(.+)', re.IGNORECASE)
BASETYPE_PATTERN = re.compile(r'^BaseType\s+(.+)', re.IGNORECASE)
RARITY_PATTERN = re.compile(r'^Rarity\s+(.+)', re.IGNORECASE)


# ==================== Parsing Functions ====================

class FilterParser:
    """Parser for POE2 filter files."""

    def __init__(self):
        self.lines: List[str] = []
        self.blocks: List[FilterBlock] = []

    def parse_file(self, lines: List[str]) -> List[FilterBlock]:
        """Parse a complete filter file into FilterBlock objects.

        Args:
            lines: List of lines from the filter file

        Returns:
            List of FilterBlock objects
        """
        self.lines = lines
        self.blocks = []

        current_block_lines = []
        start_idx = 0

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Check if this is a Show/Hide header
            if SHOWHIDE_PATTERN.match(stripped):
                # Process previous block if exists
                if current_block_lines:
                    block = self.parse_block(current_block_lines, start_idx)
                    if block:
                        self.blocks.append(block)

                # Start new block
                current_block_lines = [stripped]
                start_idx = i
            elif current_block_lines:
                # Add line to current block
                current_block_lines.append(stripped)

        # Process last block
        if current_block_lines:
            block = self.parse_block(current_block_lines, start_idx)
            if block:
                self.blocks.append(block)

        return self.blocks

    def parse_block(self, block_lines: List[str], start_idx: int) -> Optional[FilterBlock]:
        """Parse a single Show/Hide block.

        Args:
            block_lines: List of stripped lines in the block
            start_idx: Starting line index in original file

        Returns:
            FilterBlock object or None if invalid
        """
        if not block_lines:
            return None

        header = block_lines[0]
        end_idx = start_idx + len(block_lines)

        # Parse metadata
        rarity, class_values, basetype_values, context_lines = self._parse_criteria(block_lines)

        # Parse sounds
        sound_lines = self._parse_sounds(block_lines)

        # Parse colors
        color_data = self._parse_colors(block_lines)

        # Parse effects and minimap
        effect = self._find_line_starting_with(block_lines, "PlayEffect")
        minimap = self._find_line_starting_with(block_lines, "MinimapIcon")

        return FilterBlock(
            header=header,
            start_idx=start_idx,
            end_idx=end_idx,
            rarity=rarity,
            class_values=class_values,
            basetype_values=basetype_values,
            context_lines=context_lines,
            sound_lines=sound_lines,
            color_data=color_data,
            effect=effect,
            minimap=minimap,
        )

    def _parse_criteria(self, block_lines: List[str]) -> Tuple[str, List[str], List[str], List[str]]:
        """Parse filter criteria from block lines.

        Returns:
            Tuple of (rarity, class_values, basetype_values, context_lines)
        """
        # No Rarity line in the block = it matches every rarity (currency,
        # waystones, etc.). The old "Unknown" string read as if data were missing.
        rarity = "Any rarity"
        class_values = []
        basetype_values = []
        context_lines = []

        # Important criteria keywords
        CRITERIA_KEYS = (
            "ItemLevel", "DropLevel", "Sockets", "GemLevel", "HasInfluence",
            "BaseDefencePercentile", "Corrupted", "StackSize", "AreaLevel",
            "AnyEnchantment", "HasExplicitMod", "Quality", "SocketGroup",
            "Height", "Width", "LinkedSockets"
        )

        # Visual setting keywords (include in context)
        SETTING_KEYS = ("SetFontSize",)

        for line in block_lines[1:]:  # Skip header
            # Parse Rarity
            match = RARITY_PATTERN.match(line)
            if match:
                rarity = f"Rarity {match.group(1)}"
                context_lines.append(line)
                continue

            # Parse Class
            match = CLASS_PATTERN.match(line)
            if match:
                # Class can have multiple quoted values
                values_str = match.group(1)
                class_values.extend(self._extract_quoted_values(values_str))
                context_lines.append(line)
                continue

            # Parse BaseType
            match = BASETYPE_PATTERN.match(line)
            if match:
                # BaseType can have multiple quoted values
                values_str = match.group(1)
                basetype_values.extend(self._extract_quoted_values(values_str))
                context_lines.append(line)
                continue

            # Other criteria
            if line.startswith(CRITERIA_KEYS) or line.startswith(SETTING_KEYS):
                context_lines.append(line)

        return rarity, class_values, basetype_values, context_lines

    def _extract_quoted_values(self, text: str) -> List[str]:
        """Extract all quoted values from a string.

        Example: '"Ring" "Amulet"' -> ["Ring", "Amulet"]
        """
        pattern = re.compile(r'"([^"]+)"')
        return pattern.findall(text)

    def _parse_sounds(self, block_lines: List[str]) -> List[str]:
        """Extract sound lines from block."""
        sounds = []

        for line in block_lines:
            if SOUND_RE_CUSTOM.match(line) or SOUND_RE_PLAY.match(line):
                sounds.append(line)

        return sounds

    def _parse_colors(self, block_lines: List[str]) -> Optional[ColorData]:
        """Parse color information from block lines.

        Returns:
            ColorData object or None if no colors found
        """
        text_color = None
        border_color = None
        bg_color = None
        text_line = ""
        border_line = ""
        bg_line = ""

        for line in block_lines:
            # Try each color pattern
            for color_type, pattern in COLOR_PATTERNS.items():
                match = pattern.match(line)
                if match:
                    indent, keyword, r, g, b, a = match.groups()
                    r, g, b = int(r), int(g), int(b)
                    a = int(a) if a else 255  # Default alpha

                    rgba = (r, g, b, a)

                    if color_type == "text":
                        text_color = rgba
                        text_line = line
                    elif color_type == "border":
                        border_color = rgba
                        border_line = line
                    elif color_type == "background":
                        bg_color = rgba
                        bg_line = line

        # Only create ColorData if at least one color was found
        if text_color or border_color or bg_color:
            return ColorData(
                text_color=text_color,
                border_color=border_color,
                bg_color=bg_color,
                text_line=text_line,
                border_line=border_line,
                bg_line=bg_line,
            )

        return None

    def _find_line_starting_with(self, block_lines: List[str], prefix: str) -> str:
        """Find first line starting with given prefix."""
        for line in block_lines:
            if line.startswith(prefix):
                return line.replace("\t", "").strip()
        return ""


# ==================== Helper Functions ====================

def parse_color_line(line: str) -> Optional[Tuple[str, Tuple[int, int, int, int]]]:
    """Parse a single color line.

    Args:
        line: Line from filter file

    Returns:
        Tuple of (color_type, (R,G,B,A)) or None if not a color line
    """
    for color_type, pattern in COLOR_PATTERNS.items():
        match = pattern.match(line)
        if match:
            indent, keyword, r, g, b, a = match.groups()
            r, g, b = int(r), int(g), int(b)
            a = int(a) if a else 255
            return (color_type, (r, g, b, a))
    return None


def format_color_line(color_type: str, rgba: Tuple[int, int, int, int], indent: str = "\t") -> str:
    """Format a color tuple into a filter line.

    Args:
        color_type: "text", "border", or "background"
        rgba: (R, G, B, A) tuple
        indent: Indentation string

    Returns:
        Formatted filter line
    """
    keyword_map = {
        "text": "SetTextColor",
        "border": "SetBorderColor",
        "background": "SetBackgroundColor",
    }

    keyword = keyword_map.get(color_type)
    if not keyword:
        raise ValueError(f"Invalid color_type: {color_type}")

    r, g, b, a = rgba
    return f"{indent}{keyword} {r} {g} {b} {a}\n"


def validate_color_component(value: int) -> bool:
    """Validate that a color component is in valid range (0-255)."""
    return 0 <= value <= 255


def validate_rgba(rgba: Tuple[int, int, int, int]) -> bool:
    """Validate that all RGBA components are in valid range."""
    return all(validate_color_component(v) for v in rgba)
