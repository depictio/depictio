"""Tidy Space Ranger's per-sample `metrics_summary.csv` into typed columns.

Space Ranger count writes one summary row per sample. Its header depends on
the assay: a probe-based run (FFPE, CytAssist) reports "Q30 Bases in Probe
Read", "Reads Mapped to Probe Set" and "Genes Detected", a whole transcriptome
run "Q30 Bases in RNA Read", "Reads Mapped to Genome", "Reads Mapped
Confidently to Transcriptome" and "Total Genes Detected". This recipe folds
both onto one schema and records which one it read in ``assay``.

Values are plain numbers in the Space Ranger releases nf-core runs (fractions
as 0 to 1); older or hand-exported files may carry thousands separators or a
``%`` sign, so every value is parsed as text: separators dropped, a ``%`` value
read as a percentage. Fractions come out as ``_pct`` columns (0 to 100).

The sample comes from the file path, never from the "Sample ID" column (that
is the FASTQ prefix, which need not be the sample sheet's id)::

    config:
      type: Table
      scan:
        mode: recursive
        scan_parameters:
          regex_config: {pattern: '.*/spaceranger/outs/metrics_summary\\.csv$'}
      dc_specific_properties:
        format: CSV
        polars_kwargs:
          include_file_paths: source_path
          infer_schema_length: 0

Output schema:
    sample : Utf8                                  <sample>/spaceranger/outs/
    assay : Utf8                                   probe-based | whole transcriptome
    spots_under_tissue : Int64                     "Number of Spots Under Tissue"
    number_of_reads : Int64                        "Number of Reads"
    mean_reads_per_spot : Float64                  "Mean Reads per Spot"
    mean_reads_under_tissue_per_spot : Float64     "Mean Reads Under Tissue per Spot"
    fraction_spots_under_tissue_pct : Float64      "Fraction of Spots Under Tissue"
    valid_barcodes_pct : Float64                   "Valid Barcodes"
    valid_umis_pct : Float64                       "Valid UMIs"
    sequencing_saturation_pct : Float64            "Sequencing Saturation"
    q30_barcode_pct : Float64                      "Q30 Bases in Barcode"
    q30_read_pct : Float64                         Q30 of the RNA or probe read
    q30_umi_pct : Float64                          "Q30 Bases in UMI"
    reads_mapped_pct : Float64                     to the probe set or the genome
    reads_mapped_confidently_pct : Float64         to the probe set or the transcriptome
    fraction_reads_in_spots_under_tissue_pct : Float64
    median_genes_per_spot : Float64                "Median Genes per Spot"
    median_umi_per_spot : Float64                  "Median UMI Counts per Spot"
    genes_detected : Int64                         "Genes Detected" / "Total Genes Detected"
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_DC_TAG = "spaceranger_metrics_raw"

SOURCES: list[RecipeSource] = [RecipeSource(ref="metrics", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "assay": pl.Utf8,
    "spots_under_tissue": pl.Int64,
    "number_of_reads": pl.Int64,
    "mean_reads_per_spot": pl.Float64,
    "mean_reads_under_tissue_per_spot": pl.Float64,
    "fraction_spots_under_tissue_pct": pl.Float64,
    "valid_barcodes_pct": pl.Float64,
    "valid_umis_pct": pl.Float64,
    "sequencing_saturation_pct": pl.Float64,
    "q30_barcode_pct": pl.Float64,
    "q30_read_pct": pl.Float64,
    "q30_umi_pct": pl.Float64,
    "reads_mapped_pct": pl.Float64,
    "reads_mapped_confidently_pct": pl.Float64,
    "fraction_reads_in_spots_under_tissue_pct": pl.Float64,
    "median_genes_per_spot": pl.Float64,
    "median_umi_per_spot": pl.Float64,
    "genes_detected": pl.Int64,
}

# output column -> raw header candidates, first present wins
_INTS: dict[str, tuple[str, ...]] = {
    "spots_under_tissue": ("Number of Spots Under Tissue",),
    "number_of_reads": ("Number of Reads",),
    "genes_detected": ("Genes Detected", "Total Genes Detected"),
}
_FLOATS: dict[str, tuple[str, ...]] = {
    "mean_reads_per_spot": ("Mean Reads per Spot",),
    "mean_reads_under_tissue_per_spot": ("Mean Reads Under Tissue per Spot",),
    "median_genes_per_spot": ("Median Genes per Spot",),
    "median_umi_per_spot": ("Median UMI Counts per Spot",),
}
_FRACTIONS: dict[str, tuple[str, ...]] = {
    "fraction_spots_under_tissue_pct": ("Fraction of Spots Under Tissue",),
    "valid_barcodes_pct": ("Valid Barcodes",),
    "valid_umis_pct": ("Valid UMIs",),
    "sequencing_saturation_pct": ("Sequencing Saturation",),
    "q30_barcode_pct": ("Q30 Bases in Barcode",),
    "q30_read_pct": ("Q30 Bases in RNA Read", "Q30 Bases in Probe Read"),
    "q30_umi_pct": ("Q30 Bases in UMI",),
    "reads_mapped_pct": ("Reads Mapped to Probe Set", "Reads Mapped to Genome"),
    "reads_mapped_confidently_pct": (
        "Reads Mapped Confidently to Probe Set",
        "Reads Mapped Confidently to Transcriptome",
    ),
    "fraction_reads_in_spots_under_tissue_pct": ("Fraction Reads in Spots Under Tissue",),
}

_SAMPLE_RE = r"(?:^|/)([^/]+)/spaceranger/outs/metrics_summary\.csv$"
_FALLBACK_SAMPLE_RE = r"(?:^|/)([^/]+)/outs/metrics_summary\.csv$"


def _text(columns: list[str], candidates: tuple[str, ...]) -> pl.Expr:
    present = [c for c in candidates if c in columns]
    if not present:
        return pl.lit(None, dtype=pl.Utf8)
    return pl.coalesce([pl.col(c).cast(pl.Utf8).str.strip_chars() for c in present])


def _number(columns: list[str], candidates: tuple[str, ...]) -> pl.Expr:
    return _text(columns, candidates).str.replace_all(",", "").str.replace_all("%", "")


def _fraction_pct(columns: list[str], candidates: tuple[str, ...]) -> pl.Expr:
    """0-100 whatever the raw spelling: `0.95`, `95%` or `95.0%`."""
    raw = _text(columns, candidates)
    value = _number(columns, candidates).cast(pl.Float64, strict=False)
    return pl.when(raw.str.contains("%")).then(value).otherwise(value * 100)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    df = sources["metrics"]
    if "source_path" not in df.columns:
        raise ValueError(
            "spaceranger_metrics: input has no 'source_path' column, the raw data "
            "collection must be scanned with polars_kwargs.include_file_paths"
        )
    cols = df.columns
    # Per row: a scan over probe-based and whole transcriptome samples unions
    # both headers, each row filling only its own.
    probe = _text(cols, ("Reads Mapped to Probe Set", "Q30 Bases in Probe Read")).is_not_null()
    path = pl.col("source_path").cast(pl.Utf8).str.replace_all(r"\\", "/")
    exprs: list[pl.Expr] = [
        pl.coalesce(
            path.str.extract(_SAMPLE_RE, 1), path.str.extract(_FALLBACK_SAMPLE_RE, 1)
        ).alias("sample"),
        pl.when(probe)
        .then(pl.lit("probe-based"))
        .otherwise(pl.lit("whole transcriptome"))
        .alias("assay"),
    ]
    exprs += [
        _number(cols, c).cast(pl.Float64, strict=False).cast(pl.Int64).alias(n)
        for n, c in _INTS.items()
    ]
    exprs += [_number(cols, c).cast(pl.Float64, strict=False).alias(n) for n, c in _FLOATS.items()]
    exprs += [_fraction_pct(cols, c).alias(n) for n, c in _FRACTIONS.items()]
    result = df.select(exprs)
    if result.filter(pl.col("sample").is_null()).height:
        raise ValueError(
            "spaceranger_metrics: a row's source_path does not look like "
            "'<sample>/spaceranger/outs/metrics_summary.csv'"
        )
    return result.select(list(EXPECTED_SCHEMA)).sort("sample")
