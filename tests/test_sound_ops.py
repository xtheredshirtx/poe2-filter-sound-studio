"""Tests for the pure sound-directive line editor (core/sound_ops.py)."""

from __future__ import annotations

from core.sound_ops import (
    block_bounds,
    detect_indent,
    remove_custom_sound,
    set_custom_sound,
)


def _block(*body: str) -> list[str]:
    return [f"{x}\n" for x in ("Show", *body)]


def test_block_bounds_and_indent():
    lines = _block('\tClass "Currency"', '\tBaseType "X"') + ["Show\n"]
    start, end = block_bounds(lines, 0)
    assert (start, end) == (0, 3)
    assert detect_indent(lines, start, end) == "\t"


def test_replace_existing_custom_sound():
    lines = _block('\tClass "Currency"', '\tCustomAlertSound "old.mp3" 200')
    inserted = set_custom_sound(lines, 0, len(lines), "new.mp3", 300)
    assert inserted is False
    assert '\tCustomAlertSound "new.mp3" 300\n' in lines
    assert "old.mp3" not in "".join(lines)


def test_insert_when_absent():
    lines = _block('\tClass "Currency"', '\tBaseType "X"')
    inserted = set_custom_sound(lines, 0, len(lines), "beep.mp3", 250)
    assert inserted is True
    assert lines[-1] == '\tCustomAlertSound "beep.mp3" 250\n'


def test_play_alert_sound_becomes_custom():
    lines = _block("\tPlayAlertSound 1 300")
    set_custom_sound(lines, 0, len(lines), "x.wav")
    assert any(ln.strip().startswith('CustomAlertSound "x.wav"') for ln in lines)
    assert not any("PlayAlertSound" in ln for ln in lines)


def test_active_only_ignores_commented_and_inserts():
    lines = _block('\t# CustomAlertSound "disabled.mp3" 100', '\tClass "X"')
    inserted = set_custom_sound(lines, 0, len(lines), "new.mp3", active_only=True)
    assert inserted is True  # no ACTIVE sound -> inserted
    # The commented line is untouched.
    assert '\t# CustomAlertSound "disabled.mp3" 100\n' in lines


def test_preserve_volume_keeps_existing():
    lines = _block('\tCustomAlertSound "old.mp3" 175')
    set_custom_sound(lines, 0, len(lines), "new.mp3", 300, preserve_volume=True)
    assert '\tCustomAlertSound "new.mp3" 175\n' in lines


def test_keep_disabled_compat_mode():
    # Compatibility mode used by the bulk replacer: replace commented lines too,
    # preserving the comment marker.
    lines = _block('\t# CustomAlertSound "x.mp3" 100')
    set_custom_sound(
        lines, 0, len(lines), "y.mp3", preserve_volume=True, keep_disabled=True, active_only=False
    )
    assert any(ln.strip().startswith('# CustomAlertSound "y.mp3"') for ln in lines)


def test_other_lines_untouched():
    lines = _block('\tClass "Currency"', "\tSetTextColor 1 2 3", "\tPlayAlertSound 1 300")
    set_custom_sound(lines, 0, len(lines), "z.mp3")
    assert '\tClass "Currency"\n' in lines
    assert "\tSetTextColor 1 2 3\n" in lines


def test_remove_custom_sound_active_only():
    lines = _block(
        '\tCustomAlertSound "a.mp3" 300',
        '\t# CustomAlertSound "b.mp3" 100',
        '\tClass "X"',
    )
    removed = remove_custom_sound(lines, 0, len(lines))
    assert removed == 1
    assert not any(ln.strip().startswith('CustomAlertSound "a.mp3"') for ln in lines)
    assert '\t# CustomAlertSound "b.mp3" 100\n' in lines  # commented kept
