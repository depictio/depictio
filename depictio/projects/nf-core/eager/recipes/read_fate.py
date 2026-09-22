"""Where every sequenced read of a library ends up, as a flow of read counts.

An ancient-DNA run loses reads at four places, and each loss means something
different: trimming drops short and low-quality reads, collapsing merges two
overlapping mates into one sequence, mapping drops everything that is not the
target organism, the mapping-quality filter drops ambiguous placements and
deduplication drops PCR copies. Reading those four as separate bar charts makes
them look independent; they are not, and a flow says so.

The accounting is exact, not apportioned. AdapterRemoval's own identity holds
per lane::

    2 x total_read_pairs = retained_reads + collapsed_pairs + discarded_reads

and, summed over a library's lanes, ``retained_reads`` equals the pre-filter
flagstat total to the read (71 388 991 on COD076E1bL1 in the 2.4.5 megatest), so
the two reports chain without a fudge factor. From there the flagstat pair and
the MarkDuplicates report carry the rest::

    mapped            pre-filter flagstat mapped
    unmapped          pre-filter total minus mapped
    passed the filter post-filter flagstat total
    below the filter  mapped minus post-filter total
    duplicate         MarkDuplicates duplicates
    unique            post-filter total minus duplicates

Collapsing is a node at the trimming step rather than a step of its own on
purpose: one read of each merged pair stops existing there, and the reports
give no way to say which of the surviving sequences were collapsed and which
were not, so a collapse *stage* would have to apportion the mapped reads
between the two, which would be invention. As an outflow it is exact.

Terminal fates are carried forward to the last column so the flow ends where
the read did, rather than stopping mid-diagram.

Sources:
    lanes    the ``eager_lane_stats`` collection (lane counts, keyed to libraries)
    flagstat the ``samtools_flagstat`` collection (pre- and post-filter)
    dedup    the ``picard_markduplicates_metrics`` collection (optional)

Output schema:
    sample : Utf8             library the reads belong to
    step_sequencing : Utf8    stage 1 node: everything sequenced
    step_trimming : Utf8      stage 2: retained, merged on collapse, or discarded
    step_mapping : Utf8       stage 3: mapped or unmapped
    step_filtering : Utf8     stage 4: passed or below the mapping-quality filter
    step_duplication : Utf8   stage 5: unique or duplicate
    reads : Int64             reads taking that path
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

LANES_DC_TAG = "eager_lane_stats"
FLAGSTAT_DC_TAG = "samtools_flagstat"
DEDUP_DC_TAG = "picard_markduplicates_metrics"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="lanes", dc_ref=LANES_DC_TAG),
    RecipeSource(ref="flagstat", dc_ref=FLAGSTAT_DC_TAG),
    RecipeSource(ref="dedup", dc_ref=DEDUP_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "step_sequencing": pl.Utf8,
    "step_trimming": pl.Utf8,
    "step_mapping": pl.Utf8,
    "step_filtering": pl.Utf8,
    "step_duplication": pl.Utf8,
    "reads": pl.Int64,
}

STEP_COLUMNS = [
    "step_sequencing",
    "step_trimming",
    "step_mapping",
    "step_filtering",
    "step_duplication",
]

_SEQUENCED = "Sequenced"
_RETAINED = "Retained by trimming"
_MERGED = "Merged on collapse"
_DISCARDED = "Discarded by trimming"
_MAPPED = "Mapped"
_UNMAPPED = "Unmapped"
_PASSED = "Passed the quality filter"
_BELOW = "Below the quality filter"
_UNIQUE = "Unique"
_DUPLICATE = "PCR duplicate"


def _path(sample: str, labels: list[str], reads: float | int | None) -> dict | None:
    """One sankey row: a fate carried across every remaining stage."""
    if reads is None:
        return None
    count = int(reads)
    if count <= 0:
        return None
    filled = labels + [labels[-1]] * (len(STEP_COLUMNS) - len(labels))
    row: dict = {"sample": sample, "reads": count}
    row.update(dict(zip(STEP_COLUMNS, filled)))
    return row


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (library, fate path)."""
    lanes = sources["lanes"]
    flagstat = sources["flagstat"]
    dedup = sources.get("dedup")

    if lanes is None or lanes.is_empty():
        raise ValueError("eager_read_fate: the eager_lane_stats collection is empty")
    if flagstat is None or flagstat.is_empty():
        raise ValueError("eager_read_fate: the samtools_flagstat collection is empty")

    per_library = (
        lanes.filter(pl.col("sample_id").is_not_null())
        .group_by("sample_id")
        .agg(
            pl.col("total_reads").sum().alias("sequenced"),
            pl.col("retained_reads").sum().alias("retained"),
            pl.col("collapsed_pairs").sum().alias("merged"),
            pl.col("discarded_reads").sum().alias("discarded"),
        )
        .rename({"sample_id": "sample"})
    )

    stages = (
        flagstat.group_by(["sample", "stage"])
        .agg(
            pl.col("total_reads").max().alias("total_reads"),
            pl.col("mapped_reads").max().alias("mapped_reads"),
        )
        .pivot(on="stage", index="sample", values=["total_reads", "mapped_reads"])
    )

    # polars names a two-value pivot `<value>_<stage>`; a run with a single
    # stage keeps the plain names, so both spellings are looked up.
    def _column(frame: pl.DataFrame, *candidates: str) -> pl.Expr:
        for name in candidates:
            if name in frame.columns:
                return pl.col(name)
        return pl.lit(None, dtype=pl.Int64)

    stages = stages.select(
        pl.col("sample"),
        _column(stages, "mapped_reads_pre-filter", "mapped_reads").alias("mapped"),
        _column(stages, "total_reads_post-filter").alias("passed_filter"),
    )

    frame = per_library.join(stages, on="sample", how="left")

    if dedup is not None and not dedup.is_empty() and "duplicate_reads" in dedup.columns:
        duplicates = dedup.group_by("sample").agg(
            pl.col("duplicate_reads").sum().alias("duplicates")
        )
        frame = frame.join(duplicates, on="sample", how="left")
    else:
        frame = frame.with_columns(pl.lit(None, dtype=pl.Int64).alias("duplicates"))

    rows: list[dict] = []
    for record in frame.iter_rows(named=True):
        sample = record["sample"]
        retained = record["retained"] or 0
        mapped = record["mapped"] if record["mapped"] is not None else retained
        passed = record["passed_filter"] if record["passed_filter"] is not None else mapped
        duplicates = record["duplicates"]

        # No MarkDuplicates report means no duplicate outflow, and every read
        # that passed the filter is then counted as unique: `_path` drops the
        # duplicate row on its own because its count is None.
        candidates = [
            _path(sample, [_SEQUENCED, _DISCARDED], record["discarded"]),
            _path(sample, [_SEQUENCED, _MERGED], record["merged"]),
            _path(sample, [_SEQUENCED, _RETAINED, _UNMAPPED], retained - mapped),
            _path(sample, [_SEQUENCED, _RETAINED, _MAPPED, _BELOW], mapped - passed),
            _path(
                sample,
                [_SEQUENCED, _RETAINED, _MAPPED, _PASSED, _UNIQUE],
                passed - (duplicates or 0),
            ),
            _path(sample, [_SEQUENCED, _RETAINED, _MAPPED, _PASSED, _DUPLICATE], duplicates),
        ]
        rows.extend(row for row in candidates if row is not None)

    if not rows:
        raise ValueError("eager_read_fate: no library produced a single non-empty fate")

    return pl.DataFrame(rows, schema=EXPECTED_SCHEMA).sort(["sample", *STEP_COLUMNS])
