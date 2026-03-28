"""Layout for the Peak Explorer module.

DMC 2.0 Paper wrapper with progressive-filter sidebar (pattern-matching IDs)
and main area with summary badges, scatter plot, funnel chart, enrichment
curve, annotation pie, and AG Grid table.

All component IDs are prefixed with ``pe-`` to avoid conflicts with other modules.
"""

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

ANNOTATION_CATEGORIES: list[str] = [
    "Promoter",
    "5' UTR",
    "3' UTR",
    "Exon",
    "Intron",
    "Intergenic",
    "TTS",
]

NUMERIC_COLS: list[str] = [
    "score",
    "neg_log10_pvalue",
    "fold_enrichment",
    "width",
    "distance_to_tss",
]
CATEGORICAL_COLS: list[str] = ["annotation", "chr"]

COLUMN_LABELS: dict[str, str] = {
    "score": "Peak Score",
    "neg_log10_pvalue": "-log10(p-value)",
    "fold_enrichment": "Fold Enrichment",
    "width": "Peak Width (bp)",
    "distance_to_tss": "Distance to TSS",
    "annotation": "Annotation",
    "chr": "Chromosome",
    "peak_id": "Peak ID",
    "nearest_gene": "Nearest Gene",
}

ALL_COLS = NUMERIC_COLS + CATEGORICAL_COLS

OPERATORS: list[dict[str, str]] = [
    {"value": ">", "label": ">"},
    {"value": "<", "label": "<"},
    {"value": ">=", "label": ">="},
    {"value": "<=", "label": "<="},
]

# Default filter chain for peak analysis
DEFAULT_FILTERS = [
    {
        "id": 0,
        "column": "score",
        "col_type": "numeric",
        "operator": ">=",
        "threshold": 100,
        "use_abs": False,
        "cat_values": [],
        "enabled": True,
    },
    {
        "id": 1,
        "column": "fold_enrichment",
        "col_type": "numeric",
        "operator": ">=",
        "threshold": 3.0,
        "use_abs": False,
        "cat_values": [],
        "enabled": True,
    },
    {
        "id": 2,
        "column": "neg_log10_pvalue",
        "col_type": "numeric",
        "operator": ">=",
        "threshold": 5.0,
        "use_abs": False,
        "cat_values": [],
        "enabled": True,
    },
    {
        "id": 3,
        "column": "annotation",
        "col_type": "categorical",
        "operator": ">",
        "threshold": 0,
        "use_abs": False,
        "cat_values": list(ANNOTATION_CATEGORIES),
        "enabled": True,
    },
]


def _col_options() -> list[dict[str, str]]:
    """Build Select options for all columns."""
    return [{"value": c, "label": COLUMN_LABELS.get(c, c)} for c in ALL_COLS]


def _create_filter_card(f: dict) -> dmc.Paper:
    """Create a single filter card from a filter definition dict."""
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
                                    "---",
                                    id={"type": "pe-filter-count-badge", "index": fid},
                                    color="blue",
                                    variant="light",
                                    size="sm",
                                ),
                                dmc.Switch(
                                    id={"type": "pe-filter-enabled", "index": fid},
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
                    id={"type": "pe-filter-column", "index": fid},
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
                                id={"type": "pe-filter-operator", "index": fid},
                                data=OPERATORS,
                                value=f["operator"],
                                label="Operator",
                                size="xs",
                                w=80,
                            ),
                            dmc.Checkbox(
                                id={"type": "pe-filter-abs", "index": fid},
                                label="|abs|",
                                checked=f.get("use_abs", False),
                                size="xs",
                                mt=24,
                            ),
                        ],
                    ),
                    id={"type": "pe-numeric-controls", "index": fid},
                    style={"display": "block" if is_numeric else "none"},
                ),
                html.Div(
                    [
                        dmc.Text("Threshold", size="xs", c="dimmed"),
                        dmc.NumberInput(
                            id={"type": "pe-filter-threshold", "index": fid},
                            value=f["threshold"],
                            size="xs",
                            step=0.5,
                            decimalScale=4,
                        ),
                    ],
                    id={"type": "pe-threshold-container", "index": fid},
                    style={"display": "block" if is_numeric else "none"},
                ),
                # Categorical controls
                html.Div(
                    dmc.MultiSelect(
                        id={"type": "pe-filter-cat-values", "index": fid},
                        data=[],
                        value=f.get("cat_values", []),
                        label="Allowed values",
                        size="xs",
                        placeholder="Select values...",
                    ),
                    id={"type": "pe-cat-controls", "index": fid},
                    style={"display": "block" if not is_numeric else "none"},
                ),
            ],
            gap="xs",
        ),
        p="sm",
        radius="sm",
        withBorder=True,
        id={"type": "pe-filter-card", "index": fid},
    )


def _create_sidebar_content() -> dmc.ScrollArea:
    """Build sidebar with filter chain controls."""
    default_cards = [_create_filter_card(f) for f in DEFAULT_FILTERS]

    return dmc.ScrollArea(
        dmc.Stack(
            [
                dmc.Title("Peak Explorer", order=4),
                dmc.Text("Threshold-driven analysis", size="xs", c="dimmed"),
                dmc.Divider(label="Filter Chain", labelPosition="center"),
                dmc.Button(
                    "Add Filter",
                    id="pe-add-filter-btn",
                    leftSection=DashIconify(icon="mdi:plus", width=16),
                    variant="light",
                    size="sm",
                    fullWidth=True,
                ),
                html.Div(
                    default_cards,
                    id="pe-filter-cards-container",
                ),
            ],
            gap="sm",
            p="md",
        ),
        type="auto",
    )


def _create_peak_table() -> dag.AgGrid:
    """Create the filtered peak data table."""
    return dag.AgGrid(
        id="pe-peak-table",
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
            "minWidth": 90,
            "sortable": True,
            "resizable": True,
            "filter": True,
        },
        style={"height": "400px"},
        className="ag-theme-alpine",
    )


def create_layout(data: dict) -> dmc.Paper:
    """Create the Peak Explorer module layout.

    Args:
        data: The data dict from ``shared_data.load_all_data()``.

    Returns:
        A ``dmc.Paper`` wrapping the full module UI.
    """
    return dmc.Paper(
        dmc.Grid(
            [
                # Sidebar column
                dmc.GridCol(
                    _create_sidebar_content(),
                    span=3,
                ),
                # Main area column
                dmc.GridCol(
                    dmc.Stack(
                        [
                            # Hidden stores
                            dcc.Store(
                                id="pe-filter-store",
                                data=DEFAULT_FILTERS,
                            ),
                            dcc.Store(id="pe-next-filter-id", data=len(DEFAULT_FILTERS)),
                            # Summary badges row
                            dmc.Paper(
                                dmc.Group(
                                    id="pe-summary-badges",
                                    children=[
                                        dmc.Text("Loading...", size="sm", c="dimmed"),
                                    ],
                                    gap="sm",
                                    wrap="wrap",
                                ),
                                p="sm",
                                radius="sm",
                                withBorder=True,
                            ),
                            # Row 1: Scatter plot (span 7) + Funnel chart (span 5)
                            dmc.Grid(
                                [
                                    dmc.GridCol(
                                        dmc.Paper(
                                            dcc.Graph(
                                                id="pe-scatter-plot",
                                                config={
                                                    "displayModeBar": "hover",
                                                    "responsive": True,
                                                },
                                                style={"height": "460px"},
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
                                                id="pe-funnel-chart",
                                                config={
                                                    "displayModeBar": False,
                                                    "responsive": True,
                                                },
                                                style={"height": "460px"},
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
                            # Row 2: Enrichment curve (span 7) + Annotation pie (span 5)
                            dmc.Grid(
                                [
                                    dmc.GridCol(
                                        dmc.Paper(
                                            dcc.Graph(
                                                id="pe-enrichment-curve",
                                                config={
                                                    "displayModeBar": "hover",
                                                    "responsive": True,
                                                },
                                                style={"height": "400px"},
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
                                                id="pe-annotation-pie",
                                                config={
                                                    "displayModeBar": "hover",
                                                    "responsive": True,
                                                },
                                                style={"height": "400px"},
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
                            # Row 3: Peak table
                            dmc.Paper(
                                _create_peak_table(),
                                p="xs",
                                radius="sm",
                                withBorder=True,
                            ),
                        ],
                        gap="md",
                        p="md",
                    ),
                    span=9,
                ),
            ],
            gutter="md",
        ),
        p="md",
        radius="sm",
        withBorder=True,
    )
