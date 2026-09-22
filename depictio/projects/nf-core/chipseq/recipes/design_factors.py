"""One row per sequencing library of a chipseq run, with its factors as columns.

nf-core/chipseq 1.2.0 derives `pipeline_info/design_controls.csv` from the user's
design sheet: one row per ChIP, naming the input control it is called against and
the antibody it was raised against. Two things make that sheet unusable as the
dashboard's hub on its own.

First, the experimental conditions never become columns. The megatest compares
EZH2 in NTKO against TKO cells and FOXA1 in E2-treated against vehicle-treated
cells, and both comparisons exist ONLY inside the sample names
(`EZH2_IP_NTKO_R1`, `FOXA1_IP_VEH_R2`). A reader could filter by antibody, which
has two values and separates the two experiments, but not by the condition the
run was designed to test. This recipe parses `<antibody>_IP_<condition>_R<n>`
into real `condition` and `replicate` columns, token by token rather than with a
pipeline-specific regex: the replicate is the trailing `_R<digits>`, and the
condition is what is left of the name after the leading antibody token and an
optional `IP` / `ChIP` marker.

Second, the sheet lists the 8 ChIP libraries and none of the 8 input controls,
although the controls are sequenced libraries that appear in every QC collection
of the run (preseq, plotFingerprint, plotProfile, samtools, MultiQC). A sample
filter built on the sheet alone can therefore never select an input, which is
half of what a ChIP QC comparison is. The controls are recovered from the
`control_id` column and carried as rows of their own, labelled by `role`, so the
hub covers every library the run produced.

`replicatesExist` and `multipleGroups` are deliberately dropped: the pipeline
writes 1 in both for every row of a design that has replicates and groups, so on
this run (and on any run the template is worth shipping for) they are constant
and back a card and a filter that can never move.

Output schema:
    sample_id : Utf8       library name every downstream file uses
    role : Utf8            "ChIP" or "input control"
    is_control : Boolean   true for the input control libraries
    antibody : Utf8        antibody of the ChIP, or the control's own prefix
    condition : Utf8       experimental condition parsed out of the sample name
    replicate : Utf8       replicate tag parsed out of the sample name (R1, R2)
    control_id : Utf8      input control of a ChIP row, null on a control row
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

_REQUIRED = ["sample_id", "control_id", "antibody"]

# `IP` in `EZH2_IP_NTKO_R1` says the library is the immunoprecipitate, not what
# was varied between samples, so it is not part of the condition.
_ASSAY_TOKENS = ["IP", "CHIP"]

_REPLICATE_SUFFIX = r"_(R\d+)$"


def _replicate() -> pl.Expr:
    """The trailing `_R<digits>` tag, or null when the run does not use one."""
    return pl.col("sample_id").str.extract(_REPLICATE_SUFFIX, 1).alias("replicate")


def _condition() -> pl.Expr:
    """What is left of the sample name once the antibody and replicate are gone.

    Token based rather than regex based: the name is split on `_`, the leading
    antibody token and an optional `IP` / `ChIP` marker are dropped, and the rest
    is rejoined. A name with nothing left (a single-token sample id) gives null
    rather than an empty string, so the column reads as "not stated".
    """
    stem = pl.col("sample_id").str.replace(_REPLICATE_SUFFIX, "")
    rest = stem.str.split("_").list.slice(1)
    without_assay = (
        pl.when(rest.list.first().str.to_uppercase().is_in(_ASSAY_TOKENS))
        .then(rest.list.slice(1))
        .otherwise(rest)
    )
    joined = without_assay.list.join("_")
    return pl.when(joined.str.len_chars() > 0).then(joined).otherwise(None).alias("condition")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Expand the ChIP design sheet to every library and parse its factors."""
    df = sources["design"]
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"chipseq design_factors: design_controls.csv lacks columns {missing}")

    chips = df.select(
        pl.col("sample_id").cast(pl.Utf8),
        pl.lit("ChIP").alias("role"),
        pl.lit(False).alias("is_control"),
        pl.col("antibody").cast(pl.Utf8).replace("", None).alias("antibody"),
        pl.col("control_id").cast(pl.Utf8).replace("", None).alias("control_id"),
    )

    # The controls are libraries of the run but rows of nobody's sheet. Their
    # "antibody" is the first token of their own name (INPUT in the megatest),
    # which keeps the antibody filter a complete partition of the cohort.
    controls = (
        df.select(pl.col("control_id").cast(pl.Utf8).replace("", None).alias("sample_id"))
        .drop_nulls()
        .unique()
        .with_columns(
            pl.lit("input control").alias("role"),
            pl.lit(True).alias("is_control"),
            pl.col("sample_id").str.split("_").list.first().alias("antibody"),
            pl.lit(None, pl.Utf8).alias("control_id"),
        )
    )

    libraries = pl.concat([chips, controls], how="diagonal_relaxed")
    libraries = libraries.with_columns(_condition(), _replicate())
    return libraries.select(list(EXPECTED_SCHEMA)).sort(
        ["is_control", "antibody", "condition", "replicate"]
    )
