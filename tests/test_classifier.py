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
    # The skip is reported as ONE aggregated note, not one warning per block.
    assert len(res.warnings) == 1
    assert "Rarity Normal" in res.warnings[0]


def test_chance_not_normal_warning_is_aggregated():
    # Many non-Normal blocks listing chance bases -> still a single warning line.
    text = "".join('Show\n\tRarity Magic\n\tBaseType "Sapphire Ring"\n' for _ in range(20))
    res = _classify(text, enable_chance_boost=True, min_confidence=Confidence.low)
    assert len(res.warnings) == 1
    assert "20 block(s)" in res.warnings[0]


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


def test_no_grading_signal_stays_unknown():
    # No $tier tag and no recognised section -> the filter doesn't grade it, so
    # we leave it unchanged rather than inventing a tier.
    res = _classify(
        'Show\n\tRarity Rare\n\tBaseType "Mystery Plate"\n',
        use_heuristic_fallback=True,
        min_confidence=Confidence.low,
    )
    assert res.classifications[0].status == Status.UNKNOWN


def test_uncut_gem_scales_by_level():
    # Higher gem level -> higher tier, monotonically (no inversion).
    def tier_for(gemlevel_line):
        text = f'Show\n\t{gemlevel_line}\n\tBaseType "Uncut Skill Gem"\n'
        return _classify(text, min_confidence=Confidence.medium).classifications[0].tier

    assert tier_for("GemLevel >= 20") == "A"
    assert tier_for("GemLevel 19") == "B"
    assert tier_for("GemLevel 18") == "C"
    assert tier_for("GemLevel 16") == "D"
    assert tier_for("GemLevel 14") == "F"
    # No GemLevel -> treated as the low catch-all, not a high tier.
    no_level = _classify('Show\n\tBaseType "Uncut Spirit Gem"\n', min_confidence=Confidence.medium)
    assert no_level.classifications[0].tier == "F"


def test_tier_tag_number_not_used_as_rank():
    # A $tier->skill20 tag must NOT be read as "tier 20 -> junk". With no
    # recognised section and not a gem base, the block is simply unknown.
    res = _classify(
        'Show # $type->foo $tier->skill20\n\tBaseType "Random Thing"\n',
        use_heuristic_fallback=True,
        min_confidence=Confidence.low,
    )
    assert res.classifications[0].status == Status.UNKNOWN


def test_section_grading_applied_by_default():
    # Grading can also come from a recognised section name.
    text = "# [[5000]] Waystones\n" 'Show\n\tClass "Foo"\n\tBaseType "Bar"\n'
    res = _classify(text, use_heuristic_fallback=True, min_confidence=Confidence.medium)
    c = res.classifications[0]
    assert c.status == Status.CLASSIFIED
    assert c.applicable(Confidence.medium) is True


def test_fingerprint_determinism_and_sensitivity():
    text = 'Show\n\tBaseType == "Divine Orb"\n'
    o1 = ClassifyOptions(enable_chance_boost=False)
    o2 = ClassifyOptions(enable_chance_boost=True)
    fp1 = compute_fingerprint(text, DATA.fingerprint, "tpl", o1)
    fp1b = compute_fingerprint(text, DATA.fingerprint, "tpl", o1)
    fp2 = compute_fingerprint(text, DATA.fingerprint, "tpl", o2)
    assert fp1 == fp1b
    assert fp1 != fp2
