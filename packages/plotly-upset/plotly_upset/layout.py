"""Subplot grid layout engine for UpSet plots."""

from __future__ import annotations

from dataclasses import dataclass, field

import plotly.graph_objects as go
from plotly.subplots import make_subplots


@dataclass
class UpSetGridLayout:
    """Describes the subplot grid and cell positions for an UpSet plot.

    Cell coordinates are **1-indexed** (matching ``make_subplots``).
    """

    n_rows: int
    n_cols: int
    row_heights: list[float]
    column_widths: list[float]
    specs: list[list[dict | None]]

    # Element -> (row, col) mappings (1-indexed)
    intersection_bar_cell: tuple[int, int] = (1, 1)
    dot_matrix_cell: tuple[int, int] = (2, 2)
    set_size_cell: tuple[int, int] | None = None
    annotation_cells: list[tuple[int, int]] = field(default_factory=list)


def compute_upset_layout(
    *,
    n_annotation_tracks: int = 0,
    track_sizes: list[float] | None = None,
    show_set_sizes: bool = True,
    n_sets: int = 1,
    intersection_bar_ratio: float = 0.45,
    dot_matrix_base: float = 0.04,
    set_size_ratio: float = 0.25,
) -> UpSetGridLayout:
    """Compute the subplot grid for an UpSet plot.

    Grid (top->bottom, left->right):

    ::

        [empty]          [annotation track N]
        ...              ...
        [empty]          [annotation track 1]
        [empty]          [intersection bars]
        [set size bars]  [dot matrix]

    """
    if track_sizes is None:
        track_sizes = []

    n_cols = 2 if show_set_sizes else 1
    n_rows = n_annotation_tracks + 2  # annotations + intersection bars + dot matrix

    # Row heights: annotations, then intersection bars, then dot matrix
    row_heights: list[float] = []

    # Dot matrix height scales with number of sets
    dot_matrix_height = max(0.15, min(0.50, dot_matrix_base * n_sets))

    # Annotation track heights
    anno_total = 0.0
    for i in range(n_annotation_tracks):
        sz = track_sizes[i] if i < len(track_sizes) else 0.08
        row_heights.append(sz)
        anno_total += sz

    # Intersection bars get the remaining space
    bar_height = max(0.2, 1.0 - dot_matrix_height - anno_total)
    row_heights.append(bar_height)

    # Dot matrix
    row_heights.append(dot_matrix_height)

    # Column widths
    if show_set_sizes:
        column_widths = [set_size_ratio, 1.0 - set_size_ratio]
    else:
        column_widths = [1.0]

    # Build specs
    specs: list[list[dict | None]] = []
    annotation_cells: list[tuple[int, int]] = []

    main_col = n_cols  # rightmost column (1-indexed)

    for ri in range(n_rows):
        row_spec: list[dict | None] = [None] * n_cols
        r1 = ri + 1  # 1-indexed

        if ri < n_annotation_tracks:
            # Annotation track row — only the main column is active
            row_spec[main_col - 1] = {}
            annotation_cells.append((r1, main_col))
        elif ri == n_annotation_tracks:
            # Intersection bar row — only main column
            row_spec[main_col - 1] = {}
        elif ri == n_annotation_tracks + 1:
            # Dot matrix row — main column + optional set-size column
            row_spec[main_col - 1] = {}
            if show_set_sizes:
                row_spec[0] = {}

        specs.append(row_spec)

    intersection_bar_cell = (n_annotation_tracks + 1, main_col)
    dot_matrix_cell = (n_annotation_tracks + 2, main_col)
    set_size_cell = (n_annotation_tracks + 2, 1) if show_set_sizes else None

    return UpSetGridLayout(
        n_rows=n_rows,
        n_cols=n_cols,
        row_heights=row_heights,
        column_widths=column_widths,
        specs=specs,
        intersection_bar_cell=intersection_bar_cell,
        dot_matrix_cell=dot_matrix_cell,
        set_size_cell=set_size_cell,
        annotation_cells=annotation_cells,
    )


def create_figure(layout: UpSetGridLayout) -> go.Figure:
    """Build a ``plotly.graph_objects.Figure`` from an :class:`UpSetGridLayout`."""
    fig = make_subplots(
        rows=layout.n_rows,
        cols=layout.n_cols,
        row_heights=layout.row_heights,
        column_widths=layout.column_widths,
        shared_xaxes="columns",
        shared_yaxes="rows",
        horizontal_spacing=0.02,
        vertical_spacing=0.02,
        specs=layout.specs,
    )
    return fig
