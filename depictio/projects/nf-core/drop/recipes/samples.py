"""The nf-core/drop sample hub: one row per RNA sample of the run's sample sheet.

DROP reads one annotation table (``--input``, a TSV): one row per RNA assay with
its alignment (``RNA_BAM_FILE``) or, for a sample taken from another study, its
exported counts (``GENE_COUNTS_FILE``), the analysis groups it belongs to
(``DROP_GROUP``, comma-separated: one sample can sit in several groups) and the
optional DNA genotype and phenotype terms. Every output of the run names its rows
after ``RNA_ID``, so that column is the key every link joins on.

The hub gives each sample one ``drop_group`` so the group filter and the colours have a
single value to read: the most specific group of its ``DROP_GROUP`` list, the one the
fewest samples of the sheet share (a batch before an "all" group), the first listed on
a tie. The full list stays in ``drop_groups`` and the long ``group_membership``
collection counts a sample once per group it belongs to. ``group_size`` is the number of
samples in the largest group a sample belongs to: the cohort its OUTRIDER and FRASER models
are fitted on, which decides whether they have the power to call anything.

Sources:
    sheet   the run's sample sheet (the template repoints it at ``{SAMPLESHEET}``)

Output schema: see ``OUTPUT_SCHEMA``. Columns the sheet leaves empty fall back to
the pipeline's own defaults (paired-end, ``IntersectionStrict`` counting).
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="sheet",
        path="input/samplesheet.tsv",
        format="tsv",
        input_schema={"RNA_ID": pl.Utf8, "DROP_GROUP": pl.Utf8},
        read_kwargs={"infer_schema_length": 0},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "drop_group": pl.Utf8,
    "drop_groups": pl.Utf8,
    "n_groups": pl.Int64,
    "group_size": pl.Int64,
    "count_source": pl.Utf8,
    "strandedness": pl.Utf8,
    "read_type": pl.Utf8,
    "count_mode": pl.Utf8,
    "has_dna": pl.Utf8,
    "n_hpo_terms": pl.Int64,
    "annotation": pl.Utf8,
    "genome": pl.Utf8,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "dna_id": pl.Utf8,
    "hpo_terms": pl.Utf8,
}

_STRAND = {"no": "unstranded", "yes": "stranded", "reverse": "reverse-stranded"}
_FALSE = ("false", "0", "no", "f")


def _clean(df: pl.DataFrame, column: str) -> pl.Expr:
    """The column as trimmed text, empty and NA cells as null (absent column: null)."""
    if column not in df.columns:
        return pl.lit(None, dtype=pl.Utf8)
    text = pl.col(column).cast(pl.Utf8).str.strip_chars()
    return pl.when(text.is_in(["", "NA", "nan"])).then(None).otherwise(text)


def _groups(value: str | None) -> list[str]:
    return [g.strip() for g in (value or "").split(",") if g.strip()]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per RNA sample, with its primary group, count source and design."""
    sheet = sources["sheet"]
    base = sheet.select(
        _clean(sheet, "RNA_ID").alias("sample"),
        _clean(sheet, "DROP_GROUP").alias("_groups"),
        _clean(sheet, "RNA_BAM_FILE").alias("_bam"),
        _clean(sheet, "GENE_COUNTS_FILE").alias("_counts"),
        _clean(sheet, "STRAND").str.to_lowercase().alias("_strand"),
        _clean(sheet, "PAIRED_END").str.to_lowercase().alias("_paired"),
        _clean(sheet, "COUNT_MODE").alias("count_mode"),
        _clean(sheet, "DNA_VCF_FILE").alias("_vcf"),
        _clean(sheet, "DNA_ID").alias("dna_id"),
        _clean(sheet, "HPO_TERMS").alias("hpo_terms"),
        _clean(sheet, "GENE_ANNOTATION").alias("annotation"),
        _clean(sheet, "GENOME").alias("genome"),
    ).filter(pl.col("sample").is_not_null())

    records = base.to_dicts()
    sizes: dict[str, int] = {}
    for rec in records:
        for group in _groups(rec["_groups"]):
            sizes[group] = sizes.get(group, 0) + 1

    rows = []
    for rec in records:
        groups = _groups(rec["_groups"])
        # min() keeps the first of equals: ties go to the group listed first.
        primary = min(groups, key=lambda g: sizes[g]) if groups else "ungrouped"
        hpo = [t for t in (rec["hpo_terms"] or "").split(",") if t.strip()]
        rows.append(
            {
                "sample": rec["sample"],
                "drop_group": primary,
                "drop_groups": ", ".join(groups),
                "n_groups": len(groups),
                "group_size": max((sizes[g] for g in groups), default=1),
                "count_source": "Alignment" if rec["_bam"] else "External counts",
                "strandedness": _STRAND.get(rec["_strand"] or "", rec["_strand"] or "unknown"),
                "read_type": "single-end" if (rec["_paired"] or "true") in _FALSE else "paired-end",
                "count_mode": rec["count_mode"] or "IntersectionStrict",
                "has_dna": "Genotyped" if rec["_vcf"] else "RNA only",
                "n_hpo_terms": len(hpo),
                "annotation": rec["annotation"] or "",
                "genome": rec["genome"] or "",
                "dna_id": rec["dna_id"],
                "hpo_terms": rec["hpo_terms"],
            }
        )
    schema = {**OUTPUT_SCHEMA, **OPTIONAL_OUTPUT_SCHEMA}
    return pl.DataFrame(rows, schema=schema).unique(subset="sample", keep="first").sort("sample")
