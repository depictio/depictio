"""`ComplexHeatmapConfig` names its value columns by list or by pattern, never both.

A template whose heatmap columns are one per sample of the run cannot list
them: a list written against one run fails on every other. The pattern is the
field that makes such a template portable, so these tests pin that it is
accepted, that it must compile, and that it cannot be combined with a list.
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from depictio.models.components.advanced_viz.configs import ComplexHeatmapConfig, VizConfig


def test_pattern_is_accepted() -> None:
    cfg = ComplexHeatmapConfig(value_columns_pattern=r"\.mLb\.clN$")
    assert cfg.value_columns_pattern == r"\.mLb\.clN$"
    assert cfg.value_columns is None


def test_neither_field_still_means_every_numeric_column() -> None:
    cfg = ComplexHeatmapConfig()
    assert cfg.value_columns is None
    assert cfg.value_columns_pattern is None


def test_list_and_pattern_are_mutually_exclusive() -> None:
    with pytest.raises(ValidationError, match="mutually exclusive"):
        ComplexHeatmapConfig(value_columns=["a"], value_columns_pattern="a")


def test_pattern_must_compile() -> None:
    with pytest.raises(ValidationError, match="regular expression"):
        ComplexHeatmapConfig(value_columns_pattern="(unclosed")


def test_empty_pattern_is_rejected() -> None:
    # An empty pattern matches every numeric column, which is the default with
    # extra steps; omit the field instead.
    with pytest.raises(ValidationError):
        ComplexHeatmapConfig(value_columns_pattern="")


def test_pattern_survives_the_viz_config_union() -> None:
    cfg = TypeAdapter(VizConfig).validate_python(
        {"viz_kind": "complex_heatmap", "value_columns_pattern": r"_R\d+$"}
    )
    assert isinstance(cfg, ComplexHeatmapConfig)
    assert cfg.value_columns_pattern == r"_R\d+$"


def test_height_caps_are_opt_in() -> None:
    cfg = ComplexHeatmapConfig()
    assert cfg.min_cell_px is None
    assert cfg.max_rows is None


def test_height_caps_survive_the_viz_config_union() -> None:
    cfg = TypeAdapter(VizConfig).validate_python(
        {"viz_kind": "complex_heatmap", "min_cell_px": 6, "max_rows": 8}
    )
    assert isinstance(cfg, ComplexHeatmapConfig)
    assert (cfg.min_cell_px, cfg.max_rows) == (6, 8)


@pytest.mark.parametrize("field, value", [("min_cell_px", 1), ("max_rows", 2), ("max_rows", 17)])
def test_height_caps_are_bounded(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        ComplexHeatmapConfig(**{field: value})
