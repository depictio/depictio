"""Sample hub for nf-core/crisprseq (targeted): the run's samplesheet, one row per library.

crisprseq does not publish the samplesheet it ran on, so the template reads the
file named by ``METADATA_FILE`` (by default the copy under ``input/``). The
targeted input schema has ``sample``, ``fastq_1``, ``fastq_2``, ``reference``
(the amplicon sequence), ``protospacer`` and ``template`` (the HDR donor); only
``sample`` is required. Every other sheet column is kept under its own name so
``GROUP_COL`` can name any of them, except the sequences, which are summarised:

* ``guide``: the protospacer, upper-cased, the key of the per-guide tables. A
  run that gave one protospacer through ``--protospacer`` instead of the sheet
  gets a single ``run protospacer`` guide;
* ``has_template``: ``yes`` when the library has an HDR donor template;
* ``amplicon_length``: length of the reference amplicon, only when the sheet
  has a ``reference`` column (a column of nulls would only take table width).

The ``reference`` and ``template`` sequences and the FASTQ paths are dropped:
they are long, and nothing in the dashboards reads them.
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
    "guide": pl.Utf8,
    "has_template": pl.Utf8,
}
# Only when the sheet carries the ``reference`` amplicon sequences.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {"amplicon_length": pl.Int64}

RUN_GUIDE = "run protospacer"
_DROP = {"fastq_1", "fastq_2", "reference", "template"}


def _fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    """Re-split a tab-separated sheet that was read with a comma separator."""
    if df.width == 1 and "\t" in df.columns[0]:
        text = "\n".join([df.columns[0]] + [str(v) for v in df[df.columns[0]].to_list()])
        return pl.read_csv(io.StringIO(text), separator="\t", infer_schema_length=0)
    return df


def _sanitise(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).strip("_") or "column"


def _text(col: str, sheet: pl.DataFrame) -> pl.Expr:
    if col not in sheet.columns:
        return pl.lit(None, dtype=pl.Utf8)
    return pl.col(col).cast(pl.Utf8).str.strip_chars().replace("", None)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    sheet = _fix_delimiter(sources["samplesheet"])
    sheet = sheet.rename({c: _sanitise(c) for c in sheet.columns})
    if "sample" not in sheet.columns:
        raise ValueError(f"crisprseq samplesheet: no 'sample' column; got {sheet.columns}")
    out = sheet.with_columns(
        _text("sample", sheet).alias("sample"),
        _text("protospacer", sheet).str.to_uppercase().fill_null(RUN_GUIDE).alias("guide"),
        pl.when(_text("template", sheet).is_not_null())
        .then(pl.lit("yes"))
        .otherwise(pl.lit("no"))
        .alias("has_template"),
    )
    if "reference" in sheet.columns:
        out = out.with_columns(
            _text("reference", sheet).str.len_chars().cast(pl.Int64).alias("amplicon_length")
        )
    # A library sequenced on several lanes has one sheet row per FASTQ pair.
    out = out.filter(pl.col("sample").is_not_null()).unique(
        subset=["sample"], keep="first", maintain_order=True
    )
    head = [*EXPECTED_SCHEMA, *(c for c in OPTIONAL_SCHEMA if c in out.columns)]
    rest = [c for c in out.columns if c not in head and c not in _DROP]
    return out.select([*head, *rest]).sort("sample")
