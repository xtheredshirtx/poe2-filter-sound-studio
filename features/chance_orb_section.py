"""Inject a "Chance Orb Valuables" section into a POE2 filter.

The section lists Normal-rarity bases the user wants flagged loudly because
they're commonly chanced for valuable uniques. The base list lives in
``data/chance_orb_bases.json`` so the user can curate it as the meta shifts —
no code change needed.

The injection is idempotent: we wrap the generated lines between a pair of
sentinel markers (`# [chance-orb-section:start]` … `# [chance-orb-section:end]`)
so a re-run replaces the existing section instead of duplicating it.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)


SENTINEL_START = "# [chance-orb-section:start] managed by POE2 Filter Sound Studio"
SENTINEL_END = "# [chance-orb-section:end]"


@dataclass
class ChanceOrbConfig:
    section_title: str = "Chance Orb Valuables"
    section_id: int = 9001
    bases: List[dict] = field(default_factory=list)
    style: dict = field(default_factory=dict)

    def enabled_base_names(self) -> List[str]:
        out: List[str] = []
        seen = set()
        for entry in self.bases:
            if not isinstance(entry, dict):
                continue
            if not entry.get("enabled", True):
                continue
            name = (entry.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(name)
        return out


def default_bases_path(app_dir: str) -> str:
    return os.path.join(app_dir, "data", "chance_orb_bases.json")


def load_config(path: str) -> Optional[ChanceOrbConfig]:
    """Read the bases file. Returns None if it's missing/unreadable."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Could not read chance bases %s: %s", path, e)
        return None
    cfg = ChanceOrbConfig(
        section_title=str(data.get("section_title", "Chance Orb Valuables")),
        section_id=int(data.get("section_id", 9001) or 9001),
        bases=list(data.get("bases", [])) if isinstance(data.get("bases"), list) else [],
        style=dict(data.get("style", {}) if isinstance(data.get("style"), dict) else {}),
    )
    return cfg


# ---------------------- Section building ----------------------

def build_section_lines(cfg: ChanceOrbConfig) -> List[str]:
    """Render the section as filter lines (each ending in newline).

    Format:
        # [chance-orb-section:start] managed by POE2 Filter Sound Studio
        # [[9001]] Chance Orb Valuables
        # Edit data/chance_orb_bases.json to change which bases appear here.
        Show
            Rarity Normal
            BaseType "X" "Y" "Z"
            <styling>
        # [chance-orb-section:end]
    """
    names = cfg.enabled_base_names()
    out: List[str] = [
        SENTINEL_START + "\n",
        f"# [[{cfg.section_id}]] {cfg.section_title}\n",
        "# Auto-generated. Edit data/chance_orb_bases.json and re-run\n",
        "# Tools -> 'Add/Update Chance Orb Items' to refresh.\n",
    ]

    if not names:
        # Empty list: emit a commented-out placeholder so the section still
        # round-trips on re-runs but doesn't actually match anything.
        out.extend([
            "# (no bases enabled in chance_orb_bases.json)\n",
            SENTINEL_END + "\n",
            "\n",
        ])
        return out

    basetype_args = " ".join(f'"{n}"' for n in names)
    style = cfg.style or {}

    out.append("Show\n")
    out.append("\tRarity Normal\n")
    out.append(f"\tBaseType {basetype_args}\n")
    for line in _render_style_lines(style):
        out.append(line)
    out.append(SENTINEL_END + "\n")
    out.append("\n")
    return out


def _render_style_lines(style: dict) -> List[str]:
    """Translate the JSON style dict into filter style lines."""
    lines: List[str] = []
    text = style.get("text_color")
    if _rgba_ok(text):
        lines.append(f"\tSetTextColor {_fmt_rgba(text)}\n")
    border = style.get("border_color")
    if _rgba_ok(border):
        lines.append(f"\tSetBorderColor {_fmt_rgba(border)}\n")
    bg = style.get("bg_color")
    if _rgba_ok(bg):
        lines.append(f"\tSetBackgroundColor {_fmt_rgba(bg)}\n")
    font = style.get("font_size")
    if isinstance(font, (int, float)) and 12 <= int(font) <= 60:
        lines.append(f"\tSetFontSize {int(font)}\n")
    effect = style.get("play_effect")
    if isinstance(effect, list) and len(effect) >= 1 and effect[0]:
        color = effect[0]
        temp = " Temp" if (len(effect) > 1 and effect[1]) else ""
        lines.append(f"\tPlayEffect {color}{temp}\n")
    minimap = style.get("minimap")
    if isinstance(minimap, list) and len(minimap) == 3:
        size, color, shape = minimap
        if isinstance(size, int) and size in (0, 1, 2) and color and shape:
            lines.append(f"\tMinimapIcon {size} {color} {shape}\n")
    alert = style.get("alert_sound")
    if isinstance(alert, list) and len(alert) == 2:
        sid, vol = alert
        if sid:
            vol_part = f" {int(vol)}" if isinstance(vol, (int, float)) else ""
            lines.append(f"\tPlayAlertSound {sid}{vol_part}\n")
    return lines


def _rgba_ok(v) -> bool:
    return (isinstance(v, list) and len(v) in (3, 4)
            and all(isinstance(x, (int, float)) and 0 <= int(x) <= 255 for x in v))


def _fmt_rgba(v) -> str:
    if len(v) == 3:
        return f"{int(v[0])} {int(v[1])} {int(v[2])} 255"
    return f"{int(v[0])} {int(v[1])} {int(v[2])} {int(v[3])}"


# ---------------------- Insertion / update ----------------------

def find_existing_section(lines: List[str]) -> Optional[Tuple[int, int]]:
    """Locate `[start, end)` of an existing chance-orb section (sentinel match).

    Returns None if no section is present.
    """
    start_idx: Optional[int] = None
    for i, line in enumerate(lines):
        if SENTINEL_START in line:
            start_idx = i
        elif SENTINEL_END in line and start_idx is not None:
            return (start_idx, i + 1)
    return None


def upsert_section(lines: List[str], cfg: ChanceOrbConfig,
                    *, position: str = "top") -> Tuple[List[str], int, int]:
    """Insert or update the section in `lines`.

    Returns:
        (new_lines, base_count, action_kind)
        action_kind: 0 = no-op (nothing to insert), 1 = inserted, 2 = updated
    """
    new_section = build_section_lines(cfg)
    base_count = len(cfg.enabled_base_names())
    existing = find_existing_section(lines)

    if existing is not None:
        s, e = existing
        updated = list(lines[:s]) + new_section + list(lines[e:])
        return updated, base_count, 2  # updated

    if position == "top":
        # Insert BEFORE the first existing `# [[NNNN]]` section header. That
        # makes our section the first section in the file, so the sidebar
        # shows it as its own clickable category. If we instead inserted
        # after a section header, our `[[9001]]` line would overwrite the
        # current_section tracker mid-section and "steal" blocks from the
        # neighboring category.
        #
        # If the file has no section headers at all, fall back to inserting
        # before the first Show/Hide block (which is still safe there).
        insert_at = _first_insertion_point(lines)
        new_lines = list(lines[:insert_at]) + new_section + list(lines[insert_at:])
    else:
        new_lines = list(lines) + new_section
    return new_lines, base_count, 1


# Match `# [[NNNN]] Title` — the section-header convention NeverSink/FilterBlade use.
import re as _re  # local alias so the top-of-file `import re` isn't shadowed
_SECTION_HEADER_RE = _re.compile(r"^\s*#\s*\[\[\d+\]\]")


def _first_insertion_point(lines: List[str]) -> int:
    """Best spot to inject a new top-level section.

    Prefers `before the first existing section header`, since that keeps our
    section self-contained. Falls back to `before the first Show/Hide` when
    the filter has no section headers at all.
    """
    for i, line in enumerate(lines):
        if _SECTION_HEADER_RE.match(line):
            return i
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("Show", "Hide", "Continue")) and not stripped.startswith("#"):
            return i
    return len(lines)


def _first_show_or_hide_idx(lines: List[str]) -> int:
    """Index of the first `Show`/`Hide` line — kept for backward compat."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("Show", "Hide", "Continue")) and not stripped.startswith("#"):
            return i
    return len(lines)
