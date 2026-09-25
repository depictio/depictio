"""One row per nf-core/nanoseq sample: the validated samplesheet, joined to the run's design.

nanoseq's ``sample`` column already IS the name every output file uses (FastQC,
NanoPlot, minimap2, Bambu's count-matrix column headers all key on it
directly), so no name derivation is needed to link the outputs. The pipeline
builds that name itself as ``<group>_R<replicate>`` from the input sheet's
``group`` and ``replicate`` columns, which the validated sheet does not keep,
so those two are recovered exactly by splitting at that pipeline-made
``_R<digits>`` suffix. Nothing else is read out of a sample or file name.

Every other factor comes from the run's design table, declared through
``METADATA_FILE`` (the ampliseq convention): sample id in ``METADATA_ID_COL``
(else a column named ``sample``, else the first column), every other column a
factor, matched on the sample name and, for a table written one row per group,
on the group.

* ``condition`` is the ``GROUP_COL`` factor (the ``group_col`` param; the first
  factor when it is unset or not a column of the table), else the
  samplesheet group;
* ``protocol``, ``source_replicate`` and ``run_id`` are the design table's
  columns of those names (the library preparation, the replicate numbering of
  the source dataset and the flow-cell run: the confounders the dashboard
  offers beside the condition), ``"unknown"`` when the table does not carry
  them;
* every other factor is carried as an extra column under its own name.

Output schema:
    sample_id : Utf8         the samplesheet ``sample`` column, unmodified
    condition : Utf8         GROUP_COL of the design table, else the sheet group
    replicate : Int64        replicate number inside the group (pipeline suffix)
    protocol : Utf8          library preparation, from the design table
    source_replicate : Utf8  source-dataset replicate, from the design table
    run_id : Utf8            flow-cell run, from the design table
    reference : Utf8         genome/transcriptome build (the ``fasta`` column)
    is_transcripts : Boolean true when ``input_file`` is already a transcriptome
    has_fast5 : Boolean      true when a nanopolish fast5 directory was supplied
    <design columns> : Utf8  every other factor of METADATA_FILE, when given
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="pipeline_info/samplesheet.valid.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
    ),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "condition": pl.Utf8,
    "replicate": pl.Int64,
    "protocol": pl.Utf8,
    "source_replicate": pl.Utf8,
    "run_id": pl.Utf8,
    "reference": pl.Utf8,
    "is_transcripts": pl.Boolean,
    "has_fast5": pl.Boolean,
}
# Extra design columns are run-dependent; validated dynamically.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_REQUIRED = ["sample", "fasta"]

#: Design-table columns bound to fixed hub columns of the same name.
DESIGN_COLUMNS = ("protocol", "source_replicate", "run_id")
UNKNOWN = "unknown"

#: `<group>_R<replicate>`, the sample name the pipeline builds from the sheet.
_PIPELINE_ID = r"^(.*)_R(\d+)$"

#: `GROUP_COL` value the CLI sets when the run declares no group column.
NO_GROUP_SENTINEL = "__no_group__"


def _param(params: dict[str, str] | None, key: str) -> str | None:
    value = ((params or {}).get(key) or "").strip()
    return value if value and value != NO_GROUP_SENTINEL else None


def _truthy(column: pl.Expr) -> pl.Expr:
    return column.cast(pl.Utf8).str.to_lowercase().is_in(["1", "true", "yes", "y"]).fill_null(False)


def _design_table(
    metadata: pl.DataFrame | None, id_col: str | None, group_col: str | None
) -> tuple[pl.DataFrame, list[str]] | None:
    """The design table keyed on ``key``: ``_condition``, the bound columns, the extras."""
    if metadata is None or metadata.is_empty() or metadata.width < 2:
        return None
    if id_col not in metadata.columns:
        id_col = "sample" if "sample" in metadata.columns else metadata.columns[0]
    factors = [c for c in metadata.columns if c not in (id_col, "source_path")]
    if not factors:
        return None
    condition_col = group_col if group_col in factors else factors[0]
    extras = [c for c in factors if c != condition_col and c not in EXPECTED_SCHEMA]
    bound = [c for c in DESIGN_COLUMNS if c in factors]
    table = metadata.select(
        pl.col(id_col).cast(pl.Utf8).str.strip_chars().alias("key"),
        pl.col(condition_col).cast(pl.Utf8).alias("_condition"),
        *[pl.col(c).cast(pl.Utf8).alias(f"_{c}") for c in bound],
        *[pl.col(c).cast(pl.Utf8) for c in extras],
    ).unique(subset="key", keep="first", maintain_order=True)
    return table, extras


def transform(
    sources: dict[str, pl.DataFrame | None], params: dict[str, str] | None = None
) -> pl.DataFrame:
    df = sources["samplesheet"]
    if df is None:
        raise ValueError("nanoseq samples: samplesheet.valid.csv is missing")
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"nanoseq samples: samplesheet lacks columns {missing}")

    if "nanopolish_fast5" in df.columns:
        has_fast5 = pl.col("nanopolish_fast5").cast(pl.Utf8).fill_null("").str.len_chars() > 0
    else:
        has_fast5 = pl.lit(False)
    is_transcripts = (
        _truthy(pl.col("is_transcripts")) if "is_transcripts" in df.columns else pl.lit(False)
    )

    sample = pl.col("sample").cast(pl.Utf8)
    hub = df.select(
        sample.alias("sample_id"),
        sample.str.extract(_PIPELINE_ID, 1).fill_null(sample).alias("_group"),
        sample.str.extract(_PIPELINE_ID, 2).cast(pl.Int64, strict=False).alias("replicate"),
        pl.col("fasta").cast(pl.Utf8).alias("reference"),
        is_transcripts.alias("is_transcripts"),
        has_fast5.alias("has_fast5"),
    ).unique(subset="sample_id", keep="first", maintain_order=True)

    extras: list[str] = []
    design = _design_table(
        sources.get("metadata"), _param(params, "id_col"), _param(params, "group_col")
    )
    if design is None:
        hub = hub.with_columns(pl.col("_group").alias("_condition"))
    else:
        table, extras = design
        by_id = hub.join(table, left_on="sample_id", right_on="key", how="left")
        by_group = hub.join(table, left_on="_group", right_on="key", how="left")
        # A sample the table does not list by name falls back to its group.
        hub = by_id.with_columns(
            pl.coalesce(pl.col(c), by_group.get_column(c)).alias(c)
            for c in table.columns
            if c != "key"
        )

    hub = hub.with_columns(
        pl.coalesce("_condition", "_group").alias("condition"),
        *[
            (
                pl.col(f"_{c}").fill_null(UNKNOWN) if f"_{c}" in hub.columns else pl.lit(UNKNOWN)
            ).alias(c)
            for c in DESIGN_COLUMNS
        ],
    )
    return hub.select([*EXPECTED_SCHEMA, *extras]).sort("sample_id")
