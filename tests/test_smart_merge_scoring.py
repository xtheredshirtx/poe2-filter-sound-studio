"""Smart Merge scoring tests. The feature itself is unmodified; these lock in
its scoring behaviour as required by the spec (existing Smart Merge must keep
passing)."""

from __future__ import annotations

import pytest

from core.data_models import FilterBlock
from features.smart_merge import MatchFinder, SimilarityScorer


def _block(
    header="Show",
    rarity="Rarity Rare",
    classes=None,
    bases=None,
    context=None,
    sounds=None,
    start=0,
):
    return FilterBlock(
        header=header,
        start_idx=start,
        end_idx=start + 1,
        rarity=rarity,
        class_values=classes or [],
        basetype_values=bases or [],
        context_lines=context or [],
        sound_lines=sounds or [],
    )


def test_weights_must_sum_to_one():
    SimilarityScorer()  # default weights are valid
    with pytest.raises(ValueError):
        SimilarityScorer(weights={"rarity": 0.5, "class": 0.1})


def test_identical_blocks_score_one():
    s = SimilarityScorer()
    a = _block(classes=["Ring"], bases=["Sapphire Ring"], context=["ItemLevel >= 50"])
    b = _block(classes=["Ring"], bases=["Sapphire Ring"], context=["ItemLevel >= 50"])
    assert s.calculate_similarity(a, b) == pytest.approx(1.0)


def test_rarity_mismatch_lowers_score():
    s = SimilarityScorer()
    a = _block(rarity="Rarity Rare", classes=["Ring"])
    b = _block(rarity="Rarity Normal", classes=["Ring"])
    assert s.calculate_similarity(a, b) < 1.0


def test_classify_match_thresholds():
    s = SimilarityScorer()
    assert s.classify_match(0.95) == "exact"
    assert s.classify_match(0.75) == "high"
    assert s.classify_match(0.55) == "medium"
    assert s.classify_match(0.10) == "low"


def test_jaccard_via_class():
    s = SimilarityScorer()
    a = _block(classes=["Ring", "Amulet"])
    b = _block(classes=["Ring"])
    # Shared 1 of 2 union -> class component contributes partial score.
    bd = s.get_breakdown(a, b)
    assert 0 < bd["class"] < s.weights["class"]


def test_match_finder_only_matches_blocks_with_sound():
    finder = MatchFinder()
    old = [
        _block(classes=["Ring"], bases=["Sapphire Ring"], sounds=["PlayAlertSound 1 300"]),
        _block(classes=["Belt"], bases=["Heavy Belt"]),  # no sound -> ignored
    ]
    new = [_block(classes=["Ring"], bases=["Sapphire Ring"])]
    matches = finder.find_matches(old, new, min_confidence=0.5)
    assert len(matches) == 1
    stats = finder.get_statistics(matches)
    assert stats["total"] == 1 and stats["pending"] == 1
