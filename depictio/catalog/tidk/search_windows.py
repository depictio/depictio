"""Telomeric repeats per window along every sequence, from ``tidk search``.

``tidk search`` writes one tab-separated table per assembly::

    id  window  forward_repeat_number  reverse_repeat_number  telomeric_repeat

one row per window of ``--window`` bases (10 kb by default) along each
sequence. ``window`` is the window's END: the last window of a sequence ends at
the sequence's length, so the table also gives every sequence its length
(``sequence_length``), which a karyotype of a genome with no assembly table
needs.

The assembly is named after the file: tidk's own ``<name>_telomeric_repeat_windows.tsv``,
or the ``<name>.tsv`` a pipeline renames it to (nf-core/genomeqc publishes
``tidk/<assembly>/search/aposteriori/<assembly>.tsv``). ``search`` is
``apriori`` (a repeat the run was given, ``--repeat``) or ``aposteriori`` (the
unit ``tidk explore`` picked) when the path says so. When an assembly was
searched both ways, the a priori search is kept: it is the known telomere, the
a posteriori one only the best guess.

Input: every ``*.tsv`` below a ``search/`` directory, with its path in
``source_path``.

Output schema:
    genome : Utf8              assembly, from the file name
    sequence : Utf8            sequence (chromosome, scaffold or contig) id
    start : Int64              window start, 0-based
    end : Int64                window end, exclusive (tidk's ``window``)
    forward_repeats : Int64    repeat units on the forward strand in the window
    reverse_repeats : Int64    repeat units on the reverse strand
    repeats : Int64            both strands
    repeat_unit : Utf8         the unit counted
    search : Utf8              apriori, aposteriori, or '' when the path does not say
    sequence_length : Int64    end of the sequence's last window, its length
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCE_PATH_COL = "source_path"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="windows",
        glob_pattern="**/search/**/*.tsv",
        format="csv",
        read_kwargs={
            "separator": "\t",
            "infer_schema_length": 0,
        },
        source_path=SOURCE_PATH_COL,
        input_schema={
            "id": pl.Utf8,
            "window": pl.Utf8,
            "forward_repeat_number": pl.Utf8,
            "reverse_repeat_number": pl.Utf8,
            SOURCE_PATH_COL: pl.Utf8,
        },
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome": pl.Utf8,
    "sequence": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "forward_repeats": pl.Int64,
    "reverse_repeats": pl.Int64,
    "repeats": pl.Int64,
    "repeat_unit": pl.Utf8,
    "search": pl.Utf8,
    "sequence_length": pl.Int64,
}

#: Search kinds, preferred first.
SEARCH_PREFERENCE = ["apriori", "aposteriori", ""]

_SUFFIX = re.compile(r"(?:_telomeric_repeat_windows)?\.tsv$")


def genome_of(source_path: str) -> str:
    """``tidk/A/search/aposteriori/A.tsv`` -> ``A``."""
    return _SUFFIX.sub("", PurePosixPath(source_path.replace("\\", "/")).name)


def search_of(source_path: str) -> str:
    """``apriori`` or ``aposteriori`` when a directory of the path names it, else ''."""
    parts = PurePosixPath(source_path.replace("\\", "/")).parts
    for kind in ("apriori", "aposteriori"):
        if kind in parts:
            return kind
    return ""


def _int(column: str) -> pl.Expr:
    return pl.col(column).cast(pl.Utf8).str.strip_chars().cast(pl.Int64, strict=False)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per window, the start derived and the sequence length attached."""
    raw = sources["windows"]
    if "telomeric_repeat" not in raw.columns:
        raw = raw.with_columns(pl.lit(None, dtype=pl.Utf8).alias("telomeric_repeat"))
    frame = (
        raw.filter(pl.col("id").is_not_null() & (pl.col("id") != ""))
        .with_columns(
            pl.col(SOURCE_PATH_COL).map_elements(genome_of, return_dtype=pl.Utf8).alias("genome"),
            pl.col(SOURCE_PATH_COL).map_elements(search_of, return_dtype=pl.Utf8).alias("search"),
            pl.col("id").cast(pl.Utf8).alias("sequence"),
            _int("window").alias("end"),
            _int("forward_repeat_number").fill_null(0).alias("forward_repeats"),
            _int("reverse_repeat_number").fill_null(0).alias("reverse_repeats"),
            pl.col("telomeric_repeat").cast(pl.Utf8).alias("repeat_unit"),
        )
        .drop_nulls(["end"])
    )
    if frame.is_empty():
        raise ValueError("tidk_search_windows: no window row in the tidk search tables")

    # One search per assembly, the a priori one when the run did both.
    rank = pl.col("search").replace_strict(
        {k: i for i, k in enumerate(SEARCH_PREFERENCE)}, default=len(SEARCH_PREFERENCE)
    )
    best = frame.select("genome", rank.alias("_rank")).group_by("genome").agg(pl.min("_rank"))
    frame = frame.with_columns(rank.alias("_rank")).join(best, on=["genome", "_rank"])

    by_sequence = ["genome", "search", "sequence"]
    return (
        frame.sort([*by_sequence, "end"])
        .with_columns(
            pl.col("end").shift(1, fill_value=0).over(by_sequence).alias("start"),
            (pl.col("forward_repeats") + pl.col("reverse_repeats")).alias("repeats"),
            pl.col("end").max().over(by_sequence).alias("sequence_length"),
        )
        .unique(subset=[*by_sequence, "end"], keep="first", maintain_order=True)
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
    )
