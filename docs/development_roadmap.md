# Development Roadmap

Status of planned engineering work. Items implemented as part of the Economy
Tier Visual Preset feature are marked **done**; the rest are future work.

## Economy Tier Visual Preset

**Done**
- Economy tier classification (SS → F + `SS_CHANCE_BASE`) reading
  `data/economy_tiers/poe2_0_5_tiers.json`.
- Round-trip-fidelity parser (`economy_tier/filter_parser.py`):
  `serialize(parse(text)) == text` byte-for-byte; preserves CRLF/LF, BOM,
  indentation, comments, blank runs; operator-aware (`==` vs substring).
- Five-mode dropdown + Tools-menu dialog; preview-before-save with full diff.
- Idempotent re-apply via sentinel markers + structural-diff guard that aborts on
  any unexpected delta.
- Sound preservation (locked); never edits `PlayAlertSound*` / `CustomAlertSound*`
  / `DisableDropSound`; post-edit validation proves it.
- Verified, spec-named backups; same-dir atomic replace; external-edit detection;
  post-write verification.
- Disk-persisted operation history; `Restore Previous Visuals` (itself undoable).
- Schema-validated, versioned, staleness-warned, confidence-gated data/template
  loading with graceful feature-disable on bad data.
- Color/visual **templates UI**: Template dropdown + per-kind transfer toggles,
  plus an in-app **per-tier style editor** (🎨 Edit Tier Styles…) that saves named
  presets (colours, font, PlayEffect beam, MinimapIcon) to the user's config dir.
- Offline runtime + separate maintainer updater (`tools/update_economy_tiers.py`).
- **Generated `requirements.txt`** (+ `requirements-dev.txt`) from actual imports;
  PyInstaller spec/script bundle the new data + schemas.
- **Automated tests** for parser (round-trip incl. Hypothesis property tests),
  classifier, patcher, save/backup, validator (incl. a negative diff-guard test),
  controller, golden/snapshot corpus, and a 15k-line benchmark — ≥90% coverage on
  the new modules. `mypy --strict`, `ruff`, and `black` clean on the new code.
- **Smart-merge scoring tests** added (the Smart Merge feature itself is unchanged).

## Future work

- **Real undo/redo stack** spanning all editing features (not just the
  economy-tier op-history), with multi-step redo.
- **Manual block mapping** in Smart Merge: let the user hand-pair old/new blocks
  the scorer missed.
- **Optional color / effect / minimap transfer in Smart Merge** (currently it
  transfers sounds only; the executor has a placeholder for colours).
- **Richer color-template editor UI**: the economy-tier per-tier editor exists;
  extend visual editing to the *manual* colour templates too, and add
  drag-to-reorder / import-export of economy-tier presets.
- **Block-splitting** so a mixed block can be split by tier instead of taking the
  highest tier present (only behind an explicit, safe opt-in).
- **Per-category template overrides** if users want, say, currency to deviate from
  the uniform tier look.
