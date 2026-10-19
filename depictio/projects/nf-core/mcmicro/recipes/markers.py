"""The marker panel of an nf-core/mcmicro run: one row per channel of the marker sheet.

mcmicro reads the channels of every cycle from ``--marker_sheet``
(``channel_number``, ``cycle_number``, ``marker_name``, and optional
``filter``, ``excitation_wavelength``, ``emission_wavelength``, ``background``,
``exposure``, ``remove``) and does not publish it, so the template reads the
file named by ``MARKER_SHEET`` (by default the copy under ``input/``).

Derived columns:

* ``marker_role``: ``Nuclear stain`` for a DNA / DAPI / Hoechst channel (the
  one segmentation runs on), ``Marker`` otherwise;
* ``status``: ``Removed`` for a channel the sheet marks ``remove`` (background
  subtraction drops it, after using it as another channel's background),
  ``Quantified`` otherwise;
* ``quantified``: 1 for a quantified channel, so a card counts them;
* ``background_subtracted``: 1 when the sheet names a ``background`` channel
  for it.

Output:
    marker_name, marker_role, status, background, filter : Utf8,
    channel_number, cycle_number, quantified, background_subtracted : Int64,
    exposure, excitation_wavelength, emission_wavelength : Float64
"""

from __future__ import annotations

import io
import re

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.mcquant import is_nuclear

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="marker_sheet",
        path="input/markers.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "marker_name": pl.Utf8,
    "channel_number": pl.Int64,
    "cycle_number": pl.Int64,
    "marker_role": pl.Utf8,
    "status": pl.Utf8,
    "quantified": pl.Int64,
    "background": pl.Utf8,
    "background_subtracted": pl.Int64,
    "exposure": pl.Float64,
    "filter": pl.Utf8,
    "excitation_wavelength": pl.Float64,
    "emission_wavelength": pl.Float64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

_REQUIRED = ("channel_number", "cycle_number", "marker_name")
_TRUE = {"true", "yes", "1", "t", "y"}


def _fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    if df.width == 1 and "\t" in df.columns[0]:
        text = "\n".join([df.columns[0]] + [str(v) for v in df[df.columns[0]].to_list()])
        return pl.read_csv(io.StringIO(text), separator="\t", infer_schema_length=0)
    return df


def _blank_to_null(column: str) -> pl.Expr:
    text = pl.col(column).cast(pl.Utf8).str.strip_chars()
    return pl.when(text.is_in(["", "NA", "nan", "None"])).then(None).otherwise(text).alias(column)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    sheet = _fix_delimiter(sources["marker_sheet"])
    sheet = sheet.rename(
        {c: re.sub(r"[^0-9A-Za-z]+", "_", c.strip()).strip("_") for c in sheet.columns}
    )
    missing = [c for c in _REQUIRED if c not in sheet.columns]
    if missing:
        raise ValueError(f"mcmicro marker sheet: missing column(s) {missing}; got {sheet.columns}")
    for column in (
        "background",
        "exposure",
        "remove",
        "filter",
        "excitation_wavelength",
        "emission_wavelength",
    ):
        if column not in sheet.columns:
            sheet = sheet.with_columns(pl.lit(None, dtype=pl.Utf8).alias(column))
    sheet = sheet.with_columns(
        *[
            _blank_to_null(c)
            for c in (
                "marker_name",
                "background",
                "exposure",
                "remove",
                "filter",
                "excitation_wavelength",
                "emission_wavelength",
            )
        ]
    ).filter(pl.col("marker_name").is_not_null())
    removed = pl.col("remove").fill_null("").str.to_lowercase().is_in(list(_TRUE))
    out = sheet.with_columns(
        pl.col("channel_number").cast(pl.Int64, strict=False),
        pl.col("cycle_number").cast(pl.Int64, strict=False),
        pl.col("marker_name")
        .map_elements(
            lambda m: "Nuclear stain" if is_nuclear(m) else "Marker", return_dtype=pl.Utf8
        )
        .alias("marker_role"),
        pl.when(removed).then(pl.lit("Removed")).otherwise(pl.lit("Quantified")).alias("status"),
        pl.when(removed).then(0).otherwise(1).cast(pl.Int64).alias("quantified"),
        pl.col("background").is_not_null().cast(pl.Int64).alias("background_subtracted"),
        pl.col("exposure").cast(pl.Float64, strict=False),
        pl.col("excitation_wavelength").cast(pl.Float64, strict=False),
        pl.col("emission_wavelength").cast(pl.Float64, strict=False),
    )
    return out.select(list(OUTPUT_SCHEMA)).sort("channel_number")
