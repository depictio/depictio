"""Read length distribution per library, from miRTrace via MultiQC.

The length profile is the quickest check that a small RNA library is what it
claims to be: mature miRNAs are 20 to 24 nt, so a good library peaks there. A
second peak around 30 to 33 nt is usually piRNA or tRNA fragments, a broad
smear to longer lengths degraded RNA, and a pile-up below 18 nt adapter dimers
or over-trimming. Lengths are shown as a percentage of the library so libraries
of different depth overlay.

Each length also carries the band miRTrace colours it with, as ``length_class``.

Source: the run's ``multiqc_data/multiqc.parquet`` (plot ``mirtrace_length_plot``).

Output schema:
    sample : Utf8
    length : Int64         read length, nt
    reads : Float64        reads of that length
    percent : Float64      of the library's reads, %
    length_class : Utf8    under 18 nt | 18 to 26 nt (miRNA) | 26 to 40 nt | 40 nt and over
"""

from __future__ import annotations

import json

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="report",
        glob_pattern="**/*_data/multiqc.parquet",
        format="parquet",
        read_kwargs={"columns": ["anchor", "type", "plot_input_data"]},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "length": pl.Int64,
    "reads": pl.Float64,
    "percent": pl.Float64,
    "length_class": pl.Utf8,
}

ANCHOR = "mirtrace_length_plot"


def series(report: pl.DataFrame, anchor: str) -> list[dict]:
    """The line plot's series (``{"name", "pairs"}``) of its first dataset."""
    rows = report.filter((pl.col("anchor") == anchor) & (pl.col("type") == "plot_input"))
    if rows.is_empty() or rows["plot_input_data"][0] is None:
        return []
    data = json.loads(rows["plot_input_data"][0]).get("data") or []
    return data[0] if data else []


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (sample, length)."""
    records = [
        {"sample": str(s["name"]), "length": int(x), "reads": float(y)}
        for s in series(sources["report"], ANCHOR)
        for x, y in s.get("pairs") or []
        if isinstance(x, (int, float)) and isinstance(y, (int, float))
    ]
    if not records:
        raise ValueError("mirtrace_length_distribution: no miRTrace length plot in the report")
    frame = pl.DataFrame(
        records, schema={"sample": pl.Utf8, "length": pl.Int64, "reads": pl.Float64}
    )
    frame = frame.with_columns(
        (pl.col("reads") * 100.0 / pl.col("reads").sum().over("sample"))
        .fill_nan(None)
        .alias("percent"),
        pl.when(pl.col("length") < 18)
        .then(pl.lit("under 18 nt"))
        .when(pl.col("length") < 26)
        .then(pl.lit("18 to 26 nt (miRNA)"))
        .when(pl.col("length") < 40)
        .then(pl.lit("26 to 40 nt"))
        .otherwise(pl.lit("40 nt and over"))
        .alias("length_class"),
    )
    return frame.select(list(EXPECTED_SCHEMA)).sort(["sample", "length"])
