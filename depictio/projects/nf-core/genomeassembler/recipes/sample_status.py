"""One row per samplesheet sample: its design and what the QC tools found.

A genome assembly run is uneven by nature: an assembler can fail on one sample,
QC can be switched off for another, and a sample the samplesheet lists may
never reach the assessment stage at all. This recipe keeps every samplesheet
row, restates its design (`assembler_used`, `scaffolders`, as in
`assemblies.py`), and counts what the per-assembly table holds for it, so the
samples without any assembly QC are visible instead of silently missing from
every plot.

Inputs: the ``samplesheet`` data collection (every column passed through as
text) and the ``assemblies`` data collection (optional: a run with no assembly
QC at all still lists its samples).

Output schema (plus every samplesheet column, as text):
    sample : Utf8                  samplesheet sample
    assembler_used : Utf8          assembler(s), from the samplesheet
    scaffolders : Utf8             scaffolders switched on, comma-separated
    n_assemblies_assessed : Int64  assessed assemblies (stages) of the sample
    stages_assessed : Utf8         their stages, in pipeline order
    best_qv : Float64              highest Merqury QV over the stages
    best_busco_complete : Float64  highest BUSCO complete over the stages
    best_n50 : Int64               highest N50 over the stages
    qc_status : Utf8               "Assembly QC published" or "No assembly QC"
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="samplesheet", dc_ref="samplesheet"),
    RecipeSource(ref="assemblies", dc_ref="assemblies", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "assembler_used": pl.Utf8,
    "scaffolders": pl.Utf8,
    "n_assemblies_assessed": pl.Int64,
    "stages_assessed": pl.Utf8,
    "best_qv": pl.Float64,
    "best_busco_complete": pl.Float64,
    "best_n50": pl.Int64,
    "qc_status": pl.Utf8,
}

SAMPLE_COL = "sample"


TRUTHY = ["true", "yes", "1", "t", "y"]


def _truthy(column: str) -> pl.Expr:
    return pl.col(column).str.strip_chars().str.to_lowercase().is_in(TRUTHY).fill_null(False)


def design_columns(sheet: pl.DataFrame) -> pl.DataFrame:
    """The samplesheet as text, plus `assembler_used` and `scaffolders`.

    Same derivation as `assemblies.py` (recipes cannot import each other).
    """
    sheet = sheet.select([pl.col(c).cast(pl.Utf8) for c in sheet.columns])
    if SAMPLE_COL not in sheet.columns:
        sheet = sheet.rename({sheet.columns[0]: SAMPLE_COL})

    def _blank(column: str) -> pl.Expr:
        if column not in sheet.columns:
            return pl.lit(None, dtype=pl.Utf8)
        value = pl.col(column).str.strip_chars()
        return pl.when(value.str.len_chars() > 0).then(value).otherwise(None)

    ont, hifi = _blank("assembler_ont"), _blank("assembler_hifi")
    per_platform = pl.concat_str(
        [
            pl.when(ont.is_not_null()).then(ont + pl.lit(" (ONT)")),
            pl.when(hifi.is_not_null()).then(hifi + pl.lit(" (HiFi)")),
        ],
        separator=" + ",
        ignore_nulls=True,
    )
    assembler_used = pl.coalesce(
        _blank("assembler"),
        pl.when(per_platform.str.len_chars() > 0).then(per_platform),
    )
    scaffold_cols = [c for c in sheet.columns if c.startswith("scaffold_")]
    if scaffold_cols:
        scaffolders = pl.concat_str(
            [pl.when(_truthy(c)).then(pl.lit(c.removeprefix("scaffold_"))) for c in scaffold_cols],
            separator=", ",
            ignore_nulls=True,
        )
        scaffolders = pl.when(scaffolders.str.len_chars() > 0).then(scaffolders)
    else:
        scaffolders = pl.lit(None, dtype=pl.Utf8)
    return sheet.with_columns(
        assembler_used.alias("assembler_used"), scaffolders.alias("scaffolders")
    ).unique(subset=[SAMPLE_COL], keep="first", maintain_order=True)


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """Every samplesheet row with its assessed-assembly counts."""
    sheet = sources["samplesheet"]
    if sheet is None or sheet.is_empty():
        raise ValueError("genomeassembler sample_status: the samplesheet is empty")
    design = design_columns(sheet)

    summary_schema = {
        SAMPLE_COL: pl.Utf8,
        "n_assemblies_assessed": pl.Int64,
        "stages_assessed": pl.Utf8,
        "best_qv": pl.Float64,
        "best_busco_complete": pl.Float64,
        "best_n50": pl.Int64,
    }
    assemblies = sources.get("assemblies")
    if assemblies is not None and not assemblies.is_empty():
        summary = (
            assemblies.sort(["sample", "stage_rank", "stage"])
            .group_by(SAMPLE_COL, maintain_order=True)
            .agg(
                pl.len().cast(pl.Int64).alias("n_assemblies_assessed"),
                pl.col("stage").str.join(", ").alias("stages_assessed"),
                pl.col("qv").max().alias("best_qv"),
                pl.col("busco_complete").max().alias("best_busco_complete"),
                pl.col("n50").max().alias("best_n50"),
            )
            .select(list(summary_schema))
        )
    else:
        summary = pl.DataFrame(schema=summary_schema)

    out = design.join(summary, on=SAMPLE_COL, how="left").with_columns(
        pl.col("n_assemblies_assessed").fill_null(0),
        pl.when(pl.col("n_assemblies_assessed").fill_null(0) > 0)
        .then(pl.lit("Assembly QC published"))
        .otherwise(pl.lit("No assembly QC"))
        .alias("qc_status"),
    )
    extra = [c for c in out.columns if c not in EXPECTED_SCHEMA]
    return out.select([*EXPECTED_SCHEMA, *extra])
