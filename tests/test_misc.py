"""Coverage for resources, logging, schema_validation, errors."""

from __future__ import annotations

import os

import pytest

from economy_tier.errors import EconomyTierError, TierDataError
from economy_tier.logging_setup import get_logger
from economy_tier.resources import (
    op_history_path,
    resource_path,
    schema_path,
    templates_path,
    tier_data_path,
    user_data_dir,
)
from economy_tier.schema_validation import load_and_validate


def test_resource_paths_exist():
    assert os.path.isfile(tier_data_path())
    assert os.path.isfile(templates_path())
    assert os.path.isfile(schema_path("tiers"))
    assert resource_path("data").endswith("data")


def test_user_dirs_created():
    d = user_data_dir()
    assert os.path.isdir(d)
    assert op_history_path().endswith("op_history.json")


def test_logger_is_singleton():
    a = get_logger()
    b = get_logger()
    assert a is b
    # Re-configuring does not stack handlers.
    handlers_before = len(a.handlers)
    get_logger()
    assert len(a.handlers) == handlers_before


def test_schema_validation_errors(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{bad", encoding="utf-8")
    with pytest.raises(TierDataError):
        load_and_validate(str(p), "tiers", TierDataError)


def test_error_hierarchy():
    assert issubclass(TierDataError, EconomyTierError)
