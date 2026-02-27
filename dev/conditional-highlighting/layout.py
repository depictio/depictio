"""Layout components for the conditional highlighting prototype.

Uses DMC 2.0 AppShell with a sidebar for controls and main area for
the scatter plot, summary card, and AG Grid table.
"""

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc
from dash_iconify import DashIconify
from data import CATEGORICAL_COLS, COLUMN_LABELS, NUMERIC_COLS


def _col_options(cols: list[str]) -> list[dict[str, str]]:
    """Build Select options list from column names."""
    return [{"value": c, "label": COLUMN_LABELS.get(c, c)} for c in cols]


# ── Condition panel defaults per index ────────────────────────────────────────
_COND_DEFAULTS: dict[int, dict] = {
    1: {
        "col": "log2fc",
        "op": ">",
        "abs": True,
        "enabled": True,
        # Slider range for |log2fc|: 0 → ~5
        "slider_min": 0,
        "slider_max": 5.0,
        "slider_val": 1.5,
    },
    2: {
        "col": "neg_log10_pvalue",
        "op": ">",
        "abs": False,
        "enabled": True,
        # Slider range for neg_log10_pvalue: 0 → ~50
        "slider_min": 0,
        "slider_max": 50.0,
        "slider_val": 1.3,
    },
}

_OPERATORS: list[dict[str, str]] = [
    {"value": ">", "label": ">"},
    {"value": "<", "label": "<"},
    {"value": ">=", "label": ">="},
    {"value": "<=", "label": "<="},
]


def _slider_marks(vmin: float, vmax: float, n: int = 5) -> list[dict]:
    """Generate evenly-spaced slider marks."""
    step = (vmax - vmin) / (n - 1) if n > 1 else 0
    return [
        {"value": round(vmin + i * step, 2), "label": str(round(vmin + i * step, 2))}
        for i in range(n)
    ]


def _create_condition_panel(index: int) -> dmc.Paper:
    """Create a single condition builder panel.

    Args:
        index: Condition number (1 or 2).
    """
    d = _COND_DEFAULTS[index]
    disabled = not d["enabled"]

    return dmc.Paper(
        dmc.Stack(
            [
                dmc.Group(
                    [
                        dmc.Text(f"Condition {index}", fw=600, size="sm"),
                        dmc.Switch(
                            id=f"cond-{index}-enabled",
                            checked=d["enabled"],
                            size="sm",
                            color="blue",
                        ),
                    ],
                    justify="space-between",
                ),
                dmc.Select(
                    id=f"cond-{index}-col",
                    data=_col_options(NUMERIC_COLS),
                    value=d["col"],
                    label="Column",
                    size="xs",
                    disabled=disabled,
                ),
                dmc.Group(
                    [
                        dmc.Select(
                            id=f"cond-{index}-op",
                            data=_OPERATORS,
                            value=d["op"],
                            label="Operator",
                            size="xs",
                            w=80,
                            disabled=disabled,
                        ),
                        dmc.Checkbox(
                            id=f"cond-{index}-abs",
                            label="|abs|",
                            checked=d["abs"],
                            size="xs",
                            disabled=disabled,
                            mt=24,
                        ),
                    ],
                ),
                dmc.Text("Threshold", size="xs", c="dimmed"),
                dmc.Slider(
                    id=f"cond-{index}-slider",
                    min=d["slider_min"],
                    max=d["slider_max"],
                    step=0.01,
                    value=d["slider_val"],
                    marks=_slider_marks(d["slider_min"], d["slider_max"]),
                    precision=2,
                    size="sm",
                    disabled=disabled,
                    color="blue",
                ),
                dmc.Text(
                    id=f"cond-{index}-value-display",
                    size="xs",
                    c="dimmed",
                    ta="center",
                ),
            ],
            gap="xs",
        ),
        p="sm",
        radius="sm",
        withBorder=True,
    )


# ── Sidebar ───────────────────────────────────────────────────────────────────


def _create_navbar_content() -> dmc.ScrollArea:
    """Build the full sidebar control panel."""
    return dmc.ScrollArea(
        dmc.Stack(
            [
                dmc.Title("Conditional Highlighting", order=4),
                dmc.Text("Prototype v0.1", size="xs", c="dimmed"),
                # ── Axis config ──────────────────────────
                dmc.Divider(label="Axis Configuration", labelPosition="center"),
                dmc.Select(
                    id="x-col",
                    data=_col_options(NUMERIC_COLS),
                    value="log2fc",
                    label="X Axis",
                    size="xs",
                    leftSection=DashIconify(icon="mdi:axis-x-arrow", width=14),
                ),
                dmc.Select(
                    id="y-col",
                    data=_col_options(NUMERIC_COLS),
                    value="neg_log10_pvalue",
                    label="Y Axis",
                    size="xs",
                    leftSection=DashIconify(icon="mdi:axis-y-arrow", width=14),
                ),
                dmc.Select(
                    id="color-col",
                    data=_col_options(CATEGORICAL_COLS),
                    value="significance",
                    label="Color",
                    size="xs",
                    clearable=True,
                    placeholder="None",
                    leftSection=DashIconify(icon="mdi:palette", width=14),
                ),
                dmc.Group(
                    [
                        dmc.Stack(
                            [
                                dmc.Text("X Scale", size="xs"),
                                dmc.SegmentedControl(
                                    id="x-scale",
                                    data=["linear", "log"],
                                    value="linear",
                                    size="xs",
                                ),
                            ],
                            gap=2,
                        ),
                        dmc.Stack(
                            [
                                dmc.Text("Y Scale", size="xs"),
                                dmc.SegmentedControl(
                                    id="y-scale",
                                    data=["linear", "log"],
                                    value="linear",
                                    size="xs",
                                ),
                            ],
                            gap=2,
                        ),
                    ],
                ),
                # ── Conditions ───────────────────────────
                dmc.Divider(label="Conditions (AND)", labelPosition="center"),
                _create_condition_panel(1),
                _create_condition_panel(2),
            ],
            gap="sm",
            p="md",
        ),
        type="auto",
    )


# ── AG Grid ───────────────────────────────────────────────────────────────────


def _create_ag_grid() -> dag.AgGrid:
    """Create the data table with row highlighting support."""
    return dag.AgGrid(
        id="data-table",
        columnDefs=[],
        rowData=[],
        dashGridOptions={
            "pagination": True,
            "paginationPageSize": 50,
            "paginationPageSizeSelector": [25, 50, 100, 200],
            "rowSelection": "multiple",
            "enableCellTextSelection": True,
            "animateRows": False,
            "rowClassRules": {
                "row-highlighted": "params.data && params.data._highlighted === true",
                "row-dimmed": "params.data && params.data._highlighted === false",
            },
        },
        defaultColDef={
            "flex": 1,
            "minWidth": 100,
            "sortable": True,
            "resizable": True,
            "filter": True,
        },
        style={"height": "400px"},
        className="ag-theme-alpine",
    )


# ── Main layout ───────────────────────────────────────────────────────────────


def create_layout() -> dmc.MantineProvider:
    """Create the full application layout wrapped in MantineProvider.

    Returns:
        The top-level Dash component tree.
    """
    return dmc.MantineProvider(
        dmc.AppShell(
            [
                dmc.AppShellNavbar(_create_navbar_content()),
                dmc.AppShellMain(
                    dmc.Container(
                        dmc.Stack(
                            [
                                # Summary card
                                dmc.Paper(
                                    dmc.Group(
                                        id="summary-content",
                                        children=[
                                            dmc.Text(
                                                "Loading...",
                                                size="sm",
                                                c="dimmed",
                                            ),
                                        ],
                                        gap="xs",
                                        wrap="wrap",
                                    ),
                                    p="sm",
                                    radius="sm",
                                    withBorder=True,
                                ),
                                # Scatter plot
                                dmc.Paper(
                                    dcc.Graph(
                                        id="main-scatter",
                                        config={
                                            "displayModeBar": "hover",
                                            "responsive": True,
                                        },
                                        style={"height": "520px"},
                                    ),
                                    p="xs",
                                    radius="sm",
                                    withBorder=True,
                                ),
                                # Data table
                                dmc.Paper(
                                    _create_ag_grid(),
                                    p="xs",
                                    radius="sm",
                                    withBorder=True,
                                ),
                            ],
                            gap="md",
                            p="md",
                        ),
                        fluid=True,
                    ),
                ),
            ],
            navbar={"width": 320, "breakpoint": "sm"},
            padding="md",
        ),
        forceColorScheme="light",
    )
