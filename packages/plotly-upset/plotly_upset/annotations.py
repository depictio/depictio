"""UpSet annotation track types and the ``UpSetAnnotation`` container.

Unlike ``HeatmapAnnotation`` which takes pre-computed values, ``UpSetAnnotation``
takes raw DataFrame column references. At render time, the data is grouped
by intersection membership to produce per-intersection distributions or summaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from numpy.typing import NDArray

from plotly_upset.utils import categorical_colorscale, generate_colors

# Default track sizes (fraction of figure dimension)
_BOX_SIZE = 0.08
_VIOLIN_SIZE = 0.08
_BAR_SIZE = 0.06
_SCATTER_SIZE = 0.06
_CATEGORICAL_SIZE = 0.025
_STACKED_BAR_SIZE = 0.08

# Aggregation function registry
_AGG_FUNCS: dict[str, Any] = {
    "mean": np.nanmean,
    "median": np.nanmedian,
    "sum": np.nansum,
    "count": len,
}


# ---------------------------------------------------------------------------
# Track specification (parsed from user input, before materialization)
# ---------------------------------------------------------------------------


@dataclass
class TrackSpec:
    """Parsed specification for a single annotation track."""

    name: str
    column: str
    track_type: str  # "box", "violin", "bar", "scatter", "categorical", "stacked_bar", "auto"
    agg: str = "mean"
    color: str | None = None
    colors: dict[str, str] | None = None
    size: float | None = None
    stack_columns: list[str] | None = None


# ---------------------------------------------------------------------------
# Materialized tracks (after grouping by intersection)
# ---------------------------------------------------------------------------


@dataclass
class MaterializedTrack:
    """Base class for a materialized annotation track."""

    name: str
    size: float

    def to_traces(self, positions: NDArray[np.floating]) -> list[go.BaseTraceType]:
        raise NotImplementedError


@dataclass
class MaterializedBoxTrack(MaterializedTrack):
    """Box plot per intersection."""

    values: list[list[float]] = field(default_factory=list)
    color: str = "#72B7B2"

    def to_traces(self, positions: NDArray[np.floating]) -> list[go.BaseTraceType]:
        traces: list[go.BaseTraceType] = []
        n = len(positions)
        spacing = float(positions[1] - positions[0]) if n > 1 else 1.0
        box_width = spacing * 0.75
        for idx, vals in enumerate(self.values):
            if not vals:
                continue
            pos_val = float(positions[idx])
            traces.append(
                go.Box(
                    y=vals,
                    x=[pos_val] * len(vals),
                    width=box_width,
                    marker_color=self.color,
                    line_color=self.color,
                    fillcolor=self.color,
                    name=self.name,
                    showlegend=False,
                    boxpoints=False,
                    hoverinfo="y",
                )
            )
        return traces


@dataclass
class MaterializedViolinTrack(MaterializedTrack):
    """Violin plot per intersection."""

    values: list[list[float]] = field(default_factory=list)
    color: str = "#FF9DA7"

    def to_traces(self, positions: NDArray[np.floating]) -> list[go.BaseTraceType]:
        traces: list[go.BaseTraceType] = []
        n = len(positions)
        spacing = float(positions[1] - positions[0]) if n > 1 else 1.0
        vln_width = spacing * 0.75
        for idx, vals in enumerate(self.values):
            if len(vals) < 2:
                continue
            pos_val = float(positions[idx])
            traces.append(
                go.Violin(
                    y=vals,
                    x=[pos_val] * len(vals),
                    width=vln_width,
                    scalemode="width",
                    marker_color=self.color,
                    line_color=self.color,
                    fillcolor=self.color,
                    name=self.name,
                    showlegend=False,
                    hoverinfo="y",
                    meanline_visible=True,
                    points=False,
                )
            )
        return traces


@dataclass
class MaterializedBarTrack(MaterializedTrack):
    """Aggregated bar per intersection."""

    values: list[float] = field(default_factory=list)
    color: str = "#4C78A8"

    def to_traces(self, positions: NDArray[np.floating]) -> list[go.BaseTraceType]:
        return [
            go.Bar(
                x=positions.tolist(),
                y=self.values,
                marker_color=self.color,
                marker_line_color="#333333",
                marker_line_width=0.5,
                name=self.name,
                showlegend=False,
                hovertemplate=f"{self.name}: %{{y:.2f}}<extra></extra>",
            )
        ]


@dataclass
class MaterializedScatterTrack(MaterializedTrack):
    """Aggregated scatter point per intersection."""

    values: list[float] = field(default_factory=list)
    color: str = "#E45756"
    marker_size: int = 8

    def to_traces(self, positions: NDArray[np.floating]) -> list[go.BaseTraceType]:
        return [
            go.Scatter(
                x=positions.tolist(),
                y=self.values,
                mode="markers",
                marker={"color": self.color, "size": self.marker_size},
                name=self.name,
                showlegend=False,
                hovertemplate=f"{self.name}: %{{y:.2f}}<extra></extra>",
            )
        ]


@dataclass
class MaterializedCategoricalTrack(MaterializedTrack):
    """Categorical proportion display per intersection."""

    proportions: list[dict[str, float]] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    colors: dict[str, str] = field(default_factory=dict)

    def to_traces(self, positions: NDArray[np.floating]) -> list[go.BaseTraceType]:
        if not self.categories:
            return []

        n_cats = len(self.categories)
        cat_to_int = {c: i for i, c in enumerate(self.categories)}
        color_list = [self.colors[c] for c in self.categories]
        cs = categorical_colorscale(color_list, n_cats)

        # Build a matrix of dominant category per intersection
        z_values: list[int] = []
        hover_text: list[str] = []
        for props in self.proportions:
            if props:
                dominant = max(props, key=props.get)  # type: ignore[arg-type]
                z_values.append(cat_to_int[dominant])
                parts = [f"{k}: {v:.0%}" for k, v in sorted(props.items())]
                hover_text.append("<br>".join(parts))
            else:
                z_values.append(0)
                hover_text.append("")

        z = np.array(z_values).reshape(1, -1)
        custom = np.array(hover_text, dtype=object).reshape(1, -1)

        return [
            go.Heatmap(
                z=z,
                x=positions.tolist(),
                y=[self.name],
                colorscale=cs,
                zmin=-0.5,
                zmax=n_cats - 0.5,
                showscale=False,
                hovertemplate="%{customdata}<extra></extra>",
                customdata=custom,
                xgap=1,
                ygap=1,
            )
        ]

    def legend_items(self) -> list[go.Scatter]:
        items: list[go.Scatter] = []
        for cat in self.categories:
            items.append(
                go.Scatter(
                    x=[None],
                    y=[None],
                    mode="markers",
                    marker={"size": 10, "color": self.colors[cat], "symbol": "square"},
                    name=f"{self.name}: {cat}",
                    legendgroup=self.name,
                    legendgrouptitle={"text": self.name},
                    showlegend=True,
                )
            )
        return items


@dataclass
class MaterializedStackedBarTrack(MaterializedTrack):
    """Stacked bar per intersection with multiple columns."""

    layer_values: dict[str, list[float]] = field(default_factory=dict)
    colors: list[str] = field(default_factory=list)

    def to_traces(self, positions: NDArray[np.floating]) -> list[go.BaseTraceType]:
        traces: list[go.BaseTraceType] = []
        for si, (layer_name, vals) in enumerate(self.layer_values.items()):
            color = self.colors[si] if si < len(self.colors) else "#888888"
            traces.append(
                go.Bar(
                    x=positions.tolist(),
                    y=vals,
                    marker_color=color,
                    marker_line_color="#333333",
                    marker_line_width=0.5,
                    name=f"{self.name}: {layer_name}",
                    legendgroup=self.name,
                    showlegend=False,
                    hovertemplate=f"{layer_name}: %{{y:.2f}}<extra></extra>",
                )
            )
        return traces


# ---------------------------------------------------------------------------
# Container
# ---------------------------------------------------------------------------


class UpSetAnnotation:
    """Container for per-intersection annotation tracks.

    Stores raw DataFrame column references. At render time, ``materialize()``
    groups data by intersection membership.

    Parameters
    ----------
    data:
        Source DataFrame containing annotation columns.
    gap:
        Spacing between annotation tracks.
    **kwargs:
        Track specifications. Each keyword maps a track name to either:

        - A ``str``: column name in *data* (type auto-detected).
        - A ``dict`` with keys ``"column"``, ``"type"``, ``"agg"``, ``"color"``,
          ``"size"``, ``"stack_columns"``.
    """

    def __init__(
        self,
        data: Any,
        gap: float = 0.01,
        **kwargs: str | dict[str, Any],
    ) -> None:
        self.gap = gap
        self._data: pd.DataFrame = self._to_pandas(data)
        self._track_specs: list[TrackSpec] = []

        for name, spec in kwargs.items():
            if isinstance(spec, str):
                self._track_specs.append(TrackSpec(name=name, column=spec, track_type="auto"))
            elif isinstance(spec, dict):
                self._track_specs.append(
                    TrackSpec(
                        name=name,
                        column=spec.get("column", name),
                        track_type=spec.get("type", "auto"),
                        agg=spec.get("agg", "mean"),
                        color=spec.get("color"),
                        colors=spec.get("colors"),
                        size=spec.get("size"),
                        stack_columns=spec.get("stack_columns"),
                    )
                )
            else:
                raise TypeError(f"Track spec for {name!r} must be str or dict, got {type(spec).__name__}")

    @staticmethod
    def _to_pandas(data: Any) -> pd.DataFrame:
        if isinstance(data, pd.DataFrame):
            return data
        try:
            import polars as pl
        except ImportError:
            pl = None  # type: ignore[assignment]
        if pl is not None and isinstance(data, pl.DataFrame):
            return data.to_pandas()
        raise TypeError(f"Expected pandas or polars DataFrame, got {type(data).__name__}")

    @property
    def n_tracks(self) -> int:
        return len(self._track_specs)

    def track_sizes(self) -> list[float]:
        """Return the size of each track (for layout computation)."""
        sizes: list[float] = []
        for spec in self._track_specs:
            if spec.size is not None:
                sizes.append(spec.size)
            elif spec.track_type == "auto":
                sizes.append(self._infer_size(spec))
            else:
                sizes.append(self._default_size(spec.track_type))
        return sizes

    def total_size(self) -> float:
        if not self._track_specs:
            return 0.0
        sizes = self.track_sizes()
        return sum(sizes) + self.gap * max(0, len(sizes) - 1)

    @staticmethod
    def _default_size(track_type: str) -> float:
        return {
            "box": _BOX_SIZE,
            "violin": _VIOLIN_SIZE,
            "bar": _BAR_SIZE,
            "scatter": _SCATTER_SIZE,
            "categorical": _CATEGORICAL_SIZE,
            "stacked_bar": _STACKED_BAR_SIZE,
        }.get(track_type, _BAR_SIZE)

    def _infer_size(self, spec: TrackSpec) -> float:
        col = spec.column
        if col not in self._data.columns:
            return _BAR_SIZE
        dtype = self._data[col].dtype
        if dtype.kind in ("U", "S", "O"):
            return _CATEGORICAL_SIZE
        return _BOX_SIZE

    def _infer_type(self, spec: TrackSpec) -> str:
        col = spec.column
        if col not in self._data.columns:
            return "bar"
        dtype = self._data[col].dtype
        if dtype.kind in ("U", "S", "O"):
            return "categorical"
        if dtype.kind == "i" and self._data[col].nunique() <= 10:
            return "categorical"
        return "box"

    def materialize(
        self,
        intersection_indices: dict[tuple[int, ...], NDArray[np.intp]],
        intersection_order: list[tuple[int, ...]],
    ) -> list[MaterializedTrack]:
        """Group raw data by intersection membership.

        Parameters
        ----------
        intersection_indices:
            Mapping from pattern to row indices.
        intersection_order:
            Sorted/filtered list of patterns (determines x-axis order).
        """
        tracks: list[MaterializedTrack] = []

        for spec in self._track_specs:
            track_type = spec.track_type if spec.track_type != "auto" else self._infer_type(spec)
            size = spec.size if spec.size is not None else self._default_size(track_type)

            if track_type == "box":
                tracks.append(self._materialize_box(spec, intersection_indices, intersection_order, size))
            elif track_type == "violin":
                tracks.append(self._materialize_violin(spec, intersection_indices, intersection_order, size))
            elif track_type == "bar":
                tracks.append(self._materialize_bar(spec, intersection_indices, intersection_order, size))
            elif track_type == "scatter":
                tracks.append(self._materialize_scatter(spec, intersection_indices, intersection_order, size))
            elif track_type == "categorical":
                tracks.append(self._materialize_categorical(spec, intersection_indices, intersection_order, size))
            elif track_type == "stacked_bar":
                tracks.append(self._materialize_stacked_bar(spec, intersection_indices, intersection_order, size))
            else:
                raise ValueError(f"Unknown track type: {track_type!r}")

        return tracks

    def _group_values(
        self,
        column: str,
        intersection_indices: dict[tuple[int, ...], NDArray[np.intp]],
        intersection_order: list[tuple[int, ...]],
    ) -> list[list[float]]:
        """Group column values by intersection, returning list of lists."""
        col_data = self._data[column]
        grouped: list[list[float]] = []
        for pattern in intersection_order:
            idx = intersection_indices[pattern]
            if len(idx) > 0:
                vals = col_data.iloc[idx].dropna().tolist()
                grouped.append([float(v) for v in vals])
            else:
                grouped.append([])
        return grouped

    def _materialize_box(
        self,
        spec: TrackSpec,
        intersection_indices: dict[tuple[int, ...], NDArray[np.intp]],
        intersection_order: list[tuple[int, ...]],
        size: float,
    ) -> MaterializedBoxTrack:
        grouped = self._group_values(spec.column, intersection_indices, intersection_order)
        color = spec.color or "#72B7B2"
        return MaterializedBoxTrack(name=spec.name, size=size, values=grouped, color=color)

    def _materialize_violin(
        self,
        spec: TrackSpec,
        intersection_indices: dict[tuple[int, ...], NDArray[np.intp]],
        intersection_order: list[tuple[int, ...]],
        size: float,
    ) -> MaterializedViolinTrack:
        grouped = self._group_values(spec.column, intersection_indices, intersection_order)
        color = spec.color or "#FF9DA7"
        return MaterializedViolinTrack(name=spec.name, size=size, values=grouped, color=color)

    def _materialize_bar(
        self,
        spec: TrackSpec,
        intersection_indices: dict[tuple[int, ...], NDArray[np.intp]],
        intersection_order: list[tuple[int, ...]],
        size: float,
    ) -> MaterializedBarTrack:
        grouped = self._group_values(spec.column, intersection_indices, intersection_order)
        agg_fn = _AGG_FUNCS.get(spec.agg, np.nanmean)
        aggregated = [float(agg_fn(g)) if g else 0.0 for g in grouped]
        color = spec.color or "#4C78A8"
        return MaterializedBarTrack(name=spec.name, size=size, values=aggregated, color=color)

    def _materialize_scatter(
        self,
        spec: TrackSpec,
        intersection_indices: dict[tuple[int, ...], NDArray[np.intp]],
        intersection_order: list[tuple[int, ...]],
        size: float,
    ) -> MaterializedScatterTrack:
        grouped = self._group_values(spec.column, intersection_indices, intersection_order)
        agg_fn = _AGG_FUNCS.get(spec.agg, np.nanmean)
        aggregated = [float(agg_fn(g)) if g else 0.0 for g in grouped]
        color = spec.color or "#E45756"
        return MaterializedScatterTrack(name=spec.name, size=size, values=aggregated, color=color)

    def _materialize_categorical(
        self,
        spec: TrackSpec,
        intersection_indices: dict[tuple[int, ...], NDArray[np.intp]],
        intersection_order: list[tuple[int, ...]],
        size: float,
    ) -> MaterializedCategoricalTrack:
        col_data = self._data[spec.column]
        categories = sorted(col_data.dropna().unique().tolist())
        n_cats = len(categories)

        if spec.colors:
            colors = spec.colors
        else:
            palette = generate_colors(n_cats)
            colors = dict(zip(categories, palette))

        proportions: list[dict[str, float]] = []
        for pattern in intersection_order:
            idx = intersection_indices[pattern]
            if len(idx) > 0:
                group = col_data.iloc[idx].dropna()
                counts = group.value_counts(normalize=True)
                proportions.append({str(k): float(v) for k, v in counts.items()})
            else:
                proportions.append({})

        return MaterializedCategoricalTrack(
            name=spec.name,
            size=size,
            proportions=proportions,
            categories=[str(c) for c in categories],
            colors={str(k): v for k, v in colors.items()},
        )

    def _materialize_stacked_bar(
        self,
        spec: TrackSpec,
        intersection_indices: dict[tuple[int, ...], NDArray[np.intp]],
        intersection_order: list[tuple[int, ...]],
        size: float,
    ) -> MaterializedStackedBarTrack:
        columns = spec.stack_columns or [spec.column]
        agg_fn = _AGG_FUNCS.get(spec.agg, np.nanmean)

        layer_values: dict[str, list[float]] = {}
        for col in columns:
            col_data = self._data[col]
            aggregated: list[float] = []
            for pattern in intersection_order:
                idx = intersection_indices[pattern]
                if len(idx) > 0:
                    vals = col_data.iloc[idx].dropna().tolist()
                    aggregated.append(float(agg_fn(vals)) if vals else 0.0)
                else:
                    aggregated.append(0.0)
            layer_values[col] = aggregated

        colors = generate_colors(len(columns)) if not spec.color else [spec.color] * len(columns)

        return MaterializedStackedBarTrack(
            name=spec.name,
            size=size,
            layer_values=layer_values,
            colors=colors,
        )
