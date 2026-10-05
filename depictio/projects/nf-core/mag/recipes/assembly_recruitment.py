"""Cross-sample read recruitment: one row per assembly, one column per read sample.

nf-core/mag maps every sample's reads back onto every assembly, which is what
differential-coverage binning feeds on. The canonical figure of that signal is a
bin by sample depth heatmap, and nf-core/mag builds it from
`GenomeBinning/depths/bins/bin_depths_summary.tsv`. The 5.5.0 megatest does not
publish that table, nor the bins' FASTA that would map contigs to bins, so the
bin rows cannot be rebuilt honestly. What the run does publish is the per-contig
depth of every sample on every assembly, and summing it per assembly gives the
level above: how much of each sample's community each assembly recruits.

For each assembly and read sample the value is the length-weighted mean depth
over the assembly's contigs of at least 1 kbp (the rows `mag/contig_depths.py`
keeps), which is the assembly's average coverage by that sample's reads. A
bright diagonal is a cohort whose samples carry different organisms; a bright
row is an assembly built from a sample whose organisms every other sample also
carries, which is when a co-assembly would have paid off.

Input: the ``contig_depths`` data collection (long, one row per contig and read
sample).

Output schema (the read-sample columns are added per run, one Float64 column
named after each sample whose reads were mapped back, e.g. ``CAPES_S11``):
    assembly_id : Utf8     <assembler>-<sample>
    assembler : Utf8       assembler that built it
    sample : Utf8          sample the assembly was built from

No other numeric column is emitted, so the heatmap reads every numeric column
as a read sample without naming them.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

DEPTHS_DC_TAG = "contig_depths"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="depths", dc_ref=DEPTHS_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "assembly_id": pl.Utf8,
    "assembler": pl.Utf8,
    "sample": pl.Utf8,
}

_REQUIRED = (
    "assembly_id",
    "assembler",
    "sample",
    "contig_length",
    "read_sample",
    "depth",
)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Length-weighted mean depth per assembly and read sample, pivoted wide."""
    depths = sources["depths"]
    if depths.is_empty():
        raise ValueError("mag_assembly_recruitment: the contig depth collection is empty")
    missing = [column for column in _REQUIRED if column not in depths.columns]
    if missing:
        raise ValueError(f"mag_assembly_recruitment: contig_depths lacks {missing}")

    keys = ["assembly_id", "assembler", "sample"]
    weighted = (
        depths.filter(pl.col("read_sample").is_not_null() & pl.col("depth").is_not_null())
        .group_by([*keys, "read_sample"])
        .agg(
            ((pl.col("depth") * pl.col("contig_length")).sum() / pl.col("contig_length").sum())
            .cast(pl.Float64)
            .alias("mean_depth"),
        )
    )
    if weighted.is_empty():
        raise ValueError("mag_assembly_recruitment: no contig carries a read-sample depth")

    read_samples = sorted(weighted["read_sample"].unique().to_list())
    wide = weighted.pivot(on="read_sample", index=keys, values="mean_depth")
    return wide.select(*keys, *[pl.col(name).cast(pl.Float64) for name in read_samples]).sort(keys)
