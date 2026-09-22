"""Nonpareil redundancy summaries -> the coverage curve each of them stands for.

``NONPAREIL_SET`` merges every library's ``.npo`` into one small table, written by R's
``write.table`` so the library id sits in an unnamed first column::

    <blank>  kappa  C  LR  modelR  LRstar  diversity
    MOCK_001_Illumina_Hiseq_3000_1  0.57019  0.59837  102758434.2  0.99799  ...

Six fitted numbers per library, and no curve: the per-effort redundancy samples stay
inside the ``.npo`` files, which nf-core pipelines do not publish. The curve is what
Nonpareil is run for, so this recipe rebuilds it from the model those numbers
describe - a gamma CDF on the log of the sequencing effort, whose mean is the
published ``diversity`` and whose 95th percentile is ``ln(LRstar)``. The arithmetic,
and the round-trip check that keeps it honest, live in
``depictio/recipes/lib/nonpareil.py``.

The library id carries the run accession (``..._1``, ``..._2``), so a sample
sequenced over two runs contributes two curves. The samplesheet is joined in as an
optional source to recover the sample the run belongs to, which is what lets the
persistent sample filter reach this collection; without it ``sample`` falls back to
the library id.

``profile`` tiles are never downsampled by the backend, so the effort axis is
decimated here to ``POINTS`` values per curve.

Output (one row per library x effort step):
    sample, library, platform, sequencing_effort, coverage,
    observed_effort, projected_effort, diversity
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.nonpareil import (
    attribute_library,
    coverage,
    effort_grid,
    fit_model,
    samplesheet_lookup,
)

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="summaries",
        glob_pattern="nonpareil/*all_samples.tsv",
        format="tsv",
        # write.table emits one fewer header field than the rows carry, so the
        # header is skipped and the columns are named here instead.
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
    "sequencing_effort": pl.Float64,
    "coverage": pl.Float64,
    "observed_effort": pl.Float64,
    "projected_effort": pl.Float64,
    "diversity": pl.Float64,
}

OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

# The `profile` kind asks recipes to decimate to at most 200 points per series.
POINTS = 200


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Fit each library's model and sample it over a log-spaced effort axis."""
    summaries = sources["summaries"]
    if "library" not in summaries.columns:
        raise ValueError("nonpareil curves: the summary reader produced no `library` column")

    numeric = ("coverage", "lr", "lr_star", "diversity")
    frame = summaries.with_columns(
        pl.col("library").cast(pl.Utf8).str.strip_chars('" '),
        *[pl.col(col).cast(pl.Float64, strict=False) for col in numeric],
    ).filter(
        pl.col("library").is_not_null()
        & (pl.col("diversity") > 0)
        & (pl.col("lr_star") > 1)
        & (pl.col("lr") > 1)
    )
    if frame.is_empty():
        raise ValueError("nonpareil curves: no library carried a usable model fit")

    lookup = samplesheet_lookup(sources.get("samples"))
    rows: dict[str, list] = {key: [] for key in EXPECTED_SCHEMA}
    for row in frame.iter_rows(named=True):
        library = row["library"]
        sample, platform = attribute_library(library, lookup)
        lr = float(row["lr"])
        lr_star = float(row["lr_star"])
        diversity = float(row["diversity"])
        shape, scale = fit_model(diversity, lr_star)
        for effort in effort_grid(lr, lr_star, POINTS):
            rows["sample"].append(sample)
            rows["library"].append(library)
            rows["platform"].append(platform)
            rows["sequencing_effort"].append(effort)
            rows["coverage"].append(coverage(shape, scale, effort))
            rows["observed_effort"].append(lr)
            rows["projected_effort"].append(lr_star)
            rows["diversity"].append(diversity)

    return pl.DataFrame(rows, schema=dict(EXPECTED_SCHEMA)).sort(["library", "sequencing_effort"])
