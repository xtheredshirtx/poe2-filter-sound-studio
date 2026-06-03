"""Visual emphasis + randomization for POE2 item filters.

Two features built on the same primitives:

  1. EmphasisStyler — read each Show/Hide block, classify its value tier from
     signals already in the filter (Show/Hide header, $tier-> tag, section
     name), and apply a preset style so high-tier items POP and low-tier items
     fade. Deterministic — same input always produces the same output.

  2. RandomizerStyler — assign a curated, legibility-checked palette to each
     visible block. Seeded so the same filter + same seed = same result.

Both styles touch ONLY visual lines inside Show/Hide blocks:
  SetTextColor, SetBorderColor, SetBackgroundColor, SetFontSize,
  PlayEffect, MinimapIcon

We never touch Show/Hide headers, Class/BaseType/Rarity conditions, or sound
commands. That guarantees the filter still matches the same items — only the
on-screen presentation changes.
"""

from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Tuple


# ==================== Tier classification ====================

class ValueTier(IntEnum):
    """Heuristic value tier inferred from filter annotations.

    Higher = more valuable. HIDDEN is a sentinel for Hide blocks; we never
    re-style them so the filter author's intent is preserved.
    """
    HIDDEN = -1
    JUNK = 0
    LOW = 1
    MID = 2
    HIGH = 3
    TOP = 4
    MYTHIC = 5


# Keyword signals in section names. Order matters — earlier keys win.
# All matching is case-insensitive substring.
_SECTION_KEYWORDS: List[Tuple[str, ValueTier]] = [
    ("mirror", ValueTier.MYTHIC),
    ("mythic", ValueTier.MYTHIC),
    ("exceptional", ValueTier.MYTHIC),
    ("currency - special", ValueTier.TOP),
    ("currency - exceptions", ValueTier.TOP),
    ("unique", ValueTier.TOP),
    ("exotic", ValueTier.TOP),
    ("recombinator", ValueTier.TOP),
    ("currency - regular currency tiering", ValueTier.HIGH),
    ("waystone", ValueTier.HIGH),
    ("relics", ValueTier.HIGH),
    ("soul cores", ValueTier.HIGH),
    ("runes", ValueTier.HIGH),
    ("splinters, tablets, fragments", ValueTier.HIGH),
    ("endgame flasks", ValueTier.MID),
    ("endgame charms", ValueTier.MID),
    ("endgame - rare - jewellery", ValueTier.MID),
    ("endgame - rare - gear", ValueTier.MID),
    ("untiered rare", ValueTier.MID),
    ("gems and uncut gems", ValueTier.MID),
    ("jewels", ValueTier.MID),
    ("remaining currency", ValueTier.LOW),
    ("normal and magic items", ValueTier.LOW),
    ("leveling - useful", ValueTier.LOW),
    ("leveling - life mana", ValueTier.LOW),
    ("leveling - rules", ValueTier.LOW),
    ("leveling - salvagable", ValueTier.JUNK),
    ("leveling - hide", ValueTier.JUNK),
    ("hide layer", ValueTier.JUNK),
    ("hiding rules", ValueTier.JUNK),
]

# $tier->t1, t2, ... — NeverSink's tier tag.
_TIER_TAG_RE = re.compile(r"\$tier->([a-zA-Z]+)(\d+)", re.IGNORECASE)


def classify_block(header: str, section_name: str = "") -> ValueTier:
    """Pick a ValueTier from the signals available in one block.

    `header` is the full Show/Hide line (we read the inline $tier-> tag from
    it). `section_name` comes from the nearest preceding `# [[NNNN]] Title`
    marker — it's how NeverSink groups blocks.
    """
    header_stripped = (header or "").strip()
    if header_stripped.lower().startswith("hide"):
        return ValueTier.HIDDEN

    # Tier tag wins over section heuristics — it's the author's explicit grade.
    m = _TIER_TAG_RE.search(header_stripped)
    if m:
        try:
            n = int(m.group(2))
        except ValueError:
            n = 5
        if n <= 1:
            return ValueTier.TOP
        if n == 2:
            return ValueTier.HIGH
        if n == 3:
            return ValueTier.MID
        if n == 4:
            return ValueTier.LOW
        return ValueTier.JUNK

    section_lower = (section_name or "").lower()
    for needle, tier in _SECTION_KEYWORDS:
        if needle in section_lower:
            return tier

    return ValueTier.MID  # unknown territory — leave it neutral


# ==================== Style targets ====================

@dataclass
class BlockStyle:
    """What to set on one Show block. Any field left None is preserved."""
    text_color: Optional[Tuple[int, int, int, int]] = None
    border_color: Optional[Tuple[int, int, int, int]] = None
    bg_color: Optional[Tuple[int, int, int, int]] = None
    font_size: Optional[int] = None
    # POE2 PlayEffect: "Red", "Blue", "Yellow", etc. + optional "Temp"
    play_effect: Optional[Tuple[str, bool]] = None  # (color, is_temp)
    # POE2 MinimapIcon: size (0|1|2), color, shape
    minimap: Optional[Tuple[int, str, str]] = None


# POE2's named-color palette for PlayEffect/MinimapIcon.
POE2_NAMED_COLORS = (
    "Red", "Green", "Blue", "Brown", "White", "Yellow",
    "Cyan", "Grey", "Orange", "Pink", "Purple",
)

POE2_MINIMAP_SHAPES = (
    "Circle", "Diamond", "Hexagon", "Square", "Star", "Triangle",
    "Cross", "Moon", "Raindrop", "Kite", "Pentagon", "UpsideDownHouse",
)


# ==================== Emphasis presets ====================
#
# Tuned for legibility against POE2's default dark background. Top-tier items
# get a hot palette + size boost + ground beam + biggest minimap icon. Low-tier
# items dim down so they don't compete with everything else on screen.

EMPHASIS_PRESETS: Dict[ValueTier, BlockStyle] = {
    ValueTier.MYTHIC: BlockStyle(
        text_color=(255, 200, 0, 255),
        border_color=(255, 100, 0, 255),
        bg_color=(60, 0, 0, 220),
        font_size=45,
        play_effect=("Red", False),
        minimap=(0, "Red", "Star"),
    ),
    ValueTier.TOP: BlockStyle(
        text_color=(255, 215, 0, 255),
        border_color=(220, 150, 0, 255),
        bg_color=(40, 20, 0, 210),
        font_size=42,
        play_effect=("Yellow", False),
        minimap=(0, "Yellow", "Diamond"),
    ),
    ValueTier.HIGH: BlockStyle(
        text_color=(120, 220, 255, 255),
        border_color=(60, 160, 255, 255),
        bg_color=(0, 15, 35, 200),
        font_size=38,
        play_effect=("Blue", True),
        minimap=(1, "Blue", "Hexagon"),
    ),
    ValueTier.MID: BlockStyle(
        # Mid is the "no big changes" tier — only nudge the font so it's
        # visibly distinct from low/junk, leave colors to the filter author.
        font_size=34,
    ),
    ValueTier.LOW: BlockStyle(
        text_color=(170, 170, 170, 255),
        border_color=(80, 80, 80, 200),
        font_size=28,
    ),
    ValueTier.JUNK: BlockStyle(
        text_color=(110, 110, 110, 220),
        border_color=(50, 50, 50, 180),
        bg_color=(15, 15, 15, 160),
        font_size=22,
    ),
}


# ==================== Curated random palettes ====================
#
# Each entry is a high-contrast text/border/bg combo that stays legible on POE2's
# dark background. Effect + minimap are paired so the on-ground beam matches the
# map icon color. Font size stays in the readable 32-40 range.

@dataclass(frozen=True)
class _Palette:
    text: Tuple[int, int, int, int]
    border: Tuple[int, int, int, int]
    bg: Tuple[int, int, int, int]
    effect_color: str
    minimap_color: str
    minimap_shape: str
    font_size: int = 36


CURATED_PALETTES: Tuple[_Palette, ...] = (
    _Palette((255, 80, 80, 255), (200, 30, 30, 255), (30, 0, 0, 200),
             "Red", "Red", "Diamond"),
    _Palette((255, 165, 0, 255), (200, 100, 0, 255), (30, 15, 0, 200),
             "Orange", "Orange", "Star"),
    _Palette((255, 220, 0, 255), (200, 160, 0, 255), (30, 25, 0, 200),
             "Yellow", "Yellow", "Hexagon"),
    _Palette((120, 255, 100, 255), (50, 200, 50, 255), (0, 30, 0, 200),
             "Green", "Green", "Triangle"),
    _Palette((100, 255, 220, 255), (30, 200, 180, 255), (0, 30, 25, 200),
             "Cyan", "Cyan", "Moon"),
    _Palette((100, 200, 255, 255), (30, 130, 220, 255), (0, 15, 35, 200),
             "Blue", "Blue", "Square"),
    _Palette((180, 130, 255, 255), (130, 60, 220, 255), (20, 0, 35, 200),
             "Purple", "Purple", "Pentagon"),
    _Palette((255, 150, 220, 255), (220, 80, 170, 255), (35, 0, 25, 200),
             "Pink", "Pink", "Raindrop"),
    _Palette((230, 180, 130, 255), (170, 110, 60, 255), (30, 20, 5, 200),
             "Brown", "Brown", "Kite"),
    _Palette((240, 240, 240, 255), (180, 180, 180, 255), (15, 15, 15, 200),
             "White", "White", "Circle"),
    _Palette((255, 100, 100, 255), (255, 180, 0, 255), (35, 15, 0, 210),
             "Red", "Orange", "Star"),
    _Palette((140, 255, 255, 255), (60, 180, 255, 255), (0, 20, 40, 210),
             "Cyan", "Blue", "Hexagon"),
    _Palette((200, 255, 120, 255), (150, 220, 50, 255), (10, 25, 0, 200),
             "Green", "Yellow", "Triangle"),
    _Palette((255, 200, 255, 255), (220, 100, 255, 255), (25, 0, 35, 210),
             "Pink", "Purple", "Diamond"),
    _Palette((255, 230, 150, 255), (220, 170, 60, 255), (35, 25, 0, 210),
             "Yellow", "Orange", "Pentagon"),
)


# ==================== Line rewriting primitives ====================

# Recognizers for the styling lines we may replace.
_STYLE_RE = {
    "text":   re.compile(r"^(\s*)(#\s*)?SetTextColor\b.*$",       re.IGNORECASE),
    "border": re.compile(r"^(\s*)(#\s*)?SetBorderColor\b.*$",     re.IGNORECASE),
    "bg":     re.compile(r"^(\s*)(#\s*)?SetBackgroundColor\b.*$", re.IGNORECASE),
    "font":   re.compile(r"^(\s*)(#\s*)?SetFontSize\b.*$",        re.IGNORECASE),
    "effect": re.compile(r"^(\s*)(#\s*)?PlayEffect\b.*$",         re.IGNORECASE),
    "minimap":re.compile(r"^(\s*)(#\s*)?MinimapIcon\b.*$",        re.IGNORECASE),
}

_SHOWHIDE_RE = re.compile(r"^\s*(Show|Hide|Continue)\b", re.IGNORECASE)
_SECTION_RE = re.compile(r"^#\s*\[\[(\d+)\]\]\s*(.+?)\s*$")
_SUBSECTION_RE = re.compile(r"^#\s+\[(\d+)\]\s+(.+?)\s*$")


def _fmt_rgba(rgba: Tuple[int, int, int, int]) -> str:
    r, g, b, a = rgba
    return f"{r} {g} {b} {a}"


def _build_style_lines(style: BlockStyle, indent: str, newline: str) -> Dict[str, str]:
    """Produce the new line text for each style field that's set."""
    out: Dict[str, str] = {}
    if style.text_color is not None:
        out["text"] = f"{indent}SetTextColor {_fmt_rgba(style.text_color)}{newline}"
    if style.border_color is not None:
        out["border"] = f"{indent}SetBorderColor {_fmt_rgba(style.border_color)}{newline}"
    if style.bg_color is not None:
        out["bg"] = f"{indent}SetBackgroundColor {_fmt_rgba(style.bg_color)}{newline}"
    if style.font_size is not None:
        out["font"] = f"{indent}SetFontSize {style.font_size}{newline}"
    if style.play_effect is not None:
        color, is_temp = style.play_effect
        suffix = " Temp" if is_temp else ""
        out["effect"] = f"{indent}PlayEffect {color}{suffix}{newline}"
    if style.minimap is not None:
        size, color, shape = style.minimap
        out["minimap"] = f"{indent}MinimapIcon {size} {color} {shape}{newline}"
    return out


def _detect_block_indent(block_lines: List[str]) -> str:
    """Return the leading whitespace used by indented lines in this block."""
    for line in block_lines[1:]:
        if not line.strip():
            continue
        leading_len = len(line) - len(line.lstrip(" \t"))
        if leading_len > 0:
            return line[:leading_len]
    return "\t"  # NeverSink convention


def _detect_newline(block_lines: List[str]) -> str:
    for line in block_lines:
        if line.endswith("\r\n"):
            return "\r\n"
        if line.endswith("\n"):
            return "\n"
    return "\n"


def apply_style_to_block(block_lines: List[str], style: BlockStyle) -> List[str]:
    """Return a new list of lines for one Show/Hide block with the style applied.

    Rules:
      - For each style field set, if a matching line exists in the block,
        replace it in place (preserving the original indent and any leading
        '#' comment marker by un-commenting it).
      - If no matching line exists, append a new one after the existing
        condition lines but before any trailing blank lines.
      - Lines we don't touch are preserved verbatim.
    """
    if not block_lines or not style:
        return list(block_lines)

    indent = _detect_block_indent(block_lines)
    newline = _detect_newline(block_lines)
    new_lines_by_kind = _build_style_lines(style, indent, newline)
    if not new_lines_by_kind:
        return list(block_lines)

    result = list(block_lines)
    replaced: set = set()

    for i, line in enumerate(result):
        if i == 0:
            continue  # never touch the Show/Hide header
        for kind, pattern in _STYLE_RE.items():
            if kind in replaced or kind not in new_lines_by_kind:
                continue
            if pattern.match(line):
                result[i] = new_lines_by_kind[kind]
                replaced.add(kind)
                break

    # Append any kinds we didn't find. Find the real end of the block's
    # content by scanning back past blank lines AND past any section /
    # subsection header comments that belong to the *next* block (the
    # iter_blocks yields everything from one Show/Hide up to the next, so a
    # trailing `# [[1000]] Title` line is the next block's header, not ours).
    missing = [k for k in new_lines_by_kind if k not in replaced]
    if missing:
        insert_at = len(result)
        while insert_at > 1:
            prev = result[insert_at - 1]
            prev_stripped = prev.strip()
            if not prev_stripped:
                insert_at -= 1
                continue
            if _SECTION_RE.match(prev_stripped) or _SUBSECTION_RE.match(prev_stripped):
                insert_at -= 1
                continue
            break
        for kind in missing:
            result.insert(insert_at, new_lines_by_kind[kind])
            insert_at += 1

    return result


def iter_blocks(lines: List[str]):
    """Yield (start_idx, end_idx_exclusive, header, section_name, block_lines).

    `start_idx` points at the Show/Hide line. `end_idx` is one past the last
    line of the block. Tracks the most recent `# [[NNNN]] Title` section
    header so callers can use it for classification.
    """
    current_section = ""
    block_start: Optional[int] = None
    block_header = ""
    block_section = ""

    for i, raw in enumerate(lines):
        stripped = raw.strip()
        sec_m = _SECTION_RE.match(stripped)
        if sec_m:
            current_section = sec_m.group(2).strip()

        if _SHOWHIDE_RE.match(stripped):
            if block_start is not None:
                yield (block_start, i, block_header, block_section,
                       lines[block_start:i])
            block_start = i
            block_header = raw
            block_section = current_section

    if block_start is not None:
        yield (block_start, len(lines), block_header, block_section,
               lines[block_start:len(lines)])


# ==================== Stylers ====================

@dataclass
class StyleChange:
    """One block's planned restyle, for preview + apply."""
    start_idx: int
    end_idx: int
    tier: ValueTier
    style: BlockStyle


class EmphasisStyler:
    """Rule-based: classify each block, look up preset, plan a restyle."""

    def __init__(self, presets: Optional[Dict[ValueTier, BlockStyle]] = None,
                 skip_hidden: bool = True):
        self.presets = presets if presets is not None else EMPHASIS_PRESETS
        self.skip_hidden = skip_hidden

    def plan(self, lines: List[str]) -> List[StyleChange]:
        changes: List[StyleChange] = []
        for start, end, header, section, _block in iter_blocks(lines):
            tier = classify_block(header, section)
            if tier == ValueTier.HIDDEN and self.skip_hidden:
                continue
            style = self.presets.get(tier)
            if style is None:
                continue
            changes.append(StyleChange(start, end, tier, style))
        return changes


class RandomizerStyler:
    """Curated-palette random restyle, seeded for reproducibility."""

    def __init__(self, seed: Optional[int] = None,
                 palettes: Optional[Tuple[_Palette, ...]] = None,
                 skip_hidden: bool = True):
        self.seed = seed
        self.palettes = palettes if palettes is not None else CURATED_PALETTES
        self.skip_hidden = skip_hidden

    def plan(self, lines: List[str]) -> List[StyleChange]:
        rng = random.Random(self.seed)
        changes: List[StyleChange] = []
        for start, end, header, section, _block in iter_blocks(lines):
            tier = classify_block(header, section)
            if tier == ValueTier.HIDDEN and self.skip_hidden:
                continue
            pal = rng.choice(self.palettes)
            style = BlockStyle(
                text_color=pal.text,
                border_color=pal.border,
                bg_color=pal.bg,
                font_size=pal.font_size,
                play_effect=(pal.effect_color, False),
                minimap=(1, pal.minimap_color, pal.minimap_shape),
            )
            changes.append(StyleChange(start, end, tier, style))
        return changes


def apply_changes(lines: List[str], changes: List[StyleChange]) -> List[str]:
    """Apply planned block restyles, in reverse so indices stay valid."""
    result = list(lines)
    for change in sorted(changes, key=lambda c: c.start_idx, reverse=True):
        block_lines = result[change.start_idx:change.end_idx]
        new_block = apply_style_to_block(block_lines, change.style)
        result[change.start_idx:change.end_idx] = new_block
    return result


def tier_summary(changes: List[StyleChange]) -> Dict[ValueTier, int]:
    counts: Dict[ValueTier, int] = {}
    for c in changes:
        counts[c.tier] = counts.get(c.tier, 0) + 1
    return counts


# ==================== JSON-backed presets ====================
#
# Persisted at data/visual_presets.json so users can tweak colors, font sizes,
# effects, and palettes without touching code. The loader is forgiving: any
# missing tier falls back to its code default, any malformed palette is
# skipped, and a missing file just means "use code defaults".

_VALID_NAMED_COLORS = set(POE2_NAMED_COLORS)
_VALID_MINIMAP_SHAPES = set(POE2_MINIMAP_SHAPES)


def default_visual_presets_path(app_dir: str) -> str:
    return os.path.join(app_dir, "data", "visual_presets.json")


def _rgba_from_list(value) -> Optional[Tuple[int, int, int, int]]:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) not in (3, 4):
        return None
    out = []
    for v in value:
        try:
            iv = int(v)
        except (TypeError, ValueError):
            return None
        if iv < 0 or iv > 255:
            return None
        out.append(iv)
    if len(out) == 3:
        out.append(255)
    return tuple(out)


def _effect_from_list(value) -> Optional[Tuple[str, bool]]:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) < 1:
        return None
    color = value[0]
    if color not in _VALID_NAMED_COLORS:
        return None
    is_temp = bool(value[1]) if len(value) > 1 else False
    return (color, is_temp)


def _minimap_from_list(value) -> Optional[Tuple[int, str, str]]:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    size, color, shape = value
    try:
        size = int(size)
    except (TypeError, ValueError):
        return None
    if size not in (0, 1, 2):
        return None
    if color not in _VALID_NAMED_COLORS:
        return None
    if shape not in _VALID_MINIMAP_SHAPES:
        return None
    return (size, color, shape)


def _block_style_from_dict(d: dict) -> BlockStyle:
    """Build a BlockStyle from a JSON dict. Bad fields are silently dropped
    (the field stays None) so a typo in one entry doesn't kill the whole load."""
    return BlockStyle(
        text_color=_rgba_from_list(d.get("text_color")),
        border_color=_rgba_from_list(d.get("border_color")),
        bg_color=_rgba_from_list(d.get("bg_color")),
        font_size=_clamp_int(d.get("font_size"), 12, 60),
        play_effect=_effect_from_list(d.get("play_effect")),
        minimap=_minimap_from_list(d.get("minimap")),
    )


def _palette_from_dict(d: dict) -> Optional[_Palette]:
    text = _rgba_from_list(d.get("text"))
    border = _rgba_from_list(d.get("border"))
    bg = _rgba_from_list(d.get("bg"))
    effect_color = d.get("effect_color")
    minimap_color = d.get("minimap_color")
    minimap_shape = d.get("minimap_shape")
    font_size = _clamp_int(d.get("font_size"), 12, 60) or 36
    if not (text and border and bg
            and effect_color in _VALID_NAMED_COLORS
            and minimap_color in _VALID_NAMED_COLORS
            and minimap_shape in _VALID_MINIMAP_SHAPES):
        return None
    return _Palette(text, border, bg, effect_color, minimap_color,
                    minimap_shape, font_size)


def _clamp_int(value, lo: int, hi: int) -> Optional[int]:
    if value is None:
        return None
    try:
        iv = int(value)
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, iv))


def _block_style_to_dict(s: BlockStyle) -> dict:
    return {
        "text_color": list(s.text_color) if s.text_color else None,
        "border_color": list(s.border_color) if s.border_color else None,
        "bg_color": list(s.bg_color) if s.bg_color else None,
        "font_size": s.font_size,
        "play_effect": [s.play_effect[0], s.play_effect[1]] if s.play_effect else None,
        "minimap": [s.minimap[0], s.minimap[1], s.minimap[2]] if s.minimap else None,
    }


def _palette_to_dict(p: _Palette) -> dict:
    return {
        "text": list(p.text),
        "border": list(p.border),
        "bg": list(p.bg),
        "effect_color": p.effect_color,
        "minimap_color": p.minimap_color,
        "minimap_shape": p.minimap_shape,
        "font_size": p.font_size,
    }


def load_visual_presets(path: str) -> Tuple[Dict[ValueTier, BlockStyle],
                                              Tuple[_Palette, ...]]:
    """Load presets + palettes from `path`. Missing file => code defaults.

    Tiers absent from the JSON fall back to their code-default style, so users
    can override just the tiers they care about without restating every tier.
    """
    if not path or not os.path.isfile(path):
        return dict(EMPHASIS_PRESETS), tuple(CURATED_PALETTES)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[visual_emphasis] Could not read {path}: {e} — using code defaults")
        return dict(EMPHASIS_PRESETS), tuple(CURATED_PALETTES)

    # Presets: start from code defaults, overlay anything the user supplied.
    presets: Dict[ValueTier, BlockStyle] = dict(EMPHASIS_PRESETS)
    raw_presets = data.get("emphasis_presets", {}) if isinstance(data, dict) else {}
    if isinstance(raw_presets, dict):
        for tier_name, style_dict in raw_presets.items():
            try:
                tier = ValueTier[tier_name.upper()]
            except KeyError:
                continue
            if isinstance(style_dict, dict):
                presets[tier] = _block_style_from_dict(style_dict)

    # Palettes: replace whole list if user provided any; else keep code defaults.
    raw_palettes = data.get("palettes", []) if isinstance(data, dict) else []
    palettes: List[_Palette] = []
    if isinstance(raw_palettes, list):
        for entry in raw_palettes:
            if isinstance(entry, dict):
                p = _palette_from_dict(entry)
                if p is not None:
                    palettes.append(p)
    if not palettes:
        palettes = list(CURATED_PALETTES)

    return presets, tuple(palettes)


def write_default_presets_file(path: str) -> str:
    """Write the code defaults to `path` as a starter file. Returns the path.

    Used by the 'Edit Presets File' button so first-time users have something
    to open.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "version": 1,
        "_about": ("Visual presets for the Visual Tools feature. "
                   "Reloaded every time the dialog opens — no app restart needed."),
        "_notes": {
            "tiers": "MYTHIC, TOP, HIGH, MID, LOW, JUNK. Any tier you omit keeps its code default.",
            "colors": "RGB or RGBA, each 0-255. Three values = alpha defaults to 255.",
            "font_size": "12-60. POE2's natural range is roughly 18-45.",
            "play_effect": "[color, is_temp]. Color must be one of: "
                            + ", ".join(POE2_NAMED_COLORS),
            "minimap": "[size, color, shape]. Size: 0 (large), 1, 2 (small). "
                        "Shape must be one of: " + ", ".join(POE2_MINIMAP_SHAPES),
            "palettes": "List of full palette entries used by the randomizer. "
                         "Provide any number; the randomizer picks among them.",
        },
        "emphasis_presets": {
            tier.name: _block_style_to_dict(style)
            for tier, style in EMPHASIS_PRESETS.items()
        },
        "palettes": [_palette_to_dict(p) for p in CURATED_PALETTES],
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    return path
