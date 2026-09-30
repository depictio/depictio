"""Sample hub for nf-core/proteinfamilies: the run's samplesheet, one row per sample.

proteinfamilies reads its samplesheet from ``--input`` and does not publish it,
so the template reads the file named by ``METADATA_FILE`` (by default the copy
under ``input/``). The pipeline's input schema fixes ``sample`` and ``fasta``;
``existing_hmms_to_update`` and ``existing_msas_to_update`` are optional, and a
row that gives them runs the update mode (the sample's sequences are first
matched against those families, the rest build new ones).

Every sheet column is kept under its own name (sanitised to ``[0-9A-Za-z_]``),
so ``GROUP_COL`` can name any column a user adds to the sheet, and one column
is derived from the sheet's content, never from the sample names:

* ``mode``: ``update`` when the row names existing HMMs to update, else
  ``create``. It is the template's default ``GROUP_COL``.

``fasta`` and the two archive columns are reduced to their file names.

Output:
    sample, mode, fasta, existing_hmms_to_update, existing_msas_to_update : Utf8,
    <other sheet columns> : Utf8
"""

from __future__ import annotations

import io
import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "mode": pl.Utf8,
    "fasta": pl.Utf8,
    "existing_hmms_to_update": pl.Utf8,
    "existing_msas_to_update": pl.Utf8,
}

_PATH_COLUMNS = ("fasta", "existing_hmms_to_update", "existing_msas_to_update")


def _fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    """Re-split a tab-separated sheet that was read with a comma separator."""
    if df.width == 1 and "\t" in df.columns[0]:
        text = "\n".join([df.columns[0]] + [str(v) for v in df[df.columns[0]].to_list()])
        return pl.read_csv(io.StringIO(text), separator="\t", infer_schema_length=0)
    return df


def _sanitise(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).strip("_") or "column"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    sheet = _fix_delimiter(sources["samplesheet"])
    sheet = sheet.select(
        [pl.col(c).cast(pl.Utf8).str.strip_chars().alias(_sanitise(c)) for c in sheet.columns]
    )
    if "sample" not in sheet.columns:
        raise ValueError(
            f"proteinfamilies samplesheet: missing the 'sample' column; got {sheet.columns}"
        )
    for column in _PATH_COLUMNS:
        if column not in sheet.columns:
            sheet = sheet.with_columns(pl.lit(None, dtype=pl.Utf8).alias(column))
        sheet = sheet.with_columns(
            pl.when(pl.col(column).str.len_chars() > 0)
            .then(pl.col(column).str.split("/").list.last())
            .otherwise(None)
            .alias(column)
        )
    out = sheet.with_columns(
        pl.when(pl.col("existing_hmms_to_update").is_not_null())
        .then(pl.lit("update"))
        .otherwise(pl.lit("create"))
        .alias("mode")
    ).filter(pl.col("sample").is_not_null() & (pl.col("sample") != ""))
    lead = list(EXPECTED_SCHEMA)
    return out.select(lead + [c for c in out.columns if c not in lead]).sort("sample")
