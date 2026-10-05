"""TAD intervals derived from the insulation track's boundary calls.

``cooltools insulation`` calls boundaries, not domains: it flags individual
bins (``is_boundary_<window>``) whose neighbourhood is depleted of crossing
contacts. A TAD is what lies BETWEEN two consecutive boundaries, and no nf-core
Hi-C module emits that interval list (``HICEXPLORER_HICFINDTADS`` never runs in
nf-core/hic 2.x). This recipe derives it from the same file
``cooltools/insulation.py`` reads, so a dashboard can draw domains as intervals
on a genome axis and score their size distribution.

How an interval is built, per (sample, resolution, window, region):

1. keep the bins cooltools called a boundary;
2. merge runs of ADJACENT boundary bins into one boundary region, because a
   boundary at 20 kb resolution is usually two or three bins wide and each of
   them would otherwise open a spurious 20 kb domain;
3. a domain runs from the end of one boundary region to the start of the next.

The grouping key is cooltools' own ``region`` (the chromosome arm it scanned),
not the chromosome, so a domain never spans the gap between two scanned
regions. Domains are additionally scored on how much of their span is mappable:
``valid_fraction`` is the share of non-``is_bad_bin`` bins inside the interval,
and a domain below ``MIN_VALID_FRACTION`` is dropped, which is what keeps a
multi-megabase unmappable stretch from being reported as one enormous TAD.

The raw scan is the same one ``cooltools/insulation.py`` documents
(``cooltools_insulation_raw``); both recipes read it through ``dc_ref``.

Output schema:
    sample : Utf8          sample insulation was scanned for
    resolution : Int64      bin size in bp
    window : Int64          insulation window the boundaries were called at
    chrom : Utf8            chromosome
    start : Int64           domain start (end of the left boundary region)
    end : Int64             domain end (start of the right boundary region)
    size : Int64            domain length in bp
    size_kb : Float64       domain length in kb, the axis a size plot reads
    n_bins : Int64          bins the domain spans
    valid_fraction : Float64  share of those bins that are mappable
    region : Utf8           cooltools region label (chromosome arm)
    left_boundary_strength : Float64   boundary strength at the left edge
    right_boundary_strength : Float64  boundary strength at the right edge
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.cooltools import float_col

#: Same raw scan as `cooltools/insulation.py`.
RAW_DC_TAG = "cooltools_insulation_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="insulation", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "resolution": pl.Int64,
    "window": pl.Int64,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "size": pl.Int64,
    "size_kb": pl.Float64,
    "n_bins": pl.Int64,
    "valid_fraction": pl.Float64,
    "region": pl.Utf8,
    "left_boundary_strength": pl.Float64,
    "right_boundary_strength": pl.Float64,
}

#: A domain whose span is mostly unmappable is a gap, not a TAD.
MIN_VALID_FRACTION = 0.5

#: `<sample>.<resolution>_balanced_insulation.tsv`
_PATH_RE = r"([^/\\]+)\.(\d+)_balanced_insulation\.tsv$"
#: A window-suffixed boundary column, e.g. `is_boundary_300000` -> `300000`.
_WINDOW_COL_RE = r"^is_boundary_(\d+)$"


def _empty() -> pl.DataFrame:
    return pl.DataFrame(schema=EXPECTED_SCHEMA)


def _domains_for_window(bins: pl.DataFrame, window: int) -> pl.DataFrame | None:
    """Intervals between consecutive boundary regions, for one window size."""
    boundary_col = f"is_boundary_{window}"
    strength_col = f"boundary_strength_{window}"
    if boundary_col not in bins.columns or strength_col not in bins.columns:
        return None

    keys = ["sample", "resolution", "region"]
    flagged = (
        bins.with_columns(float_col(strength_col).alias("strength"))
        .filter(pl.col(boundary_col) == "True")
        .sort([*keys, "start"])
    )
    if flagged.is_empty():
        return None

    # Runs of adjacent boundary bins collapse into one boundary region: a new
    # run starts wherever this bin does not begin where the previous one ended.
    flagged = flagged.with_columns(
        (
            pl.col("start").shift(1).over(keys).is_null()
            | (pl.col("start") != pl.col("end").shift(1).over(keys))
        )
        .cum_sum()
        .alias("boundary_run")
    )
    edges = (
        flagged.group_by([*keys, "boundary_run"])
        .agg(
            pl.col("chrom").first(),
            pl.col("start").min().alias("edge_start"),
            pl.col("end").max().alias("edge_end"),
            pl.col("strength").max().alias("edge_strength"),
        )
        .sort([*keys, "edge_start"])
    )

    domains = (
        edges.with_columns(
            pl.col("edge_end").alias("start"),
            pl.col("edge_start").shift(-1).over(keys).alias("end"),
            pl.col("edge_strength").alias("left_boundary_strength"),
            pl.col("edge_strength").shift(-1).over(keys).alias("right_boundary_strength"),
        )
        .filter(pl.col("end").is_not_null() & (pl.col("end") > pl.col("start")))
        .with_columns(pl.lit(window, dtype=pl.Int64).alias("window"))
    )
    return domains if not domains.is_empty() else None


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Derive TAD intervals from the insulation track's boundary calls."""
    raw = sources["insulation"]
    if raw.is_empty():
        return _empty()

    bins = raw.with_columns(
        pl.col("source_path").str.extract(_PATH_RE, 1).alias("sample"),
        pl.col("source_path").str.extract(_PATH_RE, 2).cast(pl.Int64).alias("resolution"),
        pl.col("start").cast(pl.Int64, strict=False),
        pl.col("end").cast(pl.Int64, strict=False),
    ).filter(pl.col("sample").is_not_null())
    if bins.is_empty():
        return _empty()

    # Mappable-bin prefix sum per region: the number of good bins strictly
    # before each bin, so a domain's good-bin count is one subtraction.
    keys = ["sample", "resolution", "region"]
    mappable = (
        bins.sort([*keys, "start"])
        .with_columns((pl.col("is_bad_bin") != "True").cast(pl.Int64).alias("is_good"))
        .with_columns(
            (pl.col("is_good").cum_sum().over(keys) - pl.col("is_good")).alias("good_before")
        )
        .select([*keys, "start", "good_before"])
    )

    windows = sorted(
        int(m.group(1)) for c in raw.columns if (m := re.match(_WINDOW_COL_RE, c)) is not None
    )
    per_window = [d for w in windows if (d := _domains_for_window(bins, w)) is not None]
    if not per_window:
        return _empty()

    domains = pl.concat(per_window, how="vertical_relaxed")
    domains = (
        domains.join(mappable, on=[*keys, "start"], how="left")
        .join(
            mappable.rename({"start": "end", "good_before": "good_before_end"}),
            on=[*keys, "end"],
            how="left",
        )
        .with_columns(
            (pl.col("end") - pl.col("start")).alias("size"),
            ((pl.col("end") - pl.col("start")) / pl.col("resolution"))
            .cast(pl.Int64)
            .alias("n_bins"),
        )
        .with_columns(
            ((pl.col("end") - pl.col("start")) / 1000.0).alias("size_kb"),
            pl.when(pl.col("n_bins") > 0)
            .then((pl.col("good_before_end") - pl.col("good_before")) / pl.col("n_bins"))
            .otherwise(None)
            .cast(pl.Float64)
            .alias("valid_fraction"),
        )
    )

    # A domain whose mappability could not be measured (a region edge the
    # prefix sum has no row for) is kept: dropping it would lose the last
    # domain of every chromosome arm.
    domains = domains.filter(
        pl.col("valid_fraction").is_null() | (pl.col("valid_fraction") >= MIN_VALID_FRACTION)
    )

    return domains.select(list(EXPECTED_SCHEMA)).sort(
        ["sample", "resolution", "window", "chrom", "start"]
    )
