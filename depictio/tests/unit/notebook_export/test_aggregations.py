"""Card reductions emitted for the notebook agree with the server's."""

from typing import get_args

import polars as pl
import pytest

from depictio.api.v1.services.notebook_export.aggregations import agg_expr_source
from depictio.models.components.types import AggregationFunction

FRAME = pl.DataFrame({"v": [1.0, 2.0, 2.0, 5.0, None, 9.5, 3.25]})
NO_EXPRESSION = {"box_plot_stats", "mode"}


@pytest.mark.parametrize("aggregation", sorted(get_args(AggregationFunction)))
def test_every_aggregation_is_classified(aggregation):
    src = agg_expr_source("v", aggregation)
    if aggregation in NO_EXPRESSION:
        assert src is None
    else:
        assert src is not None


@pytest.mark.parametrize("aggregation", sorted(set(get_args(AggregationFunction)) - NO_EXPRESSION))
def test_emitted_reduction_matches_server_expression(aggregation):
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import _agg_expr, _agg_value

    server_expr = _agg_expr("v", aggregation)
    assert server_expr is not None
    emitted = eval(agg_expr_source("v", aggregation), {"pl": pl})  # noqa: S307
    got = FRAME.select(emitted).item()
    want = FRAME.select(server_expr).item()
    assert got == pytest.approx(want)
    # ...and with the materialised path the card endpoint falls back to.
    materialised = _agg_value(FRAME["v"], aggregation)
    assert got == pytest.approx(materialised)
