"""Per-contig depth, from the ``Coverage per contig`` block of genome_results.txt.

Qualimap BamQC closes ``genome_results.txt`` with one line per reference
sequence, tab-separated and leading-tab indented::

    >>>>>>> Coverage per contig

        NC_044048.1  30875876  27566110  0.8928041426257833  1.2222801402423151
        NC_044049.1  28732775  22680740  0.7893682388839922  1.1810230248064657

which is contig, length, mapped bases, mean depth, depth standard deviation.
The genome-wide mean in the ``Coverage`` block above it hides everything this
shows: whether a library is spread evenly, whether one scaffold soaked up the
reads, and, on an assembly with a known sex chromosome, the relative depth a
sex call is made from.

The relative depth (contig mean over the library's length-weighted genome mean)
is added here because it is the comparable quantity: raw per-contig means move
with the library's overall depth, the ratio does not.

Reads the same ``genome_results.txt`` scan as
``qualimap/bamqc_genome_results.py``: one LINE per row, with
``include_file_paths: source_path``, so a template that already declares the
summary needs no second raw collection.

Output schema:
    sample : Utf8             library Qualimap ran on
    chromosome : Utf8         contig / chromosome name
    length : Int64            contig length, bp
    mapped_bases : Int64      bases of mapped reads placed on the contig
    mean_coverage : Float64   mean depth over the contig, X
    coverage_std : Float64    standard deviation of that depth
    relative_coverage : Float64  mean_coverage over the library's genome-wide mean
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.qualimap_raw import CONTIG_MARKER, contig_coverage_block

#: Data-collection tag the template must scan the BamQC reports into. Shared
#: with ``qualimap/bamqc_genome_results.py``, which reads the same files.
RAW_DC_TAG = "qualimap_bamqc_genome_results_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="lines", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "chromosome": pl.Utf8,
    "length": pl.Int64,
    "mapped_bases": pl.Int64,
    "mean_coverage": pl.Float64,
    "coverage_std": pl.Float64,
    "relative_coverage": pl.Float64,
}

_RECIPE = "qualimap_coverage_per_contig"
_NUMERIC = ["length", "mapped_bases", "mean_coverage", "coverage_std"]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (sample, contig)."""
    # A contig line short of one of its four numbers is not a row here: the
    # relative depth below needs all of them.
    frame = contig_coverage_block(sources["lines"], recipe=_RECIPE).drop_nulls(_NUMERIC)
    if frame.is_empty():
        raise ValueError(
            f"{_RECIPE}: no report carried a '{CONTIG_MARKER}' block; Qualimap "
            f"omits it when the reference has a single sequence"
        )

    genome_mean = (pl.col("mapped_bases").sum() / pl.col("length").sum()).over("sample")
    return (
        frame.with_columns(
            pl.when(genome_mean > 0)
            .then(pl.col("mean_coverage") / genome_mean)
            .otherwise(None)
            .cast(pl.Float64)
            .alias("relative_coverage")
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "chromosome"])
    )
