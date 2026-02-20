"""Shared filter utilities for ref_line_slider component.

Provides build_filter_mask() for applying highlight conditions to Polars DataFrames,
shared between ref_line_slider callbacks and table_component callbacks.
"""

from typing import Any

import polars as pl

from depictio.api.v1.configs.logging_init import logger


def build_filter_mask(
    df: Any,
    conditions: list[dict[str, Any]],
    slider_map: dict[str, float],
    logic: str,
) -> Any:
    """Build a polars filter mask from highlight conditions + slider values.

    Args:
        df: Polars DataFrame.
        conditions: List of condition dicts with column, operator, value/linked_slider.
        slider_map: Mapping of slider tag → current value.
        logic: "and" or "or" combination logic.

    Returns:
        Polars expression or None if no valid conditions.
    """
    masks = []
    for condition in conditions:
        col = condition.get("column")
        op = condition.get("operator", "eq")

        # Resolve value: prefer linked_slider, fall back to static value
        linked_slider = condition.get("linked_slider")
        if linked_slider and linked_slider in slider_map:
            val = slider_map[linked_slider]
        else:
            val = condition.get("value")

        if col is None or val is None:
            continue

        # Handle dot notation (e.g., "sepal.length" → "sepal_length")
        safe_col = col.replace(".", "_") if "." in col else col
        if safe_col not in df.columns and col in df.columns:
            safe_col = col

        if safe_col not in df.columns:
            logger.warning(f"highlight_filter: column '{col}' not found in dataframe")
            continue

        try:
            if op == "eq":
                mask = pl.col(safe_col) == val
            elif op == "ne":
                mask = pl.col(safe_col) != val
            elif op == "gt":
                mask = pl.col(safe_col) > val
            elif op == "gte":
                mask = pl.col(safe_col) >= val
            elif op == "lt":
                mask = pl.col(safe_col) < val
            elif op == "lte":
                mask = pl.col(safe_col) <= val
            else:
                logger.warning(f"highlight_filter: unknown operator '{op}'")
                continue
            masks.append(mask)
        except Exception as e:
            logger.error(f"highlight_filter: error building mask for '{col}': {e}")

    if not masks:
        return None

    combined = masks[0]
    for m in masks[1:]:
        if logic == "or":
            combined = combined | m
        else:
            combined = combined & m

    return combined
