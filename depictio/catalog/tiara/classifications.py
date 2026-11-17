"""Tiara's class for every sequence of an assembly.

Tiara writes one tab-separated table per assembly::

    sequence_id  class_fst_stage  class_snd_stage

with the FASTA header in full as ``sequence_id`` (the id, then its
description). The first stage is eukarya, bacteria, archaea, prokarya,
organelle or unknown; the second refines organelle into mitochondrion, plastid
or unknown (``n/a`` otherwise). Beside each table Tiara writes a
``log_<name>.txt`` that is skipped.

A pipeline may classify an assembly twice, before and after cleaning it
(nf-core/genomeqc publishes ``tiara/raw/`` and ``tiara/cleaned/``); the
directory is kept in ``stage``, so a template picks one (or both) by filter.

Input: every ``*.txt`` under a ``tiara/`` directory, one line per row, with its path in
``source_path``.

Output schema:
    genome : Utf8           assembly, from the file name
    stage : Utf8            raw or cleaned when the directory says so, else ''
    sequence : Utf8         sequence id (the header up to its first space)
    class_fst_stage : Utf8  Tiara's first-stage class
    class_snd_stage : Utf8  its organelle call, null when not organellar
    tiara_class : Utf8      one class: the organelle call for an organellar
                            sequence (``organelle`` when unknown), the first stage otherwise
    is_eukaryotic : Boolean eukarya, mitochondrion or plastid
"""

from __future__ import annotations

from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCE_PATH_COL = "source_path"
RAW_LINE_COL = "raw_line"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="tables",
        glob_pattern="**/tiara/**/*.txt",
        format="csv",
        # One line per row: the logs beside the tables are ragged, so the
        # columns are split here, after the logs are dropped.
        read_kwargs={
            "separator": "\x1e",
            "has_header": False,
            "new_columns": [RAW_LINE_COL],
            "quote_char": None,
            "infer_schema_length": 0,
        },
        source_path=SOURCE_PATH_COL,
        input_schema={RAW_LINE_COL: pl.Utf8, SOURCE_PATH_COL: pl.Utf8},
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome": pl.Utf8,
    "stage": pl.Utf8,
    "sequence": pl.Utf8,
    "class_fst_stage": pl.Utf8,
    "class_snd_stage": pl.Utf8,
    "tiara_class": pl.Utf8,
    "is_eukaryotic": pl.Boolean,
}

STAGES = ("raw", "cleaned")


def genome_of(source_path: str) -> str:
    return PurePosixPath(str(source_path).replace("\\", "/")).name.removesuffix(".txt")


def stage_of(source_path: str) -> str:
    parts = PurePosixPath(str(source_path).replace("\\", "/")).parts
    return next((p for p in reversed(parts[:-1]) if p in STAGES), "")


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    lines = sources["tables"]
    names = pl.col(SOURCE_PATH_COL).map_elements(
        lambda p: PurePosixPath(str(p)).name, return_dtype=pl.Utf8
    )
    cells = pl.col(RAW_LINE_COL).str.split("\t")
    raw = (
        lines.filter(~names.str.starts_with("log_") & pl.col(RAW_LINE_COL).str.contains("\t"))
        .with_columns(
            cells.list.get(0, null_on_oob=True).alias("sequence_id"),
            cells.list.get(1, null_on_oob=True).alias("class_fst_stage"),
            cells.list.get(2, null_on_oob=True).alias("class_snd_stage"),
        )
        .filter(pl.col("sequence_id") != "sequence_id")
    )
    first = pl.col("class_fst_stage").str.strip_chars().str.to_lowercase()
    second = pl.col("class_snd_stage").str.strip_chars().str.to_lowercase().replace("n/a", None)
    frame = raw.filter(
        pl.col("sequence_id").is_not_null() & pl.col("class_fst_stage").is_not_null()
    ).select(
        pl.col(SOURCE_PATH_COL).map_elements(genome_of, return_dtype=pl.Utf8).alias("genome"),
        pl.col(SOURCE_PATH_COL).map_elements(stage_of, return_dtype=pl.Utf8).alias("stage"),
        pl.col("sequence_id").str.strip_chars().str.split(" ").list.first().alias("sequence"),
        first.alias("class_fst_stage"),
        second.alias("class_snd_stage"),
    )
    if frame.is_empty():
        raise ValueError("tiara_classifications: the Tiara tables hold no sequence")
    tiara_class = (
        pl.when(pl.col("class_fst_stage") == "organelle")
        .then(
            pl.when(pl.col("class_snd_stage").is_in(["mitochondrion", "plastid"]))
            .then(pl.col("class_snd_stage"))
            .otherwise(pl.lit("organelle"))
        )
        .otherwise(pl.col("class_fst_stage"))
    )
    return (
        frame.with_columns(tiara_class.alias("tiara_class"))
        .with_columns(
            pl.col("tiara_class")
            .is_in(["eukarya", "mitochondrion", "plastid"])
            .alias("is_eukaryotic")
        )
        .select(list(OUTPUT_SCHEMA))
        .sort(["genome", "stage", "sequence"])
    )
