"""One row per sarek sample, from the CSV manifests sarek publishes under csv/.

sarek writes its own resume points as CSVs in ``<outdir>/csv/``, and those are
the only sample table every run carries: the samplesheet it was launched with
is not part of the output. Which manifests exist depends on the steps the run
executed, so every source is optional and the first one present wins:

- ``csv/recalibrated.csv``: ``patient,sex,status,sample,cram,crai``, written
  when base recalibration ran;
- ``csv/markduplicates.csv`` / ``csv/markduplicates_no_table.csv``: the same
  first four columns, written after duplicate marking;
- ``csv/variantcalled.csv``: ``patient,sample,variantcaller,vcf``, written
  whenever a caller ran. It carries no sex or status, and on a somatic run its
  paired callers name the pair (``<tumour>_vs_<normal>``) rather than a sample.
  A pair is not a hub row: the callers that ran on it are counted for its
  tumour sample.

``variantcalled.csv`` also gives each sample the number of callers that ran on
it (``n_callers``), whichever manifest supplied the design. The status label
is sarek's convention (0 normal, 1 tumour), the only design factor a sarek
samplesheet carries; nothing is parsed out of the sample names.

``design`` says what the run can say about a patient, from the status of its
samples (``depictio.recipes.lib.sarek_units``): ``Paired`` (a tumour and a
normal), ``Germline only`` (normals, or samples whose status is unknown) or
``Tumour-only`` (tumours alone). Every sample of a patient carries its label,
so one filter keeps or drops the whole patient. The pairs themselves are the
``pairs`` collection.

Output schema:
    sample_id    : Utf8   the key every other collection is linked on
    patient      : Utf8   patient / individual identifier
    sex          : Utf8   as declared in the samplesheet (XX, XY, or NA)
    status       : Int64  0 = normal, 1 = tumour; null when only
                          variantcalled.csv was available
    status_label : Utf8   "Normal", "Tumour" or "Unknown"
    design       : Utf8   the patient's design: "Paired", "Germline only" or "Tumour-only"
    n_callers    : Int64  variant callers that produced a VCF for the sample
                          (a pair's callers count for its tumour)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sarek_units import PAIR_SEP, design_label

_CSV_KWARGS = {"infer_schema_length": 0}

#: Design manifests, most complete first.
_DESIGN_REFS = ("recalibrated", "markduplicates", "markduplicates_no_table")

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    *(
        RecipeSource(
            ref=ref,
            path=f"csv/{ref}.csv",
            format="CSV",
            input_schema={"sample": pl.Utf8},
            read_kwargs=_CSV_KWARGS,
            optional=True,
        )
        for ref in _DESIGN_REFS
    ),
    RecipeSource(
        ref="variantcalled",
        path="csv/variantcalled.csv",
        format="CSV",
        input_schema={"sample": pl.Utf8},
        read_kwargs=_CSV_KWARGS,
        optional=True,
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "patient": pl.Utf8,
    "sex": pl.Utf8,
    "status": pl.Int64,
    "status_label": pl.Utf8,
    "design": pl.Utf8,
    "n_callers": pl.Int64,
}


def _design(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame | None:
    """patient / sex / status / sample from the first design manifest present."""
    for ref in _DESIGN_REFS:
        df = sources.get(ref)
        if df is None or df.is_empty() or "sample" not in df.columns:
            continue
        return df.select(
            pl.col("sample").cast(pl.Utf8).alias("sample_id"),
            (pl.col("patient") if "patient" in df.columns else pl.col("sample"))
            .cast(pl.Utf8)
            .alias("patient"),
            (pl.col("sex") if "sex" in df.columns else pl.lit(None)).cast(pl.Utf8).alias("sex"),
            (pl.col("status") if "status" in df.columns else pl.lit(None))
            .cast(pl.Int64, strict=False)
            .alias("status"),
        ).unique(subset="sample_id", keep="first")
    return None


def _caller_counts(called: pl.DataFrame | None) -> pl.DataFrame | None:
    """Callers per sample from variantcalled.csv; a pair's callers count for its tumour."""
    if called is None or called.is_empty() or "sample" not in called.columns:
        return None
    # `<tumour>_vs_<normal>` -> the tumour; a single sample is its own unit.
    unit = pl.col("sample").cast(pl.Utf8)
    called = called.with_columns(
        unit.str.splitn(PAIR_SEP, 2).struct.field("field_0").alias("sample")
    )
    n_callers = (
        pl.col("variantcaller").n_unique() if "variantcaller" in called.columns else pl.len()
    )
    patient = pl.col("patient") if "patient" in called.columns else pl.col("sample")
    return called.group_by(pl.col("sample").alias("sample_id")).agg(
        n_callers.cast(pl.Int64).alias("n_callers"),
        patient.first().cast(pl.Utf8).alias("patient"),
    )


def _designs(hub: pl.DataFrame) -> pl.DataFrame:
    """patient -> design label, from the status of the patient's samples."""
    rows = [
        {"patient": patient, "design": design_label(group["status"].to_list())}
        for (patient,), group in hub.group_by(["patient"], maintain_order=True)
    ]
    return pl.DataFrame(rows, schema={"patient": pl.Utf8, "design": pl.Utf8})


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """One row per sample, design from the manifests, caller count from variantcalled."""
    callers = _caller_counts(sources.get("variantcalled"))
    design = _design(sources)
    if design is None:
        if callers is None:
            raise ValueError(
                "sarek samples: no csv/recalibrated.csv, csv/markduplicates*.csv or "
                "csv/variantcalled.csv under the data root; sarek writes at least one of them"
            )
        design = callers.select(
            "sample_id",
            "patient",
            pl.lit(None, dtype=pl.Utf8).alias("sex"),
            pl.lit(None, dtype=pl.Int64).alias("status"),
        )

    if callers is not None:
        design = design.join(callers.select("sample_id", "n_callers"), on="sample_id", how="left")
    else:
        design = design.with_columns(pl.lit(None, dtype=pl.Int64).alias("n_callers"))

    design = design.join(_designs(design), on="patient", how="left")

    return (
        design.with_columns(
            pl.col("n_callers").fill_null(0).cast(pl.Int64),
            pl.when(pl.col("status") == 1)
            .then(pl.lit("Tumour"))
            .when(pl.col("status") == 0)
            .then(pl.lit("Normal"))
            .otherwise(pl.lit("Unknown"))
            .alias("status_label"),
        )
        .select(list(OUTPUT_SCHEMA))
        .sort("sample_id")
    )
