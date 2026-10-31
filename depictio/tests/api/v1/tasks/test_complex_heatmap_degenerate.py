"""A heatmap narrowed to a sliver of its matrix still draws.

Filters can leave one column (a single time point picked), one row, or none.
The dendrogram needs two leaves, and a correlation distance needs two values per
leaf: the library failed with "float division by zero" on an empty frame and with
"condensed distance matrix must contain only finite values" on a one-column one.
"""

from __future__ import annotations

import pandas as pd
import pytest

from depictio.api.v1.celery_tasks import _heatmap_clustering_flags


@pytest.mark.parametrize(
    ("n_rows", "n_cols", "metric", "expected"),
    [
        (40, 11, "correlation", (True, True)),
        (40, 11, "euclidean", (True, True)),
        # One column: rows have no correlation distance, columns no leaves.
        (40, 1, "correlation", (False, False)),
        (40, 1, "euclidean", (True, False)),
        # One row: the mirror image.
        (1, 11, "correlation", (False, False)),
        (1, 11, "euclidean", (False, True)),
        # Nothing left.
        (0, 11, "euclidean", (False, True)),
        (0, 0, "correlation", (False, False)),
    ],
)
def test_clustering_flags_drop_what_cannot_be_clustered(n_rows, n_cols, metric, expected):
    assert _heatmap_clustering_flags(n_rows, n_cols, True, True, metric) == expected


def test_clustering_flags_respect_an_axis_left_off():
    assert _heatmap_clustering_flags(40, 11, False, True, "correlation") == (False, True)
    assert _heatmap_clustering_flags(40, 11, True, False, "correlation") == (True, False)


def test_unclustered_slivers_render():
    from plotly_complexheatmap import ComplexHeatmap

    for n_rows, cols in [(40, ["a"]), (1, ["a", "b", "c"])]:
        pdf = pd.DataFrame(
            {"id": [f"r{i}" for i in range(n_rows)]}
            | {c: [float(i + j) for i in range(n_rows)] for j, c in enumerate(cols)}
        )
        cluster_rows, cluster_cols = _heatmap_clustering_flags(
            n_rows, len(cols), True, True, "correlation"
        )
        ComplexHeatmap.from_dataframe(
            pdf,
            index_column="id",
            value_columns=cols,
            cluster_rows=cluster_rows,
            cluster_cols=cluster_cols,
            cluster_metric="correlation",
            normalize="row",
        ).to_plotly()
