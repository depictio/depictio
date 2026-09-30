"""Well hub for nf-core/cellpainting: the plate map, one row per imaged well.

The pipeline's samplesheet describes images (one row per channel, site and
well) and carries no design: which perturbation a well received lives in the
screen's plate map, a separate file. The template reads it from the path named
by ``METADATA_FILE`` (by default the vendored copy under ``input/``). The only
columns it requires are the plate and the well, under either of the two names
screening tools use (``plate`` / ``well`` or the JUMP / pycytominer
``Metadata_Plate`` / ``Metadata_Well``); every other column is kept under its
own name, so ``GROUP_COL`` can name any of them (a perturbation type, a
compound, a gene, a dose).

The hub key is ``well_id`` = ``<plate>_<well>``, the same key the CytoTable
recipes derive from the ``<batch>_<plate>_<well>_<site>`` file names, with the
well normalised to a row letter plus two-digit column (``A3`` -> ``A03``) on
both sides. When the per-site table is available (``cp-sites``), the hub is
restricted to the wells the run imaged, a plate map of a whole plate does not
flood the filters with wells that have no data, and gains the number of sites
and cells of each well; a well imaged but missing from the plate map is kept
with empty design columns rather than dropped.

Output:
    well_id, plate, well, row : Utf8, column : Int64,
    n_sites, n_cells : Int64 (null without the per-site table),
    <every other plate-map column> : Utf8
"""

from __future__ import annotations

import io
import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SITES_DC_TAG = "cp-sites"

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="platemap",
        path="input/platemap.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0},
    ),
    RecipeSource(ref="sites", dc_ref=SITES_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "well_id": pl.Utf8,
    "plate": pl.Utf8,
    "well": pl.Utf8,
    "row": pl.Utf8,
    "column": pl.Int64,
    "n_sites": pl.Int64,
    "n_cells": pl.Int64,
}

_PLATE_NAMES = ("plate", "Metadata_Plate", "Plate", "Assay_Plate_Barcode")
_WELL_NAMES = ("well", "Metadata_Well", "Well", "well_position", "Metadata_well_position")


def _fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    """Re-split a tab-separated plate map that was read with a comma separator."""
    if df.width == 1 and "\t" in df.columns[0]:
        text = "\n".join([df.columns[0]] + [str(v) for v in df[df.columns[0]].to_list()])
        return pl.read_csv(io.StringIO(text), separator="\t", infer_schema_length=0)
    return df


def normalise_well(well: str | None) -> str | None:
    """``a3`` / ``A3`` / ``A003`` -> ``A03``; anything else is returned upper-cased."""
    if well is None:
        return None
    match = re.fullmatch(r"([A-Za-z]{1,2})0*(\d{1,3})", well.strip())
    if not match:
        return well.strip().upper()
    return f"{match.group(1).upper()}{int(match.group(2)):02d}"


def _pick(columns: list[str], candidates: tuple[str, ...], what: str) -> str:
    for name in candidates:
        if name in columns:
            return name
    raise ValueError(
        f"cellpainting plate map: no {what} column (one of {candidates}); got {columns}"
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    plate_map = _fix_delimiter(sources["platemap"])
    plate_col = _pick(plate_map.columns, _PLATE_NAMES, "plate")
    well_col = _pick(plate_map.columns, _WELL_NAMES, "well")
    design = [c for c in plate_map.columns if c not in (plate_col, well_col, "well_id")]
    hub = plate_map.select(
        pl.col(plate_col).cast(pl.Utf8).str.strip_chars().alias("plate"),
        pl.col(well_col)
        .cast(pl.Utf8)
        .map_elements(normalise_well, return_dtype=pl.Utf8)
        .alias("well"),
        *[pl.col(c).cast(pl.Utf8) for c in design],
    ).with_columns((pl.col("plate") + "_" + pl.col("well")).alias("well_id"))
    hub = hub.unique(subset="well_id", keep="first", maintain_order=True)

    sites = sources.get("sites")
    if sites is not None and not sites.is_empty():
        imaged = sites.group_by(["well_id", "plate", "well"]).agg(
            pl.col("site").n_unique().cast(pl.Int64).alias("n_sites"),
            pl.col("n_cells").sum().cast(pl.Int64).alias("n_cells"),
        )
        hub = imaged.join(hub.drop("plate", "well"), on="well_id", how="left")
    else:
        hub = hub.with_columns(
            pl.lit(None, dtype=pl.Int64).alias("n_sites"),
            pl.lit(None, dtype=pl.Int64).alias("n_cells"),
        )

    hub = hub.with_columns(
        pl.col("well").str.extract(r"^([A-Za-z]+)", 1).alias("row"),
        pl.col("well").str.extract(r"(\d+)$", 1).cast(pl.Int64).alias("column"),
    )
    head = [pl.col(name).cast(dtype) for name, dtype in EXPECTED_SCHEMA.items()]
    return hub.select(*head, *[pl.col(c) for c in design]).sort(["plate", "row", "column"])
