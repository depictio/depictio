"""P(s): contact probability against genomic distance, per chromosome and pooled.

The contact-probability curve is the single most diagnostic plot of a Hi-C
library: its slope in log-log space reports the polymer regime (a fractal
globule sits near -1, a cohesin-depleted genome flattens, a failed ligation
plateaus), and a bump at the far end is trans contamination. nf-core/hic does
not run ``cooltools expected-cis``, so the curve has to be recomputed from what
the run does publish, the ICE-balanced ``cooler dump`` triplet and its bins:
the same two raw scans ``cooler/contact_matrix.py`` documents
(``cooler_contacts_raw`` and ``cooler_bins_raw``), read through ``dc_ref``.

How the curve is built:

1. only the FINEST resolution the run dumped is kept, and only
   intra-chromosomal bin pairs;
2. every pair is assigned a separation in bins, ``bin2_id - bin1_id``;
3. the numerator at separation ``s`` is the sum of the balanced contact values
   at that separation, the denominator is the number of bin pairs that COULD
   have been observed (``n_bins(chrom) - s``) rather than the number of
   non-zero pixels in the sparse dump: dividing by the observed pixels would
   flatten the curve exactly where the matrix gets sparse;
4. separations are pooled into ``N_LOG_BINS`` log-spaced distance bins (sums on
   both sides, so a bin is a weighted mean and not a mean of ratios), which
   keeps every series well under the point budget a `profile` tile wants;
5. ``log10_slope`` is the finite-difference derivative of log10 P against log10
   s along that binned curve, the second series a reader actually looks at.

Each chromosome is one series and ``all`` is the genome-wide pooled curve,
matching the convention hicexplorer's own distance-decay table uses.

Output schema:
    sample : Utf8                  sample the matrix was dumped for
    resolution : Int64              bin size in bp (the finest present)
    chrom : Utf8                    chromosome, or "all" for the pooled curve
    distance : Int64                centre of the log-spaced distance bin, bp
    contact_probability : Float64   balanced contacts per possible bin pair
    log10_slope : Float64           d log10 P / d log10 s (null on the first point)
    observed : Float64              summed balanced contact value in the bin
    n_possible : Int64              bin pairs that could have been observed
"""

from __future__ import annotations

import math

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Same two raw scans as `cooler/contact_matrix.py`.
CONTACTS_DC_TAG = "cooler_contacts_raw"
BINS_DC_TAG = "cooler_bins_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="contacts", dc_ref=CONTACTS_DC_TAG),
    RecipeSource(ref="bins", dc_ref=BINS_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "resolution": pl.Int64,
    "chrom": pl.Utf8,
    "distance": pl.Int64,
    "contact_probability": pl.Float64,
    "log10_slope": pl.Float64,
    "observed": pl.Float64,
    "n_possible": pl.Int64,
}

#: Log-spaced distance bins per curve. 40 keeps every series far below the
#: ~200-point budget a `profile` tile wants while still resolving the knee.
N_LOG_BINS = 40

#: Label of the genome-wide pooled curve, hicexplorer's own convention.
POOLED = "all"

_CONTACTS_RE = r"([^/\\]+)\.(\d+)_balanced\.txt$"
_BINS_RE = r"cooler_bins_(\d+)\.bed$"


def _empty() -> pl.DataFrame:
    return pl.DataFrame(schema=EXPECTED_SCHEMA)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Recompute P(s) and its log-log slope from the balanced contact dump."""
    contacts = sources["contacts"]
    bins = sources["bins"]
    if contacts.is_empty() or bins.is_empty():
        return _empty()

    contacts = contacts.with_columns(
        pl.col("source_path").str.extract(_CONTACTS_RE, 1).alias("sample"),
        pl.col("source_path").str.extract(_CONTACTS_RE, 2).cast(pl.Int64).alias("resolution"),
        pl.col("bin1_id").cast(pl.Int64),
        pl.col("bin2_id").cast(pl.Int64),
        pl.col("count").cast(pl.Float64),
    ).filter(pl.col("sample").is_not_null())
    if contacts.is_empty():
        return _empty()

    finest = contacts["resolution"].min()
    contacts = contacts.filter(pl.col("resolution") == finest)

    bins = (
        bins.with_columns(
            pl.col("source_path").str.extract(_BINS_RE, 1).cast(pl.Int64).alias("resolution")
        )
        .filter(pl.col("resolution") == finest)
        .with_columns(pl.int_range(pl.len()).over("source_path").alias("bin_id"))
        .select(["bin_id", "chrom"])
    )
    if bins.is_empty():
        return _empty()

    # Observed: summed balanced value per (sample, chromosome, separation).
    observed = (
        contacts.join(bins.rename({"chrom": "chrom1"}), left_on="bin1_id", right_on="bin_id")
        .join(bins.rename({"chrom": "chrom2"}), left_on="bin2_id", right_on="bin_id")
        .filter(pl.col("chrom1") == pl.col("chrom2"))
        .with_columns((pl.col("bin2_id") - pl.col("bin1_id")).abs().alias("separation"))
        .group_by(["sample", "chrom1", "separation"])
        .agg(pl.col("count").sum().alias("observed"))
        .rename({"chrom1": "chrom"})
    )
    if observed.is_empty():
        return _empty()

    # Possible: every separation a chromosome can hold, whether or not the
    # sparse dump wrote a pixel for it.
    n_bins = bins.group_by("chrom").len().rename({"len": "n_bins"})
    possible = (
        n_bins.with_columns(pl.int_ranges(1, pl.col("n_bins")).alias("separation"))
        .explode("separation")
        .drop_nulls("separation")
        .with_columns(
            pl.col("separation").cast(pl.Int64),
            (pl.col("n_bins") - pl.col("separation")).cast(pl.Int64).alias("n_possible"),
        )
        .select(["chrom", "separation", "n_possible"])
    )
    samples = observed.select("sample").unique()
    curve = (
        possible.join(samples, how="cross")
        .join(observed, on=["sample", "chrom", "separation"], how="left")
        .with_columns(pl.col("observed").fill_null(0.0))
    )

    pooled = (
        curve.group_by(["sample", "separation"])
        .agg(pl.col("observed").sum(), pl.col("n_possible").sum())
        .with_columns(pl.lit(POOLED, dtype=pl.Utf8).alias("chrom"))
    )
    columns = ["sample", "chrom", "separation", "observed", "n_possible"]
    curve = pl.concat([curve.select(columns), pooled.select(columns)]).with_columns(
        (pl.col("separation") * finest).cast(pl.Int64).alias("distance")
    )

    # Log-spaced binning. The edges are shared by every series so the slope of
    # one chromosome is comparable with the slope of another.
    low = math.log10(float(finest))
    high = math.log10(float(curve["distance"].max()))
    span = max(high - low, 1e-9)
    curve = curve.with_columns(
        (((pl.col("distance").cast(pl.Float64).log10() - low) / span * N_LOG_BINS).floor())
        .clip(0, N_LOG_BINS - 1)
        .cast(pl.Int64)
        .alias("log_bin")
    )

    binned = (
        curve.group_by(["sample", "chrom", "log_bin"])
        .agg(
            pl.col("observed").sum(),
            pl.col("n_possible").sum(),
            pl.col("distance").min().alias("distance_min"),
            pl.col("distance").max().alias("distance_max"),
        )
        .filter((pl.col("n_possible") > 0) & (pl.col("observed") > 0))
        .with_columns(
            (pl.col("observed") / pl.col("n_possible")).alias("contact_probability"),
            # Geometric centre of the bin: the natural x on a log axis.
            (
                10
                ** (
                    (
                        pl.col("distance_min").cast(pl.Float64).log10()
                        + pl.col("distance_max").cast(pl.Float64).log10()
                    )
                    / 2
                )
            )
            .round()
            .cast(pl.Int64)
            .alias("distance"),
        )
        .sort(["sample", "chrom", "distance"])
    )
    if binned.is_empty():
        return _empty()

    binned = binned.with_columns(
        (
            pl.col("contact_probability").log10().diff().over(["sample", "chrom"])
            / pl.col("distance").cast(pl.Float64).log10().diff().over(["sample", "chrom"])
        ).alias("log10_slope"),
        pl.lit(finest, dtype=pl.Int64).alias("resolution"),
    )

    return binned.select(list(EXPECTED_SCHEMA)).sort(["sample", "chrom", "distance"])
