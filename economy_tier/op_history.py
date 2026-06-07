"""Disk-persisted operation history powering ``Restore Previous Visuals``.

A small JSON file in the per-user data dir records each apply/restore: the full
original and new content, timestamp, operation name, template, changed-block
count, and the run fingerprint. ``Restore Previous Visuals`` reverts the last
economy-tier operation for a given file; the restore itself is recorded so it is
also undoable (A.11).

The store is forgiving: a missing or corrupt file is treated as empty history so
the feature keeps working.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime

from economy_tier import SCHEMA_VERSION
from economy_tier.logging_setup import get_logger
from economy_tier.resources import op_history_path

_log = get_logger()

# Keep history bounded so the file can't grow without limit.
_MAX_ENTRIES = 100


@dataclass
class HistoryEntry:
    """One recorded economy-tier operation."""

    timestamp: str
    operation: str
    file_path: str
    original_content: str
    new_content: str
    template: str = ""
    changed_block_count: int = 0
    fingerprint: str = ""


@dataclass
class OpHistory:
    """In-memory view of the on-disk history, with load/save helpers."""

    entries: list[HistoryEntry] = field(default_factory=list)
    path: str = ""

    @classmethod
    def load(cls, path: str | None = None) -> OpHistory:
        p = path or op_history_path()
        if not os.path.isfile(p):
            return cls(entries=[], path=p)
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            raw_entries = data.get("entries", []) if isinstance(data, dict) else []
            entries = [
                HistoryEntry(
                    timestamp=str(e.get("timestamp", "")),
                    operation=str(e.get("operation", "")),
                    file_path=str(e.get("file_path", "")),
                    original_content=str(e.get("original_content", "")),
                    new_content=str(e.get("new_content", "")),
                    template=str(e.get("template", "")),
                    changed_block_count=int(e.get("changed_block_count", 0)),
                    fingerprint=str(e.get("fingerprint", "")),
                )
                for e in raw_entries
                if isinstance(e, dict)
            ]
            return cls(entries=entries, path=p)
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            _log.warning("Op-history unreadable (%s); starting fresh", exc)
            return cls(entries=[], path=p)

    def save(self) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "entries": [asdict(e) for e in self.entries[-_MAX_ENTRIES:]],
        }
        tmp = self.path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError as exc:
            _log.error("Failed to save op-history: %s", exc)

    # ----- operations -----------------------------------------------------

    def record(self, entry: HistoryEntry) -> None:
        self.entries.append(entry)
        self.entries = self.entries[-_MAX_ENTRIES:]
        self.save()

    def last_apply_for(self, file_path: str) -> HistoryEntry | None:
        """Most recent non-restore entry for ``file_path`` (the thing to undo)."""
        target = os.path.normcase(os.path.abspath(file_path))
        for entry in reversed(self.entries):
            if os.path.normcase(os.path.abspath(entry.file_path)) != target:
                continue
            if entry.operation.lower().startswith("restore"):
                continue
            return entry
        return None

    def has_restorable(self, file_path: str) -> bool:
        return self.last_apply_for(file_path) is not None


def new_entry(
    operation: str,
    file_path: str,
    original_content: str,
    new_content: str,
    template: str = "",
    changed_block_count: int = 0,
    fingerprint: str = "",
) -> HistoryEntry:
    return HistoryEntry(
        timestamp=datetime.now().isoformat(timespec="seconds"),
        operation=operation,
        file_path=file_path,
        original_content=original_content,
        new_content=new_content,
        template=template,
        changed_block_count=changed_block_count,
        fingerprint=fingerprint,
    )


__all__ = ["HistoryEntry", "OpHistory", "new_entry"]
