"""Read fates through the airrflow pre-processing funnel, shaped for a Sankey.

From the same per-step counts as ``sequence_counts`` (the ``parsed_logs/``
pRESTO table plus the report's Change-O table) this recipe emits one row per
sample and loss point. Reads that survive to the end carry every milestone
label; reads that stop at a milestone carry the labels up to the previous one
and ``Lost`` from there on. ``reads`` weights the row, so a Sankey over the
milestone columns draws the funnel with the losses peeling off into a growing
``Lost`` lane.

Counts are made monotonic before the differences are taken (read-pair stages
collapse to the smaller mate, and a stage that reports more than its
predecessor is clamped), so no loss can come out negative.

The six pRESTO milestone columns are always emitted so the Sankey binding is
stable across library preparations: a run whose logs never reported a stage
(no UMI consensus, say) still gets the column, labelled ``Not run``, and the
reads flow straight through it rather than a loss being invented. The two
Change-O milestones (``productive``, ``collapsed``) need the repertoire
comparison report and are left out when it is absent.
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

# (output column, node label, raw column(s)) in pipeline order. A pair of raw
# columns is a read-pair stage: the surviving count is the smaller mate.
_MILESTONES: list[tuple[str, str, tuple[str, ...]]] = [
    ("input", "Input reads", ("Sequences",)),
    ("quality", "Quality filtered", ("Filtered_quality_R1", "Filtered_quality_R2")),
    ("paired", "Paired", ("Paired",)),
    ("consensus", "UMI consensus", ("Build_consensus",)),
    ("assembled", "Assembled", ("Assemble_pairs",)),
    ("representative", "Representative", ("Representative_2",)),
    ("productive", "Productive", ("ParseDb-split",)),
    ("collapsed", "Unique sequences", ("CollapseDuplicates",)),
]
LOST = "Lost"
NOT_RUN = "Not run"
# Milestones from the always-present pRESTO log; emitted whether or not the run
# reported them, so a dashboard can bind the same steps everywhere.
_PRESTO_MILESTONES = _MILESTONES[:6]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "subject_id": pl.Utf8,
    **{out: pl.Utf8 for out, _, _ in _PRESTO_MILESTONES},
    "reads": pl.Int64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {out: pl.Utf8 for out, _, _ in _MILESTONES[6:]}


def _subject(df: pl.DataFrame) -> pl.Expr:
    """The clone-definition group. A log table without one gets a single group."""
    if "subject_id" in df.columns:
        return pl.col("subject_id").cast(pl.Utf8).str.strip_chars()
    return pl.lit("all", dtype=pl.Utf8).alias("subject_id")


def _stage(raw_cols: tuple[str, ...], available: list[str]) -> pl.Expr | None:
    present = [c for c in raw_cols if c in available]
    if not present:
        return None
    counts = [
        pl.col(c).cast(pl.Utf8).str.strip_chars().cast(pl.Int64, strict=False) for c in present
    ]
    return counts[0] if len(counts) == 1 else pl.min_horizontal(counts)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Expand per-stage counts into one weighted fate path per sample and loss point."""
    sample = pl.col("sample_id").cast(pl.Utf8).str.strip_chars()
    counts = sources["presto"].with_columns(sample)
    changeo = sources.get("changeo")
    if changeo is not None:
        counts = counts.join(
            changeo.with_columns(sample), on="sample_id", how="left", suffix="_changeo"
        )
    # pRESTO milestones are always kept (a stage the logs never reported becomes
    # a pass-through labelled "Not run"); Change-O ones only when they resolved.
    milestones: list[tuple[str, str, pl.Expr | None]] = [
        (out, label, _stage(raw, counts.columns)) for out, label, raw in _PRESTO_MILESTONES
    ]
    milestones += [
        (out, label, expr)
        for out, label, raw in _MILESTONES[6:]
        if (expr := _stage(raw, counts.columns)) is not None
    ]
    stage_cols = [out for out, _, _ in milestones]
    labels = [label if expr is not None else NOT_RUN for _, label, expr in milestones]
    counts = counts.select(
        pl.col("sample_id"),
        _subject(counts),
        *[
            (expr if expr is not None else pl.lit(None, dtype=pl.Int64)).alias(out)
            for out, _, expr in milestones
        ],
    )

    rows: list[dict] = []
    for rec in counts.iter_rows(named=True):
        running = rec[stage_cols[0]] or 0
        remaining = [running]
        for col in stage_cols[1:]:
            value = rec[col]
            running = min(running, value if value is not None else running)
            remaining.append(running)
        base = {"sample_id": rec["sample_id"], "subject_id": rec["subject_id"]}
        for k in range(1, len(stage_cols)):
            lost = remaining[k - 1] - remaining[k]
            if lost <= 0:
                continue
            path = labels[:k] + [LOST] * (len(stage_cols) - k)
            rows.append({**base, **dict(zip(stage_cols, path)), "reads": lost})
        rows.append({**base, **dict(zip(stage_cols, labels)), "reads": remaining[-1]})

    schema: dict[str, type[pl.DataType]] = {"sample_id": pl.Utf8, "subject_id": pl.Utf8}
    schema.update({c: pl.Utf8 for c in stage_cols})
    schema["reads"] = pl.Int64
    return pl.DataFrame(rows, schema=schema).sort(["sample_id", "reads"], descending=[False, True])
