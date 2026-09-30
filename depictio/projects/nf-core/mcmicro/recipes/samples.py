"""One row per sample of an nf-core/mcmicro run: the hub every tab filters on.

The cycle samplesheet (``--input_cycle``: ``sample``, ``cycle_number``,
``image_tiles``, optional ``dfp`` / ``ffp``) lists one row per acquisition cycle
of a sample; the hub groups it to one row per sample with its cycle count. The
sample name is the one every output file uses (``registration/ashlar/<sample>
.ome.tif``, the segmentation masks, the MCQUANT tables).

The experimental factor comes from the run's design table, declared through
``METADATA_FILE`` (the ampliseq convention): sample id in ``METADATA_ID_COL``
(else a column named ``sample``, else the first column), every other column a
factor. ``condition`` is the ``GROUP_COL`` factor (the first factor when it is
unset or absent), every other factor is carried under its own name. Without a
design table ``condition`` is ``all``, so the filter and the group colouring
still resolve. Nothing is read out of a sample name.

Output columns:
    sample, n_cycles, condition, <design columns>
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="samplesheet", dc_ref="samplesheet"),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "n_cycles": pl.Int64,
    "condition": pl.Utf8,
}
# Extra design columns are run-dependent; validated dynamically.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

#: `GROUP_COL` value the CLI sets when the run declares no group column.
NO_GROUP_SENTINEL = "__no_group__"
NO_DESIGN = "all"


def _param(params: dict[str, str] | None, key: str) -> str | None:
    value = ((params or {}).get(key) or "").strip()
    return value if value and value != NO_GROUP_SENTINEL else None


def _design(
    metadata: pl.DataFrame | None, id_col: str | None, group_col: str | None
) -> tuple[pl.DataFrame, list[str]] | None:
    if metadata is None or metadata.is_empty() or metadata.width < 2:
        return None
    if id_col not in metadata.columns:
        id_col = "sample" if "sample" in metadata.columns else metadata.columns[0]
    factors = [c for c in metadata.columns if c not in (id_col, "source_path")]
    if not factors:
        return None
    condition_col = group_col if group_col in factors else factors[0]
    extras = [c for c in factors if c != condition_col and c not in EXPECTED_SCHEMA]
    table = metadata.select(
        pl.col(id_col).cast(pl.Utf8).str.strip_chars().alias("sample"),
        pl.col(condition_col).cast(pl.Utf8).alias("condition"),
        *[pl.col(c).cast(pl.Utf8) for c in extras],
    ).unique(subset="sample", keep="first", maintain_order=True)
    return table, extras


def transform(
    sources: dict[str, pl.DataFrame | None], params: dict[str, str] | None = None
) -> pl.DataFrame:
    sheet = sources["samplesheet"]
    if sheet is None or "sample" not in sheet.columns:
        raise ValueError("mcmicro samples: the samplesheet has no 'sample' column")
    cycles = pl.col("cycle_number").n_unique() if "cycle_number" in sheet.columns else pl.len()
    hub = (
        sheet.with_columns(pl.col("sample").cast(pl.Utf8).str.strip_chars())
        .group_by("sample", maintain_order=True)
        .agg(cycles.cast(pl.Int64).alias("n_cycles"))
    )
    design = _design(sources.get("metadata"), _param(params, "id_col"), _param(params, "group_col"))
    extras: list[str] = []
    if design is None:
        hub = hub.with_columns(pl.lit(NO_DESIGN).alias("condition"))
    else:
        table, extras = design
        hub = hub.join(table, on="sample", how="left").with_columns(
            pl.col("condition").fill_null(NO_DESIGN)
        )
    return hub.select(*EXPECTED_SCHEMA, *extras).sort("sample")
