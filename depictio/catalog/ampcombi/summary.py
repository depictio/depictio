"""Tidy the AMPcombi ``complete`` summary: one row per AMP candidate.

AMPcombi merges the per-tool AMP predictions (ampir, Macrel, AMPlify, HMMER)
into one table per sample, annotates each candidate with physicochemical
properties (molecular weight, isoelectric point, hydrophobicity, secondary
structure fractions) and aligns it against a reference AMP database. The
``complete`` step concatenates the samples into ``Ampcombi_summary.tsv``.

The tool probability columns depend on which predictors ran: absent ones are
added as nulls so the schema stays stable, and ``prob_max`` / ``n_tools``
summarise them (AMPcombi writes 0 for a tool that did not call the peptide).

Output columns:
    sample, cds_id, contig, prob_ampir, prob_macrel, prob_amplify, prob_max,
    n_tools, aa_length, molecular_weight, isoelectric_point, hydrophobicity,
    helix_fraction, turn_fraction, sheet_fraction, charge_class,
    transporter_protein, stop_codon, cds_start, cds_end, strand, db_hit,
    db_description, db_evalue, db_pident, aa_sequence
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summary",
        path="reports/ampcombi2/Ampcombi_summary.tsv",
        format="TSV",
        read_kwargs={"infer_schema_length": 10000, "null_values": ["NA", ""], "quote_char": None},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "cds_id": pl.Utf8,
    "contig": pl.Utf8,
    "prob_ampir": pl.Float64,
    "prob_macrel": pl.Float64,
    "prob_amplify": pl.Float64,
    "prob_max": pl.Float64,
    "n_tools": pl.Int64,
    "aa_length": pl.Int64,
    "molecular_weight": pl.Float64,
    "isoelectric_point": pl.Float64,
    "hydrophobicity": pl.Float64,
    "helix_fraction": pl.Float64,
    "turn_fraction": pl.Float64,
    "sheet_fraction": pl.Float64,
    "charge_class": pl.Utf8,
    "transporter_protein": pl.Utf8,
    "stop_codon": pl.Utf8,
    "cds_start": pl.Int64,
    "cds_end": pl.Int64,
    "strand": pl.Utf8,
    "db_hit": pl.Utf8,
    "db_description": pl.Utf8,
    "db_evalue": pl.Float64,
    "db_pident": pl.Float64,
    "aa_sequence": pl.Utf8,
}

_PROB_COLS = ("prob_ampir", "prob_macrel", "prob_amplify")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Normalise column names and derive the summary scores."""
    df = sources["summary"]

    def _col(name: str, dtype: type[pl.DataType]) -> pl.Expr:
        if name in df.columns:
            return pl.col(name).cast(dtype, strict=False)
        return pl.lit(None).cast(dtype)

    # The reference-database columns are named after the database id AMPcombi
    # was run with (APD_ID / DRAMP_ID / UniRef100_ID ...): take whatever *_ID /
    # *_Description pair the run wrote.
    db_id_col = next((c for c in df.columns if c.endswith("_ID") and c != "CDS_ID"), None)
    db_desc_col = next((c for c in df.columns if c.endswith("_Description")), None)

    probs = [_col(c, pl.Float64).alias(c) for c in _PROB_COLS]
    out = df.select(
        _col("sample_id", pl.Utf8).alias("sample"),
        _col("CDS_id", pl.Utf8).alias("cds_id"),
        _col("contig_id", pl.Utf8).alias("contig"),
        *probs,
        _col("aa_sequence", pl.Utf8).str.len_chars().cast(pl.Int64).alias("aa_length"),
        _col("molecular_weight", pl.Float64).alias("molecular_weight"),
        _col("isoelectric_point", pl.Float64).alias("isoelectric_point"),
        _col("hydrophobicity", pl.Float64).alias("hydrophobicity"),
        _col("helix_fraction", pl.Float64).alias("helix_fraction"),
        _col("turn_fraction", pl.Float64).alias("turn_fraction"),
        _col("sheet_fraction", pl.Float64).alias("sheet_fraction"),
        _col("transporter_protein", pl.Utf8).alias("transporter_protein"),
        _col("CDS_stop_codon_found", pl.Utf8).alias("stop_codon"),
        _col("CDS_start", pl.Int64).alias("cds_start"),
        _col("CDS_end", pl.Int64).alias("cds_end"),
        _col("CDS_dir", pl.Int64).alias("cds_dir"),
        (_col(db_id_col, pl.Utf8) if db_id_col else pl.lit(None).cast(pl.Utf8)).alias("db_hit"),
        (_col(db_desc_col, pl.Utf8) if db_desc_col else pl.lit(None).cast(pl.Utf8)).alias(
            "db_description"
        ),
        _col("evalue", pl.Float64).alias("db_evalue"),
        _col("pident", pl.Float64).alias("db_pident"),
        _col("aa_sequence", pl.Utf8).alias("aa_sequence"),
    )
    return out.with_columns(
        pl.max_horizontal(*_PROB_COLS).alias("prob_max"),
        pl.sum_horizontal(*[(pl.col(c).fill_null(0.0) > 0).cast(pl.Int64) for c in _PROB_COLS])
        .cast(pl.Int64)
        .alias("n_tools"),
        pl.when(pl.col("isoelectric_point") >= 8.0)
        .then(pl.lit("basic"))
        .when(pl.col("isoelectric_point") <= 6.0)
        .then(pl.lit("acidic"))
        .otherwise(pl.lit("neutral"))
        .alias("charge_class"),
        pl.when(pl.col("cds_dir") < 0).then(pl.lit("-")).otherwise(pl.lit("+")).alias("strand"),
    ).select(list(EXPECTED_SCHEMA))
