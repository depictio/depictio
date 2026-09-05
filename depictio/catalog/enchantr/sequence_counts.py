"""Sequences left after every pRESTO and Change-O step, one wide row per sample.

airrflow's log parser writes ``parsed_logs/Table_sequences_process.tsv`` (the
pRESTO pre-processing chain: raw reads, quality filter, primer masking, mate
pairing, UMI consensus, pair assembly, deduplication, representatives seen at
least twice) and the report adds
``repertoire_comparison/Sequence_numbers_summary/Table_sequences_assembled.tsv``
(the Change-O chain: IgBLAST assignment, MakeDb, quality filter, productive
split, junction-length filter, duplicate collapse). Both are joined on
``sample_id`` and the stage columns renamed to a stable snake_case vocabulary.

Read/mate columns are collapsed to the mate that survived least
(``min(R1, R2)``) so the stage counts fall monotonically and the funnel is
honest. Note that ``consensus``, ``unique`` and ``representative`` COLLAPSE
reads onto UMI groups rather than discarding them, so a large drop there is
expected rather than a QC failure.

``retention`` is the fraction of raw reads still represented at the last stage
the run produced. Sample metadata columns carried by the log table (species,
tissue, sex ...) are dropped: they belong to the samplesheet.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="presto",
        path="parsed_logs/Table_sequences_process.tsv",
        format="TSV",
        read_kwargs={"infer_schema_length": 0},
    ),
    RecipeSource(
        ref="changeo",
        path="repertoire_comparison/Sequence_numbers_summary/Table_sequences_assembled.tsv",
        format="TSV",
        read_kwargs={"infer_schema_length": 0},
        optional=True,
    ),
]

# Output column -> the raw column(s) it comes from, in pipeline order. A tuple
# of two names is a read-pair stage: the surviving count is the smaller mate.
_PRESTO_STAGES: dict[str, tuple[str, ...]] = {
    "sequences": ("Sequences",),
    "quality_filtered": ("Filtered_quality_R1", "Filtered_quality_R2"),
    "primers_masked": ("Mask_primers_R1", "Mask_primers_R2"),
    "paired": ("Paired",),
    "consensus": ("Build_consensus",),
    "assembled": ("Assemble_pairs",),
    "unique": ("Unique",),
    "representative": ("Representative_2",),
}
_CHANGEO_STAGES: dict[str, tuple[str, ...]] = {
    "igblast_assigned": ("AssignGenes-igblast",),
    "annotated": ("MakeDB-igblast",),
    "quality_pass": ("FilterQuality",),
    "productive": ("ParseDb-split",),
    "junction_mod3": ("FilterJunctionMod3",),
    "collapsed": ("CollapseDuplicates",),
}
STAGE_ORDER: list[str] = [*_PRESTO_STAGES, *_CHANGEO_STAGES]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "subject_id": pl.Utf8,
    "sequences": pl.Int64,
    "retention": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {
    name: pl.Int64 for name in STAGE_ORDER if name != "sequences"
}


def _subject(df: pl.DataFrame) -> pl.Expr:
    """The clone-definition group. A log table without one gets a single group."""
    if "subject_id" in df.columns:
        return pl.col("subject_id").cast(pl.Utf8).str.strip_chars()
    return pl.lit("all", dtype=pl.Utf8).alias("subject_id")


def _stage(raw_cols: tuple[str, ...], available: list[str]) -> pl.Expr | None:
    """Count for one stage: the raw column, or the smaller of a read pair."""
    present = [c for c in raw_cols if c in available]
    if not present:
        return None
    counts = [
        pl.col(c).cast(pl.Utf8).str.strip_chars().cast(pl.Int64, strict=False) for c in present
    ]
    return counts[0] if len(counts) == 1 else pl.min_horizontal(counts)


def _stage_columns(df: pl.DataFrame, stages: dict[str, tuple[str, ...]]) -> list[pl.Expr]:
    exprs = []
    for name, raw_cols in stages.items():
        expr = _stage(raw_cols, df.columns)
        if expr is not None:
            exprs.append(expr.alias(name))
    return exprs


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Join the pRESTO and Change-O stage counts into one wide row per sample."""
    presto = sources["presto"]
    sample = pl.col("sample_id").cast(pl.Utf8).str.strip_chars()
    out = presto.select(sample, _subject(presto), *_stage_columns(presto, _PRESTO_STAGES))

    changeo = sources.get("changeo")
    if changeo is not None:
        out = out.join(
            changeo.select(sample, *_stage_columns(changeo, _CHANGEO_STAGES)),
            on="sample_id",
            how="left",
        )

    present = [c for c in STAGE_ORDER if c in out.columns]
    out = out.with_columns(
        (pl.col(present[-1]).cast(pl.Float64) / pl.col("sequences").cast(pl.Float64)).alias(
            "retention"
        )
    )
    return out.select("sample_id", "subject_id", *present, "retention").sort("sample_id")
