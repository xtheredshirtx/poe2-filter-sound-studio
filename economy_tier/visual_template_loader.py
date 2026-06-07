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
import os
from dataclasses import dataclass, field
from typing import Any

from economy_tier import SCHEMA_VERSION
from economy_tier.directive_value_validator import (
    validate_font_size,
    validate_minimap,
    validate_play_effect,
    validate_rgba,
)
from economy_tier.errors import TemplateError
from economy_tier.logging_setup import get_logger
from economy_tier.resources import templates_path, user_templates_path
from economy_tier.schema_validation import load_and_validate

_log = get_logger()

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
    """All templates available, keyed by name (shipped + user presets)."""

    schema_version: int
    templates: dict[str, Template]
    default_name: str
    fingerprint: str = ""
    # Names that came from the user's editable preset file (the rest are the
    # read-only shipped templates). Used by the editor to allow overwrite/delete.
    user_names: set[str] = field(default_factory=set)

    def get(self, name: str | None = None) -> Template:
        if name is None:
            name = self.default_name
        try:
            return self.templates[name]
        except KeyError as exc:
            raise TemplateError(f"No template named {name!r}") from exc

    def names(self) -> list[str]:
        return list(self.templates.keys())

    def is_user(self, name: str) -> bool:
        return name in self.user_names


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


def load_all_templates(
    shipped_path: str | None = None,
    user_path: str | None = None,
) -> TemplateSet:
    """Load the shipped templates and overlay the user's saved presets.

    User presets (saved via :func:`save_user_template`) are added to / override
    the shipped set by name. A corrupt user file is logged and ignored so the
    shipped templates always remain available. The default template stays the
    shipped one.
    """
    shipped = load_templates(shipped_path)
    up = user_path or user_templates_path()
    if not os.path.isfile(up):
        return shipped

    try:
        user = load_templates(up)
    except TemplateError as exc:
        _log.warning("Ignoring unreadable user templates file %s: %s", up, exc)
        return shipped

    merged = dict(shipped.templates)
    merged.update(user.templates)
    return TemplateSet(
        schema_version=shipped.schema_version,
        templates=merged,
        default_name=shipped.default_name,
        fingerprint=hashlib.sha256(
            (shipped.fingerprint + user.fingerprint).encode("utf-8")
        ).hexdigest(),
        user_names=set(user.templates.keys()),
    )


# ---------------------------------------------------------------------------
# Serialization + user-preset persistence
# ---------------------------------------------------------------------------


def _tier_style_to_dict(style: TierStyle) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if style.text_color is not None:
        out["text_color"] = list(style.text_color)
    if style.bg_color is not None:
        out["bg_color"] = list(style.bg_color)
    if style.border_color is not None:
        out["border_color"] = list(style.border_color)
    if style.font_size is not None:
        out["font_size"] = style.font_size
    if style.play_effect is not None:
        out["play_effect"] = [style.play_effect[0], style.play_effect[1]]
    if style.minimap is not None:
        out["minimap"] = [style.minimap[0], style.minimap[1], style.minimap[2]]
    return out


def template_to_dict(template: Template) -> dict[str, Any]:
    """Serialize a :class:`Template` to its JSON-schema shape."""
    return {
        "name": template.name,
        "description": template.description,
        "tiers": {tier: _tier_style_to_dict(style) for tier, style in template.tiers.items()},
    }


def save_user_template(template: Template, user_path: str | None = None) -> None:
    """Add/replace a user preset by name and persist it (validated, atomic).

    The new file is validated (schema + every emitted token) by re-loading a
    temp copy *before* it replaces the real file, so a bad template can never
    corrupt the user's preset store. Raises :class:`TemplateError` on failure.
    """
    up = user_path or user_templates_path()

    existing: list[dict[str, Any]] = []
    if os.path.isfile(up):
        try:
            with open(up, encoding="utf-8") as f:
                existing = json.load(f).get("templates", [])
        except (OSError, json.JSONDecodeError):
            existing = []

    existing = [t for t in existing if t.get("name") != template.name]
    existing.append(template_to_dict(template))
    payload = {"schema_version": SCHEMA_VERSION, "templates": existing}

    os.makedirs(os.path.dirname(up), exist_ok=True)
    tmp = up + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    try:
        load_templates(tmp)  # schema + token validation
    except TemplateError:
        os.remove(tmp)
        raise
    os.replace(tmp, up)


def delete_user_template(name: str, user_path: str | None = None) -> bool:
    """Remove a user preset by name. Returns True if something was removed."""
    up = user_path or user_templates_path()
    if not os.path.isfile(up):
        return False
    try:
        with open(up, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    templates = data.get("templates", [])
    kept = [t for t in templates if t.get("name") != name]
    if len(kept) == len(templates):
        return False
    data["templates"] = kept
    tmp = up + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, up)
    return True


__all__ = [
    "RGBA",
    "TierStyle",
    "Template",
    "TemplateSet",
    "load_templates",
    "load_all_templates",
    "template_to_dict",
    "save_user_template",
    "delete_user_template",
]
