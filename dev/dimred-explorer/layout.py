"""Layout for the PCA / UMAP / t-SNE explorer prototype.

DMC 2.0 AppShell with sidebar controls and main area for the
dimensionality reduction scatter, variance explained bar chart, loadings,
and sample data table.
"""

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc
from dash_iconify import DashIconify
from data import COLUMN_LABELS, METADATA_COLS


def _meta_options() -> list[dict[str, str]]:
    """Metadata column options for Select dropdowns."""
    return [{"value": c, "label": COLUMN_LABELS.get(c, c)} for c in METADATA_COLS]


def _create_navbar_content() -> dmc.ScrollArea:
    """Build sidebar with all controls."""
    return dmc.ScrollArea(
        dmc.Stack(
            [
                dmc.Title("Dim. Reduction Explorer", order=4),
                dmc.Text("Prototype v0.1", size="xs", c="dimmed"),
                # ── Method ─────────────────────────────────
                dmc.Divider(label="Method", labelPosition="center"),
                dmc.SegmentedControl(
                    id="method-select",
                    data=[
                        {"value": "pca", "label": "PCA"},
                        {"value": "umap", "label": "UMAP"},
                        {"value": "tsne", "label": "t-SNE"},
                    ],
                    value="pca",
                    fullWidth=True,
                    size="sm",
                ),
                # ── Gene filtering ─────────────────────────
                dmc.Divider(label="Gene Selection", labelPosition="center"),
                dmc.NumberInput(
                    id="n-top-genes",
                    label="Top variable genes",
                    value=200,
                    min=10,
                    max=500,
                    step=10,
                    size="xs",
                    leftSection=DashIconify(icon="mdi:dna", width=14),
                ),
                # ── Appearance ─────────────────────────────
                dmc.Divider(label="Appearance", labelPosition="center"),
                dmc.Select(
                    id="color-by",
                    data=_meta_options(),
                    value="condition",
                    label="Color by",
                    size="xs",
                    leftSection=DashIconify(icon="mdi:palette", width=14),
                ),
                dmc.Select(
                    id="symbol-by",
                    data=[{"value": "", "label": "None"}] + _meta_options(),
                    value="batch",
                    label="Symbol by",
                    size="xs",
                    clearable=True,
                    leftSection=DashIconify(icon="mdi:shape", width=14),
                ),
                dmc.Slider(
                    id="point-size",
                    min=3,
                    max=20,
                    value=8,
                    step=1,
                    marks=[
                        {"value": 3, "label": "3"},
                        {"value": 10, "label": "10"},
                        {"value": 20, "label": "20"},
                    ],
                    size="sm",
                ),
                dmc.Text("Point size", size="xs", c="dimmed"),
                # ── PCA axes ───────────────────────────────
                dmc.Divider(label="Axes", labelPosition="center"),
                dmc.Group(
                    [
                        dmc.NumberInput(
                            id="pc-x",
                            label="X component",
                            value=1,
                            min=1,
                            max=10,
                            step=1,
                            size="xs",
                            w=100,
                        ),
                        dmc.NumberInput(
                            id="pc-y",
                            label="Y component",
                            value=2,
                            min=1,
                            max=10,
                            step=1,
                            size="xs",
                            w=100,
                        ),
                    ],
                ),
                # ── UMAP / t-SNE params ───────────────────
                dmc.Divider(label="Algorithm Parameters", labelPosition="center"),
                # Perplexity (t-SNE)
                dmc.NumberInput(
                    id="tsne-perplexity",
                    label="Perplexity (t-SNE)",
                    value=30,
                    min=5,
                    max=50,
                    step=5,
                    size="xs",
                ),
                # n_neighbors (UMAP)
                dmc.NumberInput(
                    id="umap-n-neighbors",
                    label="n_neighbors (UMAP)",
                    value=15,
                    min=2,
                    max=100,
                    step=1,
                    size="xs",
                ),
                dmc.NumberInput(
                    id="umap-min-dist",
                    label="min_dist (UMAP)",
                    value=0.1,
                    min=0.0,
                    max=1.0,
                    step=0.05,
                    size="xs",
                    decimalScale=2,
                ),
            ],
            gap="sm",
            p="md",
        ),
        type="auto",
    )


def _create_ag_grid() -> dag.AgGrid:
    """Sample metadata table."""
    return dag.AgGrid(
        id="sample-table",
        columnDefs=[],
        rowData=[],
        dashGridOptions={
            "pagination": True,
            "paginationPageSize": 20,
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
                                # Main scatter plot
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
                                # Bottom row: variance + loadings side by side
                                dmc.Grid(
                                    [
                                        dmc.GridCol(
                                            dmc.Paper(
                                                dcc.Graph(
                                                    id="variance-bar",
                                                    config={
                                                        "displayModeBar": False,
                                                        "responsive": True,
                                                    },
                                                    style={"height": "280px"},
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
                                                    id="loadings-bar",
                                                    config={
                                                        "displayModeBar": False,
                                                        "responsive": True,
                                                    },
                                                    style={"height": "280px"},
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
                                # Sample table
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
