"""`UpsetPlotConfig` names its sets by list or by pattern, never both.

A template whose set columns are one per sample of the run cannot list them:
a list written against one run fails on every other. The pattern is the field
that makes such a template portable, so these tests pin that it is accepted,
that it must compile, and that it cannot be combined with a list.
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from depictio.models.components.advanced_viz.configs import UpsetPlotConfig, VizConfig


def test_pattern_is_accepted() -> None:
    cfg = UpsetPlotConfig(set_columns_pattern=r"\.mLb\.clN$")
    assert cfg.set_columns_pattern == r"\.mLb\.clN$"
    assert cfg.set_columns is None


def test_neither_field_still_means_auto_detect() -> None:
    cfg = UpsetPlotConfig()
    assert cfg.set_columns is None
    assert cfg.set_columns_pattern is None


def test_explicit_list_is_still_accepted() -> None:
    assert UpsetPlotConfig(set_columns=["a", "b"]).set_columns == ["a", "b"]


def test_list_and_pattern_are_mutually_exclusive() -> None:
    with pytest.raises(ValidationError, match="mutually exclusive"):
        UpsetPlotConfig(set_columns=["a"], set_columns_pattern="a")


def test_pattern_must_compile() -> None:
    with pytest.raises(ValidationError, match="regular expression"):
        UpsetPlotConfig(set_columns_pattern="(unclosed")


def test_empty_pattern_is_rejected() -> None:
    # An empty pattern matches every binary column, which is auto-detect with
    # extra steps; omit the field instead.
    with pytest.raises(ValidationError):
        UpsetPlotConfig(set_columns_pattern="")


def test_pattern_survives_the_viz_config_union() -> None:
    cfg = TypeAdapter(VizConfig).validate_python(
        {"viz_kind": "upset_plot", "set_columns_pattern": r"_R\d+$"}
    )
    assert isinstance(cfg, UpsetPlotConfig)
    assert cfg.set_columns_pattern == r"_R\d+$"
