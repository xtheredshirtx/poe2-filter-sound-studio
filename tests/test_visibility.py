"""Tests for the Item Visibility feature (features/visibility_manager.py).

Covers the contract that flipping Show<->Hide changes ONLY the header word and
leaves every other line — conditions, sounds, colors, effects, minimap icons,
comments and line endings — untouched.
"""

from __future__ import annotations

from features.visibility_manager import (
    VisibilityManager, rewrite_header_word, header_word, iter_filter_blocks,
    build_block_view, assess_risk,
)


# A small filter with varied blocks: a valuable currency block with sound/effect,
# a plain rare-gear block, an already-hidden block, a broad catch-all, and a
# multi-basetype block.
SAMPLE = (
    "# [[1000]] Currency - SPECIAL\n"
    "Show # $tier->t1\n"
    "\tClass \"Currency\"\n"
    "\tBaseType \"Divine Orb\" \"Mirror of Kalandra\"\n"
    "\tSetTextColor 255 200 0 255\n"
    "\tSetFontSize 45\n"
    "\tPlayEffect Red\n"
    "\tMinimapIcon 0 Red Star\n"
    "\tCustomAlertSound \"divine.mp3\" 300\n"
    "\n"
    "# [[2000]] Endgame - Rare - Gear\n"
    "Show\n"
    "\tClass \"Body Armours\"\n"
    "\tRarity Rare\n"
    "\tSetBorderColor 100 100 255 255\n"
    "\n"
    "# [[3000]] Hide Layer 1\n"
    "Hide\n"
    "\tClass \"Quivers\"\n"
    "\n"
    "# [[4000]] Catch All\n"
    "Show\n"
    "\tSetFontSize 18\n"
)


def _mgr(text=SAMPLE):
    m = VisibilityManager()
    m.load_from_lines(list(_splitlines_keepends(text)), filter_path="")
    return m


def _splitlines_keepends(text):
    return text.splitlines(keepends=True)


# ---------------------------------------------------------------- pure helpers

def test_header_word_detection():
    assert header_word("Show\n") == "Show"
    assert header_word("\tHide # comment\n") == "Hide"
    assert header_word("\tClass \"x\"\n") == ""


def test_rewrite_show_to_hide_only_changes_word():
    line, changed = rewrite_header_word("Show # $tier->t1\n", "Hide")
    assert changed
    assert line == "Hide # $tier->t1\n"


def test_rewrite_hide_to_show_only_changes_word():
    line, changed = rewrite_header_word("\tHide # keep me\n", "Show")
    assert changed
    assert line == "\tShow # keep me\n"


def test_rewrite_preserves_crlf_line_ending():
    line, changed = rewrite_header_word("Show # x\r\n", "Hide")
    assert changed and line == "Hide # x\r\n"
    # And a missing trailing newline (last line of file).
    line2, changed2 = rewrite_header_word("Hide", "Show")
    assert changed2 and line2 == "Show"


def test_rewrite_ignores_non_header():
    line, changed = rewrite_header_word("\tClass \"Rings\"\n", "Hide")
    assert not changed and line == "\tClass \"Rings\"\n"


# ---------------------------------------------------------------- parsing

def test_parses_all_blocks_with_sections():
    # (8) Section comments precede blocks; each block gets its own section.
    m = _mgr()
    assert [b.current_visibility for b in m.blocks] == ["Show", "Show", "Hide", "Show"]
    assert m.blocks[0].category == "Currency - SPECIAL"
    assert m.blocks[1].category == "Endgame - Rare - Gear"
    assert m.blocks[2].category == "Hide Layer 1"
    assert m.blocks[3].category == "Catch All"


def test_block_with_no_basetype():
    # (9) A block with no BaseType still parses; base_types is empty.
    m = _mgr()
    gear = m.blocks[1]
    assert gear.base_types == []
    assert gear.classes == ["Body Armours"]


def test_block_with_multiple_basetypes():
    # (10) Multiple quoted BaseType values are all captured.
    m = _mgr()
    cur = m.blocks[0]
    assert cur.base_types == ["Divine Orb", "Mirror of Kalandra"]


# ---------------------------------------------------------------- risk

def test_high_risk_blocks_are_flagged():
    # (7) Currency/effect/minimap/large-font block -> High.
    m = _mgr()
    assert m.blocks[0].risk_level == "High"
    # Broad catch-all (no Class, no BaseType) -> High.
    assert m.blocks[3].risk_level == "High"
    assert any("broad" in r.lower() for r in m.blocks[3].risk_reasons)


def test_low_risk_for_plain_hidden_block():
    label, reasons = assess_risk(
        header="Hide", section="Hide Layer 1", subsection="",
        classes=["Quivers"], base_types=[], rarity="Any rarity",
        effect=False, minimap=False, sounds_active=False, font_size=0,
        context="Class \"Quivers\"",
    )
    # Broad class with no basetype is Medium at most, never High here.
    assert label in ("Low", "Medium")


# ---------------------------------------------------------------- apply

def test_apply_show_to_hide_only_changes_first_line(temp_filter):
    # (1) + (3) Only the header flips; conditions/sound/color/effect/minimap stay.
    path = temp_filter(SAMPLE)
    m = VisibilityManager()
    lines = _splitlines_keepends(SAMPLE)
    m.load_from_lines(lines, filter_path=path)

    before = list(lines)
    target = m.blocks[0]
    m.set_desired(target, "Hide")
    result = m.apply(create_backup=True)

    assert result.ok and result.applied == 1 and result.to_hide == 1
    # Exactly one line differs, and it is the header.
    diffs = [i for i, (a, b) in enumerate(zip(before, m.lines)) if a != b]
    assert diffs == [target.start_line]
    assert m.lines[target.start_line] == "Hide # $tier->t1\n"
    # Every non-header line preserved exactly.
    assert m.lines[target.start_line + 1:target.end_line] == before[target.start_line + 1:target.end_line]


def test_apply_hide_to_show(temp_filter):
    # (2) Hide -> Show changes only the header word.
    path = temp_filter(SAMPLE)
    lines = _splitlines_keepends(SAMPLE)
    m = VisibilityManager()
    m.load_from_lines(lines, filter_path=path)
    hidden = m.blocks[2]
    assert hidden.current_visibility == "Hide"
    m.set_desired(hidden, "Show")
    before = list(m.lines)
    result = m.apply(create_backup=False)
    assert result.ok and result.to_show == 1
    diffs = [i for i, (a, b) in enumerate(zip(before, m.lines)) if a != b]
    assert diffs == [hidden.start_line]
    assert header_word(m.lines[hidden.start_line]) == "Show"


def test_apply_creates_backup(temp_filter):
    path = temp_filter(SAMPLE)
    m = VisibilityManager()
    m.load_from_lines(_splitlines_keepends(SAMPLE), filter_path=path)
    m.set_desired(m.blocks[1], "Hide")
    result = m.apply(create_backup=True)
    assert result.backup_path and result.backup_path.endswith(".filter")
    import os
    assert os.path.isfile(result.backup_path)


def test_apply_only_affects_selected_blocks(temp_filter):
    # (4) Staging a change on one block leaves the others alone on apply.
    path = temp_filter(SAMPLE)
    m = VisibilityManager()
    lines = _splitlines_keepends(SAMPLE)
    m.load_from_lines(lines, filter_path=path)
    before = list(lines)

    m.set_desired(m.blocks[1], "Hide")  # only the gear block
    m.apply(create_backup=False)

    changed = [i for i, (a, b) in enumerate(zip(before, m.lines)) if a != b]
    assert len(changed) == 1
    # The currency and hide blocks are untouched.
    assert header_word(m.lines[1]) == "Show"   # currency header
    assert "divine.mp3" in "".join(m.lines)


def test_revert_does_not_edit_lines():
    # (5) Reverting pending changes never touches the file lines.
    m = _mgr()
    before = list(m.lines)
    m.set_desired(m.blocks[0], "Hide")
    m.set_desired(m.blocks[1], "Hide")
    assert m.has_pending()
    m.revert_all()
    assert not m.has_pending()
    assert m.lines == before
    for b in m.blocks:
        assert b.desired_visibility == b.current_visibility


def test_filter_does_not_change_hidden_rows():
    # (6) The visible/filter mechanism is read-only — pending changes set on a
    # block survive even though it is not in the "currently visible" subset.
    m = _mgr()
    # Stage a change on a block, then verify the manager still reports it
    # regardless of any UI-side filtering (filtering happens in the view layer,
    # never on the manager's blocks).
    target = m.blocks[2]
    m.set_desired(target, "Show")
    pending = m.pending_changes()
    assert len(pending) == 1
    assert pending[0].start_line == target.start_line
    # Other blocks remain unaffected.
    assert sum(1 for b in m.blocks if b.has_pending_change) == 1


def test_apply_validates_drifted_header(temp_filter):
    # If the target line no longer starts with Show/Hide, it is skipped safely.
    path = temp_filter(SAMPLE)
    m = VisibilityManager()
    m.load_from_lines(_splitlines_keepends(SAMPLE), filter_path=path)
    target = m.blocks[0]
    m.set_desired(target, "Hide")
    # Simulate drift: corrupt the header line in memory.
    m.lines[target.start_line] = "\tClass \"Currency\"\n"
    result = m.apply(create_backup=False)
    assert result.skipped == 1 and result.applied == 0
