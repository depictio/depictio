"""Layout for the Peak Explorer prototype.

DMC 2.0 AppShell with sidebar for peak filtering controls and main area for
annotation distribution, peak width histogram, FRiP bar chart, consensus
heatmap, and peak table.
"""

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

ANNOTATION_CATEGORIES = [
    "Promoter", "5' UTR", "3' UTR", "Exon", "Intron", "Intergenic", "TTS",
]


def _create_navbar_content() -> dmc.ScrollArea:
    """Build sidebar with peak filtering controls."""
    return dmc.ScrollArea(
        dmc.Stack(
            [
                dmc.Title("Peak Explorer", order=4),
                dmc.Text("ChIP-seq / ATAC-seq / CUT&RUN", size="xs", c="dimmed"),
                dmc.Divider(label="Filters", labelPosition="center"),
                dmc.NumberInput(
                    id="min-score-input",
                    label="Min peak score",
                    value=50,
                    min=0,
                    max=1000,
                    step=10,
                    size="sm",
                ),
                dmc.NumberInput(
                    id="min-fold-input",
                    label="Min fold enrichment",
                    value=2.0,
                    min=0,
                    max=50,
                    step=0.5,
                    decimalScale=1,
                    size="sm",
                ),
                dmc.MultiSelect(
                    id="annotation-filter",
                    label="Annotation categories",
                    data=[{"value": a, "label": a} for a in ANNOTATION_CATEGORIES],
                    value=ANNOTATION_CATEGORIES,
                    size="sm",
                    placeholder="Select annotations...",
                ),
                dmc.Divider(label="Consensus", labelPosition="center"),
                dmc.NumberInput(
                    id="min-samples-input",
                    label="Min samples with peak",
                    value=1,
                    min=1,
                    max=6,
                    step=1,
                    size="sm",
                ),
                dmc.Divider(label="Summary", labelPosition="center"),
                dmc.Stack(
                    id="summary-stats",
                    gap="xs",
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
        id="peak-table",
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
                                # Row 1: Annotation pie + Peak width histogram
                                dmc.Grid(
                                    [
                                        dmc.GridCol(
                                            dmc.Paper(
                                                dcc.Graph(
                                                    id="annotation-chart",
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
                                                    id="width-histogram",
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
                                # Row 2: FRiP bar chart + Consensus heatmap
                                dmc.Grid(
                                    [
                                        dmc.GridCol(
                                            dmc.Paper(
                                                dcc.Graph(
                                                    id="frip-chart",
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
                                                    id="consensus-heatmap",
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
                        fluid=True,
                    ),
                ),
            ],
            navbar={"width": 300, "breakpoint": "sm"},
            padding="md",
        ),
        forceColorScheme="light",
    )
