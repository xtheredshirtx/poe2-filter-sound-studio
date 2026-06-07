"""Extra targeted tests covering error/edge branches in the I/O modules."""

from __future__ import annotations

import os

import pytest

from economy_tier import backup_manager as bm
from economy_tier.controller import EconomyTierController, Mode
from economy_tier.errors import BackupError, TierDataError
from economy_tier.filter_visual_patcher import TransferOptions
from economy_tier.schema_validation import load_and_validate


def test_compute_state_missing_file(tmp_path):
    st = bm.compute_state(str(tmp_path / "nope.filter"))
    assert st.exists is False
    assert st.size == -1


def test_atomic_write_bad_dir_raises():
    with pytest.raises(BackupError):
        bm.atomic_write(os.path.join("Z:\\no\\such\\dir", "x.filter"), "data")


def test_schema_validation_missing_file(tmp_path):
    with pytest.raises(TierDataError):
        load_and_validate(str(tmp_path / "missing.json"), "tiers", TierDataError)


def test_schema_validation_non_object(tmp_path):
    p = tmp_path / "arr.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(TierDataError):
        load_and_validate(str(p), "tiers", TierDataError)


def test_restore_with_no_history(temp_filter, isolated_history):
    path = temp_filter('Show\n\tBaseType == "Divine Orb"\n')
    ctrl = EconomyTierController(path, open(path, encoding="utf-8").readlines())
    res = ctrl.restore()
    assert res.ok is False
    assert "No previous" in res.message


def test_apply_wrong_mode_rejected(temp_filter, isolated_history):
    path = temp_filter('Show\n\tBaseType == "Divine Orb"\n')
    ctrl = EconomyTierController(path, open(path, encoding="utf-8").readlines())
    res = ctrl.apply(Mode.RESTORE, TransferOptions(), "low")
    assert res.ok is False


def test_no_change_apply_returns_ok(temp_filter, isolated_history):
    # A filter with nothing classifiable at 'high' confidence -> 0 changes.
    path = temp_filter('Show\n\tBaseType "Totally Unknown Base"\n')
    ctrl = EconomyTierController(path, open(path, encoding="utf-8").readlines())
    res = ctrl.apply(Mode.APPLY, TransferOptions(), "high")
    assert res.ok is True and res.changed_count == 0
