"""The HiC-Pro valid-pair funnel, one wide row per sample.

HiC-Pro writes its own statistics as a handful of headerless key/value files
under ``stats/<sample>/``, one per processing stage:

``<sample>.R1.mmapstat`` / ``<sample>.R2.mmapstat``
    reads mapped per mate, split into the full-length (``global``) and the
    trimmed two-step (``local``) pass.
``<sample>.mpairstat``
    read pairs processed, and where they are lost: unmapped, low mapping
    quality, one mate only. A third column repeats the count as a percentage.
``<sample>.mRSstat``
    the restriction-fragment filter: valid 3C products against dangling ends,
    re-ligations, self circles and pairs dumped for other reasons.
``<sample>_allValidPairs.mergestat``
    what survives de-duplication, split into cis and trans, and cis into short
    and long range.

Those numbers reach a MultiQC report through HiC-Pro's own MultiQC module, but
a MultiQC panel is an image: nothing on a dashboard can filter it, put it in a
card or join it to another collection. This recipe reads the same files
directly and pivots them into ONE ROW PER SAMPLE, so the funnel becomes an
`attrition` card, the rates become gauges and the whole thing becomes a table.

The files differ in width (``mpairstat`` has a percentage column the others do
not), so they are read through a single **scan** data collection with
``has_header: false`` and NO ``new_columns``: polars names the fields
``column_1``/``column_2``/``column_3`` and depictio's own schema union
null-fills the third on the two-column files::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config:
             {pattern: '.*\\.(mmapstat|mpairstat|mRSstat|mergestat)$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\t"
          has_header: false
          include_file_paths: source_path
          infer_schema_length: 0

The sample name is recovered from the FILE NAME rather than from the
``stats/<sample>/`` directory, so the recipe survives a run that publishes the
five files flat: the stem is stripped of the ``.R1`` / ``.R2`` mate suffix and
of ``_allValidPairs``.

Output schema (counts are Int64, rates are fractions in 0..1):
    sample : Utf8                sample the funnel belongs to
    total_pairs : Int64          read pairs HiC-Pro processed
    unmapped_pairs : Int64       pairs with neither mate mapped
    low_qual_pairs : Int64       pairs dropped on mapping quality
    singleton_pairs : Int64      pairs with one mate mapped only
    reported_pairs : Int64       uniquely paired alignments reaching the RS filter
    valid_pairs : Int64          valid 3C products
    dangling_end_pairs : Int64   un-ligated fragment ends
    religation_pairs : Int64     re-ligations of adjacent fragments
    self_circle_pairs : Int64    self-circularised fragments
    dumped_pairs : Int64         pairs dropped for any other reason
    valid_pairs_rmdup : Int64    valid pairs left after de-duplication
    cis_pairs : Int64            intra-chromosomal contacts
    trans_pairs : Int64          inter-chromosomal contacts
    cis_short_range : Int64      cis contacts below HiC-Pro's range cut-off
    cis_long_range : Int64       cis contacts above it
    total_reads : Int64          reads per mate entering mapping
    mapped_r1 / mapped_r2 : Int64        reads mapped per mate
    trimmed_r1 / trimmed_r2 : Int64      reads rescued by the two-step pass
    mapping_rate_r1 / mapping_rate_r2 : Float64
    low_qual_rate : Float64      low-quality pairs over pairs processed
    valid_pair_rate : Float64    valid pairs over pairs processed
    duplicate_rate : Float64     duplicates over valid pairs
    cis_ratio / trans_ratio : Float64    share of the de-duplicated contacts
    long_range_ratio : Float64   long-range share of the cis contacts
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the recipe reads. A template reusing this recipe must
#: scan HiC-Pro's `stats/` key/value files into a DC with this tag.
RAW_DC_TAG = "hicpro_stats_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="stats", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "total_pairs": pl.Int64,
    "unmapped_pairs": pl.Int64,
    "low_qual_pairs": pl.Int64,
    "singleton_pairs": pl.Int64,
    "reported_pairs": pl.Int64,
    "valid_pairs": pl.Int64,
    "dangling_end_pairs": pl.Int64,
    "religation_pairs": pl.Int64,
    "self_circle_pairs": pl.Int64,
    "dumped_pairs": pl.Int64,
    "valid_pairs_rmdup": pl.Int64,
    "cis_pairs": pl.Int64,
    "trans_pairs": pl.Int64,
    "cis_short_range": pl.Int64,
    "cis_long_range": pl.Int64,
    "total_reads": pl.Int64,
    "mapped_r1": pl.Int64,
    "mapped_r2": pl.Int64,
    "trimmed_r1": pl.Int64,
    "trimmed_r2": pl.Int64,
    "mapping_rate_r1": pl.Float64,
    "mapping_rate_r2": pl.Float64,
    "low_qual_rate": pl.Float64,
    "valid_pair_rate": pl.Float64,
    "duplicate_rate": pl.Float64,
    "cis_ratio": pl.Float64,
    "trans_ratio": pl.Float64,
    "long_range_ratio": pl.Float64,
}

#: `<stem>.<one of the four stat extensions>` -> the stem.
_STEM_RE = r"([^/\\]+)\.(?:mmapstat|mpairstat|mRSstat|mergestat)$"
#: Mate and merge suffixes a stem may carry before the sample name is left.
_SAMPLE_SUFFIX_RE = r"(?:_allValidPairs|[._]R[12])$"

#: HiC-Pro metric name -> output column. Names are case-sensitive and differ
#: between files on purpose (`Valid_interaction_pairs` in mRSstat is the same
#: number as `valid_interaction` in mergestat), so nothing collides.
_COUNTS: dict[str, str] = {
    "Total_pairs_processed": "total_pairs",
    "Unmapped_pairs": "unmapped_pairs",
    "Low_qual_pairs": "low_qual_pairs",
    "Pairs_with_singleton": "singleton_pairs",
    "Reported_pairs": "reported_pairs",
    "Valid_interaction_pairs": "valid_pairs",
    "Dangling_end_pairs": "dangling_end_pairs",
    "Religation_pairs": "religation_pairs",
    "Self_Cycle_pairs": "self_circle_pairs",
    "Dumped_pairs": "dumped_pairs",
    "valid_interaction_rmdup": "valid_pairs_rmdup",
    "cis_interaction": "cis_pairs",
    "trans_interaction": "trans_pairs",
    "cis_shortRange": "cis_short_range",
    "cis_longRange": "cis_long_range",
    "total_R1": "total_reads",
    "mapped_R1": "mapped_r1",
    "mapped_R2": "mapped_r2",
    "local_R1": "trimmed_r1",
    "local_R2": "trimmed_r2",
}


def _count(available: set[str], column: str) -> pl.Expr:
    """A pivoted metric column, or a null Int64 when the run never wrote it."""
    if column in available:
        return pl.col(column).cast(pl.Int64).alias(column)
    return pl.lit(None, dtype=pl.Int64).alias(column)


def _ratio(numerator: str, denominator: str, name: str) -> pl.Expr:
    """`numerator / denominator` as a fraction, null when the denominator is 0 or absent."""
    return (
        pl.when(pl.col(denominator).fill_null(0) > 0)
        .then(pl.col(numerator) / pl.col(denominator))
        .otherwise(None)
        .cast(pl.Float64)
        .alias(name)
    )


def _empty() -> pl.DataFrame:
    return pl.DataFrame(schema=EXPECTED_SCHEMA)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Pivot HiC-Pro's key/value stat files into one funnel row per sample."""
    raw = sources["stats"]
    if raw.is_empty() or "column_1" not in raw.columns:
        return _empty()

    tidy = raw.select(
        pl.col("source_path")
        .str.extract(_STEM_RE, 1)
        .str.replace(_SAMPLE_SUFFIX_RE, "")
        .alias("sample"),
        pl.col("column_1").str.strip_chars().alias("metric"),
        pl.col("column_2").str.strip_chars().cast(pl.Float64, strict=False).alias("value"),
    ).filter(pl.col("sample").is_not_null() & pl.col("metric").is_in(list(_COUNTS)))
    if tidy.is_empty():
        return _empty()

    tidy = tidy.with_columns(pl.col("metric").replace_strict(_COUNTS, default=None))
    wide = tidy.pivot(on="metric", index="sample", values="value", aggregate_function="max")

    available = set(wide.columns)
    wide = wide.select(
        pl.col("sample"),
        *[_count(available, column) for column in _COUNTS.values()],
    )

    # The de-duplicated valid pairs split into cis and trans; the difference
    # between the valid pairs and that split is what de-duplication removed.
    wide = wide.with_columns(
        _ratio("mapped_r1", "total_reads", "mapping_rate_r1"),
        _ratio("mapped_r2", "total_reads", "mapping_rate_r2"),
        _ratio("low_qual_pairs", "total_pairs", "low_qual_rate"),
        _ratio("valid_pairs", "total_pairs", "valid_pair_rate"),
        _ratio("cis_pairs", "valid_pairs_rmdup", "cis_ratio"),
        _ratio("trans_pairs", "valid_pairs_rmdup", "trans_ratio"),
        _ratio("cis_long_range", "cis_pairs", "long_range_ratio"),
    ).with_columns(
        pl.when(pl.col("valid_pairs").fill_null(0) > 0)
        .then(
            (pl.col("valid_pairs") - pl.col("valid_pairs_rmdup")).clip(lower_bound=0)
            / pl.col("valid_pairs")
        )
        .otherwise(None)
        .cast(pl.Float64)
        .alias("duplicate_rate")
    )

    return wide.select(list(EXPECTED_SCHEMA)).sort("sample")
