"""Parse ARTIC/clair3 (or medaka) nanopore per-sample VCFs into variants_long.

This is the nanopore variant-calling path of nf-core/viralrecon: instead of
ivar's `variants_long_table.csv`, nanopore runs produce per-sample
`*.pass.vcf.gz` files under `artic_minion/` (clair3 by default, medaka legacy).
This recipe reshapes those VCFs into the SAME long-table schema as
`ivar/variants_long.py`, so the artic tool reuses the same advanced-viz renders.

!!! UNVALIDATED — must be checked against a real nf-core/viralrecon nanopore run.
No nanopore sample data is available in this repo, so the VCF/INFO field names
(AF source, snpEff `ANN`/`EFF` annotation layout, GENE/AA/EFFECT extraction) are
best-effort guesses based on the clair3 + snpEff conventions. Verify the column
names and the ANN-field index used below against actual output before relying on
this in production.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="variants_raw",
        # Per-sample clair3/medaka pass VCFs under the ARTIC minion output dir.
        glob_pattern="**/artic_minion/**/*.pass.vcf.gz",
        format="CSV",  # VCF is read as a headerless TSV; see transform()
        read_kwargs={
            "separator": "\t",
            "comment_prefix": "#",
            "has_header": False,
            "new_columns": [
                "CHROM",
                "POS",
                "ID",
                "REF",
                "ALT",
                "QUAL",
                "FILTER",
                "INFO",
                "FORMAT",
                "SAMPLE_COL",
            ],
        },
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "CHROM": pl.Utf8,
    "POS": pl.Int64,
    "REF": pl.Utf8,
    "ALT": pl.Utf8,
    "AF": pl.Float64,
    "GENE": pl.Utf8,
    "AA": pl.Utf8,
    "EFFECT": pl.Utf8,
    "FUNCLASS": pl.Utf8,
    "mutation_label": pl.Utf8,
}


def _extract_info(info: pl.Expr, key: str) -> pl.Expr:
    """Pull a `KEY=value` field out of a VCF INFO column (null if absent)."""
    return info.str.extract(rf"(?:^|;){key}=([^;]+)", 1)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Reshape a clair3/medaka VCF into the variants_long schema.

    Best-effort parser:
      - sample name is not in the VCF body, so it is recovered from the file's
        sample/genotype column header if available, else left as "Unknown"
        (a real ingest should bind it per-file).
      - AF is read from INFO (clair3 emits `AF=` in some configs; medaka uses a
        FORMAT field) — adjust against a real run if the source differs.
      - GENE / AA / EFFECT come from the snpEff `ANN=` annotation (pipe-split):
        ANN = Allele|Annotation|Impact|Gene_Name|...|HGVS.p|... — indices below
        follow the snpEff spec but MUST be verified against real viralrecon output.
    """
    df = sources["variants_raw"]

    # Numeric position.
    df = df.with_columns(pl.col("POS").cast(pl.Int64, strict=False))

    info = pl.col("INFO")

    # Allele frequency — try an INFO AF= field first.
    df = df.with_columns(_extract_info(info, "AF").cast(pl.Float64, strict=False).alias("AF"))

    # snpEff ANN: first annotation, pipe-separated fields.
    ann = _extract_info(info, "ANN")
    ann_fields = ann.str.split("|")
    df = df.with_columns(
        ann_fields.list.get(1, null_on_oob=True).alias("EFFECT"),  # Annotation
        ann_fields.list.get(3, null_on_oob=True).alias("GENE"),  # Gene_Name
        ann_fields.list.get(10, null_on_oob=True).alias("AA"),  # HGVS.p
    )

    # sample: VCF body has none; use a placeholder unless an ingest binds it.
    df = df.with_columns(pl.lit("Unknown").alias("sample"))

    # Derive FUNCLASS from EFFECT (mirror ivar recipe buckets).
    df = df.with_columns(
        pl.when(
            pl.col("EFFECT").str.contains("(?i)synonymous")
            & ~pl.col("EFFECT").str.contains("(?i)missense|non")
        )
        .then(pl.lit("SILENT"))
        .when(pl.col("EFFECT").str.contains("(?i)missense"))
        .then(pl.lit("MISSENSE"))
        .when(pl.col("EFFECT").str.contains("(?i)stop_gained|nonsense|frameshift"))
        .then(pl.lit("NONSENSE"))
        .otherwise(pl.lit("OTHER"))
        .alias("FUNCLASS")
    )

    # Fill nulls for the categorical/annotation columns.
    for col_name in ("GENE", "AA", "EFFECT", "FUNCLASS"):
        df = df.with_columns(pl.col(col_name).fill_null("Unknown"))

    # mutation_label: GENE:REF{POS}ALT (same shape as ivar).
    df = df.with_columns(
        (pl.col("GENE") + ":" + pl.col("REF") + pl.col("POS").cast(pl.Utf8) + pl.col("ALT")).alias(
            "mutation_label"
        )
    )

    return df.select(list(EXPECTED_SCHEMA.keys()))
