"""Backup creation, external-edit detection, atomic writes (A.7)."""

from __future__ import annotations

import os

import pytest

from economy_tier import backup_manager as bm
from economy_tier.errors import BackupError, FileChangedError


def test_make_backup_creates_verified_copy(temp_filter):
    path = temp_filter('Show\n\tClass "Currency"\n')
    backup = bm.make_economy_backup(path)
    assert os.path.isfile(backup)
    assert "before_economy_tier_visuals" in os.path.basename(backup)
    assert open(backup, encoding="utf-8").read() == open(path, encoding="utf-8").read()


def test_make_backup_missing_file_raises(tmp_path):
    with pytest.raises(BackupError):
        bm.make_economy_backup(str(tmp_path / "nope.filter"))


def test_external_edit_detection(temp_filter):
    path = temp_filter("Show\n")
    state = bm.compute_state(path)
    bm.verify_unchanged(path, state)  # no change yet -> ok
    # Modify the file out-of-band.
    with open(path, "a", encoding="utf-8") as f:
        f.write("Hide\n")
    with pytest.raises(FileChangedError):
        bm.verify_unchanged(path, state)


def test_verify_unchanged_none_state_is_noop(temp_filter):
    path = temp_filter("Show\n")
    bm.verify_unchanged(path, None)  # should not raise


def test_atomic_write_roundtrip(tmp_path):
    p = str(tmp_path / "out.filter")
    bm.atomic_write(p, 'Show\n\tClass "X"\n')
    assert open(p, encoding="utf-8").read() == 'Show\n\tClass "X"\n'
    # No temp files left behind.
    assert not any(name.endswith(".tmp") for name in os.listdir(tmp_path))


def test_atomic_write_bom(tmp_path):
    p = str(tmp_path / "out.filter")
    bm.atomic_write(p, "Show\n", had_bom=True)
    assert open(p, "rb").read().startswith(b"\xef\xbb\xbf")


def test_backup_unique_names(temp_filter):
    path = temp_filter("Show\n")
    b1 = bm.make_economy_backup(path)
    b2 = bm.make_economy_backup(path)
    assert b1 != b2
