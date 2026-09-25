"""Per-sample expression distributions from the variance-stabilised matrix.

This is the exploratory panel shinyngs opens with, and the one reading a PCA
cannot replace: a PCA says which libraries differ, a distribution says whether a
library is shaped like the others at all. A sample whose density is shifted, or
whose upper tail is short, is normalised differently from its neighbours, and
every downstream contrast inherits that.

The matrix is features by samples and large (13 MB, around 20000 rows by a few
dozen columns), so nothing about it is published row by row. Each sample is
reduced to two things:

* a **density curve** over a shared grid of expression bins, so the curves of
  every sample are directly comparable and stack into one plot; and
* the **five-number summary** of that sample, repeated on each of its rows, so a
  card can draw the spread across samples without a second collection.

The grid is shared on purpose. Binning each sample against its own range would
draw every library the same shape and hide exactly the difference the panel is
for. Bin centres are the x axis, and the density is a share of the sample's own
features, so libraries of different depth stay comparable.

Zeros are dropped before the grid is built. A variance-stabilised matrix carries
a large spike at its floor for the features that are not expressed, and that
spike is tall enough to flatten everything else; the share of features at the
floor is published as ``floor_share`` instead, which is the number that spike
actually carries.

Output (one row per sample and bin):
    sample_id : Utf8      sample, the series of the density plot
    bin_centre : Float64  expression value at the middle of the bin
    density : Float64     share of the sample's expressed features in the bin
    group : Utf8          the sheet's most factor-like column, for colouring
    q1, median, q3 : Float64      the sample's quartiles, repeated on every row
    p05, p95 : Float64            the sample's 5th and 95th percentiles
    floor_share : Float64         share of features at or below the matrix floor
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="vst",
        glob_pattern="**/all.vst.tsv",
        format="tsv",
        read_kwargs={"null_values": ["NA"], "infer_schema_length": 10000},
    ),
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.tsv",
        format="tsv",
        optional=True,
        read_kwargs={"infer_schema_length": 10000},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "bin_centre": pl.Float64,
    "density": pl.Float64,
    "group": pl.Utf8,
    "q1": pl.Float64,
    "median": pl.Float64,
    "q3": pl.Float64,
    "p05": pl.Float64,
    "p95": pl.Float64,
    "floor_share": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

N_BINS = 60
MAX_LEVELS = 12


def _numeric_columns(df: pl.DataFrame) -> list[str]:
    return [c for c, dtype in df.schema.items() if dtype.is_numeric()]


def _group_map(sheet: pl.DataFrame | None, samples: list[str]) -> dict[str, str]:
    """The sheet's most factor-like column, keyed by sample, or a constant."""
    if sheet is None or sheet.is_empty():
        return {}
    wanted = set(samples)
    id_col, hits = None, -1
    for col in sheet.columns:
        overlap = len(wanted & set(sheet.get_column(col).cast(pl.Utf8).to_list()))
        if overlap > hits:
            id_col, hits = col, overlap
    if id_col is None or hits <= 0:
        return {}
    best, best_levels = None, None
    for col in sheet.columns:
        if col == id_col:
            continue
        levels = sheet.get_column(col).cast(pl.Utf8).n_unique()
        if not 2 <= levels <= min(MAX_LEVELS, max(2, sheet.height - 1)):
            continue
        if best_levels is None or levels < best_levels:
            best, best_levels = col, levels
    if best is None:
        return {}
    ids = sheet.get_column(id_col).cast(pl.Utf8).to_list()
    values = sheet.get_column(best).cast(pl.Utf8).to_list()
    return dict(zip(ids, values, strict=True))


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Reduce each sample column to a density curve on a shared grid."""
    matrix = sources["vst"]
    sheet = sources.get("samplesheet")
    samples = _numeric_columns(matrix)
    if not samples:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)

    groups = _group_map(sheet, samples)

    # The floor of a variance-stabilised matrix is the value the unexpressed
    # features collapse onto, so it is the minimum over the whole matrix rather
    # than a per-sample one.
    floor = min(v for v in (matrix.get_column(c).min() for c in samples) if v is not None)
    expressed = matrix.select(
        [pl.when(pl.col(c) > floor).then(pl.col(c)).alias(c) for c in samples]
    )
    low = min(v for v in (expressed.get_column(c).min() for c in samples) if v is not None)
    high = max(v for v in (expressed.get_column(c).max() for c in samples) if v is not None)
    if not high > low:
        high = low + 1.0
    width = (high - low) / N_BINS
    centres = [low + width * (i + 0.5) for i in range(N_BINS)]

    # One long (sample, value) frame over the expressed features, so the bin
    # counts and the quantiles run as grouped expressions rather than a Python
    # loop over every value.
    values = expressed.unpivot(samples, variable_name="sample_id", value_name="value").drop_nulls(
        "value"
    )
    if values.is_empty():
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    per_sample = values.group_by("sample_id").agg(
        pl.len().alias("total"),
        pl.col("value").quantile(0.25).alias("q1"),
        pl.col("value").quantile(0.5).alias("median"),
        pl.col("value").quantile(0.75).alias("q3"),
        pl.col("value").quantile(0.05).alias("p05"),
        pl.col("value").quantile(0.95).alias("p95"),
    )
    counts = (
        values.select(
            "sample_id",
            ((pl.col("value") - low) / width)
            .floor()
            .cast(pl.Int64)
            .clip(0, N_BINS - 1)
            .alias("bin"),
        )
        .group_by(["sample_id", "bin"])
        .len(name="count")
    )
    grid = per_sample.select("sample_id").join(
        pl.DataFrame({"bin": list(range(N_BINS)), "bin_centre": [float(c) for c in centres]}),
        how="cross",
    )
    labels = pl.DataFrame(
        {
            "sample_id": samples,
            "group": [groups.get(sample, "all samples") for sample in samples],
            "floor_share": [
                float(matrix.get_column(sample).le(floor).sum()) / max(matrix.height, 1)
                for sample in samples
            ],
        }
    )
    return (
        grid.join(counts, on=["sample_id", "bin"], how="left")
        .join(per_sample, on="sample_id", how="left")
        .join(labels, on="sample_id", how="left")
        .with_columns((pl.col("count").fill_null(0) / pl.col("total")).alias("density"))
        .select([pl.col(name).cast(dtype) for name, dtype in EXPECTED_SCHEMA.items()])
        .sort(["sample_id", "bin_centre"])
    )
