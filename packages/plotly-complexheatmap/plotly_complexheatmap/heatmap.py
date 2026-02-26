"""Main ``ComplexHeatmap`` class — the public entry-point."""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import plotly.graph_objects as go
from numpy.typing import NDArray

from plotly_complexheatmap.annotations import HeatmapAnnotation
from plotly_complexheatmap.clustering import DendrogramResult, compute_dendrogram, dendrogram_traces
from plotly_complexheatmap.layout import GridLayout, compute_grid_layout, create_figure
from plotly_complexheatmap.legends import collect_legend_items
from plotly_complexheatmap.utils import COMPLEXHEATMAP_COLORSCALE, FONT_FAMILY, normalize_data, validate_data

# Plotly 6+ merged Heatmapgl into Heatmap; detect availability
_HAS_HEATMAPGL = hasattr(go, "Heatmapgl")

# WebGL auto-switch threshold (rows * cols) — only used on Plotly <6
_WEBGL_THRESHOLD = 100_000


class ComplexHeatmap:
    """Clustered heatmap with dendrograms, annotation tracks, and split support.

    Parameters
    ----------
    data:
        2-D data — ``pandas.DataFrame`` or array-like.
    cluster_rows / cluster_cols:
        Whether to perform hierarchical clustering on rows / columns.
    top_annotation / bottom_annotation:
        ``HeatmapAnnotation`` objects for column annotations (top/bottom).
    left_annotation / right_annotation:
        ``HeatmapAnnotation`` objects for row annotations (left/right).
    colorscale:
        Any Plotly-compatible colorscale name or list.  Defaults to
        a ComplexHeatmap-style blue–white–red diverging scale.
    normalize:
        ``"none"``, ``"row"``, ``"column"``, or ``"global"`` z-score normalisation.
    use_webgl:
        ``None`` (auto — use WebGL above threshold), ``True``, or ``False``.
    split_rows_by:
        Split the heatmap into horizontal groups.  Either a list of group
        labels (one per row), or a string naming an annotation track.
    cluster_method / cluster_metric:
        Parameters forwarded to ``scipy.cluster.hierarchy``.
    dendro_ratio:
        Fraction of figure allocated to each dendrogram axis.
    name:
        Name for the heatmap colourbar title.
    width / height:
        Figure size in pixels.
    """

    def __init__(
        self,
        data: Any,
        *,
        cluster_rows: bool = True,
        cluster_cols: bool = True,
        top_annotation: HeatmapAnnotation | None = None,
        bottom_annotation: HeatmapAnnotation | None = None,
        left_annotation: HeatmapAnnotation | None = None,
        right_annotation: HeatmapAnnotation | None = None,
        colorscale: str | list[list[Any]] | None = None,
        normalize: str = "none",
        use_webgl: bool | None = None,
        split_rows_by: Sequence[str] | str | None = None,
        cluster_method: str = "ward",
        cluster_metric: str = "euclidean",
        dendro_ratio: float = 0.08,
        name: str = "",
        width: int = 900,
        height: int = 700,
    ) -> None:
        arr, row_labels, col_labels = validate_data(data)
        self._raw = arr
        self._data = normalize_data(arr, method=normalize)
        self._row_labels = row_labels
        self._col_labels = col_labels

        self.cluster_rows = cluster_rows
        self.cluster_cols = cluster_cols
        self.top_annotation = top_annotation
        self.bottom_annotation = bottom_annotation
        self.left_annotation = left_annotation
        self.right_annotation = right_annotation
        self.colorscale = colorscale if colorscale is not None else COMPLEXHEATMAP_COLORSCALE
        self.use_webgl = use_webgl
        self.split_rows_by = split_rows_by
        self.cluster_method = cluster_method
        self.cluster_metric = cluster_metric
        self.dendro_ratio = dendro_ratio
        self.name = name
        self.width = width
        self.height = height

        # Computed during to_plotly()
        self._row_dendro: DendrogramResult | None = None
        self._col_dendro: DendrogramResult | None = None
        self._row_order: NDArray[np.intp] | None = None
        self._col_order: NDArray[np.intp] | None = None
        self._split_groups: list[str] | None = None
        self._group_indices: dict[str, NDArray[np.intp]] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def from_dataframe(
        cls,
        df: Any,
        *,
        index_column: str | None = None,
        value_columns: list[str] | None = None,
        row_annotations: list[str] | dict[str, dict[str, Any]] | None = None,
        col_annotations: dict[str, Any] | None = None,
        row_annotation_side: str = "right",
        col_annotation_side: str = "top",
        **kwargs: Any,
    ) -> ComplexHeatmap:
        """Build a ``ComplexHeatmap`` from a single pandas or polars DataFrame.

        This is the recommended entry-point for Depictio integration: pass one
        DataFrame and specify which columns hold heatmap values vs. annotations.

        Parameters
        ----------
        df:
            A ``pandas.DataFrame`` or ``polars.DataFrame``.
        index_column:
            Column to use as row labels.  For pandas, defaults to the
            existing index; for polars (which has no index), defaults to
            integer row numbers.
        value_columns:
            Columns whose values form the heatmap matrix.  When *None*,
            all numeric columns **not** listed in *row_annotations* are
            used automatically.
        row_annotations:
            Per-row metadata extracted from the DataFrame.

            - ``list[str]``: column names — track type is auto-detected
              (string → categorical, numeric → bar chart).
            - ``dict[str, dict]``: column names mapped to config dicts
              accepted by :class:`HeatmapAnnotation` (e.g.
              ``{"score": {"type": "bar", "color": "#4C78A8"}}``).
        col_annotations:
            Per-column metadata — **not** in the DataFrame (because each
            column is a heatmap variable, not a row).  Passed as keyword
            arguments to :class:`HeatmapAnnotation`, e.g.
            ``{"group": ["A", "A", "B", "B"]}``.
        row_annotation_side:
            ``"left"`` or ``"right"`` (default).
        col_annotation_side:
            ``"top"`` (default) or ``"bottom"``.
        **kwargs:
            Forwarded to :meth:`ComplexHeatmap.__init__`
            (``colorscale``, ``normalize``, ``cluster_rows``, etc.).

        Examples
        --------
        >>> import pandas as pd
        >>> df = pd.DataFrame({
        ...     "gene": ["TP53", "BRCA1", "EGFR"],
        ...     "pathway": ["apoptosis", "repair", "signaling"],
        ...     "sample_A": [1.2, 0.5, 3.1],
        ...     "sample_B": [0.8, 2.1, 1.0],
        ...     "sample_C": [2.0, 1.3, 0.4],
        ... })
        >>> hm = ComplexHeatmap.from_dataframe(
        ...     df,
        ...     index_column="gene",
        ...     row_annotations=["pathway"],
        ...     col_annotations={"group": ["ctrl", "ctrl", "treat"]},
        ... )
        """
        pdf = _to_pandas(df, index_column=index_column)

        # Determine which columns are annotations vs. heatmap values
        anno_cols: set[str] = set()
        if row_annotations is not None:
            if isinstance(row_annotations, list):
                anno_cols = set(row_annotations)
            else:
                anno_cols = set(row_annotations.keys())

        if value_columns is None:
            value_columns = [c for c in pdf.columns if c not in anno_cols and pdf[c].dtype.kind in ("f", "i", "u")]
        if not value_columns:
            raise ValueError("No numeric value columns found. Specify value_columns explicitly.")

        data_df = pdf[value_columns]

        # Build row annotations
        if row_annotations is not None:
            ha_kw: dict[str, Any] = {}
            if isinstance(row_annotations, list):
                for col in row_annotations:
                    ha_kw[col] = pdf[col].tolist()
            else:
                for col, cfg in row_annotations.items():
                    if isinstance(cfg, dict):
                        ha_kw[col] = {"values": pdf[col].tolist(), **cfg}
                    else:
                        ha_kw[col] = pdf[col].tolist()

            row_ha = HeatmapAnnotation(which="row", **ha_kw)
            side_key = "left_annotation" if row_annotation_side == "left" else "right_annotation"
            kwargs.setdefault(side_key, row_ha)

        # Build column annotations
        if col_annotations is not None:
            col_ha = HeatmapAnnotation(which="column", **col_annotations)
            side_key = "top_annotation" if col_annotation_side == "top" else "bottom_annotation"
            kwargs.setdefault(side_key, col_ha)

        return cls(data_df, **kwargs)

    def to_plotly(self) -> go.Figure:
        """Build and return the complete Plotly ``Figure``."""
        self._resolve_split()
        self._cluster()
        self._reorder()

        layout = self._build_layout()
        fig: go.Figure = create_figure(layout)  # type: ignore[assignment]

        self._add_heatmap(fig, layout)
        self._add_dendrograms(fig, layout)
        self._add_top_annotations(fig, layout)
        self._add_bottom_annotations(fig, layout)
        self._add_left_annotations(fig, layout)
        self._add_right_annotations(fig, layout)
        self._add_legends(fig)
        self._style_axes(fig, layout)
        self._style_figure(fig, layout)

        return fig

    # ------------------------------------------------------------------
    # Split resolution
    # ------------------------------------------------------------------

    def _resolve_split(self) -> None:
        if self.split_rows_by is None:
            self._split_groups = None
            self._group_indices = None
            return

        labels: list[str]
        if isinstance(self.split_rows_by, str):
            labels = self._find_split_labels(self.split_rows_by)
        else:
            labels = [str(v) for v in self.split_rows_by]

        if len(labels) != self._data.shape[0]:
            raise ValueError(f"split_rows_by length ({len(labels)}) != data rows ({self._data.shape[0]})")

        unique = sorted(set(labels))
        self._split_groups = unique
        self._group_indices = {}
        for g in unique:
            self._group_indices[g] = np.array([i for i, v in enumerate(labels) if v == g])

    def _find_split_labels(self, track_name: str) -> list[str]:
        for ha in (self.right_annotation, self.left_annotation, self.top_annotation):
            if ha is None:
                continue
            for track in ha.tracks:
                if track.name == track_name:
                    return [str(v) for v in track.values]
        raise ValueError(f"Annotation track {track_name!r} not found for split_rows_by")

    # ------------------------------------------------------------------
    # Clustering
    # ------------------------------------------------------------------

    def _cluster(self) -> None:
        if self.cluster_cols:
            self._col_dendro = compute_dendrogram(
                self._data.T,
                method=self.cluster_method,
                metric=self.cluster_metric,
            )
            self._col_order = self._col_dendro.leaf_order
        else:
            self._col_order = np.arange(self._data.shape[1])

        if self._split_groups is not None:
            self._cluster_split_rows()
        elif self.cluster_rows:
            self._row_dendro = compute_dendrogram(
                self._data,
                method=self.cluster_method,
                metric=self.cluster_metric,
            )
            self._row_order = self._row_dendro.leaf_order
        else:
            self._row_order = np.arange(self._data.shape[0])

    def _cluster_split_rows(self) -> None:
        """Cluster within each row-split group independently."""
        assert self._group_indices is not None
        assert self._split_groups is not None

        self._group_dendros: dict[str, DendrogramResult | None] = {}
        ordered_per_group: dict[str, NDArray[np.intp]] = {}

        for g in self._split_groups:
            idx = self._group_indices[g]
            if self.cluster_rows and len(idx) > 1:
                dn = compute_dendrogram(
                    self._data[idx],
                    method=self.cluster_method,
                    metric=self.cluster_metric,
                )
                ordered_per_group[g] = idx[dn.leaf_order]
                self._group_dendros[g] = dn
            else:
                ordered_per_group[g] = idx
                self._group_dendros[g] = None

        self._row_order = np.concatenate([ordered_per_group[g] for g in self._split_groups])
        self._group_indices = ordered_per_group

    # ------------------------------------------------------------------
    # Reordering
    # ------------------------------------------------------------------

    def _reorder(self) -> None:
        assert self._row_order is not None
        assert self._col_order is not None

        self._data = self._data[np.ix_(self._row_order, self._col_order)]
        self._row_labels = [self._row_labels[i] for i in self._row_order]
        self._col_labels = [self._col_labels[i] for i in self._col_order]

        if self.top_annotation is not None:
            self.top_annotation = self.top_annotation.reorder(self._col_order)
        if self.bottom_annotation is not None:
            self.bottom_annotation = self.bottom_annotation.reorder(self._col_order)
        if self.left_annotation is not None:
            self.left_annotation = self.left_annotation.reorder(self._row_order)
        if self.right_annotation is not None:
            self.right_annotation = self.right_annotation.reorder(self._row_order)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self) -> GridLayout:
        if self._split_groups is not None:
            assert self._group_indices is not None
            group_sizes = [len(self._group_indices[g]) for g in self._split_groups]
        else:
            group_sizes = [self._data.shape[0]]

        return compute_grid_layout(
            has_col_dendro=self.cluster_cols,
            has_row_dendro=self.cluster_rows,
            top_annotation=self.top_annotation,
            bottom_annotation=self.bottom_annotation,
            left_annotation=self.left_annotation,
            right_annotation=self.right_annotation,
            n_row_groups=len(group_sizes),
            group_sizes=group_sizes,
            dendro_ratio=self.dendro_ratio,
            total_rows=self._data.shape[0],
        )

    # ------------------------------------------------------------------
    # Heatmap traces
    # ------------------------------------------------------------------

    def _should_use_webgl(self) -> bool:
        if self.use_webgl is not None:
            return self.use_webgl
        return self._data.shape[0] * self._data.shape[1] > _WEBGL_THRESHOLD

    def _colorbar_props(self) -> dict[str, object]:
        """Colorbar config positioned to avoid overlapping row labels."""
        max_label_len = max((len(lbl) for lbl in self._row_labels), default=0)
        label_frac = min(max_label_len * 6.5 / self.width, 0.12)

        title_cfg: dict[str, object] | None = None
        if self.name:
            title_cfg = {"text": self.name, "font": {"size": 10, "family": FONT_FAMILY}}

        return {
            "title": title_cfg,
            "len": 0.3,
            "thickness": 12,
            "outlinewidth": 0,
            "xpad": 4,
            "x": 1.0 + label_frac + 0.01,
            "y": 0.5,
            "tickfont": {"size": 9, "family": FONT_FAMILY},
        }

    def _heatmap_class(self) -> type:
        webgl = self._should_use_webgl()
        if webgl and _HAS_HEATMAPGL:
            return go.Heatmapgl
        return go.Heatmap

    def _add_heatmap(self, fig: go.Figure, layout: GridLayout) -> None:
        HeatmapTrace = self._heatmap_class()

        if self._split_groups is not None:
            self._add_split_heatmaps(fig, layout, HeatmapTrace)
        else:
            r, c = layout.heatmap_cells[0]
            col_pos = np.arange(self._data.shape[1], dtype=float)
            row_pos = np.arange(self._data.shape[0], dtype=float)

            trace = HeatmapTrace(
                z=self._data,
                x=col_pos,
                y=row_pos,
                colorscale=self.colorscale,
                colorbar=self._colorbar_props(),
                hovertemplate="row: %{customdata[0]}<br>col: %{customdata[1]}<br>value: %{z:.3f}<extra></extra>",
                customdata=self._hover_custom(self._row_labels, self._col_labels),
                xgap=0.5,
                ygap=0.5,
            )
            fig.add_trace(trace, row=r, col=c)

    def _add_split_heatmaps(self, fig: go.Figure, layout: GridLayout, HeatmapTrace: type) -> None:
        assert self._split_groups is not None
        assert self._group_indices is not None

        offset = 0
        for gi, g in enumerate(self._split_groups):
            gs = len(self._group_indices[g])
            z = self._data[offset : offset + gs]
            rl = self._row_labels[offset : offset + gs]
            col_pos = np.arange(self._data.shape[1], dtype=float)
            row_pos = np.arange(gs, dtype=float)

            r, c = layout.heatmap_cells[gi]
            show_colorbar = gi == 0

            trace = HeatmapTrace(
                z=z,
                x=col_pos,
                y=row_pos,
                colorscale=self.colorscale,
                showscale=show_colorbar,
                colorbar=self._colorbar_props() if show_colorbar else None,
                hovertemplate="row: %{customdata[0]}<br>col: %{customdata[1]}<br>value: %{z:.3f}<extra></extra>",
                customdata=self._hover_custom(rl, self._col_labels),
                xgap=0.5,
                ygap=0.5,
            )
            fig.add_trace(trace, row=r, col=c)
            offset += gs

    @staticmethod
    def _hover_custom(row_labels: list[str], col_labels: list[str]) -> NDArray[np.object_]:
        """Build a (n_rows, n_cols, 2) customdata array for hover templates."""
        nr, nc = len(row_labels), len(col_labels)
        cd = np.empty((nr, nc, 2), dtype=object)
        for i, rl in enumerate(row_labels):
            for j, cl in enumerate(col_labels):
                cd[i, j, 0] = rl
                cd[i, j, 1] = cl
        return cd

    # ------------------------------------------------------------------
    # Dendrogram traces
    # ------------------------------------------------------------------

    def _add_dendrograms(self, fig: go.Figure, layout: GridLayout) -> None:
        if self._col_dendro is not None and layout.col_dendro_cell is not None:
            r, c = layout.col_dendro_cell
            for tr in dendrogram_traces(self._col_dendro, orientation="top"):
                fig.add_trace(tr, row=r, col=c)

        if self._split_groups is not None:
            self._add_split_row_dendrograms(fig, layout)
        elif self._row_dendro is not None and layout.row_dendro_cells:
            r, c = layout.row_dendro_cells[0]
            for tr in dendrogram_traces(self._row_dendro, orientation="left"):
                fig.add_trace(tr, row=r, col=c)

    def _add_split_row_dendrograms(self, fig: go.Figure, layout: GridLayout) -> None:
        assert self._split_groups is not None
        if not hasattr(self, "_group_dendros"):
            return

        for gi, g in enumerate(self._split_groups):
            dn = self._group_dendros.get(g)
            if dn is None or gi >= len(layout.row_dendro_cells):
                continue
            r, c = layout.row_dendro_cells[gi]
            for tr in dendrogram_traces(dn, orientation="left"):
                fig.add_trace(tr, row=r, col=c)

    # ------------------------------------------------------------------
    # Annotation traces
    # ------------------------------------------------------------------

    def _add_top_annotations(self, fig: go.Figure, layout: GridLayout) -> None:
        if self.top_annotation is None:
            return
        col_pos = np.arange(self._data.shape[1], dtype=float)

        for ti, track in enumerate(self.top_annotation.tracks):
            if ti >= len(layout.top_anno_cells):
                break
            cells = layout.top_anno_cells[ti]
            if not cells:
                continue
            r, c = cells[0]
            for tr in track.to_traces("x", col_pos):
                fig.add_trace(tr, row=r, col=c)

    def _add_bottom_annotations(self, fig: go.Figure, layout: GridLayout) -> None:
        if self.bottom_annotation is None:
            return
        col_pos = np.arange(self._data.shape[1], dtype=float)

        for ti, track in enumerate(self.bottom_annotation.tracks):
            if ti >= len(layout.bottom_anno_cells):
                break
            cells = layout.bottom_anno_cells[ti]
            if not cells:
                continue
            r, c = cells[0]
            for tr in track.to_traces("x", col_pos):
                fig.add_trace(tr, row=r, col=c)

    def _add_left_annotations(self, fig: go.Figure, layout: GridLayout) -> None:
        if self.left_annotation is None:
            return

        if self._split_groups is not None:
            self._add_split_side_annotations(fig, layout, self.left_annotation, layout.left_anno_cells)
            return

        row_pos = np.arange(self._data.shape[0], dtype=float)
        if layout.left_anno_cells and layout.left_anno_cells[0]:
            for ti, track in enumerate(self.left_annotation.tracks):
                if ti >= len(layout.left_anno_cells[0]):
                    break
                r, c = layout.left_anno_cells[0][ti]
                for tr in track.to_traces("y", row_pos):
                    fig.add_trace(tr, row=r, col=c)

    def _add_right_annotations(self, fig: go.Figure, layout: GridLayout) -> None:
        if self.right_annotation is None:
            return

        if self._split_groups is not None:
            self._add_split_side_annotations(fig, layout, self.right_annotation, layout.right_anno_cells)
            return

        row_pos = np.arange(self._data.shape[0], dtype=float)
        if layout.right_anno_cells and layout.right_anno_cells[0]:
            for ti, track in enumerate(self.right_annotation.tracks):
                if ti >= len(layout.right_anno_cells[0]):
                    break
                r, c = layout.right_anno_cells[0][ti]
                for tr in track.to_traces("y", row_pos):
                    fig.add_trace(tr, row=r, col=c)

    def _add_split_side_annotations(
        self,
        fig: go.Figure,
        layout: GridLayout,
        annotation: HeatmapAnnotation,
        anno_cells: list[list[tuple[int, int]]],
    ) -> None:
        """Add left or right annotations for split heatmaps."""
        assert self._split_groups is not None
        assert self._group_indices is not None

        offset = 0
        for gi, g in enumerate(self._split_groups):
            gs = len(self._group_indices[g])
            row_pos = np.arange(gs, dtype=float)

            if gi >= len(anno_cells):
                break
            cells = anno_cells[gi]

            for ti, track in enumerate(annotation.tracks):
                if ti >= len(cells):
                    break
                r, c = cells[ti]
                sliced_vals = np.asarray(track.values)[offset : offset + gs]
                tmp = _slice_track(track, sliced_vals.tolist())
                if tmp is None:
                    continue

                for tr in tmp.to_traces("y", row_pos):
                    if gi > 0 and hasattr(tr, "showlegend"):
                        tr.showlegend = False
                    fig.add_trace(tr, row=r, col=c)

            offset += gs

    # ------------------------------------------------------------------
    # Legends
    # ------------------------------------------------------------------

    def _add_legends(self, fig: go.Figure) -> None:
        for item in collect_legend_items(
            self.top_annotation, self.bottom_annotation, self.left_annotation, self.right_annotation
        ):
            fig.add_trace(item)

    # ------------------------------------------------------------------
    # Axis styling
    # ------------------------------------------------------------------

    def _style_axes(self, fig: go.Figure, layout: GridLayout) -> None:
        """Configure tick labels, grid lines, and axis visibility."""
        has_right_anno = bool(self.right_annotation and layout.right_anno_cells and layout.right_anno_cells[0])
        has_left_anno = bool(self.left_annotation and layout.left_anno_cells and layout.left_anno_cells[0])

        # Hide all axes by default
        for ax_name in list(fig.layout):
            ax_str = str(ax_name)
            if ax_str.startswith("xaxis") or ax_str.startswith("yaxis"):
                fig.layout[ax_name].update(  # type: ignore[index]
                    showgrid=False,
                    zeroline=False,
                    showticklabels=False,
                    showline=False,
                )

        # Column labels on the bottom-most heatmap (or bottom annotation)
        if layout.bottom_anno_cells:
            last_cell = layout.bottom_anno_cells[-1][0]
        else:
            last_cell = layout.heatmap_cells[-1]
        hm_xaxis = self._axis_name(fig, last_cell, "x")
        fig.layout[hm_xaxis].update(
            tickvals=list(range(len(self._col_labels))),
            ticktext=self._col_labels,
            showticklabels=True,
            tickangle=-90 if len(self._col_labels) > 20 else -45,
            side="bottom",
            tickfont={"size": 10, "family": FONT_FAMILY},
        )

        # Explicitly suppress x-ticks on non-bottom heatmap cells (split case)
        if len(layout.heatmap_cells) > 1:
            for cell in layout.heatmap_cells[:-1]:
                xax = self._axis_name(fig, cell, "x")
                fig.layout[xax].update(showticklabels=False, tickvals=[])

        # Row labels — place on the RIGHTMOST element
        self._place_row_labels(fig, layout, has_right_anno)

        # Explicit y-range on ALL cells in each heatmap row (prevents
        # padding from box/violin/scatter traces and keeps annotation
        # heights exactly matching the heatmap)
        self._constrain_y_ranges(fig, layout)

        # Top/bottom annotation x-axes — hide (shared with heatmap columns)
        for cells_list in (layout.top_anno_cells, layout.bottom_anno_cells):
            for cells in cells_list:
                for cell in cells:
                    xax = self._axis_name(fig, cell, "x")
                    fig.layout[xax].update(showticklabels=False)

        # Left annotation axes — show track name as axis title
        if has_left_anno:
            assert self.left_annotation is not None
            self._label_side_annotation_axes(fig, self.left_annotation, layout.left_anno_cells)

        # Right annotation axes — show track name as axis title
        if has_right_anno:
            assert self.right_annotation is not None
            self._label_side_annotation_axes(fig, self.right_annotation, layout.right_anno_cells)

        # Column dendrogram — no ticks
        if layout.col_dendro_cell is not None:
            xax = self._axis_name(fig, layout.col_dendro_cell, "x")
            yax = self._axis_name(fig, layout.col_dendro_cell, "y")
            fig.layout[xax].update(showticklabels=False)
            fig.layout[yax].update(showticklabels=False)

        # Top annotation axes — show track name as y-axis title for numeric tracks
        if self.top_annotation:
            self._label_col_annotation_axes(fig, self.top_annotation, layout.top_anno_cells)
        if self.bottom_annotation:
            self._label_col_annotation_axes(fig, self.bottom_annotation, layout.bottom_anno_cells)

        # Add borders + value axes on numeric annotation subplots
        self._add_annotation_borders(fig, layout)

        # Ensure barmode is stacked for StackedBarTrack support
        fig.update_layout(barmode="stack")

    def _label_side_annotation_axes(
        self,
        fig: go.Figure,
        ha: HeatmapAnnotation,
        cells_per_group: list[list[tuple[int, int]]],
    ) -> None:
        """Label left/right annotation x-axes: categorical gets track name as tick,
        numeric gets track name as axis title (axis ticks show values)."""
        from plotly_complexheatmap.annotations import CategoricalTrack

        last_group = cells_per_group[-1] if cells_per_group else []
        for ti, track in enumerate(ha.tracks):
            if ti >= len(last_group):
                break
            cell = last_group[ti]
            xax = self._axis_name(fig, cell, "x")
            if isinstance(track, CategoricalTrack):
                fig.layout[xax].update(
                    showticklabels=True,
                    tickvals=[track.name],
                    ticktext=[track.name],
                    tickangle=-90,
                    tickfont={"size": 9, "family": FONT_FAMILY},
                )
            else:
                fig.layout[xax].update(
                    title={"text": track.name, "font": {"size": 9, "family": FONT_FAMILY}},
                )

    def _label_col_annotation_axes(
        self,
        fig: go.Figure,
        ha: HeatmapAnnotation,
        cells_list: list[list[tuple[int, int]]],
    ) -> None:
        """Label top/bottom annotation y-axes: numeric gets track name as axis title."""
        from plotly_complexheatmap.annotations import CategoricalTrack

        for ti, track in enumerate(ha.tracks):
            if ti >= len(cells_list):
                break
            cell = cells_list[ti][0]
            if isinstance(track, CategoricalTrack):
                continue
            yax = self._axis_name(fig, cell, "y")
            fig.layout[yax].update(
                title={"text": track.name, "font": {"size": 9, "family": FONT_FAMILY}},
            )

    def _add_annotation_borders(self, fig: go.Figure, layout: GridLayout) -> None:
        """Add border + axis ticks on numeric annotation subplots only."""
        from plotly_complexheatmap.annotations import CategoricalTrack

        _BORDER = {"showline": True, "linewidth": 1.2, "linecolor": "#666666", "mirror": True}
        _TICK = {
            "showticklabels": True,
            "ticks": "outside",
            "ticklen": 3,
            "tickfont": {"size": 7, "family": FONT_FAMILY},
        }

        def _apply_numeric_border(
            ha: HeatmapAnnotation | None,
            cells_per_group: list[list[tuple[int, int]]],
            orientation: str,
        ) -> None:
            """Apply borders and axis ticks to numeric track cells.

            *orientation*: ``"col"`` for top/bottom annotations (value axis = y),
            ``"row"`` for left/right annotations (value axis = x).

            Borders are drawn on every group; value-axis tick labels are
            shown only on the **bottom-most** group so they don't repeat
            across split-heatmap panels.
            """
            if ha is None:
                return
            n_groups = len(cells_per_group)
            for gi, group_cells in enumerate(cells_per_group):
                is_bottom = gi == n_groups - 1
                for ti, cell in enumerate(group_cells):
                    if ti >= len(ha.tracks):
                        break
                    track = ha.tracks[ti]
                    if isinstance(track, CategoricalTrack):
                        continue
                    xax = self._axis_name(fig, cell, "x")
                    yax = self._axis_name(fig, cell, "y")
                    fig.layout[xax].update(**_BORDER)
                    fig.layout[yax].update(**_BORDER)
                    # Value-axis ticks only on the bottom group
                    if is_bottom:
                        if orientation == "col":
                            fig.layout[yax].update(**_TICK)
                        else:
                            fig.layout[xax].update(**_TICK)

        # Top annotations: flatten into a single group so ti maps to track index
        if self.top_annotation:
            _apply_numeric_border(self.top_annotation, [[c[0] for c in layout.top_anno_cells]], "col")

        # Bottom annotations
        if self.bottom_annotation:
            _apply_numeric_border(self.bottom_annotation, [[c[0] for c in layout.bottom_anno_cells]], "col")

        # Left annotations: cells_per_group[gi] has one cell per track
        if self.left_annotation:
            _apply_numeric_border(self.left_annotation, layout.left_anno_cells, "row")

        # Right annotations
        if self.right_annotation:
            _apply_numeric_border(self.right_annotation, layout.right_anno_cells, "row")

    def _place_row_labels(self, fig: go.Figure, layout: GridLayout, has_right_anno: bool) -> None:
        """Put row tick labels on the rightmost subplot column."""
        if self._split_groups is not None:
            self._place_row_labels_split(fig, layout, has_right_anno)
            return

        if has_right_anno:
            label_cell = layout.right_anno_cells[0][-1]
        else:
            label_cell = layout.heatmap_cells[0]

        n = len(self._row_labels)
        y_range = [n - 0.5, -0.5]  # reversed: row 0 at top

        yax = self._axis_name(fig, label_cell, "y")
        fig.layout[yax].update(
            tickvals=list(range(n)),
            ticktext=self._row_labels,
            showticklabels=True,
            side="right",
            range=y_range,
            autorange=False,
            tickfont={"size": 9, "family": FONT_FAMILY},
        )

        hm_yax = self._axis_name(fig, layout.heatmap_cells[0], "y")
        fig.layout[hm_yax].update(range=y_range, autorange=False)

    def _place_row_labels_split(self, fig: go.Figure, layout: GridLayout, has_right_anno: bool) -> None:
        assert self._split_groups is not None
        assert self._group_indices is not None

        offset = 0
        for gi, g in enumerate(self._split_groups):
            gs = len(self._group_indices[g])
            rl = self._row_labels[offset : offset + gs]

            if has_right_anno and gi < len(layout.right_anno_cells) and layout.right_anno_cells[gi]:
                label_cell = layout.right_anno_cells[gi][-1]
            else:
                label_cell = layout.heatmap_cells[gi]

            y_range = [gs - 0.5, -0.5]  # reversed: row 0 at top

            yax = self._axis_name(fig, label_cell, "y")
            fig.layout[yax].update(
                tickvals=list(range(gs)),
                ticktext=rl,
                showticklabels=True,
                side="right",
                range=y_range,
                autorange=False,
                tickfont={"size": 9, "family": FONT_FAMILY},
            )

            hm_yax = self._axis_name(fig, layout.heatmap_cells[gi], "y")
            fig.layout[hm_yax].update(range=y_range, autorange=False)

            offset += gs

    def _constrain_y_ranges(self, fig: go.Figure, layout: GridLayout) -> None:
        """Set explicit y-range on every subplot in each heatmap row.

        This ensures dendrograms, annotations, and the heatmap itself share
        an identical y-extent with no extra padding — critical for box,
        violin, and scatter annotation tracks whose data might otherwise
        cause Plotly to expand the axis.
        """

        def _set_range(cells: list[tuple[int, int]], y_range: list[float]) -> None:
            for cell in cells:
                yax = self._axis_name(fig, cell, "y")
                fig.layout[yax].update(range=y_range, autorange=False)

        if self._split_groups is not None:
            assert self._group_indices is not None
            for gi, g in enumerate(self._split_groups):
                gs = len(self._group_indices[g])
                y_range = [gs - 0.5, -0.5]
                cells: list[tuple[int, int]] = []
                if gi < len(layout.heatmap_cells):
                    cells.append(layout.heatmap_cells[gi])
                if gi < len(layout.row_dendro_cells):
                    cells.append(layout.row_dendro_cells[gi])
                if gi < len(layout.left_anno_cells):
                    cells.extend(layout.left_anno_cells[gi])
                if gi < len(layout.right_anno_cells):
                    cells.extend(layout.right_anno_cells[gi])
                _set_range(cells, y_range)
        else:
            n = self._data.shape[0]
            y_range = [n - 0.5, -0.5]
            cells = list(layout.heatmap_cells) + list(layout.row_dendro_cells)
            for group_cells in layout.left_anno_cells:
                cells.extend(group_cells)
            for group_cells in layout.right_anno_cells:
                cells.extend(group_cells)
            _set_range(cells, y_range)

    def _style_figure(self, fig: go.Figure, layout: GridLayout) -> None:
        """Apply global figure styling: margins, legend, font, background."""
        has_legend = any(
            a is not None
            for a in (self.top_annotation, self.bottom_annotation, self.left_annotation, self.right_annotation)
        )

        # Right margin must fit: row labels + colorbar + legend
        max_label_len = max((len(lbl) for lbl in self._row_labels), default=0)
        label_px = max_label_len * 7 + 10
        colorbar_px = 50
        legend_px = 120 if has_legend else 0
        right_margin = label_px + colorbar_px + legend_px

        # Left margin for left annotations or dendrogram
        left_margin = 5

        legend_x_frac = 1.0 + (label_px + colorbar_px + 8) / self.width

        fig.update_layout(
            width=self.width,
            height=self.height,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="white",
            margin={"l": left_margin, "r": right_margin, "t": 30, "b": 5},
            font={"family": FONT_FAMILY, "size": 11},
            legend={
                "x": legend_x_frac,
                "y": 1.0,
                "xanchor": "left",
                "yanchor": "top",
                "font": {"size": 10, "family": FONT_FAMILY},
                "tracegroupgap": 8,
                "itemsizing": "constant",
                "bgcolor": "rgba(255,255,255,0.8)",
                "bordercolor": "#cccccc",
                "borderwidth": 1,
            },
        )

    @staticmethod
    def _axis_name(fig: go.Figure, cell: tuple[int, int], axis: str) -> str:
        """Resolve the Plotly axis property name for a subplot cell.

        ``cell`` is 1-indexed ``(row, col)``.
        """
        ref = fig.get_subplot(cell[0], cell[1])
        if ref is None:
            return f"{axis}axis"
        attr = ref.xaxis if axis == "x" else ref.yaxis
        name = attr.plotly_name
        return name


def _to_pandas(df: Any, *, index_column: str | None = None) -> Any:
    """Normalise a pandas or polars DataFrame to a pandas DataFrame.

    If *index_column* is given the corresponding column is set as the index
    (works for both pandas and polars inputs).
    """
    import pandas as pd

    # Polars — import separately so conversion errors propagate clearly
    try:
        import polars as pl
    except ImportError:
        pl = None  # type: ignore[assignment]

    if pl is not None and isinstance(df, pl.DataFrame):
        pdf = df.to_pandas()
        if index_column is not None:
            pdf = pdf.set_index(index_column)
        return pdf

    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"Expected a pandas or polars DataFrame, got {type(df).__name__}")

    if index_column is not None:
        df = df.set_index(index_column)
    return df


def _slice_track(track: Any, sliced_vals: list[Any]) -> Any:
    """Create a temporary track slice for split annotations."""
    from plotly_complexheatmap.annotations import (
        BoxTrack,
        CategoricalTrack,
        NumericBarTrack,
        NumericScatterTrack,
        StackedBarTrack,
        ViolinTrack,
    )

    if isinstance(track, CategoricalTrack):
        tmp = CategoricalTrack(name=track.name, values=sliced_vals, which=track.which, size=track.size)
        tmp.colors = track.colors
        tmp._categories = track._categories
        tmp._cat_to_int = track._cat_to_int
        return tmp
    if isinstance(track, NumericBarTrack):
        return NumericBarTrack(name=track.name, values=sliced_vals, color=track.color, size=track.size)
    if isinstance(track, NumericScatterTrack):
        return NumericScatterTrack(
            name=track.name,
            values=sliced_vals,
            color=track.color,
            marker_size=track.marker_size,
            size=track.size,
        )
    if isinstance(track, StackedBarTrack):
        return StackedBarTrack(
            name=track.name,
            values=sliced_vals,
            stack_names=track.stack_names,
            colors=track.colors,
            size=track.size,
        )
    if isinstance(track, BoxTrack):
        return BoxTrack(name=track.name, values=sliced_vals, color=track.color, size=track.size)
    if isinstance(track, ViolinTrack):
        return ViolinTrack(name=track.name, values=sliced_vals, color=track.color, size=track.size)
    return None
