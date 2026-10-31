"""Salmon sample PCA with each library's design group.

The catalog recipe ``salmon/sample_pca.py`` projects the merged Salmon TPM matrix
onto its first principal components and joins the sample sheet. Its ``group``
column is the sheet's most factor-like column, which on a riboseq sheet is the
assay (``type``): the PCA then separates the assays and never shows the design.
This recipe keeps that transform and adds one column, named by the template's
``GROUP_COL``, that the PCA colours by, so a library keeps the colour its group
has on every other tile:

* the value comes from the design table when that has the column, else from the
  sample sheet;
* a library the design table does not list, and a run without a design group,
  read ``All libraries``, so the column is always there and the PCA draws one colour
  instead of failing on a missing column.

The catalog's ``group`` column is kept: it stays one of the PCA's Colour-by options
(the assay split).

Sources: the merged gene TPM matrix, the run's sample sheet and the optional
design table.

Parameters:
    group_col  the design column the libraries are coloured by (the template's ``GROUP_COL``)

Output schema: the catalog's, then the group column.
"""

from __future__ import annotations

import polars as pl

# OUTPUT SCHEMA: the catalog PCA columns, plus the group column below.
from depictio.catalog.salmon.sample_pca import OPTIONAL_OUTPUT_SCHEMA, OUTPUT_SCHEMA
from depictio.catalog.salmon.sample_pca import SOURCES as _CATALOG_SOURCES
from depictio.catalog.salmon.sample_pca import transform as _pca
from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    *_CATALOG_SOURCES,
    # The design table (METADATA_FILE), absent on a run without one.
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

_UNGROUPED = "All libraries"


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
    """The catalog's sample PCA, with a column for the design group."""
    out = _pca(
        {k: v for k, v in sources.items() if k in ("matrix", "samplesheet") and v is not None}
    )
    group = ((params or {}).get("group_col") or "").strip()
    if not group or group in out.columns:
        return out

    sheet = sources.get("samplesheet")
    sheet_id = None
    if sheet is not None:
        sheet = _fix_delimiter(sheet)
        sheet = sheet.rename({c: c.strip() for c in sheet.columns})
        sheet_id = next(
            (c for c in sheet.columns if c.lower() in ("sample", "sample_id", "sampleid")), None
        )
    design = sources.get("metadata")
    if design is not None:
        design = design.rename({c: c.strip() for c in design.columns})
    design_id = design.columns[0] if design is not None and design.width else None

    values = _by_sample(design, design_id, group) or _by_sample(sheet, sheet_id, group)
    labelled = pl.col("sample_id").replace_strict(values, default=None) if values else pl.lit(None)
    return out.with_columns(labelled.cast(pl.Utf8).fill_null(_UNGROUPED).alias(group))


__all__ = ["OPTIONAL_OUTPUT_SCHEMA", "OUTPUT_SCHEMA", "SOURCES", "transform"]
