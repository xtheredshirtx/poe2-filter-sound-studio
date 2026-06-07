"""Shared pytest fixtures and helpers for the economy_tier test suite."""

from __future__ import annotations

import os
import sys

import pytest

# Ensure the project root is importable when pytest is run from anywhere.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture_text(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


SAMPLE_BASIC = """\
Show
\tClass "Currency"
\tBaseType == "Divine Orb"
\tSetFontSize 30
\tPlayAlertSound 1 300
Show
\tClass "Rings"
\tRarity Normal
\tBaseType "Sapphire Ring"
Hide
\tClass "Currency"
\tBaseType "Scroll of Wisdom"
"""


@pytest.fixture()
def isolated_history(tmp_path, monkeypatch):
    """Redirect op-history to a temp file so tests don't touch user config."""
    hist = tmp_path / "op_history.json"
    monkeypatch.setattr("economy_tier.op_history.op_history_path", lambda: str(hist))
    return str(hist)


@pytest.fixture()
def temp_filter(tmp_path):
    """Factory: write filter text to a temp .filter file and return its path."""

    def _make(text: str, name: str = "test.filter") -> str:
        p = tmp_path / name
        p.write_text(text, encoding="utf-8", newline="")
        return str(p)

    return _make
