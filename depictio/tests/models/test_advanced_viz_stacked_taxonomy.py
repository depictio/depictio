"""stacked_taxonomy options for a composition that is not a taxonomy."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from depictio.models.components.advanced_viz.configs import StackedTaxonomyConfig


def test_defaults_keep_the_taxonomy_tile() -> None:
    cfg = StackedTaxonomyConfig()
    assert cfg.hidden_controls is None
    assert cfg.rank_label is None
    assert cfg.x_title is None
    assert cfg.legend_pos == "bottom"
    assert cfg.category_palette is None


def test_non_taxonomy_options_validate() -> None:
    cfg = StackedTaxonomyConfig(
        hidden_controls=["rank", "top_n", "sample_sort"],
        rank_label="Level",
        x_title="",
        legend_pos="right",
        category_palette={"FSM": "#228be6"},
    )
    assert cfg.hidden_controls == ["rank", "top_n", "sample_sort"]
    assert cfg.x_title == ""


@pytest.mark.parametrize(
    "bad", [{"hidden_controls": ["legend"]}, {"legend_pos": "top"}, {"hide_rank": True}]
)
def test_unknown_values_are_refused(bad: dict) -> None:
    with pytest.raises(ValidationError):
        StackedTaxonomyConfig(**bad)
