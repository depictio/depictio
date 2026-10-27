"""Sample hub for nf-core/mcmicro: one row per sample (one image to register).

mcmicro reads its samplesheet from ``--input_cycle`` (one row per sample and
cycle: ``sample``, ``cycle_number``, ``image_tiles``, optional ``dfp`` / ``ffp``
illumination profiles) or ``--input_sample`` (one row per sample, the tiles of
every cycle in one directory). It does not publish the sheet, so the template
reads the file named by ``METADATA_FILE`` (by default the copy under
``input/``). A sample is one tissue image: its cycles are stitched and
registered into one OME-TIFF, segmented and quantified.

Rows are grouped by ``sample``. Columns derived from the sheet's content, never
from the sample names:

* ``cycle_count``: the cycles of the sample (rows of a cycle sheet, 1 for a
  sample sheet);
* ``cycles``: the same as a label (``3 cycles``), the template's default
  ``GROUP_COL``, since a sheet carries no design column of its own;
* ``image_files``: the tile files the sheet lists for the sample.

Every other sheet column is kept under its own name (sanitised to
``[0-9A-Za-z_]``, its first value per sample), so ``GROUP_COL`` can name a
design column a user adds (tissue, patient, condition). The file paths
(``image_tiles``, ``dfp``, ``ffp``) are dropped.

Output:
    sample : Utf8, cycle_count : Int64, cycles : Utf8, image_files : Int64,
    <other sheet columns> : Utf8
"""

from __future__ import annotations

import io
import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    # No input_schema: a tab-separated sheet is read as one column and re-split
    # by _fix_delimiter, so the required columns only exist after transform() starts.
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "cycle_count": pl.Int64,
    "cycles": pl.Utf8,
    "image_files": pl.Int64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

_PATH_COLUMNS = ("image_tiles", "dfp", "ffp", "image_directory")


def _fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    """Re-split a tab-separated sheet that was read with a comma separator."""
    if df.width == 1 and "\t" in df.columns[0]:
        text = "\n".join([df.columns[0]] + [str(v) for v in df[df.columns[0]].to_list()])
        return pl.read_csv(io.StringIO(text), separator="\t", infer_schema_length=0)
    return df


def _sanitise(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).strip("_") or "column"


def transform(
    sources: dict[str, pl.DataFrame], params: dict[str, str] | None = None
) -> pl.DataFrame:
    sheet = _fix_delimiter(sources["samplesheet"])
    sheet = sheet.select(
        [pl.col(c).cast(pl.Utf8).str.strip_chars().alias(_sanitise(c)) for c in sheet.columns]
    )
    id_col = _sanitise((params or {}).get("id_col") or "sample")
    if id_col not in sheet.columns:
        raise ValueError(
            f"mcmicro samplesheet: no '{id_col}' column; got {sheet.columns}. Expected the "
            "--input_cycle sheet (sample, cycle_number, image_tiles) or the --input_sample one"
        )
    rows = sheet.filter(pl.col(id_col).is_not_null() & (pl.col(id_col) != ""))
    if id_col != "sample":
        rows = rows.drop("sample", strict=False).rename({id_col: "sample"})
    has_cycles = "cycle_number" in rows.columns
    has_tiles = "image_tiles" in rows.columns
    extra = [
        c
        for c in rows.columns
        if c not in ("sample", "cycle_number", *_PATH_COLUMNS, *OUTPUT_SCHEMA)
    ]
    out = rows.group_by("sample", maintain_order=True).agg(
        (pl.col("cycle_number").n_unique() if has_cycles else pl.lit(1))
        .cast(pl.Int64)
        .alias("cycle_count"),
        (pl.col("image_tiles").drop_nulls().len() if has_tiles else pl.len())
        .cast(pl.Int64)
        .alias("image_files"),
        *[pl.col(c).drop_nulls().first().alias(c) for c in extra],
    )
    out = out.with_columns(
        pl.when(pl.col("cycle_count") == 1)
        .then(pl.lit("1 cycle"))
        .otherwise(pl.col("cycle_count").cast(pl.Utf8) + " cycles")
        .alias("cycles"),
    )
    lead = list(OUTPUT_SCHEMA)
    return out.select(lead + [c for c in out.columns if c not in lead]).sort("sample")
