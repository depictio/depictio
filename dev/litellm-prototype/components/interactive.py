"""Interactive filter components."""

from __future__ import annotations

import dash_mantine_components as dmc


def create_select(
    component_id: str,
    label: str,
    options: list[str],
    value: str | None = None,
) -> dmc.Select:
    """Create a single-select dropdown."""
    data = [{"label": str(v), "value": str(v)} for v in sorted(options)]
    return dmc.Select(
        id=component_id,
        label=label,
        data=data,
        value=value or (data[0]["value"] if data else None),
        clearable=True,
        searchable=True,
        w="100%",
        size="sm",
    )


def create_range_slider(
    component_id: str,
    label: str,
    min_val: float,
    max_val: float,
    step: float | None = None,
) -> dmc.Stack:
    """Create a labeled range slider."""
    if step is None:
        span = max_val - min_val
        step = round(span / 100, 2) if span > 0 else 1

    marks = [
        {"value": min_val, "label": f"{min_val:.1f}"},
        {"value": (min_val + max_val) / 2, "label": f"{(min_val + max_val) / 2:.1f}"},
        {"value": max_val, "label": f"{max_val:.1f}"},
    ]

    return dmc.Stack(
        [
            dmc.Text(label, size="sm", fw=500),
            dmc.RangeSlider(
                id=component_id,
                min=min_val,
                max=max_val,
                value=[min_val, max_val],
                marks=marks,
                step=step,
                size="md",
                w="100%",
                styles={"root": {"paddingBottom": "1rem"}},
            ),
        ],
        gap="xs",
    )


def create_multiselect(
    component_id: str,
    label: str,
    options: list[str],
    value: list[str] | None = None,
) -> dmc.MultiSelect:
    """Create a multi-select dropdown."""
    data = [{"label": str(v), "value": str(v)} for v in sorted(options)]
    return dmc.MultiSelect(
        id=component_id,
        label=label,
        data=data,
        value=value or [d["value"] for d in data],
        searchable=True,
        clearable=True,
        w="100%",
        size="sm",
    )
