"""File operations module for filter file management.

Handles loading, saving, and backing up POE2 filter files.
"""

import filecmp
import os
import shutil
from datetime import datetime
from typing import List, Optional


def load_filter_file(file_path: str) -> List[str]:
    """Load a filter file and return its lines.

    Args:
        file_path: Path to the .filter file

    Returns:
        List of lines from the file

    Raises:
        FileNotFoundError: If file doesn't exist
        UnicodeDecodeError: If file encoding is invalid
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Filter file not found: {file_path}")

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        return f.readlines()


def save_filter_file(file_path: str, lines: List[str],
                     create_backup: bool = True, max_backups: Optional[int] = None) -> None:
    """Save lines to a filter file with optional backup rotation.

    Writes atomically: data is first written to ``<file>.tmp`` then ``os.replace``'d
    over the destination so a crash mid-write can't truncate the user's filter.
    """
    if create_backup and os.path.isfile(file_path):
        make_backup(file_path, max_keep=max_backups)

    tmp_path = file_path + ".tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    os.replace(tmp_path, file_path)


def make_backup(file_path: str, max_keep: Optional[int] = None,
                label: str = "backup",
                skip_if_identical: bool = False) -> Optional[str]:
    """Create a timestamped backup of a filter file, with optional rotation.

    Creates backups in a subdirectory named ``{filename}_backups/``. When
    ``max_keep`` is provided, older backups beyond that count are removed.

    Args:
        file_path: Path to the file to backup
        max_keep: Maximum number of backups to keep (oldest removed); None = keep all
        label: Word inserted into the backup filename (e.g. "backup", "load").
               Lets callers distinguish on-load snapshots from pre-save snapshots.
               Rotation is applied per label, so load and save backups don't evict
               each other.
        skip_if_identical: When True, if the most recent existing backup with the
               same label is byte-identical to the current file, skip making a new
               one. Useful for on-load backups to avoid piling up duplicates when
               the user reloads the same file repeatedly.

    Returns:
        Path to the backup file (or the existing identical one when skipped),
        or None if backup failed.
    """
    try:
        if not file_path or not os.path.isfile(file_path):
            return None

        base_dir = os.path.dirname(file_path)
        full_name = os.path.basename(file_path)
        name_without_ext, ext = os.path.splitext(full_name)

        backup_dir = os.path.join(base_dir, f"{name_without_ext}_backups")
        os.makedirs(backup_dir, exist_ok=True)

        prefix = f"{name_without_ext}_{label}_"

        # Collect existing backups for this label (used for both skip-check and rotation).
        try:
            existing = [
                os.path.join(backup_dir, f)
                for f in os.listdir(backup_dir)
                if f.startswith(prefix) and f.endswith(ext)
            ]
            existing.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        except OSError:
            existing = []

        if skip_if_identical and existing:
            try:
                if filecmp.cmp(file_path, existing[0], shallow=False):
                    return existing[0]
            except OSError:
                pass

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_name = f"{prefix}{timestamp}{ext}"
        backup_path = os.path.join(backup_dir, backup_name)
        # Two backups can collide on second-resolution timestamps (rapid reloads,
        # batch operations). Tie-break with a short suffix so we never silently
        # overwrite a prior snapshot.
        if os.path.exists(backup_path):
            n = 2
            while True:
                candidate = os.path.join(backup_dir, f"{prefix}{timestamp}-{n}{ext}")
                if not os.path.exists(candidate):
                    backup_path = candidate
                    break
                n += 1
        shutil.copy2(file_path, backup_path)

        # Rotation: trim oldest backups (for this label) if max_keep is set.
        if max_keep is not None and max_keep > 0:
            try:
                existing.insert(0, backup_path)  # new one is newest
                for old in existing[max_keep:]:
                    try:
                        os.remove(old)
                    except OSError:
                        pass
            except OSError:
                pass

        return backup_path

    except Exception as e:
        print(f"Warning: Failed to create backup: {e}")
        return None


def get_filter_directory(file_path: str) -> str:
    """Get the directory containing the filter file.

    Args:
        file_path: Path to the filter file

    Returns:
        Directory path
    """
    return os.path.dirname(os.path.abspath(file_path))


def copy_sound_file(source_path: str, filter_directory: str) -> str:
    """Copy a sound file to the filter directory.

    Args:
        source_path: Path to the source sound file
        filter_directory: Directory where the filter file is located

    Returns:
        Path to the copied file

    Raises:
        FileNotFoundError: If source file doesn't exist
        IOError: If copy fails
    """
    if not os.path.isfile(source_path):
        raise FileNotFoundError(f"Sound file not found: {source_path}")

    filename = os.path.basename(source_path)
    dest_path = os.path.join(filter_directory, filename)

    # Only copy if source and destination are different
    if os.path.normpath(source_path) != os.path.normpath(dest_path):
        shutil.copy2(source_path, dest_path)

    return dest_path


def validate_filter_extension(file_path: str) -> bool:
    """Check if file has .filter extension.

    Args:
        file_path: Path to check

    Returns:
        True if file has .filter extension
    """
    return file_path.lower().endswith('.filter')


def get_poe2_filter_directory() -> Optional[str]:
    """Get the standard POE2 filter directory for the current user.

    Returns:
        Path to POE2 filter directory, or None if not found
    """
    # Windows path
    if os.name == 'nt':
        userprofile = os.environ.get('USERPROFILE')
        if userprofile:
            poe2_dir = os.path.join(userprofile, 'Documents', 'My Games', 'Path of Exile 2')
            if os.path.isdir(poe2_dir):
                return poe2_dir

    # Linux path
    home = os.path.expanduser('~')
    poe2_dir = os.path.join(home, '.local', 'share', 'Path of Exile 2')
    if os.path.isdir(poe2_dir):
        return poe2_dir

    return None
