"""Sequences left after each V(D)J annotation and QC step, one row per sample.

airrflow's report writes
``repertoire_comparison/Sequence_numbers_summary/Table_sequences_assembled.tsv``
on every route that runs it: the Change-O and enchantR chain that follows read
processing (IgBLAST assignment, MakeDb, quality filter, productive split,
junction-length filter, metadata, germlines, chimera filter, duplicate
collapse). It does not depend on pRESTO or on the clonal analysis, so it is the
sequence count a run still has when either is missing:

* ``--mode assembled`` never runs pRESTO, so ``parsed_logs/`` is absent and
  ``enchantr/sequence_counts`` has nothing to read. With ``--reassign`` (the
  default) the chain opens on ``ConvertDb-fasta``, the assembled AIRR table
  turned back into FASTA for IgBLAST.
* ``--skip_clonal_analysis`` writes no ``clonal_analysis/``, but the report
  still runs on the repertoires after QC.

``input`` is the first stage a sample logged: the sequences that entered
annotation (``ConvertDb-fasta`` or ``AssignGenes-igblast``; a run that skipped
reassignment logs its first count after the quality filter). ``collapsed`` is
the unique annotated sequences after duplicate collapse, the per-sample total
the report's V family table counts. The table is written with R's character
padding (`` 59111``), so every count is stripped before it is cast, and an
``NA`` stage reads as null.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="changeo",
        path="repertoire_comparison/Sequence_numbers_summary/Table_sequences_assembled.tsv",
        format="TSV",
        input_schema={"sample_id": pl.Utf8, "CollapseDuplicates": pl.Utf8},
        read_kwargs={"infer_schema_length": 0},
    ),
]

# Output column -> the report's task column, in pipeline order.
_STAGES: dict[str, str] = {
    "converted": "ConvertDb-fasta",
    "igblast_assigned": "AssignGenes-igblast",
    "annotated": "MakeDB-igblast",
    "quality_pass": "FilterQuality",
    "productive": "ParseDb-split",
    "junction_mod3": "FilterJunctionMod3",
    "germlines": "CreateGermlines",
    "chimera_pass": "RemoveChimeric",
    "collapsed": "CollapseDuplicates",
}

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "input": pl.Int64,  # first stage the sample logged: sequences entering annotation
    "collapsed": pl.Int64,  # unique annotated sequences after duplicate collapse
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    name: pl.Int64 for name in _STAGES if name != "collapsed"
}


def _count(column: str) -> pl.Expr:
    return pl.col(column).cast(pl.Utf8).str.strip_chars().cast(pl.Int64, strict=False)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per sample: every stage the run logged, plus its first count."""
    df = sources["changeo"]
    present = {name: raw for name, raw in _STAGES.items() if raw in df.columns}
    out = df.select(
        pl.col("sample_id").cast(pl.Utf8).str.strip_chars(),
        *(_count(raw).alias(name) for name, raw in present.items()),
    ).filter(pl.col("sample_id").is_not_null() & (pl.col("sample_id") != ""))
    out = out.with_columns(pl.coalesce([pl.col(name) for name in present]).alias("input"))
    return out.select("sample_id", "input", *present).sort("sample_id")
