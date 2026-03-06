"""Layout for the GSEA explorer prototype.

DMC 2.0 AppShell with sidebar controls (contrast selector, source filter,
top-N slider) and main area with enrichment table, running ES plot,
dot plot, and leading edge heatmap.
"""

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc
from dash_iconify import DashIconify
from data import CONTRASTS


def _create_navbar_content() -> dmc.ScrollArea:
    """Build sidebar with all controls."""
    return dmc.ScrollArea(
        dmc.Stack(
            [
                dmc.Title("GSEA Explorer", order=4),
                dmc.Text("Prototype v0.1", size="xs", c="dimmed"),
                # ── Contrast selector ─────────────────────
                dmc.Divider(label="Contrast", labelPosition="center"),
                dmc.Select(
                    id="contrast-select",
                    data=[{"value": c, "label": c.replace("_", " ")} for c in CONTRASTS],
                    value=CONTRASTS[0],
                    label="DE Contrast",
                    size="xs",
                    leftSection=DashIconify(icon="mdi:compare-arrows", width=14),
                ),
                # ── Pathway source filter ─────────────────
                dmc.Divider(label="Pathway Source", labelPosition="center"),
                dmc.CheckboxGroup(
                    id="source-filter",
                    label="Filter by source",
                    value=["GO_BP", "KEGG", "Reactome"],
                    children=dmc.Stack(
                        [
                            dmc.Checkbox(label="GO Biological Process", value="GO_BP"),
                            dmc.Checkbox(label="KEGG", value="KEGG"),
                            dmc.Checkbox(label="Reactome", value="Reactome"),
                        ],
                        gap="xs",
                    ),
                ),
                # ── Top N slider ──────────────────────────
                dmc.Divider(label="Dot Plot", labelPosition="center"),
                dmc.Text("Top N pathways", size="xs", c="dimmed"),
                dmc.Slider(
                    id="top-n-slider",
                    min=5,
                    max=30,
                    value=15,
                    step=1,
                    marks=[
                        {"value": 5, "label": "5"},
                        {"value": 15, "label": "15"},
                        {"value": 30, "label": "30"},
                    ],
                    size="sm",
                ),
            ],
            gap="sm",
            p="md",
        ),
        type="auto",
    )


def _create_enrichment_grid() -> dag.AgGrid:
    """Enrichment results AG Grid table."""
    return dag.AgGrid(
        id="enrichment-table",
        columnDefs=[
            {"field": "pathway_name", "headerName": "Pathway", "minWidth": 250, "flex": 2},
            {
                "field": "NES",
                "headerName": "NES",
                "type": "numericColumn",
                "valueFormatter": {"function": "d3.format('.3f')(params.value)"},
                "flex": 1,
            },
            {
                "field": "padj",
                "headerName": "p-adj",
                "type": "numericColumn",
                "valueFormatter": {"function": "d3.format('.2e')(params.value)"},
                "flex": 1,
            },
            {"field": "leading_edge_size", "headerName": "LE Size", "type": "numericColumn", "flex": 1},
            {"field": "gene_set_size", "headerName": "Set Size", "type": "numericColumn", "flex": 1},
            {"field": "source", "headerName": "Source", "flex": 1},
        ],
        rowData=[],
        dashGridOptions={
            "pagination": True,
            "paginationPageSize": 10,
            "rowSelection": {"mode": "singleRow"},
            "enableCellTextSelection": True,
            "animateRows": False,
        },
        defaultColDef={
            "sortable": True,
            "resizable": True,
            "filter": True,
        },
        style={"height": "300px"},
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
                                # Enrichment table
                                dmc.Paper(
                                    _create_enrichment_grid(),
                                    p="xs",
                                    radius="sm",
                                    withBorder=True,
                                ),
                                # Running ES plot
                                dmc.Paper(
                                    dcc.Graph(
                                        id="running-es-plot",
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
                                # Bottom row: dot plot + leading edge heatmap
                                dmc.Grid(
                                    [
                                        dmc.GridCol(
                                            dmc.Paper(
                                                dcc.Graph(
                                                    id="dot-plot",
                                                    config={
                                                        "displayModeBar": "hover",
                                                        "responsive": True,
                                                    },
                                                    style={"height": "500px"},
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
                                                    id="le-heatmap",
                                                    config={
                                                        "displayModeBar": "hover",
                                                        "responsive": True,
                                                    },
                                                    style={"height": "500px"},
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
