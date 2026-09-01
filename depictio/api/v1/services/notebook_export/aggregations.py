"""Polars source for a card's scalar aggregation.

Mirrors ``routes._agg_expr`` (the pushdown form the card endpoint uses) and,
for the precompute-parity aggregations, the shared ``_POLARS_AGG_EXPRS``
factories. A parity test evaluates every emitted expression against the
server's for the whole ``AggregationFunction`` literal.
"""

from __future__ import annotations


def agg_expr_source(column: str, aggregation: str) -> str | None:
    """``pl.col(column).<reduction>`` as text, or ``None`` when the server has no expression.

    ``box_plot_stats`` is a compound payload and ``mode`` deliberately goes
    through the materialised path on the server (ties have no stable order),
    so neither is expressible here; such cards reach the notebook via the API.
    """
    agg = (aggregation or "").lower()
    col = f"pl.col({column!r})"
    if agg == "count":
        return f"{col}.drop_nulls().len()"
    if agg in ("average", "mean"):
        return f"{col}.mean()"
    if agg == "sum":
        return f"{col}.sum()"
    if agg == "median":
        return f"{col}.median()"
    if agg == "min":
        return f"{col}.min()"
    if agg == "max":
        return f"{col}.max()"
    if agg in ("std", "std_dev"):
        return f"{col}.std()"
    if agg in ("variance", "var"):
        return f"{col}.var()"
    if agg in ("nunique", "unique"):
        return f"{col}.n_unique()"
    if agg == "range":
        return f"{col}.max() - {col}.min()"
    if agg in ("q1", "q3"):
        q = 0.25 if agg == "q1" else 0.75
        return f'{col}.quantile({q}, interpolation="linear")'
    if agg == "skewness":
        # Undefined below 3 observations: the server's precompute factory
        # guards the same way so tiny columns read as null, not as a number.
        return f"pl.when({col}.count() >= 3).then({col}.skew(bias=False))"
    if agg == "kurtosis":
        return f"pl.when({col}.count() >= 4).then({col}.kurtosis(bias=False))"
    if agg == "percentile":
        return f'{col}.quantile(0.5, interpolation="linear")'
    return None
