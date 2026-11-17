"""MSIsensor-pro microsatellite instability, one row per tumour/normal pair.

sarek runs MSIsensor-pro on a pair and publishes its summary as a file named after the
pair, ``variant_calling/msisensorpro/<tumour>_vs_<normal>/<tumour>_vs_<normal>``, beside
the ``_dis``, ``_germline`` and ``_somatic`` site tables. The summary is one tab-separated
row::

    Total_Number_of_Sites  Number_of_Unstable_Sites  %

The score is the ``%`` column: the share of the microsatellite sites that are unstable in
the tumour against the normal. No cut-off is applied here; the tools publish none with the
number, and the right one depends on the assay.

The raw scan (``msisensorpro_raw``) matches the summary file by its name (the folder's
name repeated), so the site tables are not read. A run without a pair, or without
MSIsensor-pro in ``--tools``, has no such file: the collection is skipped.

Output schema:
    unit : Utf8              `<tumour>_vs_<normal>`
    unit_type : Utf8         paired (a unit that is not a pair keeps its own type)
    patient : Utf8           the patient (from the hub)
    sample : Utf8            the tumour sample
    normal : Utf8            the pair's normal sample
    total_sites : Int64      microsatellite sites evaluated
    unstable_sites : Int64   sites that are unstable
    msi_score : Float64      share of unstable sites, in percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sarek_units import unit_frame

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="raw",
        dc_ref="msisensorpro_raw",
        input_schema={
            "Total_Number_of_Sites": pl.Utf8,
            "Number_of_Unstable_Sites": pl.Utf8,
            "%": pl.Utf8,
            "source_path": pl.Utf8,
        },
    ),
    RecipeSource(
        ref="hub",
        dc_ref="samples",
        input_schema={"sample_id": pl.Utf8, "patient": pl.Utf8, "status": pl.Int64},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "unit": pl.Utf8,
    "unit_type": pl.Utf8,
    "patient": pl.Utf8,
    "sample": pl.Utf8,
    "normal": pl.Utf8,
    "total_sites": pl.Int64,
    "unstable_sites": pl.Int64,
    "msi_score": pl.Float64,
}

#: `variant_calling/msisensorpro/<unit>/<unit>`: the unit is the folder.
_UNIT_RE = r"msisensorpro/([^/]+)/[^/]*$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per MSIsensor-pro summary, with the pair it was run on."""
    raw = sources["raw"]
    scores = raw.select(
        pl.col("source_path").str.extract(_UNIT_RE, 1).alias("unit"),
        pl.col("Total_Number_of_Sites").cast(pl.Int64, strict=False).alias("total_sites"),
        pl.col("Number_of_Unstable_Sites").cast(pl.Int64, strict=False).alias("unstable_sites"),
        pl.col("%").cast(pl.Float64, strict=False).alias("msi_score"),
    ).filter(pl.col("unit").is_not_null() & pl.col("msi_score").is_not_null())
    if scores.is_empty():
        raise ValueError(
            "sarek msi: no MSIsensor-pro summary (variant_calling/msisensorpro/<pair>/<pair>) "
            "among the run's files"
        )
    units = unit_frame(scores["unit"], sources.get("hub"))
    return (
        scores.unique(subset="unit", keep="first")
        .join(units, on="unit", how="left")
        .select(list(OUTPUT_SCHEMA))
        .sort("unit")
    )
