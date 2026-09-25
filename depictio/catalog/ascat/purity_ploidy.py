"""ASCAT's tumour purity and ploidy estimate, one row per sample.

The nf-core module writes ``<sample>.purityploidy.txt``, tab separated with a
header row and a single data row (ASCAT documentation, ``ascat.output``)::

    AberrantCellFraction  Ploidy

``AberrantCellFraction`` is the tumour purity, the share of the sequenced cells
that carry the tumour genome; ``Ploidy`` is the average copy number of the
tumour genome, which is the baseline every log2 ratio in a copy-number profile
is implicitly read against. Both belong on the profile tab as cards: a log2
track from a 20 percent pure sample is a flattened version of the same biology,
and saying so next to the plot is what stops the reader under-calling it.

Neither file carries a sample column, so the raw data collection is a **scan**
(``include_file_paths``) and the sample is recovered from the
``variant_calling/ascat/<sample>/`` directory nf-core/sarek publishes into.

A template reusing this recipe declares one raw scan data collection::

    # ascat_purityploidy_raw
    regex_config: {pattern: 'variant_calling/ascat/[^/]+/[^/]+\\.purityploidy\\.txt$'}
    dc_specific_properties:
      format: CSV
      polars_kwargs: {separator: "\\t", include_file_paths: source_path}

Output schema:
    sample : Utf8      tumour sample the estimate belongs to
    purity : Float64   aberrant cell fraction, 0 to 1
    ploidy : Float64   average copy number of the tumour genome
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

PURITY_PLOIDY_DC_TAG = "ascat_purityploidy_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="purityploidy", dc_ref=PURITY_PLOIDY_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "purity": pl.Float64,
    "ploidy": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

#: nf-core/sarek writes `variant_calling/ascat/<sample>/<sample>.purityploidy.txt`.
_SAMPLE_RE = r"ascat/([^/]+)/[^/]*$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per sample: purity and ploidy, named as a reader would name them."""
    df = sources["purityploidy"]

    missing = [c for c in ("AberrantCellFraction", "Ploidy") if c not in df.columns]
    if missing:
        raise ValueError(
            f"ascat_purity_ploidy: the .purityploidy.txt input lacks columns {missing}; "
            f"got {df.columns}"
        )
    if "sample" not in df.columns and "source_path" not in df.columns:
        raise ValueError(
            "ascat_purity_ploidy: the input has neither a 'sample' nor a 'source_path' "
            "column, so the raw data collection must be scanned with "
            "polars_kwargs.include_file_paths"
        )

    sample = (
        pl.col("sample").cast(pl.Utf8)
        if "sample" in df.columns
        else pl.col("source_path").str.extract(_SAMPLE_RE, 1).cast(pl.Utf8)
    )
    return (
        df.select(
            sample.alias("sample"),
            pl.col("AberrantCellFraction").cast(pl.Float64, strict=False).alias("purity"),
            pl.col("Ploidy").cast(pl.Float64, strict=False).alias("ploidy"),
        )
        .filter(pl.col("sample").is_not_null())
        .sort("sample")
    )
