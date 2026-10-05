"""PURPLE's tumor fit and QC verdict, one row per tumor sample.

PURPLE (hmftools) fits purity and ploidy jointly from the tumor/normal read
depth ratios (COBALT) and B-allele frequencies (AMBER), then summarises the
tumor's genome-wide state in two files per tumor:

* ``<tumor>.purple.purity.tsv``: one header row and one data row with the fit
  (purity, ploidy, diploid proportion, fit status, sex) and the genome-wide
  mutational load (microsatellite indels per Mb and MSI status, tumor mutational
  load and burden, structural-variant burden, whole-genome duplication);
* ``<tumor>.purple.qc``: two columns, key then value, no header (QC status,
  copy-number segments, deleted genes, contamination, LOH fraction, TINC).

Neither file names the tumor inside, so both are read with the file path and
the tumor id is the file name before ``.purple.``. The two are joined into one
row: the fit and the checks that say whether to trust it belong together.

Output: one row per tumor, see ``EXPECTED_SCHEMA``. ``*_fraction`` columns are
fractions (0 to 1), the unit PURPLE writes even where its key says Percent.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_TSV = {"infer_schema_length": 0}

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="purity",
        glob_pattern="**/purple/*.purple.purity.tsv",
        format="tsv",
        read_kwargs=_TSV,
        source_path="source_path",
    ),
    RecipeSource(
        ref="qc",
        glob_pattern="**/purple/*.purple.qc",
        format="tsv",
        read_kwargs={**_TSV, "has_header": False, "new_columns": ["key", "value"]},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "purity": pl.Float64,
    "ploidy": pl.Float64,
    "fit_status": pl.Utf8,
    "sex": pl.Utf8,
    "whole_genome_duplication": pl.Boolean,
    "ms_indels_per_mb": pl.Float64,
    "ms_status": pl.Utf8,
    "tmb_per_mb": pl.Float64,
    "tmb_status": pl.Utf8,
    "tml": pl.Int64,
    "tml_status": pl.Utf8,
    "sv_tmb": pl.Int64,
    "diploid_fraction": pl.Float64,
    "polyclonal_fraction": pl.Float64,
    "min_purity": pl.Float64,
    "max_purity": pl.Float64,
    "min_ploidy": pl.Float64,
    "max_ploidy": pl.Float64,
    "fit_score": pl.Float64,
    "run_mode": pl.Utf8,
    "qc_status": pl.Utf8,
    "fit_method": pl.Utf8,
    "cn_segments": pl.Int64,
    "unsupported_cn_segments": pl.Int64,
    "deleted_genes": pl.Int64,
    "contamination": pl.Float64,
    "germline_aberrations": pl.Utf8,
    "amber_mean_depth": pl.Int64,
    "loh_fraction": pl.Float64,
    "tinc_level": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_SAMPLE_RE = r"([^/]+)\.purple\.(?:purity\.tsv|qc)$"

#: purity.tsv column -> (output column, dtype)
_PURITY_COLUMNS: dict[str, tuple[str, type[pl.DataType]]] = {
    "purity": ("purity", pl.Float64),
    "ploidy": ("ploidy", pl.Float64),
    "status": ("fit_status", pl.Utf8),
    "gender": ("sex", pl.Utf8),
    "msIndelsPerMb": ("ms_indels_per_mb", pl.Float64),
    "msStatus": ("ms_status", pl.Utf8),
    "tmbPerMb": ("tmb_per_mb", pl.Float64),
    "tmbStatus": ("tmb_status", pl.Utf8),
    "tml": ("tml", pl.Int64),
    "tmlStatus": ("tml_status", pl.Utf8),
    "svTumorMutationalBurden": ("sv_tmb", pl.Int64),
    "diploidProportion": ("diploid_fraction", pl.Float64),
    "polyclonalProportion": ("polyclonal_fraction", pl.Float64),
    "minPurity": ("min_purity", pl.Float64),
    "maxPurity": ("max_purity", pl.Float64),
    "minPloidy": ("min_ploidy", pl.Float64),
    "maxPloidy": ("max_ploidy", pl.Float64),
    "score": ("fit_score", pl.Float64),
    "runMode": ("run_mode", pl.Utf8),
}

#: purple.qc key -> (output column, dtype)
_QC_KEYS: dict[str, tuple[str, type[pl.DataType]]] = {
    "QCStatus": ("qc_status", pl.Utf8),
    "Method": ("fit_method", pl.Utf8),
    "CopyNumberSegments": ("cn_segments", pl.Int64),
    "UnsupportedCopyNumberSegments": ("unsupported_cn_segments", pl.Int64),
    "DeletedGenes": ("deleted_genes", pl.Int64),
    "Contamination": ("contamination", pl.Float64),
    "GermlineAberrations": ("germline_aberrations", pl.Utf8),
    "AmberMeanDepth": ("amber_mean_depth", pl.Int64),
    "LohPercent": ("loh_fraction", pl.Float64),
    "TincLevel": ("tinc_level", pl.Float64),
}


def _cast(name: str, dtype: type[pl.DataType]) -> pl.Expr:
    col = pl.col(name).cast(pl.Utf8).str.strip_chars()
    if dtype == pl.Int64:
        return col.cast(pl.Float64, strict=False).round(0).cast(pl.Int64)
    return col.cast(dtype, strict=False)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    purity = sources["purity"].with_columns(
        pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample")
    )
    for raw in _PURITY_COLUMNS:
        if raw not in purity.columns:
            purity = purity.with_columns(pl.lit(None, pl.Utf8).alias(raw))
    wgd = pl.col("wholeGenomeDuplication") if "wholeGenomeDuplication" in purity.columns else None
    fit = purity.select(
        pl.col("sample"),
        *[_cast(raw, dtype).alias(out) for raw, (out, dtype) in _PURITY_COLUMNS.items()],
        (
            wgd.cast(pl.Utf8).str.to_lowercase() == "true"
            if wgd is not None
            else pl.lit(None, pl.Boolean)
        ).alias("whole_genome_duplication"),
    )

    qc_long = (
        sources["qc"]
        .with_columns(pl.col("source_path").str.extract(_SAMPLE_RE, 1).alias("sample"))
        .filter(pl.col("key").is_in(list(_QC_KEYS)))
        .select("sample", "key", pl.col("value").cast(pl.Utf8))
    )
    qc = qc_long.pivot(on="key", index="sample", values="value", aggregate_function="first")
    for raw in _QC_KEYS:
        if raw not in qc.columns:
            qc = qc.with_columns(pl.lit(None, pl.Utf8).alias(raw))
    qc = qc.select(
        "sample", *[_cast(raw, dtype).alias(out) for raw, (out, dtype) in _QC_KEYS.items()]
    )

    return (
        fit.join(qc, on="sample", how="left")
        .filter(pl.col("sample").is_not_null())
        .select(list(EXPECTED_SCHEMA))
        .sort("sample")
    )
