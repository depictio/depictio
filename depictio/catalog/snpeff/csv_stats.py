"""The composition sections of SnpEff's CSV summary, melted into one long frame.

``*_snpEff.csv`` is not a CSV: it is a stack of sections, each introduced by a
``# <Section name>`` line and holding comma-separated rows padded with spaces.
Most sections share a ``Type , Count , Percent`` shape, which is why they all
fit one long frame keyed by ``section`` and ``category`` and one tab filter can
drive every tile built on them.

The raw DC scans with a separator that never occurs in the file so one full
line lands in ``raw_line``; crucially it scans WITHOUT ``comment_prefix``,
because the ``#`` lines are the section markers, not comments. The current
section is carried down each file with a forward fill over ``source_path``,
which relies on the scan preserving each file's line order (it does: the CLI
scans one file per lazy frame and concatenates them).

The sections left out are the ones no tile reads and that would dominate the
row count: the run header, the 64 by 64 codon and amino-acid change tables, the
chromosome change table and the quality / allele-frequency distributions
(``bcftools/stats_sections`` already carries those distributions per caller).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.vcf import sample_and_caller

RAW_DC_TAG = "snpeff_csv_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="raw", dc_ref=RAW_DC_TAG)]

#: SnpEff section title -> the `section` value tiles filter on. "Variantss by
#: type" is SnpEff's own typo, kept verbatim on the left so the match works.
_SECTIONS: dict[str, str] = {
    "Effects by impact": "impact",
    "Effects by functional class": "functional_class",
    "Count by effects": "effect",
    "Count by genomic region": "region",
    "Variantss by type": "variant_type",
    "Hom/Het table": "zygosity",
}
#: The Hom/Het section is `Key , Value` shaped rather than `Type , Count ,
#: Percent`, and only these four of its keys are counts.
_ZYGOSITY_KEYS = ["Reference", "Het", "Hom", "Missing"]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "caller": pl.Utf8,
    "section": pl.Utf8,
    "category": pl.Utf8,
    "count": pl.Int64,
    "percent": pl.Float64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Melt the composition sections of every SnpEff CSV into one long frame."""
    raw = sources["raw"]
    line = pl.col("raw_line")

    tagged = raw.with_columns(
        pl.when(line.str.starts_with("# "))
        .then(line.str.slice(2).str.strip_chars())
        .otherwise(None)
        .forward_fill()
        .over("source_path")
        .alias("section_title")
    ).filter(
        line.is_not_null()
        & ~line.str.starts_with("#")
        & pl.col("section_title").is_in(list(_SECTIONS))
    )

    fields = line.str.split(",")
    field0 = fields.list.get(0, null_on_oob=True).str.strip_chars()
    field1 = fields.list.get(1, null_on_oob=True).str.strip_chars()
    field2 = fields.list.get(2, null_on_oob=True).str.strip_chars().str.strip_suffix("%")

    is_zygosity = pl.col("section_title") == "Hom/Het table"
    rows = (
        tagged.with_columns(
            pl.col("section_title").replace_strict(_SECTIONS).alias("section"),
            field0.alias("category"),
            field1.cast(pl.Int64, strict=False).alias("count"),
            pl.when(is_zygosity)
            .then(None)
            .otherwise(field2.cast(pl.Float64, strict=False))
            .alias("percent"),
        )
        .join(sample_and_caller(raw), on="source_path", how="left")
        .filter(
            pl.col("count").is_not_null()
            & (pl.col("category") != "Type")
            & (~is_zygosity | pl.col("category").is_in(_ZYGOSITY_KEYS))
        )
    )

    return rows.select(list(EXPECTED_SCHEMA)).sort(["sample", "caller", "section", "category"])
