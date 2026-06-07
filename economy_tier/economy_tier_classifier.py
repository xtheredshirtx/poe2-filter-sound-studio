"""Classify every filter block into an economy value tier (pure, A.3/A.6).

``classify`` is a pure function of ``(document, tier_data, options)`` -- no I/O,
no wall-clock, no global state -- so the same inputs always yield the same
diff. It implements the §1 priority order:

1. exact ``BaseType`` in ``SS_CHANCE_BASE`` (only under the chance-boost mode,
   only on ``Rarity Normal`` blocks, only on an exact base-name hit) (A.3)
2-4. exact item/base name in the SS/S/A (and below) named-entry lists
5. ``Rarity Unique`` -> A
6. ``Class "Currency"`` unmatched -> C (never below C without an explicit entry)
7. ``WaystoneTier`` numeric rule
8. gem class -> C
9. section/``$tier`` heuristic fallback (reuses ``features.visual_emphasis``),
   marked low-confidence so it is previewed but not written by default
10. otherwise unknown -> left unchanged

Confidence gating (A.5) is applied by the caller via :meth:`Classification.applicable`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum

from economy_tier.economy_tier_data import (
    Confidence,
    TierData,
    TierEntry,
    higher_tier,
    tier_rank,
)
from economy_tier.filter_parser import (
    NUMERIC_KEYWORDS,
    Block,
    FilterDocument,
)

# Reuse the existing section keyword map for grading by section name.
from features.visual_emphasis import _SECTION_KEYWORDS, ValueTier

_SECTION_RE = re.compile(r"^#\s*\[\[(\d+)\]\]\s*(.+?)\s*$")

# Map the heuristic ValueTier onto economy tier names (the fallback, step 9).
_HEURISTIC_TO_TIER: dict[ValueTier, str] = {
    ValueTier.MYTHIC: "SS",
    ValueTier.TOP: "S",
    ValueTier.HIGH: "A",
    ValueTier.MID: "B",
    ValueTier.LOW: "C",
    ValueTier.JUNK: "F",
}

# Condition directives that mean "this block identifies a kind of item".
_IDENTITY_KEYWORDS = frozenset(
    {
        "class",
        "basetype",
        "rarity",
        "corrupted",
        "identified",
        "mirrored",
        "hasexplicitmod",
        "hasinfluence",
        "anyenchantment",
        "socketgroup",
        "unidentifieditemtier",
        "replica",
        "hasenchantment",
    }
    | {k.lower() for k in NUMERIC_KEYWORDS}
)


class Status(str, Enum):
    """What the classifier decided to do with a block."""

    CLASSIFIED = "classified"
    UNKNOWN = "unknown"
    SKIPPED_HIDDEN = "skipped_hidden"
    SKIPPED_SOUND_ONLY = "skipped_sound_only"


@dataclass
class ClassifyOptions:
    """Knobs for one classification run (part of the run fingerprint)."""

    enable_chance_boost: bool = False
    min_confidence: Confidence = Confidence.medium
    skip_hidden: bool = True
    use_heuristic_fallback: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "enable_chance_boost": self.enable_chance_boost,
            "min_confidence": self.min_confidence.name,
            "skip_hidden": self.skip_hidden,
            "use_heuristic_fallback": self.use_heuristic_fallback,
        }


@dataclass
class Classification:
    """The classifier's verdict for one block."""

    block_index: int
    start_line: int  # 1-based, inclusive
    end_line: int  # 1-based, inclusive
    status: Status
    tier: str | None = None
    confidence: Confidence = Confidence.low
    reason: str = ""
    match_type: str = ""
    is_hidden: bool = False
    is_chance_promotion: bool = False
    has_sound: bool = False

    def applicable(self, min_confidence: Confidence) -> bool:
        """True if this block should actually be written (confidence-gated)."""
        return (
            self.status == Status.CLASSIFIED
            and self.tier is not None
            and self.confidence >= min_confidence
        )


@dataclass
class ClassificationResult:
    """All per-block verdicts plus a reproducible run fingerprint."""

    classifications: list[Classification]
    fingerprint: str
    options: ClassifyOptions
    warnings: list[str] = field(default_factory=list)

    def tier_counts(self, min_confidence: Confidence | None = None) -> dict[str, int]:
        counts: dict[str, int] = {}
        for c in self.classifications:
            if c.tier is None:
                continue
            if min_confidence is not None and not c.applicable(min_confidence):
                continue
            counts[c.tier] = counts.get(c.tier, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# Block-level helpers
# ---------------------------------------------------------------------------


def _block_has_identity(block: Block) -> bool:
    for ln in block.lines:
        d = ln.directive
        if d is None or d.disabled:
            continue
        if d.keyword.lower() in _IDENTITY_KEYWORDS:
            return True
    return False


def _candidate_names(block: Block) -> list[tuple[str, bool]]:
    """(value, exact) pairs to test against named tier entries."""
    return block.basetype_values() + block.class_values()


def _is_normal_only(block: Block) -> bool:
    rarities = [r.lower() for r in block.rarities()]
    if not rarities:
        return False  # rarity unspecified -> conservative, don't promote
    return all(r == "normal" for r in rarities)


def _match_chance_base(block: Block, data: TierData) -> tuple[TierEntry, str] | None:
    """Return (entry, match_type) if this block is an exact chance base, else None.

    Exact-match gated (A.3): the directive value must *equal* the base name
    (case-insensitive). A proper substring (e.g. ``"Ring"``) never promotes.
    """
    base_values = block.basetype_values()
    for entry in data.chance_base_entries():
        name_lc = entry.name.lower()
        for value, exact in base_values:
            if value.lower() == name_lc:
                mt = "exact (==)" if exact else "name-equal"
                return entry, mt
    return None


def _match_named_entry(block: Block, data: TierData) -> tuple[TierEntry, str] | None:
    """First named tier entry (strongest tier first) whose name equals a value."""
    candidates = [v.lower() for v, _ in _candidate_names(block)]
    if not candidates:
        return None
    for entry in data.all_named_entries():
        if entry.name.lower() in candidates:
            return entry, "name-equal"
    return None


def _waystone_tier(block: Block) -> tuple[str, str] | None:
    d = block.first("WaystoneTier")
    if d is None:
        return None
    n = d.numeric_value()
    if n is None:
        return None
    if n >= 15:
        return "A", f"WaystoneTier {d.operator} {n} (>=15)"
    if n >= 11:
        return "B", f"WaystoneTier {d.operator} {n} (11-14)"
    if n >= 6:
        return "C", f"WaystoneTier {d.operator} {n} (6-10)"
    return "D", f"WaystoneTier {d.operator} {n} (<6)"


def _grading_tier(header: str, section: str) -> tuple[str, Confidence] | None:
    """Use the filter's OWN grade for this block, from its SECTION name.

    The block's section (e.g. "Endgame - Rare - Gear", "Waystones") is a reliable
    grade, so we trust it at MEDIUM confidence — that's how rare/magic/normal gear
    the filter groups gets tiered by default, like uniques.

    We deliberately DON'T use the ``$tier->`` tag's trailing number as an
    importance rank: in NeverSink PoE2 filters that number is category-specific
    (e.g. ``$tier->skill20`` is a gem *level*, not "tier 20"), so reading it as a
    rank mis-tiers things badly. Blocks with no recognised section return None and
    are left unchanged.
    """
    sec = (section or "").lower()
    for needle, vt in _SECTION_KEYWORDS:
        if needle in sec:
            tier = _HEURISTIC_TO_TIER.get(vt)
            if tier is not None:
                return tier, Confidence.medium
    return None


def _uncut_gem_tier(block: Block) -> tuple[str, str] | None:
    """Tier Uncut Skill/Spirit/Support Gems by their gem level (higher = better).

    Their value rises with level, so the styling should too. Returns
    ``(tier, reason)`` or None if this block isn't an uncut-gem block.
    """
    bases = [v.lower() for v, _ in block.basetype_values()]
    if not any("uncut" in b and "gem" in b for b in bases):
        return None
    d = block.first("GemLevel")
    lvl = d.numeric_value() if d is not None else None
    if lvl is None:
        return "F", "uncut gem (unleveled / low)"
    if lvl >= 20:
        return "A", f"uncut gem level {lvl}"
    if lvl == 19:
        return "B", f"uncut gem level {lvl}"
    if lvl >= 17:
        return "C", f"uncut gem level {lvl}"
    if lvl >= 15:
        return "D", f"uncut gem level {lvl}"
    return "F", f"uncut gem level {lvl}"


def _section_map(doc: FilterDocument) -> dict[int, str]:
    """Map each block index to the nearest preceding ``# [[NNNN]] Title`` name."""
    out: dict[int, str] = {}
    current = ""
    bi = 0
    block_starts = {b.start: b.index for b in doc.blocks}
    for i, ln in enumerate(doc.lines):
        m = _SECTION_RE.match(ln.content.strip())
        if m:
            current = m.group(2).strip()
        if i in block_starts:
            out[block_starts[i]] = current
    _ = bi
    return out


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def classify(
    doc: FilterDocument,
    data: TierData,
    options: ClassifyOptions,
    template_fingerprint: str = "",
) -> ClassificationResult:
    """Classify every block in ``doc``. Pure function -- see module docstring."""
    sections = _section_map(doc)
    results: list[Classification] = []
    warnings: list[str] = []
    # Count (don't itemize) the common, expected case where a block lists a
    # chance base but isn't Rarity Normal, so we summarize it as one line
    # instead of flooding the preview with one warning per block.
    chance_not_normal = 0

    for block in doc.blocks:
        start_line = block.start + 1
        end_line = block.end  # exclusive index == 1-based inclusive last line
        has_sound = bool(block.sound_lines())
        is_hidden = block.is_hide

        base = Classification(
            block_index=block.index,
            start_line=start_line,
            end_line=end_line,
            status=Status.UNKNOWN,
            is_hidden=is_hidden,
            has_sound=has_sound,
        )

        # (0a) Hidden blocks: skip when the option says so.
        if is_hidden and options.skip_hidden:
            base.status = Status.SKIPPED_HIDDEN
            results.append(base)
            continue

        # (0b) Pure sound rules with no item identity: never restyle.
        if has_sound and not _block_has_identity(block):
            base.status = Status.SKIPPED_SOUND_ONLY
            results.append(base)
            continue

        tier: str | None = None
        confidence = Confidence.low
        reason = ""
        match_type = ""
        is_promotion = False

        # (1) Chance-base promotion (mode-gated, exact, Rarity Normal only).
        if options.enable_chance_boost:
            cb = _match_chance_base(block, data)
            if cb is not None:
                entry, mt = cb
                if _is_normal_only(block):
                    tier = "SS_CHANCE_BASE"
                    confidence = entry.confidence
                    reason = entry.reason
                    match_type = f"chance base {mt}"
                    is_promotion = True
                else:
                    chance_not_normal += 1

        # (2-4) Named tier entry by exact name.
        if tier is None:
            named = _match_named_entry(block, data)
            if named is not None:
                entry, mt = named
                tier = entry.tier
                confidence = entry.confidence
                reason = entry.reason or f"named entry {entry.name!r}"
                match_type = f"{entry.match_type or 'name'} {mt}".strip()

        # (5) Rarity Unique -> A baseline.
        if tier is None and any(r.lower() == "unique" for r in block.rarities()):
            tier, confidence = "A", Confidence.medium
            reason, match_type = "Rarity Unique (generic pickup)", "rule:unique"

        # (7) WaystoneTier numeric rule.
        if tier is None:
            wt = _waystone_tier(block)
            if wt is not None:
                tier, reason = wt
                confidence, match_type = Confidence.medium, "rule:waystone"

        # (6) Currency class default -> C (never below C without an entry).
        if tier is None and any("currency" in v.lower() for v, _ in block.class_values()):
            tier, confidence = "C", Confidence.medium
            reason, match_type = "unmatched currency (default C)", "rule:currency"

        # (7b) Uncut gems: tier by gem level (higher = more valuable).
        if tier is None:
            ug = _uncut_gem_tier(block)
            if ug is not None:
                tier, reason = ug
                confidence, match_type = Confidence.medium, "rule:uncut_gem"

        # (8) Gem class default -> C.
        if tier is None and any("gem" in v.lower() for v, _ in block.class_values()):
            tier, confidence = "C", Confidence.low
            reason, match_type = "gem class (default C)", "rule:gem"

        # (9) The filter's OWN grading ($tier tag or known section). Applied at
        #     MEDIUM confidence so graded rare/magic/normal gear is tiered by
        #     default; blocks with no grade are left untouched (returns None).
        if tier is None and options.use_heuristic_fallback:
            section = sections.get(block.index, "")
            graded = _grading_tier(block.header_line.content, section)
            if graded is not None:
                tier, confidence = graded
                reason = f"filter grading (section={section!r})"
                match_type = "grading"

        if tier is None:
            base.status = Status.UNKNOWN
            results.append(base)
            continue

        base.status = Status.CLASSIFIED
        base.tier = tier
        base.confidence = confidence
        base.reason = reason
        base.match_type = match_type
        base.is_chance_promotion = is_promotion
        results.append(base)

    if chance_not_normal:
        warnings.append(
            f"{chance_not_normal} block(s) list a chance base but aren't Rarity "
            "Normal, so they were not promoted (expected — chancing needs Normal items)."
        )

    fingerprint = compute_fingerprint(
        doc.serialize(), data.fingerprint, template_fingerprint, options
    )
    return ClassificationResult(
        classifications=results,
        fingerprint=fingerprint,
        options=options,
        warnings=warnings,
    )


def compute_fingerprint(
    filter_text: str,
    tier_fp: str,
    template_fp: str,
    options: ClassifyOptions,
) -> str:
    """Stable hash of all inputs that determine the output diff (A.6)."""
    payload = json.dumps(
        {
            "filter": hashlib.sha256(filter_text.encode("utf-8")).hexdigest(),
            "tiers": tier_fp,
            "template": template_fp,
            "options": options.as_dict(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# Re-export for callers that compose tiers.
__all__ = [
    "Status",
    "ClassifyOptions",
    "Classification",
    "ClassificationResult",
    "classify",
    "compute_fingerprint",
    "higher_tier",
    "tier_rank",
]
