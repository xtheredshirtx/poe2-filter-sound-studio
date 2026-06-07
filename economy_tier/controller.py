"""Orchestration service for the Economy Tier feature.

The UI talks only to this module. It wires the pure core (parser, data,
classifier, patcher, validator) to the I/O modules (backup, history) and
enforces the safety ordering for a save:

    classify -> patch (in memory) -> validate + structural-diff guard
    -> verify file unchanged on disk -> create & verify backup
    -> atomic replace -> re-read & verify -> record history

If the tier data or template fails to load, the controller reports a clear
message and the rest of the app keeps working (A.5). ``Preview Only`` never
writes; ``Restore`` writes and is itself recorded so it can be undone (A.11).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum

from economy_tier import backup_manager
from economy_tier.economy_tier_classifier import (
    Classification,
    ClassificationResult,
    ClassifyOptions,
    Status,
    classify,
)
from economy_tier.economy_tier_data import Confidence, TierData, load_tier_data
from economy_tier.errors import EconomyTierError, ValidationError
from economy_tier.filter_parser import parse
from economy_tier.filter_validator import ValidationReport, validate
from economy_tier.filter_visual_patcher import (
    BlockPatch,
    PatchResult,
    TransferOptions,
    patch,
)
from economy_tier.logging_setup import get_logger
from economy_tier.op_history import OpHistory, new_entry
from economy_tier.visual_template_loader import Template, TemplateSet, load_templates

_log = get_logger()


class Mode(str, Enum):
    """Canonical dropdown modes (A.11 order)."""

    OFF = "Off"
    PREVIEW = "Preview Only"
    APPLY = "Apply Economy Tier Visuals"
    APPLY_CHANCE = "Apply Economy Tier Visuals Plus Chance Base Boost"
    RESTORE = "Restore Previous Visuals"


#: Order to present the modes in any dropdown.
MODE_ORDER: list[str] = [m.value for m in Mode]


@dataclass
class PreviewModel:
    """Everything the preview dialog needs to render a diff (no disk writes)."""

    mode: Mode
    total_blocks: int
    changed: int
    unchanged: int
    skipped_hidden: int
    skipped_sound_only: int
    unknown: int
    low_confidence_shown: int
    chance_promotions: int
    tier_counts: dict[str, int]
    warnings: list[str]
    patches: list[BlockPatch]
    classifications: list[Classification]
    fingerprint: str
    new_text: str
    validation: ValidationReport | None = None
    staleness: str | None = None


@dataclass
class ApplyResult:
    """Outcome of a write operation."""

    ok: bool
    message: str
    new_text: str = ""
    new_lines: list[str] = field(default_factory=list)
    backup_path: str = ""
    changed_count: int = 0
    fingerprint: str = ""


def _confidence_from_str(value: str) -> Confidence:
    try:
        return Confidence[value]
    except KeyError:
        return Confidence.medium


class EconomyTierController:
    """Stateful per-session controller. Construct when the feature is invoked."""

    def __init__(
        self,
        filter_path: str,
        lines: list[str],
        template_name: str | None = None,
    ) -> None:
        self.filter_path = filter_path
        self.original_text = "".join(lines)
        self.template_name = template_name
        self.available = False
        self.disabled_reason: str | None = None
        self._data: TierData | None = None
        self._templates: TemplateSet | None = None
        # External-edit guard baseline (A.7).
        self._source_state = backup_manager.compute_state(filter_path) if filter_path else None
        self._history = OpHistory.load()
        self._load_resources()

    # ----- resource loading ----------------------------------------------

    def _load_resources(self) -> None:
        try:
            self._data = load_tier_data()
            self._templates = load_templates()
            if self.template_name is None:
                self.template_name = self._templates.default_name
            self.available = True
        except EconomyTierError as exc:
            self.available = False
            self.disabled_reason = str(exc)
            _log.error("Economy Tier feature disabled: %s", exc)

    @property
    def data(self) -> TierData:
        assert self._data is not None
        return self._data

    @property
    def templates(self) -> TemplateSet:
        assert self._templates is not None
        return self._templates

    def template(self) -> Template:
        return self.templates.get(self.template_name)

    def template_names(self) -> list[str]:
        return self.templates.names() if self.available else []

    def staleness_message(self) -> str | None:
        if not self.available:
            return None
        age = self.data.age_days()
        if age is not None and self.data.is_stale():
            return (
                f"Economy data is {age} days old — values drift; "
                "consider refreshing via tools/update_economy_tiers.py."
            )
        return None

    def has_restorable(self) -> bool:
        return self._history.has_restorable(self.filter_path)

    # ----- preview --------------------------------------------------------

    def build_preview(
        self,
        mode: Mode,
        transfer: TransferOptions,
        min_confidence: str = "medium",
    ) -> PreviewModel:
        """Classify + patch in memory and assemble preview stats. No writes."""
        if not self.available:
            raise EconomyTierError(self.disabled_reason or "Feature unavailable")

        min_conf = _confidence_from_str(min_confidence)
        opts = ClassifyOptions(
            enable_chance_boost=(mode == Mode.APPLY_CHANCE),
            min_confidence=min_conf,
            skip_hidden=True,
        )
        doc = parse(self.original_text)
        result: ClassificationResult = classify(
            doc, self.data, opts, template_fingerprint=self.templates.fingerprint
        )

        applicable = [c for c in result.classifications if c.applicable(min_conf)]
        patch_result: PatchResult = patch(doc, applicable, self.template(), transfer)
        new_text = "".join(patch_result.new_lines)

        # Validate the in-memory result so the preview reflects what would save.
        report: ValidationReport | None = None
        try:
            report = validate(self.original_text, new_text, patch_result.edited_block_indices)
        except ValidationError as exc:
            result.warnings.append(f"Validation would fail: {exc}")

        cl = result.classifications
        skipped_hidden = sum(1 for c in cl if c.status == Status.SKIPPED_HIDDEN)
        skipped_sound = sum(1 for c in cl if c.status == Status.SKIPPED_SOUND_ONLY)
        unknown = sum(1 for c in cl if c.status == Status.UNKNOWN)
        classified = sum(1 for c in cl if c.status == Status.CLASSIFIED)
        low_shown = sum(
            1 for c in cl if c.status == Status.CLASSIFIED and not c.applicable(min_conf)
        )
        promotions = sum(1 for c in cl if c.is_chance_promotion and c.applicable(min_conf))
        unchanged = classified - patch_result.changed_count

        return PreviewModel(
            mode=mode,
            total_blocks=len(cl),
            changed=patch_result.changed_count,
            unchanged=max(0, unchanged),
            skipped_hidden=skipped_hidden,
            skipped_sound_only=skipped_sound,
            unknown=unknown,
            low_confidence_shown=low_shown,
            chance_promotions=promotions,
            tier_counts=result.tier_counts(min_conf),
            warnings=result.warnings,
            patches=patch_result.patches,
            classifications=cl,
            fingerprint=result.fingerprint,
            new_text=new_text,
            validation=report,
            staleness=self.staleness_message(),
        )

    # ----- apply ----------------------------------------------------------

    def apply(
        self,
        mode: Mode,
        transfer: TransferOptions,
        min_confidence: str = "medium",
    ) -> ApplyResult:
        """Apply visuals and save atomically with a verified backup."""
        if not self.available:
            return ApplyResult(False, self.disabled_reason or "Feature unavailable")
        if mode not in (Mode.APPLY, Mode.APPLY_CHANCE):
            return ApplyResult(False, f"{mode.value} does not write to disk.")

        preview = self.build_preview(mode, transfer, min_confidence)
        if preview.changed == 0:
            return ApplyResult(
                True,
                "No blocks needed changes (already styled or nothing matched).",
                new_text=self.original_text,
                new_lines=self.original_text.splitlines(keepends=True),
                changed_count=0,
                fingerprint=preview.fingerprint,
            )

        # Re-validate hard before writing; abort on any guard failure.
        try:
            edited = {p.block_index for p in preview.patches}
            validate(self.original_text, preview.new_text, edited)
        except ValidationError as exc:
            _log.error("Aborting save (validation): %s", exc)
            return ApplyResult(False, f"Aborted: {exc}")

        return self._write(
            new_text=preview.new_text,
            operation=mode.value,
            changed_count=preview.changed,
            fingerprint=preview.fingerprint,
        )

    # ----- restore --------------------------------------------------------

    def restore(self) -> ApplyResult:
        """Revert the last economy-tier operation for this file (A.11)."""
        if not self.filter_path:
            return ApplyResult(False, "No file loaded.")
        entry = self._history.last_apply_for(self.filter_path)
        if entry is None:
            return ApplyResult(False, "No previous economy-tier operation to restore.")

        # Restore writes the recorded original content back. It is itself
        # recorded (current -> restored) so a restore can be undone.
        return self._write(
            new_text=entry.original_content,
            operation="Restore Previous Visuals",
            changed_count=entry.changed_block_count,
            fingerprint=entry.fingerprint,
            skip_self_classification=True,
        )

    # ----- shared write path ---------------------------------------------

    def _write(
        self,
        new_text: str,
        operation: str,
        changed_count: int,
        fingerprint: str,
        skip_self_classification: bool = False,
    ) -> ApplyResult:
        path = self.filter_path
        # (1) External-edit guard.
        try:
            backup_manager.verify_unchanged(path, self._source_state)
        except EconomyTierError as exc:
            return ApplyResult(False, str(exc))

        # (2) Backup first; never write if backup fails/unverifiable.
        backup_path = ""
        try:
            if os.path.isfile(path):
                backup_path = backup_manager.make_economy_backup(path)
        except EconomyTierError as exc:
            return ApplyResult(False, f"Backup failed, nothing written: {exc}")

        # (3) Atomic replace.
        try:
            had_bom = self.original_text.startswith("﻿")
            backup_manager.atomic_write(path, new_text, had_bom=had_bom)
        except EconomyTierError as exc:
            return ApplyResult(False, f"Write failed: {exc}")

        # (4) Re-read and verify the exact bytes landed.
        try:
            expected = new_text.encode("utf-8")
            if had_bom and not new_text.startswith("﻿"):
                expected = b"\xef\xbb\xbf" + expected
            with open(path, "rb") as f:
                on_disk = f.read()
            if on_disk != expected:
                return ApplyResult(
                    False,
                    "Post-write verification failed; the backup is intact at " f"{backup_path}.",
                )
        except OSError as exc:
            return ApplyResult(False, f"Post-write read failed: {exc}")

        # (5) Record history and refresh the external-edit baseline.
        self._history.record(
            new_entry(
                operation=operation,
                file_path=path,
                original_content=self.original_text,
                new_content=new_text,
                template=self.template_name or "",
                changed_block_count=changed_count,
                fingerprint=fingerprint,
            )
        )
        self._source_state = backup_manager.compute_state(path)
        self.original_text = new_text

        return ApplyResult(
            ok=True,
            message=(
                f"{operation}: {changed_count} block(s) changed, saved with backup."
                if changed_count
                else f"{operation}: saved with backup."
            ),
            new_text=new_text,
            new_lines=new_text.splitlines(keepends=True),
            backup_path=backup_path,
            changed_count=changed_count,
            fingerprint=fingerprint,
        )


__all__ = [
    "Mode",
    "MODE_ORDER",
    "PreviewModel",
    "ApplyResult",
    "EconomyTierController",
]
