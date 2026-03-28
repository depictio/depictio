"""Layout for the Progressive Filter module.

DMC 2.0 Paper with sidebar for filter chain and main area for
summary badges, volcano plot, funnel chart, and gene table.

All component IDs are prefixed with ``pf-`` to avoid conflicts
when composed with other modules.
"""

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

# ── Column metadata (matches shared_data DE result columns) ──────────────

NUMERIC_COLS: list[str] = ["log2fc", "pvalue", "padj", "neg_log10_pvalue", "mean_expression"]
CATEGORICAL_COLS: list[str] = ["cluster", "significance"]

COLUMN_LABELS: dict[str, str] = {
    "log2fc": "log2(FC)",
    "pvalue": "p-value",
    "padj": "Adjusted p-value",
    "neg_log10_pvalue": "-log10(p-value)",
    "mean_expression": "Mean Expression",
    "cluster": "Cluster",
    "significance": "Significance",
    "gene_name": "Gene",
}

ALL_COLS = NUMERIC_COLS + CATEGORICAL_COLS

OPERATORS: list[dict[str, str]] = [
    {"value": ">", "label": ">"},
    {"value": "<", "label": "<"},
    {"value": ">=", "label": ">="},
    {"value": "<=", "label": "<="},
]

# Default filter definitions loaded at startup
DEFAULT_FILTERS = [
    {
        "id": 0,
        "column": "log2fc",
        "col_type": "numeric",
        "operator": ">",
        "threshold": 1.5,
        "use_abs": True,
        "cat_values": [],
        "enabled": True,
    },
    {
        "id": 1,
        "column": "padj",
        "col_type": "numeric",
        "operator": "<",
        "threshold": 0.05,
        "use_abs": False,
        "cat_values": [],
        "enabled": True,
    },
    {
        "id": 2,
        "column": "mean_expression",
        "col_type": "numeric",
        "operator": ">",
        "threshold": 5.0,
        "use_abs": False,
        "cat_values": [],
        "enabled": False,
    },
]


def _col_options() -> list[dict[str, str]]:
    """Build Select options for all columns."""
    return [{"value": c, "label": COLUMN_LABELS.get(c, c)} for c in ALL_COLS]


def _create_filter_card(f: dict) -> dmc.Paper:
    """Create a single filter card from a filter definition dict.

    All IDs use pattern-matching dicts with ``"module": "pf"`` key.
    """
    fid = f["id"]
    is_numeric = f["col_type"] == "numeric"

    return dmc.Paper(
        dmc.Stack(
            [
                dmc.Group(
                    [
                        dmc.Text(f"Filter {fid + 1}", fw=600, size="sm"),
                        dmc.Group(
                            [
                                dmc.Badge(
                                    "—",
                                    id={"type": "pf-filter-count-badge", "index": fid},
                                    color="blue",
                                    variant="light",
                                    size="sm",
                                ),
                                dmc.Switch(
                                    id={"type": "pf-filter-enabled", "index": fid},
                                    checked=f["enabled"],
                                    size="sm",
                                    color="blue",
                                ),
                            ],
                            gap="xs",
                        ),
                    ],
                    justify="space-between",
                ),
                dmc.Select(
                    id={"type": "pf-filter-column", "index": fid},
                    data=_col_options(),
                    value=f["column"],
                    label="Column",
                    size="xs",
                ),
                # Numeric controls
                html.Div(
                    dmc.Group(
                        [
                            dmc.Select(
                                id={"type": "pf-filter-operator", "index": fid},
                                data=OPERATORS,
                                value=f["operator"],
                                label="Operator",
                                size="xs",
                                w=80,
                            ),
                            dmc.Checkbox(
                                id={"type": "pf-filter-abs", "index": fid},
                                label="|abs|",
                                checked=f.get("use_abs", False),
                                size="xs",
                                mt=24,
                            ),
                        ],
                    ),
                    id={"type": "pf-numeric-controls", "index": fid},
                    style={"display": "block" if is_numeric else "none"},
                ),
                html.Div(
                    [
                        dmc.Text("Threshold", size="xs", c="dimmed"),
                        dmc.NumberInput(
                            id={"type": "pf-filter-threshold", "index": fid},
                            value=f["threshold"],
                            size="xs",
                            step=0.01,
                            decimalScale=4,
                        ),
                    ],
                    id={"type": "pf-threshold-container", "index": fid},
                    style={"display": "block" if is_numeric else "none"},
                ),
                # Categorical controls
                html.Div(
                    dmc.MultiSelect(
                        id={"type": "pf-filter-cat-values", "index": fid},
                        data=[],
                        value=f.get("cat_values", []),
                        label="Allowed values",
                        size="xs",
                        placeholder="Select values...",
                    ),
                    id={"type": "pf-cat-controls", "index": fid},
                    style={"display": "block" if not is_numeric else "none"},
                ),
            ],
            gap="xs",
        ),
        p="sm",
        radius="sm",
        withBorder=True,
        id={"type": "pf-filter-card", "index": fid},
    )


def _create_sidebar() -> dmc.ScrollArea:
    """Build sidebar with filter chain controls."""
    default_cards = [_create_filter_card(f) for f in DEFAULT_FILTERS]

    return dmc.ScrollArea(
        dmc.Stack(
            [
                dmc.Title("Progressive Filter", order=4),
                dmc.Text("Module v1.0", size="xs", c="dimmed"),
                dmc.Divider(label="Filter Chain", labelPosition="center"),
                dmc.Button(
                    "Add Filter",
                    id="pf-add-filter-btn",
                    leftSection=DashIconify(icon="mdi:plus", width=16),
                    variant="light",
                    size="sm",
                    fullWidth=True,
                ),
                html.Div(
                    default_cards,
                    id="pf-filter-cards-container",
                ),
            ],
            gap="sm",
            p="md",
        ),
        type="auto",
    )


def _create_ag_grid() -> dag.AgGrid:
    """Create the filtered gene data table."""
    return dag.AgGrid(
        id="pf-gene-table",
        columnDefs=[],
        rowData=[],
        dashGridOptions={
            "pagination": True,
            "paginationPageSize": 50,
            "paginationPageSizeSelector": [25, 50, 100, 200],
            "rowSelection": "multiple",
            "enableCellTextSelection": True,
            "animateRows": False,
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


def create_layout(data: dict) -> dmc.Paper:
    """Create the Progressive Filter module layout.

    Args:
        data: The data dict from ``shared_data.load_all_data()``.

    Returns:
        A ``dmc.Paper`` wrapping the complete module UI.
    """
    return dmc.Paper(
        dmc.Stack(
            [
                # Hidden stores (module-internal)
                dcc.Store(id="pf-filter-store", data=DEFAULT_FILTERS),
                dcc.Store(id="pf-next-filter-id", data=3),
                # Module layout: sidebar + main area
                dmc.Grid(
                    [
                        # Sidebar column
                        dmc.GridCol(
                            _create_sidebar(),
                            span=3,
                        ),
                        # Main content column
                        dmc.GridCol(
                            dmc.Stack(
                                [
                                    # Summary badges row
                                    dmc.Paper(
                                        dmc.Group(
                                            id="pf-summary-badges",
                                            children=[
                                                dmc.Text(
                                                    "Loading...",
                                                    size="sm",
                                                    c="dimmed",
                                                ),
                                            ],
                                            gap="sm",
                                            wrap="wrap",
                                        ),
                                        p="sm",
                                        radius="sm",
                                        withBorder=True,
                                    ),
                                    # Charts row: volcano + funnel
                                    dmc.Grid(
                                        [
                                            dmc.GridCol(
                                                dmc.Paper(
                                                    dcc.Graph(
                                                        id="pf-volcano-plot",
                                                        config={
                                                            "displayModeBar": "hover",
                                                            "responsive": True,
                                                        },
                                                        style={"height": "480px"},
                                                    ),
                                                    p="xs",
                                                    radius="sm",
                                                    withBorder=True,
                                                ),
                                                span=7,
                                            ),
                                            dmc.GridCol(
                                                dmc.Paper(
                                                    dcc.Graph(
                                                        id="pf-funnel-chart",
                                                        config={
                                                            "displayModeBar": False,
                                                            "responsive": True,
                                                        },
                                                        style={"height": "480px"},
                                                    ),
                                                    p="xs",
                                                    radius="sm",
                                                    withBorder=True,
                                                ),
                                                span=5,
                                            ),
                                        ],
                                        gutter="md",
                                    ),
                                    # Gene table
                                    dmc.Paper(
                                        _create_ag_grid(),
                                        p="xs",
                                        radius="sm",
                                        withBorder=True,
                                    ),
                                ],
                                gap="md",
                            ),
                            span=9,
                        ),
                    ],
                    gutter="md",
                ),
            ],
            gap="md",
        ),
        p="md",
        radius="sm",
        withBorder=True,
    )
