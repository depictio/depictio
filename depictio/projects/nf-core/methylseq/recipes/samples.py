"""One row per methylseq sample: the samplesheet, joined to the run's design.

Every Bismark output file names itself after the samplesheet ``sample`` column
directly (no ``_T<n>`` technical-replicate suffix, unlike cutandrun / eager), so
this hub needs no id reconstruction. The pipeline samplesheet carries no design
column, so the design comes from an optional table declared through
``METADATA_FILE`` (the ampliseq convention): sample id in a column named
``sample`` or else in the first column, every other column a factor. Nothing is
ever parsed out of the sample names, whose spelling is the submitter's choice.

The factors are carried under their own names and in the table's own column
order, so the dashboards' ``{GROUP_COL}`` resolves against the hub and the
catalog's window comparison can test along the first two-level factor (which is
also the column the CLI picks as ``GROUP_COL`` when none is given). Without a
design table the hub is the samplesheet alone: every tile bound to the sample
id keeps working, and the group comparison is skipped.

Output schema:
    sample_id : Utf8        the samplesheet's own sample name (matches every
                             Bismark output file for this sample)
    fastq_1 : Utf8          read 1 FASTQ path/URL from the samplesheet
    fastq_2 : Utf8          read 2 FASTQ path/URL, empty for single-end samples
    <design columns> : Utf8 one per factor of METADATA_FILE, when given
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet_full.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
    ),
    RecipeSource(ref="design", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "fastq_1": pl.Utf8,
    "fastq_2": pl.Utf8,
}
# Design columns are run-dependent; validated dynamically.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

#: Design-table column names that are never a factor: the sample id spellings
#: and bookkeeping columns a samplesheet-derived table may carry along.
NON_FACTOR_COLUMNS = frozenset({"sample", "sample_id", "fastq_1", "fastq_2", "genome"})


def _design(design: pl.DataFrame | None) -> pl.DataFrame | None:
    """The design table keyed on ``sample_id``, factors as strings, in file order."""
    if design is None or design.is_empty() or design.width < 2:
        return None
    id_col = "sample" if "sample" in design.columns else design.columns[0]
    factors = [c for c in design.columns if c != id_col and c not in NON_FACTOR_COLUMNS]
    if not factors:
        return None
    return design.select(
        pl.col(id_col).cast(pl.Utf8).alias("sample_id"),
        *[pl.col(c).cast(pl.Utf8) for c in factors],
    ).unique(subset="sample_id", keep="first", maintain_order=True)


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """The samplesheet's sample and FASTQ columns, plus the design factors."""
    sheet = sources["samplesheet"]
    if sheet is None or "sample" not in sheet.columns:
        columns = None if sheet is None else sheet.columns
        raise ValueError(f"methylseq samples: samplesheet lacks a 'sample' column, got {columns}")

    hub = sheet.select(
        pl.col("sample").cast(pl.Utf8).alias("sample_id"),
        *[
            (pl.col(c) if c in sheet.columns else pl.lit(None)).cast(pl.Utf8).alias(c)
            for c in ("fastq_1", "fastq_2")
        ],
    ).unique(subset="sample_id", keep="first", maintain_order=True)

    design = _design(sources.get("design"))
    if design is not None:
        hub = hub.join(design, on="sample_id", how="left")
    return hub.sort("sample_id")
