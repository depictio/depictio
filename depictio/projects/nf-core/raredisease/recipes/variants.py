"""nf-core/raredisease small-variant calls: one row per carried call, from the family callset.

raredisease calls the whole family at once (DeepVariant per sample, then GLnexus
joint-genotypes them) and publishes one multi-sample VCF per family under
``call_snv/genome/<family>_snv.vcf.gz``. The catalog ``vcf/*`` recipes read a
frame with one row per sample and call, so this recipe unpivots the sample
columns of that file: the sample names are read off its ``#CHROM`` line (a
joint VCF names its samples in the header, not in the file name), each sample
column is rewritten as a one-sample VCF line, and the shared reader
(``depictio.recipes.lib.vcf.vcf_to_long``) parses it. The frame therefore has
exactly the 14 columns of the catalog ``vcf/variants`` output and every catalog
recipe built on it (callset summary, substitution spectrum, FILTER breakdown,
variant density) reads it unchanged.

Only the calls a sample carries are kept (genotype with an alternate allele).
A joint VCF holds a row for every site any sample varies at, so most sample
cells are homozygous reference or no-call; counting those would swamp the Ts/Tv,
het/hom and PASS numbers the catalog recipes derive.

The caller is the ``FOUND_IN`` INFO value of the file's first record
(``deepvariant`` for the default caller, ``sentieon`` or another name otherwise),
and ``snv`` when the file carries none.

Sources:
    raw  every ``call_snv/genome/*_snv.vcf.gz``, one VCF line per row in
         ``raw_line``, the file path in ``source_path``

Output schema: the 14 columns of ``depictio.recipes.lib.vcf.CORE_COLUMNS``
(sample, caller, chrom, pos, variant_key, ref, alt, variant_type, qual,
filter_status, is_pass, gt, dp, vaf).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.vcf import CORE_COLUMNS, RAW_LINE_COL, SOURCE_PATH_COL, vcf_to_long

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="raw",
        glob_pattern="call_snv/genome/*_snv.vcf.gz",
        format="csv",
        # One full VCF line per row: no separator, quote or header can occur in it.
        read_kwargs={
            "separator": "\x1e",
            "has_header": False,
            "new_columns": [RAW_LINE_COL],
            "quote_char": None,
            "infer_schema_length": 0,
        },
        source_path=SOURCE_PATH_COL,
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
}

_FOUND_IN = r"(?:^|;)FOUND_IN=([A-Za-z0-9_-]+)"
_CARRIES_ALT = r"[1-9]"


def _joint_files(raw: pl.DataFrame):
    """Yield ``(sample names, data lines)`` for every VCF of the raw frame."""
    for path in raw[SOURCE_PATH_COL].unique(maintain_order=True).to_list():
        lines = raw.filter(pl.col(SOURCE_PATH_COL) == path)[RAW_LINE_COL].drop_nulls()
        header = lines.filter(lines.str.starts_with("#CHROM"))
        if header.is_empty():
            continue
        names = header[0].split("\t")[9:]
        body = lines.filter(~lines.str.starts_with("#")).to_frame(RAW_LINE_COL)
        if names and not body.is_empty():
            yield names, body


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per call carried by a sample of the family callset."""
    frames: list[pl.DataFrame] = []
    for names, body in _joint_files(sources["raw"]):
        fields = pl.col(RAW_LINE_COL).str.split("\t")
        body = body.with_columns(fields.alias("_f"))
        found = (
            body.select(fields.list.get(7, null_on_oob=True).str.extract(_FOUND_IN, 1).alias("c"))
            .drop_nulls()
            .head(1)
        )
        caller = found["c"][0] if not found.is_empty() else "snv"
        for i, name in enumerate(names):
            fixed = [pl.col("_f").list.get(k, null_on_oob=True) for k in range(9)]
            one = body.select(
                pl.concat_str(
                    [*fixed, pl.col("_f").list.get(9 + i, null_on_oob=True)], separator="\t"
                ).alias(RAW_LINE_COL),
                pl.lit(f"{name}.{caller}.vcf.gz").alias(SOURCE_PATH_COL),
            )
            frames.append(vcf_to_long(one))
    if not frames:
        raise ValueError("raredisease variants: no call_snv/genome/*_snv.vcf.gz with samples")
    calls = pl.concat(frames).filter(pl.col("gt").str.contains(_CARRIES_ALT).fill_null(False))
    return (
        calls.select(CORE_COLUMNS)
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["sample", "chrom", "pos"])
    )
