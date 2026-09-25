"""ASCAT allele-specific segments as a canonical ``cnv_profile`` table.

ASCAT calls absolute, allele-specific copy number: every segment gets a major
and a minor allele count rather than a ratio. The nf-core module writes
``ascat.output$segments`` to ``<sample>.cnvs.txt``, tab separated with a header
row and one row per segment (ASCAT documentation, "segments")::

    sample  chr  startpos  endpos  nMajor  nMinor

Older ASCAT builds omit the ``sample`` column, so the sample is recovered from
the ``variant_calling/ascat/<sample>/`` directory nf-core/sarek publishes into
when it is absent.

Two derived quantities put allele-specific calls on the same axis as a
ratio-based caller:

* ``log2 = log2((nMajor + nMinor) / 2)``, the copy ratio the segment would show
  against a diploid baseline. A homozygous deletion (total 0) is floored, see
  ``LOG2_FLOOR``.
* ``baf = nMinor / (nMajor + nMinor)``, the expected B-allele frequency of the
  segment. A balanced segment sits at 0.5 and copy-neutral LOH (2+0) drops to
  0, which is exactly the split the renderer's BAF panel exists to show.

A template reusing this recipe declares one raw scan data collection::

    # ascat_segments_raw
    regex_config: {pattern: 'variant_calling/ascat/[^/]+/[^/]+\\.cnvs\\.txt$'}
    dc_specific_properties:
      format: CSV
      polars_kwargs: {separator: "\\t", include_file_paths: source_path}

``optional: true`` on a germline-only run, which publishes no
``variant_calling/ascat/`` directory at all.

Output schema: the canonical cnv_profile contract, see
``depictio/recipes/lib/cnv_profile.py``. Every row is a segment
(``segment = "segment"``); ASCAT publishes no bin-level track of its own, so a
dashboard pairs this with CNVkit or Control-FREEC when it wants the evidence
under the call.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.cnv_profile import (
    CNV_PROFILE_SCHEMA,
    SEGMENT_ROW,
    finalise,
    safe_log2,
)

SEGMENTS_DC_TAG = "ascat_segments_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="segments", dc_ref=SEGMENTS_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = CNV_PROFILE_SCHEMA
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

#: nf-core/sarek writes `variant_calling/ascat/<sample>/<sample>.cnvs.txt`.
_SAMPLE_RE = r"ascat/([^/]+)/[^/]*$"

_REQUIRED = ("chr", "startpos", "endpos", "nMajor", "nMinor")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Turn allele counts into a log2 ratio, a BAF and an absolute copy number."""
    df = sources["segments"]

    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(
            f"ascat_cnv_segments: the .cnvs.txt input lacks columns {missing}; got {df.columns}"
        )
    if "sample" not in df.columns and "source_path" not in df.columns:
        raise ValueError(
            "ascat_cnv_segments: the input has neither a 'sample' nor a 'source_path' "
            "column, so the raw data collection must be scanned with "
            "polars_kwargs.include_file_paths"
        )

    sample = (
        pl.col("sample").cast(pl.Utf8)
        if "sample" in df.columns
        else pl.col("source_path").str.extract(_SAMPLE_RE, 1).cast(pl.Utf8)
    )
    major = pl.col("nMajor").cast(pl.Int64, strict=False)
    minor = pl.col("nMinor").cast(pl.Int64, strict=False)
    total = major + minor

    return finalise(
        df.select(
            sample.alias("sample"),
            pl.col("chr").cast(pl.Utf8).alias("chrom"),
            pl.col("startpos").cast(pl.Int64, strict=False).alias("start"),
            pl.col("endpos").cast(pl.Int64, strict=False).alias("end"),
            safe_log2(total.cast(pl.Float64) / 2.0).alias("log2"),
            # Balanced heterozygosity is 0.5; LOH collapses to 0. A segment with
            # no copies left has no allele fraction to report.
            pl.when(total > 0)
            .then(minor.cast(pl.Float64) / total.cast(pl.Float64))
            .otherwise(None)
            .alias("baf"),
            total.alias("copy_number"),
            pl.lit(SEGMENT_ROW).alias("segment"),
            pl.concat_str([major.cast(pl.Utf8), pl.lit("+"), minor.cast(pl.Utf8)]).alias("label"),
            pl.lit(None, dtype=pl.Float64).alias("depth"),
        )
    )
