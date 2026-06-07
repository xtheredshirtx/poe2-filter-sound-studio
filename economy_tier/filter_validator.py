"""Post-edit validation + the structural-diff guard (A.2, §VALIDATION).

This is the last line of defence before a write. It re-parses the edited text
and proves that the only differences from the original are *targeted visual
directives (and our sentinel) inside blocks we intended to edit*. Any other
delta -- a touched sound line, a reordered block, a dropped comment, a changed
condition -- raises :class:`ValidationError` so the save aborts and the user's
filter is never corrupted.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from economy_tier.errors import ValidationError
from economy_tier.filter_parser import (
    SENTINEL_RE,
    SOUND_KEYWORDS,
    Block,
    FilterDocument,
    parse,
)
from features.visual_emphasis import _STYLE_RE


@dataclass
class ValidationReport:
    """Summary of what validation confirmed (for logging / status)."""

    blocks: int
    edited_blocks: int
    sentinels_added: int
    sound_lines: int
    warnings: list[str] = field(default_factory=list)


def _is_visual_or_sentinel(line: str) -> bool:
    stripped = line.rstrip("\r\n")
    if SENTINEL_RE.match(stripped):
        return True
    for pattern in _STYLE_RE.values():
        if pattern.match(stripped):
            return True
    return False


def _skeleton(block: Block) -> list[str]:
    """Block raw lines with visual + sentinel lines removed."""
    out: list[str] = []
    for ln in block.lines:
        if _is_visual_or_sentinel(ln.raw()):
            continue
        out.append(ln.raw())
    return out


def _sound_multiset(doc: FilterDocument) -> Counter[str]:
    counts: Counter[str] = Counter()
    for ln in doc.lines:
        d = ln.directive
        if d is not None and not d.disabled and d.keyword in SOUND_KEYWORDS:
            counts[ln.raw()] += 1
    return counts


def validate(
    original_text: str,
    new_text: str,
    edited_block_indices: set[int],
) -> ValidationReport:
    """Validate the edit. Raises :class:`ValidationError` on any violation."""
    old_doc = parse(original_text)
    new_doc = parse(new_text)

    # (1) Block count unchanged.
    if len(old_doc.blocks) != len(new_doc.blocks):
        raise ValidationError(
            f"Show/Hide block count changed: {len(old_doc.blocks)} -> "
            f"{len(new_doc.blocks)}. Aborting."
        )

    # (2) Preamble (lines before the first block) must be byte-identical.
    old_pre_end = old_doc.blocks[0].start if old_doc.blocks else len(old_doc.lines)
    new_pre_end = new_doc.blocks[0].start if new_doc.blocks else len(new_doc.lines)
    old_pre = [ln.raw() for ln in old_doc.lines[:old_pre_end]]
    new_pre = [ln.raw() for ln in new_doc.lines[:new_pre_end]]
    if old_pre != new_pre:
        raise ValidationError("Content before the first block was modified. Aborting.")

    sentinels_added = 0
    edited_count = 0

    # (3) Per-block: untouched blocks identical; edited blocks differ only in
    #     visual/sentinel lines (skeleton unchanged).
    # Block counts are already proven equal above, so strict pairing is safe.
    for old_b, new_b in zip(old_doc.blocks, new_doc.blocks, strict=True):
        old_raw = [ln.raw() for ln in old_b.lines]
        new_raw = [ln.raw() for ln in new_b.lines]
        if old_raw == new_raw:
            continue
        if old_b.index not in edited_block_indices:
            raise ValidationError(
                f"Block {old_b.index} changed but was not scheduled for editing. "
                "Aborting (structural diff guard)."
            )
        if _skeleton(old_b) != _skeleton(new_b):
            raise ValidationError(
                f"Block {old_b.index} changed a non-visual line "
                "(condition, comment, sound, or order). Aborting (structural diff guard)."
            )
        edited_count += 1
        old_sent = sum(1 for ln in old_b.lines if ln.is_sentinel)
        new_sent = sum(1 for ln in new_b.lines if ln.is_sentinel)
        sentinels_added += max(0, new_sent - old_sent)

    # (4) Every sound directive line preserved the exact same number of times.
    #     Reuse the already-parsed docs -- don't re-parse the whole file again.
    old_sounds = _sound_multiset(old_doc)
    new_sounds = _sound_multiset(new_doc)
    if old_sounds != new_sounds:
        raise ValidationError("A sound directive line was added, removed, or modified. Aborting.")

    return ValidationReport(
        blocks=len(new_doc.blocks),
        edited_blocks=edited_count,
        sentinels_added=sentinels_added,
        sound_lines=sum(old_sounds.values()),
    )


__all__ = ["ValidationReport", "validate"]
