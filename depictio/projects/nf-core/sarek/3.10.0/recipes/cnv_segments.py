"""CNVkit copy-number segments and bins, one profile per calling unit.

Reads the CNVkit files sarek publishes under ``variant_calling/cnvkit/<unit>/`` and
returns the canonical ``cnv_profile`` table (``depictio.recipes.lib.cnv_profile``: the
columns the advanced viz binds, bins as points and segments as strokes) plus the identity
of the unit: a normal sample (germline), a tumour on its own (tumour-only), or a pair
(``<tumour>_vs_<normal>``). It overrides the catalog's ``cnvkit/cnv_profile`` only to add
that identity; the file formats are the same.

Which segment file speaks for a unit: sarek publishes the called segments three ways,
``<s>.somatic.call.cns`` (a pair), ``<s>.germline.call.cns`` (a sample called on its own)
and a plain ``<s>.call.cns``. The first present wins, in that order, and ``call_source``
says which; the `.cns` of segmentation and the bintest are not read. ``sample`` is the
tumour of a pair, so the sample filters reach it; ``unit`` keeps the pair's name.

log2 ratios are floored at -3 (``depictio.recipes.lib.cnv_profile.LOG2_FLOOR``): CNVkit
writes -20 for a bin with no coverage, which would flatten every other bin on the axis.

A run without CNVkit has no such files, so the collection is skipped and the Copy number
tab does not draw a profile.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.cnv_profile import (
    BIN_ROW,
    CNV_PROFILE_COLUMNS,
    CNV_PROFILE_SCHEMA,
    LOG2_FLOOR,
    SEGMENT_ROW,
    decimate_bins,
)
from depictio.recipes.lib.sarek_units import PAIRED, TUMOUR_ONLY, unit_frame

_RAW_COLUMNS = {
    "chromosome": pl.Utf8,
    "start": pl.Utf8,
    "end": pl.Utf8,
    "log2": pl.Utf8,
    "source_path": pl.Utf8,
}

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(ref="segments", dc_ref="cnvkit_segments_raw", input_schema=dict(_RAW_COLUMNS)),
    RecipeSource(
        ref="bins", dc_ref="cnvkit_bins_raw", optional=True, input_schema=dict(_RAW_COLUMNS)
    ),
    RecipeSource(
        ref="hub",
        dc_ref="samples",
        input_schema={"sample_id": pl.Utf8, "patient": pl.Utf8, "status": pl.Int64},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    **CNV_PROFILE_SCHEMA,
    "unit": pl.Utf8,
    "unit_type": pl.Utf8,
    "patient": pl.Utf8,
    "normal": pl.Utf8,
    "call_source": pl.Utf8,
}

#: `variant_calling/cnvkit/<unit>/<file>`: the unit is the folder.
_UNIT_RE = r"cnvkit/([^/]+)/[^/]*$"
#: The called-segment files, most specific first.
_CALL_SOURCES = ("somatic", "germline", "call")
_CNVKIT_GENE_FILLER = ["-", ".", "", "Antitarget", "Background"]
#: Row order by unit type: the profile opens on the first sample it sees, which
#: should be a tumour against its normal rather than the normal on its own.
_UNIT_ORDER = {PAIRED: 0, TUMOUR_ONLY: 1}


def _call_source() -> pl.Expr:
    path = pl.col("source_path")
    return (
        pl.when(path.str.ends_with(".somatic.call.cns"))
        .then(pl.lit("somatic"))
        .when(path.str.ends_with(".germline.call.cns"))
        .then(pl.lit("germline"))
        .otherwise(pl.lit("call"))
    )


def _numeric(df: pl.DataFrame, name: str, dtype: type[pl.DataType]) -> pl.Expr:
    if name in df.columns:
        return pl.col(name).cast(dtype, strict=False)
    return pl.lit(None, dtype=dtype)


def _frame(df: pl.DataFrame, row_type: str) -> pl.DataFrame:
    """A raw CNVkit frame in canonical columns, `sample` still the unit's folder."""
    gene = pl.col("gene").cast(pl.Utf8) if "gene" in df.columns else pl.lit(None, dtype=pl.Utf8)
    cn = _numeric(df, "cn", pl.Int64)
    label = (
        pl.concat_str([pl.lit("CN "), cn.cast(pl.Utf8)])
        if row_type == SEGMENT_ROW and "cn" in df.columns
        else pl.when(gene.is_in(_CNVKIT_GENE_FILLER)).then(None).otherwise(gene)
    )
    return df.select(
        pl.col("source_path").str.extract(_UNIT_RE, 1).alias("unit"),
        pl.col("chromosome").cast(pl.Utf8).alias("chrom"),
        _numeric(df, "start", pl.Int64).alias("start"),
        _numeric(df, "end", pl.Int64).alias("end"),
        _numeric(df, "log2", pl.Float64).clip(lower_bound=LOG2_FLOOR).alias("log2"),
        _numeric(df, "baf", pl.Float64).alias("baf"),
        (cn if row_type == SEGMENT_ROW else pl.lit(None, dtype=pl.Int64)).alias("copy_number"),
        pl.lit(row_type).alias("segment"),
        label.alias("label"),
        _numeric(df, "depth", pl.Float64).alias("depth"),
        (_call_source() if row_type == SEGMENT_ROW else pl.lit("bins")).alias("call_source"),
    ).with_columns(pl.col("unit").alias("sample"))


def _best_call_file(segments: pl.DataFrame) -> pl.DataFrame:
    """Per unit, the rows of its most specific called-segment file."""
    rank = pl.col("call_source").replace_strict(
        {name: i for i, name in enumerate(_CALL_SOURCES)}, default=len(_CALL_SOURCES)
    )
    return (
        segments.with_columns(rank.alias("_rank"))
        .filter(pl.col("_rank") == pl.col("_rank").min().over("unit"))
        .drop("_rank")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """The unit's segments and bins in canonical cnv_profile columns, plus who the unit is."""
    called = sources["segments"].filter(pl.col("source_path").str.ends_with(".call.cns"))
    segments = _best_call_file(_frame(called, SEGMENT_ROW).filter(pl.col("unit").is_not_null()))

    raw_bins = sources.get("bins")
    bins = pl.DataFrame(schema=segments.schema)
    if raw_bins is not None and not raw_bins.is_empty():
        cnr = raw_bins.filter(pl.col("source_path").str.ends_with(".cnr"))
        # `decimate_bins` groups on `sample`, which is still the unit's folder here, and
        # keeps the canonical columns only: the unit comes back from `sample`.
        bins = decimate_bins(
            _frame(cnr, BIN_ROW).filter(pl.col("unit").is_not_null())
        ).with_columns(pl.col("sample").alias("unit"), pl.lit("bins").alias("call_source"))

    profile = pl.concat([segments, bins], how="diagonal_relaxed").filter(
        pl.col("chrom").is_not_null() & pl.col("start").is_not_null() & pl.col("log2").is_not_null()
    )
    if segments.is_empty():
        raise ValueError(
            "sarek cnv_segments: no CNVkit called segments (variant_calling/cnvkit/<unit>/"
            "<unit>.call.cns) among the run's files"
        )

    units = unit_frame(profile["unit"], sources.get("hub")).select(
        "unit", "unit_type", "patient", pl.col("sample").alias("_sample"), "normal"
    )
    return (
        profile.drop("sample")
        .join(units, on="unit", how="left")
        .rename({"_sample": "sample"})
        .select([*CNV_PROFILE_COLUMNS, "unit", "unit_type", "patient", "normal", "call_source"])
        .sort(
            [
                pl.col("unit_type").replace_strict(_UNIT_ORDER, default=2),
                "unit",
                "segment",
                "chrom",
                "start",
            ]
        )
    )
