"""Library complexity curve with its confidence ribbon, one row per read depth.

``preseq lc_extrap`` writes one ``<sample>.ccurve.txt`` per library: a
tab-separated table of ``TOTAL_READS``, ``EXPECTED_DISTINCT`` and the two bounds
of the 95% confidence interval on that extrapolation. The reading is how many
*new* molecules the next million reads would buy, and how sure preseq is of it:
a curve still climbing steeply at the sequenced depth means resequencing pays,
one that has flattened means the library is exhausted, and a ribbon that fans
out means the extrapolation itself is guesswork.

Input: the ``preseq_ccurve_raw`` data collection, a recursive Table scan of the
per-sample files. The recipe reads it through ``dc_ref`` rather than a glob for
the same reason ``deseq2/results_long.py`` does: the sample id exists only in the
file NAME, the recipe glob loader concatenates matched files without a per-file
label, and only a scan carries the path. The DC must therefore be declared with::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '.*\\.ccurve\\.txt$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\t"
          include_file_paths: source_path   # carries the sample id
          infer_schema_length: 0            # every column Utf8; recast here

Why the curve is clipped and thinned
------------------------------------
``lc_extrap`` extrapolates on a 1e6 grid out to 1e10 reads by default, which is
10 001 rows per library of which the last nine thousand describe a sequencing
depth no ChIP or ATAC library will ever see. The ``profile`` kind never samples
its frame — a curve with holes is a wrong answer, not a lower-resolution one —
so the thinning has to happen here, in the recipe, rather than at read time.
Rows past ``MAX_TOTAL_READS`` are dropped and what remains is decimated to at
most ``MAX_POINTS`` evenly spaced depths per library, first and last always
kept. A run that extrapolated less far than the clip is left alone by it.

Output schema:
    sample : Utf8               library preseq ran on
    total_reads : Float64       sequencing depth the row extrapolates to
    expected_distinct : Float64 unique molecules expected at that depth
    lower_ci : Float64          lower bound of the 95% interval
    upper_ci : Float64          upper bound of the 95% interval
    ci_width : Float64          upper_ci - lower_ci, how wide the guess is
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sample_ids import strip_stage_suffixes

#: Data-collection tag the recipe reads. A template reusing this recipe must
#: scan its per-sample curves into a DC with this tag (see module docstring).
RAW_DC_TAG = "preseq_ccurve_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="curves", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "total_reads": pl.Float64,
    "expected_distinct": pl.Float64,
    "lower_ci": pl.Float64,
    "upper_ci": pl.Float64,
    "ci_width": pl.Float64,
}

# Column the scan is asked to add (polars include_file_paths).
SOURCE_PATH_COL = "source_path"

#: Deepest extrapolated depth kept, in reads. A billion is roughly twenty times
#: the deepest a ChIP or ATAC library is ever resequenced to, so everything past
#: it is a flat tail nobody reads.
MAX_TOTAL_READS = 1_000_000_000.0

#: Points kept per library after clipping.
MAX_POINTS = 200

# Canonical name -> accepted spellings, compared case-insensitively. `lc_extrap`
# names the interval columns after the level it was run at (`LOWER_0.95CI`), and
# a non-default `-c` changes the number, so the bounds are matched on the
# LOWER_/UPPER_ prefix rather than on the whole name.
_ALIASES: dict[str, tuple[str, ...]] = {
    "total_reads": ("total_reads", "totalreads", "total_bases"),
    "expected_distinct": ("expected_distinct", "distinct_reads", "expecteddistinct"),
}


def _norm(name: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", name.strip().lower()).strip("_")


def _resolve_columns(columns: list[str]) -> dict[str, str]:
    """Map the four preseq columns onto the ones actually present."""
    normalised = {_norm(c): c for c in columns}
    found: dict[str, str] = {}
    for canonical, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in normalised:
                found[canonical] = normalised[alias]
                break
    for norm_name, original in normalised.items():
        if norm_name.startswith("lower") and "lower_ci" not in found:
            found["lower_ci"] = original
        elif norm_name.startswith("upper") and "upper_ci" not in found:
            found["upper_ci"] = original
    missing = {"total_reads", "expected_distinct"} - set(found)
    if missing:
        raise ValueError(
            f"preseq_complexity_curve: no column matched {sorted(missing)}; got {columns}"
        )
    return found


def _thin(frame: pl.DataFrame) -> pl.DataFrame:
    """Clip the extrapolated tail, then keep at most MAX_POINTS depths."""
    clipped = frame.filter(pl.col("total_reads") <= MAX_TOTAL_READS)
    # A run whose whole grid sits past the clip would otherwise vanish; keep it
    # rather than silently dropping the library from the plot.
    if clipped.is_empty():
        clipped = frame
    height = clipped.height
    if height <= MAX_POINTS:
        return clipped
    step = -(-height // MAX_POINTS)  # ceil, so the result never exceeds MAX_POINTS
    return clipped.gather_every(step).vstack(clipped.tail(1)).unique(subset=["total_reads"])


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Label every curve with its library, thin it, and stack the libraries."""
    raw = sources["curves"]
    if raw.is_empty():
        raise ValueError("preseq_complexity_curve: the scanned curves are empty")

    columns = _resolve_columns(raw.columns)
    if SOURCE_PATH_COL in raw.columns:
        sample = pl.col(SOURCE_PATH_COL).map_elements(strip_stage_suffixes, return_dtype=pl.Utf8)
    else:
        # No path column: the scan was declared without `include_file_paths`, so
        # every row belongs to one unnamed library rather than to a wrong one.
        sample = pl.lit("all", dtype=pl.Utf8)

    numeric = {
        canonical: pl.col(original).cast(pl.Float64, strict=False)
        for canonical, original in columns.items()
    }
    frame = raw.select(
        sample.alias("sample"),
        numeric["total_reads"].alias("total_reads"),
        numeric["expected_distinct"].alias("expected_distinct"),
        numeric.get("lower_ci", pl.lit(None, dtype=pl.Float64)).alias("lower_ci"),
        numeric.get("upper_ci", pl.lit(None, dtype=pl.Float64)).alias("upper_ci"),
    ).drop_nulls(["total_reads", "expected_distinct"])

    if frame.is_empty():
        raise ValueError("preseq_complexity_curve: no row carried a depth and a distinct count")

    thinned = pl.concat(
        [_thin(part.sort("total_reads")) for (_,), part in frame.group_by(["sample"])],
        how="vertical",
    )
    return (
        thinned.with_columns((pl.col("upper_ci") - pl.col("lower_ci")).alias("ci_width"))
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "total_reads"])
    )
