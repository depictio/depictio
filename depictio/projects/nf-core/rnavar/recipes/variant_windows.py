"""nf-core/rnavar Genome tab navigator: PASS variants of the cohort in 1 Mb windows.

The Genome tab's locus section is driven by one ``genome_view`` navigator that
emits a region filter; the call track and the file-backed VCF track follow it.
A navigator receives its whole collection sampled to about 10,000 rows
(TEMPLATE_BOTTLENECKS 20), so it reads a cohort-level summary rather than the
calls: one row per 1 Mb window holding at least one PASS call, about 2,500 on a
human transcriptome, never sampled. RNA calls pile up on expressed genes, so the
windows light up where the transcriptome is dense (chr19, chr17, chr1p) and stay
dark over gene deserts.

The coordinates are named ``chrom`` / ``pos`` / ``end`` like the call track's,
because a follower only zooms on a region the navigator names in its own column
names (TEMPLATE_BOTTLENECKS 19). Only the primary contigs are kept, since the
assembly-aware view throws on an alt or unplaced contig (TEMPLATE_BOTTLENECKS 21).

The windows are the 0-based, 1 Mb aligned ones ``depictio.recipes.lib.genomic_bins``
draws. The per-sample, ideogram-shaped density (chrom, start, end, value,
sample) is the catalog output ``vcf/variant_density``, built on that helper;
this one is the navigator's.

Sources:
    variants  ``vcf_variants`` (this template's ``variants.py``)

Output schema:
    chrom : Utf8          primary contig
    pos : Int64           window start, 0-based
    end : Int64           window end, exclusive
    variants : Int64      distinct PASS variants in the window, over every sample
    calls : Int64         PASS calls in the window (a variant called in 3 samples counts 3)
    samples : Int64       samples with at least one PASS call in the window
    snv_pct : Float64     share of the window's distinct variants that are SNVs, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="variants",
        dc_ref="vcf_variants",
        input_schema={
            "sample": pl.Utf8,
            "chrom": pl.Utf8,
            "pos": pl.Int64,
            "variant_key": pl.Utf8,
            "variant_type": pl.Utf8,
            "is_pass": pl.Boolean,
        },
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "chrom": pl.Utf8,
    "pos": pl.Int64,
    "end": pl.Int64,
    "variants": pl.Int64,
    "calls": pl.Int64,
    "samples": pl.Int64,
    "snv_pct": pl.Float64,
}

BIN_SIZE = 1_000_000
PRIMARY_CONTIG_RE = r"^(?:chr)?(?:[1-9]|1[0-9]|2[0-2]|X|Y|M|MT)$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Sum the cohort's PASS calls into 1 Mb windows over the primary contigs."""
    calls = sources["variants"].filter(
        pl.col("is_pass").fill_null(False)
        & pl.col("chrom").str.contains(PRIMARY_CONTIG_RE)
        & pl.col("pos").is_not_null()
    )
    if calls.is_empty():
        return pl.DataFrame(schema=OUTPUT_SCHEMA)
    windowed = calls.with_columns(((pl.col("pos") - 1) // BIN_SIZE * BIN_SIZE).alias("_start"))
    per_window = windowed.group_by(["chrom", "_start"]).agg(
        pl.col("variant_key").n_unique().cast(pl.Int64).alias("variants"),
        pl.len().cast(pl.Int64).alias("calls"),
        pl.col("sample").n_unique().cast(pl.Int64).alias("samples"),
        pl.col("variant_key")
        .filter(pl.col("variant_type") == "SNP")
        .n_unique()
        .cast(pl.Int64)
        .alias("_snvs"),
    )
    return (
        per_window.with_columns(
            pl.col("_start").cast(pl.Int64).alias("pos"),
            (pl.col("_start") + BIN_SIZE).cast(pl.Int64).alias("end"),
            pl.when(pl.col("variants") > 0)
            .then(pl.col("_snvs") * 100.0 / pl.col("variants"))
            .otherwise(None)
            .round(2)
            .alias("snv_pct"),
        )
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["chrom", "pos"])
    )
