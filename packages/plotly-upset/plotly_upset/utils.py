"""Color utilities, data validation, and shared constants."""

from __future__ import annotations

import colorsys
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

FONT_FAMILY = "Arial, Helvetica, sans-serif"

# Default UpSet qualitative palette: a dependency-free copy of depictio's "marque"
# categorical slots (depictio/models/palettes/depictio_palettes.json, light mode).
# This package must stay installable on its own, so it cannot import depictio;
# depictio/tests/unit/test_palette_copies.py fails when the copy drifts.
#
# `generate_colors` hands out `UPSET_PALETTE[:n]`, so index 0 is what every
# degenerate or first-assigned case gets (a single-category annotation track,
# the first degree group, the first layer of a stacked bar); it is a hue, never
# a near-black that would read as "unstyled".
UPSET_PALETTE = [
    "#925FC4",
    "#F68B33",
    "#37ADA1",
    "#F288C0",
    "#6495ED",
    "#EBD244",
    "#6EC863",
    "#E53935",
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
