"""Carry a run's design columns from the ``samples`` hub onto a recipe's output.

A template may declare a sample sheet under the repo-wide ``samples`` tag, and
when it does, an output is far more useful coloured by the factor the run
compares than by the sample id. The hub is optional though, and a template that
declares one need not declare every design column, so the columns have to exist
either way: a figure bound to ``treatment`` must find a ``treatment`` column,
null everywhere, rather than fail to build.

Shared here rather than copied because more than one recipe joins the same hub
the same way, and recipes may not import one another.
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

HUB_KEY = "sample_id"


def annotate_from_hub(
    frame: pl.DataFrame,
    samples: pl.DataFrame | None,
    columns: Sequence[str],
    *,
    left_on: str = HUB_KEY,
) -> pl.DataFrame:
    """Left-join the hub's design ``columns``, null-filling the absent ones.

    ``left_on`` names ``frame``'s own sample column; the hub is always keyed on
    ``sample_id``.
    """
    carried = (
        [c for c in columns if c in samples.columns]
        if samples is not None and not samples.is_empty() and HUB_KEY in samples.columns
        else []
    )
    if carried:
        frame = frame.join(
            samples.select(HUB_KEY, *carried).unique(subset=HUB_KEY),
            left_on=left_on,
            right_on=HUB_KEY,
            how="left",
        )
    return frame.with_columns(
        *[
            (pl.col(column) if column in carried else pl.lit(None)).cast(pl.Utf8).alias(column)
            for column in columns
        ]
    )
