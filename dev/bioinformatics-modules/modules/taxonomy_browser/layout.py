"""Layout for the Taxonomy Browser module.

DMC 2.0 Paper wrapper with sidebar for rank selection, abundance threshold,
top-N selector, and condition filter. Main area with summary badges,
differential abundance scatter, stacked bar chart, alpha diversity,
and AG Grid table.

All component IDs are prefixed with ``tb-`` to avoid conflicts with other modules.
"""

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc

RANK_ORDER: list[str] = ["kingdom", "phylum", "class", "order", "family", "genus", "species"]


def _create_sidebar_content() -> dmc.ScrollArea:
    """Build sidebar with taxonomy controls and summary badges."""
    return dmc.ScrollArea(
        dmc.Stack(
            [
                dmc.Title("Taxonomy Browser", order=4),
                dmc.Text("16S / Metagenomics Analysis", size="xs", c="dimmed"),
                # --- Rank selector ---
                dmc.Divider(label="Taxonomic Rank", labelPosition="center"),
                dmc.SegmentedControl(
                    id="tb-rank-selector",
                    data=[{"value": r, "label": r.capitalize()} for r in RANK_ORDER],
                    value="phylum",
                    orientation="vertical",
                    fullWidth=True,
                    size="sm",
                ),
                # --- Abundance threshold ---
                dmc.Divider(label="Abundance Filter", labelPosition="center"),
                dmc.Text("Min relative abundance (%)", size="xs", c="dimmed"),
                dmc.Slider(
                    id="tb-abundance-threshold-slider",
                    value=0.5,
                    min=0,
                    max=10,
                    step=0.1,
                    marks=[
                        {"value": 0, "label": "0%"},
                        {"value": 1, "label": "1%"},
                        {"value": 5, "label": "5%"},
                        {"value": 10, "label": "10%"},
                    ],
                    size="sm",
                ),
                # --- Top-N selector ---
                dmc.Divider(label="Display", labelPosition="center"),
                dmc.NumberInput(
                    id="tb-top-n-input",
                    label="Show top N taxa",
                    value=10,
                    min=3,
                    max=30,
                    step=1,
                    size="sm",
                ),
                # --- Condition filter ---
                dmc.Divider(label="Condition", labelPosition="center"),
                dmc.MultiSelect(
                    id="tb-condition-filter",
                    label="Filter conditions",
                    data=[
                        {"value": "Healthy", "label": "Healthy"},
                        {"value": "Disease", "label": "Disease"},
                    ],
                    value=["Healthy", "Disease"],
                    size="sm",
                ),
                # --- Sidebar summary badges ---
                dmc.Divider(label="Summary", labelPosition="center"),
                dmc.Stack(id="tb-sidebar-summary", gap="xs"),
            ],
            gap="sm",
            p="md",
        ),
        type="auto",
    )


def _create_abundance_table() -> dag.AgGrid:
    """Create the differential abundance data table."""
    return dag.AgGrid(
        id="tb-abundance-table",
        columnDefs=[],
        rowData=[],
        dashGridOptions={
            "pagination": True,
            "paginationPageSize": 25,
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
        style={"height": "380px"},
        className="ag-theme-alpine",
    )


def create_layout(data: dict) -> dmc.Paper:
    """Create the Taxonomy Browser module layout.

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
                            # Row 0: Summary badges
                            dmc.Group(
                                id="tb-summary-badges",
                                gap="sm",
                            ),
                            # Row 1: Differential abundance scatter
                            dmc.Paper(
                                dcc.Graph(
                                    id="tb-differential-scatter",
                                    config={
                                        "displayModeBar": "hover",
                                        "responsive": True,
                                    },
                                    style={"height": "440px"},
                                ),
                                p="xs",
                                radius="sm",
                                withBorder=True,
                            ),
                            # Row 2: Stacked bar chart
                            dmc.Paper(
                                dcc.Graph(
                                    id="tb-stacked-bar",
                                    config={
                                        "displayModeBar": "hover",
                                        "responsive": True,
                                    },
                                    style={"height": "420px"},
                                ),
                                p="xs",
                                radius="sm",
                                withBorder=True,
                            ),
                            # Row 3: Alpha diversity box plot
                            dmc.Paper(
                                dcc.Graph(
                                    id="tb-alpha-diversity-chart",
                                    config={
                                        "displayModeBar": "hover",
                                        "responsive": True,
                                    },
                                    style={"height": "380px"},
                                ),
                                p="xs",
                                radius="sm",
                                withBorder=True,
                            ),
                            # Row 4: Abundance table
                            dmc.Paper(
                                _create_abundance_table(),
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
