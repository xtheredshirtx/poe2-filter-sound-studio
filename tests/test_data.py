"""Economy tier data loading, schema validation, staleness (A.5)."""

from __future__ import annotations

import json
from datetime import date

import pytest

from economy_tier.economy_tier_data import (
    Confidence,
    higher_tier,
    load_tier_data,
    tier_rank,
)
from economy_tier.errors import TierDataError
from economy_tier.resources import tier_data_path


def test_load_shipped_data():
    td = load_tier_data()
    assert td.patch == "0.5.0"
    assert "Mirror of Kalandra" in [e.name for e in td.tiers["SS"]]
    assert any(e.name == "Sapphire Ring" for e in td.chance_base_entries())
    assert td.fingerprint  # non-empty


def test_fingerprint_stable():
    assert load_tier_data().fingerprint == load_tier_data().fingerprint


def test_confidence_ordering():
    assert Confidence.low < Confidence.medium < Confidence.high
    assert Confidence.parse("high") == Confidence.high
    with pytest.raises(TierDataError):
        Confidence.parse("bogus")


def test_tier_rank_and_higher():
    assert tier_rank("SS") > tier_rank("A") > tier_rank("F")
    assert higher_tier("A", "C") == "A"
    assert higher_tier("F", "SS") == "SS"
    assert tier_rank("nonsense") == -1


def test_staleness():
    td = load_tier_data()
    # Pretend "today" is far in the future -> stale.
    assert td.is_stale(14, today=date(2099, 1, 1)) is True
    assert td.age_days(today=date(2099, 1, 1)) > 14


def test_bad_schema_version(tmp_path):
    raw = json.loads(open(tier_data_path(), encoding="utf-8").read())
    raw["schema_version"] = 999
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(TierDataError):
        load_tier_data(str(p))


def test_schema_violation(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")  # missing required
    with pytest.raises(TierDataError):
        load_tier_data(str(p))


def test_missing_file(tmp_path):
    with pytest.raises(TierDataError):
        load_tier_data(str(tmp_path / "nope.json"))


def test_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(TierDataError):
        load_tier_data(str(p))
