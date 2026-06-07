"""Parser round-trip fidelity + directive parsing (A.1, A.3)."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from economy_tier.filter_parser import parse, read_text, serialize, write_text
from tests.conftest import SAMPLE_BASIC, fixture_text

ROUND_TRIP_SAMPLES = [
    "",
    "Show",
    "Show\n",
    'Show\r\n\tClass "Currency"\r\n',
    "# comment only\n\n\n",
    'Show\n\tBaseType "a#b" # real comment\n',
    "Hide\n\t# SetTextColor 1 2 3\n\tWaystoneTier >= 15\n",
    'Show\r\n\tSetTextColor 255 0 0  # red\r\nHide\r\n\tBaseType "Foo"\r\n',
    'Show\n\tClass\t\t"Currency"   \n',  # odd whitespace
    SAMPLE_BASIC,
]


def test_round_trip_samples():
    for s in ROUND_TRIP_SAMPLES:
        assert serialize(parse(s)) == s, repr(s)


def test_round_trip_fixture():
    text = fixture_text("sample_basic.filter")
    assert serialize(parse(text)) == text


def test_no_trailing_newline_preserved():
    s = 'Show\n\tClass "Currency"'  # no final newline
    assert serialize(parse(s)) == s


def test_crlf_and_lf_mixed_preserved():
    s = 'Show\r\n\tClass "X"\nHide\r\n'
    assert serialize(parse(s)) == s


def test_bom_round_trip(tmp_path):
    p = tmp_path / "bom.filter"
    p.write_bytes(b'\xef\xbb\xbfShow\n\tClass "Currency"\n')
    text, had_bom = read_text(str(p))
    assert had_bom is True
    assert not text.startswith("﻿")
    doc = parse(text, had_bom=had_bom)
    out = tmp_path / "out.filter"
    write_text(str(out), serialize(doc), had_bom=had_bom)
    assert out.read_bytes() == p.read_bytes()


def test_block_grouping_and_headers():
    doc = parse(SAMPLE_BASIC)
    assert len(doc.blocks) == 3
    assert doc.blocks[0].is_hide is False
    assert doc.blocks[2].is_hide is True


def test_directive_operator_and_values():
    doc = parse('Show\n\tBaseType == "Divine Orb" "Chaos Orb"\n\tClass "Currency"\n')
    b = doc.blocks[0]
    assert b.basetype_values() == [("Divine Orb", True), ("Chaos Orb", True)]
    assert b.class_values() == [("Currency", False)]


def test_substring_vs_exact():
    doc = parse('Show\n\tBaseType "Sapphire Ring"\nShow\n\tBaseType == "Sapphire Ring"\n')
    assert doc.blocks[0].basetype_values() == [("Sapphire Ring", False)]
    assert doc.blocks[1].basetype_values() == [("Sapphire Ring", True)]


def test_numeric_directive():
    d = parse("Show\n\tWaystoneTier >= 15\n").blocks[0].first("WaystoneTier")
    assert d is not None
    assert d.operator == ">="
    assert d.numeric_value() == 15


def test_sound_lines_detected():
    doc = parse('Show\n\tPlayAlertSound 1 300\n\tCustomAlertSound "x.wav"\n')
    sounds = doc.blocks[0].sound_lines()
    assert len(sounds) == 2


def test_disabled_directive_is_not_active():
    doc = parse("Show\n\t# SetTextColor 1 2 3\n")
    b = doc.blocks[0]
    # The disabled visual line must not appear as an active directive value.
    assert b.first("SetTextColor") is None


def test_inline_comment_with_hash_in_quotes():
    d = parse('Show\n\tBaseType "a#b"\n').blocks[0].first("BaseType")
    assert d is not None
    assert d.values == ["a#b"]


def test_sentinel_detection():
    doc = parse('Show\n\t# [ETVP tier=SS template="X" v=1]\n')
    assert doc.blocks[0].has_sentinel() is True


# --- property-based round trip (A.10) ---------------------------------------

_token = st.text(alphabet='ABCDEdivneOrb "\t#', min_size=0, max_size=20)
_line = st.builds(
    lambda kw, rest, nl: kw + rest + nl,
    st.sampled_from(["Show", "Hide", "\tClass", "\tBaseType", "#c", "", "\tSetFontSize"]),
    _token,
    st.sampled_from(["\n", "\r\n", ""]),
)


@settings(max_examples=200)
@given(st.lists(_line, max_size=15))
def test_property_round_trip(lines):
    text = "".join(lines)
    assert serialize(parse(text)) == text
