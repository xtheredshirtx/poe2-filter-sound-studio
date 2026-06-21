"""Item Visibility management for POE2 item filters.

Backs the "Item Visibility" tab. The single job of this module is to let the
user flip a filter block between ``Show`` and ``Hide`` *without* touching
anything else in the block — conditions, sounds, colors, PlayEffect, MinimapIcon
and comments are all preserved byte-for-byte. Only the first word of the block
header changes.

Design notes
------------
* Block boundaries are discovered the same way the rest of the app does it: a
  block starts on a line whose stripped text begins with ``Show`` or ``Hide``
  and runs until the next such line (or EOF). See :func:`iter_filter_blocks`,
  which is deliberately a shared helper so future tools can reuse the same
  boundary logic instead of re-deriving it.
* Metadata extraction reuses :func:`core.user_overrides.parse_block` and the
  sound/section regexes from :mod:`core.parser` rather than re-implementing
  parsing.
* Risk classification leans on the existing
  :func:`features.visual_emphasis.classify_block` tier heuristic plus a small
  set of structural/keyword rules.

The source of truth for *applying* a change is always the block's start line in
the currently loaded ``lines`` list. The ``stable_key`` is an identity that
ignores the Show/Hide word — useful for matching rows across rebuilds — but it
is never used to decide *which line* to edit.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

from core.parser import (
    SECTION_RE, SUBSECTION_RE, SOUND_RE_CUSTOM, SOUND_RE_PLAY,
)
from core.file_operations import save_filter_file, make_backup
from core.user_overrides import parse_block, block_signature
from features.visual_emphasis import classify_block, ValueTier

log = logging.getLogger(__name__)


# A block header always starts with one of these words (case-insensitive).
_HEADER_RE = re.compile(r"^(\s*)(Show|Hide)\b(.*)$", re.IGNORECASE)
_FONTSIZE_RE = re.compile(r"^SetFontSize\s+(\d+)", re.IGNORECASE)
_LEVEL_KEYS = ("ItemLevel", "DropLevel", "AreaLevel", "WaystoneTier", "MapTier")

# Section / subsection / item context that should make us cautious about hiding.
_VALUABLE_KEYWORDS = [
    "currency", "waystone", "map", "unique", "gem", "rune", "soul core",
    "idol", "breach", "expedition", "boss", "divine", "exalted", "mirror",
    "quest", "valuable", "relic", "fragment", "tablet", "splinter",
]


# ==================== Low-level line helpers ====================

def split_eol(line: str) -> Tuple[str, str]:
    """Split a raw line into (body, end-of-line) preserving the exact EOL.

    Handles ``\\r\\n``, ``\\n``, ``\\r`` and a missing trailing newline (last
    line of file). Keeping the original EOL is how we guarantee the file's line
    endings survive a visibility edit.
    """
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def header_word(line: str) -> str:
    """Return ``"Show"``/``"Hide"`` (normalized casing) for a header line, else ""."""
    m = _HEADER_RE.match(line)
    if not m:
        return ""
    return m.group(2).capitalize()


def rewrite_header_word(raw_line: str, new_word: str) -> Tuple[str, bool]:
    """Return ``(new_line, changed)`` with only the Show/Hide word swapped.

    Indentation, the trailing comment (e.g. ``# %D7 $type->gold``) and the exact
    end-of-line sequence are all preserved. Returns ``changed=False`` (and the
    original line untouched) if the line is not a Show/Hide header.
    """
    body, eol = split_eol(raw_line)
    m = _HEADER_RE.match(body)
    if not m:
        return raw_line, False
    indent, _old, rest = m.group(1), m.group(2), m.group(3)
    return f"{indent}{new_word}{rest}{eol}", True


# ==================== Shared block walker ====================

@dataclass
class RawBlock:
    """A located Show/Hide block: where it is, its lines, and its section."""
    start_line: int                 # index into the file's lines (inclusive)
    end_line: int                   # exclusive
    raw_lines: List[str]            # original lines incl. EOLs (header + body)
    section: str
    subsection: str


def iter_filter_blocks(lines: List[str]) -> Iterator[RawBlock]:
    """Yield every Show/Hide block in ``lines`` with its section context.

    Shared boundary logic: a new block begins on a stripped line starting with
    ``Show`` or ``Hide`` and ends just before the next one (or EOF). Section and
    subsection are tracked from the NeverSink ``# [[NNNN]] Title`` /
    ``#  [NNNN] Title`` markers — mirroring ``main.refresh_filter_data`` — so a
    section header that sits *between* a block's body and the next block
    correctly attaches to the following block, not the preceding one.

    A block's ``raw_lines`` are the contiguous slice from its header up to the
    next block, with trailing blank lines and section/subsection markers trimmed
    off (those belong to the next section). The block's ``start_line`` — the one
    we ever edit — is never affected by that trimming.
    """
    section = "(uncategorized)"
    subsection = ""
    start: Optional[int] = None
    block_section = section
    block_subsection = subsection

    def _flush(end: int) -> Optional[RawBlock]:
        if start is None:
            return None
        # Trim trailing blanks / section markers that really belong to whatever
        # comes next, so the block preview is clean.
        e = end
        while e > start + 1:
            s = lines[e - 1].strip()
            if s == "" or SECTION_RE.match(s) or SUBSECTION_RE.match(s):
                e -= 1
            else:
                break
        return RawBlock(
            start_line=start,
            end_line=e,
            raw_lines=lines[start:e],
            section=block_section,
            subsection=block_subsection,
        )

    for i, raw in enumerate(lines):
        stripped = raw.strip()

        # Section / subsection markers update context on every line (they are
        # never part of a block) — exactly as the editor tab tracks them.
        sec_m = SECTION_RE.match(stripped)
        if sec_m:
            section = sec_m.group(2).strip()
            subsection = ""
            continue
        sub_m = SUBSECTION_RE.match(stripped)
        if sub_m:
            subsection = sub_m.group(2).strip()
            continue

        if header_word(stripped):
            prev = _flush(i)
            if prev is not None:
                yield prev
            start = i
            block_section = section
            block_subsection = subsection

    tail = _flush(len(lines))
    if tail is not None:
        yield tail


# ==================== View / change models ====================

@dataclass
class VisibilityBlockView:
    """Everything the Item Visibility table needs to render one block."""
    index: int
    start_line: int
    end_line: int
    current_visibility: str           # "Show" | "Hide"
    desired_visibility: str           # "Show" | "Hide"
    category: str
    subsection: str
    rarity: str
    classes: List[str] = field(default_factory=list)
    base_types: List[str] = field(default_factory=list)
    item_level: str = ""
    stack_size: str = ""
    sound_summary: str = ""
    effect_summary: str = ""
    minimap_summary: str = ""
    context_summary: str = ""
    raw_lines: List[str] = field(default_factory=list)
    risk_level: str = "Low"           # "Low" | "Medium" | "High"
    risk_reasons: List[str] = field(default_factory=list)
    stable_key: str = ""

    @property
    def has_pending_change(self) -> bool:
        return self.desired_visibility != self.current_visibility

    def header_line_index(self) -> int:
        return self.start_line


@dataclass
class VisibilityChange:
    """A single planned Show<->Hide edit, for previews and confirmation."""
    block_key: str
    start_line: int
    end_line: int
    old_visibility: str
    new_visibility: str
    summary: str
    risk_level: str
    risk_reasons: List[str] = field(default_factory=list)


@dataclass
class ApplyResult:
    """Outcome of applying pending visibility changes."""
    applied: int = 0
    to_hide: int = 0
    to_show: int = 0
    high_risk: int = 0
    backup_path: str = ""
    errors: List[str] = field(default_factory=list)
    skipped: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


# ==================== Metadata + risk extraction ====================

def _summarize_sounds(stripped_lines: List[str]) -> Tuple[str, bool]:
    """Return (human summary, has_active_sound) for a block's sound lines."""
    active = []
    disabled = []
    for line in stripped_lines:
        mc = SOUND_RE_CUSTOM.match(line)
        mp = SOUND_RE_PLAY.match(line)
        if not (mc or mp):
            continue
        commented = bool((mc or mp).group(1))
        if mc:
            label = mc.group(3)
        else:
            label = f"id {mp.group(3)}"
        (disabled if commented else active).append(label)
    if active:
        return ", ".join(active), True
    if disabled:
        return f"(disabled) {', '.join(disabled)}", False
    return "No sound", False


def assess_risk(*, header: str, section: str, subsection: str,
                classes: List[str], base_types: List[str], rarity: str,
                effect: bool, minimap: bool, sounds_active: bool,
                font_size: int, context: str) -> Tuple[str, List[str]]:
    """Classify how risky it would be to hide this block.

    Returns ``("High"|"Medium"|"Low", reasons)``. The heuristic combines the
    existing value-tier classifier with keyword and structural checks. It is
    intentionally conservative — over-warning is safer than silently hiding
    something valuable.
    """
    reasons: List[str] = []
    level = 0  # 0 = Low, 1 = Medium, 2 = High

    haystack = " ".join([section, subsection, context]).lower()
    hits = sorted({kw for kw in _VALUABLE_KEYWORDS if kw in haystack})
    if hits:
        level = max(level, 2)
        reasons.append("Looks valuable: " + ", ".join(hits))

    tier = classify_block(header, section)
    if tier in (ValueTier.MYTHIC, ValueTier.TOP, ValueTier.HIGH):
        level = max(level, 2)
        reasons.append(f"High value tier ({tier.name.title()})")

    if effect:
        level = max(level, 2)
        reasons.append("Has drop beam (PlayEffect)")
    if minimap:
        level = max(level, 2)
        reasons.append("Has minimap icon")
    if font_size and font_size >= 40:
        level = max(level, 2)
        reasons.append(f"Large font size ({font_size})")

    if not base_types and not classes:
        level = max(level, 2)
        reasons.append("Very broad: no Class and no BaseType")
    elif classes and not base_types:
        level = max(level, 1)
        reasons.append("Broad: Class set but no specific BaseType")

    if sounds_active:
        level = max(level, 1)
        reasons.append("Has an active drop sound")
    if "rare" in rarity.lower():
        level = max(level, 1)
        reasons.append("Matches Rare items")

    label = {0: "Low", 1: "Medium", 2: "High"}[level]
    if not reasons:
        reasons.append("No risk signals detected")
    return label, reasons


def visibility_stable_key(raw_lines: List[str], section: str, subsection: str) -> str:
    """A block identity that ignores the Show/Hide word.

    Built from sorted Rarity/Class/BaseType plus section context, so flipping
    visibility does NOT change the key (unlike ``block_signature`` which folds
    the head word in). Used to match rows across rebuilds.
    """
    p = parse_block(raw_lines)
    parts: List[str] = []
    if p.rarity:
        parts.append("rar=" + " ".join(p.rarity.lower().split()))
    if p.classes:
        parts.append("cls=" + ",".join(sorted(c.lower() for c in p.classes)))
    if p.basetypes:
        parts.append("base=" + ",".join(sorted(b.lower() for b in p.basetypes)))
    if p.stack_size:
        parts.append("stack=" + " ".join(p.stack_size.lower().split()))
    ctx = (section or "").strip().lower()
    if subsection:
        ctx += "::" + subsection.strip().lower()
    if ctx:
        parts.append("sec=" + ctx)
    return " | ".join(parts) if parts else f"@{section}::{subsection}"


def build_block_view(raw: RawBlock, index: int) -> VisibilityBlockView:
    """Turn a located block into a fully populated view row."""
    stripped = [l.strip() for l in raw.raw_lines]
    current = header_word(stripped[0]) if stripped else "Show"
    if current not in ("Show", "Hide"):
        current = "Show"

    p = parse_block(raw.raw_lines)

    levels = [l for l in stripped if l.startswith(_LEVEL_KEYS)]
    item_level = "; ".join(levels)

    font_size = 0
    for l in stripped:
        mfs = _FONTSIZE_RE.match(l)
        if mfs:
            try:
                font_size = max(font_size, int(mfs.group(1)))
            except ValueError:
                pass

    effect_line = next((l for l in stripped if l.startswith("PlayEffect")), "")
    minimap_line = next((l for l in stripped if l.startswith("MinimapIcon")), "")
    sound_summary, sounds_active = _summarize_sounds(stripped)

    context_keys = (
        "Class", "BaseType", "Rarity", "ItemLevel", "DropLevel", "AreaLevel",
        "StackSize", "WaystoneTier", "Sockets", "Quality", "Corrupted",
        "GemLevel", "HasInfluence", "HasExplicitMod", "SetFontSize",
    )
    context = " ; ".join(l for l in stripped[1:] if l.startswith(context_keys))

    risk_level, risk_reasons = assess_risk(
        header=stripped[0] if stripped else "",
        section=raw.section, subsection=raw.subsection,
        classes=p.classes, base_types=p.basetypes, rarity=p.rarity,
        effect=bool(effect_line), minimap=bool(minimap_line),
        sounds_active=sounds_active, font_size=font_size, context=context,
    )

    return VisibilityBlockView(
        index=index,
        start_line=raw.start_line,
        end_line=raw.end_line,
        current_visibility=current,
        desired_visibility=current,
        category=raw.section,
        subsection=raw.subsection,
        rarity=p.rarity or "Any rarity",
        classes=p.classes,
        base_types=p.basetypes,
        item_level=item_level,
        stack_size=p.stack_size,
        sound_summary=sound_summary,
        effect_summary=effect_line.replace("PlayEffect", "").strip(),
        minimap_summary=minimap_line.replace("MinimapIcon", "").strip(),
        context_summary=context,
        raw_lines=list(raw.raw_lines),
        risk_level=risk_level,
        risk_reasons=risk_reasons,
        stable_key=visibility_stable_key(raw.raw_lines, raw.section, raw.subsection),
    )


# ==================== Smart groups ====================

# Coarse, beginner-friendly buckets used by the tab's "Smart group" dropdown.
SMART_GROUPS = [
    "Currency", "Waystones/Maps", "Uniques", "Gems", "Gear",
    "Flasks/Charms", "Runes/Soul Cores/Idols", "Other",
]


def smart_group_for(view: VisibilityBlockView) -> str:
    """Map a block to one of :data:`SMART_GROUPS` from its section + criteria."""
    hay = " ".join([
        view.category, view.subsection, view.context_summary,
        " ".join(view.classes), " ".join(view.base_types),
    ]).lower()

    def has(*words: str) -> bool:
        return any(w in hay for w in words)

    if has("currency", "orb", "shard", "catalyst"):
        return "Currency"
    if has("waystone", "map", "tablet", "fragment", "splinter"):
        return "Waystones/Maps"
    if has("rune", "soul core", "idol"):
        return "Runes/Soul Cores/Idols"
    if has("unique"):
        return "Uniques"
    if has("gem", "jewel"):
        return "Gems"
    if has("flask", "charm"):
        return "Flasks/Charms"
    if has("armour", "weapon", "gear", "jewellery", "ring", "amulet",
            "belt", "boots", "gloves", "helmet", "body armour", "shield"):
        return "Gear"
    return "Other"


# ==================== Manager / controller ====================

class VisibilityManager:
    """Holds the parsed view rows and applies Show/Hide edits to ``lines``.

    The manager operates on the *same* ``lines`` list object owned by the app so
    that an applied edit is visible to every other tab immediately. Pending
    changes live only on the view rows (``desired_visibility``) until
    :meth:`apply` writes them to disk.
    """

    def __init__(self) -> None:
        self.lines: List[str] = []
        self.filter_path: str = ""
        self.blocks: List[VisibilityBlockView] = []

    # ---- loading / rebuilding ----

    def load_from_lines(self, lines: List[str], filter_path: str = "") -> None:
        """Bind to a filter's lines and (re)build the view rows from scratch."""
        self.lines = lines
        self.filter_path = filter_path
        self.rebuild()

    def rebuild(self) -> None:
        """Re-parse blocks from ``self.lines``. Drops any pending changes."""
        self.blocks = [
            build_block_view(raw, idx)
            for idx, raw in enumerate(iter_filter_blocks(self.lines))
        ]

    # ---- pending-change manipulation ----

    def set_desired(self, view: VisibilityBlockView, desired: str) -> None:
        if desired in ("Show", "Hide"):
            view.desired_visibility = desired

    def reset(self, view: VisibilityBlockView) -> None:
        view.desired_visibility = view.current_visibility

    def revert_all(self) -> None:
        for v in self.blocks:
            v.desired_visibility = v.current_visibility

    def has_pending(self) -> bool:
        return any(v.has_pending_change for v in self.blocks)

    def pending_views(self) -> List[VisibilityBlockView]:
        return [v for v in self.blocks if v.has_pending_change]

    def pending_changes(self) -> List[VisibilityChange]:
        """Build a :class:`VisibilityChange` for every row with a pending edit."""
        out: List[VisibilityChange] = []
        for v in self.pending_views():
            out.append(VisibilityChange(
                block_key=v.stable_key,
                start_line=v.start_line,
                end_line=v.end_line,
                old_visibility=v.current_visibility,
                new_visibility=v.desired_visibility,
                summary=self.summarize(v),
                risk_level=v.risk_level,
                risk_reasons=list(v.risk_reasons),
            ))
        return out

    @staticmethod
    def summarize(view: VisibilityBlockView) -> str:
        """Short human label for a block (BaseType > Class > Rarity)."""
        if view.base_types:
            shown = ", ".join(view.base_types[:4])
            if len(view.base_types) > 4:
                shown += f" +{len(view.base_types) - 4} more"
            return shown
        if view.classes:
            return ", ".join(view.classes[:4])
        if view.rarity and view.rarity != "Any rarity":
            return f"All {view.rarity}"
        return view.category or "(no item criteria)"

    # ---- applying ----

    def apply(self, create_backup: bool = True,
              max_backups: Optional[int] = None) -> ApplyResult:
        """Write all pending Show/Hide changes to disk, atomically.

        Steps, in order:
          1. Validate every target line still starts with Show/Hide.
          2. Create a backup of the current file (so the user can always undo).
          3. Replace only the header word on each changed block, in place.
          4. Atomic save via :func:`core.file_operations.save_filter_file`.
          5. Rebuild views so current == on-disk state.
        """
        result = ApplyResult()
        changes = self.pending_changes()
        if not changes:
            return result

        if not self.filter_path or not os.path.isfile(self.filter_path):
            result.errors.append("No saved filter file to write to. Save the filter first.")
            return result

        # 1. Validate first — refuse to touch anything if a line drifted.
        valid: List[VisibilityChange] = []
        for ch in changes:
            if not (0 <= ch.start_line < len(self.lines)):
                result.errors.append(f"Line {ch.start_line} is out of range; skipped.")
                result.skipped += 1
                continue
            current_word = header_word(self.lines[ch.start_line])
            if current_word not in ("Show", "Hide"):
                result.errors.append(
                    f"Line {ch.start_line + 1} no longer starts with Show/Hide; skipped."
                )
                result.skipped += 1
                continue
            valid.append(ch)

        if not valid:
            return result

        # 2. Backup (explicitly, so we can report exactly where it went).
        if create_backup:
            backup = make_backup(self.filter_path, max_keep=max_backups,
                                 label="visibility")
            if backup:
                result.backup_path = backup

        # 3. Rewrite header words in place.
        for ch in valid:
            new_line, changed = rewrite_header_word(self.lines[ch.start_line],
                                                    ch.new_visibility)
            if not changed:
                result.skipped += 1
                continue
            self.lines[ch.start_line] = new_line
            result.applied += 1
            if ch.new_visibility == "Hide":
                result.to_hide += 1
            else:
                result.to_show += 1
            if ch.risk_level == "High" and ch.new_visibility == "Hide":
                result.high_risk += 1

        # 4. Atomic save (backup already taken above, so don't double it).
        try:
            save_filter_file(self.filter_path, self.lines, create_backup=False)
        except Exception as e:  # pragma: no cover - disk failure path
            log.exception("Visibility apply: save failed")
            result.errors.append(f"Save failed: {e}")
            return result

        # 5. Resync view state to disk.
        self.rebuild()
        return result
