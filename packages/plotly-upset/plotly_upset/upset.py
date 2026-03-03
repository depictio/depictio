"""Main ``UpSetPlot`` class — the public entry-point."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from numpy.typing import NDArray

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
from plotly_upset.utils import FONT_FAMILY, generate_colors, validate_binary_data


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
    set_colors:
        Per-set colors. Either a ``dict`` mapping set name to color,
        or a ``list`` of colors (one per set, positional). When provided,
        dots, set-size bars, and edges are colored per-set.
    color_intersections_by:
        How to color intersection bars. ``None`` uses a single *color*;
        ``"set"`` colors degree-1 bars by their set color and multi-set
        bars with a neutral dark color; ``"degree"`` assigns a color per
        degree level (one legend entry per degree).
    degree_colors:
        Custom color mapping for degree-based coloring, e.g.
        ``{1: "#E41A1C", 2: "#377EB8", 3: "#4DAF4A"}``. Only used when
        ``color_intersections_by="degree"``. Auto-generated when ``None``.
    show_values:
        If ``True``, display intersection count labels on top of bars.
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
        set_colors: dict[str, str] | list[str] | None = None,
        color_intersections_by: str | None = None,
        degree_colors: dict[int, str] | None = None,
        show_values: bool = False,
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
        self.color_intersections_by = color_intersections_by
        self.degree_colors = degree_colors
        self.show_values = show_values
        self.dot_size = dot_size
        self.width = width
        self.height = height

        # Normalize set_colors to a dict
        self._set_colors_map = self._normalize_set_colors(set_colors)

        # Computed during to_plotly()
        self._result: IntersectionResult | None = None
        self._set_sizes: dict[str, int] | None = None
        self._materialized_tracks: list[MaterializedTrack] | None = None

    def _normalize_set_colors(self, set_colors: dict[str, str] | list[str] | None) -> dict[str, str] | None:
        """Convert set_colors input to a dict[str, str] or None."""
        if set_colors is None:
            return None
        if isinstance(set_colors, dict):
            return set_colors
        if isinstance(set_colors, list):
            if len(set_colors) != len(self._set_names):
                raise ValueError(
                    f"set_colors list has {len(set_colors)} items but there are {len(self._set_names)} sets"
                )
            return dict(zip(self._set_names, set_colors))
        raise TypeError(f"set_colors must be dict, list, or None, got {type(set_colors).__name__}")

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

    @classmethod
    def from_dataframe(
        cls,
        df: Any,
        *,
        set_columns: list[str] | None = None,
        annotations: list[str] | dict[str, str | dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> UpSetPlot:
        """Convenience constructor from a single DataFrame containing both
        binary set columns and annotation columns.

        Parameters
        ----------
        df:
            DataFrame containing binary set columns and (optionally)
            annotation columns.
        set_columns:
            Explicit list of binary (0/1) columns to use as sets.
            If ``None``, auto-detects binary columns.
        annotations:
            Columns to use as annotation tracks. Accepts:

            - ``list[str]``: column names, type auto-detected.
            - ``dict[str, str]``: maps track name to column name
              (type auto-detected).
            - ``dict[str, dict]``: maps track name to a full spec dict
              (keys: ``"column"``, ``"type"``, ``"agg"``, ``"color"``,
              ``"size"``, ``"stack_columns"``).
            - ``None``: **auto-detect** — all non-set, non-binary columns
              become annotation tracks.
        **kwargs:
            Forwarded to ``UpSetPlot.__init__()`` (e.g. ``sort_by``,
            ``set_colors``, ``color_intersections_by``, ``show_values``,
            ``title``, ``width``, ``height``, …).
        """
        pdf = cls._ensure_pandas(df)

        # Resolve set columns
        if set_columns is not None:
            missing = [c for c in set_columns if c not in pdf.columns]
            if missing:
                raise ValueError(f"Columns not found in data: {missing}")
            resolved_sets = list(set_columns)
        else:
            resolved_sets = []
            for col in pdf.columns:
                vals = pdf[col].dropna().unique()
                if len(vals) > 0 and set(vals).issubset({0, 1, 0.0, 1.0, True, False}):
                    resolved_sets.append(col)
            if not resolved_sets:
                raise ValueError("No binary (0/1) columns found. Specify set_columns explicitly.")

        # Resolve annotation specs
        anno_specs: dict[str, str | dict[str, Any]] = {}

        if annotations is None:
            # Auto-detect: every non-set column becomes an annotation
            for col in pdf.columns:
                if col not in resolved_sets:
                    anno_specs[col] = col  # str spec → auto-detect type
        elif isinstance(annotations, list):
            for col in annotations:
                anno_specs[col] = col
        elif isinstance(annotations, dict):
            anno_specs = annotations
        else:
            raise TypeError(f"annotations must be list, dict, or None, got {type(annotations).__name__}")

        # Build UpSetAnnotation if there are annotation columns
        annotation_obj: UpSetAnnotation | None = None
        if anno_specs:
            annotation_obj = UpSetAnnotation(data=pdf, **anno_specs)

        return cls(
            pdf,
            set_columns=resolved_sets,
            annotation=annotation_obj,
            **kwargs,
        )

    @staticmethod
    def _ensure_pandas(data: Any) -> pd.DataFrame:
        """Convert to pandas DataFrame."""
        if isinstance(data, pd.DataFrame):
            return data
        try:
            import polars as pl
        except ImportError:
            pl = None  # type: ignore[assignment]
        if pl is not None and isinstance(data, pl.DataFrame):
            return data.to_pandas()
        raise TypeError(f"Expected pandas or polars DataFrame, got {type(data).__name__}")

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
    # Intersection bar coloring
    # ------------------------------------------------------------------

    def _compute_bar_colors(self) -> str | list[str]:
        """Compute per-bar colors for intersection bars (used by 'set' mode)."""
        assert self._result is not None

        if self.color_intersections_by != "set" or self._set_colors_map is None:
            return self.color

        bar_colors: list[str] = []
        for pattern in self._result.patterns:
            active_sets = [i for i, b in enumerate(pattern) if b == 1]
            if len(active_sets) == 1:
                bar_colors.append(self._set_colors_map.get(self._set_names[active_sets[0]], self.color))
            elif len(active_sets) == 0:
                bar_colors.append(self.inactive_color)
            else:
                bar_colors.append("#333333")
        return bar_colors

    def _get_degree_color_map(self) -> dict[int, str]:
        """Build degree → color mapping for degree-based coloring."""
        assert self._result is not None
        if self.degree_colors is not None:
            return self.degree_colors
        # Auto-generate: one color per unique degree, sorted descending
        unique_degrees = sorted(set(int(d) for d in self._result.degrees), reverse=True)
        palette = generate_colors(len(unique_degrees))
        return dict(zip(unique_degrees, palette))

    # ------------------------------------------------------------------
    # Trace builders
    # ------------------------------------------------------------------

    def _add_intersection_bars(self, fig: go.Figure, layout: UpSetGridLayout) -> None:
        """Add the intersection size bar chart."""
        assert self._result is not None
        positions = np.arange(len(self._result.patterns), dtype=float)
        cell = layout.intersection_bar_cell
        sizes = self._result.sizes.tolist()

        if self.color_intersections_by == "degree":
            self._add_degree_colored_bars(fig, cell, positions, sizes)
        else:
            bar_colors = self._compute_bar_colors()
            bar_kwargs: dict[str, Any] = {
                "x": positions.tolist(),
                "y": sizes,
                "marker_color": bar_colors,
                "marker_line_color": "#555555",
                "marker_line_width": 0.5,
                "name": "Intersection Size",
                "showlegend": False,
                "hovertemplate": "Size: %{y}<extra></extra>",
            }
            if self.show_values:
                bar_kwargs["text"] = [str(s) for s in sizes]
                bar_kwargs["textposition"] = "outside"
                bar_kwargs["textfont"] = {"size": 9, "family": FONT_FAMILY}
            fig.add_trace(go.Bar(**bar_kwargs), row=cell[0], col=cell[1])

    def _add_degree_colored_bars(
        self,
        fig: go.Figure,
        cell: tuple[int, int],
        positions: NDArray[np.floating],
        sizes: list[int],
    ) -> None:
        """Emit one go.Bar per degree group with legend entries."""
        assert self._result is not None
        degree_map = self._get_degree_color_map()
        degrees = [int(d) for d in self._result.degrees]

        # Group indices by degree (sorted descending so highest degree appears first in legend)
        unique_degrees = sorted(set(degrees), reverse=True)
        for deg in unique_degrees:
            mask = [i for i, d in enumerate(degrees) if d == deg]
            x_vals = [float(positions[i]) for i in mask]
            y_vals = [sizes[i] for i in mask]
            color = degree_map.get(deg, "#888888")

            bar_kwargs: dict[str, Any] = {
                "x": x_vals,
                "y": y_vals,
                "marker_color": color,
                "marker_line_color": "#555555",
                "marker_line_width": 0.5,
                "name": str(deg),
                "legendgroup": "degree",
                "legendgrouptitle": {"text": "Nb. of associations"},
                "showlegend": True,
                "hovertemplate": f"Degree {deg}<br>Size: %{{y}}<extra></extra>",
            }
            if self.show_values:
                bar_kwargs["text"] = [str(s) for s in y_vals]
                bar_kwargs["textposition"] = "outside"
                bar_kwargs["textfont"] = {"size": 9, "family": FONT_FAMILY}
            fig.add_trace(go.Bar(**bar_kwargs), row=cell[0], col=cell[1])

    def _add_dot_matrix(self, fig: go.Figure, layout: UpSetGridLayout) -> None:
        """Add the dot-matrix indicator panel."""
        assert self._result is not None
        cell = layout.dot_matrix_cell

        matrix_result = dot_matrix_traces(
            self._result.patterns,
            self._set_names,
            active_color=self.color,
            inactive_color=self.inactive_color,
            set_colors=self._set_colors_map,
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

        # Per-set coloring for set-size bars
        if self._set_colors_map is not None:
            bar_colors: str | list[str] = [self._set_colors_map.get(name, self.color) for name in self._set_names]
        else:
            bar_colors = self.color

        fig.add_trace(
            go.Bar(
                x=sizes,
                y=positions.tolist(),
                orientation="h",
                marker_color=bar_colors,
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

            # Add legend items for categorical tracks (if any remain)
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
