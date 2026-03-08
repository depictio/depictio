"""Layout for the Taxonomy Browser prototype.

DMC 2.0 AppShell with sidebar for rank selection and condition filter,
main area with stacked bar chart, alpha diversity, and abundance table.
"""

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify
from data import RANK_ORDER


def _create_navbar_content() -> dmc.ScrollArea:
    """Build sidebar with taxonomy controls."""
    return dmc.ScrollArea(
        dmc.Stack(
            [
                dmc.Title("Taxonomy Browser", order=4),
                dmc.Text("16S / Metagenomics", size="xs", c="dimmed"),
                dmc.Divider(label="Taxonomic Rank", labelPosition="center"),
                dmc.SegmentedControl(
                    id="rank-selector",
                    data=[{"value": r, "label": r.capitalize()} for r in RANK_ORDER],
                    value="phylum",
                    orientation="vertical",
                    fullWidth=True,
                    size="sm",
                ),
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
                dmc.Switch(
                    id="relative-toggle",
                    label="Relative abundance",
                    checked=True,
                    size="sm",
                ),
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
                dmc.Divider(label="Summary", labelPosition="center"),
                dmc.Stack(id="taxonomy-summary", gap="xs"),
            ],
            gap="sm",
            p="md",
        ),
        type="auto",
    )


def _create_abundance_table() -> dag.AgGrid:
    """Create the abundance data table."""
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
            "minWidth": 80,
            "sortable": True,
            "resizable": True,
            "filter": True,
        },
        style={"height": "350px"},
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
                                # Row 1: Stacked bar chart (full width)
                                dmc.Paper(
                                    dcc.Graph(
                                        id="stacked-bar-chart",
                                        config={"displayModeBar": "hover", "responsive": True},
                                        style={"height": "420px"},
                                    ),
                                    p="xs",
                                    radius="sm",
                                    withBorder=True,
                                ),
                                # Row 2: Alpha diversity + sunburst
                                dmc.Grid(
                                    [
                                        dmc.GridCol(
                                            dmc.Paper(
                                                dcc.Graph(
                                                    id="alpha-diversity-chart",
                                                    config={"displayModeBar": "hover", "responsive": True},
                                                    style={"height": "380px"},
                                                ),
                                                p="xs",
                                                radius="sm",
                                                withBorder=True,
                                            ),
                                            span=6,
                                        ),
                                        dmc.GridCol(
                                            dmc.Paper(
                                                dcc.Graph(
                                                    id="sunburst-chart",
                                                    config={"displayModeBar": "hover", "responsive": True},
                                                    style={"height": "380px"},
                                                ),
                                                p="xs",
                                                radius="sm",
                                                withBorder=True,
                                            ),
                                            span=6,
                                        ),
                                    ],
                                    gutter="md",
                                ),
                                # Row 3: Abundance table
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
