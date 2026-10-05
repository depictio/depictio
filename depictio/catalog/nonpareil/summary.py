"""Nonpareil's per-library fit, tidied into one row per sequencing library.

Same source file as ``curves.py`` (``nonpareil_all_samples.tsv``, written by R's
``write.table`` with an unnamed id column), read here without expanding the model:
the six fitted numbers are the readings a card strip is made of, and a card that
averaged them over an expanded 200-point curve would count every library 200 times.

``coverage`` is the share of the metagenome the reads already reach;
``projected_effort`` is the sequencing effort Nonpareil projects for 95% coverage,
so ``projected_effort / observed_effort`` is how many times deeper the run would have
to go. ``diversity`` (Nd) is Nonpareil's diversity index, on a log scale where about
17-21 spans soil to marine communities.

Output (one row per library): sample, library, platform, kappa, coverage,
observed_effort, model_fit, projected_effort, diversity, effort_multiple.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.nonpareil import attribute_library, samplesheet_lookup

# Recipes are loaded by file path, not as a package, so a sibling recipe cannot be
# imported: the source declaration is repeated rather than shared with curves.py.
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summaries",
        glob_pattern="nonpareil/*all_samples.tsv",
        format="tsv",
        read_kwargs={
            "has_header": False,
            "skip_rows": 1,
            "new_columns": [
                "library",
                "kappa",
                "coverage",
                "lr",
                "model_r",
                "lr_star",
                "diversity",
            ],
            "truncate_ragged_lines": True,
        },
    ),
    RecipeSource(ref="samples", dc_ref="samplesheet", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "library": pl.Utf8,
    "platform": pl.Utf8,
    "kappa": pl.Float64,
    "coverage": pl.Float64,
    "observed_effort": pl.Float64,
    "model_fit": pl.Float64,
    "projected_effort": pl.Float64,
    "diversity": pl.Float64,
    "effort_multiple": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Type the summary table, attribute each library to a sample and derive the gap."""
    summaries = sources["summaries"]
    if "library" not in summaries.columns:
        raise ValueError("nonpareil summary: the summary reader produced no `library` column")

    numeric = ("kappa", "coverage", "lr", "model_r", "lr_star", "diversity")
    frame = summaries.with_columns(
        pl.col("library").cast(pl.Utf8).str.strip_chars('" '),
        *[pl.col(col).cast(pl.Float64, strict=False) for col in numeric],
    ).filter(pl.col("library").is_not_null() & (pl.col("library") != ""))
    if frame.is_empty():
        raise ValueError("nonpareil summary: no library row survived parsing")

    lookup = samplesheet_lookup(sources.get("samples"))
    attributed = [attribute_library(library, lookup) for library in frame["library"].to_list()]

    return (
        frame.with_columns(
            pl.Series("sample", [pair[0] for pair in attributed], dtype=pl.Utf8),
            pl.Series("platform", [pair[1] for pair in attributed], dtype=pl.Utf8),
        )
        .with_columns(
            pl.col("lr").alias("observed_effort"),
            pl.col("model_r").alias("model_fit"),
            pl.col("lr_star").alias("projected_effort"),
            # A library with no observed effort has no multiple, not an infinite one.
            pl.when(pl.col("lr") > 0)
            .then(pl.col("lr_star") / pl.col("lr"))
            .otherwise(None)
            .cast(pl.Float64)
            .alias("effort_multiple"),
        )
        .select(*EXPECTED_SCHEMA)
        .sort("library")
    )
