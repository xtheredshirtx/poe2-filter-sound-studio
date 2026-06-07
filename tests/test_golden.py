"""Golden/snapshot tests: a real fixture restyled under several option combos.

Each combo's output is committed under ``fixtures/expected/``. Run with the env
var ``ETVP_REGEN=1`` to regenerate the snapshots after an intentional change.
"""

from __future__ import annotations

import os

import pytest

from economy_tier.economy_tier_classifier import ClassifyOptions, classify
from economy_tier.economy_tier_data import Confidence, load_tier_data
from economy_tier.filter_parser import parse
from economy_tier.filter_validator import validate
from economy_tier.filter_visual_patcher import patch
from economy_tier.visual_template_loader import load_templates
from tests.conftest import FIXTURES, fixture_text

DATA = load_tier_data()
TPL = load_templates().get()
EXPECTED_DIR = os.path.join(FIXTURES, "expected")

COMBOS = {
    "apply_medium": dict(enable_chance_boost=False, min_confidence=Confidence.medium),
    "apply_low": dict(enable_chance_boost=False, min_confidence=Confidence.low),
    "apply_chance_low": dict(enable_chance_boost=True, min_confidence=Confidence.low),
}


def _run(text: str, **opts) -> str:
    options = ClassifyOptions(**opts)
    doc = parse(text)
    res = classify(doc, DATA, options)
    applicable = [c for c in res.classifications if c.applicable(options.min_confidence)]
    pr = patch(doc, applicable, TPL)
    new_text = "".join(pr.new_lines)
    # Every golden output must pass the structural guard.
    validate(text, new_text, pr.edited_block_indices)
    return new_text


@pytest.mark.parametrize("combo", sorted(COMBOS))
def test_golden(combo):
    text = fixture_text("sample_basic.filter")
    produced = _run(text, **COMBOS[combo])
    expected_path = os.path.join(EXPECTED_DIR, f"sample_basic.{combo}.filter")

    if os.environ.get("ETVP_REGEN") == "1":
        os.makedirs(EXPECTED_DIR, exist_ok=True)
        with open(expected_path, "w", encoding="utf-8", newline="") as f:
            f.write(produced)
        pytest.skip(f"regenerated {expected_path}")

    with open(expected_path, encoding="utf-8") as f:
        expected = f.read()
    assert produced == expected
