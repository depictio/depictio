"""Layout for the Contrast Manager module.

Sidebar controls for contrast building and selection, main area with AG Grid
table, MA plot, PCA mini-view, and contrast-vs-contrast scatter.

All component IDs are prefixed with ``cm-`` to avoid conflicts with other modules.
"""

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc
from dash_iconify import DashIconify



def _get_conditions(data: dict) -> list[str]:
    """Extract unique conditions from metadata."""
    return sorted(data["metadata_df"]["condition"].unique().tolist())


def _get_contrasts(data: dict) -> list[str]:
    """Extract available contrast names from DE results."""
    return sorted(data["de_results"].keys())


def _condition_options(data: dict) -> list[dict[str, str]]:
    return [{"value": c, "label": c} for c in _get_conditions(data)]


def _contrast_options(data: dict) -> list[dict[str, str]]:
    return [{"value": c, "label": c} for c in _get_contrasts(data)]


def _create_sidebar(data: dict) -> dmc.ScrollArea:
    """Build sidebar with contrast builder and selectors."""
    contrasts = _get_contrasts(data)
    default_contrast = contrasts[0] if contrasts else None

    return dmc.ScrollArea(
        dmc.Stack(
            [
                dmc.Title("Contrast Manager", order=4),
                dmc.Text("Module v1.0", size="xs", c="dimmed"),
                # ── Summary badges ─────────────────────────
                dmc.Group(
                    [
                        dmc.Badge(
                            f"{len(contrasts)} contrasts",
                            variant="light",
                            size="sm",
                            id="cm-badge-contrasts",
                        ),
                        dmc.Badge(
                            id="cm-badge-sig-genes",
                            variant="light",
                            color="red",
                            size="sm",
                            children="0 sig. genes",
                        ),
                        dmc.Badge(
                            id="cm-badge-samples",
                            variant="light",
                            color="teal",
                            size="sm",
                            children=f"{len(data['metadata_df'])} samples",
                        ),
                    ],
                    gap="xs",
                ),
                # ── Contrast Builder ──────────────────────
                dmc.Divider(label="Contrast Builder", labelPosition="center"),
                dmc.MultiSelect(
                    id="cm-numerator-select",
                    data=_condition_options(data),
                    label="Numerator groups",
                    placeholder="Select numerator conditions",
                    size="xs",
                    leftSection=DashIconify(icon="mdi:plus-circle-outline", width=14),
                ),
                dmc.Text(id="cm-numerator-count", size="xs", c="dimmed"),
                dmc.MultiSelect(
                    id="cm-denominator-select",
                    data=_condition_options(data),
                    label="Denominator groups",
                    placeholder="Select denominator conditions",
                    size="xs",
                    leftSection=DashIconify(icon="mdi:minus-circle-outline", width=14),
                ),
                dmc.Text(id="cm-denominator-count", size="xs", c="dimmed"),
                dmc.Button(
                    "Add Contrast",
                    id="cm-add-contrast-btn",
                    size="xs",
                    variant="filled",
                    fullWidth=True,
                    leftSection=DashIconify(icon="mdi:plus", width=14),
                ),
                # ── Active Contrast ───────────────────────
                dmc.Divider(label="Active Contrast", labelPosition="center"),
                dmc.Select(
                    id="cm-active-contrast-select",
                    data=_contrast_options(data),
                    value=default_contrast,
                    label="Select contrast (MA + PCA)",
                    size="xs",
                    leftSection=DashIconify(icon="mdi:chart-scatter-plot", width=14),
                ),
                # ── Contrast Pair ─────────────────────────
                dmc.Divider(label="Contrast Pair", labelPosition="center"),
                dmc.Select(
                    id="cm-contrast-a-select",
                    data=_contrast_options(data),
                    value=contrasts[0] if len(contrasts) > 0 else None,
                    label="Contrast A (x-axis)",
                    size="xs",
                ),
                dmc.Select(
                    id="cm-contrast-b-select",
                    data=_contrast_options(data),
                    value=contrasts[1] if len(contrasts) > 1 else None,
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
    """Contrast summary AG Grid table."""
    return dag.AgGrid(
        id="cm-contrast-table",
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


def create_layout(data: dict) -> dmc.Paper:
    """Create the Contrast Manager module layout.

    Parameters
    ----------
    data : dict
        Data dict from ``shared_data.load_all_data()``.

    Returns
    -------
    dmc.Paper
        The module wrapped in a Paper component (no AppShell).
    """
    return dmc.Paper(
        dmc.Grid(
            [
                # Sidebar column
                dmc.GridCol(
                    _create_sidebar(data),
                    span=3,
                ),
                # Main content column
                dmc.GridCol(
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
                                                id="cm-ma-plot",
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
                                                id="cm-pca-mini",
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
                                    id="cm-contrast-scatter",
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
