"""One row per library pooling the numbers an ancient-DNA library is judged on.

eager publishes each signal from a different tool: endorS.py for endogenous
DNA, Picard MarkDuplicates for clonality, Qualimap BamQC for depth, mapping
quality, error rate and GC, DamageProfiler for terminal deamination and
fragment length. Each lands in its own tidied collection keyed on the library
id (``sample``). This recipe joins those four collections so two figures can
read them together:

* the endogenous DNA against clonality plane (a library worth sequencing
  deeper sits high on endogenous and low on duplication), and
* the per-library QC profile (``parallel_coordinates``), one polyline per
  library across every metric.

The endogenous collection gives the library list and is the only required
input; the other three are left-joined on ``sample``, so a library missing
from one tool keeps its row with nulls in that tool's columns and a partial
run still draws what it has.

Output schema:
    sample : Utf8                 library id (the samplesheet's Library_ID)
    endogenous_dna : Float64      mapped over input reads, percent (endorS.py)
    endogenous_dna_post : Float64 the same after the quality filter and deduplication, percent
    clonality_pct : Float64       Picard duplicate fraction, as a percent
    mean_coverage : Float64       mean depth over the reference, X (Qualimap)
    mean_mapping_quality : Float64 mean MAPQ of mapped reads (Qualimap)
    error_rate_pct : Float64      mismatches over mapped bases, as a percent (Qualimap)
    gc_percentage : Float64       GC content of mapped bases, percent (Qualimap)
    ct_5p_first_pct : Float64     C to T at the first 5 prime base, as a percent (DamageProfiler)
    mean_length : Float64         mean mapped fragment length, bp (DamageProfiler)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

ENDOGENOUS_DC_TAG = "endorspy_endogenous"
DEDUP_DC_TAG = "picard_markduplicates_metrics"
BAMQC_DC_TAG = "qualimap_bamqc_genome_results"
DAMAGE_DC_TAG = "damageprofiler_authenticity"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="endogenous", dc_ref=ENDOGENOUS_DC_TAG),
    RecipeSource(ref="dedup", dc_ref=DEDUP_DC_TAG, optional=True),
    RecipeSource(ref="bamqc", dc_ref=BAMQC_DC_TAG, optional=True),
    RecipeSource(ref="damage", dc_ref=DAMAGE_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "endogenous_dna": pl.Float64,
    "endogenous_dna_post": pl.Float64,
    "clonality_pct": pl.Float64,
    "mean_coverage": pl.Float64,
    "mean_mapping_quality": pl.Float64,
    "error_rate_pct": pl.Float64,
    "gc_percentage": pl.Float64,
    "ct_5p_first_pct": pl.Float64,
    "mean_length": pl.Float64,
}

_RECIPE = "eager_library_qc"

#: (source ref, {output column: expression over that source}) in output order.
_PICKS: list[tuple[str, dict[str, pl.Expr]]] = [
    (
        "dedup",
        {"clonality_pct": pl.col("percent_duplication").cast(pl.Float64) * 100.0},
    ),
    (
        "bamqc",
        {
            "mean_coverage": pl.col("mean_coverage").cast(pl.Float64),
            "mean_mapping_quality": pl.col("mean_mapping_quality").cast(pl.Float64),
            "error_rate_pct": pl.col("general_error_rate").cast(pl.Float64) * 100.0,
            "gc_percentage": pl.col("gc_percentage").cast(pl.Float64),
        },
    ),
    (
        "damage",
        {
            "ct_5p_first_pct": pl.col("ct_5p_first").cast(pl.Float64) * 100.0,
            "mean_length": pl.col("mean_length").cast(pl.Float64),
        },
    ),
]


def _per_sample(frame: pl.DataFrame | None, columns: dict[str, pl.Expr]) -> pl.DataFrame:
    """``sample`` plus the picked columns, one row per sample (first wins), or an empty frame."""
    schema = {"sample": pl.Utf8, **{name: pl.Float64 for name in columns}}
    if frame is None or frame.is_empty() or "sample" not in frame.columns:
        return pl.DataFrame(schema=schema)
    return (
        frame.select(pl.col("sample").cast(pl.Utf8), *[e.alias(n) for n, e in columns.items()])
        .drop_nulls("sample")
        .unique(subset="sample", keep="first", maintain_order=True)
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Join the four per-library collections on ``sample``."""
    endogenous = sources.get("endogenous")
    if endogenous is None or endogenous.is_empty():
        raise ValueError(f"{_RECIPE}: the endogenous DNA collection is empty")

    out = _per_sample(
        endogenous,
        {
            "endogenous_dna": pl.col("endogenous_dna").cast(pl.Float64),
            "endogenous_dna_post": pl.col("endogenous_dna_post").cast(pl.Float64),
        },
    )
    for ref, columns in _PICKS:
        out = out.join(_per_sample(sources.get(ref), columns), on="sample", how="left")

    return out.select([pl.col(name).cast(dtype) for name, dtype in EXPECTED_SCHEMA.items()]).sort(
        "sample"
    )
