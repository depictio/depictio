"""Layout for the Contrast Manager prototype.

DMC 2.0 AppShell with sidebar controls for contrast building and selection,
and main area with AG Grid table, MA plot, PCA mini-view, and contrast-vs-contrast scatter.
"""

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc
from dash_iconify import DashIconify
from data import CONDITIONS, CONTRASTS


def _condition_options() -> list[dict[str, str]]:
    """Condition options for MultiSelect dropdowns."""
    return [{"value": c, "label": c} for c in CONDITIONS]


def _contrast_options() -> list[dict[str, str]]:
    """Pre-defined contrast options for Select dropdowns."""
    return [{"value": c, "label": c} for c in CONTRASTS]


def _create_navbar_content() -> dmc.ScrollArea:
    """Build sidebar with contrast builder and selectors."""
    return dmc.ScrollArea(
        dmc.Stack(
            [
                dmc.Title("Contrast Manager", order=4),
                dmc.Text("Prototype v0.1", size="xs", c="dimmed"),
                # ── Contrast Builder ──────────────────────
                dmc.Divider(label="Contrast Builder", labelPosition="center"),
                dmc.MultiSelect(
                    id="numerator-select",
                    data=_condition_options(),
                    label="Numerator groups",
                    placeholder="Select numerator conditions",
                    size="xs",
                    leftSection=DashIconify(icon="mdi:plus-circle-outline", width=14),
                ),
                dmc.Text(id="numerator-count", size="xs", c="dimmed"),
                dmc.MultiSelect(
                    id="denominator-select",
                    data=_condition_options(),
                    label="Denominator groups",
                    placeholder="Select denominator conditions",
                    size="xs",
                    leftSection=DashIconify(icon="mdi:minus-circle-outline", width=14),
                ),
                dmc.Text(id="denominator-count", size="xs", c="dimmed"),
                dmc.Button(
                    "Add Contrast",
                    id="add-contrast-btn",
                    size="xs",
                    variant="filled",
                    fullWidth=True,
                    leftSection=DashIconify(icon="mdi:plus", width=14),
                ),
                # ── Active Contrast ───────────────────────
                dmc.Divider(label="Active Contrast", labelPosition="center"),
                dmc.Select(
                    id="active-contrast-select",
                    data=_contrast_options(),
                    value=CONTRASTS[0],
                    label="Select contrast (MA + PCA)",
                    size="xs",
                    leftSection=DashIconify(icon="mdi:chart-scatter-plot", width=14),
                ),
                # ── Contrast Pair ─────────────────────────
                dmc.Divider(label="Contrast Pair", labelPosition="center"),
                dmc.Select(
                    id="contrast-a-select",
                    data=_contrast_options(),
                    value=CONTRASTS[0],
                    label="Contrast A (x-axis)",
                    size="xs",
                ),
                dmc.Select(
                    id="contrast-b-select",
                    data=_contrast_options(),
                    value=CONTRASTS[1],
                    label="Contrast B (y-axis)",
                    size="xs",
                ),
            ],
            gap="sm",
            p="md",
        ),
        type="auto",
    )


def _create_contrast_table() -> dag.AgGrid:
    """Contrast summary table."""
    return dag.AgGrid(
        id="contrast-table",
        columnDefs=[
            {"field": "name", "headerName": "Contrast"},
            {"field": "numerator", "headerName": "Numerator"},
            {"field": "denominator", "headerName": "Denominator"},
            {"field": "n_samples_num", "headerName": "N (num)", "maxWidth": 100},
            {"field": "n_samples_den", "headerName": "N (den)", "maxWidth": 100},
            {"field": "n_sig_genes", "headerName": "Sig. Genes", "maxWidth": 110},
            {
                "field": "balance_warning",
                "headerName": "Imbalanced",
                "maxWidth": 110,
                "cellDataType": "boolean",
            },
        ],
        rowData=[],
        dashGridOptions={
            "pagination": False,
            "rowSelection": "single",
            "enableCellTextSelection": True,
            "animateRows": False,
            "domLayout": "autoHeight",
        },
        defaultColDef={
            "flex": 1,
            "minWidth": 80,
            "sortable": True,
            "resizable": True,
            "filter": True,
        },
        style={"height": "250px"},
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
                                # Contrast table
                                dmc.Paper(
                                    _create_contrast_table(),
                                    p="xs",
                                    radius="sm",
                                    withBorder=True,
                                ),
                                # MA plot + PCA mini-view
                                dmc.Grid(
                                    [
                                        dmc.GridCol(
                                            dmc.Paper(
                                                dcc.Graph(
                                                    id="ma-plot",
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
                                            span=6,
                                        ),
                                        dmc.GridCol(
                                            dmc.Paper(
                                                dcc.Graph(
                                                    id="pca-mini",
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
                                            span=6,
                                        ),
                                    ],
                                    gutter="md",
                                ),
                                # Contrast-vs-contrast scatter
                                dmc.Paper(
                                    dcc.Graph(
                                        id="contrast-scatter",
                                        config={
                                            "displayModeBar": "hover",
                                            "responsive": True,
                                        },
                                        style={"height": "450px"},
                                    ),
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
