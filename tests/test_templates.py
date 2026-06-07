"""Visual template loading + token validation (A.4/A.5)."""

from __future__ import annotations

import json

import pytest

from economy_tier.errors import TemplateError
from economy_tier.resources import templates_path
from economy_tier.visual_template_loader import load_templates


def test_load_shipped_templates():
    ts = load_templates()
    assert ts.default_name == "High Contrast Economy Tiers"
    tpl = ts.get()
    ss = tpl.style_for("SS")
    assert ss is not None and ss.font_size == 45
    assert ss.play_effect == ("Red", True)
    assert ss.minimap == (0, "Red", "Star")
    # C tier carries no effect/minimap.
    c = tpl.style_for("C")
    assert c is not None and c.play_effect is None and c.minimap is None


def test_get_unknown_template_raises():
    ts = load_templates()
    with pytest.raises(TemplateError):
        ts.get("does not exist")


def _base_template():
    return json.loads(open(templates_path(), encoding="utf-8").read())


def test_invalid_color_token(tmp_path):
    raw = _base_template()
    raw["templates"][0]["tiers"]["SS"]["play_effect"] = ["Mauve", True]
    p = tmp_path / "t.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(TemplateError):
        load_templates(str(p))


def test_schema_violation(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"schema_version": 1, "templates": []}), encoding="utf-8")
    with pytest.raises(TemplateError):
        load_templates(str(p))


def test_bad_schema_version(tmp_path):
    raw = _base_template()
    raw["schema_version"] = 99
    p = tmp_path / "t.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(TemplateError):
        load_templates(str(p))


def test_rgba_three_gets_alpha(tmp_path):
    raw = _base_template()
    raw["templates"][0]["tiers"]["SS"]["text_color"] = [10, 20, 30]
    p = tmp_path / "t.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    ts = load_templates(str(p))
    assert ts.get().style_for("SS").text_color == (10, 20, 30, 255)
