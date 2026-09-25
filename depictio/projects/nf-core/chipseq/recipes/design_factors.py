"""One row per sequencing library of a chipseq run, with its factors as columns.

nf-core/chipseq 1.2.0 derives `pipeline_info/design_controls.csv` from the user's
design sheet (columns `group`, `replicate`, `antibody`, `control`): one row per
ChIP, naming the input control it is called against and the antibody it was
raised against. The pipeline itself builds every library id as
`<group>_R<replicate>` (and the control id as `<control>_R<control replicate>`),
so the sheet's `group` and `replicate` columns are recovered exactly by
splitting the id at that pipeline-made `_R<digits>` suffix. Nothing else is read
out of a name: the group is never tokenised, and no condition is guessed from
it.

The experimental factor a run was designed to test comes from the run's design
table, declared through `METADATA_FILE` (the ampliseq convention): sample id in
`METADATA_ID_COL` (else a column named `sample`, else the first column), every
other column a factor. `condition` is the `GROUP_COL` factor (passed as the
`group_col` param; the first factor when it is unset or not a column of the
table), and every other factor is carried as an extra column under its own
name. The table is matched on the library id, and on the design group for a
table written one row per group. Without a design table `condition` is the
design sheet's `group`, the unit the pipeline itself compares.

The sheet lists the ChIP libraries and none of the input controls, although the
controls are sequenced libraries that appear in every QC collection of the run.
They are recovered from the `control_id` column and carried as rows of their
own, labelled by `role`. A control takes the antibody of the ChIPs it serves
(comma-joined when it serves several), so the antibody filter selects a ChIP
set together with its inputs, and takes their condition when the design table
does not list it (or, without a table, instead of its own group).

`replicatesExist` and `multipleGroups` are deliberately dropped: the pipeline
writes 1 in both for every row of a design that has replicates and groups, so
they back a card and a filter that can never move.

Output schema:
    sample_id : Utf8         library name every downstream file uses
    role : Utf8              "ChIP" or "input control"
    is_control : Boolean     true for the input control libraries
    antibody : Utf8          antibody of the ChIP, or of the ChIPs a control serves
    condition : Utf8         GROUP_COL of the design table, else the design group
    replicate : Utf8         design sheet replicate, as the pipeline tags it (R1)
    control_id : Utf8        input control of a ChIP row, null on a control row
    <design columns> : Utf8  every other factor of METADATA_FILE, when given
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="design",
        path="pipeline_info/design_controls.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
    ),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "role": pl.Utf8,
    "is_control": pl.Boolean,
    "antibody": pl.Utf8,
    "condition": pl.Utf8,
    "replicate": pl.Utf8,
    "control_id": pl.Utf8,
}
# Extra design columns are run-dependent; validated dynamically.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_REQUIRED = ["sample_id", "control_id", "antibody"]

#: `<group>_R<replicate>`, the id the pipeline builds from the design sheet.
_PIPELINE_ID = r"^(.*)_(R\d+)$"

#: `GROUP_COL` value the CLI sets when the run declares no group column.
NO_GROUP_SENTINEL = "__no_group__"


def _param(params: dict[str, str] | None, key: str) -> str | None:
    value = ((params or {}).get(key) or "").strip()
    return value if value and value != NO_GROUP_SENTINEL else None


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
    extras = [c for c in factors if c != condition_col and c not in EXPECTED_SCHEMA]
    table = metadata.select(
        pl.col(id_col).cast(pl.Utf8).str.strip_chars().alias("key"),
        pl.col(condition_col).cast(pl.Utf8).alias("_condition"),
        *[pl.col(c).cast(pl.Utf8) for c in extras],
    ).unique(subset="key", keep="first", maintain_order=True)
    return table, extras


def transform(
    sources: dict[str, pl.DataFrame | None], params: dict[str, str] | None = None
) -> pl.DataFrame:
    """Expand the ChIP design sheet to every library and attach the design factors."""
    df = sources["design"]
    if df is None:
        raise ValueError("chipseq design_factors: design_controls.csv is missing")
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"chipseq design_factors: design_controls.csv lacks columns {missing}")

    chips = df.select(
        pl.col("sample_id").cast(pl.Utf8),
        pl.lit("ChIP").alias("role"),
        pl.lit(False).alias("is_control"),
        pl.col("antibody").cast(pl.Utf8).replace("", None).alias("antibody"),
        pl.col("control_id").cast(pl.Utf8).replace("", None).alias("control_id"),
    ).unique(subset="sample_id", keep="first", maintain_order=True)

    # The controls are libraries of the run but rows of nobody's sheet.
    controls = (
        chips.drop_nulls("control_id")
        .group_by("control_id")
        .agg(pl.col("antibody").drop_nulls().unique().sort().str.join(",").alias("antibody"))
        .rename({"control_id": "sample_id"})
        .filter(~pl.col("sample_id").is_in(chips.get_column("sample_id").implode()))
        .with_columns(
            pl.lit("input control").alias("role"),
            pl.lit(True).alias("is_control"),
            pl.col("antibody").replace("", None),
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
        # A library the table does not list by id falls back to its design group.
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

    return libraries.select([*EXPECTED_SCHEMA, *extras]).sort(
        ["is_control", "antibody", "condition", "replicate"], nulls_last=True
    )
