"""Reads per contig, per sample, from ``samtools idxstats``.

``samtools idxstats`` reads a BAM index and writes one line per reference
contig: ``<contig> <length> <mapped reads> <unmapped reads>``, no header, with a
closing ``*`` line for reads placed on no contig. It costs nothing to run, every
alignment pipeline publishes it, and it answers three QC questions a coverage
summary hides:

* how much of the library went to the mitochondrion (a stressed or dying
  culture, or a poly-A selection that failed, sends a large share there);
* whether the X and Y counts agree with the declared sex of the sample;
* how many reads landed on unplaced, alt and decoy contigs.

So each contig is classed (``autosome``, ``X``, ``Y``, ``mitochondrion``,
``other``) from its name alone, with and without the ``chr`` prefix, and the
reads are given as a share of the sample's mapped reads.

Some pipelines publish idxstats twice per sample (rnavar and sarek: on the
aligned BAM and again after MarkDuplicates, ``<sample>.aligned.idxstats`` and
``<sample>.md.idxstats``), with the same counts. The recipe keeps one stage per
sample, the most processed one, and says which in ``stage``.

Input: every ``*.idxstats`` under the run (tab-separated, no header), with the
file path in ``source_path``.

Output schema:
    sample : Utf8              sample id, the file name without its stage tokens
    stage : Utf8               the stage token the kept file carried (md, aligned...), '' if none
    contig : Utf8              reference contig
    contig_class : Utf8        autosome, X, Y, mitochondrion or other
    length : Int64             contig length in base pairs
    mapped_reads : Int64       reads mapped to the contig
    mapped_pct : Float64       of the sample's mapped reads, percent
    reads_per_mb : Float64     mapped reads per megabase of contig
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sample_ids import ALIGNMENT_STAGE_TOKENS, strip_stage_suffixes

SOURCE_PATH_COL = "source_path"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="idxstats",
        glob_pattern="**/*.idxstats",
        format="csv",
        read_kwargs={
            "separator": "\t",
            "has_header": False,
            "new_columns": ["contig", "length", "mapped_reads", "unmapped_reads"],
            "schema_overrides": {"contig": pl.Utf8},
        },
        source_path=SOURCE_PATH_COL,
        input_schema={
            "contig": pl.Utf8,
            "length": pl.Int64,
            "mapped_reads": pl.Int64,
            SOURCE_PATH_COL: pl.Utf8,
        },
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "stage": pl.Utf8,
    "contig": pl.Utf8,
    "contig_class": pl.Utf8,
    "length": pl.Int64,
    "mapped_reads": pl.Int64,
    "mapped_pct": pl.Float64,
    "reads_per_mb": pl.Float64,
}

#: Stage tokens, most processed first: the kept file per sample is the first hit.
STAGE_PREFERENCE = ["recal", "md", "markdup", "mkd", "dedup", "cln", "sorted", "aligned", ""]

_AUTOSOME_RE = r"^(?:chr)?(?:[1-9]|[1-9][0-9])$"
_X_RE = r"^(?:chr)?X$"
_Y_RE = r"^(?:chr)?Y$"
_MITO_RE = r"^(?:chr)?(?:M|MT)$"


def _sample_and_stage(path: str) -> tuple[str, str]:
    """``reports/samtools/S1/S1.md.idxstats`` -> ``("S1", "md")``."""
    name = str(path).replace("\\", "/").rsplit("/", 1)[-1]
    stem = re.sub(r"\.idxstats$", "", name)
    sample = strip_stage_suffixes(stem, extra=ALIGNMENT_STAGE_TOKENS)
    stage = stem[len(sample) :].lstrip(".")
    return sample, stage


def _stage_rank(stage: str) -> int:
    first = stage.split(".")[-1].lower() if stage else ""
    return STAGE_PREFERENCE.index(first) if first in STAGE_PREFERENCE else len(STAGE_PREFERENCE)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Class every contig, keep one stage per sample and share the reads out."""
    raw = sources["idxstats"].filter(pl.col("contig") != "*")
    files = [
        (path, *_sample_and_stage(path))
        for path in raw.get_column(SOURCE_PATH_COL).unique().sort().to_list()
    ]
    kept: dict[str, tuple[str, str]] = {}
    for path, sample, stage in sorted(files, key=lambda f: (f[1], _stage_rank(f[2]), f[0])):
        kept.setdefault(sample, (path, stage))
    keys = pl.DataFrame(
        {
            SOURCE_PATH_COL: [p for p, _ in kept.values()],
            "sample": list(kept),
            "stage": [s for _, s in kept.values()],
        },
        schema={SOURCE_PATH_COL: pl.Utf8, "sample": pl.Utf8, "stage": pl.Utf8},
    )
    contig = pl.col("contig")
    contig_class = (
        pl.when(contig.str.contains(_AUTOSOME_RE))
        .then(pl.lit("autosome"))
        .when(contig.str.contains(_X_RE))
        .then(pl.lit("X"))
        .when(contig.str.contains(_Y_RE))
        .then(pl.lit("Y"))
        .when(contig.str.contains(_MITO_RE))
        .then(pl.lit("mitochondrion"))
        .otherwise(pl.lit("other"))
    )
    total = pl.col("mapped_reads").sum().over("sample")
    return (
        raw.join(keys, on=SOURCE_PATH_COL, how="inner")
        .with_columns(
            contig_class.alias("contig_class"),
            pl.col("length").cast(pl.Int64),
            pl.col("mapped_reads").cast(pl.Int64),
        )
        .with_columns(
            pl.when(total > 0)
            .then(pl.col("mapped_reads") * 100.0 / total)
            .otherwise(None)
            .round(4)
            .alias("mapped_pct"),
            pl.when(pl.col("length") > 0)
            .then(pl.col("mapped_reads") * 1e6 / pl.col("length"))
            .otherwise(None)
            .round(2)
            .alias("reads_per_mb"),
        )
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
        .sort(["sample", "contig"])
    )
