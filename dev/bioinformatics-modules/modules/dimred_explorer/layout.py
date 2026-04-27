"""Layout for the DimRed Explorer module.

Provides PCA / UMAP / t-SNE scatter, variance explained bar, loadings bar,
summary badges, and a sample data table.  All component IDs are prefixed
with ``dr-`` to avoid collisions with other modules.

The outer wrapper is a ``dmc.Paper`` (not a full AppShell) so it can be
composed inside the demo app's shell.
"""

import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc
from dash_iconify import DashIconify

# ── Metadata helpers ──────────────────────────────────────────────────────

METADATA_COLS: list[str] = ["condition", "batch", "cell_type"]

COLUMN_LABELS: dict[str, str] = {
    "condition": "Condition",
    "batch": "Batch",
    "cell_type": "Cell Type",
    "sample_id": "Sample ID",
}


def _meta_options() -> list[dict[str, str]]:
    """Metadata column options for Select dropdowns."""
    return [{"value": c, "label": COLUMN_LABELS.get(c, c)} for c in METADATA_COLS]


# ── Sidebar ───────────────────────────────────────────────────────────────


def _create_sidebar() -> dmc.ScrollArea:
    """Build sidebar with all controls."""
    return dmc.ScrollArea(
        dmc.Stack(
            [
                dmc.Title("Dim. Reduction Explorer", order=4),
                dmc.Text("Module v1.0", size="xs", c="dimmed"),
                # ── Summary badges ─────────────────────────
                dmc.Group(
                    [
                        dmc.Badge(
                            id="dr-badge-samples",
                            children="0 samples",
                            variant="light",
                            size="sm",
                        ),
                        dmc.Badge(
                            id="dr-badge-genes",
                            children="0 genes",
                            variant="light",
                            size="sm",
                        ),
                    ],
                    gap="xs",
                ),
                dmc.Group(
                    [
                        dmc.Badge(
                            id="dr-badge-method",
                            children="PCA",
                            variant="outline",
                            size="sm",
                        ),
                        dmc.Badge(
                            id="dr-badge-variance",
                            children="--",
                            variant="outline",
                            size="sm",
                        ),
                    ],
                    gap="xs",
                ),
                # ── Method ─────────────────────────────────
                dmc.Divider(label="Method", labelPosition="center"),
                dmc.SegmentedControl(
                    id="dr-method-select",
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
                    id="dr-n-top-genes",
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
                    id="dr-color-by",
                    data=_meta_options(),
                    value="condition",
                    label="Color by",
                    size="xs",
                    leftSection=DashIconify(icon="mdi:palette", width=14),
                ),
                dmc.Select(
                    id="dr-symbol-by",
                    data=[{"value": "", "label": "None"}] + _meta_options(),
                    value="batch",
                    label="Symbol by",
                    size="xs",
                    clearable=True,
                    leftSection=DashIconify(icon="mdi:shape", width=14),
                ),
                dmc.Slider(
                    id="dr-point-size",
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
                            id="dr-pc-x",
                            label="X component",
                            value=1,
                            min=1,
                            max=10,
                            step=1,
                            size="xs",
                            w=100,
                        ),
                        dmc.NumberInput(
                            id="dr-pc-y",
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
                dmc.NumberInput(
                    id="dr-tsne-perplexity",
                    label="Perplexity (t-SNE)",
                    value=30,
                    min=5,
                    max=50,
                    step=5,
                    size="xs",
                ),
                dmc.NumberInput(
                    id="dr-umap-n-neighbors",
                    label="n_neighbors (UMAP)",
                    value=15,
                    min=2,
                    max=100,
                    step=1,
                    size="xs",
                ),
                dmc.NumberInput(
                    id="dr-umap-min-dist",
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


# ── AG Grid ──────────────────────────────────────────────────────────────


def _create_ag_grid() -> dag.AgGrid:
    """Sample metadata table."""
    return dag.AgGrid(
        id="dr-sample-table",
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


# ── Public entry point ───────────────────────────────────────────────────


def create_layout(data: dict) -> dmc.Paper:
    """Build the DimRed Explorer module layout.

    Parameters
    ----------
    data:
        The dict returned by ``shared_data.load_all_data()``.  Used here only
        to set initial badge values; the callbacks update them dynamically.

    Returns
    -------
    dmc.Paper
        Module wrapped in a Paper component, ready to compose in the demo app.
    """
    sidebar = _create_sidebar()

    main_area = dmc.Stack(
        [
            # Main scatter plot
            dmc.Paper(
                dcc.Graph(
                    id="dr-main-scatter",
                    config={"displayModeBar": "hover", "responsive": True},
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
                                id="dr-variance-bar",
                                config={"displayModeBar": False, "responsive": True},
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
                                id="dr-loadings-bar",
                                config={"displayModeBar": False, "responsive": True},
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
    )

    # Use initial data to seed badge text (callbacks will overwrite)
    # We set the initial children via the sidebar badge IDs in the callback.

    return dmc.Paper(
        dmc.Grid(
            [
                dmc.GridCol(sidebar, span=3),
                dmc.GridCol(main_area, span=9),
            ],
            gutter="md",
        ),
        p="md",
        radius="sm",
        withBorder=True,
    )
