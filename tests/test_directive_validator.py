"""Game-valid directive value checks (A.4)."""

from __future__ import annotations

from economy_tier.directive_value_validator import (
    validate_font_size,
    validate_minimap,
    validate_play_effect,
    validate_rgba,
)


def test_rgba_valid():
    assert validate_rgba([255, 0, 128]) == []
    assert validate_rgba([255, 0, 128, 200]) == []


def test_rgba_invalid():
    assert validate_rgba([256, 0, 0]) != []
    assert validate_rgba([0, 0]) != []
    assert validate_rgba([-1, 0, 0, 0]) != []
    assert validate_rgba([True, 0, 0]) != []  # bool is not a valid channel


def test_font_size():
    assert validate_font_size(40) == []
    assert validate_font_size(0) != []
    assert validate_font_size(61) != []
    assert validate_font_size("40") != []


def test_play_effect():
    assert validate_play_effect(["Red", True]) == []
    assert validate_play_effect(["Red"]) == []
    assert validate_play_effect(["Mauve", True]) != []
    assert validate_play_effect([]) != []


def test_minimap():
    assert validate_minimap([0, "Red", "Star"]) == []
    assert validate_minimap([3, "Red", "Star"]) != []  # bad size
    assert validate_minimap([0, "Mauve", "Star"]) != []  # bad colour
    assert validate_minimap([0, "Red", "Blob"]) != []  # bad shape
    assert validate_minimap([0, "Red"]) != []  # wrong length
