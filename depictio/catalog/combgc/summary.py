"""Tidy the comBGC complete summary into one row per predicted BGC region.

comBGC (nf-core/funcscan's own aggregation script) parses antiSMASH, DeepBGC
and GECCO outputs into one shared table. It writes a per-sample
``<sample>/combgc_summary.tsv`` next to a run-level
``combgc_complete_summary.tsv``; only the run-level file carries every tool
(the per-sample files hold the antiSMASH branch alone), so the recipe reads
that one and normalises the column names.

The tool-dependent fields are cast leniently: antiSMASH reports a
completeness call but no probability, GECCO the other way round.

Output columns:
    sample, contig, tool, product_class, probability, complete, start, end,
    length, cds_count, n_pfam, pfam_domains, mibig_id, regions
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summary",
        path="reports/combgc/combgc_complete_summary.tsv",
        format="TSV",
        read_kwargs={"infer_schema_length": 10000, "null_values": ["NA", ""], "quote_char": None},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "contig": pl.Utf8,
    "tool": pl.Utf8,
    "product_class": pl.Utf8,
    "probability": pl.Float64,
    "complete": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "length": pl.Int64,
    "cds_count": pl.Int64,
    "n_pfam": pl.Int64,
    "pfam_domains": pl.Utf8,
    "mibig_id": pl.Utf8,
    "regions": pl.Int64,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Rename comBGC columns and cast the tool-dependent ones leniently."""
    df = sources["summary"]

    def _col(name: str, dtype: type[pl.DataType]) -> pl.Expr:
        if name in df.columns:
            return pl.col(name).cast(dtype, strict=False)
        return pl.lit(None).cast(dtype)

    pfam = _col("PFAM_domains", pl.Utf8)
    return (
        df.select(
            _col("sample_id", pl.Utf8).alias("sample"),
            _col("contig_id", pl.Utf8).alias("contig"),
            _col("Prediction_tool", pl.Utf8).alias("tool"),
            _col("Product_class", pl.Utf8).fill_null("Unknown").alias("product_class"),
            _col("BGC_probability", pl.Float64).alias("probability"),
            _col("BGC_complete", pl.Utf8).fill_null("unknown").alias("complete"),
            _col("BGC_start", pl.Int64).alias("start"),
            _col("BGC_end", pl.Int64).alias("end"),
            _col("BGC_length", pl.Int64).alias("length"),
            _col("CDS_count", pl.Int64).alias("cds_count"),
            # Domain richness: how many PFAM domains the region's CDSs carry.
            # comBGC writes them as one ';'-joined string per region.
            pl.when(pfam.is_null())
            .then(pl.lit(0, dtype=pl.Int64))
            .otherwise(pfam.str.split(";").list.len().cast(pl.Int64))
            .alias("n_pfam"),
            pfam.alias("pfam_domains"),
            _col("MIBiG_ID", pl.Utf8).alias("mibig_id"),
            pl.lit(1, dtype=pl.Int64).alias("regions"),
        )
        .sort("sample", "contig", "start")
        .select(list(EXPECTED_SCHEMA))
    )
