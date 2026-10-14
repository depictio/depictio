"""stacked_taxonomy options for a composition that is not a taxonomy."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from depictio.models.components.advanced_viz.configs import ScatterXyConfig, StackedTaxonomyConfig


def test_defaults_keep_the_taxonomy_tile() -> None:
    cfg = StackedTaxonomyConfig()
    assert cfg.hidden_controls is None
    assert cfg.rank_label is None
    assert cfg.x_title is None
    # The legend has sat in a column right of the bars since it collided with
    # the tilted sample labels underneath them.
    assert cfg.legend_pos == "right"


def test_non_taxonomy_options_validate() -> None:
    cfg = StackedTaxonomyConfig(
        hidden_controls=["rank", "top_n", "sample_sort"],
        rank_label="Level",
        x_title="",
        legend_pos="bottom",
        taxon_palette={"FSM": "#228be6"},
    )
    assert cfg.hidden_controls == ["rank", "top_n", "sample_sort"]
    assert cfg.x_title == ""
    assert cfg.legend_pos == "bottom"


@pytest.mark.parametrize(
    "bad",
    [
        {"hidden_controls": ["legend"]},
        {"legend_pos": "top"},
        {"hide_rank": True},
        # The component's own colours are `taxon_palette`; the dashboard's
        # `category_colors` cover the rest.
        {"category_palette": {"FSM": "#228be6"}},
    ],
)
def test_unknown_values_are_refused(bad: dict) -> None:
    with pytest.raises(ValidationError):
        StackedTaxonomyConfig(**bad)


def test_scatter_colours_come_from_the_dashboard() -> None:
    """A scatter's categories take `category_colors`, never a per-tile map."""
    with pytest.raises(ValidationError):
        ScatterXyConfig(color_col="engine", category_palette={"esmfold": "#228be6"})
