"""Operation history persistence + restore lookup (A.11)."""

from __future__ import annotations

from economy_tier.op_history import OpHistory, new_entry


def test_record_and_lookup(tmp_path):
    p = str(tmp_path / "hist.json")
    h = OpHistory.load(p)
    assert h.has_restorable("/f.filter") is False

    h.record(
        new_entry(
            "Apply Economy Tier Visuals",
            "/f.filter",
            "ORIG",
            "NEW",
            template="T",
            changed_block_count=3,
            fingerprint="abc",
        )
    )
    assert h.has_restorable("/f.filter") is True
    entry = h.last_apply_for("/f.filter")
    assert entry is not None and entry.original_content == "ORIG"


def test_restore_entries_not_counted(tmp_path):
    p = str(tmp_path / "hist.json")
    h = OpHistory.load(p)
    h.record(new_entry("Apply Economy Tier Visuals", "/f.filter", "A", "B"))
    h.record(new_entry("Restore Previous Visuals", "/f.filter", "B", "A"))
    # last_apply skips the restore and returns the apply.
    assert h.last_apply_for("/f.filter").original_content == "A"


def test_persistence_roundtrip(tmp_path):
    p = str(tmp_path / "hist.json")
    h = OpHistory.load(p)
    h.record(new_entry("Apply Economy Tier Visuals", "/f.filter", "X", "Y"))
    reloaded = OpHistory.load(p)
    assert len(reloaded.entries) == 1
    assert reloaded.entries[0].new_content == "Y"


def test_corrupt_history_starts_fresh(tmp_path):
    p = tmp_path / "hist.json"
    p.write_text("{not json", encoding="utf-8")
    h = OpHistory.load(str(p))
    assert h.entries == []


def test_other_file_not_restorable(tmp_path):
    p = str(tmp_path / "hist.json")
    h = OpHistory.load(p)
    h.record(new_entry("Apply Economy Tier Visuals", "/a.filter", "X", "Y"))
    assert h.has_restorable("/b.filter") is False
