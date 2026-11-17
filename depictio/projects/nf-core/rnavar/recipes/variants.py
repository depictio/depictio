"""nf-core/rnavar variant calls: one row per call, from the filtered VCF of each sample.

rnavar publishes each sample's HaplotypeCaller calls twice under
``variant_calling/<sample>/``: ``<sample>.haplotypecaller.vcf.gz`` as called,
and ``<sample>.haplotypecaller.filtered.vcf.gz`` after GATK VariantFiltration,
which holds the same records with the hard filters it applied written into
FILTER (FS, QD, SnpCluster). Reading both would count every call twice, so per
sample the filtered file wins and the unfiltered one is read only when the run
skipped filtration (``--skip_tools variantfiltration``), where it is the only
file. The parsing is the shared one (``depictio.recipes.lib.vcf``), so the
frame has exactly the columns of the catalog ``vcf/variants`` output and every
catalog recipe built on that output reads it unchanged.

Sources:
    raw  ``vcf_calls_raw``: one VCF line per row in ``raw_line``, the file path
         in ``source_path``

Output schema: the 14 columns of ``depictio.recipes.lib.vcf.CORE_COLUMNS``
(sample, caller, chrom, pos, variant_key, ref, alt, variant_type, qual,
filter_status, is_pass, gt, dp, vaf), plus
    stage : Utf8   ``filtered`` when the call came from the filtered VCF, ``raw`` otherwise
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.vcf import (
    CORE_COLUMNS,
    RAW_LINE_COL,
    SOURCE_PATH_COL,
    sample_and_caller,
    vcf_to_long,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="raw",
        dc_ref="vcf_calls_raw",
        input_schema={RAW_LINE_COL: pl.Utf8, SOURCE_PATH_COL: pl.Utf8},
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "caller": pl.Utf8,
    "chrom": pl.Utf8,
    "pos": pl.Int64,
    "variant_key": pl.Utf8,
    "ref": pl.Utf8,
    "alt": pl.Utf8,
    "variant_type": pl.Utf8,
    "qual": pl.Float64,
    "filter_status": pl.Utf8,
    "is_pass": pl.Boolean,
    "gt": pl.Utf8,
    "dp": pl.Int64,
    "vaf": pl.Float64,
    "stage": pl.Utf8,
}

_FILTERED_RE = r"\.filtered\.vcf(?:\.b?gz)?$"


def kept_files(raw: pl.DataFrame) -> pl.DataFrame:
    """One ``source_path`` per sample and caller: the filtered VCF when there is one."""
    files = sample_and_caller(raw).with_columns(
        pl.col(SOURCE_PATH_COL).str.contains(_FILTERED_RE).alias("_filtered")
    )
    return (
        files.sort(
            ["sample", "caller", "_filtered", SOURCE_PATH_COL],
            descending=[False, False, True, False],
        )
        .unique(subset=["sample", "caller"], keep="first", maintain_order=True)
        .select(
            SOURCE_PATH_COL,
            pl.when(pl.col("_filtered"))
            .then(pl.lit("filtered"))
            .otherwise(pl.lit("raw"))
            .alias("stage"),
        )
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Keep the filtered VCF of every sample, then one row per call."""
    raw = sources["raw"]
    keep = kept_files(raw)
    narrowed = raw.join(keep.select(SOURCE_PATH_COL), on=SOURCE_PATH_COL, how="semi")
    stage = keep.join(sample_and_caller(narrowed), on=SOURCE_PATH_COL).select(
        "sample", "caller", "stage"
    )
    calls = vcf_to_long(narrowed).join(stage, on=["sample", "caller"], how="left")
    return (
        calls.select([*CORE_COLUMNS, "stage"])
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["sample", "caller", "chrom", "pos"])
    )
