"""Layout for the Taxonomy Browser analysis module.

DMC 2.0 AppShell with sidebar for rank selection, abundance threshold,
top-N selector, and condition filter. Main area with summary badges,
differential abundance scatter, stacked bar chart, alpha diversity,
and AG Grid table.
"""

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc
from data import RANK_ORDER


def _create_navbar_content() -> dmc.ScrollArea:
    """Build sidebar with taxonomy controls and summary badges."""
    return dmc.ScrollArea(
        dmc.Stack(
            [
                dmc.Title("Taxonomy Browser", order=4),
                dmc.Text("16S / Metagenomics Analysis", size="xs", c="dimmed"),
                # --- Rank selector ---
                dmc.Divider(label="Taxonomic Rank", labelPosition="center"),
                dmc.SegmentedControl(
                    id="rank-selector",
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
                    id="abundance-threshold-slider",
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
                    id="top-n-input",
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
                    id="condition-filter",
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
                dmc.Stack(id="sidebar-summary", gap="xs"),
            ],
            gap="sm",
            p="md",
        ),
        type="auto",
    )


def _create_abundance_table() -> dag.AgGrid:
    """Create the differential abundance data table."""
    return dag.AgGrid(
        id="abundance-table",
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


def create_layout() -> dmc.MantineProvider:
    """Create the full application layout."""
    return dmc.MantineProvider(
        dmc.AppShell(
            [
                dmc.AppShellNavbar(_create_navbar_content()),
                dmc.AppShellMain(
                    dmc.Container(
                        dmc.Stack(
                            [
                                # Row 0: Summary badges
                                dmc.Group(
                                    id="summary-badges",
                                    gap="sm",
                                ),
                                # Row 1: Differential abundance scatter
                                dmc.Paper(
                                    dcc.Graph(
                                        id="differential-scatter",
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
                                        id="stacked-bar-chart",
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
                                        id="alpha-diversity-chart",
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
                        fluid=True,
                    ),
                ),
            ],
            navbar={"width": 300, "breakpoint": "sm"},
            padding="md",
        ),
        forceColorScheme="light",
    )
