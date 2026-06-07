"""Economy Tier Visual Preset feature for the POE2 Filter Sound Editor.

A self-contained, additive feature that scans a loaded ``.filter`` file,
classifies every Show/Hide block into a value tier (SS -> F, plus the special
``SS_CHANCE_BASE``), and applies one uniform visual style per tier across all
item categories -- **without ever touching sound directives, comments, block
order, or formatting**.

Design rules (see the package docstrings for detail):

* The *core* modules (parser, data, classifier, validators) are pure: no Qt/Tk
  imports, no wall-clock, no network. I/O lives only in the loader,
  ``backup_manager``, ``op_history`` and the patcher's save step.
* Editing is line-level surgical. For any block this feature does not touch,
  ``serialize(parse(text)) == text`` byte-for-byte.
* The runtime never hits the network -- it reads only local JSON shipped in
  ``data/``. ``tools/update_economy_tiers.py`` (outside the import graph)
  refreshes that data offline for maintainers.
"""

from __future__ import annotations

# Single source of truth for the on-disk formats this feature reads/writes.
SCHEMA_VERSION = 1

# Sentinel marker comment stamped on blocks this feature has restyled, so a
# re-apply is a deterministic no-op and Restore can find what it changed.
SENTINEL_PREFIX = "# [ETVP"
SENTINEL_VERSION = 1

__all__ = ["SCHEMA_VERSION", "SENTINEL_PREFIX", "SENTINEL_VERSION"]
