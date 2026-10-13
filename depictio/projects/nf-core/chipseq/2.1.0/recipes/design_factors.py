"""One row per merged library of a chipseq 2.x run, with its factors as columns.

The 2.1.0 override of the shared `nf-core/chipseq/design_factors.py`: same output
schema, same design table logic, a different input. nf-core/chipseq 2.x takes an
nf-core samplesheet and republishes it, checked and expanded, as
`pipeline_info/samplesheet.valid.csv`: one row per sequencing library, whose
`sample` the pipeline builds as `<sample>_REP<replicate>_T<technical replicate>`.
Input controls are rows of their own with an empty `antibody`, and a ChIP row's
`control` already names its control at merged-library level
(`<control>_REP<replicate>`). There is no `design_controls.csv` any more.

Everything downstream is named after the merged library, `<sample>_REP<n>`: MACS3
stamps it into every peak name, the consensus tables use it as their sample
columns, and deepTools, preseq and Picard name their reports after it. So the
technical suffix is dropped and the library rows are collapsed to that id. The
sheet's own group and replicate are recovered exactly by splitting the id at the
pipeline-made `_REP<digits>` suffix; nothing else is read out of a name.

The experimental factor comes from the run's design table, declared through
`METADATA_FILE` exactly as in 1.x: sample id in `METADATA_ID_COL` (else a column
named `sample`, else the first column), `condition` the `GROUP_COL` factor (the
first factor when unset), every other factor an extra column. The table is matched
on the merged-library id, then on the sample group for a table written one row
per group. Without a table `condition` is the sample group.

A control takes the antibodies of the ChIPs it serves (comma-joined), so the
antibody filter selects a ChIP set together with its inputs, and takes their
condition when they agree on one (or, without a table, instead of its own group).

Output schema:
    sample_id : Utf8         merged library name every downstream file uses
    role : Utf8              "ChIP" or "input control"
    is_control : Boolean     true for the input control libraries
    antibody : Utf8          antibody of the ChIP, or of the ChIPs a control serves
    condition : Utf8         GROUP_COL of the design table, else the sample group
    replicate : Utf8         biological replicate, as the pipeline tags it (REP1)
    control_id : Utf8        input control of a ChIP row, null on a control row
    <design columns> : Utf8  every other factor of METADATA_FILE, when given
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        path="pipeline_info/samplesheet.valid.csv",
        format="CSV",
        input_schema={
            "sample": pl.Utf8,
            "antibody": pl.Utf8,
            "control": pl.Utf8,
        },
        read_kwargs={"infer_schema_length": 0},
    ),
    # The metadata sheet is user supplied: its id and group columns are chosen by parameter,
    # so no column name is fixed.
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "role": pl.Utf8,
    "is_control": pl.Boolean,
    "antibody": pl.Utf8,
    "condition": pl.Utf8,
    "replicate": pl.Utf8,
    "control_id": pl.Utf8,
}
# Extra design columns are run-dependent; validated dynamically.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

_REQUIRED = ["sample", "antibody", "control"]

#: `<sample>_REP<n>_T<technical replicate>` -> `<sample>_REP<n>`.
_TECHNICAL_SUFFIX = r"_T\d+$"

#: `<sample>_REP<replicate>`, the merged-library id the pipeline builds.
_PIPELINE_ID = r"^(.*)_(REP\d+)$"

#: `GROUP_COL` value the CLI sets when the run declares no group column.
NO_GROUP_SENTINEL = "__no_group__"


def _param(params: dict[str, str] | None, key: str) -> str | None:
    value = ((params or {}).get(key) or "").strip()
    return value if value and value != NO_GROUP_SENTINEL else None


def _text(column: str) -> pl.Expr:
    """A samplesheet cell as trimmed text, null when blank."""
    value = pl.col(column).cast(pl.Utf8).str.strip_chars()
    return pl.when(value == "").then(None).otherwise(value)


def _design_table(
    metadata: pl.DataFrame | None, id_col: str | None, group_col: str | None
) -> tuple[pl.DataFrame, list[str]] | None:
    """The design table keyed on ``key``, with ``_condition`` and the extra factors."""
    if metadata is None or metadata.is_empty() or metadata.width < 2:
        return None
    if id_col not in metadata.columns:
        id_col = "sample" if "sample" in metadata.columns else metadata.columns[0]
    factors = [c for c in metadata.columns if c not in (id_col, "source_path")]
    if not factors:
        return None
    condition_col = group_col if group_col in factors else factors[0]
    extras = [c for c in factors if c != condition_col and c not in OUTPUT_SCHEMA]
    table = metadata.select(
        pl.col(id_col).cast(pl.Utf8).str.strip_chars().alias("key"),
        pl.col(condition_col).cast(pl.Utf8).alias("_condition"),
        *[pl.col(c).cast(pl.Utf8) for c in extras],
    ).unique(subset="key", keep="first", maintain_order=True)
    return table, extras


def _merged_libraries(sheet: pl.DataFrame) -> pl.DataFrame:
    """The sheet's library rows collapsed to one row per merged library."""
    return (
        sheet.select(
            _text("sample").str.replace(_TECHNICAL_SUFFIX, "").alias("sample_id"),
            _text("antibody").alias("antibody"),
            _text("control").alias("control_id"),
        )
        .drop_nulls("sample_id")
        .group_by("sample_id", maintain_order=True)
        .agg(
            pl.col("antibody").drop_nulls().first(),
            pl.col("control_id").drop_nulls().first(),
        )
    )


def transform(
    sources: dict[str, pl.DataFrame | None], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """Collapse the validated samplesheet to merged libraries and attach the design factors."""
    sheet = sources["samplesheet"]
    if sheet is None:
        raise ValueError("chipseq design_factors: samplesheet.valid.csv is missing")
    missing = [c for c in _REQUIRED if c not in sheet.columns]
    if missing:
        raise ValueError(f"chipseq design_factors: samplesheet.valid.csv lacks columns {missing}")

    merged = _merged_libraries(sheet)
    chips = merged.filter(pl.col("antibody").is_not_null()).with_columns(
        pl.lit("ChIP").alias("role"),
        pl.lit(False).alias("is_control"),
    )
    if chips.is_empty():
        raise ValueError(
            "chipseq design_factors: no ChIP row in samplesheet.valid.csv "
            "(every row lacks an antibody)"
        )

    # A control is a sheet row without an antibody, or a library a ChIP names as
    # its control that the sheet does not list (an older sheet, a trimmed copy).
    served = (
        chips.drop_nulls("control_id")
        .group_by("control_id")
        .agg(pl.col("antibody").unique().sort().str.join(",").alias("antibody"))
        .rename({"control_id": "sample_id"})
    )
    control_ids = pl.concat(
        [
            merged.filter(pl.col("antibody").is_null()).select("sample_id"),
            served.select("sample_id"),
        ]
    ).unique(maintain_order=True)
    controls = (
        control_ids.filter(~pl.col("sample_id").is_in(chips.get_column("sample_id").implode()))
        .join(served, on="sample_id", how="left")
        .with_columns(
            pl.lit("input control").alias("role"),
            pl.lit(True).alias("is_control"),
            pl.lit(None, pl.Utf8).alias("control_id"),
        )
    )

    libraries = pl.concat([chips, controls], how="diagonal_relaxed").with_columns(
        pl.col("sample_id")
        .str.extract(_PIPELINE_ID, 1)
        .fill_null(pl.col("sample_id"))
        .alias("_group"),
        pl.col("sample_id").str.extract(_PIPELINE_ID, 2).alias("replicate"),
    )

    extras: list[str] = []
    design = _design_table(
        sources.get("metadata"), _param(params, "id_col"), _param(params, "group_col")
    )
    if design is None:
        libraries = libraries.with_columns(pl.col("_group").alias("_condition"))
    else:
        table, extras = design
        by_id = libraries.join(table, left_on="sample_id", right_on="key", how="left")
        by_group = libraries.join(table, left_on="_group", right_on="key", how="left")
        # A library the table does not list by id falls back to its sample group.
        libraries = by_id.with_columns(
            pl.coalesce(pl.col(c), by_group.get_column(c)).alias(c) for c in ["_condition", *extras]
        )

    # The condition of the ChIPs each control serves, when they agree on one.
    inherited = (
        libraries.filter(~pl.col("is_control"))
        .drop_nulls("control_id")
        .group_by("control_id")
        .agg(pl.col("_condition").drop_nulls().unique().alias("_levels"))
        .filter(pl.col("_levels").list.len() == 1)
        .select(
            pl.col("control_id").alias("sample_id"),
            pl.col("_levels").list.first().alias("_inherited"),
        )
    )
    libraries = libraries.join(inherited, on="sample_id", how="left")
    if design is None:
        # No table: a control's own group names the input, not the condition.
        condition = (
            pl.when(pl.col("is_control"))
            .then(pl.coalesce("_inherited", "_condition"))
            .otherwise(pl.col("_condition"))
        )
    else:
        condition = pl.coalesce("_condition", "_inherited")
    libraries = libraries.with_columns(condition.alias("condition"))

    return libraries.select([*OUTPUT_SCHEMA, *extras]).sort(
        ["is_control", "antibody", "condition", "replicate", "sample_id"], nulls_last=True
    )
