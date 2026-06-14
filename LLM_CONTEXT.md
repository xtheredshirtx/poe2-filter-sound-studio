# LLM Context Log

Drop-in briefing for any future LLM picking up this project. Read this first,
then `CLAUDE.md` (working preferences), then dig into code. Everything below
documents what's in the repo *as of the end of the 2026-06-13 session*.

---

## 1. What this project is

**POE2 Filter Sound Studio** — a Windows desktop app (CustomTkinter) that
edits Path of Exile 2 `.filter` files. The original feature set is sound
replacement / volume tuning / category browsing across a filter's
Show/Hide blocks. This session added a thick layer of *visual* and
*safety* tools on top.

- Entry point: [main.py](main.py) — `FilterSoundEditor` class.
- Core parsing: [core/parser.py](core/parser.py) → `FilterParser` + regexes
  for sounds, colors, sections.
- Block data model: [core/data_models.py](core/data_models.py) → `FilterBlock`.
- Persistent app settings: [core/settings.py](core/settings.py) →
  `AppSettings` dataclass + JSON at `%APPDATA%/POE2FilterSoundEditor/settings.json`.
- File IO: [core/file_operations.py](core/file_operations.py) → `load_filter_file`,
  `save_filter_file` (atomic tmp+replace), `make_backup` (timestamped + rotated).

The user (`xtheredshirtx`) does not use git/GitHub directly — Claude handles
all VCS via the `gh` CLI per `CLAUDE.md`.

---

## 2. Features added this session

In the order they were built:

### 2.1 Filter Compatibility Check
**Goal:** when the game ships an update or the user loads a foreign filter,
detect unknown/renamed commands and offer auto-fixes without the user having
to ask an LLM each time.

- [core/compatibility.py](core/compatibility.py) — `FilterCompatibilityChecker`,
  `MigrationRulesEngine`, `CompatibilityReport`, `CompatibilityIssue`.
  Validates POE2 command set, RGB ranges, volume ranges, orphan actions
  outside Show/Hide.
- [data/migration_rules.json](data/migration_rules.json) — user-editable
  rule table. Schema documented inside the file itself in `_rule_schema`.
  Four rule actions: `command`, `regex`, `allow`, `remove`.
- [ui/compatibility_dialog.py](ui/compatibility_dialog.py) — modal showing
  detected issues, per-row Fix? toggles, bulk Select All Fixable, Edit Rules
  File button.
- Wired into both load paths in `main.py` + manual Tools → Check Filter
  Compatibility.
- Setting: `AppSettings.auto_check_compatibility` (default `True`).

**Important user-facing affordance:** when no fix exists in the rules, the
issue is flagged with `auto_fixable=False` and the user is pointed at
`migration_rules.json`. The user is expected to add their own rules over
time — no LLM round-trip needed for syntax changes.

### 2.2 On-load backup snapshots
**Goal:** every load creates a pristine backup before any tool can mutate
the file.

- [core/file_operations.py:48](core/file_operations.py:48) — `make_backup`
  extended with `label` (so `_load_` and `_backup_` snapshots rotate
  independently) and `skip_if_identical` (so reloading an unchanged file
  doesn't pile up duplicate copies).
- Same-second collision bug fixed with `-2`, `-3` suffix tie-break.
- Hooked into `load_filter` and `load_filter_from_path` via
  `_snapshot_on_load()`.
- Setting: `AppSettings.auto_backup_on_load` (default `True`).
- Backups land in `<filter>_backups/` next to the filter file. Files are
  named `<name>_load_<timestamp>.filter` vs `<name>_backup_<timestamp>.filter`.

### 2.3 Visual Tools — emphasis + randomizer
**Goal:** make valuable items visually pop and let users randomize the
whole filter into something fresh, *without* changing what shows up.

- [features/visual_emphasis.py](features/visual_emphasis.py) — the engine.
  - `ValueTier` enum (MYTHIC > TOP > HIGH > MID > LOW > JUNK; plus HIDDEN
    sentinel for Hide blocks that we never restyle).
  - `classify_block()` — reads three signals in order: Hide header,
    `$tier->tN` inline tag, then `_SECTION_KEYWORDS` substring match.
    No live market data. No internet calls.
  - `BlockStyle` dataclass — every field optional; only set fields get
    written.
  - `iter_blocks(lines)` — generator yielding `(start, end, header, section,
    block_lines)`. Tracks the latest `# [[NNNN]] Title` section header so
    classify_block can use it.
  - `apply_style_to_block` — rewrites lines in place, preserves indent and
    newline style; insertion point skips trailing blanks AND section/
    subsection comments (which `iter_blocks` includes between blocks).
  - Two stylers: `EmphasisStyler` (deterministic, preset-driven) and
    `RandomizerStyler` (seeded, 15 curated palettes).
  - `StyleChange` is the planned restyle for one block — gets `signature`,
    `has_override`, and `base_tier` populated when overrides are involved.
- Touches ONLY: `SetTextColor`, `SetBorderColor`, `SetBackgroundColor`,
  `SetFontSize`, `PlayEffect`, `MinimapIcon`. Never touches Show/Hide,
  conditions, or sound commands. Hide blocks are skipped wholesale.

### 2.4 JSON-backed presets
**Goal:** edit tier styling and randomizer palettes without code edits.

- [data/visual_presets.json](data/visual_presets.json) (created on first
  Edit click via `write_default_presets_file()`).
- `load_visual_presets()` is *forgiving*: missing fields fall back to code
  defaults per-tier; malformed palettes are dropped silently with a print;
  missing file = code defaults entirely.
- Schema is self-documenting via `_notes` keys in the seed file (lists all
  valid POE2 named colors and minimap shapes).

### 2.5 Visual Tools dialog (UI)
- [ui/visual_tools_dialog.py](ui/visual_tools_dialog.py) — two tabs
  (Emphasize by Tier, Randomize Visuals). Shared toolbar with Edit Presets
  File / Reload at top.
- Both tabs preview the plan before committing.
- Randomizer has seed input for reproducibility.
- Tier swatches **are clickable** — opens the tier detail dialog (see 2.7).

### 2.6 Per-filter user overrides
**Goal:** "the app remembers my customizations for each filter."

- [core/user_overrides.py](core/user_overrides.py) — sidecar file at
  `<filter>.filterstudio.json`.
- `UserOverrides` has two override layers:
  - `tier_presets: Dict[ValueTier, BlockStyle]` — "for this filter, my MYTHIC
    looks like X."
  - `block_overrides: Dict[str, BlockOverride]` — keyed by stable signature.
    Each `BlockOverride` can move the block to a different tier and/or pin
    a fully custom style.
- `block_signature(block_lines)` — `Show | rarity=Unique | base=heavy belt`.
  Stable across line shuffles, styling changes, comments. Built only from
  the Show/Hide word + Rarity + sorted Class + sorted BaseType.
- **Resolution priority** in `EmphasisStyler.plan()` (highest first):
  1. Per-block style override
  2. Per-block tier override (mapped via tier preset)
  3. Tier preset override
  4. Code default preset

### 2.7 In-app tier detail dialog
**Goal:** click a tier box, see what's in it, edit colors/effects/minimap,
reassign individual blocks — all without touching JSON.

- [ui/tier_detail_dialog.py](ui/tier_detail_dialog.py) — opens from a tier
  swatch click. Includes:
  - Live preview (raw tk.Frame so colors paint as POE2 would).
  - Text/Border/Background color rows backed by existing `ColorPickerDialog`.
  - Font slider 18–45.
  - PlayEffect (None + 11 colors + Temp checkbox).
  - MinimapIcon (size + color + shape with None sentinel).
  - Block list with right-click "Move to <tier>" and "Reset to heuristic tier".
  - "Reset to default" and "Remove tier override" actions.
- Saves to sidecar on click; `on_close` callback re-plans the parent dialog.

### 2.8a Application logging
**Goal:** "when something breaks, the user can grab one file and hand it to
an LLM."

- [core/app_logging.py](core/app_logging.py) — `init_logging()`,
  `get_logger()`, `get_log_path()`, `log_section()`, `shutdown()`.
- Uses `logging.handlers.RotatingFileHandler` (5 MB × 3 backups).
- Writes to `%APPDATA%/POE2FilterSoundEditor/app_debug.log` — same folder as
  `settings.json`. Outside the repo entirely, so it cannot be committed
  even by accident.
- Hooks `sys.excepthook` and `tk.Tk.report_callback_exception` so the two
  classes of silent-death paths get captured automatically.
- Help menu surfaces "Open Debug Log" and "Open Log Folder" so users can
  send the file with one click.
- `print()` debug calls in `core/compatibility.py`, `core/user_overrides.py`,
  and `features/visual_emphasis.py` have all been converted to logger calls
  so they appear in the same log file.

### 2.8 Conflict-aware compatibility check
**Goal:** auto-fixes from migration rules / value validators shouldn't
silently clobber user customizations.

- `CompatibilityIssue` gained `has_user_override: bool` +
  `override_summary: str`.
- `FilterCompatibilityChecker.__init__` takes `overrides=` and computes line
  ranges for customized blocks during `check()`.
- In the dialog: conflicts show with amber row tag, ⚠ prefix on Current,
  default-OFF Fix? checkbox, count in the summary line, excluded from "Select
  all fixable" bulk toggle.

---

## 3. Persistence model (where state lives)

| What | Where | Scope |
|------|-------|-------|
| App settings (theme, FFmpeg, autoload, etc.) | `%APPDATA%/POE2FilterSoundEditor/settings.json` | Per-user, per-machine |
| Migration rules (compatibility check) | `<app>/data/migration_rules.json` | Per-install, shared across all filters |
| Visual presets (tier styling + randomizer palettes) | `<app>/data/visual_presets.json` | Per-install, shared across all filters |
| Per-filter overrides (tier customizations + block reassignments) | `<filterdir>/<filtername>.filterstudio.json` | Per-filter |
| Backups (timestamped) | `<filterdir>/<filtername>_backups/` | Per-filter |
| Debug log (rotating) | `%APPDATA%/POE2FilterSoundEditor/app_debug.log` | Per-user, per-machine |

`visual_presets.json` is the *defaults* layer. `<filter>.filterstudio.json`
is the per-filter override layer. Together: the styler walks defaults →
tier preset overrides → per-block style overrides.

---

## 4. Data flow on a fresh filter load

```
User picks a filter
  └─ load_filter()
      ├─ load_filter_file() → self.lines
      ├─ _snapshot_on_load()
      │    └─ make_backup(label="load", skip_if_identical=True)
      ├─ refresh_filter_data()  [original parser, populates UI]
      └─ if auto_check_compatibility:
            _run_compatibility_check(auto=True)
              ├─ load_overrides(filter_path)  [for conflict tagging]
              ├─ FilterCompatibilityChecker(engine, overrides=...)
              ├─ checker.check(self.lines)
              └─ if not clean: show_compatibility_dialog(...)
```

When the user opens Tools → Emphasize by Tier:

```
open_visual_tools()
  └─ _VisualToolsDialog
       ├─ load_visual_presets(presets_path)  [defaults]
       ├─ load_overrides(filter_path)        [user layer]
       ├─ EmphasisStyler(presets=..., overrides=...).plan(lines)
       └─ render swatches (clickable)
             └─ on click: open_tier_detail(tier, plan, presets, overrides)
                  └─ on save: save_overrides(filter_path, overrides)
                  └─ on close cb: reload + re-plan parent
```

---

## 5. Files touched this session

### Added
- `core/compatibility.py`
- `core/user_overrides.py`
- `data/migration_rules.json`
- `data/visual_presets.json` *(written by app on first Edit click)*
- `features/visual_emphasis.py`
- `ui/compatibility_dialog.py`
- `ui/tier_detail_dialog.py`
- `ui/visual_tools_dialog.py`
- `LLM_CONTEXT.md` *(this file)*

### Modified
- `core/file_operations.py` — `make_backup` now takes `label` and
  `skip_if_identical`; same-second collision tie-break.
- `core/settings.py` — added `auto_check_compatibility` and
  `auto_backup_on_load` fields.
- `main.py` —
  - imports: compatibility, user_overrides (lazy), visual_tools_dialog
  - menus: Check Filter Compatibility, Emphasize by Tier, Randomize Visuals
  - new methods: `_snapshot_on_load`, `_run_compatibility_check`,
    `check_filter_compatibility`, `emphasize_by_tier`, `randomize_visuals`
  - settings dialog gained two new checkboxes
  - both load paths now snapshot + run compat check

---

## 6. Architecture decisions worth knowing

1. **Block signatures are stable, not positional.** They survive filter
   re-imports, reorders, comment changes. They do NOT survive criteria
   changes (Class/BaseType/Rarity edit) — which is the correct semantic:
   that's a different block.

2. **Forgiving JSON loaders everywhere.** Both `migration_rules.json` and
   `visual_presets.json` survive bad fields — print a warning, drop the
   bad entry, keep going. Never crash the load over a typo.

3. **Lazy imports across modules to break cycles.** `EmphasisStyler.plan()`
   imports `core.user_overrides.block_signature` lazily.
   `FilterCompatibilityChecker._compute_override_ranges` imports
   `features.visual_emphasis` lazily. Keep this pattern when adding cross-
   module hooks.

4. **Atomic writes via `os.replace`.** Every save goes through a `.tmp` +
   replace dance. A crash mid-write cannot truncate the filter.

5. **Backups don't block loading.** `_snapshot_on_load` swallows any
   exception and reports via status bar only. Filter loads must never fail
   because the backup folder is read-only.

6. **Visual tools touch styling ONLY.** Show/Hide, item conditions, sound
   commands are off-limits. This is a hard invariant — protect it. The
   tradeoff was discussed and the user picked the conservative path.

7. **Conflicts default to off, not on.** When a compatibility fix would
   touch a user-overridden block, the dialog defaults to "don't apply" so
   the user has to explicitly opt in to lose their customization.

---

## 7. Known limitations / gotchas

- **Block boundary detection.** `iter_blocks` yields lines from one
  Show/Hide to the next, which includes trailing blanks AND any
  `# [[NNNN]]` section header that belongs to the *next* block. Insertion
  logic in `apply_style_to_block` skips back past both. If you add a new
  trailing-content rewriter, replicate that skip.

- **`POE2 Custom Sound Filter.exe`** at repo root is the previous build.
  `build_exe.bat` rebuilds it (PyInstaller). Build number lives in a
  separate file referenced in recent commits.

- **POE2 named-color / shape sets** in `features/visual_emphasis.py`:
  `POE2_NAMED_COLORS` (11) and `POE2_MINIMAP_SHAPES` (12). If GGG adds
  new entries, update those constants AND `data/visual_presets.json`
  loader's validators (`_VALID_NAMED_COLORS`, `_VALID_MINIMAP_SHAPES`).

- **Tier classification keywords** in `_SECTION_KEYWORDS` are first-match-
  wins substring. Order matters. NeverSink section names are the assumed
  convention; other filter authors may need additional entries.

- **The `auto_check_compatibility` toggle exists** but the seed
  `migration_rules.json` ships with all examples disabled, so a clean filter
  on first run will be silent. That's by design — the user adds rules as
  needed.

- **Windows console can't print Unicode arrows** (cp1252). Tests use ASCII;
  the app itself is fine because Tk handles Unicode natively.

---

## 8. Plausible next work

Not yet built — listed in rough priority order:

1. **In-app rule editor for `migration_rules.json`.** The user can already
   open the file from the compatibility dialog, but a structured
   editor would be friendlier. Same JSON pattern as visual_presets.

2. **Conflict resolution UI for compatibility fixes.** Right now a
   conflicting fix is just default-off. A "show me what would change
   before/after" diff view would be nicer.

3. **Multi-tier bulk reassign.** "Move all blocks containing this BaseType
   to TOP" — a query-and-batch flow on top of the existing per-block UI.

4. **Apply-on-save vs apply-on-load.** Currently emphasis/randomizer
   rewrites the file when the user clicks Apply. A "preview mode" that
   doesn't touch the file (keeps overrides as a layer, only commits on save)
   would let users experiment more freely. The sidecar can already represent
   this — the styler just needs a non-destructive plan-to-preview path.

5. **Export/share customizations.** A "share my tier styling" button that
   bundles overrides + visual_presets into a single file someone else can
   import.

6. **Block-level style picker in the tier detail dialog.** Currently you
   can reassign a block's tier or use the tier preset, but to set a per-
   block style override you have to edit the sidecar by hand. The
   `BlockOverride.style` field is wired through everything; just needs UI.

7. **Smarter value heuristics.** Currently classification reads Show/Hide,
   `$tier->`, and section name. Could also weigh: existing font size,
   presence of PlayEffect/MinimapIcon (filter author already considered it
   important), StackSize thresholds.

8. **Live preview in the main editor.** The tier detail dialog has a
   preview. The main editor tree still shows category/sound/etc. — wiring
   the chosen style into the row rendering would let the user see their
   work without leaving the editor.

9. **Unit tests.** `tests/` exists per CLAUDE.md but most of this
   session's work has no tests. The most valuable to cover:
   `block_signature` stability, `apply_style_to_block` insertion edge
   cases, `_compute_override_ranges`, the migration rule resolution order.

---

## 9. Quick verification commands

```powershell
# Compile everything
python -m py_compile main.py core/*.py features/*.py ui/*.py

# Smoke-test the compatibility engine
python -c "from core.compatibility import FilterCompatibilityChecker, MigrationRulesEngine; print(len(MigrationRulesEngine().rules))"

# Test visual emphasis on a sample
python -c "from features.visual_emphasis import EmphasisStyler, apply_changes; lines=['Show\n','\tRarity Unique\n']; print(apply_changes(lines, EmphasisStyler().plan(lines)))"

# Test override round-trip (uses tempfile)
python -c "from core.user_overrides import block_signature; print(block_signature(['Show\n','\tBaseType \"Heavy Belt\"\n','\tRarity Unique\n']))"
```

---

## 10. Working preferences (mirror of CLAUDE.md, condensed)

- User does not use git/GitHub. Claude commits, pushes, opens PRs without
  being asked, on a feature branch, never directly on `main`.
- Pause before destructive operations (force-push, history rewrite, branch
  delete, PR merge).
- `gh` CLI auth as `xtheredshirtx`. Remote `origin` =
  `https://github.com/xtheredshirtx/poe2-filter-sound-studio`.
- Commit author: `xtheredshirtx <xtheredshirtx@users.noreply.github.com>`
  (set repo-local).

---

*End of context log. Last updated 2026-06-13.*
