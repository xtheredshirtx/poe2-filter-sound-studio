"""Performance: classify + diff a 15k-line filter in well under a second (A.10)."""

from __future__ import annotations

import sys
import time

from economy_tier.economy_tier_classifier import ClassifyOptions, classify
from economy_tier.economy_tier_data import Confidence, load_tier_data
from economy_tier.filter_parser import parse
from economy_tier.filter_validator import validate
from economy_tier.filter_visual_patcher import patch
from economy_tier.visual_template_loader import load_templates

DATA = load_tier_data()
TPL = load_templates().get()


def _big_filter(n_blocks: int) -> str:
    chunks = []
    for i in range(n_blocks):
        chunks.append(
            f'Show\n\tClass "Currency"\n\tBaseType == "Divine Orb"\n'
            f"\tItemLevel >= {i % 80}\n\tSetFontSize 30\n\tPlayAlertSound 1 300\n\n"
        )
    return "".join(chunks)


def test_15k_line_filter_under_one_second():
    text = _big_filter(2200)  # ~7 lines/block -> ~15k lines
    assert text.count("\n") >= 15000

    start = time.perf_counter()
    doc = parse(text)
    opts = ClassifyOptions(min_confidence=Confidence.low)
    res = classify(doc, DATA, opts)
    applicable = [c for c in res.classifications if c.applicable(opts.min_confidence)]
    pr = patch(doc, applicable, TPL)
    validate(text, "".join(pr.new_lines), pr.edited_block_indices)
    elapsed = time.perf_counter() - start

    # coverage.py / a debugger installs a trace function that inflates timing
    # several-fold; only enforce the real <1s budget when running untraced.
    budget = 8.0 if sys.gettrace() is not None else 1.0
    assert elapsed < budget, f"pipeline took {elapsed:.3f}s for {len(doc.blocks)} blocks"
