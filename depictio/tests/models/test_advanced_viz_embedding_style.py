"""EmbeddingConfig: point size, axis line width and outline colour."""

import pytest
from pydantic import ValidationError

from depictio.models.components.advanced_viz.configs import EmbeddingConfig


def test_defaults_keep_the_historical_look():
    cfg = EmbeddingConfig()
    assert cfg.point_size is None
    assert cfg.axis_line_width == 1
    assert cfg.marker_outline is False
    assert cfg.marker_outline_color == "contrast"


def test_explicit_values():
    cfg = EmbeddingConfig(
        point_size=25, axis_line_width=3, marker_outline=True, marker_outline_color="background"
    )
    assert (cfg.point_size, cfg.axis_line_width, cfg.marker_outline_color) == (25, 3, "background")


@pytest.mark.parametrize(
    "bad",
    [
        {"axis_line_width": 0.5},
        {"axis_line_width": 7},
        {"marker_outline_color": "red"},
        {"point_size": 31},
    ],
)
def test_out_of_range(bad):
    with pytest.raises(ValidationError):
        EmbeddingConfig(**bad)


def test_server_figure_draws_an_explicit_size_on_a_dense_cloud():
    from depictio.api.v1.services.advanced_viz.kinds.embedding import build

    rows = {"dim_1": list(range(1500)), "dim_2": list(range(1500))}
    sized = build(rows=rows, config={"point_size": 7}, controls={}, theme="light")
    unsized = build(rows=rows, config={}, controls={}, theme="light")
    assert sized["data"][0]["marker"]["size"] == 7
    assert unsized["data"][0]["marker"]["size"] == 4
