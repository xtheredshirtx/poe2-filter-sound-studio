"""End-to-end controller orchestration (preview/apply/restore, safety)."""

from __future__ import annotations

import os

from economy_tier import controller as controller_mod
from economy_tier.controller import EconomyTierController, Mode
from economy_tier.errors import TierDataError
from economy_tier.filter_visual_patcher import TransferOptions

TEXT = (
    'Show\n\tClass "Currency"\n\tBaseType == "Divine Orb"\n\tSetFontSize 30\n'
    "\tPlayAlertSound 1 300\n"
    'Show\n\tRarity Normal\n\tBaseType "Sapphire Ring"\n'
    'Hide\n\tBaseType "Scroll of Wisdom"\n'
)


def _ctrl(path):
    return EconomyTierController(path, open(path, encoding="utf-8").readlines())


def test_preview_writes_nothing(temp_filter, isolated_history):
    path = temp_filter(TEXT)
    before = open(path, encoding="utf-8").read()
    ctrl = _ctrl(path)
    pv = ctrl.build_preview(Mode.PREVIEW, TransferOptions(), "low")
    assert pv.changed >= 1
    assert open(path, encoding="utf-8").read() == before  # untouched


def test_preview_only_mode_does_not_apply(temp_filter, isolated_history):
    path = temp_filter(TEXT)
    ctrl = _ctrl(path)
    res = ctrl.apply(Mode.PREVIEW, TransferOptions(), "low")
    assert res.ok is False  # Preview Only never writes


def test_apply_writes_backup_and_preserves_sound(temp_filter, isolated_history):
    path = temp_filter(TEXT)
    ctrl = _ctrl(path)
    res = ctrl.apply(Mode.APPLY_CHANCE, TransferOptions(), "low")
    assert res.ok is True
    assert res.backup_path and os.path.isfile(res.backup_path)
    disk = open(path, encoding="utf-8").read()
    assert disk.count("PlayAlertSound 1 300") == 1
    assert "# [ETVP" in disk
    # Chance promotion happened on the Normal Sapphire Ring block.
    assert "SS_CHANCE_BASE" in disk


def test_apply_is_idempotent(temp_filter, isolated_history):
    path = temp_filter(TEXT)
    ctrl = _ctrl(path)
    ctrl.apply(Mode.APPLY, TransferOptions(), "low")
    res2 = ctrl.apply(Mode.APPLY, TransferOptions(), "low")
    assert res2.ok is True and res2.changed_count == 0


def test_restore_reverts(temp_filter, isolated_history):
    path = temp_filter(TEXT)
    original = open(path, encoding="utf-8").read()
    ctrl = _ctrl(path)
    ctrl.apply(Mode.APPLY, TransferOptions(), "low")
    assert open(path, encoding="utf-8").read() != original
    assert ctrl.has_restorable() is True
    res = ctrl.restore()
    assert res.ok is True
    assert open(path, encoding="utf-8").read() == original
    # Restore made its own backup (so it is itself undoable).
    backups = os.listdir(os.path.join(os.path.dirname(path), "backups"))
    assert len(backups) >= 2


def test_external_edit_aborts_apply(temp_filter, isolated_history):
    path = temp_filter(TEXT)
    ctrl = _ctrl(path)
    # Someone edits the file after the controller recorded its baseline.
    with open(path, "a", encoding="utf-8") as f:
        f.write('Show\n\tClass "Late"\n')
    res = ctrl.apply(Mode.APPLY, TransferOptions(), "low")
    assert res.ok is False
    assert "changed on disk" in res.message


def test_fingerprint_determinism(temp_filter, isolated_history):
    path = temp_filter(TEXT)
    ctrl = _ctrl(path)
    a = ctrl.build_preview(Mode.APPLY, TransferOptions(), "low")
    b = ctrl.build_preview(Mode.APPLY, TransferOptions(), "low")
    assert a.fingerprint == b.fingerprint


def test_graceful_disable_on_bad_data(temp_filter, isolated_history, monkeypatch):
    def boom(*_a, **_k):
        raise TierDataError("simulated bad data")

    monkeypatch.setattr(controller_mod, "load_tier_data", boom)
    path = temp_filter(TEXT)
    ctrl = _ctrl(path)
    assert ctrl.available is False
    assert "simulated bad data" in (ctrl.disabled_reason or "")
    # Apply refuses cleanly rather than crashing.
    res = ctrl.apply(Mode.APPLY, TransferOptions(), "low")
    assert res.ok is False


def test_reload_templates_picks_up_user_preset(
    temp_filter, isolated_history, tmp_path, monkeypatch
):
    up = str(tmp_path / "user.json")
    monkeypatch.setattr("economy_tier.visual_template_loader.user_templates_path", lambda: up)
    from economy_tier.visual_template_loader import Template, load_templates, save_user_template

    base = load_templates().get()

    path = temp_filter(TEXT)
    ctrl = _ctrl(path)
    assert "Mine" not in ctrl.template_names()  # no user file yet at construction
    # Save a preset, then reload -> it becomes available.
    save_user_template(Template(name="Mine", description="", tiers=base.tiers))
    ctrl.reload_templates(select="Mine")
    assert "Mine" in ctrl.template_names()
    assert ctrl.template_name == "Mine"
    assert ctrl.templates.is_user("Mine") is True
    # Applying with the user preset works end to end.
    res = ctrl.apply(Mode.APPLY, TransferOptions(), "low")
    assert res.ok is True
