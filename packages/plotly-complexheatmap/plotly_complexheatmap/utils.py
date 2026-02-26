"""Color utilities, data validation, and normalization helpers."""

from __future__ import annotations

import colorsys

import numpy as np
from numpy.typing import NDArray

# ComplexHeatmap-style blue–white–red diverging colorscale
# Matches circlize::colorRamp2(c(-2, 0, 2), c("#2166AC","#F7F7F7","#B2182B"))
COMPLEXHEATMAP_COLORSCALE: list[list[float | str]] = [
    [0.0, "#2166AC"],
    [0.1, "#4393C3"],
    [0.2, "#92C5DE"],
    [0.3, "#D1E5F0"],
    [0.4, "#F7F7F7"],
    [0.5, "#F7F7F7"],
    [0.6, "#FDDBC7"],
    [0.7, "#F4A582"],
    [0.8, "#D6604D"],
    [0.9, "#B2182B"],
    [1.0, "#67001F"],
]

# Default font matching ggplot2 / ComplexHeatmap
FONT_FAMILY = "Arial, Helvetica, sans-serif"

# Qualitative palette for column annotations (top/bottom) — warm tones
COLUMN_PALETTE = [
    "#E41A1C",
    "#FF7F00",
    "#FFD92F",
    "#A65628",
    "#F781BF",
    "#FC8D62",
    "#E78AC3",
    "#E5C494",
    "#D65F5F",
    "#E8853D",
    "#F0B86E",
    "#C97B84",
    "#F4A582",
    "#FDDBC7",
    "#D6604D",
    "#B2182B",
    "#FFFF33",
    "#A6D854",
    "#FFD92F",
    "#F781BF",
]

# Qualitative palette for row annotations (left/right) — cool tones
ROW_PALETTE = [
    "#377EB8",
    "#4DAF4A",
    "#984EA3",
    "#66C2A5",
    "#8DA0CB",
    "#4EAFB0",
    "#4878CF",
    "#9B72AA",
    "#8DD3C7",
    "#BEBADA",
    "#B3B3B3",
    "#999999",
    "#2166AC",
    "#4393C3",
    "#92C5DE",
    "#6BAED6",
    "#74C476",
    "#31A354",
    "#756BB1",
    "#9E9AC8",
]

# Default palette (used when side is unknown)
DEFAULT_PALETTE = COLUMN_PALETTE


def generate_colors(n: int, which: str = "column") -> list[str]:
    """Generate *n* visually distinct colors.

    Parameters
    ----------
    n:
        Number of colors to generate.
    which:
        ``"column"`` for warm tones (top/bottom annotations),
        ``"row"`` for cool tones (left/right annotations).
    """
    palette = ROW_PALETTE if which == "row" else COLUMN_PALETTE
    if n <= len(palette):
        return palette[:n]

    colors: list[str] = []
    hue_offset = 0.0 if which == "column" else 0.5
    for i in range(n):
        hue = (i / n + hue_offset) % 1.0
        r, g, b = colorsys.hls_to_rgb(hue, 0.5, 0.7)
        colors.append(f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}")
    return colors


def categorical_colorscale(colors: list[str], n: int) -> list[list[float | str]]:
    """Build a discrete Plotly colorscale where each colour fills one equal band.

    For *n* categories the i-th band spans ``[i/n, (i+1)/n]``.
    """
    scale: list[list[float | str]] = []
    for i, color in enumerate(colors):
        scale.append([i / n, color])
        scale.append([(i + 1) / n, color])
    return scale


def normalize_data(
    data: NDArray[np.floating],
    method: str = "none",
) -> NDArray[np.floating]:
    """Z-score normalise a 2-D matrix.

    Parameters
    ----------
    data:
        2-D numeric array.
    method:
        ``"none"`` (identity), ``"row"``, ``"column"``, or ``"global"``.
    """
    if method == "none":
        return data

    result = data.astype(float).copy()

    if method == "row":
        mu = np.nanmean(result, axis=1, keepdims=True)
        sd = np.nanstd(result, axis=1, keepdims=True)
        sd[sd == 0] = 1.0
        result = (result - mu) / sd
    elif method == "column":
        mu = np.nanmean(result, axis=0, keepdims=True)
        sd = np.nanstd(result, axis=0, keepdims=True)
        sd[sd == 0] = 1.0
        result = (result - mu) / sd
    elif method == "global":
        mu = np.nanmean(result)
        sd = float(np.nanstd(result))
        if sd == 0:
            sd = 1.0
        result = (result - mu) / sd
    else:
        raise ValueError(f"Unknown normalization method: {method!r}")

    return result


def validate_data(data: object) -> tuple[NDArray[np.floating], list[str], list[str]]:
    """Validate input and return ``(array, row_labels, col_labels)``.

    Accepts a ``pandas.DataFrame``, ``polars.DataFrame``, or any
    array-like convertible to a 2-D float ndarray.
    """
    import pandas as pd

    if isinstance(data, pd.DataFrame):
        row_labels = [str(x) for x in data.index.tolist()]
        col_labels = [str(x) for x in data.columns.tolist()]
        return data.values.astype(float), row_labels, col_labels

    # Polars DataFrames — import lazily to keep polars optional
    try:
        import polars as pl
    except ImportError:
        pl = None  # type: ignore[assignment]

    if pl is not None and isinstance(data, pl.DataFrame):
        row_labels = [str(i) for i in range(data.height)]
        col_labels = list(data.columns)
        return data.to_numpy(allow_copy=True).astype(float), row_labels, col_labels

    arr = np.asarray(data, dtype=float)
    if arr.ndim != 2:
        raise ValueError(f"Data must be 2-dimensional, got {arr.ndim} dimensions")

    row_labels = [str(i) for i in range(arr.shape[0])]
    col_labels = [str(i) for i in range(arr.shape[1])]
    return arr, row_labels, col_labels
