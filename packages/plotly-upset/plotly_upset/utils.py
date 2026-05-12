"""Color utilities, data validation, and shared constants."""

from __future__ import annotations

import colorsys
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

FONT_FAMILY = "Arial, Helvetica, sans-serif"

# Default UpSet qualitative palette
UPSET_PALETTE = [
    "#333333",
    "#4C78A8",
    "#E45756",
    "#72B7B2",
    "#FF9DA7",
    "#54A24B",
    "#EECA3B",
    "#B279A2",
    "#FF9D00",
    "#9D755D",
    "#E41A1C",
    "#377EB8",
    "#4DAF4A",
    "#984EA3",
    "#FF7F00",
    "#A65628",
    "#F781BF",
    "#66C2A5",
    "#8DA0CB",
    "#FC8D62",
]


def generate_colors(n: int) -> list[str]:
    """Generate *n* visually distinct colors.

    Uses the palette for small *n*, then falls back to HSL generation.
    """
    if n <= len(UPSET_PALETTE):
        return UPSET_PALETTE[:n]

    colors: list[str] = []
    for i in range(n):
        hue = (i / n) % 1.0
        r, g, b = colorsys.hls_to_rgb(hue, 0.5, 0.7)
        colors.append(f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}")
    return colors


def categorical_colorscale(colors: list[str], n: int) -> list[list[float | str]]:
    """Build a discrete Plotly colorscale where each colour fills one equal band."""
    scale: list[list[float | str]] = []
    for i, color in enumerate(colors):
        scale.append([i / n, color])
        scale.append([(i + 1) / n, color])
    return scale


def validate_binary_data(
    data: Any,
    set_columns: list[str] | None = None,
) -> tuple[NDArray[np.int_], list[str], pd.DataFrame]:
    """Validate input and extract binary matrix.

    Returns ``(binary_matrix, set_names, full_dataframe)``.

    Accepts ``pandas.DataFrame`` or ``polars.DataFrame``.
    If *set_columns* is ``None``, all columns with only 0/1 values
    are auto-detected as set columns.
    """
    df = _to_pandas(data)

    if set_columns is not None:
        missing = [c for c in set_columns if c not in df.columns]
        if missing:
            raise ValueError(f"Columns not found in data: {missing}")
        set_names = list(set_columns)
    else:
        set_names = []
        for col in df.columns:
            vals = df[col].dropna().unique()
            if len(vals) > 0 and set(vals).issubset({0, 1, 0.0, 1.0, True, False}):
                set_names.append(col)
        if not set_names:
            raise ValueError("No binary (0/1) columns found in data. Specify set_columns explicitly.")

    binary_matrix = df[set_names].values.astype(int)

    # Validate that all values are 0 or 1
    unique_vals = np.unique(binary_matrix)
    if not np.all(np.isin(unique_vals, [0, 1])):
        raise ValueError(f"Binary columns must contain only 0 and 1, found: {unique_vals}")

    return binary_matrix, set_names, df


def _to_pandas(data: Any) -> pd.DataFrame:
    """Convert input to a pandas DataFrame."""
    if isinstance(data, pd.DataFrame):
        return data

    try:
        import polars as pl
    except ImportError:
        pl = None  # type: ignore[assignment]

    if pl is not None and isinstance(data, pl.DataFrame):
        return data.to_pandas()

    raise TypeError(f"Expected pandas or polars DataFrame, got {type(data).__name__}")
