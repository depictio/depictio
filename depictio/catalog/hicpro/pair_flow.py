"""Where a Hi-C library's read pairs end up, one weighted row per fate.

Same four HiC-Pro stat files as ``hicpro/pair_stats.py`` (see that module for
the scan the raw data collection needs), reshaped for a flow diagram instead of
a wide funnel row: one row per (sample, mapping fate, filtering fate, contact
fate) with the number of read pairs that take that path.

The three levels are HiC-Pro's three decisions, and they reconcile exactly:

``mapping``   Unmapped + Low quality + Singleton + Uniquely mapped
              = ``Total_pairs_processed``
``filtering`` Dangling end + Religation + Self circle + Dumped + Valid pairs
              = ``Reported_pairs`` (the uniquely mapped ones)
``contacts``  Cis + Trans + Duplicate = ``Valid_interaction_pairs``
              (``cis_interaction`` + ``trans_interaction`` is the DE-DUPLICATED
              total, so the remainder is what de-duplication removed)

Every path that ends before the last level carries ``"Lost"`` in the remaining
columns, the same convention `enchantr/sequence_fates.py` uses, so the Sankey
draws one terminal node per loss point instead of dropping the row.

Rows whose count is zero are dropped: a Sankey node with no flow is a label
with no ribbon, and HiC-Pro writes a 0 for every branch a run did not take
(single-end mode, no re-ligation filter).

Output schema:
    sample : Utf8      sample the library belongs to
    mapping : Utf8     Unmapped / Low quality / Singleton / Uniquely mapped
    filtering : Utf8   Dangling end / Religation / Self circle / Dumped / Valid pairs / Lost
    contacts : Utf8    Cis / Trans / Duplicate / Lost
    pairs : Int64      read pairs taking this path
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Same raw scan as `hicpro/pair_stats.py`.
RAW_DC_TAG = "hicpro_stats_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="stats", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "mapping": pl.Utf8,
    "filtering": pl.Utf8,
    "contacts": pl.Utf8,
    "pairs": pl.Int64,
}

_STEM_RE = r"([^/\\]+)\.(?:mmapstat|mpairstat|mRSstat|mergestat)$"
_SAMPLE_SUFFIX_RE = r"(?:_allValidPairs|[._]R[12])$"

_LOST = "Lost"
_MAPPED = "Uniquely mapped"
_VALID = "Valid pairs"

#: Paths that end at the mapping level: (HiC-Pro metric, mapping label).
_MAPPING_LOSSES: list[tuple[str, str]] = [
    ("Unmapped_pairs", "Unmapped"),
    ("Low_qual_pairs", "Low quality"),
    ("Pairs_with_singleton", "Singleton"),
]
#: Paths that end at the restriction-fragment filter: (metric, filtering label).
_FILTER_LOSSES: list[tuple[str, str]] = [
    ("Dangling_end_pairs", "Dangling end"),
    ("Religation_pairs", "Religation"),
    ("Self_Cycle_pairs", "Self circle"),
    ("Dumped_pairs", "Dumped"),
]
#: Paths that reach a contact: (metric, contact label). ``Duplicate`` has no
#: metric of its own and is computed as the valid-pair remainder.
_CONTACT_FATES: list[tuple[str, str]] = [
    ("cis_interaction", "Cis"),
    ("trans_interaction", "Trans"),
]

_METRICS = (
    [m for m, _ in _MAPPING_LOSSES]
    + [m for m, _ in _FILTER_LOSSES]
    + [m for m, _ in _CONTACT_FATES]
    + ["Valid_interaction_pairs"]
)


def _empty() -> pl.DataFrame:
    return pl.DataFrame(schema=EXPECTED_SCHEMA)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Turn HiC-Pro's stat files into one weighted row per read-pair fate."""
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
    ).filter(pl.col("sample").is_not_null() & pl.col("metric").is_in(_METRICS))
    if tidy.is_empty():
        return _empty()

    wide = tidy.pivot(on="metric", index="sample", values="value", aggregate_function="max")

    def metric(name: str) -> pl.Expr:
        if name in wide.columns:
            return pl.col(name).cast(pl.Int64).fill_null(0)
        return pl.lit(0, dtype=pl.Int64)

    paths: list[pl.DataFrame] = []

    def add_path(mapping: str, filtering: str, contacts: str, pairs: pl.Expr) -> None:
        paths.append(
            wide.select(
                pl.col("sample"),
                pl.lit(mapping, dtype=pl.Utf8).alias("mapping"),
                pl.lit(filtering, dtype=pl.Utf8).alias("filtering"),
                pl.lit(contacts, dtype=pl.Utf8).alias("contacts"),
                pairs.alias("pairs"),
            )
        )

    for name, label in _MAPPING_LOSSES:
        add_path(label, _LOST, _LOST, metric(name))
    for name, label in _FILTER_LOSSES:
        add_path(_MAPPED, label, _LOST, metric(name))
    for name, label in _CONTACT_FATES:
        add_path(_MAPPED, _VALID, label, metric(name))
    # Valid pairs minus what survived de-duplication. Clipped at zero: a run
    # that never de-duplicated reports the same number twice.
    duplicates = (
        metric("Valid_interaction_pairs") - metric("cis_interaction") - metric("trans_interaction")
    ).clip(lower_bound=0)
    add_path(_MAPPED, _VALID, "Duplicate", duplicates)

    return (
        pl.concat(paths)
        .filter(pl.col("pairs") > 0)
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "mapping", "filtering", "contacts"])
    )
