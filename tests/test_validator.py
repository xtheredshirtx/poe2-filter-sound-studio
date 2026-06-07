"""Post-edit validation + structural-diff guard, incl. the negative test (A.2/A.10)."""

from __future__ import annotations

import pytest

from economy_tier.economy_tier_classifier import ClassifyOptions, classify
from economy_tier.economy_tier_data import Confidence, load_tier_data
from economy_tier.errors import ValidationError
from economy_tier.filter_parser import parse
from economy_tier.filter_validator import validate
from economy_tier.filter_visual_patcher import patch
from economy_tier.visual_template_loader import load_templates

DATA = load_tier_data()
TPL = load_templates().get()
BASE = 'Show\n\tClass "Currency"\n\tBaseType == "Divine Orb"\n\tPlayAlertSound 1 300\n'


def _patch(text):
    doc = parse(text)
    opts = ClassifyOptions(min_confidence=Confidence.low)
    res = classify(doc, DATA, opts)
    applicable = [c for c in res.classifications if c.applicable(opts.min_confidence)]
    pr = patch(doc, applicable, TPL)
    return pr


def test_valid_edit_passes():
    pr = _patch(BASE)
    report = validate(BASE, "".join(pr.new_lines), pr.edited_block_indices)
    assert report.edited_blocks == 1
    assert report.sound_lines == 1


def test_negative_injected_mutation_aborts():
    """Inject a non-visual mutation into an edited block -> guard must fire."""
    pr = _patch(BASE)
    lines = list(pr.new_lines)
    # Corrupt a condition line (the sound line) inside the edited block.
    for i, ln in enumerate(lines):
        if "PlayAlertSound 1 300" in ln:
            lines[i] = "\tPlayAlertSound 99 999\n"
            break
    with pytest.raises(ValidationError):
        validate(BASE, "".join(lines), pr.edited_block_indices)


def test_block_count_change_aborts():
    pr = _patch(BASE)
    new = "".join(pr.new_lines) + 'Show\n\tClass "Extra"\n'
    with pytest.raises(ValidationError):
        validate(BASE, new, pr.edited_block_indices)


def test_untouched_block_changed_aborts():
    pr = _patch(BASE)
    # Pretend nothing was scheduled, but content differs -> guard fires.
    with pytest.raises(ValidationError):
        validate(BASE, "".join(pr.new_lines), set())


def test_condition_change_aborts():
    pr = _patch(BASE)
    lines = list(pr.new_lines)
    for i, ln in enumerate(lines):
        if "Divine Orb" in ln:
            lines[i] = '\tBaseType == "Chaos Orb"\n'
            break
    with pytest.raises(ValidationError):
        validate(BASE, "".join(lines), pr.edited_block_indices)
