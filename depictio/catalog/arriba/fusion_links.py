"""Turn Arriba's ``fusions.tsv`` into one breakpoint-pair link per fusion call.

``arriba/fusions.py`` already tidies the same file into the fusion table every
other panel binds. This recipe is the coordinate view of it: the two breakpoints
Arriba writes as ``chr:pos`` strings become four bindable columns
(``chrom_a`` / ``pos_a`` / ``chrom_b`` / ``pos_b``), which is the canonical
``genome_chord`` row and is what lets a run's fusions be read as a partner map
rather than as a list of names.

Splitting the breakpoints is the whole point: the strings are not plottable, and
until they are parsed a translocation between chr8 and chr10 and a read-through
within chr4 look the same in every table on the dashboard.

The evidence columns are summed into one ``weight`` (split reads on both sides
plus discordant mates) because chord width is one number, and Arriba's ``type``
and ``confidence`` come through unchanged so the ring can be coloured by event
class and the dashboard filtered down to the high-confidence calls.

Rows whose breakpoint does not parse as ``chr:pos`` are dropped rather than
placed at position 0: a chord drawn at the wrong locus is worse than a chord
that is not drawn, and the renderer already reports how many links it left out.

The per-sample file carries no sample column, so the source declares
``source_path`` and the sample is read off the file name.

Output columns:
    sample, label, chrom_a, pos_a, chrom_b, pos_b, weight, category, confidence
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

# The sample exists only in the file NAME (`arriba/<sample>.arriba.fusions.tsv`): the source hands every
# row the path of its file, and the sample is the basename minus the suffix.
# Without it a cohort run pools every sample's calls into one table.
_SOURCE_PATH = "_source_path"
_SAMPLE_SUFFIX = ".arriba.fusions.tsv"


def _sample() -> pl.Expr:
    """``arriba/S1.arriba.fusions.tsv`` -> ``S1``."""
    return (
        pl.col(_SOURCE_PATH)
        .str.split("/")
        .list.last()
        .str.strip_suffix(_SAMPLE_SUFFIX)
        .alias("sample")
    )


SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="fusions",
        source_path=_SOURCE_PATH,
        glob_pattern="arriba/*.arriba.fusions.tsv",
        format="TSV",
        read_kwargs={
            "infer_schema_length": 10000,
            "quote_char": None,
            # Arriba's placeholder for "not available"; the read-count columns
            # never carry it, so they still parse as integers.
            "null_values": ["."],
        },
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "label": pl.Utf8,
    "chrom_a": pl.Utf8,
    "pos_a": pl.Int64,
    "chrom_b": pl.Utf8,
    "pos_b": pl.Int64,
    "weight": pl.Int64,
    "category": pl.Utf8,
    "confidence": pl.Utf8,
}


def _text(name: str) -> pl.Expr:
    """Read a text column as a never-null string so no render binds a null."""
    return pl.col(name).cast(pl.Utf8).fill_null("")


def _count(name: str) -> pl.Expr:
    """Read a read-count column as a never-null integer."""
    return pl.col(name).cast(pl.Int64, strict=False).fill_null(0)


def _breakpoint(name: str) -> list[pl.Expr]:
    """Split one ``chr:pos`` breakpoint into a chromosome and a position.

    Written with a full split rather than a two-way one so a caller that appends
    a third field (a strand, in some Arriba forks and in most SV callers) still
    yields the two fields that matter instead of parsing the position as
    ``1806934:+``.
    """
    parts = pl.col(name).cast(pl.Utf8).str.split(":")
    return [
        parts.list.get(0, null_on_oob=True).alias(f"_chrom_{name}"),
        parts.list.get(1, null_on_oob=True).cast(pl.Int64, strict=False).alias(f"_pos_{name}"),
    ]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per fusion call, as a pair of genomic loci with its evidence."""
    df = sources["fusions"]

    parsed = df.with_columns(*_breakpoint("breakpoint1"), *_breakpoint("breakpoint2")).filter(
        pl.col("_chrom_breakpoint1").is_not_null()
        & pl.col("_chrom_breakpoint2").is_not_null()
        & pl.col("_pos_breakpoint1").is_not_null()
        & pl.col("_pos_breakpoint2").is_not_null()
    )

    return parsed.select(
        _sample(),
        pl.concat_str(_text("#gene1"), pl.lit("--"), _text("gene2")).alias("label"),
        pl.col("_chrom_breakpoint1").alias("chrom_a"),
        pl.col("_pos_breakpoint1").alias("pos_a"),
        pl.col("_chrom_breakpoint2").alias("chrom_b"),
        pl.col("_pos_breakpoint2").alias("pos_b"),
        (_count("split_reads1") + _count("split_reads2") + _count("discordant_mates")).alias(
            "weight"
        ),
        _text("type").alias("category"),
        _text("confidence").alias("confidence"),
    ).select(list(EXPECTED_SCHEMA))
