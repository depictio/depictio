"""How far two segmentation methods agree on the same image (MCQUANT).

nf-core/mcmicro can segment one image with several methods (``--segmentation
mesmer,cellpose``), each quantified into its own MCQUANT table. Without the
masks, agreement is read from the cells: a cell of one method *holds* a cell of
the other when the other's centroid lies within the disc of the first cell's
area (radius ``sqrt(Area / pi)``). One row per image, method and other method:
the cells of each, their ratio, the share of the method's cells that hold at
least one cell of the other, and the median number they hold. A nuclear method
against a whole-cell one reads asymmetric by design: each whole cell holds a
nucleus, few nuclei hold a whole-cell centroid.

Needs two methods on at least one image; a single-method run has nothing to
compare and the recipe says so.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.mcquant import centroid_hits, equivalent_radius, load_cells

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="mcquant",
        input_schema={
            "source_path": pl.Utf8,
            "CellID": pl.Int64,
            "X_centroid": pl.Float64,
            "Y_centroid": pl.Float64,
        },
        glob_pattern="quantification/mcquant/*/*.csv",
        format="csv",
        source_path="source_path",
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "pair_key": pl.Utf8,
    "sample": pl.Utf8,
    "segmenter": pl.Utf8,
    "other_segmenter": pl.Utf8,
    "pair": pl.Utf8,
    "n_cells": pl.Int64,
    "other_cells": pl.Int64,
    "count_ratio": pl.Float64,
    "cells_holding_other": pl.Int64,
    "matched_share": pl.Float64,
    "median_held": pl.Float64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    cells = load_cells(sources["mcquant"]).filter(
        pl.col("X_centroid").is_not_null() & pl.col("Y_centroid").is_not_null()
    )
    rows: list[dict] = []
    for (sample,), image in cells.group_by(["sample"], maintain_order=True):
        by_method = {
            str(name): group
            for (name,), group in image.group_by(["segmenter"], maintain_order=True)
        }
        for method, own in sorted(by_method.items()):
            for other_method, other in sorted(by_method.items()):
                if other_method == method:
                    continue
                held = centroid_hits(
                    (
                        own["X_centroid"].to_numpy(),
                        own["Y_centroid"].to_numpy(),
                        equivalent_radius(own["Area"].fill_null(0).to_numpy()),
                    ),
                    (other["X_centroid"].to_numpy(), other["Y_centroid"].to_numpy()),
                )
                n_own, n_other = own.height, other.height
                holding = int(np.count_nonzero(held))
                rows.append(
                    {
                        "pair_key": f"{sample}|{method}|{other_method}",
                        "sample": str(sample),
                        "segmenter": method,
                        "other_segmenter": other_method,
                        "pair": f"{method} cells holding a {other_method} cell",
                        "n_cells": n_own,
                        "other_cells": n_other,
                        "count_ratio": round(n_own / n_other, 4) if n_other else None,
                        "cells_holding_other": holding,
                        "matched_share": round(holding / n_own, 4) if n_own else None,
                        "median_held": float(np.median(held)) if n_own else None,
                    }
                )
    if not rows:
        raise ValueError(
            "mcquant segmenter agreement: no image was segmented by two methods "
            "(run with --segmentation mesmer,cellpose to compare them)"
        )
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA).sort(["sample", "segmenter", "other_segmenter"])
