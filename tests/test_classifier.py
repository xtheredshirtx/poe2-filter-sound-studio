"""Economy classification logic (priority order, gating, chance promotion)."""

from __future__ import annotations

from economy_tier.economy_tier_classifier import (
    ClassifyOptions,
    Status,
    classify,
    compute_fingerprint,
)
from economy_tier.economy_tier_data import Confidence, load_tier_data
from economy_tier.filter_parser import parse

DATA = load_tier_data()


def _classify(text, **opts):
    return classify(parse(text), DATA, ClassifyOptions(**opts))


def test_currency_named_match():
    res = _classify('Show\n\tBaseType == "Divine Orb"\n', min_confidence=Confidence.low)
    c = res.classifications[0]
    assert c.status == Status.CLASSIFIED and c.tier == "S"


def test_highest_tier_wins():
    # Mirror (SS) beats Divine (S) when both appear.
    res = _classify(
        'Show\n\tBaseType "Divine Orb" "Mirror of Kalandra"\n', min_confidence=Confidence.low
    )
    assert res.classifications[0].tier == "SS"


def test_chance_promotion_only_when_enabled():
    text = 'Show\n\tRarity Normal\n\tBaseType "Sapphire Ring"\n'
    off = _classify(text, enable_chance_boost=False, min_confidence=Confidence.low)
    on = _classify(text, enable_chance_boost=True, min_confidence=Confidence.low)
    assert off.classifications[0].tier != "SS_CHANCE_BASE"
    assert on.classifications[0].tier == "SS_CHANCE_BASE"
    assert on.classifications[0].is_chance_promotion is True


def test_chance_not_promoted_for_magic():
    text = 'Show\n\tRarity Magic\n\tBaseType "Sapphire Ring"\n'
    res = _classify(text, enable_chance_boost=True, min_confidence=Confidence.low)
    assert res.classifications[0].tier != "SS_CHANCE_BASE"
    assert any("not Rarity Normal" in w for w in res.warnings)


def test_substring_does_not_promote():
    # "Ring" must never substring-promote to a chance base (A.3).
    text = 'Show\n\tRarity Normal\n\tBaseType "Ring"\n'
    res = _classify(text, enable_chance_boost=True, min_confidence=Confidence.low)
    assert res.classifications[0].tier != "SS_CHANCE_BASE"


def test_hidden_skipped():
    res = _classify('Hide\n\tBaseType "Scroll of Wisdom"\n', skip_hidden=True)
    assert res.classifications[0].status == Status.SKIPPED_HIDDEN


def test_hidden_classified_when_not_skipping():
    res = _classify(
        'Hide\n\tBaseType "Scroll of Wisdom"\n', skip_hidden=False, min_confidence=Confidence.low
    )
    assert res.classifications[0].status == Status.CLASSIFIED
    assert res.classifications[0].tier == "F"


def test_sound_only_skipped():
    res = _classify("Show\n\tPlayAlertSound 1 300\n")
    assert res.classifications[0].status == Status.SKIPPED_SOUND_ONLY


def test_waystone_rule():
    assert _classify("Show\n\tWaystoneTier >= 15\n").classifications[0].tier == "A"
    assert _classify("Show\n\tWaystoneTier 3\n").classifications[0].tier == "D"


def test_unique_rule():
    res = _classify("Show\n\tRarity Unique\n")
    assert res.classifications[0].tier == "A"


def test_currency_default():
    res = _classify('Show\n\tClass "Currency"\n\tBaseType "Unknownium"\n')
    assert res.classifications[0].tier == "C"


def test_unknown_unchanged_by_default():
    # A bare block with no signals and heuristic off -> unknown.
    res = _classify('Show\n\tBaseType "Mystery Plate"\n', use_heuristic_fallback=False)
    assert res.classifications[0].status == Status.UNKNOWN


def test_confidence_gating():
    # Heuristic fallback is low-confidence; not applicable at medium.
    res = _classify(
        'Show\n\tBaseType "Mystery Plate"\n',
        use_heuristic_fallback=True,
        min_confidence=Confidence.medium,
    )
    c = res.classifications[0]
    assert c.status == Status.CLASSIFIED
    assert c.applicable(Confidence.medium) is False
    assert c.applicable(Confidence.low) is True


def test_fingerprint_determinism_and_sensitivity():
    text = 'Show\n\tBaseType == "Divine Orb"\n'
    o1 = ClassifyOptions(enable_chance_boost=False)
    o2 = ClassifyOptions(enable_chance_boost=True)
    fp1 = compute_fingerprint(text, DATA.fingerprint, "tpl", o1)
    fp1b = compute_fingerprint(text, DATA.fingerprint, "tpl", o1)
    fp2 = compute_fingerprint(text, DATA.fingerprint, "tpl", o2)
    assert fp1 == fp1b
    assert fp1 != fp2
