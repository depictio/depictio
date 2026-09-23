"""nf-core/rnaseq genes as one row each: how much, how variable, where highest.

nf-core/rnaseq stops at quantification, so there is no test result to pick a
gene from. What the merged Salmon TPM matrix does give is the mean-variance
plane every RNA-seq exploration starts on: a gene's mean expression against
how much it varies across the libraries. Genes that sit high on that plane are
the ones the conditions separate, and they are the natural thing to click.
This recipe reduces the matrix to that plane plus the facts a gene record
shows once a gene is picked (identifier, symbol, the condition it peaks in).

Sources:
    matrix  ``salmon.merged.gene_tpm.tsv`` (``gene_id``, ``gene_name``, one TPM
            column per library). The template repoints it at the aligner route
            it covers.

Output, genes expressed at 1 TPM or more in at least one library (the rule the
gene explorer's long table uses), one row per gene:
    gene_id, gene_name        identifiers as the matrix spells them
    mean_log2_tpm             mean of log2(TPM + 1) over the libraries
    sd_log2_tpm               its standard deviation, the y of the plane
    max_tpm                   the highest TPM any library reached
    top_sample                the library that reached it
    top_condition             the condition with the highest mean log2(TPM + 1)
    log2fc_top_vs_rest        that condition's mean minus the mean of the rest
    libraries_detected        libraries with TPM above zero (Int64)
Conditions are read off the ``<condition>_REP<n>`` sample names nf-core
RNA-seq uses; a run without that suffix treats each library as its own
condition, which keeps every column filled.
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="matrix",
        path="salmon/salmon.merged.gene_tpm.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 10000},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "gene_id": pl.Utf8,
    "gene_name": pl.Utf8,
    "mean_log2_tpm": pl.Float64,
    "sd_log2_tpm": pl.Float64,
    "max_tpm": pl.Float64,
    "top_sample": pl.Utf8,
    "top_condition": pl.Utf8,
    "log2fc_top_vs_rest": pl.Float64,
    "libraries_detected": pl.Int64,
}

MIN_TPM = 1.0

# Same rule as the samplesheet recipe (recipes may not import each other).
_REPLICATE = re.compile(r"^(?P<condition>.+?)[._-](?:rep|r)?\d+$", re.IGNORECASE)


def _condition(sample: str) -> str:
    match = _REPLICATE.match(sample)
    return match.group("condition") if match else sample


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Reduce the gene x library TPM matrix to one summary row per gene."""
    matrix = sources["matrix"]
    id_col = "gene_id" if "gene_id" in matrix.columns else matrix.columns[0]
    name_col = "gene_name" if "gene_name" in matrix.columns else None
    samples = [
        c for c in matrix.columns if c not in (id_col, name_col) and matrix[c].dtype.is_numeric()
    ]
    if not samples:
        raise ValueError("gene_summary: the TPM matrix has no numeric library column")

    tpm = matrix.select(
        pl.col(id_col).cast(pl.Utf8).alias("gene_id"),
        (pl.col(name_col).cast(pl.Utf8) if name_col else pl.col(id_col).cast(pl.Utf8)).alias(
            "gene_name"
        ),
        *[pl.col(s).cast(pl.Float64).fill_null(0.0).alias(s) for s in samples],
    ).filter(pl.max_horizontal(samples) >= MIN_TPM)

    log2 = [(pl.col(s) + 1.0).log(2) for s in samples]
    conditions: dict[str, list[str]] = {}
    for s in samples:
        conditions.setdefault(_condition(s), []).append(s)
    cond_names = list(conditions)
    cond_means = [
        pl.mean_horizontal([(pl.col(s) + 1.0).log(2) for s in members]).alias(f"_c{i}")
        for i, members in enumerate(conditions.values())
    ]

    out = tpm.with_columns(
        pl.mean_horizontal(log2).alias("mean_log2_tpm"),
        pl.concat_list(log2).list.std().alias("sd_log2_tpm"),
        pl.max_horizontal(samples).alias("max_tpm"),
        pl.concat_list(samples).list.arg_max().alias("_top_idx"),
        pl.sum_horizontal([(pl.col(s) > 0).cast(pl.Int64) for s in samples]).alias(
            "libraries_detected"
        ),
        *cond_means,
    )
    cond_cols = [f"_c{i}" for i in range(len(cond_names))]
    out = out.with_columns(
        pl.concat_list(cond_cols).list.arg_max().alias("_top_cond_idx"),
        pl.max_horizontal(cond_cols).alias("_top_cond_mean"),
        pl.sum_horizontal(cond_cols).alias("_cond_sum"),
    )
    rest = len(cond_cols) - 1
    out = out.with_columns(
        pl.col("_top_idx")
        .map_elements(lambda i: samples[i], return_dtype=pl.Utf8)
        .alias("top_sample"),
        pl.col("_top_cond_idx")
        .map_elements(lambda i: cond_names[i], return_dtype=pl.Utf8)
        .alias("top_condition"),
        (
            pl.col("_top_cond_mean") - (pl.col("_cond_sum") - pl.col("_top_cond_mean")) / rest
            if rest > 0
            else pl.lit(0.0)
        )
        .cast(pl.Float64)
        .alias("log2fc_top_vs_rest"),
    )
    return (
        out.select(list(EXPECTED_SCHEMA))
        .with_columns(pl.col("sd_log2_tpm").fill_null(0.0))
        .sort("sd_log2_tpm", descending=True)
    )
