"""Backups, external-edit detection, and atomic writes (§BACKUP, A.7).

* Records the source file's size/mtime/content-hash at load and re-checks before
  writing, so an edit made elsewhere can't be silently clobbered.
* Writes the spec-named backup ``backups/<name>_before_economy_tier_visuals_
  <timestamp>.filter`` next to the target and *verifies it is readable* before
  the original is touched.
* Replaces the original atomically: temp file in the **same directory**, fsync,
  then ``os.replace`` (atomic on NTFS).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime

from economy_tier.errors import BackupError, FileChangedError


@dataclass(frozen=True)
class SourceState:
    """A cheap fingerprint of the on-disk file at load time."""

    size: int
    mtime_ns: int
    sha256: str

    @property
    def exists(self) -> bool:
        return self.size >= 0


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_state(path: str) -> SourceState:
    """Snapshot ``path``'s size/mtime/hash. Missing file -> sentinel state."""
    try:
        st = os.stat(path)
        with open(path, "rb") as f:
            digest = _hash_bytes(f.read())
        return SourceState(size=st.st_size, mtime_ns=st.st_mtime_ns, sha256=digest)
    except FileNotFoundError:
        return SourceState(size=-1, mtime_ns=0, sha256="")


def verify_unchanged(path: str, state: SourceState | None) -> None:
    """Raise :class:`FileChangedError` if ``path`` differs from ``state``.

    A ``None`` state means we never recorded one -- skip the check.
    """
    if state is None:
        return
    current = compute_state(path)
    if current != state:
        raise FileChangedError(
            f"{os.path.basename(path)} changed on disk since it was loaded. "
            "Re-load the file and try again."
        )


def make_economy_backup(path: str) -> str:
    """Create and verify the pre-save backup. Raises :class:`BackupError`.

    Returns the backup path. The backup must be byte-identical and readable
    before any caller proceeds to overwrite the original.
    """
    if not os.path.isfile(path):
        raise BackupError(f"Cannot back up a file that does not exist: {path}")

    base_dir = os.path.dirname(os.path.abspath(path))
    backup_dir = os.path.join(base_dir, "backups")
    name = os.path.basename(path)
    stem, ext = os.path.splitext(name)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{stem}_before_economy_tier_visuals_{timestamp}{ext or '.filter'}"

    try:
        os.makedirs(backup_dir, exist_ok=True)
        with open(path, "rb") as src:
            original = src.read()
        backup_path = os.path.join(backup_dir, backup_name)
        # Avoid clobbering a same-second backup.
        n = 2
        while os.path.exists(backup_path):
            backup_path = os.path.join(
                backup_dir, f"{stem}_before_economy_tier_visuals_{timestamp}-{n}{ext or '.filter'}"
            )
            n += 1
        with open(backup_path, "wb") as dst:
            dst.write(original)
            dst.flush()
            os.fsync(dst.fileno())
    except OSError as exc:
        raise BackupError(f"Failed to create backup: {exc}") from exc

    # Verify the backup is readable and identical before we trust it.
    try:
        with open(backup_path, "rb") as f:
            if _hash_bytes(f.read()) != _hash_bytes(original):
                raise BackupError("Backup verification failed (content mismatch).")
    except OSError as exc:
        raise BackupError(f"Backup verification failed: {exc}") from exc

    return backup_path


def atomic_write(path: str, text: str, had_bom: bool = False) -> None:
    """Write ``text`` to ``path`` atomically via a same-dir temp + os.replace."""
    data = text.encode("utf-8")
    if had_bom and not text.startswith("﻿"):
        data = b"\xef\xbb\xbf" + data

    base_dir = os.path.dirname(os.path.abspath(path)) or "."
    tmp_path = os.path.join(base_dir, f".{os.path.basename(path)}.etvp.{os.getpid()}.tmp")
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except OSError as exc:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise BackupError(f"Atomic write failed: {exc}") from exc


__all__ = [
    "SourceState",
    "compute_state",
    "verify_unchanged",
    "make_economy_backup",
    "atomic_write",
]
