"""Where each library sits among the others: a PCA and its correlation along the time course.

Over the genes detected (10 reads) in at least half of the libraries, on
``log2(cpm + 1)`` (``depictio/recipes/lib/count_matrix.py``, the selection the
correlation heatmap reads too):

* ``pc1`` to ``pc3``: the library's coordinates on the first components of a
  PCA over the 2,000 most variable of those genes, with the share of variance
  each explains. In a time course the first component is usually time itself;
* ``corr_to_baseline``: Spearman correlation with the mean profile of the
  baseline libraries (the earliest time point). It falls as the response
  unfolds and, after a transient response, comes back;
* ``corr_to_previous``: Spearman correlation with the mean profile of the
  previous time point. A dip marks the step where transcription changed most.

The design columns of the hub ride along, so the embedding colours its points by
``{GROUP_COL}``.

Sources:
    counts   ``subread_gene_counts`` (catalog ``subread/gene_counts.py``)
    samples  ``samples`` (the sample hub)

Output schema (the hub's design columns inserted after ``sample``):
    sample, time_point : Utf8, time_h : Float64, time_order : Int64, time_axis : Float64, phase : Utf8
    pc1, pc2, pc3, pc1_variance, pc2_variance, pc3_variance : Float64
    corr_to_baseline, corr_to_previous : Float64
"""

from __future__ import annotations

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.count_matrix import expressed_matrix, pca

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="counts",
        dc_ref="subread_gene_counts",
        input_schema={
            "gene_id": pl.Utf8,
            "sample": pl.Utf8,
            "counts": pl.Int64,
            "log2_cpm": pl.Float64,
        },
    ),
    RecipeSource(
        ref="samples",
        dc_ref="samples",
        input_schema={
            "sample": pl.Utf8,
            "time_point": pl.Utf8,
            "time_h": pl.Float64,
            "time_order": pl.Int64,
            "time_axis": pl.Float64,
            "phase": pl.Utf8,
        },
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "time_point": pl.Utf8,
    "time_h": pl.Float64,
    "time_order": pl.Int64,
    "time_axis": pl.Float64,
    "phase": pl.Utf8,
    "pc1": pl.Float64,
    "pc2": pl.Float64,
    "pc3": pl.Float64,
    "pc1_variance": pl.Float64,
    "pc2_variance": pl.Float64,
    "pc3_variance": pl.Float64,
    "corr_to_baseline": pl.Float64,
    "corr_to_previous": pl.Float64,
}
# The hub's design columns are run-dependent and pass through unvalidated.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

#: Hub columns that are never a design factor.
HUB_COLUMNS = frozenset(
    {
        "sample", "time_point", "time_h", "time_order", "time_axis", "phase",
        "assigned_reads", "genes_detected", "genes_detected_pct", "top100_share_pct",
        "total_read_bases", "plus_share_pct", "mito_pct", "off_main_pct", "hotspot_share_pct",
    }
)  # fmt: skip


def _spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    ra = pl.Series(a).rank(method="average").to_numpy()
    rb = pl.Series(b).rank(method="average").to_numpy()
    if np.std(ra) == 0 or np.std(rb) == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def correlations(matrix: pl.DataFrame, times: pl.DataFrame) -> pl.DataFrame:
    """``sample, corr_to_baseline, corr_to_previous`` from the expressed matrix."""
    timed = times.filter(pl.col("time_order").is_not_null())
    order = sorted(set(timed.get_column("time_order").to_list()))
    by_order: dict[int, list[str]] = {
        o: [s for s in timed.filter(pl.col("time_order") == o)["sample"] if s in matrix.columns]
        for o in order
    }

    def profile(o: int) -> np.ndarray | None:
        libs = by_order.get(o) or []
        if not libs:
            return None
        return matrix.select(libs).to_numpy().astype(float).mean(axis=1)

    rows: list[dict] = []
    for o in order:
        base = profile(order[0])
        prev = profile(order[order.index(o) - 1]) if order.index(o) > 0 else None
        for sample in by_order[o]:
            values = matrix.get_column(sample).to_numpy().astype(float)
            rows.append(
                {
                    "sample": sample,
                    "corr_to_baseline": _spearman(values, base) if base is not None else None,
                    "corr_to_previous": _spearman(values, prev) if prev is not None else None,
                }
            )
    return pl.DataFrame(
        rows,
        schema={"sample": pl.Utf8, "corr_to_baseline": pl.Float64, "corr_to_previous": pl.Float64},
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    samples = sources["samples"]
    matrix = expressed_matrix(sources["counts"])
    out = (
        samples.select("sample", "time_point", "time_h", "time_order", "time_axis", "phase")
        .join(pca(matrix), on="sample", how="inner")
        .join(correlations(matrix, samples), on="sample", how="left")
        .select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])
    )
    factors = [c for c in samples.columns if c not in HUB_COLUMNS]
    if factors:
        out = out.join(samples.select("sample", *factors), on="sample", how="left").select(
            "sample", *factors, *list(OUTPUT_SCHEMA)[1:]
        )
    return out.sort(["time_order", "sample"], nulls_last=True)
