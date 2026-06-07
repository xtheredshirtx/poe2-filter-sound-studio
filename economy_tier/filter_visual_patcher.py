"""Apply per-tier visual styles to a filter, surgically and idempotently (A.2).

For every block the classifier flagged (and the caller approved), this module
rewrites only the targeted visual directives, stamps an idempotency sentinel,
and leaves everything else -- headers, conditions, comments, blank runs, and
*all* sound directives -- byte-for-byte untouched.

It reuses the proven line-rewriting primitive from ``features.visual_emphasis``
(replace-in-place, else append after the condition lines), so newline style and
indentation are preserved per block. Running the same patch twice is a no-op.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from economy_tier import SENTINEL_VERSION
from economy_tier.economy_tier_classifier import Classification
from economy_tier.filter_parser import SENTINEL_RE, FilterDocument
from economy_tier.visual_template_loader import Template, TierStyle

# Reuse the existing, tested line-rewriting primitives.
from features.visual_emphasis import (
    _STYLE_RE,
    BlockStyle,
    _detect_block_indent,
    _detect_newline,
    apply_style_to_block,
)


@dataclass
class TransferOptions:
    """Which visual directive kinds to transfer (the optional checkboxes)."""

    apply_text: bool = True
    apply_bg: bool = True
    apply_border: bool = True
    apply_font: bool = True
    apply_effect: bool = True
    apply_minimap: bool = True


@dataclass
class BlockPatch:
    """Record of one block's restyle, for the preview diff."""

    block_index: int
    start_line: int
    end_line: int
    tier: str
    reason: str
    match_type: str
    old_visuals: list[str]
    new_visuals: list[str]
    sounds_preserved: list[str]


@dataclass
class PatchResult:
    """Outcome of patching: new file lines plus per-block change records."""

    new_lines: list[str]  # full file as raw line strings (content + newline)
    patches: list[BlockPatch] = field(default_factory=list)
    edited_block_indices: set[int] = field(default_factory=set)
    template_name: str = ""

    @property
    def changed_count(self) -> int:
        return len(self.patches)


def _style_from_template(style: TierStyle, opt: TransferOptions) -> BlockStyle:
    """Build a BlockStyle, dropping any kind the transfer options disable."""
    return BlockStyle(
        text_color=style.text_color if opt.apply_text else None,
        border_color=style.border_color if opt.apply_border else None,
        bg_color=style.bg_color if opt.apply_bg else None,
        font_size=style.font_size if opt.apply_font else None,
        play_effect=style.play_effect if opt.apply_effect else None,
        minimap=style.minimap if opt.apply_minimap else None,
    )


def _extract_visual_lines(block_lines: list[str]) -> list[str]:
    """Return the visual directive lines (stripped) present in a block."""
    out: list[str] = []
    for i, line in enumerate(block_lines):
        if i == 0:
            continue
        for pattern in _STYLE_RE.values():
            if pattern.match(line):
                out.append(line.rstrip("\r\n"))
                break
    return out


def _sentinel_text(tier: str, template_name: str, indent: str, newline: str) -> str:
    return f'{indent}# [ETVP tier={tier} template="{template_name}" v={SENTINEL_VERSION}]{newline}'


def _apply_sentinel(block_lines: list[str], sentinel: str) -> list[str]:
    """Insert the sentinel after the header, or replace an existing one."""
    out = list(block_lines)
    for i, line in enumerate(out):
        if i == 0:
            continue
        if SENTINEL_RE.match(line.rstrip("\r\n")):
            out[i] = sentinel
            return out
    out.insert(1, sentinel)
    return out


def patch(
    doc: FilterDocument,
    applicable: list[Classification],
    template: Template,
    transfer: TransferOptions | None = None,
) -> PatchResult:
    """Apply ``template`` to every block in ``applicable``. Idempotent.

    ``applicable`` must already be confidence-filtered by the caller. Returns a
    :class:`PatchResult` whose ``new_lines`` is the full file; unchanged blocks
    are left exactly as they were.
    """
    transfer = transfer or TransferOptions()
    result_lines: list[str] = [ln.raw() for ln in doc.lines]
    patches: list[BlockPatch] = []
    edited: set[int] = set()

    # Process in reverse block order so splices don't invalidate lower indices.
    ordered = sorted(applicable, key=lambda c: doc.blocks[c.block_index].start, reverse=True)
    for c in ordered:
        if c.tier is None:
            continue
        style = template.style_for(c.tier)
        if style is None:
            continue
        block = doc.blocks[c.block_index]
        orig_block = result_lines[block.start : block.end]

        block_style = _style_from_template(style, transfer)
        new_block = apply_style_to_block(orig_block, block_style)

        indent = _detect_block_indent(orig_block)
        newline = _detect_newline(orig_block)
        sentinel = _sentinel_text(c.tier, template.name, indent, newline)
        new_block = _apply_sentinel(new_block, sentinel)

        if new_block == orig_block:
            continue  # idempotent no-op

        sounds = [ln.content.strip() for ln in block.sound_lines()]
        patches.append(
            BlockPatch(
                block_index=c.block_index,
                start_line=c.start_line,
                end_line=c.end_line,
                tier=c.tier,
                reason=c.reason,
                match_type=c.match_type,
                old_visuals=_extract_visual_lines(orig_block),
                new_visuals=_extract_visual_lines(new_block),
                sounds_preserved=sounds,
            )
        )
        edited.add(c.block_index)
        result_lines[block.start : block.end] = new_block

    patches.sort(key=lambda p: p.start_line)
    return PatchResult(
        new_lines=result_lines,
        patches=patches,
        edited_block_indices=edited,
        template_name=template.name,
    )


__all__ = [
    "TransferOptions",
    "BlockPatch",
    "PatchResult",
    "patch",
]
