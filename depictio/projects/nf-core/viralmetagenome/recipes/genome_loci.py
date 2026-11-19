"""Where each genome sits in the run's reference FASTA, and its two ends, for the browser.

The genome browser opens on a locus; a viralmetagenome genome is one sequence of
the run's mapping references (see ``tracks.py``). The sequence name and length
are read off mosdepth's per-base depth (``coverage_bins``), which covers each
mapping's reference from its first base to its last. Three loci per genome:

* ``Whole genome``, the sequence end to end;
* ``5' end`` and ``3' end``, the first and last ``END_BP`` bases, where a
  consensus is least certain: the reads thin out towards a linear genome's
  ends, and a segmented virus keeps conserved termini that primer-free
  sequencing reads poorly.

Sources:
    bins     ``coverage_bins``, binned per-base depth
    genomes  ``genomes``, the genome hub, optional (virus and segment)

Output schema:
    locus_id, genome_id, sample, chrom, region : Utf8
    start, end, length : Int64      1-based, inclusive
    region_order : Int64            1 whole, 2 5' end, 3 3' end
    virus_segment : Utf8
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Bases of each genome end the end loci open on.
END_BP = 200

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="bins",
        dc_ref="coverage_bins",
        input_schema={"genome_id": pl.Utf8, "chrom": pl.Utf8, "end": pl.Int64},
    ),
    RecipeSource(
        ref="genomes",
        dc_ref="genomes",
        optional=True,
        input_schema={"genome_id": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "locus_id": pl.Utf8,
    "genome_id": pl.Utf8,
    "sample": pl.Utf8,
    "chrom": pl.Utf8,
    "region": pl.Utf8,
    "region_order": pl.Int64,
    "start": pl.Int64,
    "end": pl.Int64,
    "length": pl.Int64,
    "virus_segment": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    bins = sources["bins"]
    if "sample" not in bins.columns:
        bins = bins.with_columns(pl.lit(None, dtype=pl.Utf8).alias("sample"))
    seqs = (
        bins.filter(pl.col("genome_id").is_not_null() & pl.col("chrom").is_not_null())
        .group_by("genome_id", "chrom")
        .agg(pl.col("sample").first(), pl.col("end").max().alias("length"))
    )
    if seqs.is_empty():
        raise ValueError("viralmetagenome genome_loci: no binned depth to read the genomes off")
    # A genome shorter than both ends together is cut in two halves, as
    # genome_ends bins it.
    edge = pl.max_horizontal(pl.min_horizontal(pl.col("length") // 2, pl.lit(END_BP)), pl.lit(1))
    regions = [
        ("Whole genome", 1, pl.lit(1), pl.col("length")),
        ("5' end", 2, pl.lit(1), edge),
        ("3' end", 3, pl.col("length") - edge + 1, pl.col("length")),
    ]
    out = pl.concat(
        [
            seqs.with_columns(
                pl.lit(name).alias("region"),
                pl.lit(order, dtype=pl.Int64).alias("region_order"),
                start.cast(pl.Int64).alias("start"),
                end.cast(pl.Int64).alias("end"),
            )
            for name, order, start, end in regions
        ]
    ).with_columns(
        (pl.col("genome_id") + ":" + pl.col("chrom") + ":" + pl.col("region")).alias("locus_id")
    )
    genomes = sources.get("genomes")
    if genomes is not None and not genomes.is_empty() and "virus_segment" in genomes.columns:
        out = out.join(
            genomes.select("genome_id", "virus_segment").unique(subset="genome_id"),
            on="genome_id",
            how="left",
        )
    else:
        out = out.with_columns(pl.lit(None, dtype=pl.Utf8).alias("virus_segment"))
    return out.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()]).sort(
        ["genome_id", "chrom", "region_order"]
    )
