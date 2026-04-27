"""Layout for the Variant Inspector module.

DMC 2.0 Paper wrapper with sidebar controls (sample, thresholds, filters,
summary badges) and main area with quadrant scatter, filter funnel,
cross-sample heatmap, and AG Grid.

All component IDs are prefixed with ``vi-`` to avoid conflicts with other modules.
"""

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc

# Gene regions from shared_data
GENE_REGIONS: list[dict] = [
    {"gene": "ORF1a", "start": 266, "end": 13468},
    {"gene": "ORF1b", "start": 13468, "end": 21555},
    {"gene": "S", "start": 21563, "end": 25384},
    {"gene": "ORF3a", "start": 25393, "end": 26220},
    {"gene": "E", "start": 26245, "end": 26472},
    {"gene": "M", "start": 26523, "end": 27191},
    {"gene": "ORF7a", "start": 27394, "end": 27759},
    {"gene": "N", "start": 28274, "end": 29533},
]

SAMPLES: list[str] = [
    "WW_Site1_W01",
    "WW_Site1_W02",
    "WW_Site1_W03",
    "WW_Site1_W04",
    "WW_Site2_W01",
    "WW_Site2_W02",
    "WW_Site2_W03",
    "WW_Site2_W04",
]


def _create_sidebar_content() -> dmc.ScrollArea:
    """Build sidebar with variant filtering controls and summary badges."""
    return dmc.ScrollArea(
        dmc.Stack(
            [
                dmc.Title("Variant Inspector", order=4),
                dmc.Text("Quadrant Analysis Module", size="xs", c="dimmed"),
                # -- Sample selector -------------------------------------------
                dmc.Divider(label="Sample", labelPosition="center"),
                dmc.Select(
                    id="vi-sample-selector",
                    label="Active sample",
                    data=[{"value": s, "label": s} for s in SAMPLES],
                    value=SAMPLES[0],
                    size="sm",
                ),
                # -- Threshold sliders -----------------------------------------
                dmc.Divider(label="Thresholds", labelPosition="center"),
                dmc.Text("AF Threshold", size="xs", fw=500),
                dmc.Slider(
                    id="vi-af-threshold-slider",
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
                    id="vi-qual-threshold-slider",
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
                    id="vi-depth-threshold-input",
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
                    id="vi-effect-filter",
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
                    id="vi-gene-filter",
                    label="Gene region",
                    data=[{"value": "all", "label": "All genes"}]
                    + [{"value": str(r["gene"]), "label": str(r["gene"])} for r in GENE_REGIONS],
                    value="all",
                    size="sm",
                ),
                # -- Summary badges --------------------------------------------
                dmc.Divider(label="Summary", labelPosition="center"),
                dmc.Stack(id="vi-sidebar-summary", gap="xs"),
            ],
            gap="sm",
            p="md",
        ),
        type="auto",
    )


def _create_variant_table() -> dag.AgGrid:
    """Create the variant data table."""
    return dag.AgGrid(
        id="vi-variant-table",
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


def create_layout(data: dict) -> dmc.Paper:
    """Create the Variant Inspector module layout.

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
                            dmc.Group(id="vi-summary-badges", gap="sm"),
                            # Row 1: Quadrant scatter (span 8) + Filter funnel (span 4)
                            dmc.Grid(
                                [
                                    dmc.GridCol(
                                        dmc.Paper(
                                            dmc.Stack(
                                                [
                                                    dmc.Group(
                                                        id="vi-quadrant-badges",
                                                        gap="xs",
                                                        justify="center",
                                                    ),
                                                    dcc.Graph(
                                                        id="vi-quadrant-scatter",
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
                                                id="vi-filter-funnel",
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
                                    id="vi-sharing-heatmap",
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
                    span=9,
                ),
            ],
            gutter="md",
        ),
        p="md",
        radius="sm",
        withBorder=True,
    )
