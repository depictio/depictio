"""CNVkit bins and segments folded into one canonical ``cnv_profile`` table.

CNVkit publishes the evidence and the call in two files per sample, both
tab-separated with a header row (CNVkit "File formats" documentation):

``<sample>.cnr`` - copy ratios, one row per bin::

    chromosome  start  end  gene  depth  log2  weight

``<sample>.cns`` / ``<sample>.call.cns`` - copy number segments::

    chromosome  start  end  gene  log2  depth  probes  weight

``cnvkit call`` adds the absolute-copy-number columns to the segment file:
``cn`` (total), ``cn1`` / ``cn2`` (allele-specific) and ``baf`` (the
B-allele frequency of the segment) when a VCF of SNV sites was supplied.
Neither file carries a sample column, so both raw data collections are
**scans** (``include_file_paths``) and the sample is recovered from the
``variant_calling/cnvkit/<sample>/`` directory nf-core/sarek publishes into.

A template reusing this recipe declares two raw scan data collections::

    # cnvkit_bins_raw
    regex_config: {pattern: 'variant_calling/cnvkit/[^/]+/[^/]+\\.cnr$'}
    dc_specific_properties:
      format: CSV
      polars_kwargs: {separator: "\\t", include_file_paths: source_path}

    # cnvkit_segments_raw (.call.cns preferred, .cns accepted)
    regex_config: {pattern: 'variant_calling/cnvkit/[^/]+/[^/]+\\.cns$'}
    dc_specific_properties:
      format: CSV
      polars_kwargs: {separator: "\\t", include_file_paths: source_path}

Both are ``optional: true`` on a germline-only run, which publishes no
``variant_calling/cnvkit/`` directory at all.

Output schema: the canonical cnv_profile contract, see
``depictio/recipes/lib/cnv_profile.py``. Bins carry ``segment = "bin"``,
segments carry ``segment = "segment"``, and the gene annotation CNVkit writes
on both becomes the hover ``label``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.cnv_profile import (
    BIN_ROW,
    CNV_PROFILE_SCHEMA,
    SEGMENT_ROW,
    decimate_bins,
    finalise,
)

BINS_DC_TAG = "cnvkit_bins_raw"
SEGMENTS_DC_TAG = "cnvkit_segments_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="bins", dc_ref=BINS_DC_TAG, optional=True),
    RecipeSource(ref="segments", dc_ref=SEGMENTS_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = CNV_PROFILE_SCHEMA
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

#: nf-core/sarek writes `variant_calling/cnvkit/<sample>/<sample>.cnr`.
_SAMPLE_RE = r"cnvkit/([^/]+)/[^/]*$"

#: CNVkit writes this placeholder in the gene column of an intergenic bin.
_NO_GENE = {"-", "", "Antitarget", "Background"}


def _sample(df: pl.DataFrame) -> pl.Expr:
    """The sample id, from a sample column when present, else the path."""
    if "sample" in df.columns:
        return pl.col("sample").cast(pl.Utf8)
    return pl.col("source_path").str.extract(_SAMPLE_RE, 1).cast(pl.Utf8)


def _label() -> pl.Expr:
    """CNVkit's gene annotation, blanked when it is the intergenic filler."""
    gene = pl.col("gene").cast(pl.Utf8)
    return pl.when(gene.is_in(list(_NO_GENE))).then(None).otherwise(gene).alias("label")


def _depth(df: pl.DataFrame) -> pl.Expr:
    """CNVkit's per-row depth, null when the file does not carry the column."""
    if "depth" in df.columns:
        return pl.col("depth").cast(pl.Float64, strict=False).alias("depth")
    return pl.lit(None, dtype=pl.Float64).alias("depth")


def _require_path(df: pl.DataFrame, ref: str) -> None:
    if "sample" not in df.columns and "source_path" not in df.columns:
        raise ValueError(
            f"cnvkit_cnv_profile: the '{ref}' input has neither a 'sample' nor a "
            "'source_path' column, so the raw data collection must be scanned with "
            "polars_kwargs.include_file_paths"
        )


def _bins(df: pl.DataFrame) -> pl.DataFrame:
    _require_path(df, "bins")
    missing = {"chromosome", "start", "end", "log2"} - set(df.columns)
    if missing:
        raise ValueError(f"cnvkit_cnv_profile: the .cnr input lacks columns {sorted(missing)}")
    out = df.select(
        _sample(df).alias("sample"),
        pl.col("chromosome").cast(pl.Utf8).alias("chrom"),
        pl.col("start").cast(pl.Int64, strict=False).alias("start"),
        pl.col("end").cast(pl.Int64, strict=False).alias("end"),
        pl.col("log2").cast(pl.Float64, strict=False).alias("log2"),
        pl.lit(None, dtype=pl.Float64).alias("baf"),
        pl.lit(None, dtype=pl.Int64).alias("copy_number"),
        pl.lit(BIN_ROW).alias("segment"),
        (_label() if "gene" in df.columns else pl.lit(None, dtype=pl.Utf8).alias("label")),
        _depth(df),
    )
    return decimate_bins(out)


def _segments(df: pl.DataFrame) -> pl.DataFrame:
    _require_path(df, "segments")
    missing = {"chromosome", "start", "end", "log2"} - set(df.columns)
    if missing:
        raise ValueError(f"cnvkit_cnv_profile: the .cns input lacks columns {sorted(missing)}")
    has_cn = "cn" in df.columns
    has_baf = "baf" in df.columns
    # `cnvkit call` writes the absolute copy number and, with a SNV VCF, the
    # segment BAF. A plain `cnvkit segment` run has neither, and the segment
    # still draws from its log2 alone.
    copy_number = (
        pl.col("cn").cast(pl.Int64, strict=False) if has_cn else pl.lit(None, dtype=pl.Int64)
    )
    baf = (
        pl.col("baf").cast(pl.Float64, strict=False) if has_baf else pl.lit(None, dtype=pl.Float64)
    )
    label = (
        pl.concat_str([pl.lit("CN "), pl.col("cn").cast(pl.Utf8)])
        if has_cn
        else (_label() if "gene" in df.columns else pl.lit(None, dtype=pl.Utf8))
    )
    return df.select(
        _sample(df).alias("sample"),
        pl.col("chromosome").cast(pl.Utf8).alias("chrom"),
        pl.col("start").cast(pl.Int64, strict=False).alias("start"),
        pl.col("end").cast(pl.Int64, strict=False).alias("end"),
        pl.col("log2").cast(pl.Float64, strict=False).alias("log2"),
        baf.alias("baf"),
        copy_number.alias("copy_number"),
        pl.lit(SEGMENT_ROW).alias("segment"),
        label.alias("label"),
        _depth(df),
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Fold the .cnr bins and the .cns segments into one long table."""
    bins = sources.get("bins")
    segments = sources.get("segments")
    if (bins is None or bins.height == 0) and (segments is None or segments.height == 0):
        raise ValueError(
            "cnvkit_cnv_profile: neither the .cnr bins nor the .cns segments resolved; "
            "this recipe needs at least one of the two CNVkit outputs"
        )

    frames: list[pl.DataFrame] = []
    if bins is not None and bins.height:
        frames.append(_bins(bins))
    if segments is not None and segments.height:
        frames.append(_segments(segments))

    # No log2 is derived here: CNVkit publishes it directly, on both files.
    # `finalise` casts to the canonical dtypes and drops anything unparseable.
    return finalise(pl.concat(frames, how="diagonal_relaxed"))
