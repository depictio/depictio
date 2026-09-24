"""The nf-core/rnasplice sample hub: one row per sample, every design column.

rnasplice validates its ``--input`` sheet and publishes the result as
``pipeline_info/samplesheet.valid.csv``: one row per FASTQ pair with the
``sample``, ``single_end``, ``strandedness`` and ``condition`` columns (the
condition is mandatory, the contrasts sheet names its values). A sample
sequenced over several runs gets one row per run, suffixed ``_T1``, ``_T2``...
by the sheet check; the pipeline merges those runs and names every downstream
output after the bare sample, so the hub collapses them back the same way.

The optional design table (``METADATA_FILE``, the ``metadata`` collection)
adds factors the sheet does not carry. Its columns win over a same-named sheet
column, so a design table can refine ``condition`` without being ignored.

Sources:
    sheet     ``pipeline_info/samplesheet.valid.csv``
    metadata  the optional ``metadata`` collection (dc_ref)

Params:
    id_col    the design table's sample column (``METADATA_ID_COL``); the
              first column when absent or unknown.

Output schema:
    sample : Utf8          sample id, as every output of the run names it
    condition : Utf8       the sheet's condition (or the design table's)
    read_type : Utf8       paired-end / single-end
    strandedness : Utf8    library strandedness declared in the sheet
    runs : Int64           sequencing runs merged into the sample
    <design columns> : Utf8, one per extra design-table column
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="sheet",
        path="pipeline_info/samplesheet.valid.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0},
    ),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "condition": pl.Utf8,
    "read_type": pl.Utf8,
    "strandedness": pl.Utf8,
    "runs": pl.Int64,
}
# Design columns are run-dependent; validated dynamically.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_RUN_SUFFIX = r"_T\d+$"
_TRUE = ("true", "1", "yes", "t")


def _design(metadata: pl.DataFrame | None, id_col: str | None) -> pl.DataFrame | None:
    """The design table keyed on ``sample``, every other column as Utf8."""
    if metadata is None or metadata.is_empty():
        return None
    if not id_col or id_col not in metadata.columns:
        id_col = "sample" if "sample" in metadata.columns else metadata.columns[0]
    keep = [c for c in metadata.columns if c not in (id_col, "source_path")]
    return metadata.select(
        pl.col(id_col).cast(pl.Utf8).str.strip_chars().alias("sample"),
        *[pl.col(c).cast(pl.Utf8) for c in keep],
    ).unique(subset="sample", keep="first")


def transform(
    sources: dict[str, pl.DataFrame | None], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """Collapse the sheet's runs to samples, then carry the design table."""
    sheet = sources["sheet"]
    single = pl.col("single_end").cast(pl.Utf8).str.to_lowercase().is_in(_TRUE)
    hub = (
        sheet.with_columns(
            pl.col("sample").cast(pl.Utf8).str.replace(_RUN_SUFFIX, "").alias("sample"),
            pl.when(single)
            .then(pl.lit("single-end"))
            .otherwise(pl.lit("paired-end"))
            .alias("read_type"),
        )
        .group_by("sample", maintain_order=True)
        .agg(
            pl.col("condition").cast(pl.Utf8).first(),
            pl.col("read_type").first(),
            pl.col("strandedness").cast(pl.Utf8).first(),
            pl.len().cast(pl.Int64).alias("runs"),
        )
    )
    design = _design(sources.get("metadata"), ((params or {}).get("id_col") or "").strip())
    if design is not None:
        shared = [c for c in design.columns if c != "sample" and c in hub.columns]
        hub = hub.join(design, on="sample", how="left", suffix="_design")
        hub = hub.with_columns(
            [pl.coalesce(pl.col(f"{c}_design"), pl.col(c)).alias(c) for c in shared]
        ).drop([f"{c}_design" for c in shared])
    head = list(EXPECTED_SCHEMA)
    return hub.select(head + [c for c in hub.columns if c not in head]).sort("sample")
