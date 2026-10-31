"""riboWaltz library summary with each library's design group and label.

The catalog recipe ``ribowaltz/library_summary.py`` pools the three riboWaltz
tables of a library into one row (P-site count, frame-0 share and margin, region
shares, footprint length). This recipe keeps that transform and adds two columns
the phasing bars colour and label by:

* the design group, a column named by the template's ``GROUP_COL`` (read from the
  design table when that has it, else from the sample sheet), so a library keeps
  the colour its group has on every other tile;
* ``sample_description``, the readable library name of the sheet or the design
  table, when either has one.

Without a design group the group column is left out, and the figure draws its
bars in one colour.

Sources: the ``*.ribowaltz.frames.tsv``, ``*.ribowaltz.psite_region.tsv`` and
``*.ribowaltz.length_distribution.tsv`` files of every library, the run's sample
sheet and the optional design table.

Parameters:
    group_col  the design column the libraries are coloured by (the template's ``GROUP_COL``)

Output schema: the catalog's (``sample`` is the key), then the group column and
``sample_description`` where the run has them.
"""

from __future__ import annotations

import polars as pl

# OUTPUT SCHEMA: the catalog summary columns, plus the group column and label below.
from depictio.catalog.ribowaltz.library_summary import OUTPUT_SCHEMA
from depictio.catalog.ribowaltz.library_summary import SOURCES as _CATALOG_SOURCES
from depictio.catalog.ribowaltz.library_summary import transform as _summary
from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    *_CATALOG_SOURCES,
    # No input_schema: the id column is found by name and the design columns are run-dependent.
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0},
    ),
    # The design table (METADATA_FILE), absent on a run without one.
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

# The group column is named by the template's group_col and passes through.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {"sample_description": pl.Utf8}


def _fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    """A TSV sheet read as CSV arrives as one tab-joined column: split it."""
    if df.width != 1 or "\t" not in df.columns[0]:
        return df
    header = df.columns[0].split("\t")
    rows = [str(v).split("\t") for v in df[df.columns[0]].to_list()]
    return pl.DataFrame(
        {h: [r[i] if i < len(r) else None for r in rows] for i, h in enumerate(header)}
    )


def _by_sample(df: pl.DataFrame | None, id_col: str | None, column: str) -> dict[str, str]:
    """``sample -> value`` of one column of a table keyed on ``id_col``, blanks left out."""
    if df is None or id_col is None or column not in df.columns or column == id_col:
        return {}
    out: dict[str, str] = {}
    for record in df.to_dicts():
        sample = str(record.get(id_col) or "").strip()
        value = str(record.get(column) or "").strip()
        if sample and value:
            out.setdefault(sample, value)
    return out


def transform(
    sources: dict[str, pl.DataFrame | None], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """The catalog's library summary, with the design group and the library label."""
    out = _summary({k: sources[k] for k in ("frames", "regions", "lengths")})

    sheet = _fix_delimiter(sources["samplesheet"])
    sheet = sheet.rename({c: c.strip() for c in sheet.columns})
    sheet_id = next(
        (c for c in sheet.columns if c.lower() in ("sample", "sample_id", "sampleid")), None
    )
    design = sources.get("metadata")
    if design is not None:
        design = design.rename({c: c.strip() for c in design.columns})
    design_id = design.columns[0] if design is not None and design.width else None

    def lookup(column: str) -> dict[str, str]:
        return _by_sample(design, design_id, column) or _by_sample(sheet, sheet_id, column)

    extra: list[pl.Expr] = []
    group = ((params or {}).get("group_col") or "").strip()
    if group and group not in out.columns:
        values = lookup(group)
        if values:
            extra.append(pl.col("sample").replace_strict(values, default=None).alias(group))
    labels = lookup("sample_description")
    if labels and "sample_description" not in out.columns:
        extra.append(
            pl.col("sample").replace_strict(labels, default=None).alias("sample_description")
        )
    return out.with_columns(extra) if extra else out


__all__ = ["OPTIONAL_OUTPUT_SCHEMA", "OUTPUT_SCHEMA", "SOURCES", "transform"]
