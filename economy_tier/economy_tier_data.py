"""Load and model the economy tier data file (A.5).

Reads ``data/economy_tiers/poe2_0_5_tiers.json`` (or a supplied path),
validates it against the shipped JSON Schema, and exposes a typed, queryable
:class:`TierData` object. Pure aside from the single file read in
:func:`load_tier_data`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import IntEnum
from typing import Any

from economy_tier import SCHEMA_VERSION
from economy_tier.errors import TierDataError
from economy_tier.resources import tier_data_path
from economy_tier.schema_validation import load_and_validate

# Canonical tier order, strongest first. SS_CHANCE_BASE is handled as a special
# promotion target and is treated visually as >= SS.
TIER_ORDER = ("SS_CHANCE_BASE", "SS", "S", "A", "B", "C", "D", "F")

# Rank for "highest tier wins" comparisons (higher rank == more valuable).
_TIER_RANK = {name: len(TIER_ORDER) - i for i, name in enumerate(TIER_ORDER)}


def tier_rank(tier: str) -> int:
    """Numeric rank for a tier name; unknown tiers rank lowest."""
    return _TIER_RANK.get(tier, -1)


def higher_tier(a: str, b: str) -> str:
    """Return whichever of two tier names is more valuable."""
    return a if tier_rank(a) >= tier_rank(b) else b


class Confidence(IntEnum):
    """Ordered confidence levels (low < medium < high)."""

    low = 0
    medium = 1
    high = 2

    @classmethod
    def parse(cls, value: str) -> Confidence:
        try:
            return cls[value]
        except KeyError as exc:
            raise TierDataError(f"Unknown confidence level: {value!r}") from exc


@dataclass(frozen=True)
class TierEntry:
    """One named item/currency/base with its tier and confidence."""

    name: str
    tier: str
    confidence: Confidence
    match_type: str = ""
    reason: str = ""
    source_refs: tuple[str, ...] = ()


@dataclass
class TierData:
    """The full, validated economy dataset."""

    schema_version: int
    patch: str
    league: str
    last_updated: str
    notes: str
    # tier name -> list of entries (e.g. "SS" -> [...])
    tiers: dict[str, list[TierEntry]]
    # chance-base bucket -> entries (e.g. "SS_CHANCE_BASE" -> [...])
    chance_bases: dict[str, list[TierEntry]]
    rules: list[dict[str, str]] = field(default_factory=list)
    fingerprint: str = ""

    # ----- lookups --------------------------------------------------------

    def all_named_entries(self) -> list[TierEntry]:
        """Every regular (non-chance-base) tier entry, strongest tier first."""
        out: list[TierEntry] = []
        for tier in TIER_ORDER:
            out.extend(self.tiers.get(tier, []))
        return out

    def chance_base_entries(self) -> list[TierEntry]:
        out: list[TierEntry] = []
        for entries in self.chance_bases.values():
            out.extend(entries)
        return out

    # ----- staleness ------------------------------------------------------

    def age_days(self, today: date | None = None) -> int | None:
        """Days since ``last_updated``; None if the date can't be parsed."""
        try:
            updated = datetime.strptime(self.last_updated, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None
        ref = today or date.today()
        return (ref - updated).days

    def is_stale(self, threshold_days: int = 14, today: date | None = None) -> bool:
        age = self.age_days(today)
        return age is not None and age > threshold_days


def _entry_from_dict(d: dict[str, Any]) -> TierEntry:
    return TierEntry(
        name=str(d["name"]),
        tier=str(d["tier"]),
        confidence=Confidence.parse(str(d["confidence"])),
        match_type=str(d.get("match_type", "")),
        reason=str(d.get("reason", "")),
        source_refs=tuple(d.get("source_refs", []) or ()),
    )


def load_tier_data(path: str | None = None) -> TierData:
    """Load, schema-validate, and parse the economy tier data file.

    Raises :class:`TierDataError` on any problem (missing/bad/old-schema file).
    """
    data_path = path or tier_data_path()
    data = load_and_validate(data_path, "tiers", TierDataError)

    version = int(data.get("schema_version", 0))
    if version != SCHEMA_VERSION:
        raise TierDataError(
            f"Unsupported tier data schema_version {version} "
            f"(this build supports {SCHEMA_VERSION}). Update the app or the data file."
        )

    tiers: dict[str, list[TierEntry]] = {}
    for tier_name, entries in (data.get("tiers") or {}).items():
        tiers[tier_name] = [_entry_from_dict(e) for e in entries]

    chance_bases: dict[str, list[TierEntry]] = {}
    for bucket, entries in (data.get("chance_bases") or {}).items():
        chance_bases[bucket] = [_entry_from_dict(e) for e in entries]

    # Stable fingerprint of the data for the run-fingerprint (A.6).
    fp = hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    return TierData(
        schema_version=version,
        patch=str(data.get("patch", "")),
        league=str(data.get("league", "")),
        last_updated=str(data.get("last_updated", "")),
        notes=str(data.get("notes", "")),
        tiers=tiers,
        chance_bases=chance_bases,
        rules=list(data.get("rules", []) or []),
        fingerprint=fp,
    )


__all__ = [
    "TIER_ORDER",
    "tier_rank",
    "higher_tier",
    "Confidence",
    "TierEntry",
    "TierData",
    "load_tier_data",
]
