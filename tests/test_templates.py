"""Visual template loading + token validation (A.4/A.5)."""

from __future__ import annotations

import json
import os

import pytest

from economy_tier.errors import TemplateError
from economy_tier.resources import templates_path
from economy_tier.visual_template_loader import (
    Template,
    TierStyle,
    delete_user_template,
    load_all_templates,
    load_templates,
    save_user_template,
    template_to_dict,
)


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


# --- user preset management (named presets) ---------------------------------


def _custom(name: str) -> Template:
    return Template(
        name=name,
        description="custom",
        tiers={
            "SS": TierStyle(
                text_color=(255, 255, 255, 255),
                bg_color=(10, 10, 10, 255),
                border_color=(255, 0, 0, 255),
                font_size=45,
                play_effect=("Red", True),
                minimap=(0, "Red", "Star"),
            ),
            "F": TierStyle(text_color=(80, 80, 80, 255), font_size=30),
        },
    )


def test_template_to_dict_round_trips():
    d = template_to_dict(_custom("X"))
    assert d["name"] == "X"
    assert d["tiers"]["SS"]["play_effect"] == ["Red", True]
    assert d["tiers"]["SS"]["minimap"] == [0, "Red", "Star"]
    assert "play_effect" not in d["tiers"]["F"]  # None fields omitted


def test_save_and_load_all_merges(tmp_path):
    up = str(tmp_path / "user.json")
    save_user_template(_custom("My Loud"), user_path=up)
    merged = load_all_templates(user_path=up)
    assert "My Loud" in merged.names()
    assert "High Contrast Economy Tiers" in merged.names()  # shipped still present
    assert merged.is_user("My Loud") is True
    assert merged.is_user("High Contrast Economy Tiers") is False


def test_save_overwrites_by_name(tmp_path):
    up = str(tmp_path / "user.json")
    save_user_template(_custom("Dup"), user_path=up)
    save_user_template(_custom("Dup"), user_path=up)
    assert load_all_templates(user_path=up).names().count("Dup") == 1


def test_delete_user_template(tmp_path):
    up = str(tmp_path / "user.json")
    save_user_template(_custom("Temp"), user_path=up)
    assert delete_user_template("Temp", user_path=up) is True
    assert "Temp" not in load_all_templates(user_path=up).names()
    assert delete_user_template("Temp", user_path=up) is False  # already gone


def test_save_rejects_invalid_token(tmp_path):
    up = str(tmp_path / "user.json")
    bad = Template(name="Bad", description="", tiers={"SS": TierStyle(font_size=999)})
    with pytest.raises(TemplateError):
        save_user_template(bad, user_path=up)
    assert not os.path.exists(up)  # nothing written


def test_load_all_ignores_corrupt_user_file(tmp_path):
    up = tmp_path / "user.json"
    up.write_text("{not json", encoding="utf-8")
    merged = load_all_templates(user_path=str(up))
    assert "High Contrast Economy Tiers" in merged.names()  # shipped survives
