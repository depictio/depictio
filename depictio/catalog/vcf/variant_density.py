"""PASS variant density along the genome: calls per fixed window, per sample.

The input of a genome-wide density panel (an ideogram heat strip, a density
track): one row per sample and window holding at least one PASS call, with the
number of distinct PASS variants in it. Distinct by ``variant_key``, so a
sample called by several callers counts a variant once.

Only the primary contigs are kept (``chr1`` to ``chr22``, ``chrX``, ``chrY``,
``chrM``, with or without the ``chr`` prefix): an assembly-aware panel cannot
place an alt, unplaced or decoy contig and some renderers throw on one
(TEMPLATE_BOTTLENECKS 21). Binning goes through
``depictio.recipes.lib.genomic_bins.bin_coordinate_frame``, so the windows are
0-based, ``bin_size`` wide and aligned on multiples of it.

Template parameter (``transform.params``):
    bin_size : window width in base pairs, default 1,000,000

Output schema:
    chrom : Utf8     contig of the window
    start : Int64    window start, 0-based
    end : Int64      window end, exclusive
    value : Int64    distinct PASS variants of the sample in the window
    sample : Utf8    sample the calls were made on
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.genomic_bins import bin_coordinate_frame

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
            "is_pass": pl.Boolean,
        },
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "value": pl.Int64,
    "sample": pl.Utf8,
}

DEFAULT_BIN_SIZE = 1_000_000
PRIMARY_CONTIG_RE = r"^(?:chr)?(?:[1-9]|1[0-9]|2[0-2]|X|Y|M|MT)$"


def _bin_size(params: dict[str, str] | None) -> int:
    raw = (params or {}).get("bin_size")
    try:
        size = int(str(raw).replace("_", "").replace(",", "")) if raw else DEFAULT_BIN_SIZE
    except ValueError:
        size = DEFAULT_BIN_SIZE
    return size if size > 0 else DEFAULT_BIN_SIZE


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """Distinct PASS variants per sample in fixed windows over the primary contigs."""
    bin_size = _bin_size(params)
    calls = (
        sources["variants"]
        .filter(
            pl.col("is_pass").fill_null(False)
            & pl.col("chrom").str.contains(PRIMARY_CONTIG_RE)
            & pl.col("pos").is_not_null()
        )
        .select("sample", "chrom", "pos", "variant_key")
        .unique(subset=["sample", "variant_key"])
        # genomic_bins bins a 0-based start; a VCF POS is 1-based.
        .with_columns((pl.col("pos") - 1).alias("start0"), pl.lit(1.0).alias("one"))
    )
    parts: list[pl.DataFrame] = []
    for (sample,), block in calls.group_by("sample", maintain_order=True):
        binned = bin_coordinate_frame(
            block.lazy(),
            chrom_col="chrom",
            pos_col="start0",
            value_col="one",
            bin_size=bin_size,
            streaming=False,
        )
        parts.append(
            binned.select(
                "chrom",
                "start",
                "end",
                pl.col("n").cast(pl.Int64).alias("value"),
                pl.lit(sample, dtype=pl.Utf8).alias("sample"),
            )
        )
    if not parts:
        return pl.DataFrame(schema=OUTPUT_SCHEMA)
    return (
        pl.concat(parts)
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["sample", "chrom", "start"])
    )
