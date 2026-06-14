"""Per-filter user customizations for the visual emphasis system.

When the user opens "Emphasize by Tier" and edits a tier (or moves a single
block to a different tier), we save those choices into a sidecar JSON next
to the filter at ``<filter>.filterstudio.json``. Next time the same filter
loads, the customizations apply automatically.

Two layers of override, both optional:

  - Tier preset override: "for THIS filter, my MYTHIC styling looks like X."
    Applies to every block we classify as MYTHIC.

  - Per-block override: "this specific block (Show, Rarity Unique, BaseType
    'Heavy Belt') should be treated as TOP tier even though my heuristics
    say MID — and use this exact custom style."

Block identity is a stable signature built from the header word (Show/Hide),
the Rarity, and the sorted Class + BaseType values. That survives line-number
shuffles between filter versions; it does NOT survive a fundamental change
to the block's criteria (which is correct — that's a different block).
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

from features.visual_emphasis import (
    BlockStyle, ValueTier,
    _block_style_from_dict, _block_style_to_dict,
)


SIDECAR_EXTENSION = ".filterstudio.json"


# ==================== Block signatures ====================

_SHOWHIDE_FIRST = re.compile(r"^(Show|Hide|Continue)\b", re.IGNORECASE)
_RARITY_RE = re.compile(r"^Rarity\s+(.+)$", re.IGNORECASE)
_CLASS_RE = re.compile(r"^Class\s+(.+)$", re.IGNORECASE)
_BASETYPE_RE = re.compile(r"^BaseType\s+(.+)$", re.IGNORECASE)
_STACKSIZE_RE = re.compile(r"^StackSize\s+(.+)$", re.IGNORECASE)
_AREALEVEL_RE = re.compile(r"^AreaLevel\s+(.+)$", re.IGNORECASE)
_WAYSTONE_RE = re.compile(r"^WaystoneTier\s+(.+)$", re.IGNORECASE)
_QUOTED_RE = re.compile(r'"([^"]+)"')


@dataclass
class ParsedBlock:
    """Light parse of a Show/Hide block — what the UI needs to display it."""
    head_word: str = "Show"           # "Show" | "Hide" | "Continue"
    rarity: str = ""
    classes: List[str] = field(default_factory=list)    # original casing preserved
    basetypes: List[str] = field(default_factory=list)
    stack_size: str = ""              # "" or e.g. ">= 5"
    area_level: str = ""
    waystone_tier: str = ""


def parse_block(block_lines: List[str]) -> ParsedBlock:
    """Pull the criteria out of a block. Tolerant of order, comments, quoting."""
    out = ParsedBlock()
    if not block_lines:
        return out
    header = block_lines[0].strip()
    m = _SHOWHIDE_FIRST.match(header)
    if m:
        out.head_word = m.group(1).capitalize()

    for line in block_lines[1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m_r = _RARITY_RE.match(stripped)
        if m_r:
            out.rarity = " ".join(m_r.group(1).split()).strip()
            continue
        m_c = _CLASS_RE.match(stripped)
        if m_c:
            values = _QUOTED_RE.findall(m_c.group(1))
            if not values:
                values = m_c.group(1).split()
            out.classes.extend(v.strip() for v in values if v.strip())
            continue
        m_b = _BASETYPE_RE.match(stripped)
        if m_b:
            values = _QUOTED_RE.findall(m_b.group(1))
            if not values:
                values = m_b.group(1).split()
            out.basetypes.extend(v.strip() for v in values if v.strip())
            continue
        m_s = _STACKSIZE_RE.match(stripped)
        if m_s and not out.stack_size:
            out.stack_size = " ".join(m_s.group(1).split()).strip()
            continue
        m_a = _AREALEVEL_RE.match(stripped)
        if m_a and not out.area_level:
            out.area_level = " ".join(m_a.group(1).split()).strip()
            continue
        m_w = _WAYSTONE_RE.match(stripped)
        if m_w and not out.waystone_tier:
            out.waystone_tier = " ".join(m_w.group(1).split()).strip()
            continue
    return out


def block_signature(block_lines: List[str]) -> str:
    """Stable identifier for a block, derived from its semantic criteria.

    Same criteria = same signature, regardless of styling/sound/line shuffling.
    Used as the key in `block_overrides` so a user's tweaks survive filter
    re-imports and edits.
    """
    if not block_lines:
        return ""
    p = parse_block(block_lines)
    parts = [p.head_word]
    if p.rarity:
        parts.append(f"rarity={p.rarity}")
    if p.classes:
        parts.append("class=" + ",".join(sorted({c.lower() for c in p.classes})))
    if p.basetypes:
        parts.append("base=" + ",".join(sorted({b.lower() for b in p.basetypes})))
    return " | ".join(parts)


def friendly_block_name(block_lines: List[str], max_basetypes: int = 5) -> str:
    """A human-readable label for the block — what shows up in the UI.

    Priority of signals:
      1. BaseType (the most specific — the actual item name in POE2)
      2. Class (broader bucket — "Belts", "Currency", etc.)
      3. Rarity ("All Unique", "All Rare")
      4. Whatever's in the header tag, as a last resort

    Examples:
      `BaseType "Divine Orb"`                     -> "Divine Orb"
      `BaseType "Heavy Belt" "Leather Belt"`      -> "Heavy Belt, Leather Belt"
      17 basetypes                                 -> "X, Y, Z, A, B + 12 more (17 total)"
      `Class "Currency" Rarity = Normal`          -> "Currency (Normal)"
      `Rarity Unique` only                         -> "All Unique items"
    """
    if not block_lines:
        return "(empty)"
    p = parse_block(block_lines)

    label = ""
    if p.basetypes:
        total = len(p.basetypes)
        shown = p.basetypes[:max_basetypes]
        label = ", ".join(shown)
        if total > max_basetypes:
            # Spell out the total so the user doesn't mistake a "+N more" tail
            # for the actual list size.
            label += f" + {total - max_basetypes} more ({total} total)"
        if p.classes and len(p.classes) <= 2:
            label = f"{label}  [{', '.join(p.classes)}]"
    elif p.classes:
        total = len(p.classes)
        shown = p.classes[:max_basetypes]
        label = ", ".join(shown)
        if total > max_basetypes:
            label += f" + {total - max_basetypes} more ({total} total)"
        if p.rarity:
            label = f"{label} ({p.rarity})"
    elif p.rarity:
        label = f"All {p.rarity} items"
    else:
        # No criteria? Fall back to the inline $type-> tag from the header.
        header = block_lines[0].strip()
        tag_match = re.search(r"\$type->(\S+)", header)
        if tag_match:
            label = f"Catch-all: {tag_match.group(1)}"
        else:
            label = "(no item criteria)"

    # Useful qualifiers tacked on the right.
    qualifiers = []
    if p.stack_size:
        qualifiers.append(f"stack {p.stack_size}")
    if p.waystone_tier:
        qualifiers.append(f"waystone tier {p.waystone_tier}")
    if p.area_level:
        qualifiers.append(f"area lvl {p.area_level}")
    if qualifiers:
        label = f"{label}  ·  " + " · ".join(qualifiers)

    if p.head_word == "Hide":
        label = "[HIDDEN] " + label
    return label


# ==================== Override model ====================

@dataclass
class BlockOverride:
    """User's customization for one specific block."""
    # If set, override the heuristic-assigned tier for this block.
    tier: Optional[ValueTier] = None
    # If set, use this style for the block instead of the tier preset.
    style: Optional[BlockStyle] = None
    # Free-text label so the user can identify the block in lists.
    label: str = ""

    def to_dict(self) -> dict:
        return {
            "tier": self.tier.name if self.tier is not None else None,
            "style": _block_style_to_dict(self.style) if self.style else None,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BlockOverride":
        tier_name = data.get("tier")
        tier = None
        if tier_name:
            try:
                tier = ValueTier[tier_name.upper()]
            except KeyError:
                tier = None
        style_dict = data.get("style")
        style = _block_style_from_dict(style_dict) if isinstance(style_dict, dict) else None
        return cls(tier=tier, style=style, label=data.get("label", ""))


@dataclass
class UserOverrides:
    """The full sidecar contents for one filter file."""
    # Per-tier styling overrides — apply to every block in that tier.
    tier_presets: Dict[ValueTier, BlockStyle] = field(default_factory=dict)
    # Per-block overrides keyed by `block_signature()`.
    block_overrides: Dict[str, BlockOverride] = field(default_factory=dict)
    # The file this is for, recorded so we can warn if the sidecar gets moved.
    filter_name: str = ""

    def has_any(self) -> bool:
        return bool(self.tier_presets) or bool(self.block_overrides)

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "filter_name": self.filter_name,
            "tier_presets": {
                tier.name: _block_style_to_dict(style)
                for tier, style in self.tier_presets.items()
            },
            "block_overrides": {
                sig: ov.to_dict() for sig, ov in self.block_overrides.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserOverrides":
        out = cls(filter_name=(data or {}).get("filter_name", ""))
        raw_presets = (data or {}).get("tier_presets", {})
        if isinstance(raw_presets, dict):
            for tier_name, style_dict in raw_presets.items():
                try:
                    tier = ValueTier[tier_name.upper()]
                except KeyError:
                    continue
                if isinstance(style_dict, dict):
                    out.tier_presets[tier] = _block_style_from_dict(style_dict)
        raw_blocks = (data or {}).get("block_overrides", {})
        if isinstance(raw_blocks, dict):
            for sig, ov_dict in raw_blocks.items():
                if isinstance(ov_dict, dict):
                    out.block_overrides[sig] = BlockOverride.from_dict(ov_dict)
        return out


# ==================== Sidecar IO ====================

def sidecar_path(filter_path: str) -> str:
    """Return the absolute path of the sidecar file for `filter_path`."""
    if not filter_path:
        return ""
    base, _ = os.path.splitext(filter_path)
    return base + SIDECAR_EXTENSION


def load_overrides(filter_path: str) -> UserOverrides:
    """Return the saved overrides, or an empty UserOverrides if none exist."""
    path = sidecar_path(filter_path)
    if not path or not os.path.isfile(path):
        return UserOverrides(filter_name=os.path.basename(filter_path))
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Could not read overrides %s: %s", path, e)
        return UserOverrides(filter_name=os.path.basename(filter_path))
    overrides = UserOverrides.from_dict(data)
    if not overrides.filter_name:
        overrides.filter_name = os.path.basename(filter_path)
    return overrides


def save_overrides(filter_path: str, overrides: UserOverrides) -> Optional[str]:
    """Atomically write the sidecar. Returns the path on success."""
    path = sidecar_path(filter_path)
    if not path:
        return None
    overrides.filter_name = os.path.basename(filter_path)
    payload = overrides.to_dict()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as e:
        log.warning("Could not write overrides %s: %s", path, e)
        return None
    return path
