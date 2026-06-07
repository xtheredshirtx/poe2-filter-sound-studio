"""Visual patching: correctness, sentinel, idempotency, transfer options (A.2)."""

from __future__ import annotations

from economy_tier.economy_tier_classifier import ClassifyOptions, classify
from economy_tier.economy_tier_data import Confidence, load_tier_data
from economy_tier.filter_parser import parse
from economy_tier.filter_visual_patcher import TransferOptions, patch
from economy_tier.visual_template_loader import load_templates

DATA = load_tier_data()
TPL = load_templates().get()


def _apply(text, transfer=None, **opts):
    options = ClassifyOptions(min_confidence=Confidence.low, **opts)
    doc = parse(text)
    res = classify(doc, DATA, options)
    applicable = [c for c in res.classifications if c.applicable(options.min_confidence)]
    return patch(doc, applicable, TPL, transfer or TransferOptions())


def test_applies_and_inserts_sentinel():
    pr = _apply('Show\n\tBaseType == "Divine Orb"\n\tSetFontSize 10\n')
    text = "".join(pr.new_lines)
    assert "# [ETVP tier=S" in text
    assert "SetFontSize 43" in text  # S tier font
    assert pr.changed_count == 1


def test_sound_lines_never_touched():
    pr = _apply('Show\n\tBaseType == "Divine Orb"\n\tPlayAlertSound 1 300\n')
    text = "".join(pr.new_lines)
    assert text.count("PlayAlertSound 1 300") == 1
    assert "PlayAlertSound" in [s.split()[0] for s in pr.patches[0].sounds_preserved]


def test_idempotent_reapply():
    text = 'Show\n\tBaseType == "Divine Orb"\n'
    once = "".join(_apply(text).new_lines)
    twice = _apply(once)
    assert twice.changed_count == 0
    assert "".join(twice.new_lines) == once


def test_transfer_options_drop_kinds():
    pr = _apply(
        'Show\n\tBaseType == "Divine Orb"\n',
        transfer=TransferOptions(
            apply_text=True,
            apply_bg=False,
            apply_border=False,
            apply_font=False,
            apply_effect=False,
            apply_minimap=False,
        ),
    )
    text = "".join(pr.new_lines)
    assert "SetTextColor" in text
    assert "SetBackgroundColor" not in text
    assert "PlayEffect" not in text


def test_unchanged_blocks_byte_identical():
    text = 'Show\n\tBaseType == "Divine Orb"\nShow\n\tBaseType "Mystery"\n'
    pr = _apply(text, use_heuristic_fallback=False)
    # Only block 0 classifies; block 1 stays exactly as written.
    new = "".join(pr.new_lines)
    assert 'Show\n\tBaseType "Mystery"\n' in new
