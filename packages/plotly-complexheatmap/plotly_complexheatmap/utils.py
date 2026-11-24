"""Color utilities, data validation, and normalization helpers."""

from __future__ import annotations

import colorsys

import numpy as np
from numpy.typing import NDArray

# Defaults are a dependency-free copy of depictio's "marque" palette
# (depictio/models/palettes/depictio_palettes.json, light mode). This package
# must stay installable on its own, so it cannot import depictio; the test
# depictio/tests/unit/test_palette_copies.py fails when a copy drifts.
#
# Diverging colorscale: the marque diverging ramp (teal - grey - orange).
COMPLEXHEATMAP_COLORSCALE: list[list[float | str]] = [
    [0.0, "#0A6455"],
    [0.1, "#178673"],
    [0.2, "#53A593"],
    [0.3, "#87C1B3"],
    [0.4, "#BDDAD2"],
    [0.5, "#F2F2F2"],
    [0.6, "#F0D4C2"],
    [0.7, "#ECB592"],
    [0.8, "#DF9564"],
    [0.9, "#C97436"],
    [1.0, "#AC5708"],
]

# Default font matching ggplot2 / ComplexHeatmap
FONT_FAMILY = "Arial, Helvetica, sans-serif"

# Categorical palette for annotation tracks: the marque categorical slots minus
# slots 1 and 2, the hues at the two ends of COMPLEXHEATMAP_COLORSCALE, so a group
# is never mistaken for a low or high cell.
COLUMN_PALETTE = [
    "#925FC4",
    "#F288C0",
    "#6495ED",
    "#EBD244",
    "#6EC863",
    "#E53935",
]

# Same palette on the row side: a track keeps the colour of its value on either axis.
ROW_PALETTE = list(COLUMN_PALETTE)

# Default palette (used when side is unknown)
DEFAULT_PALETTE = COLUMN_PALETTE


def generate_colors(n: int, which: str = "column") -> list[str]:
    """Generate *n* visually distinct colors.

    Parameters
    ----------
    n:
        Number of colors to generate.
    which:
        ``"column"`` (top/bottom annotations) or ``"row"`` (left/right
        annotations); both start from the same palette, the generated
        fallback past it is shifted by half a turn on the row side.
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
