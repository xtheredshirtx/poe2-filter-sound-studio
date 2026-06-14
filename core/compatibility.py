"""Filter compatibility checker for POE2 item filters.

When the game gets an update or you load a filter authored against a different
version of POE2, some commands may be renamed, deprecated, or simply unknown.
This module scans a freshly loaded filter and surfaces:

  - Unknown commands (typos or new syntax we don't recognize yet)
  - Renamed commands that can be auto-migrated via JSON rules
  - Bad numeric values (out-of-range RGB/volume)
  - Structural issues (orphan actions outside a Show/Hide block)

The rule table lives in ``data/migration_rules.json`` so users can extend it
without touching Python — just add a new rule and reload the filter.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any

log = logging.getLogger(__name__)


# Block headers that open a new Show/Hide region.
BLOCK_HEADERS = {"Show", "Hide", "Continue"}

# Conditions valid inside a Show/Hide block.
# Seed list — add to this freely. Users can also whitelist via migration_rules.json
# ("allow" rules), which lets them keep up with GGG changes without a code edit.
KNOWN_CONDITIONS = {
    "AreaLevel", "ItemLevel", "DropLevel", "Quality", "Rarity",
    "Class", "BaseType", "BaseClass",
    "Sockets", "LinkedSockets", "SocketGroup",
    "Height", "Width",
    "HasExplicitMod", "HasEnchantment", "EnchantmentPassiveNode",
    "EnchantmentPassiveNum", "AnyEnchantment",
    "StackSize", "GemLevel", "GemQualityType", "AlternateQuality",
    "Identified", "Corrupted", "CorruptedMods", "Mirrored", "Replica",
    "Scourged", "FracturedItem", "SynthesisedItem",
    "ElderItem", "ShaperItem",
    "HasInfluence",
    "ShapedMap", "BlightedMap", "UberBlightedMap", "MapTier",
    "BaseArmour", "BaseEvasion", "BaseEnergyShield", "BaseWard",
    "BaseDefencePercentile",
    "ArchnemesisMod", "HasSearingExarchImplicit", "HasEaterOfWorldsImplicit",
    "TransfiguredGem", "HasCruciblePassiveTree",
    "Reward",
    # POE2-specific (added across 0.1–0.5 patches)
    "WaystoneTier", "HasImplicitMod", "Rune",
    "TwiceCorrupted",         # Recombinator / twice-corrupted system
    "UnidentifiedItemTier",   # New tier system for unidentified rares
    "MemoryStrands",          # Map device / memory strand condition
    "CharmTier", "RuneTier",  # Charm and rune tier filtering
}

# Actions/styling valid inside a Show/Hide block.
KNOWN_ACTIONS = {
    "SetTextColor", "SetBorderColor", "SetBackgroundColor",
    "SetFontSize",
    "PlayAlertSound", "PlayAlertSoundPositional",
    "DisableDropSound", "EnableDropSound",
    "DisableDropSoundIfAlertSound", "EnableDropSoundIfAlertSound",
    "CustomAlertSound", "CustomAlertSoundOptional",
    "MinimapIcon", "PlayEffect",
}

KNOWN_COMMANDS = BLOCK_HEADERS | KNOWN_CONDITIONS | KNOWN_ACTIONS

# Patterns for value-level validation.
_RGB_RE = re.compile(
    r"^(\s*)(SetTextColor|SetBorderColor|SetBackgroundColor)\s+(.+?)\s*$",
    re.IGNORECASE,
)
_SOUND_PLAY_RE = re.compile(
    r"^(\s*)(PlayAlertSound|PlayAlertSoundPositional)\s+(\S+)(?:\s+(\d+))?\s*$",
    re.IGNORECASE,
)
_SOUND_CUSTOM_RE = re.compile(
    r"^(\s*)(CustomAlertSound|CustomAlertSoundOptional)\s+\"([^\"]+)\"\s*(\d+)?\s*$",
    re.IGNORECASE,
)
# Strip a trailing inline comment so we validate the command itself, not the comment.
_INLINE_COMMENT_RE = re.compile(r"\s+#.*$")

# Issue kinds — keep these short, the UI displays them verbatim.
KIND_UNKNOWN = "unknown_command"
KIND_RENAME = "rename"
KIND_DEPRECATED = "deprecated"
KIND_BAD_RGB = "bad_rgb"
KIND_BAD_VOLUME = "bad_volume"
KIND_ORPHAN_ACTION = "orphan_action"
KIND_REPLACE = "replace"     # generic "this whole line becomes that line"
KIND_REMOVE = "remove"       # rule says: drop this line entirely


@dataclass
class CompatibilityIssue:
    """One problem (or one auto-fix opportunity) found on a single line."""
    line_no: int                 # 0-based index into the source `lines` list
    line_text: str               # original line (with trailing newline if present)
    kind: str                    # one of the KIND_* constants
    message: str                 # human-readable description shown in the UI
    auto_fixable: bool = False
    new_line_text: Optional[str] = None   # what we'd replace line_text with
    rule_id: Optional[str] = None         # which migration rule produced this, if any
    # True when this line lives inside a block the user has customized via the
    # tier detail dialog. The UI flags these so the user notices a fix would
    # clobber their tweaks.
    has_user_override: bool = False
    override_summary: str = ""

    @property
    def display_line(self) -> str:
        return self.line_text.rstrip("\n")

    @property
    def display_new_line(self) -> str:
        if self.new_line_text is None:
            return ""
        return self.new_line_text.rstrip("\n")


@dataclass
class MigrationRule:
    """A single user-editable migration rule from migration_rules.json.

    Supported `match_type` values:
      - "command":  match by command name (case-insensitive, first token of line).
                    Use with `replacement` (full new line) or `rename_to` (just the cmd).
      - "regex":    match `pattern` against the whole stripped line.
                    `replacement` may use $1, $2 backrefs.
      - "allow":    just whitelist `pattern` (a command name) as known. No fix.
    """
    id: str
    description: str = ""
    match_type: str = "command"
    pattern: str = ""
    replacement: Optional[str] = None
    rename_to: Optional[str] = None
    action: str = "replace"            # "replace" | "remove" | "allow"
    enabled: bool = True
    kind: str = KIND_RENAME            # what KIND_* to label issues with

    # Compiled lazily.
    _regex: Optional[re.Pattern] = field(default=None, repr=False)

    def compile(self) -> None:
        if self.match_type == "regex" and self.pattern and self._regex is None:
            self._regex = re.compile(self.pattern, re.IGNORECASE)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MigrationRule":
        # Filter unknown keys so future schema versions don't crash old releases.
        valid = {
            "id", "description", "match_type", "pattern", "replacement",
            "rename_to", "action", "enabled", "kind",
        }
        clean = {k: v for k, v in data.items() if k in valid}
        rule = cls(**clean)
        rule.compile()
        return rule


@dataclass
class CompatibilityReport:
    """Result of scanning a filter."""
    issues: List[CompatibilityIssue] = field(default_factory=list)
    rules_applied: int = 0
    rules_file: str = ""

    @property
    def auto_fixable_count(self) -> int:
        return sum(1 for i in self.issues if i.auto_fixable)

    @property
    def manual_count(self) -> int:
        return sum(1 for i in self.issues if not i.auto_fixable)

    @property
    def is_clean(self) -> bool:
        return not self.issues

    def by_kind(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for i in self.issues:
            counts[i.kind] = counts.get(i.kind, 0) + 1
        return counts


class MigrationRulesEngine:
    """Loads migration rules from JSON and applies them to lines."""

    def __init__(self, rules: Optional[List[MigrationRule]] = None,
                 rules_file: str = ""):
        self.rules: List[MigrationRule] = rules or []
        self.rules_file = rules_file
        # Commands whitelisted via "allow" rules, in addition to KNOWN_COMMANDS.
        self.extra_allowed: set = {
            r.pattern for r in self.rules
            if r.enabled and r.action == "allow" and r.pattern
        }

    @classmethod
    def load(cls, rules_file: str) -> "MigrationRulesEngine":
        """Load rules from JSON. Missing file = empty engine (not an error)."""
        if not rules_file or not os.path.isfile(rules_file):
            return cls(rules=[], rules_file=rules_file)
        try:
            with open(rules_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            log.warning("Could not read rules from %s: %s", rules_file, e)
            return cls(rules=[], rules_file=rules_file)

        raw_rules = data.get("rules", []) if isinstance(data, dict) else []
        rules: List[MigrationRule] = []
        for r in raw_rules:
            try:
                rules.append(MigrationRule.from_dict(r))
            except Exception as e:
                log.warning("Skipping bad rule %r: %s", r, e)
        return cls(rules=rules, rules_file=rules_file)

    def apply_to_line(self, stripped: str, raw: str) -> Optional[CompatibilityIssue]:
        """Return an issue if any rule fires on this line; else None.

        Only the first matching rule wins so users can layer specific rules
        before generic ones in the JSON.
        """
        first_token = _first_command_token(stripped)
        for r in self.rules:
            if not r.enabled:
                continue
            if r.action == "allow":
                continue  # whitelist handled separately

            if r.match_type == "command":
                if not first_token or not r.pattern:
                    continue
                if first_token.lower() != r.pattern.lower():
                    continue
                new_line = self._apply_command_rule(r, raw, stripped, first_token)
            elif r.match_type == "regex":
                r.compile()
                if not r._regex or not r._regex.search(stripped):
                    continue
                new_line = self._apply_regex_rule(r, raw, stripped)
            else:
                continue

            kind = r.kind or (KIND_REMOVE if r.action == "remove" else KIND_RENAME)
            return CompatibilityIssue(
                line_no=-1,   # filled in by caller
                line_text=raw,
                kind=kind,
                message=r.description or f"Rule: {r.id}",
                auto_fixable=True,
                new_line_text=new_line,
                rule_id=r.id,
            )
        return None

    def _apply_command_rule(self, rule: MigrationRule, raw: str,
                             stripped: str, first_token: str) -> Optional[str]:
        if rule.action == "remove":
            return ""
        if rule.replacement is not None:
            # Whole-line replacement — preserve indentation and trailing newline.
            leading, trailing = _split_indent_and_newline(raw)
            return f"{leading}{rule.replacement}{trailing}"
        if rule.rename_to:
            # Swap just the command token, keep everything else (args, comments).
            leading, trailing = _split_indent_and_newline(raw)
            rest = stripped[len(first_token):]
            return f"{leading}{rule.rename_to}{rest}{trailing}"
        return None

    def _apply_regex_rule(self, rule: MigrationRule, raw: str,
                           stripped: str) -> Optional[str]:
        if rule.action == "remove":
            return ""
        if rule.replacement is None:
            return None
        # Regex rules operate on the stripped line; we re-attach indent + newline.
        leading, trailing = _split_indent_and_newline(raw)
        new_stripped = rule._regex.sub(rule.replacement, stripped)
        return f"{leading}{new_stripped}{trailing}"


class FilterCompatibilityChecker:
    """Runs validation + migration rules over a filter's lines."""

    def __init__(self, engine: Optional[MigrationRulesEngine] = None,
                 overrides=None):
        self.engine = engine or MigrationRulesEngine()
        self.allowed_commands = KNOWN_COMMANDS | self.engine.extra_allowed
        # Per-filter user overrides. When set, the checker tags any issue
        # whose line lives in a customized block, so the UI can warn before
        # auto-applying a fix that would overwrite the user's tweaks.
        self.overrides = overrides

    def check(self, lines: List[str]) -> CompatibilityReport:
        report = CompatibilityReport(rules_file=self.engine.rules_file)
        in_block = False

        # Pre-compute line ranges for blocks the user has customized.
        override_ranges = self._compute_override_ranges(lines)

        for idx, raw in enumerate(lines):
            stripped_full = raw.strip()

            # Skip blanks and pure comments — `# foo` is always legal.
            if not stripped_full or stripped_full.startswith("#"):
                continue

            # Strip inline comment for command-level checks, but preserve raw
            # in the issue so the user sees what's actually in their file.
            stripped = _INLINE_COMMENT_RE.sub("", stripped_full).strip()
            if not stripped:
                continue

            first_token = _first_command_token(stripped)
            if not first_token:
                continue

            # Block-header tracking — used to flag orphan actions later.
            if first_token in BLOCK_HEADERS:
                in_block = True
                continue

            # 1) Migration rules win first — they're the user's "I know this is
            #    fine in the new season, just rewrite it" escape hatch.
            issue = self.engine.apply_to_line(stripped, raw)
            if issue is not None:
                issue.line_no = idx
                self._tag_override(issue, override_ranges)
                report.issues.append(issue)
                report.rules_applied += 1
                continue

            # 2) Unknown command outside any block? Probably a stray edit.
            if first_token not in self.allowed_commands:
                issue = CompatibilityIssue(
                    line_no=idx,
                    line_text=raw,
                    kind=KIND_UNKNOWN,
                    message=(
                        f"Unknown command '{first_token}'. "
                        "If the game added this in an update, add an 'allow' rule "
                        "in migration_rules.json so it stops being flagged."
                    ),
                    auto_fixable=False,
                )
                self._tag_override(issue, override_ranges)
                report.issues.append(issue)
                continue

            # 3) Orphan action — recognized command but not inside a Show/Hide.
            if not in_block and first_token in KNOWN_ACTIONS:
                report.issues.append(CompatibilityIssue(
                    line_no=idx,
                    line_text=raw,
                    kind=KIND_ORPHAN_ACTION,
                    message=(
                        f"'{first_token}' appears outside any Show/Hide block. "
                        "The game ignores it; consider deleting or wrapping in a block."
                    ),
                    auto_fixable=False,
                ))
                continue

            # 4) Value-level validation for commands we understand deeply.
            val_issue = self._validate_values(idx, raw, stripped)
            if val_issue:
                self._tag_override(val_issue, override_ranges)
                report.issues.append(val_issue)

        return report

    def _compute_override_ranges(self, lines: List[str]):
        """Return a list of (start_idx, end_idx, summary) tuples for blocks
        the user has customized. End is exclusive."""
        if self.overrides is None or not self.overrides.has_any():
            return []
        # Lazy import to avoid the cycle.
        from core.user_overrides import block_signature
        try:
            from features.visual_emphasis import (
                iter_blocks as _iter_blocks, classify_block as _classify,
            )
        except ImportError:
            return []

        ranges = []
        for start, end, header, section, block in _iter_blocks(lines):
            sig = block_signature(block)
            block_ov = self.overrides.block_overrides.get(sig)
            base_tier = _classify(header, section)
            effective_tier = (block_ov.tier if block_ov and block_ov.tier else base_tier)
            tier_ov = self.overrides.tier_presets.get(effective_tier)

            summary_parts = []
            if block_ov and block_ov.tier:
                summary_parts.append(f"tier→{block_ov.tier.name}")
            if block_ov and block_ov.style:
                summary_parts.append("custom block style")
            if tier_ov:
                summary_parts.append(f"{effective_tier.name} tier preset")
            if summary_parts:
                ranges.append((start, end, ", ".join(summary_parts)))
        return ranges

    @staticmethod
    def _tag_override(issue: CompatibilityIssue, ranges) -> None:
        for start, end, summary in ranges:
            if start <= issue.line_no < end:
                issue.has_user_override = True
                issue.override_summary = summary
                return

    @staticmethod
    def _validate_values(idx: int, raw: str,
                         stripped: str) -> Optional[CompatibilityIssue]:
        m = _RGB_RE.match(stripped)
        if m:
            _, cmd, args = m.groups()
            nums = re.findall(r"-?\d+", args)
            if len(nums) not in (3, 4):
                return CompatibilityIssue(
                    line_no=idx, line_text=raw, kind=KIND_BAD_RGB,
                    message=f"{cmd} expects 3 or 4 numbers (R G B [A]), got {len(nums)}.",
                )
            for n in nums:
                v = int(n)
                if v < 0 or v > 255:
                    return CompatibilityIssue(
                        line_no=idx, line_text=raw, kind=KIND_BAD_RGB,
                        message=f"{cmd} value {v} is outside 0-255.",
                    )
            return None

        m = _SOUND_PLAY_RE.match(stripped)
        if m:
            _, _, _, vol = m.groups()
            if vol is not None:
                v = int(vol)
                if v < 0 or v > 300:
                    return CompatibilityIssue(
                        line_no=idx, line_text=raw, kind=KIND_BAD_VOLUME,
                        message=f"Sound volume {v} is outside 0-300.",
                    )
            return None

        m = _SOUND_CUSTOM_RE.match(stripped)
        if m:
            _, _, _, vol = m.groups()
            if vol is not None:
                v = int(vol)
                if v < 0 or v > 300:
                    return CompatibilityIssue(
                        line_no=idx, line_text=raw, kind=KIND_BAD_VOLUME,
                        message=f"Custom sound volume {v} is outside 0-300.",
                    )
        return None

    def apply_fixes(self, lines: List[str],
                     issues: List[CompatibilityIssue]) -> Tuple[List[str], int]:
        """Apply the auto-fixable subset of `issues` to a copy of `lines`.

        Returns (new_lines, fixes_applied).
        """
        new_lines = list(lines)
        applied = 0
        # Apply in reverse line order so a "remove" doesn't shift later indices.
        for issue in sorted(issues, key=lambda i: i.line_no, reverse=True):
            if not issue.auto_fixable or issue.new_line_text is None:
                continue
            if issue.new_line_text == "":
                # Empty new_line_text means "delete this line entirely".
                del new_lines[issue.line_no]
            else:
                new_lines[issue.line_no] = issue.new_line_text
            applied += 1
        return new_lines, applied


# -------- helpers --------

def _first_command_token(stripped: str) -> str:
    """Return the first whitespace-delimited token (the command name)."""
    if not stripped:
        return ""
    return stripped.split(None, 1)[0]


def _split_indent_and_newline(raw: str) -> Tuple[str, str]:
    """Return (leading-whitespace, trailing-newline) so we can rebuild a line."""
    leading_len = len(raw) - len(raw.lstrip(" \t"))
    leading = raw[:leading_len]
    if raw.endswith("\r\n"):
        trailing = "\r\n"
    elif raw.endswith("\n"):
        trailing = "\n"
    else:
        trailing = ""
    return leading, trailing


def default_rules_path(app_dir: str) -> str:
    """Standard location of the user-editable rules file."""
    return os.path.join(app_dir, "data", "migration_rules.json")


def append_allow_rule(rules_file: str, command: str,
                       description: str = "") -> bool:
    """Add an `allow`-type migration rule that whitelists `command`.

    Used by the compatibility dialog's right-click "Whitelist this command"
    action so users can stop seeing "Unknown command" without editing JSON
    by hand. Idempotent — silently skips if an enabled allow-rule for the
    same command already exists.
    """
    if not command:
        return False
    payload: Dict[str, Any] = {}
    if os.path.isfile(rules_file):
        try:
            with open(rules_file, "r", encoding="utf-8") as f:
                payload = json.load(f) or {}
        except (OSError, json.JSONDecodeError) as e:
            log.warning("Could not read rules %s for append: %s", rules_file, e)
            payload = {}

    rules = payload.get("rules", []) if isinstance(payload, dict) else []
    if not isinstance(rules, list):
        rules = []

    # Idempotency check.
    for r in rules:
        if (isinstance(r, dict)
                and r.get("match_type") == "allow"
                and r.get("pattern", "").lower() == command.lower()
                and r.get("enabled", True)):
            return False

    new_rule = {
        "id": f"allow-{command}",
        "description": description or f"Whitelisted '{command}' via right-click.",
        "match_type": "allow",
        "pattern": command,
        "action": "allow",
        "enabled": True,
    }
    rules.append(new_rule)
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("version", 1)
    payload["rules"] = rules

    os.makedirs(os.path.dirname(rules_file), exist_ok=True)
    tmp = rules_file + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp, rules_file)
    except OSError as e:
        log.warning("Could not write rules %s: %s", rules_file, e)
        return False
    return True
