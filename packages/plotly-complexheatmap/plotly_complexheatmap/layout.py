"""Subplot grid layout engine for complex heatmaps."""

from __future__ import annotations

from dataclasses import dataclass, field

from plotly.subplots import make_subplots

from plotly_complexheatmap.annotations import HeatmapAnnotation


@dataclass
class GridLayout:
    """Describes the subplot grid and the cell positions of every element.

    Cell coordinates are **1-indexed** (matching ``make_subplots``).
    """

    n_rows: int
    n_cols: int
    row_heights: list[float]
    column_widths: list[float]

    # Element -> (row, col) mappings
    col_dendro_cell: tuple[int, int] | None = None
    row_dendro_cells: list[tuple[int, int]] = field(default_factory=list)
    heatmap_cells: list[tuple[int, int]] = field(default_factory=list)
    top_anno_cells: list[list[tuple[int, int]]] = field(default_factory=list)
    bottom_anno_cells: list[list[tuple[int, int]]] = field(default_factory=list)
    left_anno_cells: list[list[tuple[int, int]]] = field(default_factory=list)
    right_anno_cells: list[list[tuple[int, int]]] = field(default_factory=list)

    # Specs for make_subplots (None -> empty cell)
    specs: list[list[dict[str, str] | None]] = field(default_factory=list)


def compute_grid_layout(
    *,
    has_col_dendro: bool,
    has_row_dendro: bool,
    top_annotation: HeatmapAnnotation | None = None,
    bottom_annotation: HeatmapAnnotation | None = None,
    left_annotation: HeatmapAnnotation | None = None,
    right_annotation: HeatmapAnnotation | None = None,
    n_row_groups: int = 1,
    group_sizes: list[int] | None = None,
    dendro_ratio: float = 0.08,
    total_rows: int = 1,
) -> GridLayout:
    """Compute the subplot grid for a complex heatmap.

    Parameters
    ----------
    n_row_groups:
        Number of row-split groups (1 = no split).
    group_sizes:
        Number of data rows per group (used to size heatmap rows proportionally).
    dendro_ratio:
        Fraction of figure allocated to each dendrogram axis.
    total_rows:
        Total number of data rows (used when *group_sizes* is ``None``).
    """
    if group_sizes is None:
        group_sizes = [total_rows]

    # ---- Rows (top -> bottom) -----------------------------------------------
    rows: list[str] = []
    row_heights: list[float] = []

    if has_col_dendro:
        rows.append("col_dendro")
        row_heights.append(dendro_ratio)

    if top_annotation:
        for track in top_annotation.tracks:
            rows.append("top_anno")
            row_heights.append(track.size)

    heatmap_budget = max(0.3, 1.0 - sum(row_heights))

    # Reserve bottom annotation budget
    if bottom_annotation:
        bottom_total = bottom_annotation.total_size()
        heatmap_budget = max(0.3, heatmap_budget - bottom_total)

    total_data_rows = sum(group_sizes)
    for gs in group_sizes:
        rows.append("heatmap")
        row_heights.append(heatmap_budget * gs / total_data_rows)

    if bottom_annotation:
        for track in bottom_annotation.tracks:
            rows.append("bottom_anno")
            row_heights.append(track.size)

    # ---- Columns (left -> right) --------------------------------------------
    cols: list[str] = []
    col_widths: list[float] = []

    if has_row_dendro:
        cols.append("row_dendro")
        col_widths.append(dendro_ratio)

    # Left annotation columns (between dendrogram and heatmap)
    if left_annotation:
        for track in left_annotation.tracks:
            cols.append("left_anno")
            col_widths.append(track.size)

    cols.append("heatmap")

    # Right annotation columns
    left_anno_total = left_annotation.total_size() if left_annotation else 0.0
    right_anno_total = right_annotation.total_size() if right_annotation else 0.0
    used_width = dendro_ratio * has_row_dendro + left_anno_total + right_anno_total
    col_widths.append(max(0.3, 1.0 - used_width))  # heatmap gets remainder

    if right_annotation:
        for track in right_annotation.tracks:
            cols.append("right_anno")
            col_widths.append(track.size)

    n_grid_rows = len(rows)
    n_grid_cols = len(cols)

    # ---- Specs (empty cells = None) ----------------------------------------
    specs: list[list[dict[str, str] | None]] = [[None] * n_grid_cols for _ in range(n_grid_rows)]

    dendro_col = cols.index("row_dendro") if has_row_dendro else -1
    hm_col = cols.index("heatmap")
    left_anno_cols = [i for i, c in enumerate(cols) if c == "left_anno"]
    right_anno_cols = [i for i, c in enumerate(cols) if c == "right_anno"]

    col_dendro_cell = None
    row_dendro_cells: list[tuple[int, int]] = []
    heatmap_cells: list[tuple[int, int]] = []
    top_anno_cells_final: list[list[tuple[int, int]]] = []
    bottom_anno_cells_final: list[list[tuple[int, int]]] = []
    left_anno_cells_list: list[list[tuple[int, int]]] = []
    right_anno_cells_list: list[list[tuple[int, int]]] = []

    for ri, tag in enumerate(rows):
        r1 = ri + 1  # 1-indexed

        if tag == "col_dendro":
            specs[ri][hm_col] = {}
            col_dendro_cell = (r1, hm_col + 1)

        elif tag == "top_anno":
            specs[ri][hm_col] = {}
            top_anno_cells_final.append([(r1, hm_col + 1)])

        elif tag == "bottom_anno":
            specs[ri][hm_col] = {}
            bottom_anno_cells_final.append([(r1, hm_col + 1)])

        elif tag == "heatmap":
            specs[ri][hm_col] = {}
            heatmap_cells.append((r1, hm_col + 1))

            if dendro_col >= 0:
                specs[ri][dendro_col] = {}
                row_dendro_cells.append((r1, dendro_col + 1))

            la_cells: list[tuple[int, int]] = []
            for ci in left_anno_cols:
                specs[ri][ci] = {}
                la_cells.append((r1, ci + 1))
            left_anno_cells_list.append(la_cells)

            ra_cells: list[tuple[int, int]] = []
            for ci in right_anno_cols:
                specs[ri][ci] = {}
                ra_cells.append((r1, ci + 1))
            right_anno_cells_list.append(ra_cells)

    return GridLayout(
        n_rows=n_grid_rows,
        n_cols=n_grid_cols,
        row_heights=row_heights,
        column_widths=col_widths,
        specs=specs,
        col_dendro_cell=col_dendro_cell,
        row_dendro_cells=row_dendro_cells,
        heatmap_cells=heatmap_cells,
        top_anno_cells=top_anno_cells_final,
        bottom_anno_cells=bottom_anno_cells_final,
        left_anno_cells=left_anno_cells_list,
        right_anno_cells=right_anno_cells_list,
    )


def create_figure(layout: GridLayout, **kwargs: object) -> object:
    """Build a ``plotly.graph_objects.Figure`` from a :class:`GridLayout`.

    Extra *kwargs* are forwarded to ``make_subplots``.
    """
    fig = make_subplots(
        rows=layout.n_rows,
        cols=layout.n_cols,
        row_heights=layout.row_heights,
        column_widths=layout.column_widths,
        shared_xaxes="columns",
        shared_yaxes="rows",
        horizontal_spacing=0.015,
        vertical_spacing=0.015,
        specs=layout.specs,
        **kwargs,  # type: ignore[arg-type]
    )
    return fig
