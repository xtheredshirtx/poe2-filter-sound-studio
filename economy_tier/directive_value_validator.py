"""Validate emitted filter directive values against PoE's allowed enums (A.4).

Used at template-load time so a typo in a template (``"Purpel"`` instead of
``"Purple"``) fails loudly with a precise message instead of producing a filter
the game client silently rejects. Pure functions, no I/O.
"""

from __future__ import annotations

from collections.abc import Sequence

# Allowed PoE 2 named colours for PlayEffect / MinimapIcon.
NAMED_COLORS = (
    "Red",
    "Green",
    "Blue",
    "Brown",
    "White",
    "Yellow",
    "Cyan",
    "Grey",
    "Orange",
    "Pink",
    "Purple",
)

# Allowed MinimapIcon shapes.
MINIMAP_SHAPES = (
    "Circle",
    "Diamond",
    "Hexagon",
    "Square",
    "Star",
    "Triangle",
    "Cross",
    "Moon",
    "Raindrop",
    "Kite",
    "Pentagon",
    "UpsideDownHouse",
)

MINIMAP_SIZES = (0, 1, 2)


def validate_rgba(value: Sequence[int]) -> list[str]:
    """Return a list of error messages for an RGBA colour (empty == valid)."""
    errors: list[str] = []
    if not isinstance(value, (list, tuple)) or len(value) not in (3, 4):
        return [f"colour must be 3 or 4 integers, got {value!r}"]
    for ch in value:
        if not isinstance(ch, int) or isinstance(ch, bool) or not (0 <= ch <= 255):
            errors.append(f"colour channel out of range 0-255: {ch!r}")
    return errors


def validate_font_size(value: int) -> list[str]:
    if not isinstance(value, int) or isinstance(value, bool):
        return [f"font_size must be an integer, got {value!r}"]
    if not (1 <= value <= 60):
        return [f"font_size out of range 1-60: {value}"]
    return []


def validate_play_effect(value: tuple[str, bool]) -> list[str]:
    if not isinstance(value, (list, tuple)) or len(value) < 1:
        return [f"play_effect must be [color, is_temp], got {value!r}"]
    color = value[0]
    if color not in NAMED_COLORS:
        return [f"play_effect colour {color!r} not in {', '.join(NAMED_COLORS)}"]
    return []


def validate_minimap(value: tuple[int, str, str]) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return [f"minimap must be [size, color, shape], got {value!r}"]
    size, color, shape = value
    if size not in MINIMAP_SIZES:
        errors.append(f"minimap size must be 0, 1 or 2, got {size!r}")
    if color not in NAMED_COLORS:
        errors.append(f"minimap colour {color!r} not in {', '.join(NAMED_COLORS)}")
    if shape not in MINIMAP_SHAPES:
        errors.append(f"minimap shape {shape!r} not in {', '.join(MINIMAP_SHAPES)}")
    return errors


__all__ = [
    "NAMED_COLORS",
    "MINIMAP_SHAPES",
    "MINIMAP_SIZES",
    "validate_rgba",
    "validate_font_size",
    "validate_play_effect",
    "validate_minimap",
]
