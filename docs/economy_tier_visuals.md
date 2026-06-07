# Economy Tier Visual Preset

Instantly restyle a Path of Exile 2 `.filter` by **economy value tier**. The
feature scans every `Show`/`Hide` block, classifies the items it matches into a
value tier (SS → F, plus the special `SS_CHANCE_BASE`), and applies one
consistent visual style per tier across **all** item categories — an S-tier
currency and an S-tier weapon base end up looking the same.

It is purely additive: it never changes how your filter *matches* items, only how
matched items *look*.

## What it does

- **Uniform tier visuals.** Each tier gets one text/background/border colour,
  font size, `PlayEffect`, and `MinimapIcon` from the active template.
- **Five modes** (dropdown in the main window, or **Tools → Economy Tier
  Visuals…**):
  1. `Off` (default — does nothing)
  2. `Preview Only` — shows the diff; **never writes to disk, never makes a backup**
  3. `Apply Economy Tier Visuals`
  4. `Apply Economy Tier Visuals Plus Chance Base Boost`
  5. `Restore Previous Visuals`
- **Chance Base Boost.** Promotes `Rarity Normal` blocks whose `BaseType`
  *exactly* matches a known high-value chancing base (e.g. Sapphire Ring →
  Dream Fragments) to `SS_CHANCE_BASE`. It never promotes Magic/Rare versions and
  never substring-matches a short token like `"Ring"`.
- **Preview before save.** Every apply shows blocks scanned / changed / unchanged
  / skipped, per-tier counts, chance promotions, warnings, and a run fingerprint.
- **Backups.** Before any write, a verified copy is saved to
  `backups/<filter>_before_economy_tier_visuals_<timestamp>.filter`. If the
  backup can't be made or verified, nothing is written.
- **Restore.** `Restore Previous Visuals` reverts the last economy-tier
  operation on the current file. The restore itself is backed up and recorded, so
  it is also undoable.
- **Transfer toggles.** Turn off any of text/background/border/font/PlayEffect/
  MinimapIcon. *Preserve existing sounds* and *Create backup before save* are
  locked on.

## What it does NOT do — sound preservation

**Sound directives are never touched.** `PlayAlertSound`,
`PlayAlertSoundPositional`, `CustomAlertSound`, `CustomAlertSoundOptional`, and
`DisableDropSound` are left byte-for-byte identical, in the same count. A
structural-diff guard runs before every save and **aborts** if any non-visual
line (a sound line, a condition, a comment, block order) would change. Templates
physically cannot contain sound directives.

It also does not: delete comments, reorder blocks, drop unknown directives,
re-flow formatting, change line endings, or regenerate the file. Blocks it
doesn't restyle are preserved byte-for-byte. By default it will not restyle
`Hide` blocks, pure sound-only rules, or blocks it can't confidently classify
(see *confidence*).

## Confidence gating

Each classification has a confidence (`low` / `medium` / `high`). The
**Minimum confidence to apply** selector (default `medium`) controls what gets
written:

- `high` — only confident economy-data matches (named currency/uniques/rules).
- `medium` (default) — the above **plus the filter's own grading** (`$tier` tags
  and recognised sections), so rare/magic/normal gear your filter grades is
  tiered too.
- `low` — also includes the weakest guesses (e.g. generic gems).

Everything is always shown in the Preview regardless of the threshold; the
threshold only controls what gets written.

## How tiers are decided (priority order)

1. Exact `BaseType` chance-base hit (chance-boost mode, `Rarity Normal` only)
2. Exact item/currency/base **name** match against the tier lists
3. `Rarity Unique` → A
4. `WaystoneTier` numeric rule (≥15 → A, 11–14 → B, 6–10 → C, <6 → D)
5. Unmatched `Class "Currency"` → C (never lower without an explicit entry)
6. Gem class → C
7. **The filter's own grading** — a block's explicit `$tier->` tag or recognised
   section name (medium confidence, applied by default). This is how rare/magic/
   normal **weapons and armour** get tiered: they have no fixed market value, so
   the app trusts the grade your filter already assigns them.
8. Otherwise *unknown* → left unchanged (no grade to use)

When a block matches several items, the **highest** tier wins.

### Why some gear isn't tiered

Rare and magic weapons/armour are worth money based on their *random stats*, not
their base — so they aren't in the value lists. The app tiers them only when your
filter already grades them (step 7). If a block has no `$tier->` tag and isn't in
a recognised section, it's left unchanged rather than guessing. Uniques, by
contrast, get tier A automatically (step 3).

## Idempotency

Restyled blocks are stamped with a sentinel comment, e.g.
`# [ETVP tier=S template="High Contrast Economy Tiers" v=1]`. Re-applying the
same preset is a no-op (0 blocks changed) — directives are never stacked or
duplicated.

## Updating the economy data

Economy values drift constantly — **treat the shipped tiers as a starting point
and re-verify before relying on them.** The data lives in
`data/economy_tiers/poe2_0_5_tiers.json` (schema-validated on load; if it's older
than 14 days the UI shows a non-blocking staleness warning).

The runtime is fully offline. To refresh, a maintainer runs the separate tool
(not part of the packaged app):

```bash
python tools/update_economy_tiers.py --check      # validate + report age
python tools/update_economy_tiers.py --sources    # list sources to re-verify
# ...hand-edit tiers/confidence against at least two sources + official trade...
python tools/update_economy_tiers.py --touch      # stamp last_updated/checked_at
```

Confirm chase items against the official Trade 2 site's listing volume and at
least one other source before promoting a tier. **Boss-only uniques cannot be
chanced** and must never appear in `chance_bases`.

## Choosing how each tier looks (in-app editor)

Click **🎨 Edit Tier Styles…** in the Economy Tier dialog to open a visual editor
with one row per tier (SS_CHANCE_BASE, SS, S, A, B, C, D, F). For each tier you
set:

- **Text / Background / Border** colours (click a swatch → colour picker),
- **Font** size,
- **Beam** — the `PlayEffect` ground light (a colour, or `None`) + a **Temp**
  toggle (Temp = only shows briefly on drop),
- **Minimap** — the `MinimapIcon` marker: size (`None`/0/1/2), colour, and shape,

with a live preview per row. Give it a **Preset name** and **Save Preset**. Your
preset is saved as a *named template* in your per-user config dir (alongside the
app's settings), appears in the **Template** dropdown, and can be edited or
deleted later. The shipped **High Contrast Economy Tiers** default can't be
overwritten — saving from it creates a copy.

### Editing the JSON directly (advanced)

The shipped template lives in `data/color_templates/economy_tier_templates.json`
and your presets in `<user-config>/economy_tier/economy_tier_templates.json`. Both
are schema-validated and every colour/effect/minimap token is checked against
PoE's allowed enums on load — a bad token is rejected with a clear message rather
than producing a filter the client silently refuses. Never add a sound directive;
the schema forbids it.

> These files are intentionally separate from the older
> `data/color_templates/templates.json` used by the manual colour editor, which
> has a different schema.

## Restoring

Pick `Restore Previous Visuals` (dropdown or dialog). It reverts the most recent
economy-tier apply on the current file using the disk-persisted operation history
(stored per-user alongside the app's settings). A backup of the pre-restore state
is created first.

## ⚠ Caveat

Economy values change every league and within a league. The tier data is a
relative-value snapshot, never prices. Re-verify before trusting it, and prefer
`Preview Only` first.
