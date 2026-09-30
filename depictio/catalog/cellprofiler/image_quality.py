"""Image quality of every analysed site, one row per site and channel.

CellProfiler's analysis pipeline runs MeasureImageQuality on every raw channel
of every site and writes the result to ``Image.csv`` next to the object tables:
the focus score (blur), the power log-log slope (a scale-free blur measure,
more negative is blurrier), the share of saturated pixels and the intensity
statistics. Those are the numbers a screening lab reads to drop out-of-focus or
saturated fields before profiling, so this recipe reshapes them long (one row
per site and channel) for box plots per channel and a per-site table.

The plate, well and site come from the ``Metadata_Plate`` / ``Metadata_Well``
/ ``Metadata_Site`` columns CellProfiler writes from the load_data CSV; the
channel is the suffix of the ``ImageQuality_<Measure>_Orig<Channel>`` columns.
Duplicate (plate, well, site, channel) rows keep the first file read.

Layout note: nf-core/cellpainting documents one ``Image.csv`` per site
(``cellprofiler/analysis/<batch>_<plate>_<well>_<site>/``). A run that publishes
the analysis step flat (``cellprofiler/analysis/analysis/``) keeps only the last
site written, so this table then holds that single site. The template declares
it optional.

Output schema:
    site_id : Utf8               ``<plate>_<well>_s<site>``
    well_id : Utf8               ``<plate>_<well>``
    plate : Utf8                 plate barcode
    well : Utf8                  well, row letter + two-digit column
    site : Int64                 imaging site
    channel : Utf8               raw channel name (DNA, ER, RNA, AGP, Mito, ...)
    focus_score : Float64        normalised variance focus score
    power_log_log_slope : Float64  slope of the power spectrum, more negative is blurrier
    percent_saturated : Float64  share of pixels at the maximum intensity, %
    mean_intensity : Float64     mean pixel intensity, 0..1
    cells_on_site : Int64        cells segmented on the site (Count_Cells)
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="images",
        glob_pattern="**/cellprofiler/analysis/**/Image.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "site_id": pl.Utf8,
    "well_id": pl.Utf8,
    "plate": pl.Utf8,
    "well": pl.Utf8,
    "site": pl.Int64,
    "channel": pl.Utf8,
    "focus_score": pl.Float64,
    "power_log_log_slope": pl.Float64,
    "percent_saturated": pl.Float64,
    "mean_intensity": pl.Float64,
    "cells_on_site": pl.Int64,
}

#: ImageQuality measure -> output column.
MEASURES: dict[str, str] = {
    "FocusScore": "focus_score",
    "PowerLogLogSlope": "power_log_log_slope",
    "PercentMaximal": "percent_saturated",
    "MeanIntensity": "mean_intensity",
}
_COLUMN = re.compile(r"^ImageQuality_(?P<measure>[A-Za-z]+)_Orig(?P<channel>[A-Za-z0-9_]+)$")


def normalise_well(well: str | None) -> str | None:
    """``a3`` / ``A3`` / ``A003`` -> ``A03``; anything else is returned upper-cased."""
    if well is None:
        return None
    match = re.fullmatch(r"([A-Za-z]{1,2})0*(\d{1,3})", well.strip())
    if not match:
        return well.strip().upper()
    return f"{match.group(1).upper()}{int(match.group(2)):02d}"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    images = sources["images"]
    missing = [
        c for c in ("Metadata_Plate", "Metadata_Well", "Metadata_Site") if c not in images.columns
    ]
    if missing:
        raise ValueError(f"CellProfiler Image.csv lacks {missing}; cannot place the sites")
    picked: dict[str, tuple[str, str]] = {}
    for name in images.columns:
        match = _COLUMN.match(name)
        if match and match.group("measure") in MEASURES:
            picked[name] = (match.group("channel"), MEASURES[match.group("measure")])
    if not picked:
        raise ValueError(
            "CellProfiler Image.csv has no ImageQuality_<Measure>_Orig<Channel> column"
        )

    count = pl.col("Count_Cells") if "Count_Cells" in images.columns else pl.lit(None)
    base = images.select(
        pl.col("Metadata_Plate").cast(pl.Utf8).alias("plate"),
        pl.col("Metadata_Well")
        .cast(pl.Utf8)
        .map_elements(normalise_well, return_dtype=pl.Utf8)
        .alias("well"),
        pl.col("Metadata_Site").cast(pl.Float64).cast(pl.Int64).alias("site"),
        count.cast(pl.Float64).cast(pl.Int64).alias("cells_on_site"),
        *[pl.col(name) for name in picked],
    ).unique(subset=["plate", "well", "site"], keep="first", maintain_order=True)

    long = base.unpivot(
        index=["plate", "well", "site", "cells_on_site"],
        on=list(picked),
        variable_name="column",
        value_name="value",
    ).with_columns(
        pl.col("column").replace_strict({k: v[0] for k, v in picked.items()}).alias("channel"),
        pl.col("column").replace_strict({k: v[1] for k, v in picked.items()}).alias("measure"),
        pl.col("value").cast(pl.Float64, strict=False),
    )
    wide = long.pivot(
        on="measure",
        index=["plate", "well", "site", "cells_on_site", "channel"],
        values="value",
        aggregate_function="first",
    )
    for column in MEASURES.values():
        if column not in wide.columns:
            wide = wide.with_columns(pl.lit(None, dtype=pl.Float64).alias(column))
    wide = wide.with_columns(
        (pl.col("plate") + "_" + pl.col("well")).alias("well_id"),
        (pl.col("plate") + "_" + pl.col("well") + "_s" + pl.col("site").cast(pl.Utf8)).alias(
            "site_id"
        ),
    )
    return wide.select([pl.col(name).cast(dtype) for name, dtype in EXPECTED_SCHEMA.items()]).sort(
        ["plate", "well", "site", "channel"]
    )
