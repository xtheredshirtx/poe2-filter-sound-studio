"""Load economy visual templates and validate every emitted token (A.4/A.5).

A *template* maps a tier name (``"SS"``, ``"A"`` ...) to a :class:`TierStyle`
describing the visual directives to apply. The loader schema-validates the file,
then validates every colour/effect/minimap token against PoE's enums so a bad
template fails at load with a precise message rather than producing a filter the
game rejects.

Critically: a template NEVER contains a sound directive. The schema forbids
unknown style keys, and this module only ever emits the six visual directives.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from economy_tier import SCHEMA_VERSION
from economy_tier.directive_value_validator import (
    validate_font_size,
    validate_minimap,
    validate_play_effect,
    validate_rgba,
)
from economy_tier.errors import TemplateError
from economy_tier.resources import templates_path
from economy_tier.schema_validation import load_and_validate

RGBA = tuple[int, int, int, int]


@dataclass(frozen=True)
class TierStyle:
    """Visual directives for one tier. Any field left ``None`` is not applied."""

    text_color: RGBA | None = None
    bg_color: RGBA | None = None
    border_color: RGBA | None = None
    font_size: int | None = None
    play_effect: tuple[str, bool] | None = None  # (color, is_temp)
    minimap: tuple[int, str, str] | None = None  # (size, color, shape)


@dataclass(frozen=True)
class Template:
    """A named set of per-tier styles."""

    name: str
    description: str
    tiers: dict[str, TierStyle]

    def style_for(self, tier: str) -> TierStyle | None:
        return self.tiers.get(tier)


@dataclass
class TemplateSet:
    """All templates loaded from one file, keyed by name."""

    schema_version: int
    templates: dict[str, Template]
    default_name: str
    fingerprint: str = ""

    def get(self, name: str | None = None) -> Template:
        if name is None:
            name = self.default_name
        try:
            return self.templates[name]
        except KeyError as exc:
            raise TemplateError(f"No template named {name!r}") from exc

    def names(self) -> list[str]:
        return list(self.templates.keys())


def _rgba(value: Any) -> RGBA:
    errs = validate_rgba(value)
    if errs:
        raise TemplateError("; ".join(errs))
    out = list(value)
    if len(out) == 3:
        out.append(255)
    return (int(out[0]), int(out[1]), int(out[2]), int(out[3]))


def _tier_style_from_dict(tier: str, d: dict[str, Any]) -> TierStyle:
    text = _rgba(d["text_color"]) if "text_color" in d else None
    bg = _rgba(d["bg_color"]) if "bg_color" in d else None
    border = _rgba(d["border_color"]) if "border_color" in d else None

    font: int | None = None
    if "font_size" in d:
        errs = validate_font_size(d["font_size"])
        if errs:
            raise TemplateError(f"tier {tier}: " + "; ".join(errs))
        font = int(d["font_size"])

    effect: tuple[str, bool] | None = None
    if "play_effect" in d:
        errs = validate_play_effect(d["play_effect"])
        if errs:
            raise TemplateError(f"tier {tier}: " + "; ".join(errs))
        pe = d["play_effect"]
        effect = (str(pe[0]), bool(pe[1]) if len(pe) > 1 else False)

    minimap: tuple[int, str, str] | None = None
    if "minimap" in d:
        errs = validate_minimap(d["minimap"])
        if errs:
            raise TemplateError(f"tier {tier}: " + "; ".join(errs))
        mm = d["minimap"]
        minimap = (int(mm[0]), str(mm[1]), str(mm[2]))

    return TierStyle(
        text_color=text,
        bg_color=bg,
        border_color=border,
        font_size=font,
        play_effect=effect,
        minimap=minimap,
    )


def load_templates(path: str | None = None) -> TemplateSet:
    """Load, schema-validate, and token-validate the templates file.

    Raises :class:`TemplateError` on any problem.
    """
    data_path = path or templates_path()
    data = load_and_validate(data_path, "templates", TemplateError)

    version = int(data.get("schema_version", 0))
    if version != SCHEMA_VERSION:
        raise TemplateError(
            f"Unsupported templates schema_version {version} "
            f"(this build supports {SCHEMA_VERSION})."
        )

    templates: dict[str, Template] = {}
    default_name: str | None = None
    for tpl in data["templates"]:
        name = str(tpl["name"])
        if default_name is None:
            default_name = name
        tier_styles: dict[str, TierStyle] = {}
        for tier, style_dict in tpl["tiers"].items():
            tier_styles[tier] = _tier_style_from_dict(tier, style_dict)
        templates[name] = Template(
            name=name,
            description=str(tpl.get("description", "")),
            tiers=tier_styles,
        )

    if not templates or default_name is None:
        raise TemplateError(f"{data_path} contains no templates")

    fp = hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    return TemplateSet(
        schema_version=version,
        templates=templates,
        default_name=default_name,
        fingerprint=fp,
    )


__all__ = [
    "RGBA",
    "TierStyle",
    "Template",
    "TemplateSet",
    "load_templates",
]
