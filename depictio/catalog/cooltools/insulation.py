"""TAD insulation score and boundary calls, one row per genomic bin per window.

``cooltools insulation`` writes ``<sample>.<resolution>_balanced_insulation.tsv``:
one row per bin, with the insulation score, its pixel support, the boundary
strength and the boundary call repeated for every window size cooltools was
asked to scan (here 300 kb, 500 kb and 1 Mb; the column suffix carries the
window). This recipe reshapes those three parallel column groups into one row
per bin per window, which is what lets a dashboard filter on window size
instead of hard-coding one.

A low insulation score marks a bin whose neighbourhood is depleted of contacts
crossing it, a TAD boundary; ``is_boundary_<window>`` is cooltools' own
threshold call on that score's local minima. Unmappable bins carry ``nan``
scores rather than empty fields, which is why the numeric columns are read as
text and cast with the literal string ``"nan"`` mapped to null first.

A run that scans several resolutions writes one file per resolution, and
cooltools names the window columns after the window size in bp, not after a
fixed "small/medium/large" label, so two files scanned at different
resolutions can carry entirely disjoint window suffixes (the megatest's 20 kb
file has windows 300 kb/500 kb/1 Mb, its 40 kb file has 600 kb/1 Mb/2 Mb).
Depictio's scan step unions every matched file's columns and null-fills what a
given file lacks (``align_lazy_schemas`` in
``depictio/cli/cli/utils/deltatables.py``), so the raw DC ends up with the
union of every window suffix across every file; this recipe discovers the
window sizes actually present from the column names rather than assuming a
fixed set, so a row's ``window`` group is null (not a fabricated 0) on the file
that never scanned it.

The file has a header but no sample column, so it is read through a **scan**
data collection whose `include_file_paths` carries the file path into the
frame, and the recipe reads it through `dc_ref`::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '.*_balanced_insulation\\.tsv$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\t"
          include_file_paths: source_path
          infer_schema_length: 0

Output schema:
    sample : Utf8               sample insulation was scanned for
    resolution : Int64           bin size in bp
    chrom : Utf8                 chromosome
    start : Int64                  bin start
    end : Int64                    bin end
    region : Utf8                cooltools region label (chromosome arm)
    is_bad_bin : Boolean         true for a masked / unmappable bin
    window : Int64                insulation window size in bp
    log2_insulation_score : Float64   log2 insulation score at this window (null if masked)
    n_valid_pixels : Float64     valid pixels behind the score at this window
    boundary_strength : Float64  cooltools' boundary-strength statistic at this window
    is_boundary : Boolean        cooltools' own boundary call at this window (null if masked)
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.cooltools import float_col

#: Data-collection tag the recipe reads. A template reusing this recipe must
#: scan the per-sample insulation files into a DC with this tag (see module docstring).
RAW_DC_TAG = "cooltools_insulation_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="insulation", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "resolution": pl.Int64,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "region": pl.Utf8,
    "is_bad_bin": pl.Boolean,
    "window": pl.Int64,
    "log2_insulation_score": pl.Float64,
    "n_valid_pixels": pl.Float64,
    "boundary_strength": pl.Float64,
    "is_boundary": pl.Boolean,
}

#: `<sample>.<resolution>_balanced_insulation.tsv`
_PATH_RE = r"([^/\\]+)\.(\d+)_balanced_insulation\.tsv$"

#: A window-suffixed column, e.g. `log2_insulation_score_300000` -> `300000`.
_WINDOW_COL_RE = r"^log2_insulation_score_(\d+)$"


def _bool_col(name: str) -> pl.Expr:
    """A "True"/"False"/"nan" text column as a nullable Boolean."""
    return (
        pl.when(pl.col(name) == "True")
        .then(True)
        .when(pl.col(name) == "False")
        .then(False)
        .otherwise(None)
        .alias(name)
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Unpivot the per-window column groups into one row per bin per window."""
    df = sources["insulation"]
    df = df.with_columns(
        pl.col("source_path").str.extract(_PATH_RE, 1).alias("sample"),
        pl.col("source_path").str.extract(_PATH_RE, 2).cast(pl.Int64).alias("resolution"),
        pl.col("start").cast(pl.Int64, strict=False),
        pl.col("end").cast(pl.Int64, strict=False),
        _bool_col("is_bad_bin"),
    )

    # Window sizes actually present, discovered from the column names rather
    # than assumed: depictio's scan unions every matched file's columns, so a
    # window only one of several insulation files computed still shows up here
    # (null-filled on the files that lack it).
    windows = sorted(
        int(m.group(1)) for c in df.columns if (m := re.match(_WINDOW_COL_RE, c)) is not None
    )

    id_cols = ["sample", "resolution", "chrom", "start", "end", "region", "is_bad_bin"]
    per_window: list[pl.DataFrame] = []
    for window in windows:
        score_col = f"log2_insulation_score_{window}"
        pixels_col = f"n_valid_pixels_{window}"
        strength_col = f"boundary_strength_{window}"
        boundary_col = f"is_boundary_{window}"
        if not all(c in df.columns for c in (score_col, pixels_col, strength_col, boundary_col)):
            continue  # union is missing a sibling column for this window; skip rather than fabricate it
        chunk = df.select(
            *id_cols,
            pl.lit(window).cast(pl.Int64).alias("window"),
            float_col(score_col).alias("log2_insulation_score"),
            float_col(pixels_col).alias("n_valid_pixels"),
            float_col(strength_col).alias("boundary_strength"),
            _bool_col(boundary_col).alias("is_boundary"),
        )
        # A file that never scanned this window size still supplies rows after
        # the ingest-time column union (null-filled). `n_valid_pixels` is a
        # real 0.0 (not null) even on a masked bin for a window that WAS
        # computed, so "null" here means "this file lacks the window", not
        # "this bin is masked" -- drop only that case.
        chunk = chunk.filter(pl.col("n_valid_pixels").is_not_null())
        per_window.append(chunk)

    if not per_window:
        return df.select(
            [
                pl.lit(None, dtype=t).alias(c).filter(pl.lit(False))
                for c, t in EXPECTED_SCHEMA.items()
            ]
        )

    return pl.concat(per_window).select(list(EXPECTED_SCHEMA)).sort(["chrom", "start", "window"])
