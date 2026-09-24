"""Identifications against FDR threshold per raw file, from the Comet search.

For every raw file, the number of target PSMs accepted as the target-decoy
q-value threshold on the raw Comet ``Xcorr`` is relaxed from 0 to 10%, next to
the Xcorr score at that threshold. The curve rises steeply for a file with good
spectra and flattens early for a poor one; the 1% point is the usual reporting
threshold. Each curve is thinned to ``MAX_POINTS`` points on the q-value axis so
it can be drawn as a profile.

Source: the CometAdapter Percolator input tables ``<run>_pin.tsv`` (``Label`` 1
target, -1 decoy).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="pin",
        glob_pattern="**/*_pin.tsv",
        format="tsv",
        read_kwargs={
            "infer_schema_length": 0,
            "truncate_ragged_lines": True,
            "quote_char": None,
            "columns": ["Label", "Xcorr"],
        },
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "run_id": pl.Utf8,
    "q_value": pl.Float64,
    "accepted_psms": pl.Int64,
    "xcorr_threshold": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

MAX_Q = 0.10
MAX_POINTS = 200


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    pin = (
        sources["pin"]
        .with_columns(
            pl.col("source_path")
            .str.split("/")
            .list.last()
            .str.replace(r"_pin\.tsv$", "")
            .alias("run_id"),
            (pl.col("Label").cast(pl.Int64, strict=False) == -1).alias("is_decoy"),
            pl.col("Xcorr").cast(pl.Float64, strict=False).alias("xcorr"),
        )
        .filter(pl.col("Label").is_in(["1", "-1"]))
    )
    grid = pl.DataFrame(
        {"q_value": [MAX_Q * i / (MAX_POINTS - 1) for i in range(MAX_POINTS)]}
    ).with_columns(pl.col("q_value").cast(pl.Float64))
    frames = []
    for (run_id,), frame in pin.group_by("run_id"):
        ranked = frame.sort("xcorr", descending=True).with_columns(
            pl.col("is_decoy").cum_sum().alias("_d"),
            (~pl.col("is_decoy")).cum_sum().alias("_t"),
        )
        ranked = ranked.with_columns(
            (pl.col("_d") / pl.max_horizontal(pl.col("_t"), pl.lit(1))).alias("_fdr")
        ).with_columns(pl.col("_fdr").reverse().cum_min().reverse().alias("_q"))
        targets = ranked.filter(~pl.col("is_decoy")).select("_q", "_t", "xcorr").sort(["_q", "_t"])
        # For each grid threshold: the largest target count whose q-value passes.
        curve = grid.join_asof(
            targets, left_on="q_value", right_on="_q", strategy="backward"
        ).with_columns(
            pl.col("_t").fill_null(0).cast(pl.Int64).alias("accepted_psms"),
            pl.col("xcorr").alias("xcorr_threshold"),
            pl.lit(run_id).alias("run_id"),
        )
        frames.append(curve.select(list(EXPECTED_SCHEMA)))
    return pl.concat(frames).sort(["run_id", "q_value"])
