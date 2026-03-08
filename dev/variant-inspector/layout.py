"""Layout for the Variant Inspector analysis module.

DMC 2.0 AppShell with sidebar controls (sample, thresholds, filters, summary badges)
and main area with quadrant scatter, filter funnel, cross-sample heatmap, and AG Grid.
"""

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc
from data import GENE_REGIONS, SAMPLES


def _create_navbar_content() -> dmc.ScrollArea:
    """Build sidebar with variant filtering controls and summary badges."""
    return dmc.ScrollArea(
        dmc.Stack(
            [
                dmc.Title("Variant Inspector", order=4),
                dmc.Text("Quadrant Analysis Module", size="xs", c="dimmed"),
                # -- Sample selector -------------------------------------------
                dmc.Divider(label="Sample", labelPosition="center"),
                dmc.Select(
                    id="sample-selector",
                    label="Active sample",
                    data=[{"value": s, "label": s} for s in SAMPLES],
                    value=SAMPLES[0],
                    size="sm",
                ),
                # -- Threshold sliders -----------------------------------------
                dmc.Divider(label="Thresholds", labelPosition="center"),
                dmc.Text("AF Threshold", size="xs", fw=500),
                dmc.Slider(
                    id="af-threshold-slider",
                    min=0,
                    max=1,
                    step=0.01,
                    value=0.5,
                    marks=[
                        {"value": 0, "label": "0"},
                        {"value": 0.25, "label": "0.25"},
                        {"value": 0.5, "label": "0.5"},
                        {"value": 0.75, "label": "0.75"},
                        {"value": 1, "label": "1"},
                    ],
                    size="sm",
                    mb="md",
                ),
                dmc.Text("Quality Threshold", size="xs", fw=500),
                dmc.Slider(
                    id="qual-threshold-slider",
                    min=0,
                    max=250,
                    step=5,
                    value=100,
                    marks=[
                        {"value": 0, "label": "0"},
                        {"value": 50, "label": "50"},
                        {"value": 100, "label": "100"},
                        {"value": 150, "label": "150"},
                        {"value": 200, "label": "200"},
                        {"value": 250, "label": "250"},
                    ],
                    size="sm",
                    mb="md",
                ),
                dmc.NumberInput(
                    id="depth-threshold-input",
                    label="Min total depth",
                    value=10,
                    min=0,
                    max=5000,
                    step=10,
                    size="sm",
                ),
                # -- Categorical filters ---------------------------------------
                dmc.Divider(label="Filters", labelPosition="center"),
                dmc.MultiSelect(
                    id="effect-filter",
                    label="Variant effects",
                    data=[
                        {"value": "missense", "label": "Missense"},
                        {"value": "synonymous", "label": "Synonymous"},
                        {"value": "nonsense", "label": "Nonsense"},
                        {"value": "frameshift", "label": "Frameshift"},
                        {"value": "upstream", "label": "Upstream"},
                    ],
                    value=["missense", "synonymous", "nonsense", "frameshift", "upstream"],
                    size="sm",
                ),
                dmc.Select(
                    id="gene-filter",
                    label="Gene region",
                    data=[{"value": "all", "label": "All genes"}]
                    + [{"value": str(r["gene"]), "label": str(r["gene"])} for r in GENE_REGIONS],
                    value="all",
                    size="sm",
                ),
                # -- Summary badges --------------------------------------------
                dmc.Divider(label="Summary", labelPosition="center"),
                dmc.Stack(id="sidebar-summary", gap="xs"),
            ],
            gap="sm",
            p="md",
        ),
        type="auto",
    )


def _create_variant_table() -> dag.AgGrid:
    """Create the variant data table."""
    return dag.AgGrid(
        id="variant-table",
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
            "minWidth": 80,
            "sortable": True,
            "resizable": True,
            "filter": True,
        },
        style={"height": "400px"},
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
                                dmc.Group(id="summary-badges", gap="sm"),
                                # Row 1: Quadrant scatter (centerpiece) + Filter funnel
                                dmc.Grid(
                                    [
                                        dmc.GridCol(
                                            dmc.Paper(
                                                dmc.Stack(
                                                    [
                                                        dmc.Group(
                                                            id="quadrant-badges",
                                                            gap="xs",
                                                            justify="center",
                                                        ),
                                                        dcc.Graph(
                                                            id="quadrant-scatter",
                                                            config={
                                                                "displayModeBar": "hover",
                                                                "responsive": True,
                                                            },
                                                            style={"height": "420px"},
                                                        ),
                                                    ],
                                                    gap="xs",
                                                ),
                                                p="xs",
                                                radius="sm",
                                                withBorder=True,
                                            ),
                                            span=8,
                                        ),
                                        dmc.GridCol(
                                            dmc.Paper(
                                                dcc.Graph(
                                                    id="filter-funnel",
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
                                            span=4,
                                        ),
                                    ],
                                    gutter="md",
                                ),
                                # Row 2: Cross-sample sharing heatmap
                                dmc.Paper(
                                    dcc.Graph(
                                        id="sharing-heatmap",
                                        config={
                                            "displayModeBar": "hover",
                                            "responsive": True,
                                        },
                                        style={"height": "350px"},
                                    ),
                                    p="xs",
                                    radius="sm",
                                    withBorder=True,
                                ),
                                # Row 3: Variant table
                                dmc.Paper(
                                    _create_variant_table(),
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
