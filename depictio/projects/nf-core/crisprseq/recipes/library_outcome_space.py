"""Sample space of the libraries: where each one sits among the others by its edit outcomes.

One row per library that classified reads: the share of its classified reads in
each of the seven outcome classes of the CIGAR parser (wild type, template-based,
deletion-insertion, in-frame and frameshift insertions and deletions), the
library's coordinates on the first three principal components of those shares,
and the editing quartile of its guide (``guide_summary``), so the embedding can
colour by a column with a handful of values instead of one per guide.

The PCA runs on the seven shares, each standardised to unit variance so that a
rare class counts as much as wild type. A class every library lacks (no donor
template, so no template-based reads) has no variance and is left out of the
reduction. The two ``explained_pc*_pct`` columns repeat, on every row, the share
of the total variance the first two components carry: a reader needs it to know
how much of the spread the plane shows. Components are oriented so that wild
type loads negatively on PC1 (editing grows to the right) and the largest
loading of the others is positive, which keeps the picture the same between
runs.

Nothing here reads a file: the table is derived from collections that are
already ingested.

Output:
    sample : Utf8            library id
    guide : Utf8             protospacer of the library
    edit_quartile : Utf8     editing quartile of the guide, among the guides of the run
    dominant_outcome : Utf8  the edit class with the most reads in the library; Wild type when it has no edit read
    classified_reads : Int64 reads the CIGAR parser classified
    dim_1, dim_2, dim_3 : Float64   coordinates on the principal components
    explained_pc1_pct, explained_pc2_pct : Float64   variance on PC1 and PC2, percent
    <outcome>_pct : Float64  share of the classified reads in each outcome class
"""

from __future__ import annotations

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.crisprseq import (
    SAMPLES_INPUT_SCHEMA,
    SUMMARY_INPUT_SCHEMA,
    library_guides,
    rounded,
)

# The outcome classes as the edit summary names their read counts, with the share
# column each becomes. Order: wild type first, then the edits.
OUTCOME_SHARES: dict[str, str] = {
    "wt_reads": "wt_pct",
    "template_based_reads": "template_based_pct",
    "delins_reads": "delins_pct",
    "ins_inframe_reads": "ins_inframe_pct",
    "ins_frameshift_reads": "ins_frameshift_pct",
    "del_inframe_reads": "del_inframe_pct",
    "del_frameshift_reads": "del_frameshift_pct",
}
N_COMPONENTS = 3

# The outcome class each share column names, as the dashboard's ``outcome`` colours
# spell it, so a point can be coloured by the class its library edits most.
OUTCOME_LABELS: dict[str, str] = {
    "wt_pct": "Wild type",
    "template_based_pct": "Template-based",
    "delins_pct": "Deletion-insertion",
    "ins_inframe_pct": "Insertion, in-frame",
    "ins_frameshift_pct": "Insertion, frameshift",
    "del_inframe_pct": "Deletion, in-frame",
    "del_frameshift_pct": "Deletion, frameshift",
}

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(ref="samples", dc_ref="samples", input_schema=SAMPLES_INPUT_SCHEMA),
    RecipeSource(
        ref="summary",
        dc_ref="crisprseq_edit_summary",
        input_schema={
            **SUMMARY_INPUT_SCHEMA,
            **dict.fromkeys(OUTCOME_SHARES, pl.Int64),
            "edited_pct": pl.Float64,
        },
    ),
    RecipeSource(
        ref="guides",
        dc_ref="guide_summary",
        input_schema={"guide": pl.Utf8, "edit_quartile": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it. Column order is the
# table's: the library and its guide first, the coordinates next, the shares last.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "guide": pl.Utf8,
    "edit_quartile": pl.Utf8,
    "dominant_outcome": pl.Utf8,
    "classified_reads": pl.Int64,
    "dim_1": pl.Float64,
    "dim_2": pl.Float64,
    "dim_3": pl.Float64,
    "explained_pc1_pct": pl.Float64,
    "explained_pc2_pct": pl.Float64,
    "edited_pct": pl.Float64,
    **dict.fromkeys(OUTCOME_SHARES.values(), pl.Float64),
}


def principal_components(shares: np.ndarray, wt_column: int) -> tuple[np.ndarray, np.ndarray]:
    """Scores on the first :data:`N_COMPONENTS` components and variance share per component.

    ``shares`` is libraries by outcome classes. Columns without variance are
    dropped before the reduction. Scores are zero-padded when the table has fewer
    informative columns or libraries than components.
    """
    n = shares.shape[0]
    scores = np.zeros((n, N_COMPONENTS))
    explained = np.zeros(N_COMPONENTS)
    centred = shares - shares.mean(axis=0)
    std = centred.std(axis=0)
    keep = std > 0
    if n < 2 or not keep.any():
        return scores, explained
    x = centred[:, keep] / std[keep]
    _, s, vt = np.linalg.svd(x, full_matrices=False)
    k = min(N_COMPONENTS, vt.shape[0])
    loadings = vt[:k].copy()
    wt_kept = np.cumsum(keep)[wt_column] - 1 if keep[wt_column] else None
    for i in range(k):
        # Fix the sign: wild type negative on PC1, otherwise the largest loading positive.
        if i == 0 and wt_kept is not None:
            if loadings[i, wt_kept] > 0:
                loadings[i] = -loadings[i]
        elif loadings[i, np.argmax(np.abs(loadings[i]))] < 0:
            loadings[i] = -loadings[i]
    scores[:, :k] = x @ loadings.T
    var = s**2
    total = var.sum()
    if total > 0:
        explained[:k] = (var[:k] / total) * 100.0
    return scores, explained


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    summary = sources["summary"]
    libs = library_guides(sources["samples"], summary).select("sample", "guide")
    table = (
        summary.filter(pl.col("classified_reads") > 0)
        .join(libs, on="sample", how="inner")
        .join(sources["guides"].select("guide", "edit_quartile"), on="guide", how="left")
        .with_columns(
            pl.col("edit_quartile").fill_null("Not ranked"),
            *[
                (pl.col(count) * 100.0 / pl.col("classified_reads")).alias(share)
                for count, share in OUTCOME_SHARES.items()
            ],
        )
        .sort("sample")
    )
    shares = list(OUTCOME_SHARES.values())
    if table.is_empty():
        return pl.DataFrame(schema=OUTPUT_SCHEMA)
    scores, explained = principal_components(
        table.select(shares).to_numpy(), shares.index("wt_pct")
    )
    edit_shares = [c for c in shares if c != "wt_pct"]
    edit_matrix = table.select(edit_shares).to_numpy()
    dominant = [
        OUTCOME_LABELS[edit_shares[int(row.argmax())]]
        if row.max() > 0
        else OUTCOME_LABELS["wt_pct"]
        for row in edit_matrix
    ]
    out = table.with_columns(
        pl.Series("dominant_outcome", dominant, dtype=pl.Utf8),
        pl.Series("dim_1", scores[:, 0]),
        pl.Series("dim_2", scores[:, 1]),
        pl.Series("dim_3", scores[:, 2]),
        pl.lit(float(explained[0])).alias("explained_pc1_pct"),
        pl.lit(float(explained[1])).alias("explained_pc2_pct"),
    )
    floats = [c for c, t in OUTPUT_SCHEMA.items() if t == pl.Float64]
    return (
        out.with_columns([pl.col(c).cast(pl.Float64) for c in floats])
        .with_columns(rounded(*floats))
        .select(list(OUTPUT_SCHEMA))
    )
