"""The design columns of the hub, one row per sample: the confounders of the run.

The ``samples`` hub carries ``protocol``, ``source_replicate`` and ``run_id`` for
every run, as ``unknown`` when no design table (``METADATA_FILE``) was given. A
tile bound to the hub would then draw one-option filters and one-segment rings.
This collection holds the same three columns apart from the hub, so the
template can drop it when there is no design table: the library preparation,
source replicate and flow-cell run filters, and the rings that count by them,
are bound to it and leave the dashboard with it at import. The hub itself, and
every link of the sample filters, stay.

Sources:
    hub     ``samples`` (this template's ``samples.py``)

Output schema:
    sample_id : Utf8         the samplesheet ``sample`` column, as the hub has it
    protocol : Utf8          library preparation, from the design table
    source_replicate : Utf8  source-dataset replicate, from the design table
    run_id : Utf8            flow-cell run, from the design table
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="hub",
        dc_ref="samples",
        input_schema={
            "sample_id": pl.Utf8,
            "protocol": pl.Utf8,
            "source_replicate": pl.Utf8,
            "run_id": pl.Utf8,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "protocol": pl.Utf8,
    "source_replicate": pl.Utf8,
    "run_id": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """The hub's design columns, one row per sample."""
    return sources["hub"].select(list(OUTPUT_SCHEMA)).sort("sample_id")
