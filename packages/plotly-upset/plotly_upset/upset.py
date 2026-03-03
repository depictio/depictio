"""Main ``UpSetPlot`` class — the public entry-point."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from plotly_upset.annotations import MaterializedCategoricalTrack, MaterializedTrack, UpSetAnnotation
from plotly_upset.intersections import (
    IntersectionResult,
    compute_intersections,
    compute_set_sizes,
    filter_intersections,
    sort_intersections,
)
from plotly_upset.layout import UpSetGridLayout, compute_upset_layout, create_figure
from plotly_upset.matrix import dot_matrix_traces
from plotly_upset.utils import FONT_FAMILY, validate_binary_data


class UpSetPlot:
    """UpSet plot with configurable annotations, sorting, and filtering.

    Parameters
    ----------
    data:
        Binary DataFrame (pandas or polars) where each column is a set
        and each row is an element. Values must be 0 or 1.
    set_columns:
        Explicit list of columns to use as sets. If ``None``, auto-detects
        binary columns.
    set_names:
        Override display names for sets. If ``None``, uses column names.
    title:
        Plot title displayed at the top.
    subtitle:
        Description displayed below the title.
    sort_by:
        ``"cardinality"`` (default), ``"degree"``, or ``"input"``.
    sort_order:
        ``"descending"`` (default) or ``"ascending"``.
    min_size / max_size:
        Filter intersections by count.
    min_degree / max_degree:
        Filter intersections by number of participating sets.
    exclude_empty:
        If ``True`` (default), exclude intersections with zero members.
    show_set_sizes:
        Whether to show the horizontal set-size bar chart.
    annotation:
        An ``UpSetAnnotation`` container for per-intersection tracks.
    color:
        Default bar color for intersection bars.
    inactive_color:
        Color for inactive (unfilled) dots.
    dot_size:
        Marker size for matrix dots.
    width / height:
        Figure size in pixels.
    """

    def __init__(
        self,
        data: Any,
        *,
        set_columns: list[str] | None = None,
        set_names: list[str] | None = None,
        title: str | None = None,
        subtitle: str | None = None,
        sort_by: str = "cardinality",
        sort_order: str = "descending",
        min_size: int = 0,
        max_size: int | None = None,
        min_degree: int = 0,
        max_degree: int | None = None,
        exclude_empty: bool = True,
        show_set_sizes: bool = True,
        annotation: UpSetAnnotation | None = None,
        color: str = "#333333",
        inactive_color: str = "#C2C2C2",
        dot_size: int = 12,
        width: int = 900,
        height: int = 700,
    ) -> None:
        self._binary_matrix, self._set_columns, self._full_df = validate_binary_data(data, set_columns)
        self._set_names = set_names if set_names is not None else list(self._set_columns)
        self.title = title
        self.subtitle = subtitle
        self.sort_by = sort_by
        self.sort_order = sort_order
        self.min_size = min_size
        self.max_size = max_size
        self.min_degree = min_degree
        self.max_degree = max_degree
        self.exclude_empty = exclude_empty
        self.show_set_sizes = show_set_sizes
        self.annotation = annotation
        self.color = color
        self.inactive_color = inactive_color
        self.dot_size = dot_size
        self.width = width
        self.height = height

        # Computed during to_plotly()
        self._result: IntersectionResult | None = None
        self._set_sizes: dict[str, int] | None = None
        self._materialized_tracks: list[MaterializedTrack] | None = None

    @classmethod
    def from_sets(
        cls,
        sets: dict[str, set[Any]],
        *,
        data: Any | None = None,
        **kwargs: Any,
    ) -> UpSetPlot:
        """Convenience constructor from a dict of named sets.

        Builds the binary DataFrame automatically. If *data* is provided
        (a DataFrame with the same index), its columns can be used as
        annotation sources.
        """
        all_elements = sorted(set().union(*sets.values()), key=str)
        binary_data = {name: [1 if elem in s else 0 for elem in all_elements] for name, s in sets.items()}
        binary_df = pd.DataFrame(binary_data, index=all_elements)

        if data is not None:
            if isinstance(data, pd.DataFrame):
                # Merge extra columns onto the binary DataFrame
                extra_cols = [c for c in data.columns if c not in binary_df.columns]
                if extra_cols:
                    binary_df = binary_df.join(data[extra_cols], how="left")

        return cls(binary_df, **kwargs)

    def to_plotly(self) -> go.Figure:
        """Build and return the complete Plotly ``Figure``."""
        self._compute()
        self._materialize_annotations()

        layout = self._build_layout()
        fig = create_figure(layout)

        self._add_intersection_bars(fig, layout)
        self._add_dot_matrix(fig, layout)
        self._add_set_size_bars(fig, layout)
        self._add_annotation_tracks(fig, layout)
        self._add_title(fig)
        self._style_axes(fig, layout)
        self._style_figure(fig)

        return fig

    # ------------------------------------------------------------------
    # Computation
    # ------------------------------------------------------------------

    def _compute(self) -> None:
        """Compute intersections, filter, and sort."""
        result = compute_intersections(self._binary_matrix, self._set_names)
        result = filter_intersections(
            result,
            exclude_empty=self.exclude_empty,
            min_size=self.min_size,
            max_size=self.max_size,
            min_degree=self.min_degree,
            max_degree=self.max_degree,
        )
        result = sort_intersections(result, sort_by=self.sort_by, sort_order=self.sort_order)
        self._result = result
        self._set_sizes = compute_set_sizes(self._binary_matrix, self._set_names)

    def _materialize_annotations(self) -> None:
        """Group annotation data by intersection membership."""
        if self.annotation is None or self._result is None:
            self._materialized_tracks = []
            return

        self._materialized_tracks = self.annotation.materialize(
            intersection_indices=self._result.row_indices,
            intersection_order=self._result.patterns,
        )

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self) -> UpSetGridLayout:
        n_tracks = len(self._materialized_tracks) if self._materialized_tracks else 0
        track_sizes = [t.size for t in self._materialized_tracks] if self._materialized_tracks else []
        n_sets = len(self._set_names)

        return compute_upset_layout(
            n_annotation_tracks=n_tracks,
            track_sizes=track_sizes,
            show_set_sizes=self.show_set_sizes,
            n_sets=n_sets,
        )

    # ------------------------------------------------------------------
    # Trace builders
    # ------------------------------------------------------------------

    def _add_intersection_bars(self, fig: go.Figure, layout: UpSetGridLayout) -> None:
        """Add the intersection size bar chart."""
        assert self._result is not None
        positions = np.arange(len(self._result.patterns), dtype=float)
        cell = layout.intersection_bar_cell

        fig.add_trace(
            go.Bar(
                x=positions.tolist(),
                y=self._result.sizes.tolist(),
                marker_color=self.color,
                marker_line_color="#555555",
                marker_line_width=0.5,
                name="Intersection Size",
                showlegend=False,
                hovertemplate="Size: %{y}<extra></extra>",
            ),
            row=cell[0],
            col=cell[1],
        )

    def _add_dot_matrix(self, fig: go.Figure, layout: UpSetGridLayout) -> None:
        """Add the dot-matrix indicator panel."""
        assert self._result is not None
        cell = layout.dot_matrix_cell

        matrix_result = dot_matrix_traces(
            self._result.patterns,
            self._set_names,
            active_color=self.color,
            inactive_color=self.inactive_color,
            dot_size=self.dot_size,
        )

        for trace in matrix_result.traces:
            fig.add_trace(trace, row=cell[0], col=cell[1])

        # Add stripe shapes, scoped to the dot matrix axes
        axis_name = self._axis_name(fig, cell, "x")
        y_axis_name = self._axis_name(fig, cell, "y")
        x_ref = axis_name.replace("axis", "")
        y_ref = y_axis_name.replace("axis", "")

        for shape in matrix_result.shapes:
            shape["xref"] = x_ref
            shape["yref"] = y_ref
            fig.add_shape(**shape)

    def _add_set_size_bars(self, fig: go.Figure, layout: UpSetGridLayout) -> None:
        """Add the horizontal set-size bar chart."""
        if not self.show_set_sizes or layout.set_size_cell is None:
            return

        assert self._set_sizes is not None
        cell = layout.set_size_cell

        sizes = [self._set_sizes[name] for name in self._set_names]
        positions = np.arange(len(self._set_names), dtype=float)

        fig.add_trace(
            go.Bar(
                x=sizes,
                y=positions.tolist(),
                orientation="h",
                marker_color=self.color,
                marker_line_color="#555555",
                marker_line_width=0.5,
                name="Set Size",
                showlegend=False,
                hovertemplate="%{y}: %{x}<extra></extra>",
                customdata=self._set_names,
            ),
            row=cell[0],
            col=cell[1],
        )

    def _add_annotation_tracks(self, fig: go.Figure, layout: UpSetGridLayout) -> None:
        """Add annotation track traces."""
        if not self._materialized_tracks or not layout.annotation_cells:
            return

        assert self._result is not None
        positions = np.arange(len(self._result.patterns), dtype=float)

        for track, cell in zip(self._materialized_tracks, layout.annotation_cells):
            traces = track.to_traces(positions)
            for trace in traces:
                fig.add_trace(trace, row=cell[0], col=cell[1])

            # Add legend items for categorical tracks
            if isinstance(track, MaterializedCategoricalTrack):
                for legend_trace in track.legend_items():
                    fig.add_trace(legend_trace, row=cell[0], col=cell[1])

    def _add_title(self, fig: go.Figure) -> None:
        """Add title and subtitle."""
        if not self.title:
            return

        title_config: dict[str, Any] = {
            "text": self.title,
            "font": {"family": FONT_FAMILY, "size": 16},
            "x": 0.5,
            "xanchor": "center",
        }

        if self.subtitle:
            title_config["subtitle"] = {
                "text": self.subtitle,
                "font": {"family": FONT_FAMILY, "size": 12, "color": "#666666"},
            }

        fig.update_layout(title=title_config)

    # ------------------------------------------------------------------
    # Axis styling
    # ------------------------------------------------------------------

    def _style_axes(self, fig: go.Figure, layout: UpSetGridLayout) -> None:
        """Configure axis ranges, ticks, and labels."""
        assert self._result is not None
        n_intersections = len(self._result.patterns)
        n_sets = len(self._set_names)

        # Intersection bar chart — x-axis range, hide x ticks
        bar_cell = layout.intersection_bar_cell
        bar_x = self._axis_name(fig, bar_cell, "x")
        bar_y = self._axis_name(fig, bar_cell, "y")
        fig.update_layout(
            **{
                bar_x: {
                    "range": [-0.5, n_intersections - 0.5],
                    "showticklabels": False,
                    "showgrid": False,
                    "zeroline": False,
                },
                bar_y: {
                    "title": {"text": "Intersection Size", "font": {"size": 11, "family": FONT_FAMILY}},
                    "showgrid": True,
                    "gridcolor": "rgba(0,0,0,0.1)",
                    "zeroline": True,
                    "zerolinecolor": "rgba(0,0,0,0.2)",
                },
            }
        )

        # Dot matrix — shared x with bars, y shows set names
        dot_cell = layout.dot_matrix_cell
        dot_x = self._axis_name(fig, dot_cell, "x")
        dot_y = self._axis_name(fig, dot_cell, "y")
        fig.update_layout(
            **{
                dot_x: {
                    "range": [-0.5, n_intersections - 0.5],
                    "showticklabels": False,
                    "showgrid": False,
                    "zeroline": False,
                },
                dot_y: {
                    "tickvals": list(range(n_sets)),
                    "ticktext": self._set_names,
                    "showgrid": False,
                    "zeroline": False,
                    "range": [-0.5, n_sets - 0.5],
                },
            }
        )

        # Set size bars — reversed x-axis, shared y with dot matrix
        if layout.set_size_cell is not None:
            ss_cell = layout.set_size_cell
            ss_x = self._axis_name(fig, ss_cell, "x")
            ss_y = self._axis_name(fig, ss_cell, "y")
            fig.update_layout(
                **{
                    ss_x: {
                        "autorange": "reversed",
                        "title": {"text": "Set Size", "font": {"size": 11, "family": FONT_FAMILY}},
                        "showgrid": True,
                        "gridcolor": "rgba(0,0,0,0.1)",
                    },
                    ss_y: {
                        "tickvals": list(range(n_sets)),
                        "ticktext": self._set_names,
                        "showgrid": False,
                        "zeroline": False,
                        "range": [-0.5, n_sets - 0.5],
                    },
                }
            )

        # Annotation track axes
        for i, cell in enumerate(layout.annotation_cells):
            anno_x = self._axis_name(fig, cell, "x")
            anno_y = self._axis_name(fig, cell, "y")
            track_name = (
                self._materialized_tracks[i].name
                if self._materialized_tracks and i < len(self._materialized_tracks)
                else ""
            )
            fig.update_layout(
                **{
                    anno_x: {
                        "range": [-0.5, n_intersections - 0.5],
                        "showticklabels": False,
                        "showgrid": False,
                        "zeroline": False,
                    },
                    anno_y: {
                        "title": {"text": track_name, "font": {"size": 10, "family": FONT_FAMILY}},
                        "showgrid": True,
                        "gridcolor": "rgba(0,0,0,0.08)",
                    },
                }
            )

    def _style_figure(self, fig: go.Figure) -> None:
        """Apply global figure styling."""
        top_margin = 30
        if self.title:
            top_margin = 60
            if self.subtitle:
                top_margin = 80

        fig.update_layout(
            width=self.width,
            height=self.height,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="white",
            margin={"l": 5, "r": 20, "t": top_margin, "b": 20},
            font={"family": FONT_FAMILY, "size": 11},
            barmode="stack",
            showlegend=True,
            legend={
                "font": {"size": 10, "family": FONT_FAMILY},
                "tracegroupgap": 8,
                "itemsizing": "constant",
            },
        )

    @staticmethod
    def _axis_name(fig: go.Figure, cell: tuple[int, int], axis: str) -> str:
        """Resolve the Plotly axis property name for a subplot cell."""
        ref = fig.get_subplot(cell[0], cell[1])
        if ref is None:
            return f"{axis}axis"
        attr = ref.xaxis if axis == "x" else ref.yaxis
        name = attr.plotly_name
        return name
