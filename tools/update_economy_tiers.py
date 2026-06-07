#!/usr/bin/env python3
"""Maintainer-only updater for the economy tier data file (A.9).

**This tool is NOT imported by the app at runtime** -- the app reads only the
local JSON. Run it by hand to refresh ``data/economy_tiers/poe2_0_5_tiers.json``
after re-verifying values against the sources recorded in the file.

The economy drifts constantly and no single blog is authoritative. This tool
deliberately does *not* scrape prices automatically -- it helps a human do the
update safely:

  * ``--check``  validate the current file against the schema and report its age.
  * ``--sources`` print the sources to re-verify (open each, confirm against the
    official trade site's listing volume before promoting any chase item).
  * ``--touch [YYYY-MM-DD]`` after you've hand-edited tiers/confidence, stamp
    ``last_updated`` and every ``sources[].checked_at`` with the date (default:
    today), re-validate, and write the file back atomically.

Usage:
    python tools/update_economy_tiers.py --check
    python tools/update_economy_tiers.py --sources
    python tools/update_economy_tiers.py --touch
    python tools/update_economy_tiers.py --touch 2026-07-01
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

# Make the project root importable when run as a script.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from economy_tier.economy_tier_data import load_tier_data  # noqa: E402
from economy_tier.errors import TierDataError  # noqa: E402
from economy_tier.resources import tier_data_path  # noqa: E402


def _check(path: str) -> int:
    try:
        data = load_tier_data(path)
    except TierDataError as exc:
        print(f"INVALID: {exc}")
        return 1
    age = data.age_days()
    print(f"OK: schema v{data.schema_version}, patch {data.patch}, league {data.league}")
    print(
        f"last_updated={data.last_updated} (age: {age} days)"
        + ("  [STALE >14d]" if data.is_stale() else "")
    )
    counts = {t: len(v) for t, v in data.tiers.items()}
    print(f"tier entry counts: {counts}")
    print(f"chance bases: {len(data.chance_base_entries())}")
    return 0


def _sources(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    print("Re-verify against at least two of these PLUS official trade volume:")
    for s in raw.get("sources", []):
        print(f"  - {s.get('name')}: {s.get('url')}  (last checked {s.get('checked_at')})")
    return 0


def _touch(path: str, when: str) -> int:
    try:
        date.fromisoformat(when)
    except ValueError:
        print(f"ERROR: '{when}' is not a valid YYYY-MM-DD date")
        return 1

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    raw["last_updated"] = when
    for s in raw.get("sources", []):
        s["checked_at"] = when

    # Validate by round-tripping through the loader (writes a temp, re-reads).
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
        f.write("\n")
    try:
        load_tier_data(tmp)
    except TierDataError as exc:
        os.remove(tmp)
        print(f"ERROR: edited file is invalid, not saved: {exc}")
        return 1
    os.replace(tmp, path)
    print(f"Stamped last_updated and all sources[].checked_at = {when}")
    print("Remember: tier/confidence values are edited by hand -- this only dates them.")
    return 0


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the economy tier data file.")
    parser.add_argument(
        "--path",
        default=tier_data_path(),
        help="Path to poe2_0_5_tiers.json (default: shipped file)",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="validate + report age")
    group.add_argument("--sources", action="store_true", help="list sources to re-verify")
    group.add_argument(
        "--touch",
        nargs="?",
        const=date.today().isoformat(),
        metavar="YYYY-MM-DD",
        help="stamp last_updated/checked_at (default: today)",
    )
    args = parser.parse_args(argv)

    if args.check:
        return _check(args.path)
    if args.sources:
        return _sources(args.path)
    return _touch(args.path, args.touch)


if __name__ == "__main__":
    raise SystemExit(main())
