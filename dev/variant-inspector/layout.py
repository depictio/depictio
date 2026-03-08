"""Layout for the Variant Inspector prototype.

DMC 2.0 AppShell with sidebar for sample selection and AF filtering,
main area with variant table, AF histogram, coverage track, and lineage bar.
"""

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify
from data import SAMPLES, GENE_REGIONS


def _create_navbar_content() -> dmc.ScrollArea:
    """Build sidebar with variant filtering controls."""
    return dmc.ScrollArea(
        dmc.Stack(
            [
                dmc.Title("Variant Inspector", order=4),
                dmc.Text("Viralrecon / Sarek", size="xs", c="dimmed"),
                dmc.Divider(label="Sample", labelPosition="center"),
                dmc.Select(
                    id="sample-selector",
                    label="Active sample",
                    data=[{"value": s, "label": s} for s in SAMPLES],
                    value=SAMPLES[0],
                    size="sm",
                ),
                dmc.Divider(label="Filters", labelPosition="center"),
                dmc.Text("Allele Frequency", size="xs", fw=500),
                dmc.RangeSlider(
                    id="af-range-slider",
                    min=0,
                    max=1,
                    step=0.01,
                    value=[0.05, 1.0],
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
                dmc.NumberInput(
                    id="min-depth-input",
                    label="Min total depth",
                    value=10,
                    min=0,
                    max=5000,
                    step=10,
                    size="sm",
                ),
                dmc.NumberInput(
                    id="min-qual-input",
                    label="Min variant quality",
                    value=20,
                    min=0,
                    max=300,
                    step=5,
                    size="sm",
                ),
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
                dmc.Divider(label="Summary", labelPosition="center"),
                dmc.Stack(id="variant-summary", gap="xs"),
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
                                # Row 1: AF histogram + coverage track
                                dmc.Grid(
                                    [
                                        dmc.GridCol(
                                            dmc.Paper(
                                                dcc.Graph(
                                                    id="af-histogram",
                                                    config={"displayModeBar": "hover", "responsive": True},
                                                    style={"height": "350px"},
                                                ),
                                                p="xs",
                                                radius="sm",
                                                withBorder=True,
                                            ),
                                            span=5,
                                        ),
                                        dmc.GridCol(
                                            dmc.Paper(
                                                dcc.Graph(
                                                    id="coverage-track",
                                                    config={"displayModeBar": "hover", "responsive": True},
                                                    style={"height": "350px"},
                                                ),
                                                p="xs",
                                                radius="sm",
                                                withBorder=True,
                                            ),
                                            span=7,
                                        ),
                                    ],
                                    gutter="md",
                                ),
                                # Row 2: Lineage composition (full width)
                                dmc.Paper(
                                    dcc.Graph(
                                        id="lineage-chart",
                                        config={"displayModeBar": "hover", "responsive": True},
                                        style={"height": "300px"},
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
