"""Annotation track types and the ``HeatmapAnnotation`` container."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from numpy.typing import NDArray

from plotly_complexheatmap.utils import categorical_colorscale, generate_colors

# Default track sizes (fraction of figure dimension)
_CATEGORICAL_SIZE = 0.025  # thin colour bar like ComplexHeatmap
_NUMERIC_SIZE = 0.06  # bar/scatter need more room

# ---------------------------------------------------------------------------
# Individual track types
# ---------------------------------------------------------------------------


@dataclass
class AnnotationTrack:
    """Base class for a single annotation track."""

    name: str
    values: Any
    size: float = _CATEGORICAL_SIZE

    def to_traces(self, axis: str, positions: NDArray[np.floating]) -> list[go.BaseTraceType]:
        raise NotImplementedError

    def legend_items(self) -> list[go.Scatter]:
        return []


@dataclass
class CategoricalTrack(AnnotationTrack):
    """Discrete colour-bar rendered as a 1-pixel-high/wide ``go.Heatmap``.

    Black cell borders are added via ``xgap``/``ygap`` to match the
    ComplexHeatmap visual style.
    """

    colors: dict[str, str] | None = None
    which: str = "column"
    size: float = _CATEGORICAL_SIZE
    _categories: list[str] = field(default_factory=list, init=False, repr=False)
    _cat_to_int: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        cats = pd.Categorical(self.values).categories.tolist()
        if self.colors is None:
            palette = generate_colors(len(cats), which=self.which)
            self.colors = dict(zip(cats, palette))
        self._categories = cats
        self._cat_to_int = {c: i for i, c in enumerate(cats)}

    def to_traces(self, axis: str, positions: NDArray[np.floating]) -> list[go.BaseTraceType]:
        numeric = np.array([self._cat_to_int[v] for v in self.values])
        n = len(self._categories)
        cs = categorical_colorscale([self.colors[c] for c in self._categories], n)

        # Border gap gives the black-outlined ComplexHeatmap look
        border = {"xgap": 1, "ygap": 1}

        if axis == "x":
            z = numeric.reshape(1, -1)
            custom = np.array(self.values, dtype=object).reshape(1, -1)
            trace = go.Heatmap(
                z=z,
                x=positions,
                y=[self.name],
                colorscale=cs,
                zmin=-0.5,
                zmax=n - 0.5,
                showscale=False,
                hovertemplate=f"{self.name}: %{{customdata}}<extra></extra>",
                customdata=custom,
                **border,
            )
        else:
            z = numeric.reshape(-1, 1)
            custom = np.array(self.values, dtype=object).reshape(-1, 1)
            trace = go.Heatmap(
                z=z,
                x=[self.name],
                y=positions,
                colorscale=cs,
                zmin=-0.5,
                zmax=n - 0.5,
                showscale=False,
                hovertemplate=f"{self.name}: %{{customdata}}<extra></extra>",
                customdata=custom,
                **border,
            )
        return [trace]

    def legend_items(self) -> list[go.Scatter]:
        items: list[go.Scatter] = []
        assert self.colors is not None
        for cat in self._categories:
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
class NumericBarTrack(AnnotationTrack):
    """Bar-chart annotation track (like ``anno_barplot`` in ComplexHeatmap)."""

    color: str = "#4C78A8"
    size: float = _NUMERIC_SIZE

    def to_traces(self, axis: str, positions: NDArray[np.floating]) -> list[go.BaseTraceType]:
        vals = np.asarray(self.values, dtype=float)
        if axis == "x":
            return [
                go.Bar(
                    x=positions,
                    y=vals,
                    marker_color=self.color,
                    marker_line_color="#333333",
                    marker_line_width=0.5,
                    name=self.name,
                    showlegend=False,
                    hovertemplate=f"{self.name}: %{{y:.2f}}<extra></extra>",
                )
            ]
        return [
            go.Bar(
                x=vals,
                y=positions,
                orientation="h",
                marker_color=self.color,
                marker_line_color="#333333",
                marker_line_width=0.5,
                name=self.name,
                showlegend=False,
                hovertemplate=f"{self.name}: %{{x:.2f}}<extra></extra>",
            )
        ]


@dataclass
class NumericScatterTrack(AnnotationTrack):
    """Scatter / point annotation track."""

    color: str = "#E45756"
    marker_size: int = 5
    size: float = _NUMERIC_SIZE

    def to_traces(self, axis: str, positions: NDArray[np.floating]) -> list[go.BaseTraceType]:
        vals = np.asarray(self.values, dtype=float)
        common = {
            "mode": "markers",
            "marker": {"color": self.color, "size": self.marker_size},
            "name": self.name,
            "showlegend": False,
        }
        if axis == "x":
            return [
                go.Scatter(
                    x=positions,
                    y=vals,
                    hovertemplate=f"{self.name}: %{{y:.2f}}<extra></extra>",
                    **common,
                )
            ]
        return [
            go.Scatter(
                x=vals,
                y=positions,
                hovertemplate=f"{self.name}: %{{x:.2f}}<extra></extra>",
                **common,
            )
        ]


_STACKED_SIZE = 0.08  # stacked bars need a bit more room
_BOX_SIZE = 0.08
_VIOLIN_SIZE = 0.08


@dataclass
class StackedBarTrack(AnnotationTrack):
    """Stacked bar-chart annotation (like ``anno_barplot`` with stacking).

    *values* must be a 2-D array-like of shape ``(n_items, n_stacks)``.
    *stack_names* labels each stack; *colors* maps stack name → colour.
    """

    stack_names: list[str] = field(default_factory=list)
    colors: list[str] | None = None
    size: float = _STACKED_SIZE

    def __post_init__(self) -> None:
        arr = np.asarray(self.values, dtype=float)
        if arr.ndim != 2:
            raise ValueError("StackedBarTrack values must be 2-D (n_items × n_stacks)")
        n_stacks = arr.shape[1]
        if not self.stack_names:
            self.stack_names = [f"stack_{i}" for i in range(n_stacks)]
        if self.colors is None:
            self.colors = generate_colors(n_stacks)

    def to_traces(self, axis: str, positions: NDArray[np.floating]) -> list[go.BaseTraceType]:
        arr = np.asarray(self.values, dtype=float)
        traces: list[go.BaseTraceType] = []
        assert self.colors is not None
        for si in range(arr.shape[1]):
            sname = self.stack_names[si] if si < len(self.stack_names) else f"stack_{si}"
            color = self.colors[si] if si < len(self.colors) else "#888888"
            vals = arr[:, si]
            if axis == "x":
                traces.append(
                    go.Bar(
                        x=positions,
                        y=vals,
                        marker_color=color,
                        marker_line_color="#333333",
                        marker_line_width=0.5,
                        name=f"{self.name}: {sname}",
                        legendgroup=self.name,
                        showlegend=False,
                        hovertemplate=f"{sname}: %{{y:.2f}}<extra></extra>",
                    )
                )
            else:
                traces.append(
                    go.Bar(
                        x=vals,
                        y=positions,
                        orientation="h",
                        marker_color=color,
                        marker_line_color="#333333",
                        marker_line_width=0.5,
                        name=f"{self.name}: {sname}",
                        legendgroup=self.name,
                        showlegend=False,
                        hovertemplate=f"{sname}: %{{x:.2f}}<extra></extra>",
                    )
                )
        return traces

    def legend_items(self) -> list[go.Scatter]:
        items: list[go.Scatter] = []
        assert self.colors is not None
        for si, sname in enumerate(self.stack_names):
            color = self.colors[si] if si < len(self.colors) else "#888888"
            items.append(
                go.Scatter(
                    x=[None],
                    y=[None],
                    mode="markers",
                    marker={"size": 10, "color": color, "symbol": "square"},
                    name=f"{self.name}: {sname}",
                    legendgroup=self.name,
                    legendgrouptitle={"text": self.name},
                    showlegend=True,
                )
            )
        return items


@dataclass
class BoxTrack(AnnotationTrack):
    """Box-plot annotation track (like ``anno_boxplot`` in ComplexHeatmap).

    *values* is a 2-D array-like of shape ``(n_items, n_observations)`` — one
    box per item (row or column of the heatmap).
    """

    color: str = "#72B7B2"
    size: float = _BOX_SIZE

    def to_traces(self, axis: str, positions: NDArray[np.floating]) -> list[go.BaseTraceType]:
        arr = np.asarray(self.values, dtype=float)
        # One trace per row — explicit width constrains each box to one row height
        n = len(positions)
        # Position spacing: typically 1.0 for integer positions
        spacing = float(positions[1] - positions[0]) if n > 1 else 1.0
        box_width = spacing * 0.75
        traces: list[go.BaseTraceType] = []
        for idx in range(arr.shape[0]):
            obs = arr[idx]
            pos_val = float(positions[idx])
            n_obs = len(obs)
            if axis == "x":
                traces.append(
                    go.Box(
                        y=obs.tolist(),
                        x=[pos_val] * n_obs,
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
            else:
                traces.append(
                    go.Box(
                        x=obs.tolist(),
                        y=[pos_val] * n_obs,
                        width=box_width,
                        marker_color=self.color,
                        line_color=self.color,
                        fillcolor=self.color,
                        name=self.name,
                        showlegend=False,
                        boxpoints=False,
                        orientation="h",
                        hoverinfo="x",
                    )
                )
        return traces


@dataclass
class ViolinTrack(AnnotationTrack):
    """Violin-plot annotation track (like ``anno_violin`` in ComplexHeatmap).

    *values* is a 2-D array-like of shape ``(n_items, n_observations)``.
    """

    color: str = "#FF9DA7"
    size: float = _VIOLIN_SIZE

    def to_traces(self, axis: str, positions: NDArray[np.floating]) -> list[go.BaseTraceType]:
        arr = np.asarray(self.values, dtype=float)
        # One trace per row — explicit width constrains each violin to one row height
        n = len(positions)
        spacing = float(positions[1] - positions[0]) if n > 1 else 1.0
        vln_width = spacing * 0.75
        traces: list[go.BaseTraceType] = []
        for idx in range(arr.shape[0]):
            obs = arr[idx]
            pos_val = float(positions[idx])
            n_obs = len(obs)
            if axis == "x":
                traces.append(
                    go.Violin(
                        y=obs.tolist(),
                        x=[pos_val] * n_obs,
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
            else:
                traces.append(
                    go.Violin(
                        x=obs.tolist(),
                        y=[pos_val] * n_obs,
                        width=vln_width,
                        scalemode="width",
                        marker_color=self.color,
                        line_color=self.color,
                        fillcolor=self.color,
                        name=self.name,
                        showlegend=False,
                        orientation="h",
                        hoverinfo="x",
                        meanline_visible=True,
                        points=False,
                    )
                )
        return traces


# ---------------------------------------------------------------------------
# Container
# ---------------------------------------------------------------------------


class HeatmapAnnotation:
    """Collection of annotation tracks — analogous to R's ``HeatmapAnnotation``.

    Pass track data as keyword arguments.  The type is auto-detected
    (string/categorical -> colour bar, numeric -> bar chart) or can be forced
    via a ``dict`` value with a ``"type"`` key.

    Parameters
    ----------
    which:
        ``"column"`` for top/bottom annotations (indexed by heatmap columns),
        ``"row"`` for left/right annotations (indexed by heatmap rows).
    gap:
        Relative gap between tracks (fraction of figure height/width).
    **kwargs:
        ``name=values`` pairs that become annotation tracks.
    """

    def __init__(
        self,
        which: str = "column",
        gap: float = 0.005,
        **kwargs: Sequence[Any] | dict[str, Any],
    ) -> None:
        self.which = which
        self.gap = gap
        self.tracks: list[AnnotationTrack] = []

        for name, values in kwargs.items():
            if isinstance(values, dict):
                track = self._from_dict(name, values, which=self.which)
            else:
                track = self._infer(name, values, which=self.which)
            self.tracks.append(track)

    # -- factory helpers -----------------------------------------------------

    @staticmethod
    def _infer(name: str, values: Sequence[Any], which: str = "column") -> AnnotationTrack:
        arr = np.asarray(values)
        if arr.dtype.kind in ("U", "S", "O"):
            return CategoricalTrack(name=name, values=list(values), which=which)
        if arr.dtype.kind == "i" and len(np.unique(arr)) <= 10:
            return CategoricalTrack(name=name, values=[str(v) for v in values], which=which)
        return NumericBarTrack(name=name, values=values)

    @staticmethod
    def _from_dict(name: str, cfg: dict[str, Any], which: str = "column") -> AnnotationTrack:
        vals = cfg["values"]
        tp = cfg.get("type", "auto")
        sz = cfg.get("size")
        if tp == "categorical":
            return CategoricalTrack(
                name=name, values=list(vals), colors=cfg.get("colors"), which=which, size=sz or _CATEGORICAL_SIZE
            )
        if tp == "bar":
            return NumericBarTrack(name=name, values=vals, color=cfg.get("color", "#4C78A8"), size=sz or _NUMERIC_SIZE)
        if tp == "scatter":
            return NumericScatterTrack(
                name=name,
                values=vals,
                color=cfg.get("color", "#E45756"),
                size=sz or _NUMERIC_SIZE,
            )
        if tp == "stacked_bar":
            return StackedBarTrack(
                name=name,
                values=vals,
                stack_names=cfg.get("stack_names", []),
                colors=cfg.get("colors"),
                size=sz or _STACKED_SIZE,
            )
        if tp == "box":
            return BoxTrack(
                name=name,
                values=vals,
                color=cfg.get("color", "#72B7B2"),
                size=sz or _BOX_SIZE,
            )
        if tp == "violin":
            return ViolinTrack(
                name=name,
                values=vals,
                color=cfg.get("color", "#FF9DA7"),
                size=sz or _VIOLIN_SIZE,
            )
        return HeatmapAnnotation._infer(name, vals, which=which)

    # -- helpers -------------------------------------------------------------

    @property
    def n_tracks(self) -> int:
        return len(self.tracks)

    def total_size(self) -> float:
        """Total fraction of figure consumed by all tracks + gaps."""
        if not self.tracks:
            return 0.0
        return sum(t.size for t in self.tracks) + self.gap * max(0, len(self.tracks) - 1)

    def reorder(self, order: NDArray[np.intp]) -> HeatmapAnnotation:
        """Return a **new** ``HeatmapAnnotation`` with tracks reordered by *order*."""
        ha = HeatmapAnnotation.__new__(HeatmapAnnotation)
        ha.which = self.which
        ha.gap = self.gap
        ha.tracks = []

        for track in self.tracks:
            vals = np.asarray(track.values)
            new_vals = vals[order]  # works for both 1-D and 2-D

            if isinstance(track, CategoricalTrack):
                nt = CategoricalTrack(name=track.name, values=new_vals.tolist(), which=track.which, size=track.size)
                nt.colors = track.colors
                nt._categories = track._categories
                nt._cat_to_int = track._cat_to_int
            elif isinstance(track, NumericBarTrack):
                nt = NumericBarTrack(name=track.name, values=new_vals.tolist(), color=track.color, size=track.size)
            elif isinstance(track, NumericScatterTrack):
                nt = NumericScatterTrack(
                    name=track.name,
                    values=new_vals.tolist(),
                    color=track.color,
                    marker_size=track.marker_size,
                    size=track.size,
                )
            elif isinstance(track, StackedBarTrack):
                nt = StackedBarTrack(
                    name=track.name,
                    values=new_vals.tolist(),
                    stack_names=track.stack_names,
                    colors=track.colors,
                    size=track.size,
                )
            elif isinstance(track, BoxTrack):
                nt = BoxTrack(name=track.name, values=new_vals.tolist(), color=track.color, size=track.size)
            elif isinstance(track, ViolinTrack):
                nt = ViolinTrack(name=track.name, values=new_vals.tolist(), color=track.color, size=track.size)
            else:
                raise TypeError(f"Unsupported track type: {type(track)}")

            ha.tracks.append(nt)

        return ha
