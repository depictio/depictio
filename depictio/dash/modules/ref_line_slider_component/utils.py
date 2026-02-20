"""
Ref Line Slider component utilities.

Standalone slider component that controls reference line positions and
highlight thresholds in linked figure components. Decoupled from data
filtering (unlike interactive components).

Usage in YAML:
    - tag: width-threshold
      component_type: ref_line_slider
      label: "Sepal Width Threshold"
      min: 2.0
      max: 4.5
      default: 3.8
      step: 0.1
"""

import uuid

import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.logging_init import logger

_ACCENT_COLOR = "#f39c12"


def _fmt(v: float) -> str:
    """Format a mark label value compactly."""
    if v > 1e4:
        return f"{v:.1e}"
    if v == int(v):
        return str(int(v))
    return f"{v:.2g}"


def build_ref_line_slider(**kwargs) -> dmc.Paper:
    """Build a standalone reference-line slider component.

    The slider stores its current value and tag in a dcc.Store so that
    linked figure components can update their reference lines and highlights.

    Args:
        **kwargs: Keyword arguments containing:
            - index (str): Unique identifier.
            - tag (str): Human-readable tag matching `linked_slider` in figures.
            - label (str): Display label for the slider.
            - min (float): Minimum slider value.
            - max (float): Maximum slider value.
            - default (float): Initial slider value.
            - step (float | None): Step size (auto-calculated if None).

    Returns:
        dmc.Paper containing the slider with associated value store.
    """
    index = str(kwargs.get("index") or str(uuid.uuid4()))
    tag = kwargs.get("tag") or f"ref-line-slider-{index[:8]}"
    label = kwargs.get("label") or "Threshold"
    min_val = float(kwargs.get("min", 0))
    max_val = float(kwargs.get("max", 100))
    default_val = float(kwargs.get("default", (min_val + max_val) / 2))
    step = kwargs.get("step")
    step_val = float(step) if step is not None else round((max_val - min_val) / 100, 4)

    # Clamp default to [min, max]
    default_val = max(min_val, min(max_val, default_val))

    logger.debug(
        f"Building ref_line_slider: index={index}, tag={tag}, "
        f"min={min_val}, max={max_val}, default={default_val}"
    )

    marks = [
        {"value": min_val, "label": _fmt(min_val)},
        {"value": max_val, "label": _fmt(max_val)},
    ]

    return dmc.Paper(
        id={"type": "ref-line-slider-component", "index": index},
        children=[
            html.Div(
                style={
                    "padding": "8px",
                    "width": "100%",
                    "height": "100%",
                    "display": "flex",
                    "flexDirection": "column",
                    "justifyContent": "center",
                },
                children=[
                    dmc.Group(
                        justify="space-between",
                        align="center",
                        mb=6,
                        children=[
                            dmc.Group(
                                gap="xs",
                                children=[
                                    DashIconify(
                                        icon="mdi:target-variant",
                                        width=16,
                                        color=_ACCENT_COLOR,
                                    ),
                                    dmc.Text(label, size="sm", fw=500),
                                ],
                            ),
                            dmc.Badge(
                                id={"type": "ref-line-slider-display", "index": index},
                                children=f"{default_val:.2f}",
                                variant="light",
                                color="orange",
                                size="sm",
                            ),
                        ],
                    ),
                    dmc.Slider(
                        id={"type": "ref-line-slider", "index": index},
                        value=default_val,
                        min=min_val,
                        max=max_val,
                        step=step_val,
                        color="orange",
                        size="sm",
                        updatemode="drag",
                        marks=marks,
                        mb=4,
                    ),
                    # Store carries both the current value AND the tag so
                    # figure callbacks can map tag → value without knowing UUIDs.
                    dcc.Store(
                        id={"type": "ref-line-slider-value", "index": index},
                        data={"value": default_val, "tag": tag},
                    ),
                ],
            ),
        ],
        w="100%",
        h="100%",
        p=0,
        radius="md",
        withBorder=True,
        style={"borderTop": f"3px solid {_ACCENT_COLOR}"},
    )
