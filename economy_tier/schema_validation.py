"""Shared JSON-Schema load + validate helper (A.5).

Loads a data file and its schema and validates one against the other, raising a
caller-supplied exception type with a precise message on any failure (missing
file, bad JSON, schema violation). ``jsonschema`` is the only dependency.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import jsonschema

from economy_tier.resources import schema_path


def load_and_validate(
    data_path: str,
    schema_name: str,
    error_cls: Callable[[str], Exception],
) -> dict[str, Any]:
    """Load ``data_path`` and validate it against ``<schema_name>.schema.json``.

    Raises ``error_cls`` with a human-readable message on any problem.
    """
    try:
        with open(data_path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as exc:
        raise error_cls(f"Data file not found: {data_path}") from exc
    except json.JSONDecodeError as exc:
        raise error_cls(f"Invalid JSON in {data_path}: {exc}") from exc
    except OSError as exc:
        raise error_cls(f"Could not read {data_path}: {exc}") from exc

    sp = schema_path(schema_name)
    try:
        with open(sp, encoding="utf-8") as f:
            schema = json.load(f)
    except OSError as exc:
        raise error_cls(f"Could not read schema {sp}: {exc}") from exc

    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        location = "/".join(str(p) for p in exc.absolute_path) or "(root)"
        raise error_cls(
            f"{data_path} failed schema validation at {location}: {exc.message}"
        ) from exc

    if not isinstance(data, dict):
        raise error_cls(f"{data_path} must contain a JSON object at the top level")
    return data


__all__ = ["load_and_validate"]
